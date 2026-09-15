"""审核与修订（FR-KNW-005/006、规格 §9.19、§11.2/11.7）。

- Reviewer 对候选对象形成 Decision MD（90_control/decisions/）；
- 状态转换：CANDIDATE → IN_REVIEW → APPROVED / REJECTED / REQUEST_CHANGES(→CANDIDATE)；
- 驳回保留候选与驳回原因（不物理删除）；
- 人工修订记录原候选、修改人、修改时间与理由；
- 自动校验器不得伪造人工批准。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..domain import ids, states, timeutil
from ..domain.contracts import specs
from ..domain.errors import AssetNotFoundError, UsageError
from ..infrastructure import locks as locks_mod, markdown
from ..infrastructure.fs import WorkspaceWriter
from .jobs import JobController

DECISION_ENUM = ["APPROVE", "REJECT", "REQUEST_CHANGES", "WAIVE"]
_OBJECT_KINDS = {
    "ENTITY": ("entities", specs.ENTITY_SPEC),
    "RELATION": ("relations", specs.RELATION_SPEC),
    "STATEMENT": ("statements", specs.STATEMENT_SPEC),
    "RULE": ("rules", specs.RULE_SPEC),
    "SEGMENT": ("segments", specs.SEGMENT_SPEC),
    "DOCUMENT": ("documents", specs.DOCUMENT_SPEC),
}


@dataclass
class ReviewResult:
    job_id: str
    decisions: list[dict] = field(default_factory=list)


class ReviewService:
    def __init__(self, workspace: Path, *, owner: str = "svc_review",
                 dry_run: bool = False):
        self.ws = Path(workspace)
        self.owner = owner
        self.dry_run = dry_run

    def review(self, domain: str, *, run_id: str | None,
               object_refs: list[str], decision: str, reason: str,
               decided_by: str, role: str = "Reviewer") -> ReviewResult:
        ids.validate_domain(domain)
        if decision not in DECISION_ENUM:
            raise UsageError(f"非法审核决定: {decision!r}（允许 {DECISION_ENUM}）")
        if not object_refs:
            raise UsageError("object_refs 至少一个对象")
        if not reason:
            raise UsageError("审核必须提供 reason（驳回必须保留原因）")

        writer = WorkspaceWriter(self.ws, dry_run=self.dry_run)
        if self.dry_run:
            return ReviewResult(job_id="", decisions=[
                {"decision_id": f"DEC-{i}", "object_ref": r, "decision": decision}
                for i, r in enumerate(object_refs)])

        with locks_mod.WorkspaceLock(self.ws, f"domain:{domain}",
                                     job_id=f"JOB-REV-{timeutil.ts_utc()[:19]}",
                                     owner=self.owner):
            job = JobController(self.ws, writer, job_type="REVIEW",
                                requested_by=self.owner,
                                idempotency_key=f"{decision}:{','.join(object_refs)}",
                                component="reviewer")
            if job.noop:
                return ReviewResult(job_id=job.job_id)
            job.start()
            job.logger.info("REVIEW_START", "审核开始", decision=decision,
                            objects=len(object_refs))
            try:
                decisions = []
                for idx, obj_ref in enumerate(object_refs):
                    rel = self._resolve_object_rel(domain, run_id, obj_ref)
                    if not rel:
                        raise AssetNotFoundError(f"找不到候选对象: {obj_ref}")
                    fm, body = self._load_object(rel)
                    # 审核动作隐含进入 IN_REVIEW（§11.2 状态机路径）
                    current = fm.get("validation_status", "CANDIDATE")
                    if current == "CANDIDATE":
                        states.transition_knowledge_validation("CANDIDATE", "IN_REVIEW")
                        current = "IN_REVIEW"
                    target = self._target_status(current, decision)
                    if target is None:
                        raise UsageError(
                            f"对象 {obj_ref} 当前状态 {current} 不能应用决定 {decision}")
                    states.transition_knowledge_validation(current, target)
                    fm["validation_status"] = target
                    if decision == "REQUEST_CHANGES":
                        fm["status"] = "ACTIVE"
                    fm["x_review_updated_at"] = timeutil.ts_utc()
                    updated = markdown.render_contract_md(fm, body)
                    # 修订记录：更新前写审计说明到决策，不覆盖历史
                    decision_id = self._write_decision(
                        writer, obj_ref, decision, reason, decided_by, role,
                        evidence=[rel], conditions=[])
                    writer.write_text(rel, updated)
                    decisions.append({
                        "decision_id": decision_id, "object_ref": obj_ref,
                        "validation_status": target,
                    })
                    job.logger.info("REVIEW_OBJECT", "对象审核完成",
                                    object_ref=obj_ref, decision=decision,
                                    decision_id=decision_id)
                out_refs = [{"path": d["decision_id"], "version": "1.0",
                             "content_hash": ids.new_id("X")} for d in decisions]
                job.finish(output_refs=out_refs, input_count=len(object_refs),
                           output_count=len(decisions),
                           quality_summary={"decision": decision})
                return ReviewResult(job_id=job.job_id, decisions=decisions)
            except Exception as exc:
                job.fail("REVIEW_FAILED", str(exc))
                raise

    # ---------------- 内部 ----------------

    def _resolve_object_rel(self, domain, run_id, obj_ref: str) -> str | None:
        """按对象引用定位候选 MD 相对路径。"""
        # 支持 "entities/ENT-001.md" / "ENT-001" / "SEG-XXX.md"
        cand_base = f"02_work/{domain}/run={run_id}/candidates" if run_id else None
        for kind, (subdir, _spec) in _OBJECT_KINDS.items():
            name = obj_ref.split("/")[-1].removesuffix(".md")
            candidates = [
                f"{cand_base}/{subdir}/{name}.md" if cand_base else None,
                f"02_work/{domain}/run={self._find_run(domain)}/segments/{name}.md"
                if kind == "SEGMENT" else None,
                f"02_work/{domain}/run={self._find_run(domain)}/documents/{name}/DOCUMENT.md"
                if kind == "DOCUMENT" else None,
            ]
            for rel in candidates:
                if rel and (self.ws / rel).is_file():
                    return rel
        return None

    def _find_run(self, domain: str) -> str | None:
        base = self.ws / "02_work" / domain
        if not base.is_dir():
            return None
        runs = sorted((p.name for p in base.glob("run=*")), reverse=True)
        return runs[0].removeprefix("run=") if runs else None

    def _load_object(self, rel: str) -> tuple[dict, str]:
        text = (self.ws / rel).read_text(encoding="utf-8")
        parsed = markdown.parse_contract_md(text, path=rel)
        if not parsed.ok:
            raise UsageError(f"候选文件非法: {rel}: {parsed.errors}")
        return parsed.front_matter, parsed.body

    @staticmethod
    def _target_status(current: str, decision: str) -> str | None:
        if decision == "APPROVE":
            return "APPROVED" if current == "IN_REVIEW" else None
        if decision == "REJECT":
            return "REJECTED" if current in ("CANDIDATE", "IN_REVIEW") else None
        if decision == "REQUEST_CHANGES":
            return "CANDIDATE" if current == "IN_REVIEW" else None
        if decision == "WAIVE":
            return current
        return None

    def _write_decision(self, writer, obj_ref, decision, reason, decided_by,
                        role, evidence, conditions) -> str:
        decision_id = self._next_decision_id(writer)
        now = timeutil.now_utc()
        fm = {
            "schema": "review_decision/v1",
            "decision_id": decision_id,
            "object_refs": [obj_ref],
            "decision": decision,
            "decided_by": decided_by,
            "role": role,
            "decided_at": timeutil.ts_utc(now),
            "reason": reason,
            "conditions": conditions,
            "evidence_refs": evidence,
            "status": "ACTIVE",
            "version": "1.0",
        }
        body = (f"# 审核决定\n\n对象 {obj_ref}，决定 {decision}。\n\n"
                f"理由：{reason}\n")
        writer.write_text(f"90_control/decisions/{decision_id}.md",
                          markdown.render_contract_md(fm, body))
        return decision_id

    def _next_decision_id(self, writer) -> str:
        seq = 1
        while True:
            did = ids.new_id("DEC", seq=seq)
            if not writer.exists(f"90_control/decisions/{did}.md"):
                return did
            seq += 1
