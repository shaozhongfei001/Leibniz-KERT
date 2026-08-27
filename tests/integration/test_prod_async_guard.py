"""M2-P2 Owner 决策补充测试：生产 profile 强制 Runtime Store + deprecation 标记。

对应 Owner 审核结论（2026-08-27）：
- 决策 2：``recover_stale_jobs`` 标记 deprecated，保留兼容、不改行为。
- 决策 3：``profile=prod`` 且未启用 Runtime Store 时，``execute_async``
  必须拒绝执行，禁止回退到 threading 模式（防生产崩溃丢任务）。
"""

from __future__ import annotations

import inspect

import pytest

from dkws.application.skills import SkillExecutionService
from dkws.domain.errors import ServiceNotReadyError
from dkws.infrastructure.runtime_store import RuntimeStore

SKILL_ID = "skill-customer-outreach-script"
SKILL_REQUEST = {"customerId": "CUST-CORP-0001"}


@pytest.fixture()
def store(ws) -> RuntimeStore:
    """工作区内的 Runtime Store。"""
    return RuntimeStore(ws / "90_control" / "runtime" / "runtime.db")


# ------------------------------------------------- 决策 3：生产强制 Runtime Store

class TestProductionRequiresRuntimeStore:
    """生产 profile 下异步执行必须启用 Runtime Store。"""

    def test_prod_without_store_rejects_async(self, ws):
        """prod + 未启用 Store → 拒绝异步执行。"""
        svc = SkillExecutionService(ws, profile="prod")
        with pytest.raises(ServiceNotReadyError, match="必须启用 Runtime Store"):
            svc.execute_async(SKILL_ID, "REQ-PROD-1", SKILL_REQUEST)

    def test_rejection_maps_to_503(self, ws):
        """拒绝时映射为 HTTP 503 且可重试（启用 Store 后即恢复）。"""
        svc = SkillExecutionService(ws, profile="prod")
        with pytest.raises(ServiceNotReadyError) as exc:
            svc.execute_async(SKILL_ID, "REQ-PROD-2", SKILL_REQUEST)
        assert exc.value.http_status() == 503
        assert exc.value.error_code == "SERVICE_NOT_READY"
        assert exc.value.retryable() is True

    def test_rejection_carries_remediation_details(self, ws):
        """错误详情含修复指引，便于运维定位。"""
        svc = SkillExecutionService(ws, profile="prod")
        with pytest.raises(ServiceNotReadyError) as exc:
            svc.execute_async(SKILL_ID, "REQ-PROD-3", SKILL_REQUEST)
        details = exc.value.details
        assert details["profile"] == "prod"
        assert details["runtime_store_enabled"] is False
        assert "DKWS_RUNTIME_STORE_ENABLED" in details["remediation"]

    def test_no_thread_fallback_in_prod(self, ws):
        """拒绝时不得回退线程模式：不应创建任何 Job 目录。"""
        svc = SkillExecutionService(ws, profile="prod")
        with pytest.raises(ServiceNotReadyError):
            svc.execute_async(SKILL_ID, "REQ-PROD-4", SKILL_REQUEST)
        jobs_root = ws / "90_control" / "jobs"
        assert not list(jobs_root.glob("JOB-SKILL-*")) if jobs_root.is_dir() else True

    def test_prod_with_store_succeeds(self, ws, store):
        """prod + 启用 Store → 正常入队。"""
        svc = SkillExecutionService(ws, runtime_store=store, profile="prod")
        job_id = svc.execute_async(SKILL_ID, "REQ-PROD-5", SKILL_REQUEST)
        assert store.get_job(job_id).status == "PENDING"

    def test_dev_without_store_still_allowed(self, ws):
        """dev + 未启用 Store → 保持线程模式（不破坏开发流程）。"""
        svc = SkillExecutionService(ws, profile="dev")
        job_id = svc.execute_async(SKILL_ID, "REQ-DEV-1", SKILL_REQUEST)
        assert job_id.startswith("JOB-SKILL-")

    def test_default_profile_is_dev(self, ws, monkeypatch):
        """未显式指定且无环境变量时默认 dev，允许线程模式。"""
        monkeypatch.delenv("DKWS_PROFILE", raising=False)
        svc = SkillExecutionService(ws)
        assert svc.execute_async(SKILL_ID, "REQ-DEV-2", SKILL_REQUEST)

    def test_profile_read_from_env(self, ws, monkeypatch):
        """缺省时从 DKWS_PROFILE 环境变量读取。"""
        monkeypatch.setenv("DKWS_PROFILE", "prod")
        svc = SkillExecutionService(ws)
        with pytest.raises(ServiceNotReadyError):
            svc.execute_async(SKILL_ID, "REQ-PROD-6", SKILL_REQUEST)

    def test_explicit_profile_overrides_env(self, ws, monkeypatch):
        """显式参数优先于环境变量。"""
        monkeypatch.setenv("DKWS_PROFILE", "prod")
        svc = SkillExecutionService(ws, profile="dev")
        assert svc.execute_async(SKILL_ID, "REQ-DEV-3", SKILL_REQUEST)

    def test_profile_is_case_insensitive(self, ws, monkeypatch):
        """profile 比较忽略大小写与空白，避免配置笔误绕过校验。"""
        monkeypatch.delenv("DKWS_PROFILE", raising=False)
        svc = SkillExecutionService(ws, profile="  PROD  ")
        with pytest.raises(ServiceNotReadyError):
            svc.execute_async(SKILL_ID, "REQ-PROD-7", SKILL_REQUEST)

    def test_sync_execute_unaffected_in_prod(self, ws):
        """同步执行不受此约束（不依赖 Worker，无丢任务风险）。"""
        svc = SkillExecutionService(ws, profile="prod")
        result = svc.execute(SKILL_ID, "REQ-PROD-8", SKILL_REQUEST)
        assert result.status == "ok"

    def test_workspace_check_precedes_store_check(self, tmp_path):
        """未配置工作区时仍先报工作区错误（错误优先级稳定）。"""
        svc = SkillExecutionService(None, profile="prod")
        with pytest.raises(ValueError, match="workspace 未配置"):
            svc.execute_async(SKILL_ID, "REQ-PROD-9", SKILL_REQUEST)


