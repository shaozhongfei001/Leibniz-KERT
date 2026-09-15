"""解析/抽取适配器（规格 §6.3：接口隔离、可替换）。"""

from . import base, pdf_parser, text_parser  # noqa: F401

__all__ = ["base", "pdf_parser", "text_parser"]
