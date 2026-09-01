"""SP-15 第八步 EvidenceBundleAssembler（确定性、无 LLM）。

状态块（CANDIDATE 交付）：
STATUS=CANDIDATE / FROZEN=NO / IMPLEMENTED=NO

依据：
- skills/product-recommendation/contracts/recommendation-result.md
  （EvidenceBundle 必含：customerFactSnapshotId / productKnowledgeSnapshotRef /
   ruleExecutionRef / skillId+skillVersion / model+promptVersion(如使用) /
   permissionDecisionId + 每条理由 factRefs+knowledgeRefs + unknowns/conflicts +
   contentHash/traceId/生成时间；"模型置信度"不得替代证据充分度）
- gits-cbanking specs/product-recommendation/recommendation-result.schema.json
  （contentHash = sha256，用于重放与过期判断）
- gits-cbanking specs/product-recommendation/README.md（INV-04/INV-10）

职责：
把 eligibility / fit / portfolio / needProfile 各步的证据引用聚合为 EvidenceBundle；
校验必填证据 100% 覆盖——任一缺失 → 不产出（返回缺项清单）；计算确定性 contentHash。

证据引用口径（确定性推导，不调用 LLM）：
- factRefs     = 客户事实引用：eligibility ruleResults[].inputFactRefs + reason.factRefs；
- knowledgeRefs = 产品知识引用：eligibility ruleResults[].evidenceRefs（产品卡证据）
                  + reason.knowledgeRefs / reason.evidenceRefs。
每条推荐理由最终必须同时持有非空 factRefs 与 knowledgeRefs；fitScore / 模型置信度
一律不参与证据充分度判断（INV-04：CandidateReason → 至少一条 EvidenceRef 的强化版）。

不变量（本模块机器可测）：
- INV-EVB-01 必填快照/身份字段缺失 → 不产出（fail-closed，返回缺项清单）；
- INV-EVB-02 每条推荐理由缺 factRefs 或缺 knowledgeRefs → 不产出；
- INV-EVB-03 模型置信度/fitScore 不替代证据充分度（缺证据即使有置信度也拒绝）；
- INV-EVB-04 contentHash 只覆盖确定性证据内容，不含 contentHash/traceId/
  generatedAt/evidenceBundleId 自身（保证同一证据重放得到同一哈希）。

本模块不调用 LLM，不产生任何网络/文件副作用，纯确定性函数。
"""
from __future__ import annotations

import datetime as _dt
import json
from dataclasses import dataclass, field

from dkws.domain.hashing import sha256_hex

SCHEMA_VERSION = "1.0.0"
SKILL_ID = "SP-15"
CONTENT_HASH_PREFIX = "sha256"

# 必填快照/身份字段（缺一即不产出）
_REQUIRED_SNAPSHOT_FIELDS = (
    "customerFactSnapshotId",
    "productKnowledgeSnapshotRef",
    "ruleExecutionRef",
    "permissionDecisionId",
)
_REQUIRED_SKILL_FIELDS = ("skillId", "skillVersion")

# 缺项码（fail-closed 返回）
MISSING_SNAPSHOT_FIELD = "MISSING_SNAPSHOT_FIELD"
MISSING_SKILL_FIELD = "MISSING_SKILL_FIELD"
MISSING_PROMPT_VERSION = "MISSING_PROMPT_VERSION"
REASON_MISSING_FACT_REFS = "REASON_MISSING_FACT_REFS"
REASON_MISSING_KNOWLEDGE_REFS = "REASON_MISSING_KNOWLEDGE_REFS"


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------
def _dedupe(items) -> list[str]:
    """保序去重（空串/None 过滤）。"""
    seen: set[str] = set()
    out: list[str] = []
    for it in items or []:
        s = str(it).strip()
        if not s:
            continue
        if s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


def _canonical_json(obj) -> str:
    """确定性 JSON 序列化：键排序 + 稳定分隔符（供 contentHash 使用）。"""
    return json.dumps(obj, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), default=str)