class TestProductionEnforcementViaApi:
    """经 create_app 装配时 profile 正确传递。"""

    def test_api_prod_profile_propagates(self, ws):
        """生产 profile 但未启用 Store 时，API 层的 Service 亦拒绝异步执行。"""
        from dkws.api.server import create_app
        from dkws.infrastructure.runtime_config import (
            ApiKeyRecord,
            AuthConfig,
            RateLimitConfig,
            RuntimeConfig,
            _digest,
        )

        cfg = RuntimeConfig(
            profile="prod",
            auth=AuthConfig(enabled=True, keys=(
                ApiKeyRecord(key_id="svc", digest=_digest("0123456789abcdef0123"),
                             scopes=frozenset({"read", "execute"})),)),
            rate_limit=RateLimitConfig(enabled=True))
        app = create_app(ws, runtime_config=cfg)
        assert app.state.runtime_store is None
        with pytest.raises(ServiceNotReadyError, match="必须启用 Runtime Store"):
            app.state.skill_service.execute_async(SKILL_ID, "REQ-API-1", SKILL_REQUEST)

    def test_api_prod_with_store_allows_async(self, ws):
        """生产 profile + 启用 Store 时 API 层可正常入队。"""
        from dkws.api.server import create_app
        from dkws.infrastructure.runtime_config import (
            ApiKeyRecord,
            AuthConfig,
            RateLimitConfig,
            RuntimeConfig,
            RuntimeStoreConfig,
            _digest,
        )

        cfg = RuntimeConfig(
            profile="prod",
            auth=AuthConfig(enabled=True, keys=(
                ApiKeyRecord(key_id="svc", digest=_digest("0123456789abcdef0123"),
                             scopes=frozenset({"read", "execute"})),)),
            rate_limit=RateLimitConfig(enabled=True),
            runtime_store=RuntimeStoreConfig(enabled=True))
        app = create_app(ws, runtime_config=cfg)
        job_id = app.state.skill_service.execute_async(SKILL_ID, "REQ-API-2",
                                                       SKILL_REQUEST)
        assert app.state.runtime_store.get_job(job_id).status == "PENDING"

    def test_api_dev_profile_allows_thread_mode(self, ws):
        """dev profile 下 API 装配仍允许线程模式。"""
        from dkws.api.server import create_app
        from dkws.infrastructure.runtime_config import RuntimeConfig

        app = create_app(ws, runtime_config=RuntimeConfig(profile="dev"))
        assert app.state.runtime_config.profile == "dev"


# ------------------------------------------------- 决策 2：deprecation 标记

class TestRecoverStaleJobsDeprecation:
    """``recover_stale_jobs`` 已标记 deprecated 但行为不变。"""

    def test_docstring_marks_deprecated(self):
        """docstring 含 deprecated 标记，避免新代码误用。"""
        doc = inspect.getdoc(RuntimeStore.recover_stale_jobs) or ""
        assert ".. deprecated:: M2.4" in doc
        assert "reclaim_expired_leases" in doc

    def test_docstring_explains_risk(self):
        """docstring 说明误抢风险，便于评审判断。"""
        doc = inspect.getdoc(RuntimeStore.recover_stale_jobs) or ""
        assert "误抢" in doc

    def test_behavior_unchanged(self, store):
        """行为与 M2.3 一致：无条件复位所有 RUNNING（含 lease 未过期者）。"""
        store.create_job("J1", "SKILL")
        store.claim_job("w-alive", lease_seconds=3600)
        assert store.get_job("J1").status == "RUNNING"
        assert store.recover_stale_jobs() == ["J1"]
        job = store.get_job("J1")
        assert job.status == "PENDING"
        assert job.lease_owner is None

    def test_method_still_callable_and_not_removed(self, store):
        """方法未删除，兼容路径可用。"""
        assert callable(store.recover_stale_jobs)
        assert store.recover_stale_jobs() == []

    def test_reclaim_is_the_safe_alternative(self, store):
        """对照：推荐的 reclaim 不会动 lease 未过期的 Job。"""
        store.create_job("J1", "SKILL")
        store.claim_job("w-alive", lease_seconds=3600)
        assert store.reclaim_expired_leases() == []
        assert store.get_job("J1").status == "RUNNING"
