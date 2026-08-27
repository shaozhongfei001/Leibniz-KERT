"""M2.4 Job 队列语义单元测试：原子领取、lease、重试退避、dead-letter。"""

from __future__ import annotations

import threading

import pytest

from dkws.domain.errors import ConflictError
from dkws.infrastructure.runtime_store import (
    CLAIMABLE_STATES,
    SCHEMA_VERSION,
    RuntimeStore,
)


@pytest.fixture()
def store(tmp_path) -> RuntimeStore:
    """临时 Runtime Store。"""
    return RuntimeStore(tmp_path / "runtime.db")


# ---------------------------------------------------------------- schema v2

def test_schema_upgraded_to_v2(store):
    """migration 002 已应用。"""
    assert store.schema_version() == SCHEMA_VERSION == 2


def test_v2_columns_present(store):
    """lease/重试/dead-letter 列齐备。"""
    conn = store.connect()
    try:
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(jobs)").fetchall()}
    finally:
        conn.close()
    assert {"lease_owner", "lease_expires_at", "heartbeat_at", "max_attempts",
            "next_attempt_at", "error_code", "dead_letter", "dead_lettered_at",
            "dead_letter_reason", "idem_key"} <= cols


def test_claim_indexes_created(store):
    """调度相关索引已建立。"""
    conn = store.connect()
    try:
        idx = {r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index'").fetchall()}
    finally:
        conn.close()
    assert {"idx_jobs_claim", "idx_jobs_lease", "idx_jobs_dead_letter",
            "idx_jobs_idem"} <= idx


def test_v1_to_v2_upgrade_normalizes_succeeded(tmp_path):
    """v1 库升级到 v2 时把 SUCCEEDED 归一为 COMPLETED（对齐 §11.1）。

    构造真实的 v1 库：只应用 MIGRATIONS[0]，并手工建 schema_version 表
    （该表由 migrate() 负责创建，不属任何一条 migration）。
    """
    import sqlite3

    from dkws.infrastructure.runtime_store import MIGRATIONS

    db = tmp_path / "legacy.db"
    conn = sqlite3.connect(db)
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS schema_version ("
                     "version INTEGER PRIMARY KEY, applied_at REAL NOT NULL)")
        for stmt in MIGRATIONS[0]:
            conn.execute(stmt)
        conn.execute("INSERT INTO schema_version (version, applied_at) VALUES (1, 0)")
        conn.execute(
            "INSERT INTO jobs (job_id, job_type, status, payload_json, attempts, "
            "created_at, updated_at) VALUES ('J-OLD', 'SKILL', 'SUCCEEDED', '{}', 1, 0, 0)")
        conn.commit()
    finally:
        conn.close()

    upgraded = RuntimeStore(db)
    assert upgraded.schema_version() == 2
    assert upgraded.get_job("J-OLD").status == "COMPLETED"


# ---------------------------------------------------------------- 原子领取

def test_claim_returns_none_when_empty(store):
    """队列空时领取返回 None。"""
    assert store.claim_job("w1") is None


def test_claim_sets_running_and_lease(store):
    """领取后置 RUNNING，写入 lease 持有者与到期时间，并递增尝试次数。"""
    store.create_job("J1", "SKILL")
    job = store.claim_job("w1", lease_seconds=30, now=1000.0)
    assert job.status == "RUNNING"
    assert job.lease_owner == "w1"
    assert job.lease_expires_at == pytest.approx(1030.0)
    assert job.attempts == 1


def test_claim_is_exclusive(store):
    """同一 Job 只能被一个 Worker 领取。"""
    store.create_job("J1", "SKILL")
    assert store.claim_job("w1") is not None
    assert store.claim_job("w2") is None


def test_claim_respects_job_types(store):
    """job_types 过滤生效。"""
    store.create_job("J1", "INGEST")
    assert store.claim_job("w1", job_types=["SKILL"]) is None
    assert store.claim_job("w1", job_types=["INGEST"]).job_id == "J1"


def test_claim_empty_job_types_returns_none(store):
    """job_types 为空列表表示不接受任何类型。"""
    store.create_job("J1", "SKILL")
    assert store.claim_job("w1", job_types=[]) is None


def test_claim_skips_backoff_window(store):
    """退避窗口未到的 Job 不被领取。"""
    store.create_job("J1", "SKILL", available_at=2000.0)
    assert store.claim_job("w1", now=1000.0) is None
    assert store.claim_job("w1", now=2000.0) is not None


def test_claim_skips_dead_letter(store):
    """dead-letter Job 不再被领取。"""
    store.create_job("J1", "SKILL", max_attempts=1)
    store.claim_job("w1")
    store.fail_job("J1", "w1", error_message="boom")
    assert store.get_job("J1").dead_letter is True
    assert store.claim_job("w2") is None


def test_claim_skips_exhausted_attempts(store):
    """尝试额度耗尽的 Job 不被领取。"""
    store.create_job("J1", "SKILL", max_attempts=1)
    store.claim_job("w1")
    store.update_job("J1", status="RETRYING")
    assert store.claim_job("w2") is None


def test_claim_order_is_fifo(store):
    """先创建的先被领取，避免饥饿。"""
    store.create_job("J1", "SKILL")
    store.create_job("J2", "SKILL")
    assert store.claim_job("w1").job_id == "J1"
    assert store.claim_job("w2").job_id == "J2"


def test_claim_accepts_retrying_state(store):
    """RETRYING 属可领取状态（§11.1 允许 RETRYING → RUNNING）。"""
    assert "RETRYING" in CLAIMABLE_STATES
    store.create_job("J1", "SKILL", status="RETRYING")
    assert store.claim_job("w1") is not None


def test_claim_rejects_non_positive_lease(store):
    """lease_seconds 必须为正。"""
    store.create_job("J1", "SKILL")
    with pytest.raises(ConflictError, match="lease_seconds"):
        store.claim_job("w1", lease_seconds=0)


def test_concurrent_claim_no_double_delivery(store):
    """并发领取时每个 Job 只被投递一次（原子性核心断言）。"""
    for i in range(20):
        store.create_job(f"J{i}", "SKILL")
    claimed: list[str] = []
    lock = threading.Lock()

    def worker(idx: int) -> None:
        """不断领取直到队列空。"""
        while True:
            job = store.claim_job(f"w{idx}")
            if job is None:
                return
            with lock:
                claimed.append(job.job_id)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(claimed) == sorted(f"J{i}" for i in range(20))
    assert len(claimed) == len(set(claimed))


# ---------------------------------------------------------------- lease 心跳

def test_heartbeat_extends_lease(store):
    """续约推后 lease 到期时间。"""
    store.create_job("J1", "SKILL")
    store.claim_job("w1", lease_seconds=30, now=1000.0)
    assert store.heartbeat_job("J1", "w1", lease_seconds=30, now=1020.0) is True
    assert store.get_job("J1").lease_expires_at == pytest.approx(1050.0)


def test_heartbeat_rejects_non_owner(store):
    """非持有者不能续约。"""
    store.create_job("J1", "SKILL")
    store.claim_job("w1")
    assert store.heartbeat_job("J1", "w2") is False


def test_heartbeat_rejects_missing_job(store):
    """不存在的 Job 续约失败。"""
    assert store.heartbeat_job("absent", "w1") is False


def test_heartbeat_rejects_completed_job(store):
    """已完成 Job 不可续约。"""
    store.create_job("J1", "SKILL")
    store.claim_job("w1")
    store.complete_job("J1", "w1", {"ok": True})
    assert store.heartbeat_job("J1", "w1") is False


# ---------------------------------------------------------------- 完成

def test_complete_sets_terminal_state(store):
    """完成后置 COMPLETED（对齐 states.py），释放 lease。"""
    store.create_job("J1", "SKILL")
    store.claim_job("w1")
    done = store.complete_job("J1", "w1", {"ok": True})
    assert done.status == "COMPLETED"
    assert done.result == {"ok": True}
    assert done.lease_owner is None
    assert done.lease_expires_at is None


def test_complete_rejects_non_owner(store):
    """非持有者不能写回结果（防止重复执行双写）。"""
    store.create_job("J1", "SKILL")
    store.claim_job("w1")
    assert store.complete_job("J1", "w2", {"ok": True}) is None
    assert store.get_job("J1").status == "RUNNING"


# ---------------------------------------------------------------- 重试与退避

def test_fail_moves_to_retrying_with_backoff(store):
    """失败且有额度时置 RETRYING 并设置退避时间。"""
    store.create_job("J1", "SKILL", max_attempts=3)
    store.claim_job("w1", now=1000.0)
    failed = store.fail_job("J1", "w1", error_message="boom",
                            backoff_base=2.0, backoff_factor=2.0, now=1000.0)
    assert failed.status == "RETRYING"
    assert failed.dead_letter is False
    # 第 1 次失败：delay = 2.0 * 2^0 = 2.0
    assert failed.next_attempt_at == pytest.approx(1002.0)


def test_backoff_grows_exponentially(store):
    """退避随尝试次数指数增长。"""
    store.create_job("J1", "SKILL", max_attempts=5)
    delays = []
    now = 1000.0
    for _ in range(3):
        store.claim_job("w1", now=now)
        rec = store.fail_job("J1", "w1", error_message="boom",
                             backoff_base=2.0, backoff_factor=2.0, now=now)
        delays.append(rec.next_attempt_at - now)
        now = rec.next_attempt_at
    assert delays == pytest.approx([2.0, 4.0, 8.0])


def test_backoff_capped_at_max(store):
    """退避不超过上限。"""
    store.create_job("J1", "SKILL", max_attempts=10)
    now = 1000.0
    delays = []
    for _ in range(6):
        assert store.claim_job("w1", now=now) is not None
        rec = store.fail_job("J1", "w1", error_message="boom", backoff_base=2.0,
                             backoff_factor=2.0, backoff_max=10.0, now=now)
        delays.append(rec.next_attempt_at - now)
        now = rec.next_attempt_at + 1.0
    # 2, 4, 8 后触顶，其后恒为 10
    assert delays == pytest.approx([2.0, 4.0, 8.0, 10.0, 10.0, 10.0])
    assert max(delays) <= 10.0


def test_retry_then_succeed(store):
    """失败重试后成功，最终为 COMPLETED。"""
    store.create_job("J1", "SKILL", max_attempts=3)
    store.claim_job("w1", now=1000.0)
    store.fail_job("J1", "w1", error_message="boom", now=1000.0)
    again = store.claim_job("w1", now=2000.0)
    assert again.attempts == 2
    assert store.complete_job("J1", "w1").status == "COMPLETED"


def test_fail_rejects_non_owner(store):
    """非持有者不能标记失败。"""
    store.create_job("J1", "SKILL")
    store.claim_job("w1")
    assert store.fail_job("J1", "w2", error_message="boom") is None


# ---------------------------------------------------------------- dead-letter

def test_dead_letter_when_attempts_exhausted(store):
    """额度耗尽进入 dead-letter，状态为 FAILED + dead_letter=1。

    注意每轮需推进时间越过退避窗口，否则第 2 次 claim 会因退避未到而领不到。
    """
    store.create_job("J1", "SKILL", max_attempts=2)
    now = 1000.0
    rec = None
    for _ in range(2):
        assert store.claim_job("w1", now=now) is not None
        rec = store.fail_job("J1", "w1", error_message="boom", now=now)
        now = (rec.next_attempt_at or now) + 1.0
    assert rec.status == "FAILED"
    assert rec.dead_letter is True
    assert "耗尽" in rec.dead_letter_reason


def test_dead_letter_never_uses_blocked(store):
    """dead-letter 不使用 BLOCKED：§11.1 规定 FAILED 仅可转 RETRYING。"""
    from dkws.domain.states import JOB_TRANSITIONS

    store.create_job("J1", "SKILL", max_attempts=1)
    store.claim_job("w1")
    rec = store.fail_job("J1", "w1", error_message="boom")
    assert rec.status != "BLOCKED"
    assert JOB_TRANSITIONS["FAILED"] == {"RETRYING"}


def test_non_retryable_goes_dead_letter_immediately(store):
    """不可重试错误立即 dead-letter，不消耗剩余额度。"""
    store.create_job("J1", "SKILL", max_attempts=5)
    store.claim_job("w1")
    rec = store.fail_job("J1", "w1", error_message="bad input",
                         error_code="VALIDATION", retryable=False)
    assert rec.dead_letter is True
    assert rec.error_code == "VALIDATION"
    assert "不可重试" in rec.dead_letter_reason


def test_list_dead_letters(store):
    """可列出 dead-letter Job。"""
    store.create_job("J1", "SKILL", max_attempts=1)
    store.claim_job("w1")
    store.fail_job("J1", "w1", error_message="boom")
    rows = store.list_dead_letters()
    assert [j.job_id for j in rows] == ["J1"]


def test_requeue_dead_letter(store):
    """人工重放：清除 dead-letter 标记并追加额度。"""
    store.create_job("J1", "SKILL", max_attempts=1)
    store.claim_job("w1")
    store.fail_job("J1", "w1", error_message="boom")
    requeued = store.requeue_dead_letter("J1", extra_attempts=2)
    assert requeued.status == "RETRYING"
    assert requeued.dead_letter is False
    assert requeued.max_attempts == 3
    assert store.claim_job("w2") is not None


def test_requeue_non_dead_letter_returns_none(store):
    """非 dead-letter Job 重放返回 None。"""
    store.create_job("J1", "SKILL")
    assert store.requeue_dead_letter("J1") is None


def test_requeue_rejects_invalid_extra(store):
    """extra_attempts 必须 >= 1。"""
    with pytest.raises(ConflictError, match="extra_attempts"):
        store.requeue_dead_letter("J1", extra_attempts=0)


# ---------------------------------------------------------------- 幂等键

def test_idem_key_conflict_on_active_job(store):
    """同 job_type + idem_key 存在活跃 Job 时冲突。"""
    store.create_job("J1", "SKILL", idem_key="K1")
    with pytest.raises(ConflictError, match="幂等键冲突"):
        store.create_job("J2", "SKILL", idem_key="K1")


def test_idem_key_allows_reuse_after_completion(store):
    """终态后同一幂等键可再次使用。"""
    store.create_job("J1", "SKILL", idem_key="K1")
    store.claim_job("w1")
    store.complete_job("J1", "w1")
    assert store.create_job("J2", "SKILL", idem_key="K1").job_id == "J2"


def test_idem_key_scoped_by_job_type(store):
    """不同 job_type 的同名幂等键互不冲突。"""
    store.create_job("J1", "SKILL", idem_key="K1")
    assert store.create_job("J2", "INGEST", idem_key="K1").job_id == "J2"


def test_find_job_by_idem(store):
    """可按幂等键查回 Job。"""
    store.create_job("J1", "SKILL", idem_key="K1")
    assert store.find_job_by_idem("SKILL", "K1").job_id == "J1"
    assert store.find_job_by_idem("SKILL", "absent") is None
    assert store.find_job_by_idem("SKILL", "") is None


def test_max_job_seq(store):
    """可提取该类型已用最大序号，避免 Job ID 撞号。"""
    store.create_job("JOB-SKILL-20260827-0003", "SKILL")
    store.create_job("JOB-SKILL-20260827-0007", "SKILL")
    assert store.max_job_seq("SKILL") == 7
    assert store.max_job_seq("INGEST") == 0


def test_create_job_rejects_invalid_max_attempts(store):
    """max_attempts 必须 >= 1。"""
    with pytest.raises(ConflictError, match="max_attempts"):
        store.create_job("J1", "SKILL", max_attempts=0)


# ---------------------------------------------------------------- 取消与统计

def test_cancel_job(store):
    """可取消未进入终态的 Job。"""
    store.create_job("J1", "SKILL")
    rec = store.cancel_job("J1", reason="人工取消")
    assert rec.status == "CANCELLED"
    assert store.claim_job("w1") is None


def test_cancel_completed_job_returns_none(store):
    """已完成 Job 不可取消。"""
    store.create_job("J1", "SKILL")
    store.claim_job("w1")
    store.complete_job("J1", "w1")
    assert store.cancel_job("J1") is None


def test_queue_stats(store):
    """队列统计反映各状态与可领取数。"""
    store.create_job("J1", "SKILL")
    store.create_job("J2", "SKILL")
    store.claim_job("w1", now=1000.0)
    stats = store.queue_stats(now=1000.0)
    assert stats["by_status"]["RUNNING"] == 1
    assert stats["by_status"]["PENDING"] == 1
    assert stats["claimable"] == 1
    assert stats["dead_letter"] == 0
    assert stats["expired_leases"] == 0


def test_queue_stats_counts_expired_leases(store):
    """过期 lease 被统计。"""
    store.create_job("J1", "SKILL")
    store.claim_job("w1", lease_seconds=10, now=1000.0)
    assert store.queue_stats(now=1020.0)["expired_leases"] == 1


def test_attempts_remaining_and_lease_expired_helpers(store):
    """JobRecord 辅助属性正确。"""
    store.create_job("J1", "SKILL", max_attempts=3)
    job = store.claim_job("w1", lease_seconds=10, now=1000.0)
    assert job.attempts_remaining == 2
    assert job.lease_expired(now=1005.0) is False
    assert job.lease_expired(now=1011.0) is True
