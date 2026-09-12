"""Parquet/CSV/JSON 读写（规格 §10、§6.3：允许 PyArrow）。

- Parquet 默认 ZSTD 压缩；
- 列名小写 snake_case（调用方保证）；
- 时间戳 UTC；
- 支持 PyArrow 谓词下推（filters 参数），减少 I/O 和内存占用。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

try:
    import pyarrow as pa
    import pyarrow.compute as pc
    import pyarrow.csv as pa_csv
    import pyarrow.json as pa_json
    import pyarrow.parquet as pq
except ImportError:  # pragma: no cover
    pa = pc = pa_csv = pa_json = pq = None

from ..domain.errors import UsageError


# ---------------- 谓词下推过滤器构建 ----------------

# 支持的比较操作符
_FILTER_OPS = frozenset({"eq", "ne", "gt", "gte", "lt", "lte", "in", "not_in", "contains"})


def build_filter(
    conditions: dict[str, Any] | list[dict],
) -> "pc.Expression | None":
    """将条件字典/列表转为 PyArrow 过滤表达式（谓词下推）。

    简单模式（dict）：键为列名，值为等值匹配目标。
        build_filter({"entity_id": "ENT-001", "status": "ACTIVE"})
        → (field("entity_id") == "ENT-001") & (field("status") == "ACTIVE")

    高级模式（list of dict）：每个元素含 column / op / value。
        build_filter([
            {"column": "rate", "op": "gte", "value": 3.0},
            {"column": "entity_type", "op": "in", "value": ["PRODUCT", "CUSTOMER"]},
            {"column": "name", "op": "contains", "value": "产品"},
        ])
        → (field("rate") >= 3.0) & field("entity_type").isin(["PRODUCT","CUSTOMER"])
              & pc.match_substring(field("name"), "产品")

    支持操作：eq, ne, gt, gte, lt, lte, in, not_in, contains
    返回 None 表示无条件（全量读取）。
    """
    if pa is None:  # pragma: no cover
        return None
    if not conditions:
        return None

    # 简单模式：dict → 全部 eq
    if isinstance(conditions, dict):
        if not conditions:
            return None
        exprs = []
        for col, val in conditions.items():
            exprs.append(pc.field(col) == val)
        return exprs[0] if len(exprs) == 1 else _and_all(exprs)

    # 高级模式：list of {column, op, value}
    if isinstance(conditions, list):
        if not conditions:
            return None
        exprs = []
        for cond in conditions:
            col = cond["column"]
            op = cond.get("op", "eq")
            val = cond["value"]
            if op not in _FILTER_OPS:
                raise UsageError(f"不支持的过滤器操作: {op!r}，可选: {sorted(_FILTER_OPS)}")
            exprs.append(_build_comparison(col, op, val))
        return exprs[0] if len(exprs) == 1 else _and_all(exprs)

    return None


def _build_comparison(col: str, op: str, val: Any) -> "pc.Expression":
    """构建单个比较表达式。"""
    field = pc.field(col)
    if op == "eq":
        return field == val
    if op == "ne":
        return field != val
    if op == "gt":
        return field > val
    if op == "gte":
        return field >= val
    if op == "lt":
        return field < val
    if op == "lte":
        return field <= val
    if op == "in":
        return field.isin(val if isinstance(val, (list, set, tuple)) else [val])
    if op == "not_in":
        return ~field.isin(val if isinstance(val, (list, set, tuple)) else [val])
    if op == "contains":
        return pc.match_substring(field, val)
    raise UsageError(f"不支持的过滤器操作: {op!r}")  # pragma: no cover


def _and_all(exprs: list["pc.Expression"]) -> "pc.Expression":
    """将多个表达式用 AND 连接。"""
    result = exprs[0]
    for e in exprs[1:]:
        result = result & e
    return result


# ---------------- 读写接口 ----------------

def read_table(path: Path, *, filters: dict | list | None = None) -> "pa.Table":
    """按扩展名读取 CSV/JSON/JSONL/Parquet，支持谓词下推。

    filters: 传给 build_filter 的条件，仅 Parquet 格式生效。
             不传或 None 时行为与原版完全一致（向后兼容）。
    """
    if pa is None:  # pragma: no cover
        raise RuntimeError("pyarrow 未安装")
    ext = path.suffix.lower()
    if ext == ".parquet":
        filter_expr = build_filter(filters) if filters else None
        return pq.read_table(path, filters=filter_expr)
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


def read_parquet(path: Path, *, filters: dict | list | None = None) -> "pa.Table":
    """读取 Parquet 文件，支持谓词下推。"""
    if pa is None:  # pragma: no cover
        raise RuntimeError("pyarrow 未安装")
    filter_expr = build_filter(filters) if filters else None
    return pq.read_table(path, filters=filter_expr)


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
