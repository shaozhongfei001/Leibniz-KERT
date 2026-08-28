"""任务控制器（FR-CTL-001/002/005/006、规格 §9.14/§9.15/§11.1）。

- 每个任务：90_control/jobs/<job_id>/STATUS.md + 原始日志 + 完成后 RUN_REPORT.md；
- 状态转换校验前态（§11.1）；
- 幂等：同 job_type + idempotency_key 的任务，终态则 NO_OP，执行中则冲突。

M2.4（Owner 决策路线 C′）状态权威变更
------------------------------------
自 M2.4 起，当注入 ``runtime_store`` 时：

- **SQLite Runtime Store 为 Job 状态的唯一权威**（原子领取、lease、重试、
  dead-letter 均在库内完成，见 :mod:`dkws.infrastructure.runtime_store`）；
- ``STATUS.md`` / ``RUN_REPORT.md`` 降级为**从 SQLite 派生的只读审计投影**，
  仍按 §9.14/§9.15 契约写出，以保持 FR-CTL 审计产物要求与既有读取路径不变；
- 幂等判定优先查 SQLite；未注入 Store 时回落到扫描 ``STATUS.md``（M1 行为）。

派生方向是单向的：**SQLite → 文件**。任何组件都不得反向以文件内容更新状态。
"""

from __future__ import annotations

import logging
import re
import time
from pathlib import Path

from ..domain import hashing, ids, states, timeutil
from ..domain.errors import ConflictError, UsageError
from ..infrastructure import logging as logging_mod, markdown
from ..infrastructure.fs import WorkspaceWriter
from ..infrastructure.runtime_store import RuntimeStore

_log = logging.getLogger(__name__)

STATUS_HEADINGS = ["当前摘要", "输入输出", "错误与恢复建议"]
REPORT_HEADINGS = ["执行摘要", "输入与输出", "质量结果", "警告与错误",
                   "可复现信息", "非声明事项"]

_STATUS_RE = re.compile(r"^status:\s*\"?([A-Z_]+)", re.M)


