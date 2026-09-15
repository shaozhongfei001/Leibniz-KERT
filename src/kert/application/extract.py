"""知识候选抽取（FR-KNW-001~003、FR-SRV-006、规格 §11.6）。

- 从已验证片段生成实体/关系/声明/规则候选 MD；
- 强制 validation_status=CANDIDATE（模型/确定性输出不得直接 APPROVED）；
- 记录来源片段、抽取器、模型/提示词版本与置信度；
- 确定性适配器保证无模型时端到端可用（§1.6、§6.3）；
- 输出 publish_status=NOT_PUBLISHED（由任务状态记录）。
"""

from __future__ import annotations

import base64
import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

from ..domain import hashing as hashing_mod, ids, timeutil
from ..domain.contracts import specs
from ..domain.contracts.base import validate_contract
from ..domain.errors import UsageError
from ..infrastructure import locks as locks_mod, markdown
from ..infrastructure.fs import WorkspaceWriter
from .jobs import JobController

ENTITY_PATTERNS = [
    ("PRODUCT", re.compile(r"产品\s*([A-Z][A-Za-z0-9]*)")),
    ("MATERIAL", re.compile(r"材料\s*([A-Z][A-Za-z0-9]*)")),
]
RELATION_PATTERN = re.compile(r"产品\s*([A-Z][A-Za-z0-9]*)\s*需要\s*材料\s*([A-Z][A-Za-z0-9]*)")
STATEMENT_PATTERN = re.compile(r"产品\s*([A-Z][A-Za-z0-9]*)\s*利率\s*(?:为|是)?\s*(\d+(?:\.\d+)?)\s*%")
RULE_PATTERN = re.compile(r"规则[:：]\s*利率\s*(?:不超过|小于等于)?\s*(\d+)\s*%?")
NEGATED_PATTERN = re.compile(r"产品\s*([A-Z][A-Za-z0-9]*)\s*(?:不可|不得|无法)\s*("
                             r"(?:申请|提供))")


def _stable_id(prefix: str, *parts: str) -> str:
    raw = "|".join(parts)
    digest = hashlib.sha256(raw.encode("utf-8")).digest()
    b32 = base64.b32encode(digest).decode("ascii").rstrip("=")
    return f"{prefix}-" + b32[:12]


@dataclass
class Candidate:
    kind: str  # ENTITY/RELATION/STATEMENT/RULE
    asset_id: str
    front_matter: dict
    body: str


@dataclass
class ExtractResult:
    run_id: str
    job_id: str
    candidates: list[dict] = field(default_factory=list)
    plan: list[str] = field(default_factory=list)


