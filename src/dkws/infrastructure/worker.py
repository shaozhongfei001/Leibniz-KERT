"""持久化异步 Worker 运行时（M2.4）。

职责：从 SQLite Runtime Store 原子领取 Job，在 lease 租约保护下执行注册的
Handler，按结果完成或按指数退避重试，重试额度耗尽后进入 dead-letter。

设计要点：
- **状态权威在 SQLite**（Owner 决策路线 C′）。Worker 自身不持久化任何状态，
  被 ``kill -9`` 后所有进度均可从库中恢复。
- **lease 租约 + 心跳**：领取时获得带过期时间的 lease；执行期间由后台线程
  周期性续约。进程崩溃后无人续约，lease 到期即被 :meth:`reclaim_expired_leases`
  回收，从而实现崩溃恢复。
- **续约失败即中止**：若心跳发现 lease 已被他人接管（例如本进程曾长时间停顿
  导致 lease 超时被回收），立即置中止标志，避免同一 Job 被重复执行两次。
- **优雅停机**：收到 SIGTERM/SIGINT 后不再领取新 Job，等待当前 Job 结束。

不引入外部 MQ / Redis / Celery：单机单实例，依 ADR-015。
"""

from __future__ import annotations

import logging
import os
import signal
import socket
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field

from dkws.infrastructure.runtime_store import (
    DEFAULT_BACKOFF_BASE_SECONDS,
    DEFAULT_BACKOFF_FACTOR,
    DEFAULT_BACKOFF_MAX_SECONDS,
    DEFAULT_LEASE_SECONDS,
    JobRecord,
    RuntimeStore,
)

logger = logging.getLogger(__name__)

#: Handler 签名：接收 Job 记录，返回结果字典（``None`` 视为空结果）
JobHandler = Callable[[JobRecord], "dict | None"]

#: 默认轮询间隔（秒）——无可领取 Job 时的空转等待
DEFAULT_POLL_INTERVAL = 1.0

#: 心跳间隔相对 lease 时长的比例：在 lease 过期前留足续约余量
HEARTBEAT_RATIO = 0.4


class NonRetryableJobError(Exception):
    """Handler 抛出此异常表示错误不可重试，直接进入 dead-letter。

    适用于入参非法、业务规则拒绝等重试也不会成功的场景，
    避免无意义地消耗重试额度与执行资源。
    """

    def __init__(self, message: str, *, error_code: str = "NON_RETRYABLE"):
        """记录错误信息与分类码。"""
        super().__init__(message)
        self.error_code = error_code


class LeaseLostError(Exception):
    """执行期间 lease 已被他人接管，本次执行结果不可写回。"""


def default_worker_id() -> str:
    """生成默认 Worker 标识：``主机名-进程号-随机后缀``。

    含随机后缀以便同主机同进程重启后可区分（PID 可能复用）。
    """
    return f"{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:6]}"


@dataclass
class WorkerConfig:
    """Worker 运行参数。

    Attributes:
        worker_id: 本 Worker 标识，写入 ``lease_owner``。
        job_types: 限定领取的业务类型；空表示不限。
        lease_seconds: lease 租约时长。
        poll_interval: 空闲轮询间隔。
        reclaim_interval: 执行 lease 回收扫描的间隔。
        max_jobs: 处理指定数量后退出（``0`` 表示不限，用于测试与批处理）。
        backoff_base/backoff_factor/backoff_max: 指数退避参数。
    """

    worker_id: str = field(default_factory=default_worker_id)
    job_types: tuple[str, ...] = ()
    lease_seconds: float = DEFAULT_LEASE_SECONDS
    poll_interval: float = DEFAULT_POLL_INTERVAL
    reclaim_interval: float = 5.0
    max_jobs: int = 0
    backoff_base: float = DEFAULT_BACKOFF_BASE_SECONDS
    backoff_factor: float = DEFAULT_BACKOFF_FACTOR
    backoff_max: float = DEFAULT_BACKOFF_MAX_SECONDS

    def heartbeat_interval(self) -> float:
        """心跳间隔：lease 时长的固定比例，至少 0.05 秒。"""
        return max(0.05, self.lease_seconds * HEARTBEAT_RATIO)


@dataclass
class WorkerStats:
    """Worker 运行计数（进程内，仅用于观测与测试断言）。"""

    claimed: int = 0
    completed: int = 0
    retried: int = 0
    dead_lettered: int = 0
    lease_lost: int = 0
    reclaimed: int = 0


