"""时间规范：RFC 3339 UTC（规格 §8.3）。"""

from __future__ import annotations

import datetime as _dt
import re

from .errors import UsageError

_RFC3339_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$"
)


def now_utc() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


def ts_utc(dt: _dt.datetime | None = None) -> str:
    dt = dt or now_utc()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_dt.timezone.utc)
    return dt.astimezone(_dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_ts(value: str) -> _dt.datetime:
    if not isinstance(value, str) or not _RFC3339_RE.match(value):
        raise UsageError(f"非法时间戳: {value!r}（须为 RFC 3339 UTC）")
    try:
        dt = _dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise UsageError(f"非法时间戳: {value!r}") from exc
    if dt.tzinfo is None:
        raise UsageError(f"时间戳缺少时区: {value!r}")
    return dt.astimezone(_dt.timezone.utc)


def parse_business_date(value: str) -> _dt.date:
    if not isinstance(value, str):
        raise UsageError(f"业务日期必须是字符串: {value!r}")
    try:
        return _dt.date.fromisoformat(value)
    except ValueError as exc:
        raise UsageError(f"非法业务日期: {value!r}（须为 YYYY-MM-DD）") from exc


def today_business() -> str:
    return now_utc().date().isoformat()
