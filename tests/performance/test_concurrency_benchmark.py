"""并发锁竞争性能基准（NFR-006/007）。

测试场景：
- WorkspaceLock 单线程 acquire/release 延迟
- WorkspaceLock 多线程并发不同 scope（无竞争）
- RuntimeStore 并发写入 idempotency 记录
- RuntimeStore 并发写入 job 记录
- RuntimeStore 读取延迟

约束：
- 使用 time.perf_counter 手动计时
- 不依赖 pytest-benchmark
- 使用确定性适配器，不调用真实 LLM
"""

from __future__ import annotations

import hashlib
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


from dkws.infrastructure.locks import WorkspaceLock
from dkws.infrastructure.runtime_store import RuntimeStore


# ---------- WorkspaceLock 基准 ----------

SINGLE_LOCK_THRESHOLD_MS = 10       # 单次 acquire+release < 10ms
CONCURRENT_SCOPE_THRESHOLD_MS = 2000  # 10 线程各 10 次 acquire+release < 2s
CONCURRENT_WRITE_THRESHOLD_MS = 3000  # 10 线程各 10 次写入 < 3s
READ_LATENCY_THRESHOLD_MS = 5.0     # 单次读取 < 5ms


def test_workspace_lock_single_thread_benchmark(tmp_path: Path) -> None:
    """单线程 WorkspaceLock acquire/release 延迟基准。"""
    ws = tmp_path / "ws"
    ws.mkdir()

    times: list[float] = []
    for i in range(50):
        t0 = time.perf_counter()
        with WorkspaceLock(ws, f"bench:single:{i}", job_id=f"JOB-BENCH-{i}", owner="bench"):
            pass
        times.append((time.perf_counter() - t0) * 1000)

    avg_ms = sum(times) / len(times)
    max_ms = max(times)
    assert avg_ms < SINGLE_LOCK_THRESHOLD_MS, (
        f"单线程锁平均延迟 {avg_ms:.2f}ms > {SINGLE_LOCK_THRESHOLD_MS}ms"
    )
    assert max_ms < SINGLE_LOCK_THRESHOLD_MS * 5, (
        f"单线程锁最大延迟 {max_ms:.2f}ms > {SINGLE_LOCK_THRESHOLD_MS * 5}ms"
    )


def test_workspace_lock_concurrent_scopes_benchmark(tmp_path: Path) -> None:
    """多线程并发不同 WorkspaceLock scope（无竞争）基准。"""
    ws = tmp_path / "ws"
    ws.mkdir()

    n_threads = 10
    n_acquires = 10

    def worker(thread_id: int) -> float:
        total = 0.0
        for i in range(n_acquires):
            t0 = time.perf_counter()
            with WorkspaceLock(
                ws, f"bench:scope-t{thread_id}-{i}",
                job_id=f"JOB-BENCH-T{thread_id}-{i}",
                owner=f"bench-t{thread_id}",
            ):
                pass
            total += (time.perf_counter() - t0) * 1000
        return total

    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=n_threads) as pool:
        futures = [pool.submit(worker, tid) for tid in range(n_threads)]
        per_thread = [f.result() for f in as_completed(futures)]
    elapsed_ms = (time.perf_counter() - t0) * 1000

    total_acquires = n_threads * n_acquires
    avg_ms = sum(per_thread) / total_acquires
    assert elapsed_ms < CONCURRENT_SCOPE_THRESHOLD_MS, (
        f"多线程并发 scope 总耗时 {elapsed_ms:.0f}ms > {CONCURRENT_SCOPE_THRESHOLD_MS}ms "
        f"(平均 {avg_ms:.1f}ms/acquire)"
    )


def test_workspace_lock_sequential_same_scope_benchmark(tmp_path: Path) -> None:
    """同 scope 顺序 acquire/release 基准（模拟串行化工作区操作）。"""
    ws = tmp_path / "ws"
    ws.mkdir()

    times: list[float] = []
    for i in range(20):
        t0 = time.perf_counter()
        with WorkspaceLock(ws, "bench:sequential", job_id=f"JOB-SEQ-{i}", owner="bench"):
            pass
        times.append((time.perf_counter() - t0) * 1000)

    avg_ms = sum(times) / len(times)
    assert avg_ms < SINGLE_LOCK_THRESHOLD_MS, (
        f"同 scope 顺序锁平均延迟 {avg_ms:.2f}ms > {SINGLE_LOCK_THRESHOLD_MS}ms"
    )


# ---------- RuntimeStore 并发写入基准 ----------

