"""M2.4 Worker 崩溃恢复测试（验收标准：崩溃恢复测试通过）。

覆盖三类崩溃场景：
1. **进程被 kill -9**：真实子进程持有 lease 后被强杀，验证 lease 到期回收。
2. **lease 超时回收**：额度充足时转 RETRYING，额度耗尽时进入 dead-letter。
3. **重启接续**：新 Worker 接手被回收的 Job 并跑到终态。

关键不变量（贯穿全部用例）：
- 状态权威始终在 SQLite（Owner 决策路线 C′），进程崩溃不丢进度；
- 至少一次语义下**结果不双写**：非 lease 持有者无法写回；
- 崩溃回收不越过 ``max_attempts`` 额度。
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

from dkws.infrastructure.runtime_store import RuntimeStore
from dkws.infrastructure.worker import JobWorker, WorkerConfig

REPO = Path(__file__).resolve().parent.parent.parent
SRC = REPO / "src"


@pytest.fixture()
def store(tmp_path) -> RuntimeStore:
    """临时 Runtime Store。"""
    return RuntimeStore(tmp_path / "runtime.db")


def _worker(store: RuntimeStore, **overrides) -> JobWorker:
    """构造测试用 Worker。"""
    defaults = {"worker_id": "w-test", "lease_seconds": 5.0, "poll_interval": 0.01,
                "reclaim_interval": 0.0, "backoff_base": 0.01}
    defaults.update(overrides)
    return JobWorker(store, WorkerConfig(**defaults))


class TestLeaseReclaim:
    """lease 超时回收语义。"""

    def test_expired_lease_returns_job_to_queue(self, store):
        """lease 过期后 Job 转 RETRYING 并可再次领取。"""
        store.create_job("J1", "SKILL", max_attempts=3)
        store.claim_job("w-dead", lease_seconds=10, now=1000.0)
        assert store.reclaim_expired_leases(now=1020.0, backoff_base=0.01) == ["J1"]
        job = store.get_job("J1")
        assert job.status == "RETRYING"
        assert job.lease_owner is None
        assert job.error_code == "LEASE_EXPIRED"

    def test_reclaim_preserves_attempt_count(self, store):
        """回收不重置已消耗的尝试次数，防止无限重试。"""
        store.create_job("J1", "SKILL", max_attempts=3)
        store.claim_job("w-dead", lease_seconds=10, now=1000.0)
        store.reclaim_expired_leases(now=1020.0, backoff_base=0.01)
        assert store.get_job("J1").attempts == 1

    def test_reclaim_respects_max_attempts(self, store):
        """回收耗尽额度时进入 dead-letter，不再无限重试。"""
        store.create_job("J1", "SKILL", max_attempts=1)
        store.claim_job("w-dead", lease_seconds=10, now=1000.0)
        store.reclaim_expired_leases(now=1020.0)
        job = store.get_job("J1")
        assert job.dead_letter is True
        assert job.status == "FAILED"
        assert "耗尽" in job.dead_letter_reason

    def test_reclaim_ignores_live_lease(self, store):
        """未过期的 lease 不被回收，多 Worker 并存时不误抢。"""
        store.create_job("J1", "SKILL")
        store.claim_job("w-alive", lease_seconds=60, now=1000.0)
        assert store.reclaim_expired_leases(now=1010.0) == []
        assert store.get_job("J1").lease_owner == "w-alive"

    def test_reclaim_ignores_completed_job(self, store):
        """已完成 Job 不受回收影响。"""
        store.create_job("J1", "SKILL")
        store.claim_job("w1", lease_seconds=10, now=1000.0)
        store.complete_job("J1", "w1", {"ok": True})
        assert store.reclaim_expired_leases(now=9999.0) == []
        assert store.get_job("J1").status == "COMPLETED"

    def test_reclaim_is_idempotent(self, store):
        """重复回收不重复消耗额度。"""
        store.create_job("J1", "SKILL", max_attempts=3)
        store.claim_job("w-dead", lease_seconds=10, now=1000.0)
        store.reclaim_expired_leases(now=1020.0, backoff_base=0.01)
        assert store.reclaim_expired_leases(now=1030.0, backoff_base=0.01) == []
        assert store.get_job("J1").attempts == 1

    def test_stale_worker_cannot_write_back(self, store):
        """被回收后原持有者无法写回结果（至少一次语义下防双写）。"""
        store.create_job("J1", "SKILL", max_attempts=3)
        store.claim_job("w-dead", lease_seconds=10, now=1000.0)
        store.reclaim_expired_leases(now=1020.0, backoff_base=0.01)
        assert store.complete_job("J1", "w-dead", {"stale": True}) is None
        assert store.fail_job("J1", "w-dead", error_message="stale") is None
        assert store.get_job("J1").result is None


class TestRestartContinuation:
    """重启接续语义。"""

    def test_new_worker_takes_over_reclaimed_job(self, store):
        """新 Worker 接手被回收的 Job 并跑到 COMPLETED。"""
        store.create_job("J1", "SKILL", {"n": 7}, max_attempts=3)
        store.claim_job("w-dead", lease_seconds=1, now=time.time() - 100)

        w = _worker(store, worker_id="w-new", max_jobs=1)
        w.register("SKILL", lambda job: {"n": job.payload["n"] * 2})
        w.run_forever()

        job = store.get_job("J1")
        assert job.status == "COMPLETED"
        assert job.result == {"n": 14}
        assert job.attempts == 2  # 崩溃那次 + 本次
        assert w.stats.reclaimed >= 1

    def test_payload_survives_crash(self, store):
        """崩溃后入参不丢失（持久化在 SQLite）。"""
        payload = {"customerId": "C001", "nested": {"k": [1, 2, 3]}}
        store.create_job("J1", "SKILL", payload, max_attempts=3)
        store.claim_job("w-dead", lease_seconds=1, now=time.time() - 100)
        store.reclaim_expired_leases(backoff_base=0.01)
        assert store.get_job("J1").payload == payload

    def test_queue_state_survives_reopen(self, tmp_path):
        """重开数据库后队列状态完整（跨进程恢复的基础）。"""
        db = tmp_path / "runtime.db"
        first = RuntimeStore(db)
        first.create_job("J1", "SKILL", max_attempts=3)
        first.create_job("J2", "SKILL", max_attempts=1)
        first.claim_job("w-dead", lease_seconds=1, now=time.time() - 100)

        reopened = RuntimeStore(db)
        assert reopened.get_job("J1").attempts == 1
        assert reopened.queue_stats()["by_status"]["RUNNING"] == 1
        assert reopened.reclaim_expired_leases(backoff_base=0.01) == ["J1"]

    def test_dead_letter_survives_restart(self, tmp_path):
        """dead-letter 状态跨重启保留，不会被误重放。"""
        db = tmp_path / "runtime.db"
        s1 = RuntimeStore(db)
        s1.create_job("J1", "SKILL", max_attempts=1)
        s1.claim_job("w1")
        s1.fail_job("J1", "w1", error_message="boom")

        s2 = RuntimeStore(db)
        assert s2.get_job("J1").dead_letter is True
        assert s2.claim_job("w2") is None


class TestRealProcessCrash:
    """真实子进程 kill -9 崩溃恢复（M2.4 验收核心）。"""

    @staticmethod
    def _crash_script(db: Path, marker: Path) -> str:
        """生成子进程脚本：领取 Job、写就绪标记、然后挂起等待被强杀。"""
        return textwrap.dedent(f"""
            import sys, time, pathlib
            sys.path.insert(0, {str(SRC)!r})
            from dkws.infrastructure.runtime_store import RuntimeStore

            store = RuntimeStore(pathlib.Path({str(db)!r}))
            job = store.claim_job("w-crash", lease_seconds=1.0)
            assert job is not None, "子进程未能领取 Job"
            pathlib.Path({str(marker)!r}).write_text(job.job_id)
            # 不续约、不退出：模拟进程卡死后被 kill -9
            while True:
                time.sleep(0.05)
        """).strip()

    def test_kill_9_job_is_reclaimed_and_reprocessed(self, tmp_path):
        """子进程被 kill -9 后，Job 被回收并由新 Worker 跑到 COMPLETED。

        这是崩溃恢复的端到端证明：被强杀的进程没有任何机会做清理，
        全靠 lease 到期由 :meth:`reclaim_expired_leases` 兜住。
        """
        db = tmp_path / "runtime.db"
        marker = tmp_path / "claimed.txt"
        store = RuntimeStore(db)
        store.create_job("J-CRASH", "SKILL", {"v": 21}, max_attempts=3)

        script = tmp_path / "crash_worker.py"
        script.write_text(self._crash_script(db, marker), encoding="utf-8")
        proc = subprocess.Popen([sys.executable, str(script)],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            deadline = time.time() + 30
            while time.time() < deadline and not marker.exists():
                if proc.poll() is not None:
                    _, err = proc.communicate()
                    pytest.fail(f"子进程提前退出：{err.decode('utf-8', 'replace')}")
                time.sleep(0.05)
            assert marker.exists(), "子进程未在超时内领取 Job"
            assert marker.read_text().strip() == "J-CRASH"

            claimed = store.get_job("J-CRASH")
            assert claimed.status == "RUNNING"
            assert claimed.lease_owner == "w-crash"
            assert claimed.attempts == 1

            # 强杀：不给任何清理机会
            os.kill(proc.pid, signal.SIGKILL)
            proc.wait(timeout=15)
            assert proc.returncode != 0

            # lease 未被释放，仍指向已死进程
            assert store.get_job("J-CRASH").lease_owner == "w-crash"

            # 等待 lease 过期后由新 Worker 恢复
            time.sleep(1.2)
            w = _worker(store, worker_id="w-recover", max_jobs=1)
            w.register("SKILL", lambda job: {"v": job.payload["v"] * 2})
            w.run_forever()

            job = store.get_job("J-CRASH")
            assert job.status == "COMPLETED"
            assert job.result == {"v": 42}
            assert job.attempts == 2
            assert w.stats.reclaimed >= 1
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=10)

    def test_kill_9_exhausted_attempts_goes_dead_letter(self, tmp_path):
        """崩溃且额度已耗尽时进入 dead-letter，不无限重试。"""
        db = tmp_path / "runtime.db"
        marker = tmp_path / "claimed.txt"
        store = RuntimeStore(db)
        store.create_job("J-CRASH", "SKILL", max_attempts=1)

        script = tmp_path / "crash_worker.py"
        script.write_text(self._crash_script(db, marker), encoding="utf-8")
        proc = subprocess.Popen([sys.executable, str(script)],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            deadline = time.time() + 30
            while time.time() < deadline and not marker.exists():
                if proc.poll() is not None:
                    _, err = proc.communicate()
                    pytest.fail(f"子进程提前退出：{err.decode('utf-8', 'replace')}")
                time.sleep(0.05)
            assert marker.exists()

            os.kill(proc.pid, signal.SIGKILL)
            proc.wait(timeout=15)

            time.sleep(1.2)
            reclaimed = store.reclaim_expired_leases()
            assert reclaimed == ["J-CRASH"]
            job = store.get_job("J-CRASH")
            assert job.dead_letter is True
            assert job.error_code == "LEASE_EXPIRED"
            # 人工重放后可再次执行
            store.requeue_dead_letter("J-CRASH", extra_attempts=1)
            w = _worker(store, worker_id="w-recover", max_jobs=1)
            w.register("SKILL", lambda job: {"ok": True})
            w.run_forever()
            assert store.get_job("J-CRASH").status == "COMPLETED"
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=10)

    def test_sigterm_graceful_shutdown_completes_job(self, tmp_path):
        """SIGTERM 优雅停机：当前 Job 正常完成，不留悬挂 lease。"""
        db = tmp_path / "runtime.db"
        ready = tmp_path / "ready.txt"
        store = RuntimeStore(db)
        store.create_job("J-GRACE", "SKILL", max_attempts=3)

        script = tmp_path / "graceful_worker.py"
        script.write_text(textwrap.dedent(f"""
            import sys, pathlib, time
            sys.path.insert(0, {str(SRC)!r})
            from dkws.infrastructure.runtime_store import RuntimeStore
            from dkws.infrastructure.worker import JobWorker, WorkerConfig

            store = RuntimeStore(pathlib.Path({str(db)!r}))
            worker = JobWorker(store, WorkerConfig(
                worker_id="w-grace", lease_seconds=10.0, poll_interval=0.05))
            worker.install_signal_handlers()

            def handler(job):
                pathlib.Path({str(ready)!r}).write_text("running")
                time.sleep(0.6)
                return {{"graceful": True}}

            worker.register("SKILL", handler)
            worker.run_forever()
        """).strip(), encoding="utf-8")

        proc = subprocess.Popen([sys.executable, str(script)],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            deadline = time.time() + 30
            while time.time() < deadline and not ready.exists():
                if proc.poll() is not None:
                    _, err = proc.communicate()
                    pytest.fail(f"子进程提前退出：{err.decode('utf-8', 'replace')}")
                time.sleep(0.05)
            assert ready.exists(), "Handler 未在超时内开始执行"

            # Handler 执行中发送 SIGTERM：应等待当前 Job 完成后退出
            proc.send_signal(signal.SIGTERM)
            proc.wait(timeout=20)

            job = store.get_job("J-GRACE")
            assert job.status == "COMPLETED"
            assert job.result == {"graceful": True}
            assert job.lease_owner is None
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=10)
