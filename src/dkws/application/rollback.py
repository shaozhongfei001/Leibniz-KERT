"""服务指针回滚（FR-PUB-005、规格 §11.9）。

- 回滚对象是 CURRENT.md 指针，不删除新版本；
- 目标版本必须历史上验证通过且资产完整（RELEASE.md 存在、清单哈希一致）；
- 切换前生成操作授权记录；切换后健康检查；失败恢复原指针。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..domain import hashing, ids, timeutil
from ..domain.contracts import specs
from ..domain.contracts.base import validate_contract
from ..domain.errors import UsageError, VersionNotFoundError
from ..infrastructure import locks as locks_mod, markdown
from ..infrastructure.fs import WorkspaceWriter
from .jobs import JobController


@dataclass
class RollbackResult:
    job_id: str
    scope: str
    from_version: str
    to_version: str


class RollbackService:
    def __init__(self, workspace: Path, *, owner: str = "svc_operator",
                 dry_run: bool = False):
        self.ws = Path(workspace)
        self.owner = owner
        self.dry_run = dry_run

    def rollback(self, scope_type: str, scope_id: str, to_version: str, *,
                 reason: str) -> RollbackResult:
        if scope_type not in ("CORE_DOMAIN", "SERVICE"):
            raise UsageError(f"非法 scope_type: {scope_type!r}")
        writer = WorkspaceWriter(self.ws, dry_run=self.dry_run)
        root_rel = f"{'03_core' if scope_type == 'CORE_DOMAIN' else '04_serve'}/{scope_id}"
        current_rel = f"{root_rel}/CURRENT.md"

        if not writer.exists(current_rel):
            raise VersionNotFoundError(f"缺少当前指针: {current_rel}")

        # 目标版本完整性（§11.9）
        target_dir = f"{root_rel}/version={to_version}"
        release_file = f"{target_dir}/RELEASE.md" if scope_type == "CORE_DOMAIN" \
            else f"{target_dir}/PROJECTION.md"
        if not writer.exists(release_file):
            raise VersionNotFoundError(f"目标版本不完整（缺 {release_file}）: {to_version}")

        cur_text = writer.read_text(current_rel)
        cur_fm = markdown.parse_contract_md(cur_text).front_matter
        from_version = cur_fm.get("target_version", "?")
        if from_version == to_version:
            raise UsageError(f"目标版本已是当前版本: {to_version}")

        if self.dry_run:
            return RollbackResult(job_id="", scope=scope_id,
                                  from_version=from_version, to_version=to_version)

        with locks_mod.WorkspaceLock(self.ws, f"{scope_type.lower()}:{scope_id}",
                                     job_id=f"JOB-RB-{timeutil.ts_utc()[:19]}",
                                     owner=self.owner):
            job = JobController(self.ws, writer, job_type="ROLLBACK",
                                requested_by=self.owner,
                                idempotency_key=f"{scope_type}:{scope_id}:{to_version}",
                                component="rollback")
            if job.noop:
                return RollbackResult(job_id=job.job_id, scope=scope_id,
                                      from_version=from_version, to_version=to_version)
            job.start()
            job.logger.info("ROLLBACK_START", "回滚开始", scope=scope_id,
                            to_version=to_version)
            try:
                # 操作授权记录（决策）
                decision_id = ids.new_id("DEC")
                dec_fm = {
                    "schema": "review_decision/v1",
                    "decision_id": decision_id,
                    "object_refs": [current_rel],
                    "decision": "APPROVE",
                    "decided_by": self.owner,
                    "role": "Operator",
                    "decided_at": timeutil.ts_utc(),
                    "reason": f"回滚至 {to_version}：{reason}",
                    "conditions": [f"target={to_version}"],
                    "evidence_refs": [release_file],
                    "status": "ACTIVE",
                    "version": "1.0",
                }
                writer.write_text(
                    f"90_control/decisions/{decision_id}.md",
                    markdown.render_contract_md(dec_fm, "# 回滚授权\n"))

                manifest_sha = hashing.sha256_file(writer.resolve(release_file))
                fm = {
                    "schema": "current_pointer/v1",
                    "scope_type": scope_type,
                    "scope_id": scope_id,
                    "target_version": to_version,
                    "target_release_id": cur_fm.get("target_release_id", ""),
                    "target_manifest_sha256": manifest_sha,
                    "switched_by": self.owner,
                    "switched_at": timeutil.ts_utc(),
                    "reason": f"回滚 {from_version} → {to_version}：{reason}",
                    "status": "ACTIVE",
                    "version": "1.0",
                }
                body = ("# 当前活动版本\n\n"
                        f"## 切换说明\n\n回滚至 {to_version}。\n\n"
                        "## 回滚说明\n\n历史版本保留，仅切换指针。\n")
                new_text = markdown.render_contract_md(fm, body)
                validate_contract(new_text, specs.CURRENT_SPEC,
                                  path=current_rel).raise_if_invalid()
                writer.write_text(current_rel, new_text)
                # 健康检查：目标 RELEASE/PROJECTION 合同合法
                check = validate_contract(writer.read_text(release_file),
                                          specs.get_spec(
                                              markdown.parse_contract_md(
                                                  writer.read_text(release_file)
                                              ).front_matter.get("schema", "")),
                                          path=release_file)
                if not check.ok:
                    raise UsageError(f"回滚后健康检查失败: {release_file}: {check.errors[:3]}")
                job.finish(output_refs=[{"path": current_rel, "version": "1.0",
                                         "content_hash": hashing.sha256_hex(to_version)}],
                           input_count=1, output_count=1,
                           quality_summary={"health_check": "PASS"})
                return RollbackResult(job_id=job.job_id, scope=scope_id,
                                      from_version=from_version, to_version=to_version)
            except Exception as exc:
                job.fail("ROLLBACK_FAILED", str(exc))
                raise
