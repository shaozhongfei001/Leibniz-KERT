"""并发锁竞争性能基准（NFR-006/007）。

⚠ **不作为验收/冻结态证据**（裁决 **D-10**，Owner 已批 2026-09-16）：
本模块全部断言的是**墙钟阈值**（例：`assert avg_create < 20.0`）。多智能体/多进程
并发跑测时，机器负载由**我们自己的并发**引入 ⇒ 墙钟阈值**结构性不可靠**：实测失败
集合**逐轮漂移**（1 条 / 2 条 / 3 条），且**与任何被测代码改动无关**（隔离复跑仍 FAIL）。

⇒ 本模块整体标记 `perf`，并在**默认套件中排除**
（`pyproject.toml` 的 `addopts = ["-q", "-m", "not perf"]`）。须**显式**运行：

    python -m pytest -m perf tests/performance/test_concurrency_benchmark.py

**不得**只"放宽阈值"了事 —— 那只是把 flake 洗成"通过"，不是修好。若日后要让它重新
承担验收角色，须先把判据从**墙钟**换成**非墙钟**（操作计数 / 不变量 / 相对比值）。

> **D-37 已按此口径完成第一处改造（2026-09-17）**：
> `test_runtime_store_job_lifecycle_benchmark` 的 3 条 `assert avg_x < 20.0` 已换成
> **不变量 + 相对比值 + 灾难上限**（判定体 `assert_lifecycle_budget`，分母取
> `_calibration.calibrate_per_op_ms`）。改前背靠背 20 轮 **14 轮红**、
> 改后同条件 **0 轮红**（逐轮实测与降敏声明见 `BASELINE.md` §9）。
> 本模块**其余 4 个用例仍断言墙钟**（锁延迟 / 并发写总量 / 读延迟）⇒ `pytestmark = perf` 保留。

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

import pytest

from kert.infrastructure.locks import WorkspaceLock
from kert.infrastructure.runtime_store import RuntimeStore
from tests.performance._calibration import (
    CATASTROPHE_CEILING_MS,
    RATIO_LIMIT,
    calibrate_per_op_ms,
)

#: D-10：本模块断言墙钟阈值 ⇒ 默认套件排除（理由见模块 docstring）。
pytestmark = pytest.mark.perf


# ---------- WorkspaceLock 基准 ----------

SINGLE_LOCK_THRESHOLD_MS = 10       # 单次 acquire+release < 10ms
CONCURRENT_SCOPE_THRESHOLD_MS = 2000  # 10 线程各 10 次 acquire+release < 2s
CONCURRENT_WRITE_THRESHOLD_MS = 3000  # 10 线程各 10 次写入 < 3s
READ_LATENCY_THRESHOLD_MS = 5.0     # 单次读取 < 5ms


def assert_lifecycle_budget(*, avg_create: float, avg_claim: float, avg_complete: float,
                            calib_ms: float) -> None:
    """②③ 两个**相对**判据（D-37 修基准的判定体；抽成函数以便反例直接对判定体下手）。

    - ② 比值：``avg_x ≤ RATIO_LIMIT × calib_ms``（机器/负载整体漂移同作用于分子分母）；
    - ③ 上限：``avg_x < CATASTROPHE_CEILING_MS``（只抓 ≥7× 级回归）。

    判据顺序刻意"上限在前"：灾难级偏差报"上限"，其余报"比值"，两条反例各按名字命中其一。
    """
    for name, avg in (("create", avg_create), ("claim", avg_claim), ("complete", avg_complete)):
        assert avg < CATASTROPHE_CEILING_MS, (
            f"Job {name} 平均 {avg:.2f}ms 越过灾难上限 {CATASTROPHE_CEILING_MS}ms"
            f"（参考负载 {calib_ms:.2f}ms/op）—— ≥7× 级回归")
    for name, avg in (("create", avg_create), ("claim", avg_claim), ("complete", avg_complete)):
        assert avg <= RATIO_LIMIT * calib_ms, (
            f"Job {name} 平均 {avg:.2f}ms 超过参考负载的 {RATIO_LIMIT}×"
            f"（比值档：参考负载 {calib_ms:.2f}ms/op ⇒ 上限 {RATIO_LIMIT * calib_ms:.2f}ms）"
            f"—— ≥3× 级回归")


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
    """RuntimeStore Job 生命周期（create→claim→complete）：**不变量 + 相对比值 + 灾难上限**。

    D-37「修基准」（``BASELINE.md`` §9 有逐轮实测与降敏声明）：本用例的判据**不再**是
    ``assert avg_x < 20.0`` 这类绝对墙钟阈值 —— 实测同一代码/命令/机器在背靠背 20 轮里
    该量在 **13.9–34.1ms** 之间呈双态漂移（改前 14/20 轮假红），任何常数阈值都不可标定。

    三层判据：

    ① **不变量（零墙钟）**：``create`` 得 ``PENDING``；``claim`` 拿到**该** job 并置 ``RUNNING``；
       他人再 ``claim`` 得 ``None``；**非 lease 持有者** ``complete`` 得 ``None``；
       持有者 ``complete`` 后状态 ``COMPLETED``、重复 ``complete`` 得 ``None``；
       终局计数 ``50/0/0``（COMPLETED/PENDING/RUNNING）。
    ② **相对比值**：``avg_x ≤ RATIO_LIMIT(3) ×`` 同进程参考负载（:mod:`tests.performance._calibration`，
       逐字镜像"建连 + PRAGMA + 单写 + 提交"）。分母取**前后两次标定的较大者**：分母偏大 ⇒
       对测试执行期间的状态漂移更宽容，而 ≥3× 的真实回归仍被拦。
    ③ **灾难上限**：``avg_x < CATASTROPHE_CEILING_MS(100)``，只抓 ≥7× 级回归。

    ⚠ **降敏**（不得读成"这里还有单位数毫秒的性能门禁"）：**≤2× 的真实退化不会被本用例拦住**
    （比值档拦 ≥3×，上限档拦 ≥7×）。这段空白的归属见 ``BASELINE.md`` §9.3。
    """
    db_path = tmp_path / "runtime" / "bench_lifecycle.db"
    store = RuntimeStore(db_path)
    runtime_dir = tmp_path / "runtime"
    calib_before = calibrate_per_op_ms(runtime_dir / "calib_before.db")

    n_jobs = 50
    times_create: list[float] = []
    times_claim: list[float] = []
    times_complete: list[float] = []

    for i in range(n_jobs):
        job_id = f"JOB-LC-{i:04d}"

        t0 = time.perf_counter()
        created = store.create_job(job_id=job_id, job_type="BENCH_LIFECYCLE")
        times_create.append((time.perf_counter() - t0) * 1000)
        # ① 创建即 PENDING，且拿到的是**该** job
        assert created is not None and created.job_id == job_id and created.status == "PENDING"

        t0 = time.perf_counter()
        job = store.claim_job(f"worker-{i}")
        times_claim.append((time.perf_counter() - t0) * 1000)
        # ① 领取必须命中该 job 并置 RUNNING；且**同一 job 不得被再次领取**（CAS 语义）
        assert job is not None and job.job_id == job_id and job.status == "RUNNING"
        # ① 两条"负向"不变量在**每 10 次 + 末次**上核对（结构性断言，无需每次都做；
        #    每次都做会让本用例凭空多 100 次建连写盘 ⇒ perf job 变慢，收益为零）
        if i % 10 == 0 or i == n_jobs - 1:
            assert store.claim_job(f"other-{i}") is None, "已被占用的 Job 不得被再次领取"
            # ① lease 语义：非持有者不得写回结果
            assert store.complete_job(job_id, f"other-{i}", result={"ok": False}) is None, (
                "非 lease 持有者不得完成该 Job")

        t0 = time.perf_counter()
        done = store.complete_job(job.job_id, f"worker-{i}", result={"ok": True})
        times_complete.append((time.perf_counter() - t0) * 1000)
        # ① 终态 COMPLETED；重复完成必须拒绝
        assert done is not None and done.job_id == job_id and done.status == "COMPLETED"
        assert store.complete_job(job_id, f"worker-{i}", result={"ok": True}) is None, (
            "重复完成必须拒绝（终态不可再写）")

    # ① 终局计数（防空转：不许"少做几次也算过"）
    last = store.get_job(f"JOB-LC-{n_jobs - 1:04d}")
    assert last is not None and last.status == "COMPLETED"
    assert len(store.list_jobs(statuses=["COMPLETED"])) == n_jobs
    assert store.list_jobs(statuses=["PENDING"]) == []
    assert store.list_jobs(statuses=["RUNNING"]) == []

    # ②③ 相对比值 + 灾难上限
    calib_after = calibrate_per_op_ms(runtime_dir / "calib_after.db")
    calib_ms = max(calib_before, calib_after)
    assert_lifecycle_budget(
        avg_create=sum(times_create) / len(times_create),
        avg_claim=sum(times_claim) / len(times_claim),
        avg_complete=sum(times_complete) / len(times_complete),
        calib_ms=calib_ms,
    )


# --------------------------------------------------------------------------- #
# D-37 反例：证明上面那三层判据**不是空转**（判据自身必须能红）
# --------------------------------------------------------------------------- #

def test_lifecycle_budget_rejects_a_3x_ratio_regression() -> None:
    """反例（比值档）：测点放大到参考负载的 3.5× ⇒ **比值判据必须红**。"""
    with pytest.raises(AssertionError, match="比值"):
        assert_lifecycle_budget(avg_create=35.0, avg_claim=9.0, avg_complete=9.0, calib_ms=10.0)


def test_lifecycle_budget_rejects_a_catastrophe_regression() -> None:
    """反例（上限档）：比值与参考负载**持平**（1.0×）但越过 100ms ⇒ **上限判据必须红**。

    这条专门证明"上限档不是摆设"（否则 100ms 与 3×比值 重叠时上限永远不生效）。
    """
    with pytest.raises(AssertionError, match="上限"):
        assert_lifecycle_budget(avg_create=100.0, avg_claim=9.0, avg_complete=9.0, calib_ms=100.0)


def test_lifecycle_budget_rejects_a_real_injected_slowdown(tmp_path: Path,
                                                            monkeypatch: pytest.MonkeyPatch) -> None:
    """反例（**真回归**）：把被测路径人为拖慢（monkeypatch + 固定 100ms sleep）⇒ 判据必须红。

    用**固定附加延迟**而非倍数，保证在**两种机器状态**下都必然超标：
    快态约 14ms→114ms（上限红 + 比值 ~8×），慢态约 27ms→127ms（上限红 + 比值 ~4.7×）。
    """
    real_create_job = RuntimeStore.create_job

    def slow_create_job(self, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        time.sleep(0.100)
        return real_create_job(self, *args, **kwargs)

    monkeypatch.setattr(RuntimeStore, "create_job", slow_create_job)

    runtime_dir = tmp_path / "runtime"
    store = RuntimeStore(runtime_dir / "slow.db")
    calib_ms = calibrate_per_op_ms(runtime_dir / "calib_slow.db")

    times: list[float] = []
    for i in range(10):
        t0 = time.perf_counter()
        store.create_job(job_id=f"JOB-SLOW-{i:04d}", job_type="BENCH_LIFECYCLE")
        times.append((time.perf_counter() - t0) * 1000)
    avg = sum(times) / len(times)

    assert avg > CATASTROPHE_CEILING_MS, f"注入的拖慢未生效（avg={avg:.1f}ms）⇒ 本反例无法证明判据有牙"
    with pytest.raises(AssertionError, match="上限"):
        assert_lifecycle_budget(avg_create=avg, avg_claim=avg, avg_complete=avg, calib_ms=calib_ms)


def test_lifecycle_budget_documents_the_2x_blind_spot() -> None:
    """**把降敏事实机械钉住**：2× 的退化**不会**触发判据（`BASELINE.md` §9.3 的硬声明）。

    这里刻意用"判定体 + 常数"而非真实计时：本用例要证明的是**判据的灵敏度边界**
    （2× ⇒ 静默通过），不得因为机器抖动而自身变红（否则它就变成了第二个 flake）。
    """
    assert_lifecycle_budget(avg_create=20.0, avg_claim=20.0, avg_complete=20.0, calib_ms=10.0)
    # 判据是 `avg <= RATIO_LIMIT × calib` ⇒ 恰好 3.0× 仍算通过；>3× 必须红。
    # 于是"灵敏度边界"是可核的事实：2.0× 静默通过、3.1× 必红。
    assert_lifecycle_budget(avg_create=30.0, avg_claim=30.0, avg_complete=30.0, calib_ms=10.0)
    with pytest.raises(AssertionError, match="比值"):
        assert_lifecycle_budget(avg_create=31.0, avg_claim=31.0, avg_complete=31.0, calib_ms=10.0)


def test_runtime_store_job_lifecycle_benchmark_mutant_is_red() -> None:
    """**变异自证（机械化）**：若把比值判据改成"恒真"（例如短路/读常量自比）⇒ 上述反例必须红。

    实现：在内存里比对"有牙版"与"无牙版"两个判定函数对同一输入的结论**必须相反**；
    只要有人把有牙版改成恒真，本用例立刻失败（把一次性的手工自证固定下来）。
    """
    def toothless(*, avg_create: float, avg_claim: float, avg_complete: float,
                  calib_ms: float) -> None:  # 恒真（"仅记录"的假判据）
        return None

    bad = {"avg_create": 999.0, "avg_claim": 999.0, "avg_complete": 999.0, "calib_ms": 10.0}
    toothless(**bad)                                  # 假判据不报错
    with pytest.raises(AssertionError):
        assert_lifecycle_budget(**bad)                # 真判据必须报错 ⇒ 两者不同 ⇒ 有牙

