"""DOCX 只读解析适配器（python-docx，不执行宏）。

安全：python-docx 只读 document.xml；宏/嵌入对象不执行（FR-ING-006）。
"""

from __future__ import annotations

from pathlib import Path

from .base import DocumentParserAdapter, Page, ParsedDocument


class DocxParserAdapter(DocumentParserAdapter):
    parser_id = "docx_parser"
    parser_version = "1.0.0"

    def parse(self, path: Path) -> ParsedDocument:
        from docx import Document

        doc = Document(path)
        blocks: list[str] = []
        tables: list[list[list[str]]] = []
        # 遍历 body 元素顺序（段落与表格交错保留）
        for child in doc.element.body.iterchildren():
            tag = child.tag.split("}")[-1]
            if tag == "p":
                text = "".join(node.text or "" for node in child.iter() if node.tag.endswith("}t"))
                if text.strip():
                    blocks.append(text)
            elif tag == "tbl":
                table: list[list[str]] = []
                for row in child.iter():
                    if row.tag.endswith("}tr"):
                        cells = []
                        for tc in row.iter():
                            if tc.tag.endswith("}tc"):
                                cells.append("".join(n.text or "" for n in tc.iter()
                                                     if n.tag.endswith("}t")).strip())
                        if cells:
                            table.append(cells)
                if table:
                    tables.append(table)
                    blocks.append("| " + " | ".join(table[0]) + " |")
                    for r in table[1:]:
                        blocks.append("| " + " | ".join(r) + " |")
        text = "\n\n".join(blocks)
        title = doc.core_properties.title or path.stem
        return ParsedDocument(
            title=title,
            pages=[Page(number=1, text=text, tables=tables)],
            parser_id=self.parser_id, parser_version=self.parser_version,
            warnings=["DOCX 无可靠分页信息，按单页处理"],
        )
