"""ID、业务域、版本规范（规格 §8.2、§8.3）。"""

from __future__ import annotations

import datetime as _dt
import re

from .errors import UsageError

DOMAIN_RE = re.compile(r"^[a-z][a-z0-9_]{1,63}$")
ID_RE = re.compile(r"^[A-Z][A-Z0-9_-]{2,127}$")
VERSION_RE = re.compile(r"^\d{4}\.\d{2}\.\d{2}\.\d+$")
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+(-[0-9A-Za-z.-]+)?(\+[0-9A-Za-z.-]+)?$")
SCHEMA_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*/v\d+$")


def validate_domain(domain: str) -> str:
    if not isinstance(domain, str) or not DOMAIN_RE.match(domain):
        raise UsageError(f"非法业务域: {domain!r}（须匹配 {DOMAIN_RE.pattern}）")
    return domain


def validate_id(asset_id: str, label: str = "ID") -> str:
    if not isinstance(asset_id, str) or not ID_RE.match(asset_id):
        raise UsageError(f"非法{label}: {asset_id!r}（须匹配 {ID_RE.pattern}）")
    return asset_id


def validate_release_version(version: str) -> str:
    if not isinstance(version, str) or not VERSION_RE.match(version):
        raise UsageError(f"非法发布版本: {version!r}（须匹配 YYYY.MM.DD.N）")
    return version


def next_release_version(base: str) -> str:
    validate_release_version(base)
    head, _, tail = base.rpartition(".")
    return f"{head}.{int(tail) + 1}"


def release_version_for(now: _dt.datetime, seq: int = 1) -> str:
    return now.strftime("%Y.%m.%d") + f".{seq}"


def new_id(prefix: str, now: _dt.datetime | None = None,
           seq: int | None = None) -> str:
    """生成形如 BATCH-20260819-001 的受控 ID。"""
    now = now or _dt.datetime.now(_dt.timezone.utc)
    seq = seq if seq is not None else 1
    return f"{prefix}-{now.strftime('%Y%m%d')}-{seq:03d}"


def new_job_id(job_type: str, now: _dt.datetime | None = None,
               seq: int | None = None) -> str:
    t = job_type.upper().replace("-", "_")
    return new_id(f"JOB-{t}", now=now, seq=seq)


def new_run_id(run_type: str, now: _dt.datetime | None = None,
               seq: int | None = None) -> str:
    t = run_type.upper().replace("-", "_")
    return new_id(f"RUN-{t}", now=now, seq=seq)


def validate_schema_name(schema: str) -> str:
    if not isinstance(schema, str) or not SCHEMA_NAME_RE.match(schema):
        raise UsageError(f"非法 schema 名: {schema!r}（须匹配 name/v<major>）")
    return schema


def validate_semver(version: str) -> str:
    if not isinstance(version, str) or not SEMVER_RE.match(version):
        raise UsageError(f"非法 SemVer: {version!r}")
    return version
