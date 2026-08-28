"""timeutil 模块单元测试：RFC 3339 时间戳、业务日期。"""

from __future__ import annotations

import datetime as _dt

import pytest

from dkws.domain.errors import UsageError
from dkws.domain.timeutil import (
    now_utc,
    parse_business_date,
    parse_ts,
    today_business,
    ts_utc,
)


# ---------- now_utc ----------

class TestNowUtc:
    def test_returns_aware(self):
        n = now_utc()
        assert n.tzinfo is not None

    def test_utc_timezone(self):
        n = now_utc()
        assert n.tzinfo == _dt.timezone.utc


# ---------- ts_utc ----------

class TestTsUtc:
    def test_explicit_dt(self):
        dt = _dt.datetime(2026, 8, 19, 12, 30, 0, tzinfo=_dt.timezone.utc)
        assert ts_utc(dt) == "2026-08-19T12:30:00Z"

    def test_naive_dt_treated_as_utc(self):
        dt = _dt.datetime(2026, 8, 19, 12, 30, 0)
        result = ts_utc(dt)
        assert result == "2026-08-19T12:30:00Z"

    def test_default_uses_now(self):
        result = ts_utc()
        assert result.endswith("Z")
        assert "T" in result


# ---------- parse_ts ----------

class TestParseTs:
    def test_valid_z(self):
        dt = parse_ts("2026-08-19T12:30:00Z")
        assert dt.year == 2026
        assert dt.month == 8
        assert dt.day == 19

    def test_valid_offset(self):
        dt = parse_ts("2026-08-19T20:30:00+08:00")
        assert dt.hour == 12  # converted to UTC

    def test_invalid_format(self):
        with pytest.raises(UsageError, match="非法时间戳"):
            parse_ts("2026-08-19")

    def test_non_string(self):
        with pytest.raises(UsageError, match="非法时间戳"):
            parse_ts(12345)

    def test_empty_string(self):
        with pytest.raises(UsageError, match="非法时间戳"):
            parse_ts("")

    def test_with_fractional_seconds(self):
        dt = parse_ts("2026-08-19T12:30:00.123456Z")
        assert dt.year == 2026


# ---------- parse_business_date ----------

class TestParseBusinessDate:
    def test_valid(self):
        d = parse_business_date("2026-08-19")
        assert d == _dt.date(2026, 8, 19)

    def test_invalid_format(self):
        with pytest.raises(UsageError, match="非法业务日期"):
            parse_business_date("08/19/2026")

    def test_non_string(self):
        with pytest.raises(UsageError, match="业务日期必须是字符串"):
            parse_business_date(12345)

    def test_invalid_date(self):
        with pytest.raises(UsageError, match="非法业务日期"):
            parse_business_date("2026-13-01")


# ---------- today_business ----------

class TestTodayBusiness:
    def test_format(self):
        result = today_business()
        # YYYY-MM-DD
        parts = result.split("-")
        assert len(parts) == 3
        assert len(parts[0]) == 4