# ---------------------------------------------------------------------------
# 结果对象
# ---------------------------------------------------------------------------
@dataclass
class ReasonEvidence:
    """单条推荐理由的证据覆盖（factRefs + knowledgeRefs 均非空）。"""

    reason_key: str
    factRefs: list[str] = field(default_factory=list)
    knowledgeRefs: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "reasonKey": self.reason_key,
            "factRefs": list(self.factRefs),
            "knowledgeRefs": list(self.knowledgeRefs),
        }


@dataclass
class EvidenceBundle:
    schemaVersion: str = SCHEMA_VERSION
    evidenceBundleId: str = ""
    customerFactSnapshotId: str = ""
    productKnowledgeSnapshotRef: str = ""
    ruleExecutionRef: str = ""
    skillId: str = SKILL_ID
    skillVersion: str = ""
    model: str | None = None
    promptVersion: str | None = None
    permissionDecisionId: str = ""
    factRefs: list[str] = field(default_factory=list)
    knowledgeRefs: list[str] = field(default_factory=list)
    reasonEvidence: list[ReasonEvidence] = field(default_factory=list)
    unknowns: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    contentHash: str = ""
    traceId: str = ""
    generatedAt: str = ""

    def to_dict(self) -> dict:
        d = {
            "schemaVersion": self.schemaVersion,
            "evidenceBundleId": self.evidenceBundleId,
            "customerFactSnapshotId": self.customerFactSnapshotId,
            "productKnowledgeSnapshotRef": self.productKnowledgeSnapshotRef,
            "ruleExecutionRef": self.ruleExecutionRef,
            "skillId": self.skillId,
            "skillVersion": self.skillVersion,
            "permissionDecisionId": self.permissionDecisionId,
            "factRefs": list(self.factRefs),
            "knowledgeRefs": list(self.knowledgeRefs),
            "reasonEvidence": [r.to_dict() for r in self.reasonEvidence],
            "unknowns": list(self.unknowns),
            "conflicts": list(self.conflicts),
            "contentHash": self.contentHash,
            "traceId": self.traceId,
            "generatedAt": self.generatedAt,
        }
        if self.model:
            d["model"] = self.model
        if self.promptVersion:
            d["promptVersion"] = self.promptVersion
        return d

    def evidence_payload(self) -> dict:
        """确定性证据内容（供 contentHash 计算；不含哈希/追踪/时间自身）。"""
        return {
            "customerFactSnapshotId": self.customerFactSnapshotId,
            "productKnowledgeSnapshotRef": self.productKnowledgeSnapshotRef,
            "ruleExecutionRef": self.ruleExecutionRef,
            "skillId": self.skillId,
            "skillVersion": self.skillVersion,
            "model": self.model,
            "promptVersion": self.promptVersion,
            "permissionDecisionId": self.permissionDecisionId,
            "factRefs": sorted(set(self.factRefs)),
            "knowledgeRefs": sorted(set(self.knowledgeRefs)),
            "reasonEvidence": [
                {
                    "reasonKey": r.reason_key,
                    "factRefs": sorted(set(r.factRefs)),
                    "knowledgeRefs": sorted(set(r.knowledgeRefs)),
                }
                for r in sorted(self.reasonEvidence, key=lambda x: x.reason_key)
            ],
            "unknowns": sorted(set(self.unknowns)),
            "conflicts": sorted(set(self.conflicts)),
        }


@dataclass
class EvidenceAssemblyResult:
    bundle: EvidenceBundle | None = None
    missing: list[dict] = field(default_factory=list)
    fail_closed: bool = False

    @property
    def ok(self) -> bool:
        return self.bundle is not None and not self.fail_closed

    def to_dict(self) -> dict:
        return {
            "bundle": self.bundle.to_dict() if self.bundle else None,
            "missing": list(self.missing),
            "failClosed": self.fail_closed,
        }


