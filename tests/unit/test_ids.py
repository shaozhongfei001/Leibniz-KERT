"""ids 模块单元测试：ID 生成、解析、校验。"""

from __future__ import annotations

import datetime as _dt

import pytest

from dkws.domain.errors import UsageError
from dkws.domain.ids import (
    new_id,
    new_job_id,
    new_run_id,
    next_release_version,
    release_version_for,
    validate_domain,
    validate_id,
    validate_release_version,
    validate_schema_name,
    validate_semver,
)


# ---------- validate_domain ----------

class TestValidateDomain:
    def test_valid(self):
        assert validate_domain("kyc") == "kyc"

    def test_valid_with_digits(self):
        assert validate_domain("rm_2026") == "rm_2026"

    def test_empty_raises(self):
        with pytest.raises(UsageError, match="非法业务域"):
            validate_domain("")

    def test_starts_digit_raises(self):
        with pytest.raises(UsageError, match="非法业务域"):
            validate_domain("1abc")

    def test_uppercase_raises(self):
        with pytest.raises(UsageError, match="非法业务域"):
            validate_domain("ABC")

    def test_too_long_raises(self):
        with pytest.raises(UsageError, match="非法业务域"):
            validate_domain("a" * 65)

    def test_non_string_raises(self):
        with pytest.raises(UsageError, match="非法业务域"):
            validate_domain(123)


# ---------- validate_id ----------

class TestValidateId:
    def test_valid(self):
        assert validate_id("BATCH-001") == "BATCH-001"

    def test_valid_underscore(self):
        assert validate_id("ASSET_001") == "ASSET_001"

    def test_custom_label(self):
        with pytest.raises(UsageError, match="非法资产ID"):
            validate_id("bad", label="资产ID")

    def test_too_short_raises(self):
        with pytest.raises(UsageError):
            validate_id("AB")

    def test_lowercase_raises(self):
        with pytest.raises(UsageError):
            validate_id("abc")

    def test_non_string_raises(self):
        with pytest.raises(UsageError):
            validate_id(None)


# ---------- validate_release_version ----------

class TestValidateReleaseVersion:
    def test_valid(self):
        assert validate_release_version("2026.08.19.1") == "2026.08.19.1"

    def test_invalid_format(self):
        with pytest.raises(UsageError, match="非法发布版本"):
            validate_release_version("1.0.0")

    def test_missing_seq(self):
        with pytest.raises(UsageError, match="非法发布版本"):
            validate_release_version("2026.08.19")


# ---------- next_release_version ----------

class TestNextReleaseVersion:
    def test_increment(self):
        assert next_release_version("2026.08.19.1") == "2026.08.19.2"

    def test_increment_large(self):
        assert next_release_version("2026.08.19.99") == "2026.08.19.100"

    def test_invalid_base_raises(self):
        with pytest.raises(UsageError):
            next_release_version("bad")


# ---------- release_version_for ----------

class TestReleaseVersionFor:
    def test_default_seq(self):
        dt = _dt.datetime(2026, 8, 19, tzinfo=_dt.timezone.utc)
        assert release_version_for(dt) == "2026.08.19.1"

    def test_custom_seq(self):
        dt = _dt.datetime(2026, 8, 19, tzinfo=_dt.timezone.utc)
        assert release_version_for(dt, seq=5) == "2026.08.19.5"


# ---------- new_id ----------

class TestNewId:
    def test_default(self):
        now = _dt.datetime(2026, 8, 19, tzinfo=_dt.timezone.utc)
        result = new_id("BATCH", now=now)
        assert result == "BATCH-20260819-001"

    def test_custom_seq(self):
        now = _dt.datetime(2026, 8, 19, tzinfo=_dt.timezone.utc)
        result = new_id("BATCH", now=now, seq=42)
        assert result == "BATCH-20260819-042"

    def test_auto_now(self):
        result = new_id("TEST")
        assert result.startswith("TEST-")
        # 日期部分 8 位
        parts = result.split("-")
        assert len(parts[1]) == 8


# ---------- new_job_id ----------

class TestNewJobId:
    def test_basic(self):
        now = _dt.datetime(2026, 8, 19, tzinfo=_dt.timezone.utc)
        result = new_job_id("parse", now=now)
        assert result == "JOB-PARSE-20260819-001"

    def test_hyphen_converted(self):
        now = _dt.datetime(2026, 8, 19, tzinfo=_dt.timezone.utc)
        result = new_job_id("pre-visit", now=now)
        assert result == "JOB-PRE_VISIT-20260819-001"


# ---------- new_run_id ----------

class TestNewRunId:
    def test_basic(self):
        now = _dt.datetime(2026, 8, 19, tzinfo=_dt.timezone.utc)
        result = new_run_id("skill", now=now)
        assert result == "RUN-SKILL-20260819-001"


# ---------- validate_schema_name ----------

class TestValidateSchemaName:
    def test_valid(self):
        assert validate_schema_name("customer/v1") == "customer/v1"

    def test_invalid_uppercase(self):
        with pytest.raises(UsageError, match="非法 schema 名"):
            validate_schema_name("Customer/v1")

    def test_invalid_no_version(self):
        with pytest.raises(UsageError, match="非法 schema 名"):
            validate_schema_name("customer")

    def test_invalid_starts_digit(self):
        with pytest.raises(UsageError, match="非法 schema 名"):
            validate_schema_name("1schema/v1")

    def test_non_string(self):
        with pytest.raises(UsageError, match="非法 schema 名"):
            validate_schema_name(123)


# ---------- validate_semver ----------

class TestValidateSemver:
    def test_valid_simple(self):
        assert validate_semver("1.0.0") == "1.0.0"

    def test_valid_prerelease(self):
        assert validate_semver("1.0.0-alpha.1") == "1.0.0-alpha.1"

    def test_valid_build(self):
        assert validate_semver("1.0.0+build.123") == "1.0.0+build.123"

    def test_valid_prerelease_and_build(self):
        assert validate_semver("1.0.0-beta.2+build.456") == "1.0.0-beta.2+build.456"

    def test_invalid_two_parts(self):
        with pytest.raises(UsageError, match="非法 SemVer"):
            validate_semver("1.0")

    def test_invalid_text(self):
        with pytest.raises(UsageError, match="非法 SemVer"):
            validate_semver("v1.0.0")

    def test_non_string(self):
        with pytest.raises(UsageError, match="非法 SemVer"):
            validate_semver(1.0)