class JobController:
    def __init__(self, workspace: Path, writer: WorkspaceWriter, *,
                 job_type: str, requested_by: str, idempotency_key: str,
                 input_refs: list[dict] | None = None,
                 component: str = "dkws",
                 runtime_store: RuntimeStore | None = None):
        """初始化任务控制器。

        Args:
            runtime_store: M2.4 起注入后，SQLite 成为状态权威，
                ``STATUS.md`` 转为派生投影；``None`` 时保持 M1 的纯文件行为。
        """
        self.ws = Path(workspace)
        self.writer = writer
        self.job_type = job_type.upper()
        self.requested_by = requested_by
        self.idempotency_key = idempotency_key
        self.input_refs = input_refs or []
        self.noop = False
        self._store = runtime_store
        self._existing_fm: dict = {}
        self.job_id = self._resolve_job_id()
        self.logger = logging_mod.JobLogger(self.ws, self.job_id, component=component)
        self.started_at = timeutil.now_utc()
        self.updated_at = self.started_at
        self.status = "PENDING"
        self.progress = 0
        self.output_refs: list[dict] = list(self._existing_fm.get("output_refs", []))
        self.error_code: str | None = None
        self.error_message: str | None = None
        if self._store is not None and not self.noop:
            # 在权威表登记 Job；幂等冲突已在 _resolve_job_id 阶段拦截
            self._store.create_job(
                self.job_id, self.job_type,
                {"requested_by": self.requested_by, "input_refs": self.input_refs},
                idem_key=self.idempotency_key)

    # ---------------- 幂等 ----------------

    def _resolve_job_id(self) -> str:
        """解析 Job ID 并判定幂等。

        注入 Store 时以 SQLite 为权威（单一数据源，无需扫描文件系统）；
        未注入时回落到扫描 ``STATUS.md``（保持 M1 行为，不破坏既有调用方）。
        """
        if self._store is not None:
            return self._resolve_job_id_from_store()
        return self._resolve_job_id_from_files()

    def _resolve_job_id_from_store(self) -> str:
        """基于 SQLite 权威表判定幂等并分配 Job ID。"""
        existing = self._store.find_job_by_idem(self.job_type, self.idempotency_key)
        if existing is not None:
            if existing.status in states.JOB_TERMINAL:
                self.noop = True
                self._existing_fm = {"job_id": existing.job_id,
                                     "output_refs": (existing.result or {}).get(
                                         "output_refs", [])}
                return existing.job_id
            raise ConflictError(
                f"幂等键冲突：任务 {existing.job_id} 正在执行"
                f"（status={existing.status}）")
        max_seq = self._store.max_job_seq(self.job_type)
        return ids.new_job_id(self.job_type, seq=max_seq + 1)

    def _resolve_job_id_from_files(self) -> str:
        """扫描 ``STATUS.md`` 判定幂等（M1 兼容路径）。"""
        jobs_root = self.ws / "90_control" / "jobs"
        if not jobs_root.is_dir():
            return ids.new_job_id(self.job_type)
        max_seq = 0
        for status_file in sorted(jobs_root.glob("*/STATUS.md")):
            text = status_file.read_text(encoding="utf-8")
            parsed = markdown.parse_contract_md(text, path=str(status_file))
            if not parsed.ok:
                continue
            fm = parsed.front_matter
            if (fm.get("job_type") == self.job_type
                    and fm.get("idempotency_key") == self.idempotency_key):
                existing_status = fm.get("status")
                if existing_status in states.JOB_TERMINAL:
                    self.noop = True
                    self._existing_fm = fm
                    return fm.get("job_id", status_file.parent.name)
                raise ConflictError(
                    f"幂等键冲突：任务 {fm.get('job_id')} 正在执行（status={existing_status}）"
                )
            # 追踪本类型已用序号，避免 new_job_id 默认 seq=1 撞号
            m = re.match(rf"JOB-{self.job_type.replace('-', '_')}-\d{{8}}-(\d+)",
                         fm.get("job_id") or status_file.parent.name)
            if m:
                max_seq = max(max_seq, int(m.group(1)))
        return ids.new_job_id(self.job_type, seq=max_seq + 1)

    def _sync_store(self, *, result: dict | None = None) -> None:
        """把当前状态同步到 SQLite 权威表（未注入 Store 时为空操作）。

        调用顺序约定：**先同步 SQLite，再派生写文件**，
        确保任何时刻文件内容都不领先于权威表。
        """
        if self._store is None:
            return
        self._store.sync_job_state(
            self.job_id, self.status, progress=self.progress,
            error_code=self.error_code, error_message=self.error_message,
            result=result)

    # ---------------- 生命周期 ----------------

    def start(self) -> "JobController":
        states.transition_job("PENDING", "RUNNING")
        self.status = "RUNNING"
        self._sync_store()
        self._write_status()
        self.logger.info("JOB_START", "任务开始", job_type=self.job_type)
        return self

    def update(self, *, progress: int | None = None, status: str | None = None,
               error_code: str | None = None, error_message: str | None = None,
               log_code: str = "JOB_UPDATE", log_message: str = "进度更新") -> None:
        if progress is not None:
            if not isinstance(progress, int) or not 0 <= progress <= 100:
                raise UsageError(f"progress 必须为 0..100: {progress!r}")
            self.progress = progress
        if status is not None:
            states.transition_job(self.status, status)
            self.status = status
        if error_code is not None:
            self.error_code = error_code
        if error_message is not None:
            self.error_message = error_message
        self.updated_at = timeutil.now_utc()
        self._sync_store()
        self._write_status()
        self.logger.log("INFO" if status not in ("FAILED", "CANCELLED") else "WARN",
                        log_code, log_message,
                        progress=self.progress, status=self.status)

    def finish(self, *, output_refs: list[dict], input_count: int,
               output_count: int, rejected_count: int = 0,
               warning_count: int = 0, quality_summary: dict | None = None) -> None:
        states.transition_job(self.status, "VALIDATING")
        self.status = "VALIDATING"
        self.progress = 99
        self.updated_at = timeutil.now_utc()
        self._sync_store()
        self._write_status()
        self.logger.info("JOB_VALIDATING", "输出校验中")
        states.transition_job(self.status, "COMPLETED")
        self.status = "COMPLETED"
        self.progress = 100
        self.output_refs = output_refs
        self.updated_at = timeutil.now_utc()
        finished_at = timeutil.now_utc()
        self._sync_store(result={"output_refs": output_refs,
                                 "output_count": output_count,
                                 "rejected_count": rejected_count})
        self._write_status(finished_at=finished_at)
        self._write_report(
            final_status="COMPLETED", finished_at=finished_at,
            input_count=input_count, output_count=output_count,
            rejected_count=rejected_count, warning_count=warning_count,
            error_count=0, quality_summary=quality_summary or {},
        )
        self.logger.info("JOB_COMPLETED", "任务完成",
                         output_count=output_count, rejected_count=rejected_count)

    def fail(self, error_code: str, message: str) -> None:
        if self.status not in states.JOB_TERMINAL:
            try:
                states.transition_job(self.status, "FAILED")
            except UsageError:
                pass
            self.status = "FAILED"
        self.error_code = error_code
        self.error_message = message
        self.updated_at = timeutil.now_utc()
        finished_at = timeutil.now_utc()
        self._sync_store()
        self._write_status(finished_at=finished_at)
        self._write_report(
            final_status="FAILED", finished_at=finished_at,
            input_count=len(self.input_refs), output_count=0,
            rejected_count=0, warning_count=0, error_count=1,
            quality_summary={"error": error_code},
        )
        self.logger.error("JOB_FAILED", message, error_code=error_code)

    # ---------------- 文件写入 ----------------

    def _status_rel(self) -> str:
        return f"90_control/jobs/{self.job_id}/STATUS.md"

    def _write_status(self, finished_at=None) -> None:
        """派生写出 ``STATUS.md``（M2.4 起为只读投影，权威在 SQLite）。"""
        fm = {
            "schema": "job_status/v1",
            "job_id": self.job_id,
            "job_type": self.job_type,
            "status": self.status,
            "requested_by": self.requested_by,
            "idempotency_key": self.idempotency_key,
            "input_refs": self.input_refs,
            "output_refs": self.output_refs,
            "started_at": timeutil.ts_utc(self.started_at),
            "updated_at": timeutil.ts_utc(self.updated_at),
            "finished_at": timeutil.ts_utc(finished_at) if finished_at else None,
            "progress": self.progress,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "publish_status": "NOT_PUBLISHED",
            "version": "1.0",
        }
        body = (
            "# 任务状态\n\n"
            "## 当前摘要\n\n"
            f"任务 {self.job_id}（{self.job_type}）当前状态 {self.status}，进度 {self.progress}%。\n\n"
            "## 输入输出\n\n"
            "输入见 Front Matter input_refs；输出见 output_refs。\n\n"
            "## 错误与恢复建议\n\n"
            + (f"错误码 {self.error_code}：{self.error_message}\n" if self.error_code else "无。\n")
        )
        self.writer.write_text(self._status_rel(), markdown.render_contract_md(fm, body))

    def _write_report(self, *, final_status, finished_at, input_count, output_count,
                      rejected_count, warning_count, error_count, quality_summary) -> None:
        duration_ms = int((finished_at - self.started_at).total_seconds() * 1000)
        log_sha = self.logger.sha256() or hashing.sha256_hex("")
        fm = {
            "schema": "run_report/v1",
            "job_id": self.job_id,
            "final_status": final_status,
            "started_at": timeutil.ts_utc(self.started_at),
            "finished_at": timeutil.ts_utc(finished_at),
            "duration_ms": duration_ms,
            "input_count": input_count,
            "output_count": output_count,
            "rejected_count": rejected_count,
            "warning_count": warning_count,
            "error_count": error_count,
            "quality_summary": quality_summary,
            "log_sha256": log_sha,
            "status": final_status,
            "version": "1.0",
        }
        body = (
            "# 运行报告\n\n"
            f"## 执行摘要\n\n任务 {self.job_id} 结束，最终状态 {final_status}。\n\n"
            f"## 输入与输出\n\n输入 {input_count}，输出 {output_count}，拒绝 {rejected_count}。\n\n"
            f"## 质量结果\n\n{quality_summary}\n\n"
            f"## 警告与错误\n\n警告 {warning_count}，错误 {error_count}。\n\n"
            f"## 可复现信息\n\n日志 SHA-256: {log_sha}\n\n"
            "## 非声明事项\n\n本报告不构成业务审批或合规结论。\n"
        )
        self.writer.write_text(
            f"90_control/jobs/{self.job_id}/RUN_REPORT.md",
            markdown.render_contract_md(fm, body),
        )

    # ---------------- 查询 ----------------

    def current_status(self) -> dict:
        return {
            "job_id": self.job_id,
            "job_type": self.job_type,
            "status": self.status,
            "progress": self.progress,
            "noop": self.noop,
        }


def read_job_status(ws: Path, job_id: str) -> dict:
    rel = f"90_control/jobs/{job_id}/STATUS.md"
    p = Path(ws) / rel
    if not p.is_file():
        from ..domain.errors import AssetNotFoundError

        raise AssetNotFoundError(f"任务不存在: {job_id}")
    text = p.read_text(encoding="utf-8")
    parsed = markdown.parse_contract_md(text, path=rel)
    if not parsed.ok:
        raise UsageError(f"任务状态文件非法: {rel}: {parsed.errors}")
    result = parsed.front_matter
    # 异步技能作业：完成时附加 result.json（v1.4）
    res_file = Path(ws) / f"90_control/jobs/{job_id}/result.json"
    if res_file.is_file():
        try:
            import json as _json
            result["skill_result"] = _json.loads(res_file.read_text(encoding="utf-8"))
        except Exception:
            _log.warning("任务结果文件读取失败（job_id=%s）", job_id, exc_info=True
                         )
    return result


def hash_ref(path: str) -> dict:
    """把工作区相对路径转为 input/output ref（自动计算内容哈希）。"""
    return {"path": path, "version": "1.0", "content_hash": "computed"}
