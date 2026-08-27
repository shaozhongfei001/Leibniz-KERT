#!/usr/bin/env python3
"""DKWS 持久化异步 Worker 入口（M2.4）。

从 SQLite Runtime Store 领取 Job 并执行，支持 lease 租约、指数退避重试、
dead-letter 与优雅停机。状态权威在 SQLite，进程崩溃后可完整恢复。

用法::

    # 启动 Worker（处理全部已注册类型）
    python scripts/run_worker.py --workspace ./workspace

    # 仅处理指定类型，自定义 lease
    python scripts/run_worker.py --workspace ./workspace \\
        --job-types SKILL,INGEST --lease-seconds 60

    # 查看队列概览后退出
    python scripts/run_worker.py --workspace ./workspace --stats

    # 列出 dead-letter
    python scripts/run_worker.py --workspace ./workspace --list-dead-letters

    # 人工重放某个 dead-letter Job
    python scripts/run_worker.py --workspace ./workspace --requeue JOB-SKILL-20260827-0001

环境变量（可替代命令行）：``DKWS_WORKER_ID`` / ``DKWS_WORKER_JOB_TYPES`` /
``DKWS_WORKER_LEASE_SECONDS`` / ``DKWS_WORKER_POLL_INTERVAL`` /
``DKWS_WORKER_RECLAIM_INTERVAL`` / ``DKWS_WORKER_MAX_JOBS`` /
``DKWS_WORKER_BACKOFF_BASE`` / ``DKWS_WORKER_BACKOFF_FACTOR`` /
``DKWS_WORKER_BACKOFF_MAX``。
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))


def build_parser() -> argparse.ArgumentParser:
    """构造命令行参数解析器。"""
    ap = argparse.ArgumentParser(description="DKWS 持久化异步 Worker")
    ap.add_argument("--workspace", required=True, help="工作区根目录")
    ap.add_argument("--db", default=None,
                    help="数据库路径，默认 <workspace>/90_control/runtime/runtime.db")
    ap.add_argument("--worker-id", default=None, help="Worker 标识，默认自动生成")
    ap.add_argument("--job-types", default=None,
                    help="逗号分隔的业务类型，默认处理全部已注册类型")
    ap.add_argument("--lease-seconds", type=float, default=None, help="lease 租约时长")
    ap.add_argument("--poll-interval", type=float, default=None, help="空闲轮询间隔")
    ap.add_argument("--max-jobs", type=int, default=None,
                    help="处理指定数量后退出，0 表示不限")
    ap.add_argument("--stats", action="store_true", help="打印队列概览后退出")
    ap.add_argument("--list-dead-letters", action="store_true",
                    help="列出 dead-letter Job 后退出")
    ap.add_argument("--requeue", default=None,
                    help="重放指定 dead-letter Job 后退出（人工干预）")
    ap.add_argument("--log-level", default="INFO", help="日志级别")
    return ap


def register_handlers(worker, workspace: Path) -> None:
    """注册业务 Handler。

    当前仅注册 ``SKILL`` 类型作为示例接线；实际业务 Handler 应由各应用服务
    在此登记。保持此函数为唯一注册入口，便于后续扩展与审计。
    """
    from dkws.application.skills import SkillExecutionService

    service = SkillExecutionService(workspace)

    def handle_skill(job):
        """执行 Skill 类型 Job。"""
        payload = job.payload or {}
        skill_id = payload.get("skillId") or payload.get("skill_id")
        request = payload.get("request") or {}
        if not skill_id:
            from dkws.infrastructure.worker import NonRetryableJobError
            raise NonRetryableJobError("payload 缺少 skillId",
                                       error_code="MISSING_SKILL_ID")
        result = service.execute(skill_id, job.job_id, request)
        return {"status": result.status, "data": result.data}

    worker.register("SKILL", handle_skill)


def main() -> int:
    """入口：按参数执行运维子命令或启动 Worker 主循环。"""
    args = build_parser().parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s")

    from dkws.infrastructure.runtime_store import RuntimeStore
    from dkws.infrastructure.worker import JobWorker, build_worker_config_from_env

    workspace = Path(args.workspace).resolve()
    db_path = (Path(args.db) if args.db
               else workspace / "90_control" / "runtime" / "runtime.db")
    store = RuntimeStore(db_path)

    # 运维子命令：查看与干预，不进入主循环
    if args.stats:
        print(json.dumps(store.queue_stats(), ensure_ascii=False, indent=2))
        return 0
    if args.list_dead_letters:
        rows = [{"job_id": j.job_id, "job_type": j.job_type,
                 "attempts": f"{j.attempts}/{j.max_attempts}",
                 "reason": j.dead_letter_reason,
                 "error": j.error_message} for j in store.list_dead_letters()]
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return 0
    if args.requeue:
        job = store.requeue_dead_letter(args.requeue)
        if job is None:
            print(f"[worker] {args.requeue} 不存在或不在 dead-letter 中", file=sys.stderr)
            return 1
        print(f"[worker] {job.job_id} 已重新入队（max_attempts={job.max_attempts}）")
        return 0

    config = build_worker_config_from_env()
    # 命令行优先于环境变量
    if args.worker_id:
        config.worker_id = args.worker_id
    if args.job_types is not None:
        config.job_types = tuple(t.strip() for t in args.job_types.split(",") if t.strip())
    if args.lease_seconds is not None:
        config.lease_seconds = args.lease_seconds
    if args.poll_interval is not None:
        config.poll_interval = args.poll_interval
    if args.max_jobs is not None:
        config.max_jobs = args.max_jobs

    worker = JobWorker(store, config)
    register_handlers(worker, workspace)
    worker.install_signal_handlers()

    print(f"[worker] schema_version={store.schema_version()} db={db_path}", flush=True)
    print(f"[worker] worker_id={config.worker_id} "
          f"types={config.job_types or '(全部)'} lease={config.lease_seconds}s", flush=True)
    stats = worker.run_forever()
    print(f"[worker] 退出：claimed={stats.claimed} completed={stats.completed} "
          f"retried={stats.retried} dead_lettered={stats.dead_lettered} "
          f"reclaimed={stats.reclaimed}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
