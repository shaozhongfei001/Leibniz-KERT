"""M2.4 Worker 运行时单元测试：Handler 路由、lease 续约、退避重试、停机。"""

from __future__ import annotations

import threading
import time

import pytest

from dkws.infrastructure.runtime_store import RuntimeStore
from dkws.infrastructure.worker import (
    JobWorker,
    NonRetryableJobError,
    WorkerConfig,
    build_worker_config_from_env,
    default_worker_id,
)


@pytest.fixture()
def store(tmp_path) -> RuntimeStore:
    """临时 Runtime Store。"""
    return RuntimeStore(tmp_path / "runtime.db")


def _worker(store: RuntimeStore, **overrides) -> JobWorker:
    """构造测试用 Worker（默认短 lease、无退避等待，可按需覆盖任意字段）。"""
    defaults = {"worker_id": "w-test", "lease_seconds": 5.0, "poll_interval": 0.01,
                "reclaim_interval": 0.0, "backoff_base": 0.01}
    defaults.update(overrides)
    return JobWorker(store, WorkerConfig(**defaults))


# ---------------------------------------------------------------- 注册与配置

def test_register_and_list_types(store):
    """注册 Handler 后可列出已注册类型。"""
    w = _worker(store)
    w.register("SKILL", lambda job: {"ok": True})
    w.register("INGEST", lambda job: None)
    assert w.registered_types == ("INGEST", "SKILL")


def test_register_rejects_empty_type(store):
    """job_type 不能为空。"""
    with pytest.raises(ValueError, match="job_type"):
        _worker(store).register("", lambda job: None)


def test_default_worker_id_is_unique():
    """默认 Worker ID 含随机后缀，重复调用不相同。"""
    assert default_worker_id() != default_worker_id()


def test_heartbeat_interval_derived_from_lease():
    """心跳间隔按 lease 比例推导，且有下限。"""
    assert WorkerConfig(lease_seconds=30.0).heartbeat_interval() == pytest.approx(12.0)
    assert WorkerConfig(lease_seconds=0.01).heartbeat_interval() == pytest.approx(0.05)


def test_build_config_from_env():
    """从环境变量构造配置。"""
    cfg = build_worker_config_from_env({
        "DKWS_WORKER_ID": "w-env",
        "DKWS_WORKER_JOB_TYPES": "SKILL, INGEST ",
        "DKWS_WORKER_LEASE_SECONDS": "12.5",
        "DKWS_WORKER_MAX_JOBS": "3",
    })
    assert cfg.worker_id == "w-env"
    assert cfg.job_types == ("SKILL", "INGEST")
    assert cfg.lease_seconds == pytest.approx(12.5)
    assert cfg.max_jobs == 3


def test_build_config_defaults_when_env_empty():
    """空环境时使用默认值并自动生成 worker_id。"""
    cfg = build_worker_config_from_env({})
    assert cfg.worker_id
    assert cfg.job_types == ()
    assert cfg.max_jobs == 0


def test_build_config_rejects_invalid_number():
    """非法数字环境变量报错。"""
    with pytest.raises(ValueError, match="需为数字"):
        build_worker_config_from_env({"DKWS_WORKER_LEASE_SECONDS": "soon"})


def test_build_config_rejects_invalid_int():
    """非法整数环境变量报错。"""
    with pytest.raises(ValueError, match="需为整数"):
        build_worker_config_from_env({"DKWS_WORKER_MAX_JOBS": "many"})


# ---------------------------------------------------------------- 单次执行

def test_run_once_returns_none_when_idle(store):
    """无 Job 时返回 None。"""
    assert _worker(store).run_once() is None


def test_run_once_executes_handler_and_completes(store):
    """Handler 成功后 Job 置 COMPLETED，结果落库。"""
    store.create_job("J1", "SKILL", {"n": 1})
    w = _worker(store)
    seen = []
    w.register("SKILL", lambda job: seen.append(job.payload) or {"doubled": 2})
    w.run_once()
    job = store.get_job("J1")
    assert job.status == "COMPLETED"
    assert job.result == {"doubled": 2}
    assert seen == [{"n": 1}]
    assert w.stats.completed == 1