class JobWorker:
    """持久化异步 Worker。

    典型用法::

        worker = JobWorker(store, WorkerConfig())
        worker.register("SKILL", handle_skill)
        worker.run_forever()          # 或 worker.run_once() 处理单个 Job

    线程模型：主线程执行 Handler，另起一个 daemon 线程做 lease 续约。
    Handler 内部无需感知 lease，但**应支持被中断后重跑**（至少一次语义）。
    """

    def __init__(self, store: RuntimeStore, config: WorkerConfig | None = None,
                 *, time_source: Callable[[], float] | None = None):
        """绑定 Store 与配置；``time_source`` 便于测试注入可控时钟。"""
        self._store = store
        self._config = config or WorkerConfig()
        self._now = time_source or time.time
        self._handlers: dict[str, JobHandler] = {}
        self._stop = threading.Event()
        self._stats = WorkerStats()
        self._last_reclaim = 0.0

    # ---------------------------------------------------------------- 注册与属性

    def register(self, job_type: str, handler: JobHandler) -> None:
        """注册某业务类型的处理器；重复注册会覆盖。"""
        if not job_type:
            raise ValueError("job_type 不能为空")
        self._handlers[job_type] = handler

    @property
    def config(self) -> WorkerConfig:
        """当前配置。"""
        return self._config

    @property
    def stats(self) -> WorkerStats:
        """运行计数。"""
        return self._stats

    @property
    def registered_types(self) -> tuple[str, ...]:
        """已注册的业务类型。"""
        return tuple(sorted(self._handlers))

    def stopping(self) -> bool:
        """是否已收到停机信号。"""
        return self._stop.is_set()

    def request_stop(self) -> None:
        """请求优雅停机：不再领取新 Job，当前 Job 执行完毕后退出。"""
        self._stop.set()

    # ---------------------------------------------------------------- 主循环

    def install_signal_handlers(self) -> None:
        """注册 SIGTERM/SIGINT 优雅停机处理器（仅主线程可用）。"""
        def _handle(signum, _frame):
            """收到信号后置停机标志。"""
            logger.info("[worker] 收到信号 %s，进入优雅停机", signum)
            self.request_stop()

        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                signal.signal(sig, _handle)
            except (ValueError, OSError):
                # 非主线程或平台不支持时跳过，不影响功能
                logger.debug("[worker] 无法注册信号 %s", sig)

    def run_forever(self) -> WorkerStats:
        """持续领取并处理 Job，直到收到停机信号或达到 ``max_jobs``。"""
        logger.info("[worker] 启动 worker_id=%s types=%s lease=%.1fs",
                    self._config.worker_id,
                    self.registered_types or "(全部)", self._config.lease_seconds)
        while not self._stop.is_set():
            self._maybe_reclaim()
            processed = self.run_once()
            if processed is None:
                # 无可领取 Job：等待一个轮询周期（可被停机信号提前唤醒）
                self._stop.wait(self._config.poll_interval)
                continue
            if self._config.max_jobs and self._stats.claimed >= self._config.max_jobs:
                logger.info("[worker] 已达 max_jobs=%d，退出", self._config.max_jobs)
                break
        logger.info("[worker] 停止；claimed=%d completed=%d retried=%d dead=%d",
                    self._stats.claimed, self._stats.completed,
                    self._stats.retried, self._stats.dead_lettered)
        return self._stats

    def run_once(self) -> JobRecord | None:
        """领取并处理至多一个 Job。

        Returns:
            被处理的 Job（无论成功或失败）；当前无可领取时返回 ``None``。
        """
        job = self._store.claim_job(
            self._config.worker_id,
            job_types=self._config.job_types or None,
            lease_seconds=self._config.lease_seconds,
            now=self._now())
        if job is None:
            return None
        self._stats.claimed += 1
        self._execute(job)
        return job

    def _maybe_reclaim(self) -> None:
        """按间隔执行 lease 回收，把崩溃 Worker 遗留的 Job 放回队列。"""
        now = self._now()
        if now - self._last_reclaim < self._config.reclaim_interval:
            return
        self._last_reclaim = now
        reclaimed = self._store.reclaim_expired_leases(
            now=now, backoff_base=self._config.backoff_base,
            backoff_factor=self._config.backoff_factor,
            backoff_max=self._config.backoff_max)
        if reclaimed:
            self._stats.reclaimed += len(reclaimed)
            logger.warning("[worker] 回收过期 lease：%s", reclaimed)

    # ---------------------------------------------------------------- 执行单个 Job

    def _execute(self, job: JobRecord) -> None:
        """在 lease 保护下执行 Job，并按结果落终态。"""
        handler = self._handlers.get(job.job_type)
        if handler is None:
            # 未注册的类型属配置问题，重试无益 → 直接 dead-letter
            self._fail(job, f"未注册 job_type={job.job_type} 的处理器",
                       error_code="NO_HANDLER", retryable=False)
            return

        lease_lost = threading.Event()
        stop_heartbeat = threading.Event()
        beat = threading.Thread(target=self._heartbeat_loop,
                                args=(job.job_id, lease_lost, stop_heartbeat),
                                name=f"hb-{job.job_id}", daemon=True)
        beat.start()
        try:
            result = handler(job)
            if lease_lost.is_set():
                raise LeaseLostError(f"Job {job.job_id} 的 lease 已被接管")
            done = self._store.complete_job(job.job_id, self._config.worker_id,
                                            result, now=self._now())
            if done is None:
                raise LeaseLostError(f"Job {job.job_id} 完成时 lease 已失效")
            self._stats.completed += 1
            logger.info("[worker] Job %s 完成（第 %d 次尝试）", job.job_id, job.attempts)
        except LeaseLostError as exc:
            # 结果不可写回：交由 reclaim 机制重新调度，避免双写
            self._stats.lease_lost += 1
            logger.warning("[worker] %s", exc)
        except NonRetryableJobError as exc:
            self._fail(job, str(exc), error_code=exc.error_code, retryable=False)
        except Exception as exc:  # noqa: BLE001 - Worker 需兜住任何 Handler 异常
            self._fail(job, f"{type(exc).__name__}: {exc}",
                       error_code="HANDLER_ERROR", retryable=True)
        finally:
            stop_heartbeat.set()
            beat.join(timeout=2.0)

    def _fail(self, job: JobRecord, message: str, *, error_code: str,
              retryable: bool) -> None:
        """记录失败并按额度决定重试或 dead-letter。"""
        updated = self._store.fail_job(
            job.job_id, self._config.worker_id, error_message=message,
            error_code=error_code, retryable=retryable,
            backoff_base=self._config.backoff_base,
            backoff_factor=self._config.backoff_factor,
            backoff_max=self._config.backoff_max, now=self._now())
        if updated is None:
            self._stats.lease_lost += 1
            logger.warning("[worker] Job %s 失败落库时 lease 已失效", job.job_id)
            return
        if updated.dead_letter:
            self._stats.dead_lettered += 1
            logger.error("[worker] Job %s 进入 dead-letter：%s",
                         job.job_id, updated.dead_letter_reason)
        else:
            self._stats.retried += 1
            logger.warning("[worker] Job %s 第 %d 次尝试失败，将于退避后重试：%s",
                           job.job_id, updated.attempts, message)

    def _heartbeat_loop(self, job_id: str, lease_lost: threading.Event,
                        stop: threading.Event) -> None:
        """后台续约 lease；一旦续约失败即置 ``lease_lost``。"""
        interval = self._config.heartbeat_interval()
        while not stop.wait(interval):
            ok = self._store.heartbeat_job(job_id, self._config.worker_id,
                                           lease_seconds=self._config.lease_seconds,
                                           now=self._now())
            if not ok:
                lease_lost.set()
                logger.warning("[worker] Job %s 续约失败，lease 可能已被接管", job_id)
                return


