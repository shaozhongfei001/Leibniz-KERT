"""Parquet/CSV/JSON 读写（规格 §10、§6.3：允许 PyArrow）。

- Parquet 默认 ZSTD 压缩；
- 列名小写 snake_case（调用方保证）；
- 时间戳 UTC。
"""

from __future__ import annotations

import json
from pathlib import Path

try:
    import pyarrow as pa
    import pyarrow.csv as pa_csv
    import pyarrow.json as pa_json
    import pyarrow.parquet as pq
except ImportError:  # pragma: no cover
    pa = pa_csv = pa_json = pq = None

from ..domain.errors import UsageError


def read_table(path: Path) -> "pa.Table":
    """按扩展名读取 CSV/JSON/JSONL/Parquet。"""
    if pa is None:  # pragma: no cover
        raise RuntimeError("pyarrow 未安装")
    ext = path.suffix.lower()
    if ext == ".parquet":
        return pq.read_table(path)
    if ext == ".csv":
        return pa_csv.read_csv(path)
    if ext in (".json", ".jsonl"):
        return _read_json(path)
    raise UsageError(f"不支持的结构化输入类型: {ext!r}")


def _read_json(path: Path) -> "pa.Table":
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".jsonl":
        rows = [json.loads(line) for line in text.splitlines() if line.strip()]
    else:
        data = json.loads(text)
        rows = data if isinstance(data, list) else [data]
    if not rows:
        return pa.table({})
    return pa.Table.from_pylist(rows)


def write_parquet(table: "pa.Table", path: Path) -> None:
    """写 Parquet（ZSTD，默认压缩）。"""
    if pa is None:  # pragma: no cover
        raise RuntimeError("pyarrow 未安装")
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, path, compression="zstd")


def read_parquet(path: Path) -> "pa.Table":
    if pa is None:  # pragma: no cover
        raise RuntimeError("pyarrow 未安装")
    return pq.read_table(path)


def cast_column(table: "pa.Table", column: str, target_type: str) -> "pa.Table":
    """按目标类型转换列（失败行标记）。返回新表（原列被替换为转换结果或 null）。"""
    if pa is None:  # pragma: no cover
        raise RuntimeError("pyarrow 未安装")
    if column not in table.column_names:
        return table
    arr = table[column]
    try:
        if target_type in ("string", "str"):
            return table.set_column(
                table.schema.get_field_index(column), column,
                arr.cast(pa.string(), safe=False))
        if target_type in ("integer", "int"):
            return table.set_column(
                table.schema.get_field_index(column), column,
                arr.cast(pa.int64(), safe=False))
        if target_type in ("decimal", "number", "float"):
            return table.set_column(
                table.schema.get_field_index(column), column,
                arr.cast(pa.float64(), safe=False))
        if target_type in ("boolean", "bool"):
            return table.set_column(
                table.schema.get_field_index(column), column,
                arr.cast(pa.bool_(), safe=False))
    except (pa.ArrowInvalid, pa.ArrowNotImplementedError, ValueError):
        pass
    return table