def test_handler_returning_none_is_ok(store):
    """Handler 返回 None 视为空结果，仍算成功。"""
    store.create_job("J1", "SKILL")
    w = _worker(store)
    w.register("SKILL", lambda job: None)
    w.run_once()
    assert store.get_job("J1").status == "COMPLETED"


def test_unregistered_type_goes_dead_letter(store):
    """未注册类型直接 dead-letter（重试无益）。"""
    store.create_job("J1", "UNKNOWN", max_attempts=5)
    w = _worker(store)
    w.run_once()
    job = store.get_job("J1")
    assert job.dead_letter is True
    assert job.error_code == "NO_HANDLER"
    assert w.stats.dead_lettered == 1


def test_handler_exception_triggers_retry(store):
    """Handler 抛异常后置 RETRYING 并记录退避。"""
    store.create_job("J1", "SKILL", max_attempts=3)
    w = _worker(store)
    w.register("SKILL", lambda job: (_ for _ in ()).throw(RuntimeError("boom")))
    w.run_once()
    job = store.get_job("J1")
    assert job.status == "RETRYING"
    assert job.error_code == "HANDLER_ERROR"
    assert "boom" in job.error_message
    assert w.stats.retried == 1


def test_non_retryable_error_goes_dead_letter(store):
    """NonRetryableJobError 立即 dead-letter，不消耗剩余额度。"""
    store.create_job("J1", "SKILL", max_attempts=5)
    w = _worker(store)

    def handler(job):
        """抛出不可重试错误。"""
        raise NonRetryableJobError("入参非法", error_code="VALIDATION")

    w.register("SKILL", handler)
    w.run_once()
    job = store.get_job("J1")
    assert job.dead_letter is True
    assert job.error_code == "VALIDATION"
    assert job.attempts == 1


def test_retry_until_dead_letter(store):
    """反复失败直至额度耗尽进入 dead-letter。"""
    store.create_job("J1", "SKILL", max_attempts=2)
    w = _worker(store)
    w.register("SKILL", lambda job: (_ for _ in ()).throw(RuntimeError("boom")))
    w.run_once()
    time.sleep(0.05)  # 越过 backoff_base=0.01 的退避窗口
    w.run_once()
    job = store.get_job("J1")
    assert job.dead_letter is True
    assert job.attempts == 2
    assert w.stats.dead_lettered == 1


def test_eventual_success_after_retry(store):
    """先失败后成功，终态为 COMPLETED。"""
    store.create_job("J1", "SKILL", max_attempts=3)
    w = _worker(store)
    calls = {"n": 0}

    def flaky(job):
        """首次失败，其后成功。"""
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("transient")
        return {"attempt": calls["n"]}

    w.register("SKILL", flaky)
    w.run_once()
    time.sleep(0.05)
    w.run_once()
    job = store.get_job("J1")
    assert job.status == "COMPLETED"
    assert job.result == {"attempt": 2}


def test_job_types_filter_respected(store):
    """Worker 只领取自己声明的类型。"""
    store.create_job("J1", "INGEST")
    w = _worker(store, job_types=("SKILL",))
    w.register("SKILL", lambda job: None)
    assert w.run_once() is None
    assert store.get_job("J1").status == "PENDING"


# ---------------------------------------------------------------- lease 续约

def test_heartbeat_keeps_lease_alive(store):
    """长耗时 Handler 期间 lease 被持续续约，不会被回收。"""
    store.create_job("J1", "SKILL")
    w = _worker(store, lease_seconds=0.2)

    def slow(job):
        """执行时长超过单个 lease 周期。"""
        time.sleep(0.7)
        return {"ok": True}

    w.register("SKILL", slow)
    w.run_once()
    assert store.get_job("J1").status == "COMPLETED"
    assert w.stats.lease_lost == 0


