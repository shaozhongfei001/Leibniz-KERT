"""M2.4 持久化异步作业集成测试：入队、Worker 接续、STATUS.md 派生投影。

验证 Owner 决策路线 C′ 的两条核心约束：
1. **SQLite 为状态唯一权威**——所有状态推进以库为准；
2. **STATUS.md 为派生只读投影**——仍按 §9.14 契约写出，内容与库一致。
"""

from __future__ import annotations

import pytest

from dkws.application.jobs import JobController
from dkws.application.skills import SkillExecutionService
from dkws.domain.errors import ConflictError
from dkws.infrastructure.fs import WorkspaceWriter
from dkws.infrastructure.runtime_store import RuntimeStore
from dkws.infrastructure.worker import JobWorker, WorkerConfig

SKILL_ID = "skill-customer-outreach-script"
SKILL_REQUEST = {"customerId": "CUST-CORP-0001"}


@pytest.fixture()
def store(ws) -> RuntimeStore:
    """工作区内的 Runtime Store（落在 90_control/runtime 下）。"""
    return RuntimeStore(ws / "90_control" / "runtime" / "runtime.db")


def _controller(ws, store, **overrides) -> JobController:
    """构造接入 Store 的 JobController。"""
    kwargs = {"job_type": "SKILL", "requested_by": "test",
              "idempotency_key": "idem-1", "runtime_store": store}
    kwargs.update(overrides)
    return JobController(ws, WorkspaceWriter(ws), **kwargs)


def _status_text(ws, job_id: str) -> str:
    """读取派生的 STATUS.md 文本。"""
    return (ws / "90_control" / "jobs" / job_id / "STATUS.md").read_text(encoding="utf-8")


# ---------------------------------------------------------------- 状态权威在 SQLite

class TestStateAuthority:
    """SQLite 为状态唯一权威。"""

    def test_controller_registers_job_in_store(self, ws, store):
        """控制器初始化即在权威表登记 Job。"""
        job = _controller(ws, store)
        record = store.get_job(job.job_id)
        assert record is not None
        assert record.job_type == "SKILL"
        assert record.status == "PENDING"
        assert record.idem_key == "idem-1"

    def test_start_syncs_running_to_store(self, ws, store):
        """start() 后库中状态为 RUNNING。"""
        job = _controller(ws, store).start()
        assert store.get_job(job.job_id).status == "RUNNING"

    def test_finish_syncs_completed_to_store(self, ws, store):
        """finish() 后库中为 COMPLETED 且带结果。"""
        job = _controller(ws, store).start()
        job.finish(output_refs=[{"path": "a.md"}], input_count=1, output_count=1)
        record = store.get_job(job.job_id)
        assert record.status == "COMPLETED"
        assert record.result["output_refs"] == [{"path": "a.md"}]

    def test_fail_syncs_failed_to_store(self, ws, store):
        """fail() 后库中为 FAILED 且带错误码。"""
        job = _controller(ws, store).start()
        job.fail("E_TEST", "注入失败")
        record = store.get_job(job.job_id)
        assert record.status == "FAILED"
        assert record.error_code == "E_TEST"
        assert record.error_message == "注入失败"

    def test_progress_synced_to_store(self, ws, store):
        """进度同步到库中 payload。"""
        job = _controller(ws, store).start()
        job.update(progress=42)
        assert store.get_job(job.job_id).payload["progress"] == 42

    def test_idempotency_resolved_from_store(self, ws, store):
        """幂等判定走 SQLite：终态后重复提交为 NO_OP。"""
        first = _controller(ws, store).start()
        first.finish(output_refs=[], input_count=1, output_count=1)
        again = _controller(ws, store)
        assert again.noop is True
        assert again.job_id == first.job_id

    def test_active_job_conflicts(self, ws, store):
        """存在活跃 Job 时重复提交冲突。"""
        _controller(ws, store).start()
        with pytest.raises(ConflictError, match="幂等键冲突"):
            _controller(ws, store)

    def test_job_ids_do_not_collide(self, ws, store):
        """序号由库中最大值推导，多次提交不撞号。"""
        a = _controller(ws, store, idempotency_key="k1").start()
        a.finish(output_refs=[], input_count=1, output_count=1)
        b = _controller(ws, store, idempotency_key="k2").start()
        assert a.job_id != b.job_id


# ---------------------------------------------------------------- STATUS.md 派生投影

