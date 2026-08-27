#!/usr/bin/env python3
"""M2-P2 端到端验证：真实 Worker 进程 + kill -9 崩溃恢复 + dead-letter。

验证内容：
1. schema v2 migration 与 lease/重试/dead-letter 列
2. 真实 Worker 子进程领取 Job 后被 kill -9，lease 到期被回收
3. 新 Worker 接手崩溃遗留的 Job 并执行到 COMPLETED
4. 重试额度耗尽后进入 dead-letter，人工重放可恢复
5. 指数退避实际生效
6. SIGTERM 优雅停机：当前 Job 完成后退出，不留悬挂 lease
7. 并发领取无重复投递（原子性）
8. 运维子命令 --stats / --list-dead-letters / --requeue
9. 生产 profile 未启用 Runtime Store 时拒绝异步执行（Owner 决策 3）
10. recover_stale_jobs 已标记 deprecated（Owner 决策 2）

用法：
    python scripts/verify_m2p2_worker.py [--out evidence/m2-p2]
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import signal
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "src"


def _log(report: dict, name: str, passed: bool, detail: str) -> None:
    """记录一条检查结果。"""
    report["checks"].append({"name": name, "passed": bool(passed), "detail": detail})
    print(f"[{'PASS' if passed else 'FAIL'}] {name} :: {detail}", flush=True)


def _init_workspace(root: Path) -> Path:
    """初始化真实工作区。"""
    sys.path.insert(0, str(SRC))
    from dkws.domain import workspace as ws_mod

    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    ws_mod.init_workspace(root)
    return root


def _crash_worker_script(db: Path, marker: Path) -> str:
    """子进程脚本：领取 Job 后挂起，等待被 kill -9。

    限定 ``CRASHQ`` 类型，避免抢占其他验证场景的 Job。
    """
    return textwrap.dedent(f"""
        import sys, time, pathlib
        sys.path.insert(0, {str(SRC)!r})
        from dkws.infrastructure.runtime_store import RuntimeStore
        store = RuntimeStore(pathlib.Path({str(db)!r}))
        job = store.claim_job("w-crash", job_types=["CRASHQ"], lease_seconds=1.0)
        assert job is not None
        pathlib.Path({str(marker)!r}).write_text(job.job_id)
        while True:
            time.sleep(0.05)
    """).strip()


def check_schema(report: dict, store) -> None:
    """场景 1：schema v2 与新增列。"""
    _log(report, "schema_version_is_2", store.schema_version() == 2,
         f"schema_version={store.schema_version()}")
    conn = store.connect()
    try:
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(jobs)").fetchall()}
        idx = {r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index'").fetchall()}
    finally:
        conn.close()
    expected_cols = {"lease_owner", "lease_expires_at", "heartbeat_at", "max_attempts",
                     "next_attempt_at", "error_code", "dead_letter", "dead_lettered_at",
                     "dead_letter_reason", "idem_key"}
    _log(report, "lease_retry_columns_present", expected_cols <= cols,
         f"新增 {len(expected_cols)} 列齐备")
    _log(report, "scheduling_indexes_present",
         {"idx_jobs_claim", "idx_jobs_lease", "idx_jobs_dead_letter"} <= idx,
         "调度/回收/dead-letter 索引已建立")


def check_crash_recovery(report: dict, store, db: Path, tmp: Path,
                         log_dir: Path) -> None:
    """场景 2-3：真实 kill -9 后 lease 回收与接续执行。"""
    store.create_job("J-CRASH", "CRASHQ", {"v": 21}, max_attempts=3)
    marker = tmp / "claimed.txt"
    script = tmp / "crash_worker.py"
    script.write_text(_crash_worker_script(db, marker), encoding="utf-8")

    log_path = log_dir / "01_crash_worker.log"
    with log_path.open("w", encoding="utf-8") as log_file:
        proc = subprocess.Popen([sys.executable, str(script)],
                                stdout=log_file, stderr=subprocess.STDOUT)
        try:
            deadline = time.time() + 30
            while time.time() < deadline and not marker.exists():
                if proc.poll() is not None:
                    _log(report, "crash_worker_claims_job", False, "子进程提前退出")
                    return
                time.sleep(0.05)
            claimed = store.get_job("J-CRASH")
            _log(report, "crash_worker_claims_job",
                 marker.exists() and claimed.status == "RUNNING"
                 and claimed.lease_owner == "w-crash",
                 f"子进程 pid={proc.pid} 领取 J-CRASH，"
                 f"status={claimed.status} owner={claimed.lease_owner} "
                 f"attempts={claimed.attempts}")

            os.kill(proc.pid, signal.SIGKILL)
            proc.wait(timeout=15)
            _log(report, "worker_killed_with_sigkill", proc.returncode != 0,
                 f"kill -9 后退出码={proc.returncode}（负值表示被信号终止）")

            still = store.get_job("J-CRASH")
            _log(report, "lease_not_released_by_crash",
                 still.status == "RUNNING" and still.lease_owner == "w-crash",
                 "被强杀进程无机会清理，lease 仍指向已死 Worker")
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=10)

    time.sleep(1.2)  # 等 lease（1 秒）过期
    from dkws.infrastructure.worker import JobWorker, WorkerConfig

    worker = JobWorker(store, WorkerConfig(
        worker_id="w-recover", job_types=("CRASHQ",), lease_seconds=30.0,
        poll_interval=0.01, reclaim_interval=0.0, backoff_base=0.01, max_jobs=1))
    worker.register("CRASHQ", lambda job: {"v": job.payload["v"] * 2})
    worker.run_forever()

    recovered = store.get_job("J-CRASH")
    _log(report, "expired_lease_reclaimed", worker.stats.reclaimed >= 1,
         f"回收过期 lease 数={worker.stats.reclaimed}")
    _log(report, "crashed_job_reprocessed_to_completion",
         recovered.status == "COMPLETED" and recovered.result == {"v": 42},
         f"新 Worker 接手后 status={recovered.status} result={recovered.result}")
    _log(report, "attempt_count_preserved_across_crash", recovered.attempts == 2,
         f"attempts={recovered.attempts}（崩溃那次 + 恢复那次，未重置）")


def check_dead_letter(report: dict, store) -> None:
    """场景 4：额度耗尽进入 dead-letter，人工重放可恢复。

    使用独立 job_type ``DEADQ``，避免与其他场景的 Job 互相抢占。
    """
    from dkws.infrastructure.worker import JobWorker, WorkerConfig

    store.create_job("J-DEAD", "DEADQ", max_attempts=2)
    worker = JobWorker(store, WorkerConfig(
        worker_id="w-fail", job_types=("DEADQ",), lease_seconds=30.0,
        poll_interval=0.01, reclaim_interval=0.0, backoff_base=0.01))
    worker.register("DEADQ", lambda job: (_ for _ in ()).throw(RuntimeError("注入失败")))
    worker.run_once()
    first = store.get_job("J-DEAD")
    _log(report, "first_failure_goes_retrying",
         first.status == "RETRYING" and not first.dead_letter,
         f"第 1 次失败 → status={first.status}，"
         f"next_attempt_at 已设置={first.next_attempt_at is not None}")

    time.sleep(0.05)
    worker.run_once()
    dead = store.get_job("J-DEAD")
    _log(report, "exhausted_attempts_go_dead_letter",
         dead.dead_letter and dead.status == "FAILED",
         f"额度耗尽 → status={dead.status} dead_letter={dead.dead_letter} "
         f"reason={dead.dead_letter_reason}")
    _log(report, "dead_letter_not_reclaimable",
         store.claim_job("w-x", job_types=["DEADQ"]) is None,
         "dead-letter Job 不再被领取，避免无限重试")
    _log(report, "dead_letter_avoids_blocked_state", dead.status != "BLOCKED",
         "dead-letter 用 FAILED+标记位表达，未使用 BLOCKED（§11.1 合规）")

    requeued = store.requeue_dead_letter("J-DEAD", extra_attempts=1)
    ok_worker = JobWorker(store, WorkerConfig(
        worker_id="w-ok", job_types=("DEADQ",), lease_seconds=30.0,
        poll_interval=0.01, reclaim_interval=0.0, max_jobs=1))
    ok_worker.register("DEADQ", lambda job: {"recovered": True})
    ok_worker.run_forever()
    final = store.get_job("J-DEAD")
    _log(report, "dead_letter_requeue_works",
         requeued is not None and final.status == "COMPLETED",
         f"人工重放后 status={final.status} result={final.result}")


def check_backoff(report: dict, store) -> None:
    """场景 5：指数退避实际生效。

    使用独立 job_type ``BACKOFFQ``/``CAPQ``，且全程用注入时间，
    不受其他场景的 Worker 干扰。
    """
    store.create_job("J-BACKOFF", "BACKOFFQ", max_attempts=5)
    delays = []
    now = 1_000_000.0
    for _ in range(3):
        if store.claim_job("w-b", job_types=["BACKOFFQ"], now=now) is None:
            break
        rec = store.fail_job("J-BACKOFF", "w-b", error_message="boom",
                             backoff_base=2.0, backoff_factor=2.0, now=now)
        if rec is None or rec.next_attempt_at is None:
            break
        delays.append(round(rec.next_attempt_at - now, 3))
        now = rec.next_attempt_at + 1.0
    _log(report, "exponential_backoff_applied", delays == [2.0, 4.0, 8.0],
         f"退避序列={delays} 秒（base=2 factor=2）")

    store.create_job("J-CAP", "CAPQ", max_attempts=10)
    now = 2_000_000.0
    capped = []
    for _ in range(5):
        if store.claim_job("w-c", job_types=["CAPQ"], now=now) is None:
            break
        rec = store.fail_job("J-CAP", "w-c", error_message="boom", backoff_base=2.0,
                             backoff_factor=2.0, backoff_max=10.0, now=now)
        if rec is None or rec.next_attempt_at is None:
            break
        capped.append(round(rec.next_attempt_at - now, 3))
        now = rec.next_attempt_at + 1.0
    _log(report, "backoff_capped",
         capped == [2.0, 4.0, 8.0, 10.0, 10.0],
         f"退避序列={capped}，上限 10 秒生效")


def check_graceful_shutdown(report: dict, store, db: Path, tmp: Path,
                            log_dir: Path) -> None:
    """场景 6：SIGTERM 优雅停机。"""
    store.create_job("J-GRACE", "GRACEQ", max_attempts=3)
    ready = tmp / "ready.txt"
    script = tmp / "graceful_worker.py"
    script.write_text(textwrap.dedent(f"""
        import sys, pathlib, time
        sys.path.insert(0, {str(SRC)!r})
        from dkws.infrastructure.runtime_store import RuntimeStore
        from dkws.infrastructure.worker import JobWorker, WorkerConfig
        store = RuntimeStore(pathlib.Path({str(db)!r}))
        worker = JobWorker(store, WorkerConfig(
            worker_id="w-grace", job_types=("GRACEQ",),
            lease_seconds=10.0, poll_interval=0.05))
        worker.install_signal_handlers()

        def handler(job):
            pathlib.Path({str(ready)!r}).write_text("running")
            time.sleep(0.8)
            return {{"graceful": True}}

        worker.register("GRACEQ", handler)
        worker.run_forever()
    """).strip(), encoding="utf-8")

    log_path = log_dir / "02_graceful_worker.log"
    with log_path.open("w", encoding="utf-8") as log_file:
        proc = subprocess.Popen([sys.executable, str(script)],
                                stdout=log_file, stderr=subprocess.STDOUT)
        try:
            deadline = time.time() + 30
            while time.time() < deadline and not ready.exists():
                if proc.poll() is not None:
                    _log(report, "sigterm_graceful_shutdown", False, "子进程提前退出")
                    return
                time.sleep(0.05)
            proc.send_signal(signal.SIGTERM)
            proc.wait(timeout=20)
            job = store.get_job("J-GRACE")
            _log(report, "sigterm_graceful_shutdown",
                 job.status == "COMPLETED" and job.result == {"graceful": True},
                 f"执行中收到 SIGTERM，当前 Job 仍完成：status={job.status}")
            _log(report, "no_dangling_lease_after_shutdown", job.lease_owner is None,
                 "优雅停机后无悬挂 lease")
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=10)


def check_concurrency(report: dict, store) -> None:
    """场景 7：并发领取无重复投递。"""
    for i in range(30):
        store.create_job(f"J-C{i:02d}", "CONC")
    claimed: list[str] = []
    lock = threading.Lock()

    def run(idx: int) -> None:
        """不断领取直到队列空。"""
        while True:
            job = store.claim_job(f"w{idx}", job_types=["CONC"])
            if job is None:
                return
            with lock:
                claimed.append(job.job_id)

    threads = [threading.Thread(target=run, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    _log(report, "concurrent_claim_no_duplicates",
         len(claimed) == 30 and len(set(claimed)) == 30,
         f"8 线程并发领取 30 个 Job：投递 {len(claimed)} 次，去重后 {len(set(claimed))} 个")


def check_cli(report: dict, workspace: Path, log_dir: Path) -> None:
    """场景 8：运维子命令可用。"""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SRC)
    base = [sys.executable, str(REPO / "scripts" / "run_worker.py"),
            "--workspace", str(workspace)]

    stats = subprocess.run([*base, "--stats"], env=env, capture_output=True,
                           text=True, timeout=90, check=False)
    (log_dir / "03_cli_stats.log").write_text(
        f"exit={stats.returncode}\n\n{stats.stdout}\n{stats.stderr}", encoding="utf-8")
    parsed_ok = False
    try:
        payload = json.loads(stats.stdout)
        parsed_ok = "by_status" in payload and "claimable" in payload
    except json.JSONDecodeError:
        parsed_ok = False
    _log(report, "cli_stats_works", stats.returncode == 0 and parsed_ok,
         f"--stats 退出码={stats.returncode}，输出为合法 JSON 队列概览")

    dead = subprocess.run([*base, "--list-dead-letters"], env=env,
                          capture_output=True, text=True, timeout=90,
                          check=False)
    (log_dir / "04_cli_dead_letters.log").write_text(
        f"exit={dead.returncode}\n\n{dead.stdout}\n{dead.stderr}", encoding="utf-8")
    _log(report, "cli_list_dead_letters_works", dead.returncode == 0,
         f"--list-dead-letters 退出码={dead.returncode}")

    missing = subprocess.run([*base, "--requeue", "JOB-NOT-EXIST"], env=env,
                             capture_output=True, text=True, timeout=90,
                          check=False)
    _log(report, "cli_requeue_rejects_unknown", missing.returncode == 1,
         f"重放不存在的 Job 返回非零退出码={missing.returncode}")


def check_prod_async_guard(report: dict, workspace: Path) -> None:
    """场景 9：生产 profile 未启用 Runtime Store 时拒绝异步执行。

    对应 Owner 审核决策 3（2026-08-27）：禁止回退 threading 模式，
    以免生产环境进程崩溃丢任务。
    """
    from dkws.application.skills import SkillExecutionService
    from dkws.domain.errors import ServiceNotReadyError

    svc_prod = SkillExecutionService(workspace, profile="prod")
    rejected = False
    http_status = None
    details: dict = {}
    try:
        svc_prod.execute_async("skill-customer-outreach-script", "REQ-GUARD-1",
                               {"customerId": "CUST-CORP-0001"})
    except ServiceNotReadyError as exc:
        rejected = True
        http_status = exc.http_status()
        details = exc.details
    _log(report, "prod_async_without_store_rejected",
         rejected and http_status == 503,
         f"prod + Store 未启用 → 拒绝异步执行，HTTP {http_status}，"
         f"remediation={details.get('remediation')}")

    jobs_root = workspace / "90_control" / "jobs"
    guard_jobs = list(jobs_root.glob("JOB-SKILL-*")) if jobs_root.is_dir() else []
    _log(report, "prod_async_no_thread_fallback", not guard_jobs,
         "拒绝时未创建任何 SKILL Job 目录，确认未回退 threading 模式")

    svc_dev = SkillExecutionService(workspace, profile="dev")
    dev_ok = False
    try:
        job_id = svc_dev.execute_async("skill-customer-outreach-script", "REQ-GUARD-2",
                                       {"customerId": "CUST-CORP-0001"})
        dev_ok = bool(job_id)
    except Exception as exc:  # noqa: BLE001 - 仅用于记录验证结果
        dev_ok = False
        details = {"error": str(exc)}
    _log(report, "dev_async_still_allowed", dev_ok,
         "dev profile 未启用 Store 时仍可异步执行（不破坏开发流程）")


def check_deprecation_marker(report: dict) -> None:
    """场景 10：recover_stale_jobs 已标记 deprecated（Owner 决策 2）。"""
    import inspect

    from dkws.infrastructure.runtime_store import RuntimeStore

    doc = inspect.getdoc(RuntimeStore.recover_stale_jobs) or ""
    _log(report, "recover_stale_jobs_marked_deprecated",
         ".. deprecated:: M2.4" in doc and "reclaim_expired_leases" in doc,
         "docstring 含 deprecated 标记并指向 reclaim_expired_leases")
    _log(report, "recover_stale_jobs_still_available",
         callable(RuntimeStore.recover_stale_jobs),
         "方法保留可用，未删除、未改变既有行为")


def main() -> int:
    """执行全部验证并写出报告。"""
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(REPO / "evidence" / "m2-p2"))
    ap.add_argument("--workspace", default="/tmp/dkws-m2p2-e2e-ws")
    args = ap.parse_args()

    out_dir = Path(args.out)
    log_dir = out_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    tmp = Path("/tmp/dkws-m2p2-scripts")
    tmp.mkdir(parents=True, exist_ok=True)

    workspace = _init_workspace(Path(args.workspace))
    from dkws.infrastructure.runtime_store import RuntimeStore

    db = workspace / "90_control" / "runtime" / "runtime.db"
    store = RuntimeStore(db)

    report: dict = {
        "task_package": "M2-P2",
        "scope": "M2.4 持久化异步 Worker",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "environment": {"python": sys.version.split()[0],
                        "platform": platform.platform(),
                        "workspace": str(workspace)},
        "checks": [],
    }

    check_schema(report, store)
    check_crash_recovery(report, store, db, tmp, log_dir)
    check_dead_letter(report, store)
    check_backoff(report, store)
    check_graceful_shutdown(report, store, db, tmp, log_dir)
    check_concurrency(report, store)
    check_cli(report, workspace, log_dir)
    check_prod_async_guard(report, workspace)
    check_deprecation_marker(report)

    report["queue_stats_final"] = store.queue_stats()
    passed = sum(1 for c in report["checks"] if c["passed"])
    total = len(report["checks"])
    report["summary"] = {"passed": passed, "total": total,
                         "result": "PASS" if passed == total else "FAIL"}
    (out_dir / "e2e_worker_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n=== {passed}/{total} 项检查通过 → {report['summary']['result']} ===")
    print(f"报告：{out_dir / 'e2e_worker_report.json'}")
    shutil.rmtree(tmp, ignore_errors=True)
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
