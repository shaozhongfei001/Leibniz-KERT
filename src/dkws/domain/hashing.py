"""哈希规范（规格 §8.4）：SHA-256、Markdown 语义规范化、Parquet 逻辑哈希。"""

from __future__ import annotations

import hashlib

try:
    import pyarrow as pa
    import pyarrow.parquet as pq
except ImportError:  # pragma: no cover
    pa = None
    pq = None


def sha256_hex(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def sha256_file(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def canonical_md_bytes(text: str) -> bytes:
    """Markdown 语义哈希规范化字节（§8.4）：
    UTF-8、LF、去除每行尾随空格、文件末尾单个换行。"""
    lines = []
    for line in text.split("\n"):
        lines.append(line.rstrip(" \t"))
    while lines and lines[-1] == "":
        lines.pop()
    normalized = "\n".join(lines) + "\n"
    return normalized.encode("utf-8")


def md_semantic_sha256(text: str) -> str:
    return sha256_hex(canonical_md_bytes(text))


def _norm_scalar(v):
    """规范化标量用于逻辑哈希：统一空值/时间/布尔表达。"""
    if v is None:
        return "\x00NULL\x00"
    if isinstance(v, bool):
        return "true" if v else "false"
    if hasattr(v, "isoformat"):  # date/datetime/time
        return v.isoformat()
    if isinstance(v, float):
        return repr(float(v))
    if isinstance(v, (list, tuple)):
        return "[" + ",".join(_norm_scalar(x) for x in v) + "]"
    if isinstance(v, dict):
        return "{" + ",".join(
            f"{k}={_norm_scalar(val)}" for k, val in sorted(v.items())
        ) + "}"
    return str(v)


def parquet_logical_hash(table, key_columns: list[str] | None = None,
                         sort_columns: list[str] | None = None) -> str:
    """Parquet 重建一致性比较：固定列序、固定行排序、统一空值/时间表达。

    §8.4：不直接依赖二进制字节一致，采用逻辑规范化哈希。
    """
    if pa is None:  # pragma: no cover
        raise RuntimeError("pyarrow 未安装")
    if sort_columns:
        table = table.sort_by([(c, "ascending") for c in sort_columns])
    elif key_columns:
        table = table.sort_by([(c, "ascending") for c in key_columns])
    cols = list(table.column_names)
    col_order = sorted(cols)
    h = hashlib.sha256()
    h.update(("|".join(col_order)).encode("utf-8"))
    for name in col_order:
        arr = table[name]
        values = arr.to_pylist()
        for v in values:
            h.update(_norm_scalar(v).encode("utf-8"))
            h.update(b"\x1f")
        h.update(b"\x1e")
    return h.hexdigest()


def table_fingerprint(table, key_columns: list[str] | None = None,
                      sort_columns: list[str] | None = None) -> dict:
    """返回 (row_count, hash) 摘要，供 G4 门禁比较。"""
    return {
        "row_count": table.num_rows,
        "logical_hash": parquet_logical_hash(table, key_columns, sort_columns),
    }
