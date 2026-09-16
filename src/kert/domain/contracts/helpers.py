"""合同交叉字段校验公共辅助函数（规格 §9 各节）。"""

from __future__ import annotations

import re
from typing import Any

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def sha256_ok(value: Any) -> bool:
    return isinstance(value, str) and bool(_SHA256_RE.match(value))


def check_effective_range(fm: dict) -> list[str]:
    """effective_from <= effective_to（若均存在）。"""
    errors: list[str] = []
    f, t = fm.get("effective_from"), fm.get("effective_to")
    if f and t and str(f) > str(t):
        errors.append(f"时间区间非法: effective_from({f}) > effective_to({t})")
    return errors


def check_positive_int(value: Any, fm: dict) -> list[str]:
    return [] if (isinstance(value, int) and not isinstance(value, bool) and value >= 1) else ["必须为 >=1 的整数"]


def check_nonneg_int(value: Any, fm: dict) -> list[str]:
    return [] if (isinstance(value, int) and not isinstance(value, bool) and value >= 0) else ["必须为 >=0 的整数"]


def check_confidence(value: Any, fm: dict) -> list[str]:
    if value is None:
        return []
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return ["置信度必须为 0..1 的数字"]
    return [] if 0.0 <= float(value) <= 1.0 else ["置信度必须为 0..1 的数字"]


def check_list_nonempty(value: Any, fm: dict) -> list[str]:
    return [] if (isinstance(value, list) and len(value) >= 1) else ["列表至少包含 1 个元素"]


def check_list_at_least(value: Any, fm: dict, n: int) -> list[str]:
    return [] if (isinstance(value, list) and len(value) >= n) else [f"列表至少包含 {n} 个元素"]


def check_sha256_field(value: Any, fm: dict) -> list[str]:
    return [] if sha256_ok(value) else ["必须为 64 位小写十六进制 SHA-256"]