def build_worker_config_from_env(env: dict[str, str] | None = None) -> WorkerConfig:
    """从环境变量构造 Worker 配置（与 M2.1 配置风格一致）。

    支持的变量：``DKWS_WORKER_ID`` / ``DKWS_WORKER_JOB_TYPES`` /
    ``DKWS_WORKER_LEASE_SECONDS`` / ``DKWS_WORKER_POLL_INTERVAL`` /
    ``DKWS_WORKER_RECLAIM_INTERVAL`` / ``DKWS_WORKER_MAX_JOBS`` /
    ``DKWS_WORKER_BACKOFF_BASE`` / ``DKWS_WORKER_BACKOFF_FACTOR`` /
    ``DKWS_WORKER_BACKOFF_MAX``。
    """
    src = os.environ if env is None else env

    def num(name: str, default: float) -> float:
        """读取浮点环境变量。"""
        raw = src.get(name, "").strip()
        if not raw:
            return default
        try:
            return float(raw)
        except ValueError as exc:
            raise ValueError(f"{name} 需为数字，收到 {raw!r}") from exc

    def integer(name: str, default: int) -> int:
        """读取整型环境变量。"""
        raw = src.get(name, "").strip()
        if not raw:
            return default
        try:
            return int(raw)
        except ValueError as exc:
            raise ValueError(f"{name} 需为整数，收到 {raw!r}") from exc

    types_raw = src.get("DKWS_WORKER_JOB_TYPES", "").strip()
    job_types = tuple(t.strip() for t in types_raw.split(",") if t.strip())
    worker_id = src.get("DKWS_WORKER_ID", "").strip() or default_worker_id()
    return WorkerConfig(
        worker_id=worker_id,
        job_types=job_types,
        lease_seconds=num("DKWS_WORKER_LEASE_SECONDS", DEFAULT_LEASE_SECONDS),
        poll_interval=num("DKWS_WORKER_POLL_INTERVAL", DEFAULT_POLL_INTERVAL),
        reclaim_interval=num("DKWS_WORKER_RECLAIM_INTERVAL", 5.0),
        max_jobs=integer("DKWS_WORKER_MAX_JOBS", 0),
        backoff_base=num("DKWS_WORKER_BACKOFF_BASE", DEFAULT_BACKOFF_BASE_SECONDS),
        backoff_factor=num("DKWS_WORKER_BACKOFF_FACTOR", DEFAULT_BACKOFF_FACTOR),
        backoff_max=num("DKWS_WORKER_BACKOFF_MAX", DEFAULT_BACKOFF_MAX_SECONDS),
    )
