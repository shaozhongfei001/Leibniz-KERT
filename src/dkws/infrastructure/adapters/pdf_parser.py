"""PDF 安全解析适配器（pypdf，仅文本/版面提取，不执行脚本）。"""

from __future__ import annotations

from pathlib import Path

from .base import DocumentParserAdapter, Page, ParsedDocument


class PdfParserAdapter(DocumentParserAdapter):
    parser_id = "pdf_parser"
    parser_version = "1.0.0"

    def parse(self, path: Path) -> ParsedDocument:
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        if reader.is_encrypted:
            raise ValueError("加密 PDF 不支持解析（安全拒绝）")
        pages: list[Page] = []
        warnings: list[str] = []
        for i, page in enumerate(reader.pages, start=1):
            text = page.extract_text() or ""
            warnings.append(f"第 {i} 页可能存在版面噪声，仅提取文本层")
            pages.append(Page(number=i, text=text))
        title = (reader.metadata.title if reader.metadata else None) or path.stem
        return ParsedDocument(title=title, pages=pages,
                              parser_id=self.parser_id,
                              parser_version=self.parser_version,
                              warnings=warnings)


def parser_for(media_type: str, ext: str):
    if ext == ".pdf":
        return PdfParserAdapter()
    if ext == ".docx":
        from .docx_parser import DocxParserAdapter
        return DocxParserAdapter()
    if ext in (".txt", ".md", ".log"):
        from .text_parser import TextParserAdapter
        return TextParserAdapter()
    if ext in (".csv", ".json", ".jsonl"):
        from .text_parser import CsvTextParserAdapter
        return CsvTextParserAdapter()
    raise ValueError(f"无可用解析器: {ext} ({media_type})")