class TestDerivedProjection:
    """STATUS.md / RUN_REPORT.md 为派生只读投影（FR-CTL 审计产物保留）。"""

    def test_status_md_still_written(self, ws, store):
        """启用 Store 后 STATUS.md 仍按契约写出。"""
        job = _controller(ws, store).start()
        assert (ws / "90_control" / "jobs" / job.job_id / "STATUS.md").is_file()

    def test_status_md_matches_store(self, ws, store):
        """派生内容与权威表一致（不领先、不落后）。"""
        job = _controller(ws, store).start()
        job.update(progress=50)
        assert store.get_job(job.job_id).status == "RUNNING"
        assert "status: RUNNING" in _status_text(ws, job.job_id)

    def test_terminal_status_md_matches_store(self, ws, store):
        """终态时派生内容同步为 COMPLETED。"""
        job = _controller(ws, store).start()
        job.finish(output_refs=[], input_count=1, output_count=1)
        assert store.get_job(job.job_id).status == "COMPLETED"
        assert "status: COMPLETED" in _status_text(ws, job.job_id)

    def test_failed_status_md_matches_store(self, ws, store):
        """失败时派生内容同步为 FAILED（既有 recovery 测试依赖此行为）。"""
        job = _controller(ws, store).start()
        job.fail("E_X", "boom")
        assert store.get_job(job.job_id).status == "FAILED"
        assert "status: FAILED" in _status_text(ws, job.job_id)

    def test_run_report_written_on_finish(self, ws, store):
        """完成后写出 RUN_REPORT.md（§9.15）。"""
        job = _controller(ws, store).start()
        job.finish(output_refs=[], input_count=1, output_count=1)
        assert (ws / "90_control" / "jobs" / job.job_id / "RUN_REPORT.md").is_file()

    def test_file_mode_still_works_without_store(self, ws):
        """未注入 Store 时保持 M1 纯文件行为（不破坏既有调用方）。"""
        job = JobController(ws, WorkspaceWriter(ws), job_type="SKILL",
                            requested_by="test", idempotency_key="no-store")
        job.start()
        job.finish(output_refs=[], input_count=1, output_count=1)
        assert "status: COMPLETED" in _status_text(ws, job.job_id)


# ---------------------------------------------------------------- 持久化异步执行

class TestPersistentAsyncExecution:
    """execute_async 入队 + Worker 接续。"""

    def test_execute_async_enqueues_without_running(self, ws, store):
        """注入 Store 后仅入队，不在调用线程内执行。"""
        svc = SkillExecutionService(ws, runtime_store=store)
        job_id = svc.execute_async(SKILL_ID, "REQ-A1", SKILL_REQUEST)
        record = store.get_job(job_id)
        assert record.status == "PENDING"
        assert record.payload["skillId"] == SKILL_ID
        assert record.payload["request"] == SKILL_REQUEST

    def test_worker_picks_up_enqueued_job(self, ws, store):
        """Worker 领取入队的 Job 并执行到 COMPLETED。"""
        svc = SkillExecutionService(ws, runtime_store=store)
        job_id = svc.execute_async(SKILL_ID, "REQ-A2", SKILL_REQUEST)

        worker = JobWorker(store, WorkerConfig(
            worker_id="w-it", lease_seconds=30.0, poll_interval=0.01, max_jobs=1))

        def handle(job):
            """按 payload 执行 Skill。"""
            result = svc.execute(job.payload["skillId"], job.job_id,
                                 job.payload["request"])
            return {"status": result.status}

        worker.register("SKILL", handle)
        worker.run_forever()

        record = store.get_job(job_id)
        assert record.status == "COMPLETED"
        assert record.result["status"] == "ok"
        assert worker.stats.completed == 1

    def test_enqueued_job_survives_restart(self, ws):
        """入队的 Job 跨进程重启不丢失（M2.4 核心价值）。"""
        db = ws / "90_control" / "runtime" / "runtime.db"
        svc = SkillExecutionService(ws, runtime_store=RuntimeStore(db))
        job_id = svc.execute_async(SKILL_ID, "REQ-A3", SKILL_REQUEST)

        # 模拟重启：新建 Store 实例读取
        reopened = RuntimeStore(db)
        record = reopened.get_job(job_id)
        assert record.status == "PENDING"
        assert record.payload["skillId"] == SKILL_ID
        assert reopened.claim_job("w-after-restart") is not None

    def test_thread_mode_without_store(self, ws):
        """未注入 Store 时沿用线程模式（M1 兼容）。"""
        svc = SkillExecutionService(ws)
        job_id = svc.execute_async(SKILL_ID, "REQ-A4", SKILL_REQUEST)
        assert job_id.startswith("JOB-SKILL-")
        # 线程模式下 STATUS.md 由控制器写出
        assert (ws / "90_control" / "jobs" / job_id / "STATUS.md").is_file()

    def test_queue_stats_reflects_enqueued(self, ws, store):
        """队列统计反映入队的 Job。"""
        svc = SkillExecutionService(ws, runtime_store=store)
        svc.execute_async(SKILL_ID, "REQ-A5", SKILL_REQUEST)
        stats = store.queue_stats()
        assert stats["by_status"]["PENDING"] == 1
        assert stats["claimable"] == 1
