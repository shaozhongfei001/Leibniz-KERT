"""M2.3 SQLite Runtime Store 单元测试。"""

from __future__ import annotations

import sqlite3

import pytest

from dkws.domain.errors import ConflictError, IdempotencyConflictError
from dkws.infrastructure.runtime_store import (
    MIGRATIONS,
    SCHEMA_VERSION,
    RuntimeStore,
)


@pytest.fixture()
def store(tmp_path) -> RuntimeStore:
    """在临时目录创建 Runtime Store。"""
    return RuntimeStore(tmp_path / "90_control" / "runtime" / "runtime.db")


# ---------------------------------------------------------------- schema / WAL

def test_migration_applied_on_init(store):
    """初始化即完成 migration，schema 版本与 MIGRATIONS 一致。"""
    assert store.schema_version() == SCHEMA_VERSION == len(MIGRATIONS)


def test_migrate_is_idempotent(store):
    """重复 migrate 不重复应用。"""
    assert store.migrate() == SCHEMA_VERSION
    assert store.migrate() == SCHEMA_VERSION
    conn = store.connect()
    try:
        rows = conn.execute("SELECT COUNT(*) AS c FROM schema_version").fetchone()["c"]
    finally:
        conn.close()
    assert rows == SCHEMA_VERSION


def test_wal_enabled(store):
    """WAL 日志模式已启用。"""
    assert store.journal_mode() == "wal"


def test_wal_can_be_disabled(tmp_path):
    """可显式关闭 WAL（退回 delete 模式）。"""
    s = RuntimeStore(tmp_path / "runtime.db", wal=False)
    assert s.journal_mode() != "wal"


def test_reopen_preserves_schema(tmp_path):
    """重新打开同一文件不丢 schema，也不重复迁移。"""
    path = tmp_path / "runtime.db"
    RuntimeStore(path).create_job("J1", "SKILL")
    reopened = RuntimeStore(path)
    assert reopened.schema_version() == SCHEMA_VERSION
    assert reopened.get_job("J1") is not None


