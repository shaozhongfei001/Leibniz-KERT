"""媒体类型检测与允许列表（规格 FR-ING-005、§16.1）。

- 用 magic bytes 检测实际媒体类型；
- 扩展名与 magic 不符视为伪装，拒绝或隔离；
- 限制单文件大小。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..domain.errors import UsageError

ALLOWED_EXTENSIONS = {
    ".csv", ".json", ".jsonl", ".parquet", ".pdf", ".docx", ".html", ".htm",
    ".txt", ".md", ".png", ".jpg", ".jpeg", ".gif", ".log",
}
DEFAULT_MAX_BYTES = 256 * 1024 * 1024  # 256 MiB

_MAGIC_CHECKS = [
    (b"PAR1", "application/vnd.apache.parquet"),
    (b"%PDF-", "application/pdf"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF8", "image/gif"),
    (b"PK\x03\x04", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
]

_EXT_TO_MIME = {
    ".csv": "text/csv",
    ".json": "application/json",
    ".jsonl": "application/x-ndjson",
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".html": "text/html",
    ".htm": "text/html",
    ".log": "text/plain",
    ".parquet": "application/vnd.apache.parquet",
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
}

TEXT_EXTS = {".csv", ".json", ".jsonl", ".txt", ".md", ".html", ".htm", ".log"}


@dataclass
class MediaInfo:
    mime: str
    detected_by: str  # magic / extension / sniff
    suspicious: bool = False


def _sniff_text(head: bytes) -> str | None:
    """文本类文件内容嗅探。"""
    head_text = head[:2048].decode("utf-8", errors="ignore").lower()
    if head_text.lstrip().startswith("<!doctype html") or "<html" in head_text[:200]:
        return "text/html"
    if head_text.lstrip().startswith("{") or head_text.lstrip().startswith("["):
        return "application/json"
    return None


def _looks_like_text(head: bytes) -> bool:
    if not head:
        return True
    if b"\x00" in head[:4096]:
        return False
    sample = head[:4096]
    printable = sum(1 for b in sample if b in (9, 10, 13) or 32 <= b <= 126)
    return printable / len(sample) > 0.95


def detect_media(path: Path) -> MediaInfo:
    ext = path.suffix.lower()
    with open(path, "rb") as f:
        head = f.read(64 * 1024)
    for magic, mime in _MAGIC_CHECKS:
        if head.startswith(magic):
            suspicious = ext in TEXT_EXTS  # 文本扩展名却含二进制 magic
            return MediaInfo(mime, "magic", suspicious)
    sniffed = _sniff_text(head)
    if sniffed:
        expected = _EXT_TO_MIME.get(ext)
        suspicious = ext not in TEXT_EXTS and expected != sniffed
        return MediaInfo(sniffed, "sniff", suspicious)
    mime = _EXT_TO_MIME.get(ext, "application/octet-stream")
    if ext not in TEXT_EXTS and _looks_like_text(head):
        # 二进制扩展名但内容是文本 → 伪装
        return MediaInfo(mime, "extension", True)
    return MediaInfo(mime, "extension", False)


def check_source_allowed(path: Path, *, max_bytes: int = DEFAULT_MAX_BYTES) -> MediaInfo:
    """校验扩展名、大小、媒体类型；返回检测结果，失败抛 UsageError。"""
    path = Path(path)
    if not path.is_file():
        raise UsageError(f"源文件不存在: {path}")
    ext = path.suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise UsageError(f"不允许的文件类型: {ext!r}（允许 {sorted(ALLOWED_EXTENSIONS)}）")
    size = path.stat().st_size
    if size > max_bytes:
        raise UsageError(f"文件超过大小限制: {size} 字节 > {max_bytes}")
    info = detect_media(path)
    if info.suspicious:
        raise UsageError(f"文件伪装被拒绝: {path.name} 扩展名 {ext} 与实际媒体类型 {info.mime} 不符")
    return info
