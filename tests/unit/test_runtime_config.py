"""M2.1 运行时配置单元测试（认证边界与生产 profile fail-fast）。"""

from __future__ import annotations

import json

import pytest

from dkws.infrastructure.runtime_config import (
    PROFILE_DEV,
    PROFILE_PROD,
    SCOPE_ADMIN,
    ConfigError,
    RuntimeConfig,
    load_runtime_config,
    validate_runtime_config,
)

STRONG_KEY = "0123456789abcdef0123"
OTHER_KEY = "fedcba98765432100000"


def test_default_profile_is_dev_without_auth():
    """无任何环境变量时为 dev profile，认证默认关闭。"""
    cfg = load_runtime_config(env={})
    assert cfg.profile == PROFILE_DEV
    assert cfg.auth.enabled is False
    assert cfg.warnings == ()


def test_env_keys_enable_auth_implicitly():
    """仅提供 DKWS_API_KEYS 即隐式启用认证。"""
    cfg = load_runtime_config(env={"DKWS_API_KEYS": f"svc-a:{STRONG_KEY}"})
    assert cfg.auth.enabled is True
    assert len(cfg.auth.active_keys()) == 1
    assert cfg.auth.active_keys()[0].key_id == "svc-a"


def test_key_digest_not_plaintext():
    """配置中只保留摘要，不留明文密钥。"""
    cfg = load_runtime_config(env={"DKWS_API_KEYS": STRONG_KEY})
    record = cfg.auth.active_keys()[0]
    assert STRONG_KEY not in record.digest
    assert len(record.digest) == 64


def test_verify_matches_only_correct_key():
    """verify 仅接受正确密钥。"""
    cfg = load_runtime_config(env={"DKWS_API_KEYS": STRONG_KEY})
    assert cfg.auth.verify(STRONG_KEY) is not None
    assert cfg.auth.verify(OTHER_KEY) is None
    assert cfg.auth.verify("") is None


def test_scopes_parsed_from_spec():
    """支持 key_id:secret:scope1|scope2 声明作用域。"""
    cfg = load_runtime_config(
        env={"DKWS_API_KEYS": f"admin-key:{STRONG_KEY}:admin|read"})
    record = cfg.auth.verify(STRONG_KEY)
    assert record is not None
    assert record.has_scope(SCOPE_ADMIN)
    assert record.has_scope("read")
    assert not record.has_scope("execute")


def test_weak_key_rejected():
    """长度不足 16 的弱密钥被拒绝。"""
    with pytest.raises(ConfigError, match="长度不足"):
        load_runtime_config(env={"DKWS_API_KEYS": "short"})


def test_invalid_profile_rejected():
    """非法 profile 值直接报错。"""
    with pytest.raises(ConfigError, match="DKWS_PROFILE"):
        load_runtime_config(env={"DKWS_PROFILE": "staging"})


def test_prod_profile_without_auth_fails_fast():
    """生产 profile 未启用认证时 fail-fast。"""
    with pytest.raises(ConfigError, match="必须启用 API Key 认证"):
        load_runtime_config(env={"DKWS_PROFILE": "prod"})


def test_prod_profile_without_rate_limit_fails_fast():
    """生产 profile 未启用限流时 fail-fast。"""
    with pytest.raises(ConfigError, match="必须启用限流"):
        load_runtime_config(env={"DKWS_PROFILE": "prod",
                                 "DKWS_API_KEYS": STRONG_KEY})


def test_prod_profile_complete_config_passes():
    """生产 profile 齐备安全控制时通过校验。"""
    cfg = load_runtime_config(env={
        "DKWS_PROFILE": "prod",
        "DKWS_API_KEYS": f"svc:{STRONG_KEY}",
        "DKWS_RATE_LIMIT_ENABLED": "true",
        "DKWS_BIND_HOST": "0.0.0.0",
    })
    assert cfg.is_production
    assert cfg.listens_publicly()
    assert cfg.warnings == ()


def test_non_strict_mode_collects_warnings_instead_of_raising():
    """strict=False 时生产问题降级为 warnings（供诊断工具使用）。"""
    cfg = load_runtime_config(env={"DKWS_PROFILE": "prod"}, strict=False)
    assert cfg.is_production
    assert any("认证" in w for w in cfg.warnings)


def test_auth_enabled_without_keys_is_a_problem():
    """启用认证但无密钥属配置问题。"""
    cfg = RuntimeConfig(profile=PROFILE_DEV)
    problems = validate_runtime_config(cfg)
    assert problems == []
    cfg2 = load_runtime_config(env={"DKWS_AUTH_ENABLED": "true"}, strict=False)
    assert any("未配置任何有效 API Key" in w for w in cfg2.warnings)