# ---------------------------------------------------------------------------
# 聚合辅助
# ---------------------------------------------------------------------------
def _build_product_evidence_index(eligibility_results) -> tuple[dict, dict]:
    """按 productId 聚合 eligibility 的 factRefs / knowledgeRefs（确定性）。"""
    fact_index: dict[str, list[str]] = {}
    knowledge_index: dict[str, list[str]] = {}
    for er in eligibility_results or []:
        pid = er.get("productId") or ""
        for rr in er.get("ruleResults") or []:
            fact_index.setdefault(pid, []).extend(rr.get("inputFactRefs") or [])
            knowledge_index.setdefault(pid, []).extend(rr.get("evidenceRefs") or [])
    for pid in fact_index:
        fact_index[pid] = _dedupe(fact_index[pid])
    for pid in knowledge_index:
        knowledge_index[pid] = _dedupe(knowledge_index[pid])
    return fact_index, knowledge_index


def _aggregate_unknowns(eligibility_results, fit_results) -> list[str]:
    out: list[str] = []
    for er in eligibility_results or []:
        for u in er.get("unknowns") or []:
            if isinstance(u, dict):
                if u.get("question"):
                    out.append(u["question"])
            else:
                out.append(u)
    for fr in fit_results or []:
        for g in fr.get("materialGaps") or []:
            out.append(g)
    return _dedupe(out)


def _aggregate_conflicts(eligibility_results, portfolio_candidates, need_profile) -> list[str]:
    out: list[str] = []
    for er in eligibility_results or []:
        for rr in er.get("reviewRequirements") or []:
            if isinstance(rr, dict) and rr.get("reason"):
                out.append(rr["reason"])
    for pc in portfolio_candidates or []:
        for c in pc.get("conflicts") or []:
            if isinstance(c, dict):
                out.append(
                    f"{c.get('productA', '?')}×{c.get('productB', '?')}:{c.get('kind', 'CONFLICT')}")
            else:
                out.append(c)
    for np_ in need_profile or []:
        if np_.get("needStatus") == "CONFLICT":
            out.append(f"NEED_CONFLICT:{np_.get('needId', '?')}")
    return _dedupe(out)


