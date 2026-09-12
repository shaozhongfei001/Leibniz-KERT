"""文档解析适配器接口（规格 §6.3：适配器必须通过接口隔离，可替换）。

安全约束：解析器不得执行宏、脚本或外部引用（FR-ING-006、§16.1）。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Page:
    number: int
    text: str
    tables: list[list[list[str]]] = field(default_factory=list)


@dataclass
class ParsedDocument:
    title: str
    pages: list[Page]
    parser_id: str
    parser_version: str
    warnings: list[str] = field(default_factory=list)

    def full_text(self) -> str:
        parts = []
        for p in self.pages:
            parts.append(f"<!-- page:{p.number} -->\n{p.text}")
        return "\n\n".join(parts)


class DocumentParserAdapter(ABC):
    """安全文档解析适配器。实现必须：
    - 只读解析，不执行宏/脚本/外部资源；
    - 不静默混入推断内容（FR-DOC-004）；
    - 返回结构化页面文本。
    """

    parser_id: str = "base"
    parser_version: str = "0.0.0"

    @abstractmethod
    def parse(self, path: Path) -> ParsedDocument:
        """解析文档为结构化页面。"""
