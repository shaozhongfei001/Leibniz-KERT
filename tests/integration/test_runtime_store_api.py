"""M2.3 Runtime Store 与 API 的集成测试（幂等复放、审计落库、重启恢复）。"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from dkws.api.server import create_app
from dkws.application.skills import IDEMPOTENCY_SCOPE, SkillExecutionService
from dkws.domain.errors import ConflictError
from dkws.infrastructure.runtime_config import RuntimeConfig, RuntimeStoreConfig
from dkws.infrastructure.runtime_store import RuntimeStore

EXECUTE_PATH = "/api/skill/execute"
GATE_PATH = "/api/skill/gates/audit"
SKILL_ID = "skill-customer-outreach-script"
SKILL_REQUEST = {"customerId": "CUST-CORP-0001"}

DB_REL = ("90_control", "runtime", "runtime.db")


def _store_config(enabled: bool = True, path=None) -> RuntimeConfig:
    """构造启用/关闭 Runtime Store 的运行时配置。"""
    return RuntimeConfig(runtime_store=RuntimeStoreConfig(enabled=enabled, path=path))


def _client(ws, cfg: RuntimeConfig) -> TestClient:
    """构造 TestClient。"""
    return TestClient(create_app(ws, runtime_config=cfg), raise_server_exceptions=False)


def _payload(request_id: str) -> dict:
    """构造 Skill 执行请求体。"""
    return {"skillId": SKILL_ID, "requestId": request_id, "request": SKILL_REQUEST}


def _db(ws):
    """返回默认数据库路径。"""
    return ws.joinpath(*DB_REL)


# ---------------------------------------------------------------- 装配与生命周期

def test_store_created_under_control_dir(ws):
    """启用后数据库落在 90_control/runtime/runtime.db。"""
    _client(ws, _store_config())
    assert _db(ws).is_file()


def test_store_disabled_creates_no_db(ws):
    """未启用时不创建数据库文件。"""
    _client(ws, _store_config(enabled=False))
    assert not _db(ws).exists()


def test_health_reports_schema_version(ws):
    """健康检查回报 Runtime Store 状态与 schema 版本。"""
    runtime = _client(ws, _store_config()).get("/v1/health").json()["data"]["runtime"]
    assert runtime["runtime_store_enabled"] is True
    assert runtime["schema_version"] >= 1


def test_health_reports_store_absent_when_disabled(ws):
    """未启用时健康检查明确回报关闭状态。"""
    runtime = _client(ws, _store_config(enabled=False)).get(
        "/v1/health").json()["data"]["runtime"]
    assert runtime["runtime_store_enabled"] is False
    assert runtime["schema_version"] is None


def test_custom_store_path_respected(ws, tmp_path):
    """可显式指定数据库路径。"""
    target = tmp_path / "custom" / "rt.db"
    _client(ws, _store_config(path=target))
    assert target.is_file()


# ---------------------------------------------------------------- 幂等持久化

def test_execute_persists_idempotency_record(ws):
    """执行 Skill 后幂等记录落库。"""
    resp = _client(ws, _store_config()).post(EXECUTE_PATH, json=_payload("REQ-P1"))
    assert resp.status_code == 200
    assert RuntimeStore(_db(ws)).lookup(IDEMPOTENCY_SCOPE, "REQ-P1") is not None


def test_repeated_execute_is_idempotent(ws):
    """同 requestId 重复执行命中幂等。"""
    client = _client(ws, _store_config())
    client.post(EXECUTE_PATH, json=_payload("REQ-P2"))
    second = client.post(EXECUTE_PATH, json=_payload("REQ-P2")).json()
    assert any(t.get("phase") == "idempotency" for t in second["assemblyTrace"])


def test_idempotency_replay_after_restart(ws):
    """进程重启（新建 app）后仍可按 requestId 复放结果。"""
    cfg = _store_config()
    first = _client(ws, cfg).post(EXECUTE_PATH, json=_payload("REQ-P3")).json()
    second = _client(ws, cfg).post(EXECUTE_PATH, json=_payload("REQ-P3")).json()
    assert any(t.get("phase") == "idempotency" for t in second["assemblyTrace"])
    assert second["status"] == first["status"]
    assert second["data"] == first["data"]


def test_no_replay_across_restart_without_store(ws):
    """未启用 Store 时重启即丢失幂等（对照组，凸显 M2.3 价值）。"""
    cfg = _store_config(enabled=False)
    _client(ws, cfg).post(EXECUTE_PATH, json=_payload("REQ-P3B"))
    second = _client(ws, cfg).post(EXECUTE_PATH, json=_payload("REQ-P3B")).json()
    assert not any(t.get("phase") == "idempotency" for t in second["assemblyTrace"])


def test_service_level_replay_from_store(ws):
    """Service 层可直接从 Store 复原结果（不经 HTTP）。"""
    store = RuntimeStore(_db(ws))
    SkillExecutionService(ws, runtime_store=store).execute(
        SKILL_ID, "REQ-P4", SKILL_REQUEST)

    fresh = SkillExecutionService(ws, runtime_store=RuntimeStore(_db(ws)))
    restored = fresh.get_result("REQ-P4")
    assert restored is not None
    assert restored.skill_id == SKILL_ID
    assert restored.status == "ok"


def test_no_store_still_works_in_memory(ws):
    """未启用 Store 时幂等仍由内存缓存保证（不降低现有行为）。"""
    client = _client(ws, _store_config(enabled=False))
    client.post(EXECUTE_PATH, json=_payload("REQ-P5"))
    second = client.post(EXECUTE_PATH, json=_payload("REQ-P5")).json()
    assert any(t.get("phase") == "idempotency" for t in second["assemblyTrace"])


# ---------------------------------------------------------------- 审计落库

def test_gate_audit_written_to_store_and_jsonl(ws):
    """闸门审计同时写入 JSONL 与 Runtime Store。"""
    resp = _client(ws, _store_config()).post(
        GATE_PATH, json={"customerId": "C900", "gate": "GATE-BIZ-01",
                         "decision": "APPROVED", "decidedBy": "rm@bank", "reason": "ok"})
    assert resp.status_code == 200
    jsonl = ws / "90_control" / "audit" / "gates.jsonl"
    last = json.loads(jsonl.read_text(encoding="utf-8").splitlines()[-1])
    assert last["customerId"] == "C900"
    rows = RuntimeStore(_db(ws)).list_gates("C900")
    assert len(rows) == 1
    assert rows[0]["decision"] == "APPROVED"
    assert rows[0]["decided_by"] == "rm@bank"


def test_gate_audit_jsonl_still_written_without_store(ws):
    """未启用 Store 时 JSONL 审计不受影响。"""
    _client(ws, _store_config(enabled=False)).post(
        GATE_PATH, json={"customerId": "C901", "gate": "G", "decision": "PENDING",
                         "decidedBy": "u"})
    assert (ws / "90_control" / "audit" / "gates.jsonl").is_file()


def test_multiple_gate_decisions_accumulate(ws):
    """多次闸门决策按时间累积，最新在前。"""
    client = _client(ws, _store_config())
    for decision in ("PENDING", "APPROVED"):
        client.post(GATE_PATH, json={"customerId": "C902", "gate": "G",
                                     "decision": decision, "decidedBy": "u"})
    rows = RuntimeStore(_db(ws)).list_gates("C902")
    assert [r["decision"] for r in rows] == ["APPROVED", "PENDING"]


# ---------------------------------------------------------------- Job 恢复

def test_expired_lease_jobs_reclaimed_on_startup(ws):
    """启动时回收 lease 已过期的 Job（M2.4 起 create_app 改用 lease 感知回收）。

    M2.3 时 ``create_app`` 调用 ``recover_stale_jobs``（无条件复位所有 RUNNING）；
    M2.4 改为 ``reclaim_expired_leases``，仅回收 lease 已过期者，
    以免 API 启动时误抢 Worker 正在正常处理的 Job。
    """
    import time

    store = RuntimeStore(_db(ws))
    store.create_job("JOB-STALE", "SKILL", max_attempts=3)
    # 模拟 Worker 领取后崩溃：lease 早已过期
    store.claim_job("w-dead", lease_seconds=1, now=time.time() - 100)

    _client(ws, _store_config())
    job = RuntimeStore(_db(ws)).get_job("JOB-STALE")
    assert job.status == "RETRYING"
    assert job.lease_owner is None
    assert job.error_code == "LEASE_EXPIRED"


def test_live_lease_jobs_not_touched_on_startup(ws):
    """启动时不动 lease 仍有效的 Job（避免误抢正在执行的任务）。"""
    store = RuntimeStore(_db(ws))
    store.create_job("JOB-LIVE", "SKILL")
    store.claim_job("w-alive", lease_seconds=3600)

    _client(ws, _store_config())
    job = RuntimeStore(_db(ws)).get_job("JOB-LIVE")
    assert job.status == "RUNNING"
    assert job.lease_owner == "w-alive"


def test_completed_jobs_not_touched_by_recovery(ws):
    """恢复过程不影响已完成 Job。"""
    store = RuntimeStore(_db(ws))
    store.create_job("JOB-DONE", "SKILL")
    store.update_job("JOB-DONE", status="COMPLETED", result={"ok": True})

    _client(ws, _store_config())
    job = RuntimeStore(_db(ws)).get_job("JOB-DONE")
    assert job.status == "COMPLETED"
    assert job.result == {"ok": True}


# ---------------------------------------------------------------- 边界约束

def test_store_rejected_in_knowledge_dir(ws, tmp_path):
    """拒绝把 Store 放入知识数据目录（ADR-012 边界）。"""
    with pytest.raises(ConflictError):
        create_app(ws, runtime_config=_store_config(
            path=tmp_path / "03_core" / "runtime.db"))


def test_store_holds_no_knowledge_tables(ws):
    """知识权威源仍是文件资产：Store 不建知识内容表。"""
    _client(ws, _store_config()).post(EXECUTE_PATH, json=_payload("REQ-B1"))
    conn = RuntimeStore(_db(ws)).connect()
    try:
        tables = {r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%'").fetchall()}
    finally:
        conn.close()
    assert tables == {"schema_version", "idempotency_records", "jobs",
                      "evidence_audit", "gate_audit"}


def test_store_stats_after_traffic(ws):
    """产生流量后 stats 可用于证据留存。"""
    client = _client(ws, _store_config())
    client.post(EXECUTE_PATH, json=_payload("REQ-B2"))
    client.post(GATE_PATH, json={"customerId": "C903", "gate": "G",
                                 "decision": "APPROVED", "decidedBy": "u"})
    stats = RuntimeStore(_db(ws)).stats()
    assert stats["journal_mode"] == "wal"
    assert stats["idempotency_records"] >= 1
    assert stats["gate_audit"] >= 1