# ---------------------------------------------------------------------------
# EvidenceBundleAssembler
# ---------------------------------------------------------------------------
class EvidenceBundleAssembler:
    """聚合四步证据引用 → EvidenceBundle（确定性，fail-closed，无 LLM）。"""

    def assemble(self, *, context=None, eligibility_results=None, fit_results=None,
                 portfolio_candidates=None, need_profile=None,
                 evidence_bundle_id=None, trace_id=None,
                 generated_at=None) -> EvidenceAssemblyResult:
        context = context or {}
        eligibility_results = list(eligibility_results or [])
        fit_results = list(fit_results or [])
        portfolio_candidates = list(portfolio_candidates or [])
        need_profile = list(need_profile or [])

        result = EvidenceAssemblyResult()
        missing: list[dict] = []

        # 1) 必填快照/身份字段
        for fname in _REQUIRED_SNAPSHOT_FIELDS:
            if not (context.get(fname) or "").strip():
                missing.append({
                    "code": MISSING_SNAPSHOT_FIELD,
                    "field": fname,
                    "message": f"缺少必填快照/引用字段 {fname}",
                })
        for fname in _REQUIRED_SKILL_FIELDS:
            if not (context.get(fname) or "").strip():
                missing.append({
                    "code": MISSING_SKILL_FIELD,
                    "field": fname,
                    "message": f"缺少必填 Skill 字段 {fname}",
                })
        skill_id = (context.get("skillId") or SKILL_ID).strip()
        if skill_id and skill_id != SKILL_ID:
            missing.append({
                "code": MISSING_SKILL_FIELD,
                "field": "skillId",
                "message": f"skillId 必须为 {SKILL_ID}，实际为 {skill_id!r}",
            })

        # 2) model 使用则 promptVersion 必填（如未使用 model，则两者均非必填）
        model = (context.get("model") or "").strip() or None
        prompt_version = (context.get("promptVersion") or "").strip() or None
        if model and not prompt_version:
            missing.append({
                "code": MISSING_PROMPT_VERSION,
                "field": "promptVersion",
                "message": "使用 model 时必须同时提供 promptVersion",
            })

        # 3) 每条推荐理由必须同时持有 factRefs + knowledgeRefs
        fact_index, knowledge_index = _build_product_evidence_index(eligibility_results)
        reason_evidence: list[ReasonEvidence] = []
        for fr in fit_results:
            pid = fr.get("productId") or ""
            for idx, reason in enumerate(fr.get("recommendationReasons") or []):
                reason_key = f"{pid}#{idx}" if pid else f"#REASON-{idx}"

                fact_refs = _dedupe(reason.get("factRefs")) if isinstance(reason, dict) else []
                knowledge_refs = (reason.get("knowledgeRefs") or reason.get("evidenceRefs")
                                  ) if isinstance(reason, dict) else []
                knowledge_refs = _dedupe(knowledge_refs)

                # 缺失时用该产品的 eligibility 证据兜底（仍为空才算缺）
                if not fact_refs:
                    fact_refs = list(fact_index.get(pid, []))
                if not knowledge_refs:
                    knowledge_refs = list(knowledge_index.get(pid, []))

                if not fact_refs:
                    missing.append({
                        "code": REASON_MISSING_FACT_REFS,
                        "reasonKey": reason_key,
                        "message": f"推荐理由 {reason_key} 缺少 factRefs（模型置信度不得替代证据充分度）",
                    })
                if not knowledge_refs:
                    missing.append({
                        "code": REASON_MISSING_KNOWLEDGE_REFS,
                        "reasonKey": reason_key,
                        "message": f"推荐理由 {reason_key} 缺少 knowledgeRefs（模型置信度不得替代证据充分度）",
                    })
                reason_evidence.append(ReasonEvidence(
                    reason_key=reason_key,
                    factRefs=fact_refs,
                    knowledgeRefs=knowledge_refs,
                ))

        # 4) 任一缺失 → 不产出（fail-closed）
        if missing:
            result.missing = missing
            result.fail_closed = True
            return result

        # 5) 全局证据引用 + 未知/冲突聚合
        all_fact_refs: list[str] = []
        all_knowledge_refs: list[str] = []
        for re_ in reason_evidence:
            all_fact_refs.extend(re_.factRefs)
            all_knowledge_refs.extend(re_.knowledgeRefs)
        # 无推荐理由时也保留 eligibility 全量证据引用（保证聚合不丢证据）
        for pid in sorted(fact_index):
            all_fact_refs.extend(fact_index[pid])
        for pid in sorted(knowledge_index):
            all_knowledge_refs.extend(knowledge_index[pid])

        bundle = EvidenceBundle(
            evidenceBundleId=(evidence_bundle_id or "EVB-UNSET").strip(),
            customerFactSnapshotId=(context.get("customerFactSnapshotId") or "").strip(),
            productKnowledgeSnapshotRef=(context.get("productKnowledgeSnapshotRef") or "").strip(),
            ruleExecutionRef=(context.get("ruleExecutionRef") or "").strip(),
            skillId=skill_id,
            skillVersion=(context.get("skillVersion") or "").strip(),
            model=model,
            promptVersion=prompt_version,
            permissionDecisionId=(context.get("permissionDecisionId") or "").strip(),
            factRefs=_dedupe(all_fact_refs),
            knowledgeRefs=_dedupe(all_knowledge_refs),
            reasonEvidence=reason_evidence,
            unknowns=_aggregate_unknowns(eligibility_results, fit_results),
            conflicts=_aggregate_conflicts(eligibility_results, portfolio_candidates, need_profile),
            traceId=(trace_id or "TRACE-UNSET").strip(),
            generatedAt=self._normalize_generated_at(generated_at),
        )
        bundle.contentHash = CONTENT_HASH_PREFIX + ":" + sha256_hex(
            _canonical_json(bundle.evidence_payload()))

        result.bundle = bundle
        result.fail_closed = False
        return result

    @staticmethod
    def _normalize_generated_at(generated_at) -> str:
        if generated_at is None:
            return _dt.datetime.now(_dt.timezone.utc).isoformat()
        if isinstance(generated_at, _dt.datetime):
            return generated_at.isoformat()
        return str(generated_at).strip()
