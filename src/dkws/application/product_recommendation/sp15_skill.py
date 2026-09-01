"""SP-15 执行器组装（WP6-1）：确定性五段流水线，无 LLM。

状态块（CANDIDATE 交付）：
STATUS=CANDIDATE / FROZEN=NO / IMPLEMENTED=NO

依据：
- skills/product-recommendation/SP-15.md（§3 可观测步骤 0~8；§6 失败码；§7 不变量）
- skills/product-recommendation/contracts/recommendation-result.md（输出合同 + 五问）
- gits-cbanking specs/product-recommendation/recommendation-result.schema.json（8 必填字段）
- skills/product-recommendation/rules/rule-bundle-manifest.md（规则清单）
- docs/skill-execute-api-contract-vNext.md（SP-15 执行契约 + KERT_* 错误码）

职责（确定性，无 LLM / 无网络 / 无文件写副作用）：
1. RecommendationInputValidator（步骤 0）：校验 request.context（customerId /
   needVersionIds / recommendationObjective / asOf + 三快照引用 + permissionDecisionId）；
   缺失 → KERT_CONTEXT_INSUFFICIENT；权限缺失 → KERT_PERMISSION_DENIED。
2. 五段流水线（SP-15 §3 步骤 1~8 的确定性组装）：
   ProductUniverseResolver → HardEligibilityRuleExecutor → NeedProfileResolver →
   NeedCapabilityMatcher → CandidateRanker → PortfolioConstraintChecker →
   模板化 RecommendationExplanationAssembler（确定性，不依赖 LLM）→ EvidenceBundleAssembler。
3. 资源加载：优先从传入的 ProductKnowledgeSnapshot / RuleBundle 输入解析；
   提供从 skills/product-recommendation/rules/ 与 examples/product-recommendation-assets/
   读取的 loader 封装（best-effort；文件缺失/版本不符 → KERT_PRODUCT_KNOWLEDGE_STALE /
   KERT_RULE_VERSION_MISSING）。
4. 输出严格符合 recommendation-result 契约；assemblyTrace 记录步骤轨迹；contentHash 确定性。

本模块不调用 LLM；modelCalls 恒为空。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from dkws.application.product_recommendation.eligibility import (
    KERT_CONTEXT_INSUFFICIENT,
    KERT_EVIDENCE_INCOMPLETE,
    KERT_PERMISSION_DENIED,
    KERT_PRODUCT_KNOWLEDGE_STALE,
    KERT_RULE_VERSION_MISSING,
    HardEligibilityRuleExecutor,
    ProductUniverseResolver,
)
from dkws.application.product_recommendation.evidence import EvidenceBundleAssembler
from dkws.application.product_recommendation.matcher import NeedCapabilityMatcher
from dkws.application.product_recommendation.need_profile import NeedProfileResolver
from dkws.application.product_recommendation.portfolio import PortfolioConstraintChecker
from dkws.application.product_recommendation.ranker import CandidateRanker
from dkws.domain.hashing import sha256_hex

# ---------------------------------------------------------------------------
# Skill 身份常量（对齐 SP-15.md front matter / recommendation-result.schema.json）
# ---------------------------------------------------------------------------
SKILL_ID = "SP-15"
SKILL_VERSION = "2.0.0-candidate"
SCHEMA_VERSION = "1.0.0"
ACTIVATION_CONTRACT = "AC-PRODUCT-RECOMMEND-001"
CONTENT_HASH_PREFIX = "sha256"
RULE_BUNDLE_VERSION = "1.0.0-candidate"

# 输出合同必填 8 字段（对齐 recommendation-result.schema.json "required"）
RESULT_REQUIRED_FIELDS = (
    "schemaVersion",
    "runId",
    "productKnowledgeSnapshotRef",
    "ruleExecutionRef",
    "evidenceBundleId",
    "contentHash",
    "traceId",
    "generatedAt",
)

# 步骤 0 必填上下文字段（缺失 → KERT_CONTEXT_INSUFFICIENT）
_REQUIRED_CONTEXT_FIELDS = (
    "customerId",
    "needVersionIds",
    "recommendationObjective",
    "asOf",
    "customerFactSnapshotId",
    "productKnowledgeSnapshotRef",
    "ruleBundleRef",
)


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------
def _is_blank(value) -> bool:
    """判断上下文值是否缺失（None / 空串 / 空集合）。"""
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, tuple, dict, set)):
        return len(value) == 0
    return False


def _as_str_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value else []
    out: list[str] = []
    for v in value:
        if isinstance(v, str) and v:
            out.append(v)
    return out


def _dedupe(items) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for it in items or []:
        s = str(it).strip()
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out


def _canonical_json(obj) -> str:
    """确定性 JSON 序列化：键排序 + 稳定分隔符（供 contentHash）。"""
    return json.dumps(obj, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), default=str)


def _repo_root() -> Path:
    """定位仓库根目录（含 skills/ 与 examples/ 的最近祖先）。"""
    p = Path(__file__).resolve()
    for candidate in [p, *p.parents]:
        if (candidate / "skills").is_dir() and (candidate / "examples").is_dir():
            return candidate
    # 兜底：src/dkws/application/product_recommendation -> 上溯 4 级到仓库根
    if len(p.parents) >= 4:
        return p.parents[4]
    return p.parent


def _default_rules_dir() -> Path:
    return _repo_root() / "skills" / "product-recommendation" / "rules"


def _default_assets_dir() -> Path:
    return _repo_root() / "examples" / "product-recommendation-assets"


def _parse_frontmatter(text: str) -> dict:
    m = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    if not m:
        return {}
    try:
        return yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:  # pragma: no cover - 容错
        return {}


def _extract_evidence_refs(text: str) -> list[str]:
    return _dedupe(re.findall(r"EV-[A-Za-z0-9_-]+", text))


def _extract_context(request) -> dict:
    """从 SkillExecuteRequest（或裸 context）中规整出 request.context。"""
    if not isinstance(request, dict):
        return {}
    if isinstance(request.get("context"), dict):
        return request["context"]
    if isinstance(request.get("request"), dict) and isinstance(
            request["request"].get("context"), dict):
        return request["request"]["context"]
    return request


def _extract_request_id(request, context) -> str:
    if isinstance(request, dict):
        for key in ("requestId", "runId"):
            v = request.get(key)
            if v:
                return str(v)
    for key in ("runId", "requestId"):
        v = context.get(key)
        if v:
            return str(v)
    return ""


def _unwrap_facts(raw) -> dict:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        if isinstance(raw.get("facts"), dict):
            return raw["facts"]
        return raw
    return {}


def _result_content_hash(result: dict) -> str:
    """contentHash 覆盖确定性内容，不含 contentHash/generatedAt 自身（重放一致性）。"""
    payload = {k: v for k, v in result.items()
               if k not in ("contentHash", "generatedAt")}
    return CONTENT_HASH_PREFIX + ":" + sha256_hex(_canonical_json(payload))


# ---------------------------------------------------------------------------
# 步骤 0：RecommendationInputValidator
# ---------------------------------------------------------------------------
@dataclass
class ValidationResult:
    valid: bool = True
    errors: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"valid": self.valid, "errors": list(self.errors)}


class RecommendationInputValidator:
    """校验 SP-15 request.context（步骤 0，确定性）。

    缺失必填上下文字段（含三快照引用）→ KERT_CONTEXT_INSUFFICIENT；
    permissionDecisionId 缺失 → KERT_PERMISSION_DENIED。
    """

    def validate(self, context) -> ValidationResult:
        context = context if isinstance(context, dict) else {}
        errors: list[dict] = []
        for fname in _REQUIRED_CONTEXT_FIELDS:
            if _is_blank(context.get(fname)):
                errors.append({
                    "code": KERT_CONTEXT_INSUFFICIENT,
                    "field": fname,
                    "message": f"缺少必填上下文字段 {fname}",
                })
        if _is_blank(context.get("permissionDecisionId")):
            errors.append({
                "code": KERT_PERMISSION_DENIED,
                "field": "permissionDecisionId",
                "message": "缺少权限决策引用 permissionDecisionId",
            })
        return ValidationResult(valid=not errors, errors=errors)


# ---------------------------------------------------------------------------
# 资源加载：RuleBundle / ProductKnowledgeSnapshot（best-effort）
# ---------------------------------------------------------------------------
class RuleBundleLoader:
    """从传入 RuleBundle 输入或 rules/ 目录加载 {ruleId: ruleVersion}。

    文件缺失 / ruleVersion 缺失或版本不符 → KERT_RULE_VERSION_MISSING。
    """

    def __init__(self, expected_version: str = RULE_BUNDLE_VERSION):
        self.expected_version = expected_version

    def parse(self, raw) -> tuple[dict[str, str], list[dict]]:
        """解析传入的 RuleBundle 输入（dict/list 多种形态）→ {ruleId: ruleVersion}。"""
        bundle: dict[str, str] = {}
        errors: list[dict] = []
        items: list[tuple[str, Any]] = []
        if isinstance(raw, dict):
            rules = raw.get("rules", raw)
            if isinstance(rules, dict):
                items = list(rules.items())
            elif isinstance(rules, list):
                items = [(r.get("ruleId"), r) for r in rules if isinstance(r, dict)]
        elif isinstance(raw, list):
            items = [(r.get("ruleId"), r) for r in raw if isinstance(r, dict)]
        for rid, val in items:
            if not rid:
                continue
            if isinstance(val, dict):
                rv = val.get("ruleVersion")
            else:
                rv = val
            if _is_blank(rv):
                errors.append({
                    "code": KERT_RULE_VERSION_MISSING,
                    "ruleId": rid,
                    "message": f"规则 {rid} 版本缺失",
                })
                continue
            bundle[rid] = str(rv).strip()
        return bundle, errors

    def load_dir(self, rules_dir: Path | None = None) -> tuple[dict[str, str], list[dict]]:
        """从 rules/ 目录读取规则文件 frontmatter → {ruleId: ruleVersion}。"""
        rules_dir = Path(rules_dir) if rules_dir else _default_rules_dir()
        if not rules_dir.is_dir():
            return {}, [{
                "code": KERT_RULE_VERSION_MISSING,
                "message": f"规则目录缺失：{rules_dir}",
            }]
        files = sorted(rules_dir.glob("PR-*.md"))
        if not files:
            return {}, [{
                "code": KERT_RULE_VERSION_MISSING,
                "message": f"规则目录无规则文件：{rules_dir}",
            }]
        bundle: dict[str, str] = {}
        errors: list[dict] = []
        for path in files:
            fm = _parse_frontmatter(path.read_text(encoding="utf-8"))
            rid = fm.get("ruleId")
            rv = fm.get("ruleVersion")
            if not rid or not rv:
                errors.append({
                    "code": KERT_RULE_VERSION_MISSING,
                    "ruleId": rid or path.name,
                    "message": f"规则文件 {path.name} 缺少 ruleId/ruleVersion",
                })
                continue
            if rv != self.expected_version:
                errors.append({
                    "code": KERT_RULE_VERSION_MISSING,
                    "ruleId": rid,
                    "message": f"规则 {rid} 版本 {rv} 与期望 {self.expected_version} 不符",
                })
                continue
            bundle[rid] = str(rv).strip()
        return bundle, errors

    def load(self, *, bundle=None, rules_dir: Path | None = None) -> tuple[dict[str, str], list[dict]]:
        """优先传入 RuleBundle 输入；否则 best-effort 从 rules/ 目录加载。"""
        if bundle is not None:
            return self.parse(bundle)
        return self.load_dir(rules_dir)


class ProductKnowledgeLoader:
    """从传入 ProductKnowledgeSnapshot 输入或 examples/.../product-cards/ 加载产品卡。

    文件缺失 / 版本不符 → KERT_PRODUCT_KNOWLEDGE_STALE。
    """

    def parse(self, raw) -> tuple[list[dict], list[dict]]:
        """解析传入的 ProductKnowledgeSnapshot 输入 → 产品卡 dict 列表。"""
        if isinstance(raw, list):
            products = [p for p in raw if isinstance(p, dict)]
        elif isinstance(raw, dict):
            products = raw.get("products") or raw.get("productCards") or []
            products = [p for p in products if isinstance(p, dict)]
        else:
            products = []
        return products, []

    def load_dir(self, assets_dir: Path | None = None) -> tuple[list[dict], list[dict]]:
        """从 examples/product-recommendation-assets/ 下的 product-cards/ 目录加载。"""
        assets_dir = Path(assets_dir) if assets_dir else _default_assets_dir()
        if not assets_dir.is_dir():
            return [], [{
                "code": KERT_PRODUCT_KNOWLEDGE_STALE,
                "message": f"产品资产目录缺失：{assets_dir}",
            }]
        cards = sorted(p for p in assets_dir.rglob("*.md")
                       if p.parent.name == "product-cards")
        if not cards:
            return [], [{
                "code": KERT_PRODUCT_KNOWLEDGE_STALE,
                "message": f"产品资产目录无 product-cards：{assets_dir}",
            }]
        products: list[dict] = []
        for path in cards:
            products.append(parse_product_card_markdown(path))
        return products, []

    def load(self, *, snapshot=None, assets_dir: Path | None = None) -> tuple[list[dict], list[dict]]:
        """优先传入 ProductKnowledgeSnapshot 输入；否则 best-effort 从资产目录加载。"""
        if snapshot is not None:
            return self.parse(snapshot)
        return self.load_dir(assets_dir)


def parse_product_card_markdown(path: Path) -> dict:
    """把 Markdown 产品卡（front matter + 正文）投影为结构化产品 dict（确定性）。"""
    text = path.read_text(encoding="utf-8")
    fm = _parse_frontmatter(text)
    try:
        rel = path.resolve().relative_to(_repo_root())
    except ValueError:
        rel = path
    return {
        "productId": fm.get("product_id") or fm.get("productId") or path.stem,
        "productVersion": fm.get("version") or fm.get("product_version") or "",
        "name": fm.get("name") or "",
        "productFamily": fm.get("product_family") or fm.get("productFamily") or "",
        "status": fm.get("status") or "UNKNOWN",
        "effectiveFrom": fm.get("effective_from") or fm.get("effectiveFrom"),
        "effectiveTo": fm.get("effective_to") or fm.get("effectiveTo"),
        "owner": fm.get("owner") or "",
        "reviewer": fm.get("reviewer"),
        "publishedAt": fm.get("published_at") or fm.get("publishedAt"),
        "contentHash": fm.get("content_hash") or fm.get("contentHash"),
        "source": f"src://{rel}",
        "evidenceRefs": _extract_evidence_refs(text),
    }


# ---------------------------------------------------------------------------
# 步骤 7：模板化 RecommendationExplanationAssembler（确定性，无 LLM）
# ---------------------------------------------------------------------------
@dataclass
class ExplanationResult:
    explanations: list[dict] = field(default_factory=list)
    trace: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"explanations": list(self.explanations), "trace": list(self.trace)}


class RecommendationExplanationAssembler:
    """按 recommendation-result.md「五问」为每个已合格候选生成确定性解释（无 LLM）。"""

    def assemble(self, fit_results, eligibility_by_product: dict, needs, *,
                 portfolio_id: str = "") -> ExplanationResult:
        result = ExplanationResult()
        for fr in fit_results:
            pid = fr.productId
            er = eligibility_by_product.get(pid)
            served_needs = [m.needId for m in fr.matchedNeeds]
            dims = {d.dimension: d.result for d in fr.dimensionMatches}
            uncertainty = []
            if fr.materialGaps:
                uncertainty.append(f"材料缺口：{fr.materialGaps}")
            if fr.expertCollaborationRequired:
                uncertainty.append("需专家复核")
            if er is not None and er.reviewRequirements:
                uncertainty.append(f"需复核：{[r['reason'] for r in er.reviewRequirements]}")

            explanation = {
                "portfolioId": portfolio_id,
                "productId": pid,
                "productVersion": fr.productVersion,
                "whyConsidered": (
                    f"产品 {pid} 覆盖客户需求 {served_needs or '（无匹配需求）'}，"
                    f"匹配能力 {fr.matchedCapabilities or '（无）'}"),
                "whyAllowed": (
                    "通过硬约束规则 "
                    + (", ".join(rr.ruleId for rr in er.ruleResults if rr.result == "PASS")
                       if er is not None else "（无规则证据）")),
                "whyRankedHere": (
                    f"排名 {fr.rank}，FitScore={fr.fitScore}，分维度："
                    + "; ".join(f"{d}={r}" for d, r in sorted(dims.items()))),
                "whatUncertain": "；".join(uncertainty) or "无未决不确定项",
                "whereEvidence": (
                    f"产品版本 {fr.productVersion}，证据 {fr.evidenceRefs or '（无）'}"),
            }
            result.explanations.append(explanation)
            result.trace.append({"step": "EXPLAIN", "productId": pid, **explanation})
        return result


# ---------------------------------------------------------------------------
# 执行结果对象
# ---------------------------------------------------------------------------
@dataclass
class Sp15ExecutionResult:
    ok: bool = False
    status: str = "ok"
    request_id: str = ""
    run_id: str = ""
    data: dict | None = None
    errors: list[dict] = field(default_factory=list)
    assembly_trace: list[dict] = field(default_factory=list)
    model_calls: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "requestId": self.request_id,
            "status": self.status,
            "data": ({"skillId": SKILL_ID,
                      "reportUrl": f"/api/skill/report/{self.request_id or self.run_id}",
                      "result": self.data} if self.ok and self.data else {}),
            "errors": list(self.errors),
            "assemblyTrace": list(self.assembly_trace),
            "modelCalls": list(self.model_calls),
        }


def _to_response_errors(entries: list[dict]) -> list[dict]:
    """把内部 fail-closed 条目规整为响应 errors 形状（{code, message, detail?}）。"""
    out: list[dict] = []
    for e in entries or []:
        if not isinstance(e, dict):
            continue
        code = e.get("code") or e.get("errorCode") or "KERT_INTERNAL_ERROR"
        item: dict = {"code": code}
        if e.get("message"):
            item["message"] = e["message"]
        detail = {k: v for k, v in e.items() if k not in ("code", "errorCode", "message")}
        if detail:
            item["detail"] = detail
        out.append(item)
    return out


def _error_result(request_id: str, run_id: str, errors: list[dict],
                  trace: list[dict]) -> Sp15ExecutionResult:
    return Sp15ExecutionResult(
        ok=False, status="skill_error", request_id=request_id, run_id=run_id,
        data=None, errors=_to_response_errors(errors), assembly_trace=trace, model_calls=[],
    )


# ---------------------------------------------------------------------------
# 需求 → 匹配输入装配（NeedProfile 状态为权威，能力来自原始需求来源）
# ---------------------------------------------------------------------------
def _collect_capability_needs(facts, claims, interactions) -> dict[str, dict]:
    """复用 NeedProfileResolver 的 needId 归一化，收集 requiredCapabilities/needType/scenario。"""
    out: dict[str, dict] = {}
    for idx, need in enumerate(facts.get("needs") or []):
        if not isinstance(need, dict):
            continue
        cand = NeedProfileResolver._normalize_need_entry(need, idx)
        if cand is None:
            continue
        out.setdefault(cand["needId"], {
            "requiredCapabilities": _as_str_list(need.get("requiredCapabilities")),
            "needType": cand["needType"],
            "scenario": _as_str_list(need.get("scenario")),
        })
    for claim in claims or []:
        if not isinstance(claim, dict):
            continue
        cand = NeedProfileResolver._normalize_claim(claim)
        if cand is None:
            continue
        out.setdefault(cand["needId"], {
            "requiredCapabilities": _as_str_list(claim.get("requiredCapabilities")),
            "needType": cand["needType"],
            "scenario": _as_str_list(claim.get("scenario")),
        })
    for interaction in interactions or []:
        if not isinstance(interaction, dict):
            continue
        for ext in interaction.get("extractions") or []:
            if not isinstance(ext, dict):
                continue
            cand = NeedProfileResolver._normalize_extraction(ext, interaction)
            if cand is None:
                continue
            out.setdefault(cand["needId"], {
                "requiredCapabilities": _as_str_list(ext.get("requiredCapabilities")),
                "needType": cand["needType"],
                "scenario": _as_str_list(ext.get("scenario")),
            })
    return out


def _matcher_needs(profile_items, cap_index) -> list[dict]:
    needs: list[dict] = []
    for item in profile_items:
        cap = cap_index.get(item.needId, {})
        needs.append({
            "needId": item.needId,
            "needType": item.needType or cap.get("needType") or "UNSPECIFIED",
            "needStatus": item.needStatus,
            "evidenceRefs": list(item.evidenceRefs),
            "requiredCapabilities": list(cap.get("requiredCapabilities", [])),
            "scenario": list(cap.get("scenario", [])),
        })
    return needs


def _need_profile_dict(item) -> dict:
    d = item.to_dict()
    if d.get("priority") is None:
        d.pop("priority", None)
    return d


# ---------------------------------------------------------------------------
# SP-15 执行器（五段流水线编排）
# ---------------------------------------------------------------------------
class Sp15SkillExecutor:
    """SP-15 三段式 Skill 执行器：确定性五段流水线，无 LLM。

    编排 SP-15 §3 步骤 0~8；任一 fail-closed（输入不足 / 知识陈旧 / 规则缺失 /
    证据不完整）→ 不产出 data.result，返回对应 KERT_* 错误码。
    """

    def __init__(self, *, rules_dir: Path | None = None,
                 assets_dir: Path | None = None,
                 weights: dict | None = None):
        self.rules_dir = Path(rules_dir) if rules_dir else _default_rules_dir()
        self.assets_dir = Path(assets_dir) if assets_dir else _default_assets_dir()
        self.weights = weights

    def execute(self, request) -> Sp15ExecutionResult:
        trace: list[dict] = []
        context = _extract_context(request)
        request_id = _extract_request_id(request, context)
        run_id = context.get("runId") or request_id or "REC-UNSET"

        # ---- 步骤 0：输入校验 ----
        validation = RecommendationInputValidator().validate(context)
        trace.append({
            "phase": "VALIDATE", "step": 0,
            "status": "ok" if validation.valid else "error",
            "message": "输入校验通过" if validation.valid else "输入校验失败",
            "errors": validation.errors,
        })
        if not validation.valid:
            return _error_result(request_id, run_id, validation.errors, trace)

        # ---- 步骤 1：资源加载（产品全集 + 规则包）----
        bundle = self._resolve_resources(context, trace)
        if bundle is None:
            return _error_result(request_id, run_id, trace[-1]["errors"], trace)

        products = bundle["products"]
        rule_bundle = bundle["rule_bundle"]
        product_cards = bundle["product_cards"]
        facts = bundle["facts"]
        claims = bundle["claims"]
        interactions = bundle["interactions"]
        need_version_ids = bundle["need_version_ids"]
        institution = bundle["institution"]
        as_of = bundle["as_of"]

        # ---- 步骤 1b：产品全集解析 ----
        universe = ProductUniverseResolver().resolve(
            products, as_of=as_of, institution=institution)
        trace.append({
            "phase": "RESOLVE_UNIVERSE", "step": 1,
            "status": "fail_closed" if universe.fail_closed else "ok",
            "message": f"有效产品全集 {len(universe.universe)} 个，排除 {len(universe.excluded)} 个",
            "failClosedReasons": universe.fail_closed_reasons,
        })
        if universe.fail_closed:
            return _error_result(request_id, run_id, universe.fail_closed_reasons, trace)

        # ---- 步骤 2：硬约束过滤 ----
        eligibility = HardEligibilityRuleExecutor().execute(
            universe.universe, facts, as_of=as_of, rule_bundle=rule_bundle)
        trace.append({
            "phase": "ELIGIBILITY", "step": 2,
            "status": "fail_closed" if eligibility.fail_closed else "ok",
            "message": f"硬约束过滤 {len(eligibility.results)} 个产品",
            "failClosedReasons": eligibility.fail_closed_reasons,
        })
        if eligibility.fail_closed:
            return _error_result(request_id, run_id, eligibility.fail_closed_reasons, trace)

        # ---- 步骤 3：需求画像 ----
        need_profile = NeedProfileResolver().resolve(
            facts, claims, interactions, need_version_ids=need_version_ids)
        trace.append({
            "phase": "NEED_PROFILE", "step": 3,
            "status": "ok",
            "message": f"需求画像 {len(need_profile.profile)} 条，冲突 {len(need_profile.conflicts)} 条",
        })
        cap_index = _collect_capability_needs(facts, claims, interactions)
        matcher_needs = _matcher_needs(need_profile.profile, cap_index)

        # ---- 步骤 4：需求—能力匹配 ----
        fit_results = NeedCapabilityMatcher().match(
            universe.universe, matcher_needs, facts, eligibility=eligibility.results)
        trace.append({
            "phase": "MATCH", "step": 4,
            "status": "ok",
            "message": f"匹配 {len(fit_results)} 个产品",
        })

        # ---- 步骤 5：候选排序 ----
        ranked = CandidateRanker(self.weights).rank(fit_results)
        eligible_ranked = [fr for fr in ranked if fr.fitScore is not None]
        trace.append({
            "phase": "RANK", "step": 5,
            "status": "ok",
            "message": f"已合格候选 {len(eligible_ranked)} 个完成内部排序",
        })

        # ---- 步骤 6：组合校验 ----
        portfolio = self._build_portfolio(ranked, matcher_needs, run_id)
        portfolio_candidates: list[dict] = []
        if portfolio is not None:
            held = _as_str_list(facts.get("heldProducts"))
            check = PortfolioConstraintChecker().check(
                portfolio, eligibility=eligibility.results, fit_results=[fr.to_dict() for fr in ranked],
                product_cards=product_cards, held_products=held)
            if check.candidate is not None and check.candidate.primaryProduct is not None:
                portfolio_candidates.append(check.candidate.to_dict())
            trace.append({
                "phase": "PORTFOLIO", "step": 6,
                "status": "ok" if check.valid else "violations",
                "message": (f"组合 {check.candidate.portfolioId if check.candidate else ''} "
                            f"category={check.candidate.recommendationCategory if check.candidate else 'N/A'}"),
                "violations": check.violations,
            })
        else:
            trace.append({
                "phase": "PORTFOLIO", "step": 6,
                "status": "empty",
                "message": "无已合格候选，跳过组合",
            })

        # ---- 步骤 7：模板化解释（确定性，无 LLM）----
        elig_map = {er.productId: er for er in eligibility.results}
        explanation = RecommendationExplanationAssembler().assemble(
            eligible_ranked, elig_map, matcher_needs,
            portfolio_id=(portfolio or {}).get("portfolioId", ""))
        trace.append({
            "phase": "EXPLAIN", "step": 7,
            "status": "ok",
            "message": f"生成 {len(explanation.explanations)} 条候选解释",
        })

        # ---- 步骤 8：证据装配 + 内容哈希 ----
        eligibility_dicts = [er.to_dict() for er in eligibility.results]
        fit_dicts = [fr.to_dict() for fr in ranked]
        need_profile_dicts = [_need_profile_dict(it) for it in need_profile.profile]

        evidence_context = {
            "customerFactSnapshotId": context.get("customerFactSnapshotId"),
            "productKnowledgeSnapshotRef": context.get("productKnowledgeSnapshotRef"),
            "ruleExecutionRef": context.get("ruleExecutionRef") or f"RULE-RUN-{run_id}",
            "skillId": SKILL_ID,
            "skillVersion": context.get("skillVersion") or SKILL_VERSION,
            "permissionDecisionId": context.get("permissionDecisionId"),
        }
        evidence = EvidenceBundleAssembler().assemble(
            context=evidence_context,
            eligibility_results=eligibility_dicts,
            fit_results=fit_dicts,
            portfolio_candidates=portfolio_candidates,
            need_profile=need_profile_dicts,
            evidence_bundle_id=context.get("evidenceBundleId") or f"EVB-{run_id}",
            trace_id=context.get("traceId") or f"TRACE-{run_id}",
            generated_at=context.get("generatedAt"),
        )
        if not evidence.ok:
            errs = [{"code": KERT_EVIDENCE_INCOMPLETE,
                     "message": "证据装配不完整（fail-closed）",
                     "detail": m} for m in evidence.missing]
            trace.append({
                "phase": "EVIDENCE", "step": 8,
                "status": "fail_closed",
                "message": "证据装配失败",
                "errors": errs,
            })
            return _error_result(request_id, run_id, errs, trace)

        bundle_ev = evidence.bundle
        result = {
            "schemaVersion": SCHEMA_VERSION,
            "runId": run_id,
            "skillId": SKILL_ID,
            "skillVersion": evidence_context["skillVersion"],
            "productKnowledgeSnapshotRef": context.get("productKnowledgeSnapshotRef"),
            "ruleExecutionRef": evidence_context["ruleExecutionRef"],
            "evidenceBundleId": bundle_ev.evidenceBundleId,
            "contentHash": "",
            "traceId": bundle_ev.traceId,
            "eligibilityResults": eligibility_dicts,
            "fitResults": fit_dicts,
            "portfolioCandidates": portfolio_candidates,
            "needProfile": need_profile_dicts,
            "unknowns": list(bundle_ev.unknowns),
            "conflicts": list(bundle_ev.conflicts),
            "generatedAt": bundle_ev.generatedAt,
        }
        result["contentHash"] = _result_content_hash(result)
        trace.append({
            "phase": "EVIDENCE", "step": 8,
            "status": "ok",
            "message": f"证据包 {bundle_ev.evidenceBundleId}，contentHash={result['contentHash']}",
        })

        return Sp15ExecutionResult(
            ok=True, status="ok", request_id=request_id, run_id=run_id,
            data=result, errors=[], assembly_trace=trace, model_calls=[],
        )

    # ---- 资源解析 ----

    def _resolve_resources(self, context: dict, trace: list[dict]) -> dict | None:
        errors: list[dict] = []

        # 产品知识快照
        if context.get("productKnowledgeSnapshot") is not None:
            products, perrs = ProductKnowledgeLoader().parse(
                context["productKnowledgeSnapshot"])
        else:
            products, perrs = ProductKnowledgeLoader().load_dir(self.assets_dir)
        errors.extend(perrs)
        if not products:
            errors.append({
                "code": KERT_PRODUCT_KNOWLEDGE_STALE,
                "message": "产品知识快照缺失/为空（无可解析产品卡）",
            })

        # 规则包
        if context.get("ruleBundle") is not None:
            rule_bundle, rerrs = RuleBundleLoader().parse(context["ruleBundle"])
        else:
            rule_bundle, rerrs = RuleBundleLoader().load_dir(self.rules_dir)
        errors.extend(rerrs)

        if errors:
            trace.append({
                "phase": "RESOLVE_RESOURCES", "step": 1,
                "status": "error", "message": "资源加载失败（fail-closed）",
                "errors": errors,
            })
            return None

        facts = _unwrap_facts(context.get("customerFactSnapshot") or context.get("facts"))
        claims = list(context.get("claims") or [])
        interactions = list(context.get("interactions") or [])
        need_version_ids = _as_str_list(context.get("needVersionIds"))
        institution = context.get("institution") or facts.get("institution")
        as_of = context.get("asOf")
        product_cards = {
            p.get("productId"): p for p in products
            if isinstance(p, dict) and p.get("productId")
        }
        return {
            "products": products,
            "rule_bundle": rule_bundle,
            "product_cards": product_cards,
            "facts": facts,
            "claims": claims,
            "interactions": interactions,
            "need_version_ids": need_version_ids,
            "institution": institution,
            "as_of": as_of,
        }

    # ---- 组合装配（从已排序候选构建 PRIMARY/SUPPORTING 组合输入）----

    @staticmethod
    def _build_portfolio(ranked, needs, run_id: str) -> dict | None:
        eligible = [fr for fr in ranked if fr.fitScore is not None]
        if not eligible:
            return None
        primary = eligible[0]
        supporting = eligible[1:]

        def _member(fr, role, served_need_id=None):
            m = {
                "productId": fr.productId,
                "productVersion": fr.productVersion,
                "role": role,
            }
            if served_need_id:
                m["servedNeedId"] = served_need_id
            if fr.evidenceRefs:
                m["evidenceRefs"] = list(fr.evidenceRefs)
            return m

        def _served_need(fr):
            for mn in fr.matchedNeeds:
                return mn.needId
            for n in needs:
                return n.get("needId")
            return None

        primary_member = _member(primary, "PRIMARY", _served_need(primary))
        supporting_members = [
            _member(fr, "SUPPORTING", _served_need(fr)) for fr in supporting
        ]
        return {
            "portfolioId": f"PORT-{run_id}",
            "primaryProduct": primary_member,
            "supportingProducts": supporting_members,
        }