class KnowledgeExtractor:
    def __init__(self, workspace: Path, *, owner: str = "svc_extractor",
                 dry_run: bool = False, extractor_id: str = "deterministic_extractor",
                 extractor_version: str = "1.0.0"):
        self.ws = Path(workspace)
        self.owner = owner
        self.dry_run = dry_run
        self.extractor_id = extractor_id
        self.extractor_version = extractor_version

    def extract(self, domain: str, batch_id: str, *, run_id: str | None = None,
                segment_filter: list[str] | None = None) -> ExtractResult:
        ids.validate_domain(domain)
        ids.validate_id(batch_id, "batch_id")
        writer = WorkspaceWriter(self.ws, dry_run=self.dry_run)

        # 定位片段：默认最近一次解析 run 的片段
        run_id = run_id or self._latest_parse_run(domain)
        if not run_id:
            raise UsageError(f"域 {domain} 没有可用的解析 run（请先 parse-doc）")
        seg_base = f"02_work/{domain}/run={run_id}/segments"
        segment_files = sorted((self.ws / seg_base).rglob("*.md"))
        if not segment_files:
            raise UsageError(f"run={run_id} 没有片段")
        if segment_filter:
            segment_files = [f for f in segment_files
                             if f.stem in segment_filter or f.name in segment_filter]

        if self.dry_run:
            cand_base = f"02_work/{domain}/run={run_id}/candidates"
            return ExtractResult(run_id=run_id, job_id="", plan=[
                f"{cand_base}/entities/ENT-XXXX.md",
                f"{cand_base}/relations/REL-XXXX.md",
                f"{cand_base}/statements/ST-XXXX.md",
                f"{cand_base}/rules/RULE-XXXX.md",
            ])

        with locks_mod.WorkspaceLock(self.ws, f"domain:{domain}",
                                     job_id=f"JOB-EXT-{timeutil.ts_utc()[:19]}",
                                     owner=self.owner):
            job = JobController(self.ws, writer, job_type="EXTRACT",
                                requested_by=self.owner,
                                idempotency_key=f"{batch_id}:{run_id}:extract",
                                component="extractor")
            if job.noop:
                return ExtractResult(run_id=run_id, job_id=job.job_id)
            job.start()
            job.logger.info("EXTRACT_START", "知识抽取开始",
                            domain=domain, run_id=run_id, segments=len(segment_files))
            try:
                seg_data = []
                for sf in segment_files:
                    text = sf.read_text(encoding="utf-8")
                    rv = validate_contract(text, specs.SEGMENT_SPEC, path=str(sf))
                    if not rv.ok:
                        raise UsageError(f"片段合同失败: {sf.name}: {rv.errors[:3]}")
                    fm = rv.front_matter
                    seg_data.append({
                        "segment_id": fm["segment_id"],
                        "document_id": fm["document_id"],
                        "content": _extract_original(rv.body),
                        "heading_path": fm.get("heading_path", []),
                        "page_from": fm.get("page_from"),
                        "page_to": fm.get("page_to"),
                        "source_path": str(sf.relative_to(self.ws)),
                    })
                job.update(progress=30, log_code="EXTRACT_LOAD", log_message="片段加载完成")

                candidates = self._extract_candidates(seg_data, domain)
                job.update(progress=70, log_code="EXTRACT_CANDIDATES",
                           log_message=f"候选生成 {len(candidates)} 个")

                cand_base = f"02_work/{domain}/run={run_id}/candidates"
                written: list[dict] = []
                for cand in candidates:
                    # 规则候选 DSL 安全检查（FR-KNW-001、§14.2）
                    if cand.kind == "RULE":
                        from ..domain.rules import dsl as dsl_mod

                        dsl_errors = (
                            dsl_mod.validate_dsl(cand.front_matter.get("when", {}))
                            + dsl_mod.validate_dsl(cand.front_matter.get("then", {})))
                        if cand.front_matter.get("else"):
                            dsl_errors += dsl_mod.validate_dsl(cand.front_matter["else"])
                        dsl_errors += dsl_mod.validate_rule_body_text(cand.body)
                        if dsl_errors:
                            raise UsageError(
                                f"规则候选 DSL 非法: {cand.asset_id}: {dsl_errors[:3]}")
                    rel = self._candidate_rel(cand, cand_base)
                    text = markdown.render_contract_md(cand.front_matter, cand.body)
                    # 强制候选状态（FR-KNW-003）
                    if cand.front_matter.get("validation_status") != "CANDIDATE":
                        raise UsageError(f"候选 {cand.asset_id} 未处于 CANDIDATE（状态强制失败）")
                    validate_contract(text, self._spec_for(cand.kind),
                                      path=rel).raise_if_invalid(rel)
                    writer.write_text(rel, text)
                    written.append({"kind": cand.kind, "asset_id": cand.asset_id,
                                    "path": rel})

                out_refs = [{"path": w["path"], "version": "1.0",
                             "content_hash": hashing_mod.sha256_hex(w["asset_id"])}
                            for w in written]
                job.finish(output_refs=out_refs, input_count=len(segment_files),
                           output_count=len(written),
                           quality_summary={"candidates": len(written)})
                return ExtractResult(run_id=run_id, job_id=job.job_id,
                                     candidates=written)
            except Exception as exc:
                job.fail("EXTRACT_FAILED", str(exc))
                raise

    # ---------------- 内部 ----------------

    def _latest_parse_run(self, domain: str) -> str | None:
        base = self.ws / "02_work" / domain
        if not base.is_dir():
            return None
        runs = sorted((p.name for p in base.glob("run=*") if p.is_dir()), reverse=True)
        for run in runs:
            seg_dir = base / run / "segments"
            if seg_dir.is_dir() and any(seg_dir.rglob("*.md")):
                return run.removeprefix("run=")
        return None

    def _extract_candidates(self, seg_data: list[dict], domain: str) -> list[Candidate]:
        cands: list[Candidate] = []
        entity_cache: dict[tuple, str] = {}  # (document_id, type, name) -> entity_id
        for seg in seg_data:
            content = seg["content"]
            seg_id = seg["segment_id"]
            doc_id = seg["document_id"]
            # 实体：同一文档内消歧；跨文档同名保留为独立候选（审核阶段合并/检测重复）
            for etype, pat in ENTITY_PATTERNS:
                for m in pat.finditer(content):
                    name = m.group(1)
                    key = (doc_id, etype, name)
                    if key in entity_cache:
                        continue
                    eid = _stable_id("ENT", doc_id, etype, name)
                    entity_cache[key] = eid
                    cands.append(self._entity_candidate(eid, etype, name, domain, seg))
            # 关系
            for m in RELATION_PATTERN.finditer(content):
                src_name, tgt_name = m.group(1), m.group(2)
                src_id = entity_cache.get((doc_id, "PRODUCT", src_name))
                tgt_id = entity_cache.get((doc_id, "MATERIAL", tgt_name))
                if not src_id or not tgt_id:
                    continue
                rid = _stable_id("REL", seg_id, src_name, tgt_name)
                cands.append(self._relation_candidate(rid, src_id, tgt_id, seg))
            # 声明
            for m in STATEMENT_PATTERN.finditer(content):
                name, rate = m.group(1), m.group(2)
                subj = entity_cache.get((doc_id, "PRODUCT", name))
                if not subj:
                    continue
                sid = _stable_id("ST", seg_id, name, rate)
                cands.append(self._statement_candidate(sid, subj, float(rate), seg))
            for m in NEGATED_PATTERN.finditer(content):
                name = m.group(1)
                subj = entity_cache.get((doc_id, "PRODUCT", name))
                if not subj:
                    continue
                sid = _stable_id("ST", seg_id, name, "neg")
                cands.append(self._negated_statement_candidate(sid, subj, seg))
            # 规则
            for m in RULE_PATTERN.finditer(content):
                limit = m.group(1)
                rid = _stable_id("RULE", seg_id, limit)
                cands.append(self._rule_candidate(rid, int(limit), seg))
        return cands

    def _extraction_meta(self) -> dict:
        return {
            "extractor": self.extractor_id,
            "model_id": "deterministic",
            "model_version": self.extractor_version,
            "prompt_template_version": "none",
        }

    def _entity_candidate(self, eid, etype, name, domain, seg) -> Candidate:
        fm = {
            "schema": "entity/v1",
            "entity_id": eid,
            "entity_type": etype,
            "name": f"{'产品' if etype == 'PRODUCT' else '材料'}{name}",
            "aliases": [],
            "domain": domain,
            "source_ids": [seg["segment_id"]],
            "confidence": 0.9,
            "extraction": self._extraction_meta(),
            "validation_status": "CANDIDATE",
            "status": "ACTIVE",
            "version": "1.0",
        }
        body = (f"# {fm['name']}\n\n## 定义\n\n从片段 {seg['segment_id']} 抽取。\n\n"
                "## 业务说明\n\n无。\n\n## 来源证据\n\n"
                f"片段 {seg['segment_id']}（{seg['source_path']}）。\n\n"
                "## 审核说明\n\n待审核。\n")
        return Candidate("ENTITY", eid, fm, body)

    def _relation_candidate(self, rid, src_id, tgt_id, seg) -> Candidate:
        fm = {
            "schema": "relation/v1",
            "relation_id": rid,
            "source_id": src_id,
            "relation_type": "REQUIRES",
            "target_id": tgt_id,
            "direction": "DIRECTED",
            "source_ids": [seg["segment_id"]],
            "confidence": 0.9,
            "x_extraction": self._extraction_meta(),  # §8.5.9 扩展字段
            "validation_status": "CANDIDATE",
            "status": "ACTIVE",
            "version": "1.0",
        }
        body = (f"# {src_id} 需要 {tgt_id}\n\n## 语义\n\n产品需要材料。\n\n"
                f"## 来源证据\n\n片段 {seg['segment_id']}。\n\n## 审核说明\n\n待审核。\n")
        return Candidate("RELATION", rid, fm, body)

    def _statement_candidate(self, sid, subj, rate, seg, polarity="AFFIRMED") -> Candidate:
        fm = {
            "schema": "statement/v1",
            "statement_id": sid,
            "subject_id": subj,
            "predicate": "interest_rate",
            "object_id": None,
            "object_value": rate if polarity == "AFFIRMED" else None,
            "value_type": "DECIMAL" if polarity == "AFFIRMED" else "STRING",
            "source_type": "DOCUMENT",
            "source_asset_id": seg["document_id"],
            "source_record_id": None,
            "source_segment_id": seg["segment_id"],
            "confidence": 0.9,
            "x_extraction": self._extraction_meta(),
            "polarity": polarity,
            "validation_status": "CANDIDATE",
            "conflict_status": "NONE",
            "recorded_at": timeutil.ts_utc(),
            "status": "ACTIVE",
            "version": "1.0",
        }
        text = (f"# {subj} 利率为 {rate}%\n" if rate is not None
                else f"# {subj} 不可申请\n")
        body = (f"{text}\n## 规范表达\n\n{subj} interest_rate {rate or 'NEGATED'}。\n\n"
                f"## 来源证据\n\n片段 {seg['segment_id']}。\n\n"
                "## 冲突与限定\n\n无。\n\n## 审核说明\n\n待审核。\n")
        return Candidate("STATEMENT", sid, fm, body)

    def _negated_statement_candidate(self, sid, subj, seg) -> Candidate:
        """否定声明表达为布尔谓词（对象值非空，满足 §9.7 互斥约束）。"""
        fm = {
            "schema": "statement/v1",
            "statement_id": sid,
            "subject_id": subj,
            "predicate": "eligible",
            "object_id": None,
            "object_value": False,
            "value_type": "BOOLEAN",
            "source_type": "DOCUMENT",
            "source_asset_id": seg["document_id"],
            "source_record_id": None,
            "source_segment_id": seg["segment_id"],
            "confidence": 0.9,
            "x_extraction": self._extraction_meta(),
            "polarity": "NEGATED",
            "validation_status": "CANDIDATE",
            "conflict_status": "NONE",
            "recorded_at": timeutil.ts_utc(),
            "status": "ACTIVE",
            "version": "1.0",
        }
        body = (f"# {subj} 不可申请\n\n## 规范表达\n\n{subj} eligible = false（NEGATED）。\n\n"
                f"## 来源证据\n\n片段 {seg['segment_id']}。\n\n"
                "## 冲突与限定\n\n无。\n\n## 审核说明\n\n待审核。\n")
        return Candidate("STATEMENT", sid, fm, body)

    def _rule_candidate(self, rid, limit, seg) -> Candidate:
        fm = {
            "schema": "rule/v1",
            "rule_id": rid,
            "name": f"利率上限规则 {limit}%",
            "rule_type": "VALIDATION",
            "priority": 100,
            "execution_mode": "ADVISORY",
            "when": {"all": [{"lte": ["$facts.rate", limit]}]},
            "then": {"set": {"result": "OK"}},
            "else": {"emit": "利率超过上限"},
            "required_inputs": [{"name": "rate", "type": "DECIMAL"}],
            "source_document_id": seg["document_id"],
            "source_segment_id": seg["segment_id"],
            "test_case_ids": [f"TC-{rid}", f"TC-{rid}-NEG"],
            "x_extraction": self._extraction_meta(),
            "validation_status": "CANDIDATE",
            "status": "ACTIVE",
            "version": "1.0",
        }
        body = (f"# {fm['name']}\n\n## 业务解释\n\n利率不得超过 {limit}%。\n\n"
                "## 输入与输出\n\nrate。\n\n## 证据\n\n"
                f"片段 {seg['segment_id']}。\n\n## 人工责任边界\n\n建议性规则，需人工确认。\n\n"
                "## 测试说明\n\n正向与反向测试。\n")
        return Candidate("RULE", rid, fm, body)

    @staticmethod
    def _spec_for(kind: str):
        return {
            "ENTITY": specs.ENTITY_SPEC,
            "RELATION": specs.RELATION_SPEC,
            "STATEMENT": specs.STATEMENT_SPEC,
            "RULE": specs.RULE_SPEC,
        }[kind]

    @staticmethod
    def _candidate_rel(cand: Candidate, base: str) -> str:
        sub = {
            "ENTITY": "entities",
            "RELATION": "relations",
            "STATEMENT": "statements",
            "RULE": "rules",
        }[cand.kind]
        return f"{base}/{sub}/{cand.asset_id}.md"


def _extract_original(body: str) -> str:
    """从片段正文提取 '## 原文' 证据区。"""
    m = re.search(r"## 原文\n\n(.*?)(?:\n\n## 解析注记|\Z)", body, re.S)
    return m.group(1).rstrip() if m else body
