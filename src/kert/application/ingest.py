"""原始资产接入（FR-ING-001~006、规格 §11.4、§9.1）。

流程：
1. 校验域、源文件（存在/大小/扩展名/实际媒体类型）；
2. 获取领域写锁；
3. 计算哈希，幂等检查（同键同内容 → NO_OP；同键不同内容 → 冲突）；
4. 临时批次目录复制文件（绝不移动用户输入）；
5. 生成并校验 MANIFEST.md（OPEN）；
6. 原子重命名为正式批次目录；
7. Manifest 置 CLOSED；
8. 写血缘起点、任务状态、日志、运行报告。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..domain import hashing, ids, timeutil
from ..domain.contracts import specs
from ..domain.contracts.base import validate_contract
from ..domain.errors import IdempotencyConflictError, UsageError
from ..infrastructure import locks as locks_mod, markdown, media
from ..infrastructure.fs import WorkspaceWriter
from .jobs import JobController

_EXT_ROLE = {
    ".parquet": "DATA", ".csv": "DATA", ".json": "DATA", ".jsonl": "DATA",
    ".pdf": "DOCUMENT", ".docx": "DOCUMENT", ".html": "DOCUMENT",
    ".htm": "DOCUMENT", ".txt": "DOCUMENT", ".md": "DOCUMENT",
    ".png": "IMAGE", ".jpg": "IMAGE", ".jpeg": "IMAGE", ".gif": "IMAGE",
    ".log": "OTHER",
}


@dataclass
class IngestResult:
    batch_id: str
    job_id: str
    noop: bool = False
    manifest_rel: str | None = None
    files: list[dict] = field(default_factory=list)
    plan: list[str] = field(default_factory=list)


class Ingestor:
    def __init__(self, workspace: Path, *, owner: str = "svc_ingestor",
                 dry_run: bool = False, max_bytes: int = media.DEFAULT_MAX_BYTES):
        self.ws = Path(workspace)
        self.owner = owner
        self.dry_run = dry_run
        self.max_bytes = max_bytes

    # ---------------- 主入口 ----------------

    def ingest(self, domain: str, sources: list[Path], idempotency_key: str, *,
               source_system: str = "MANUAL_UPLOAD", source_uri: str | None = None,
               roles: dict[str, str] | None = None) -> IngestResult:
        ids.validate_domain(domain)
        if not sources:
            raise UsageError("至少需要一个源文件")
        sources = [Path(s) for s in sources]

        # 1. 源校验 + 哈希
        checks = [media.check_source_allowed(s, max_bytes=self.max_bytes) for s in sources]
        file_hashes = [hashing.sha256_file(s) for s in sources]

        writer = WorkspaceWriter(self.ws, dry_run=self.dry_run)
        if self.dry_run:
            batch_id = ids.new_id("BATCH")
            base = f"01_raw/{domain}/batch={batch_id}"
            plan = [f"{base}/MANIFEST.md"] + [f"{base}/{s.name}" for s in sources]
            return IngestResult(batch_id=batch_id, job_id="", plan=plan)

        # 2. 锁
        with locks_mod.WorkspaceLock(self.ws, f"domain:{domain}",
                                     job_id=f"JOB-INGEST-{timeutil.ts_utc()[:19]}",
                                     owner=self.owner):
            # 3. 任务（幂等查重）
            input_refs = [
                {"path": s.name, "version": "1.0", "content_hash": h}
                for s, h in zip(sources, file_hashes)
            ]
            job = JobController(
                self.ws, writer, job_type="INGEST", requested_by=self.owner,
                idempotency_key=idempotency_key, input_refs=input_refs,
                component="ingestor",
            )
            if job.noop:
                _assert_same_content(job, input_refs)
                batch_id = _batch_from_job(job)
                job.logger.info("INGEST_NOOP", "幂等命中，返回原批次",
                                idempotency_key=idempotency_key)
                return IngestResult(batch_id=batch_id,
                                    job_id=job.job_id, noop=True)
            job.start()
            job.logger.info("INGEST_START", "接入开始",
                            domain=domain, idempotency_key=idempotency_key,
                            source_count=len(sources))

            batch_id = self._allocate_batch_id(domain, job)
            tmp_base = f"01_raw/{domain}/.tmp-{batch_id}"
            final_base = f"01_raw/{domain}/batch={batch_id}"
            job.logger.info("INGEST_COPY", "复制源文件到临时批次",
                            batch_id=batch_id)
            try:
                # 4. 复制文件（绝不移动输入）
                copied: list[dict] = []
                for s, info, h in zip(sources, checks, file_hashes):
                    rel = f"{tmp_base}/{s.name}"
                    writer.copy_file(s, rel)
                    copied.append({
                        "path": s.name,
                        "media_type": info.mime,
                        "size_bytes": s.stat().st_size,
                        "sha256": h,
                        "role": (roles or {}).get(s.name, _EXT_ROLE.get(s.suffix.lower(), "OTHER")),
                    })
                # 5. 生成并校验 MANIFEST.md
                manifest_text = self._render_manifest(
                    batch_id, domain, copied, idempotency_key,
                    source_system, source_uri, status="OPEN",
                )
                validate_contract(manifest_text, specs.MANIFEST_SPEC,
                                  path=f"{tmp_base}/MANIFEST.md").raise_if_invalid()
                writer.write_text(f"{tmp_base}/MANIFEST.md", manifest_text)
                # 6. 原子重命名正式批次
                writer.atomic_replace_dir(tmp_base, final_base)
                # 7. 置 CLOSED（批次关闭前可追加，关闭后不可变）
                closed_text = self._render_manifest(
                    batch_id, domain, copied, idempotency_key,
                    source_system, source_uri, status="CLOSED",
                )
                validate_contract(closed_text, specs.MANIFEST_SPEC,
                                  path=f"{final_base}/MANIFEST.md").raise_if_invalid()
                writer.write_text(f"{final_base}/MANIFEST.md", closed_text)
            except Exception:
                # 失败不留被误认为 CLOSED 的不完整批次（§11.4）
                import shutil as _shutil
                from ..domain import paths as _paths
                tmp_p = _paths.resolve_ws_path(self.ws, tmp_base)
                if tmp_p.is_dir():
                    _shutil.rmtree(tmp_p)
                raise

            # 8. 血缘起点
            manifest_rel = f"{final_base}/MANIFEST.md"
            self._write_lineage(batch_id, job.job_id, input_refs,
                                manifest_rel, writer)
            # 9. 完成
            out_refs = [{"path": manifest_rel, "version": "1.0",
                         "content_hash": hashing.sha256_file(
                             writer.resolve(manifest_rel))}]
            job.finish(output_refs=out_refs, input_count=len(sources),
                       output_count=len(copied) + 1,
                       quality_summary={"gates_passed": ["G0"]})
            return IngestResult(
                batch_id=batch_id, job_id=job.job_id, noop=False,
                manifest_rel=manifest_rel,
                files=[{"path": f["path"], "role": f["role"],
                        "sha256": f["sha256"]} for f in copied],
            )

    # ---------------- 辅助 ----------------

    def _allocate_batch_id(self, domain: str, job: JobController) -> str:
        now = timeutil.now_utc()
        seq = 1
        while True:
            batch_id = ids.new_id("BATCH", now=now, seq=seq)
            rel = f"01_raw/{domain}/batch={batch_id}"
            if not (self.ws / rel).exists():
                return batch_id
            seq += 1

    def _render_manifest(self, batch_id, domain, files, idempotency_key,
                         source_system, source_uri, *, status) -> str:
        fm = {
            "schema": "raw_manifest/v1",
            "batch_id": batch_id,
            "domain": domain,
            "status": status,
            "source_system": source_system,
            "source_uri": source_uri,
            "idempotency_key": idempotency_key,
            "received_at": timeutil.ts_utc(),
            "received_by": self.owner,
            "files": files,
            "closed_at": timeutil.ts_utc() if status == "CLOSED" else None,
            "version": "1.0",
        }
        body = (
            "# 原始批次清单\n\n"
            f"## 来源说明\n\n来源系统 {source_system}。\n\n"
            "## 接入备注\n\n无。\n"
        )
        return markdown.render_contract_md(fm, body)

    def _write_lineage(self, batch_id, job_id, input_refs, manifest_rel,
                       writer: WorkspaceWriter) -> str:
        lineage_id = ids.new_id("LG")
        now = timeutil.now_utc()
        manifest_hash = hashing.sha256_file(writer.resolve(manifest_rel))
        fm = {
            "schema": "lineage/v1",
            "lineage_id": lineage_id,
            "process_id": "ingest",
            "job_id": job_id,
            "inputs": [
                {"asset_id": r.get("path", "input"), "version": "1.0",
                 "path": r.get("path", ""), "content_hash": r.get("content_hash", "")}
                for r in input_refs
            ],
            "outputs": [{"asset_id": batch_id, "version": "1.0",
                         "path": manifest_rel, "content_hash": manifest_hash}],
            "transformation_id": "ingest_copy",
            "transformation_version": "1.0.0",
            "code_version": "0.1.0",
            "started_at": timeutil.ts_utc(now),
            "finished_at": timeutil.ts_utc(),
            "status": "COMPLETED",
            "version": "1.0",
        }
        body = (
            "# 血缘记录\n\n"
            "## 转换说明\n\n原始文件复制接入并登记批次。\n\n"
            "## 输入\n\n见 Front Matter inputs。\n\n"
            "## 输出\n\n见 Front Matter outputs。\n\n"
            "## 已知限制\n\n无。\n"
        )
        rel = f"90_control/lineage/ingest/{lineage_id}.md"
        writer.write_text(rel, markdown.render_contract_md(fm, body))
        return rel


def _batch_from_job(job: JobController) -> str:
    """从已完成任务的 output_refs 提取原批次 ID。"""
    for ref in job.output_refs or []:
        path = ref.get("path", "")
        if "/batch=" in path:
            seg = path.split("batch=", 1)[1]
            return seg.split("/", 1)[0]
    raise UsageError(f"无法从任务 {job.job_id} 定位原批次")


def _assert_same_content(job: JobController, new_input_refs: list[dict]) -> None:
    """同幂等键必须同内容，否则 IDEMPOTENCY_CONFLICT（FR-ING-003/004）。"""
    old = job._existing_fm.get("input_refs", [])
    old_map = {r.get("path"): r.get("content_hash") for r in old}
    new_map = {r.get("path"): r.get("content_hash") for r in new_input_refs}
    if old_map != new_map:
        raise IdempotencyConflictError(
            "同一幂等键提交了不同内容，拒绝重复接入",
            details={"idempotency_key": job.idempotency_key},
        )