def test_config_file_digest_form(tmp_path):
    """配置文件可只提供 digest，避免明文落盘。"""
    import hashlib

    digest = hashlib.sha256(STRONG_KEY.encode()).hexdigest()
    cfg_file = tmp_path / "runtime.json"
    cfg_file.write_text(json.dumps({
        "profile": "dev",
        "auth": {"enabled": True,
                 "keys": [{"key_id": "svc-x", "digest": digest, "scopes": ["read"]}]},
    }), encoding="utf-8")
    cfg = load_runtime_config(env={"DKWS_CONFIG_FILE": str(cfg_file)})
    assert cfg.auth.verify(STRONG_KEY).key_id == "svc-x"


def test_config_file_missing_raises(tmp_path):
    """DKWS_CONFIG_FILE 指向不存在文件时报错。"""
    with pytest.raises(ConfigError, match="不存在"):
        load_runtime_config(env={"DKWS_CONFIG_FILE": str(tmp_path / "nope.json")})


def test_inactive_key_not_accepted(tmp_path):
    """active=false 的密钥被视为已吊销。"""
    cfg_file = tmp_path / "runtime.json"
    cfg_file.write_text(json.dumps({
        "auth": {"enabled": True,
                 "keys": [{"key_id": "revoked", "secret": STRONG_KEY, "active": False}]},
    }), encoding="utf-8")
    cfg = load_runtime_config(env={"DKWS_CONFIG_FILE": str(cfg_file)}, strict=False)
    assert cfg.auth.verify(STRONG_KEY) is None


def test_env_overrides_config_file(tmp_path):
    """环境变量优先于配置文件。"""
    cfg_file = tmp_path / "runtime.json"
    cfg_file.write_text(json.dumps({"profile": "dev", "rate_limit": {"enabled": False}}),
                        encoding="utf-8")
    cfg = load_runtime_config(env={"DKWS_CONFIG_FILE": str(cfg_file),
                                   "DKWS_RATE_LIMIT_ENABLED": "true"})
    assert cfg.rate_limit.enabled is True


def test_size_and_concurrency_env_parsing():
    """大小与并发配置支持环境变量覆盖。"""
    cfg = load_runtime_config(env={
        "DKWS_MAX_REQUEST_BYTES": "2048",
        "DKWS_MAX_RESPONSE_BYTES": "4096",
        "DKWS_CONCURRENCY_ENABLED": "true",
        "DKWS_MAX_IN_FLIGHT": "3",
    })
    assert cfg.size_limit.max_request_bytes == 2048
    assert cfg.size_limit.max_response_bytes == 4096
    assert cfg.concurrency.enabled is True
    assert cfg.concurrency.max_in_flight == 3


def test_invalid_int_env_rejected():
    """非整数环境变量报错。"""
    with pytest.raises(ConfigError, match="需为整数"):
        load_runtime_config(env={"DKWS_MAX_IN_FLIGHT": "many"})


def test_runtime_store_path_defaults_to_control_dir(tmp_path):
    """Runtime Store 默认落在 90_control/runtime 下。"""
    cfg = load_runtime_config(env={"DKWS_RUNTIME_STORE_ENABLED": "true"})
    resolved = cfg.runtime_store.resolve_path(tmp_path)
    assert resolved == tmp_path / "90_control" / "runtime" / "runtime.db"


def test_public_and_admin_path_classification():
    """健康检查为公开路径，闸门审计要求 admin。"""
    cfg = load_runtime_config(env={"DKWS_API_KEYS": STRONG_KEY})
    assert cfg.auth.is_public("/v1/health")
    assert cfg.auth.is_public("/api/skill/health")
    assert not cfg.auth.is_public("/api/skill/execute")
    assert cfg.auth.requires_admin("/api/skill/gates/audit")
    assert not cfg.auth.requires_admin("/api/skill/execute")


def test_rate_limit_bucket_math():
    """限流配置换算为桶容量与补充速率。"""
    cfg = load_runtime_config(env={"DKWS_RATE_LIMIT_ENABLED": "true",
                                   "DKWS_RATE_LIMIT_RPM": "120",
                                   "DKWS_RATE_LIMIT_BURST": "5"})
    assert cfg.rate_limit.capacity() == 5
    assert cfg.rate_limit.refill_per_second() == pytest.approx(2.0)


def test_prod_profile_constant():
    """常量导出正确，避免拼写漂移。"""
    assert PROFILE_PROD == "prod"
