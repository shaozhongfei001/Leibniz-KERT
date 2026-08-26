"""TXT/Markdown 文本解析适配器（确定性、无外部依赖）。"""

from __future__ import annotations

from pathlib import Path

from .base import DocumentParserAdapter, Page, ParsedDocument


class TextParserAdapter(DocumentParserAdapter):
    parser_id = "text_parser"
    parser_version = "1.0.0"

    def parse(self, path: Path) -> ParsedDocument:
        text = path.read_text(encoding="utf-8")
        title = path.stem
        return ParsedDocument(title=title, pages=[Page(number=1, text=text)],
                              parser_id=self.parser_id,
                              parser_version=self.parser_version)


class CsvTextParserAdapter(DocumentParserAdapter):
    """CSV 文件作为文档解析（表格化呈现），用于无 DOCUMENT 字段的场景。"""

    parser_id = "csv_parser"
    parser_version = "1.0.0"

    def parse(self, path: Path) -> ParsedDocument:
        import csv
        import io

        rows = []
        with open(path, "r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            for row in reader:
                rows.append(row)
        table = "\n".join("| " + " | ".join(cell for cell in row) + " |" for row in rows)
        return ParsedDocument(
            title=path.stem,
            pages=[Page(number=1, text="", tables=[rows])],
            parser_id=self.parser_id, parser_version=self.parser_version,
            warnings=[f"CSV 作为表格解析：{len(rows)} 行"],
        )