def test_expected_tables_exist(store):
    """四张运行态表齐备。"""
    conn = store.connect()
    try:
        names = {r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    finally:
        conn.close()
    assert {"schema_version", "idempotency_records", "jobs",
            "evidence_audit", "gate_audit"} <= names


def test_forbidden_path_rejected(tmp_path):
    """禁止把 Store 放进知识数据目录（ADR-012 边界）。"""
    with pytest.raises(ConflictError, match="知识数据目录"):
        RuntimeStore(tmp_path / "03_core" / "runtime.db")


@pytest.mark.parametrize("forbidden", ["01_raw", "02_work", "03_core", "04_serve"])
def test_all_knowledge_dirs_forbidden(tmp_path, forbidden):
    """四类知识目录一律拒绝。"""
    with pytest.raises(ConflictError):
        RuntimeStore(tmp_path / forbidden / "sub" / "runtime.db")


# ---------------------------------------------------------------- 幂等

def test_remember_then_lookup(store):
    """写入后可按 scope+key 查回，含响应载荷。"""
    store.remember("skill_execute", "req-1", "h1", response={"status": "ok"})
    hit = store.lookup("skill_execute", "req-1")
    assert hit is not None
    assert hit.response == {"status": "ok"}
    assert hit.status == "COMPLETED"


def test_remember_same_key_same_hash_returns_existing(store):
    """同键同内容重复写入返回原记录（NO_OP 语义）。"""
    first = store.remember("s", "k", "h", response={"n": 1})
    second = store.remember("s", "k", "h", response={"n": 2})
    assert second.response == first.response == {"n": 1}


def test_remember_same_key_different_hash_conflicts(store):
    """同键不同内容触发幂等冲突。"""
    store.remember("s", "k", "hash-a")
    with pytest.raises(IdempotencyConflictError):
        store.remember("s", "k", "hash-b")


def test_scope_isolation(store):
    """不同 scope 的同名键互不干扰。"""
    store.remember("scope-a", "k", "h", response={"who": "a"})
    store.remember("scope-b", "k", "h", response={"who": "b"})
    assert store.lookup("scope-a", "k").response == {"who": "a"}
    assert store.lookup("scope-b", "k").response == {"who": "b"}


def test_lookup_missing_returns_none(store):
    """未命中返回 None。"""
    assert store.lookup("s", "absent") is None


def test_complete_updates_response(store):
    """complete 可回填响应与状态。"""
    store.remember("s", "k", "h", status="RUNNING")
    store.complete("s", "k", {"status": "ok"}, status="COMPLETED")
    hit = store.lookup("s", "k")
    assert hit.status == "COMPLETED"
    assert hit.response == {"status": "ok"}


def test_expired_record_not_returned(tmp_path):
    """TTL 到期的记录不再命中。"""
    s = RuntimeStore(tmp_path / "runtime.db", idempotency_ttl_seconds=-1)
    s.remember("s", "k", "h", response={"a": 1})
    assert s.lookup("s", "k") is None


def test_purge_expired_removes_rows(tmp_path):
    """purge_expired 删除过期记录并返回条数。

    注意：``remember`` 写入前会顺带清理过期记录，因此此处先只写一条，
    再显式调用 purge，断言其删除计数与清理后的表行数。
    """
    s = RuntimeStore(tmp_path / "runtime.db", idempotency_ttl_seconds=-1)
    s.remember("s", "k1", "h")
    assert s.purge_expired() == 1
    assert s.stats()["idempotency_records"] == 0
    assert s.lookup("s", "k1") is None


def test_remember_purges_expired_eagerly(tmp_path):
    """写入新记录时顺带清理已过期记录，避免表无界增长。"""
    s = RuntimeStore(tmp_path / "runtime.db", idempotency_ttl_seconds=-1)
    s.remember("s", "k1", "h")
    s.remember("s", "k2", "h")
    assert s.stats()["idempotency_records"] == 1


def test_zero_ttl_never_expires(tmp_path):
    """ttl_seconds=0 视为永不过期。"""
    s = RuntimeStore(tmp_path / "runtime.db")
    s.remember("s", "k", "h", response={"a": 1}, ttl_seconds=0)
    assert s.lookup("s", "k") is not None


def test_idempotency_survives_reopen(tmp_path):
    """幂等记录跨进程重启可复放（M2.3 核心目标）。"""
    path = tmp_path / "runtime.db"
    RuntimeStore(path).remember("skill_execute", "req-x", "h",
                                response={"status": "ok", "data": {"v": 1}})
    hit = RuntimeStore(path).lookup("skill_execute", "req-x")
    assert hit is not None
    assert hit.response["data"] == {"v": 1}


# ---------------------------------------------------------------- Job

def test_create_and_get_job(store):
    """登记 Job 后可读回。"""
    store.create_job("J1", "SKILL", {"skillId": "s"})
    job = store.get_job("J1")
    assert job.job_type == "SKILL"
    assert job.status == "PENDING"
    assert job.payload == {"skillId": "s"}
    assert job.attempts == 0


def test_create_job_idempotent(store):
    """重复登记同 ID 返回既有记录。"""
    a = store.create_job("J1", "SKILL", {"n": 1})
    b = store.create_job("J1", "OTHER", {"n": 2})
    assert b.job_type == a.job_type == "SKILL"
    assert b.payload == {"n": 1}


def test_update_job_status_and_result(store):
    """更新状态、结果与尝试次数。"""
    store.create_job("J1", "SKILL")
    updated = store.update_job("J1", status="RUNNING", increment_attempts=True)
    assert updated.status == "RUNNING"
    assert updated.attempts == 1
    done = store.update_job("J1", status="SUCCEEDED", result={"ok": True})
    assert done.status == "SUCCEEDED"
    assert done.result == {"ok": True}


def test_update_job_error_message(store):
    """失败 Job 记录错误信息。"""
    store.create_job("J1", "SKILL")
    failed = store.update_job("J1", status="FAILED", error_message="boom")
    assert failed.status == "FAILED"
    assert failed.error_message == "boom"


def test_update_missing_job_returns_none(store):
    """更新不存在的 Job 返回 None。"""
    assert store.update_job("absent", status="FAILED") is None


def test_list_jobs_filter_by_status(store):
    """按状态过滤列出 Job。"""
    store.create_job("J1", "SKILL")
    store.create_job("J2", "SKILL")
    store.update_job("J2", status="SUCCEEDED")
    pending = store.list_jobs(statuses=["PENDING"])
    assert [j.job_id for j in pending] == ["J1"]
    assert len(store.list_jobs()) == 2


def test_list_jobs_respects_limit(store):
    """limit 生效。"""
    for i in range(5):
        store.create_job(f"J{i}", "SKILL")
    assert len(store.list_jobs(limit=2)) == 2


def test_recover_stale_jobs_resets_running(store):
    """重启后把 RUNNING 复位为 PENDING。"""
    store.create_job("J1", "SKILL")
    store.update_job("J1", status="RUNNING")
    store.create_job("J2", "SKILL")
    recovered = store.recover_stale_jobs()
    assert recovered == ["J1"]
    assert store.get_job("J1").status == "PENDING"
    assert store.get_job("J2").status == "PENDING"


def test_recover_stale_jobs_noop_when_clean(store):
    """无残留时返回空列表。"""
    store.create_job("J1", "SKILL")
    assert store.recover_stale_jobs() == []


def test_job_survives_reopen(tmp_path):
    """Job 状态跨重启保留。"""
    path = tmp_path / "runtime.db"
    RuntimeStore(path).create_job("J1", "SKILL", {"a": 1})
    assert RuntimeStore(path).get_job("J1").payload == {"a": 1}


# ---------------------------------------------------------------- 审计

def test_record_and_list_evidence(store):
    """Evidence 审计可写入与查询。"""
    audit_id = store.record_evidence("OBJ-1", "EV-1", source_ref="GET /v1/evidence",
                                     detail={"ref_count": 2})
    assert audit_id > 0
    rows = store.list_evidence("OBJ-1")
    assert len(rows) == 1
    assert rows[0]["evidence_id"] == "EV-1"
    assert rows[0]["detail"] == {"ref_count": 2}


def test_evidence_audit_is_append_only(store):
    """Evidence 审计为追加式，多条并存。"""
    store.record_evidence("OBJ-1", "EV-1")
    store.record_evidence("OBJ-1", "EV-2")
    assert len(store.list_evidence("OBJ-1")) == 2
    assert store.list_evidence("OBJ-2") == []


def test_record_and_list_gates(store):
    """Gate 审计可写入与查询。"""
    store.record_gate("C1", "GATE-BIZ-01", "APPROVED", "rm@bank", reason="ok")
    rows = store.list_gates("C1")
    assert len(rows) == 1
    assert rows[0]["decision"] == "APPROVED"
    assert rows[0]["decided_by"] == "rm@bank"


def test_gate_audit_ordering(store):
    """Gate 审计按 audit_id 倒序返回（最新在前）。"""
    store.record_gate("C1", "G1", "PENDING", "a")
    store.record_gate("C1", "G1", "APPROVED", "b")
    rows = store.list_gates("C1")
    assert rows[0]["decision"] == "APPROVED"


# ---------------------------------------------------------------- 运维

def test_stats_reports_counts_and_version(store):
    """stats 汇报 schema 版本、日志模式与各表行数。"""
    store.create_job("J1", "SKILL")
    store.remember("s", "k", "h")
    store.record_evidence("O", "E")
    store.record_gate("C", "G", "APPROVED", "u")
    stats = store.stats()
    assert stats["schema_version"] == SCHEMA_VERSION
    assert stats["journal_mode"] == "wal"
    assert stats["jobs"] == 1
    assert stats["idempotency_records"] == 1
    assert stats["evidence_audit"] == 1
    assert stats["gate_audit"] == 1


def test_backup_creates_readable_copy(store, tmp_path):
    """在线备份产出可读快照。"""
    store.create_job("J1", "SKILL")
    target = store.backup_to(tmp_path / "backup" / "runtime.bak.db")
    assert target.is_file()
    conn = sqlite3.connect(target)
    try:
        count = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
    finally:
        conn.close()
    assert count == 1


def test_concurrent_writes_do_not_corrupt(store):
    """多线程并发写入不丢记录（WAL + 写锁）。"""
    import threading

    def worker(idx: int) -> None:
        """并发登记 Job。"""
        store.create_job(f"J{idx}", "SKILL", {"i": idx})

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert store.stats()["jobs"] == 20