def test_lease_lost_blocks_result_writeback(store):
    """lease 失效后拒绝写回结果，避免与接管者双写（不依赖时序的确定性验证）。

    直接验证存储层契约：非持有者调用 ``complete_job`` / ``fail_job`` 均返回
    ``None``，这是 Worker 侧 ``LeaseLostError`` 分支所依赖的底层保证。
    """
    store.create_job("J1", "SKILL", max_attempts=3)
    store.claim_job("w-dead", lease_seconds=0.01, now=time.time() - 100)
    # lease 超时被回收，Job 交回队列
    assert store.reclaim_expired_leases(backoff_base=0.01) == ["J1"]
    assert store.get_job("J1").lease_owner is None
    # 原持有者此时写回结果必须失败
    assert store.complete_job("J1", "w-dead", {"stale": True}) is None
    assert store.fail_job("J1", "w-dead", error_message="stale") is None
    job = store.get_job("J1")
    assert job.status == "RETRYING"
    assert job.result is None


def test_worker_counts_lease_lost(store):
    """Handler 执行完成前 lease 已失效时，Worker 记入 lease_lost 且不算完成。"""
    store.create_job("J1", "SKILL", max_attempts=3)
    w = _worker(store, lease_seconds=60.0)

    def steal_then_return(job):
        """在返回前把 lease 转移给他人，模拟 lease 被接管。"""
        conn = store.connect()
        try:
            conn.execute("UPDATE jobs SET lease_owner='w-other' WHERE job_id=?", ("J1",))
            conn.commit()
        finally:
            conn.close()
        return {"ok": True}

    w.register("SKILL", steal_then_return)
    w.run_once()
    assert w.stats.completed == 0
    assert w.stats.lease_lost == 1
    # 结果未写回，仍由接管者持有
    assert store.get_job("J1").result is None


def test_stolen_lease_job_can_be_reprocessed(store):
    """lease 失效交回的 Job 可被其他 Worker 重新处理至完成。"""
    store.create_job("J1", "SKILL", max_attempts=3)
    store.claim_job("w-dead", lease_seconds=0.01, now=time.time() - 100)
    store.reclaim_expired_leases(backoff_base=0.01)

    w2 = _worker(store, worker_id="w-2")
    w2.register("SKILL", lambda job: {"by": "w-2"})
    time.sleep(0.05)
    w2.run_once()
    job = store.get_job("J1")
    assert job.status == "COMPLETED"
    assert job.result == {"by": "w-2"}


# ---------------------------------------------------------------- 循环与停机

def test_run_forever_stops_at_max_jobs(store):
    """达到 max_jobs 后退出循环。"""
    for i in range(5):
        store.create_job(f"J{i}", "SKILL")
    w = _worker(store, max_jobs=3)
    w.register("SKILL", lambda job: {"ok": True})
    stats = w.run_forever()
    assert stats.claimed == 3
    assert stats.completed == 3


def test_run_forever_stops_on_request(store):
    """请求停机后循环退出。"""
    w = _worker(store)
    w.register("SKILL", lambda job: None)
    stopper = threading.Timer(0.15, w.request_stop)
    stopper.start()
    w.run_forever()
    stopper.cancel()
    assert w.stopping() is True


def test_run_forever_drains_queue(store):
    """循环可处理完队列中全部 Job。"""
    for i in range(4):
        store.create_job(f"J{i}", "SKILL")
    w = _worker(store, max_jobs=4)
    w.register("SKILL", lambda job: {"ok": True})
    w.run_forever()
    assert store.queue_stats()["by_status"].get("COMPLETED") == 4


def test_reclaim_runs_in_loop(store):
    """循环中会回收过期 lease，使遗留 Job 重新可领。"""
    store.create_job("J1", "SKILL", max_attempts=3)
    # 模拟其他 Worker 领取后崩溃：lease 立即过期
    store.claim_job("w-dead", lease_seconds=0.01, now=time.time() - 100)
    w = _worker(store, max_jobs=1)
    w.register("SKILL", lambda job: {"recovered": True})
    w.run_forever()
    job = store.get_job("J1")
    assert job.status == "COMPLETED"
    assert job.result == {"recovered": True}
    assert w.stats.reclaimed >= 1


def test_install_signal_handlers_is_safe(store):
    """注册信号处理器不抛异常（非主线程时静默跳过）。"""
    _worker(store).install_signal_handlers()


def test_stats_initial_zero(store):
    """初始计数为零。"""
    stats = _worker(store).stats
    assert (stats.claimed, stats.completed, stats.retried,
            stats.dead_lettered, stats.lease_lost, stats.reclaimed) == (0, 0, 0, 0, 0, 0)