def test_runtime_store_concurrent_idempotency_writes(tmp_path: Path) -> None:
    """RuntimeStore 并发写入 idempotency 记录基准。"""
    db_path = tmp_path / "runtime" / "bench.db"
    store = RuntimeStore(db_path)

    n_threads = 10
    n_writes = 10

    def writer(thread_id: int) -> None:
        for i in range(n_writes):
            key = f"bench-key-t{thread_id}-{i}"
            req_hash = hashlib.sha256(f"payload-t{thread_id}-{i}".encode()).hexdigest()
            store.remember("bench_scope", key, req_hash)

    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=n_threads) as pool:
        futures = [pool.submit(writer, tid) for tid in range(n_threads)]
        for f in as_completed(futures):
            f.result()
    elapsed_ms = (time.perf_counter() - t0) * 1000

    assert elapsed_ms < CONCURRENT_WRITE_THRESHOLD_MS, (
        f"RuntimeStore 并发写入 {n_threads * n_writes} 条: "
        f"{elapsed_ms:.0f}ms > {CONCURRENT_WRITE_THRESHOLD_MS}ms"
    )


def test_runtime_store_concurrent_job_writes(tmp_path: Path) -> None:
    """RuntimeStore 并发写入 job 记录基准。"""
    db_path = tmp_path / "runtime" / "bench_jobs.db"
    store = RuntimeStore(db_path)

    n_threads = 10
    n_writes = 10

    def job_writer(thread_id: int) -> None:
        for i in range(n_writes):
            job_id = f"JOB-BENCH-T{thread_id}-{i}"
            store.create_job(job_id=job_id, job_type="BENCH_TEST")

    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=n_threads) as pool:
        futures = [pool.submit(job_writer, tid) for tid in range(n_threads)]
        for f in as_completed(futures):
            f.result()
    elapsed_ms = (time.perf_counter() - t0) * 1000

    assert elapsed_ms < CONCURRENT_WRITE_THRESHOLD_MS, (
        f"RuntimeStore 并发 job 写入 {n_threads * n_writes} 条: "
        f"{elapsed_ms:.0f}ms > {CONCURRENT_WRITE_THRESHOLD_MS}ms"
    )


def test_runtime_store_read_after_write(tmp_path: Path) -> None:
    """RuntimeStore 写入后立即读取延迟基准。"""
    db_path = tmp_path / "runtime" / "bench_rw.db"
    store = RuntimeStore(db_path)

    # 先写入 100 条 idempotency 记录
    for i in range(100):
        key = f"key-{i}"
        req_hash = hashlib.sha256(f"payload-{i}".encode()).hexdigest()
        store.remember("bench_scope", key, req_hash)

    # 测量读取延迟
    times: list[float] = []
    for i in range(100):
        t0 = time.perf_counter()
        hit = store.lookup("bench_scope", f"key-{i}")
        times.append((time.perf_counter() - t0) * 1000)
        assert hit is not None, f"key-{i} 应该已存在"

    avg_ms = sum(times) / len(times)
    assert avg_ms < READ_LATENCY_THRESHOLD_MS, (
        f"RuntimeStore 读取平均延迟 {avg_ms:.3f}ms > {READ_LATENCY_THRESHOLD_MS}ms"
    )


def test_runtime_store_job_lifecycle_benchmark(tmp_path: Path) -> None:
    """RuntimeStore Job 生命周期（create→claim→complete）基准。"""
    db_path = tmp_path / "runtime" / "bench_lifecycle.db"
    store = RuntimeStore(db_path)

    n_jobs = 50
    times_create: list[float] = []
    times_claim: list[float] = []
    times_complete: list[float] = []

    for i in range(n_jobs):
        job_id = f"JOB-LC-{i:04d}"

        t0 = time.perf_counter()
        store.create_job(job_id=job_id, job_type="BENCH_LIFECYCLE")
        times_create.append((time.perf_counter() - t0) * 1000)

        t0 = time.perf_counter()
        job = store.claim_job(f"worker-{i}")
        times_claim.append((time.perf_counter() - t0) * 1000)

        if job is not None:
            t0 = time.perf_counter()
            store.complete_job(job.job_id, f"worker-{i}", result={"ok": True})
            times_complete.append((time.perf_counter() - t0) * 1000)

    avg_create = sum(times_create) / len(times_create)
    avg_claim = sum(times_claim) / len(times_claim)
    avg_complete = sum(times_complete) / max(len(times_complete), 1)

    assert avg_create < 20.0, f"Job create 平均延迟 {avg_create:.2f}ms > 20.0ms"
    assert avg_claim < 20.0, f"Job claim 平均延迟 {avg_claim:.2f}ms > 20.0ms"
    assert avg_complete < 20.0, f"Job complete 平均延迟 {avg_complete:.2f}ms > 20.0ms"
