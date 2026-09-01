"""SP-15 第三段（组合）PortfolioConstraintChecker（确定性、无 LLM）。

状态块（CANDIDATE 交付）：
STATUS=CANDIDATE / FROZEN=NO / IMPLEMENTED=NO

依据：
- gits-cbanking specs/product-recommendation/portfolio-candidate.schema.json
  （组合输出闭集：role PRIMARY/SUPPORTING；Dependency PREREQUISITE/SEQUENCE/COMPLEMENTARY；
   Conflict MUTUAL_EXCLUSION/DUPLICATE/SALES_BOUNDARY；recommendationCategory 三态）
- skills/product-recommendation/SP-15.md（§3 步骤 6 PortfolioConstraintChecker：组合互斥/依赖/顺序）
- skills/product-recommendation/rules/PR-PRMUTEX-001.md（前置与互斥规则 + 「组合中的任一硬失败
   产品必须移除，不能以整体分数掩盖」不变量）
- skills/product-recommendation/rules/README.md（硬约束执行顺序）
- skills/product-recommendation/contracts/recommendation-result.md（portfolioCandidates 口径）

职责（确定性，纯函数，无 LLM / 无网络 / 无文件副作用）：
1. 硬失败移除：组合内任一 Eligibility=INELIGIBLE 的产品必须移除，不得以整体分数 / 匹配分掩盖
   （INV-02 门禁在本模块表现为：只消费 eligibility 做准入，绝不消费 fitScore 判准入；若上游
   传入 fitScore，仅记录用于证明「高分也未能掩盖 INELIGIBLE」）。
2. 结构校验：每方案最多一个 PRIMARY；SUPPORTING 必须说明 servedNeedId（服务的次级需求）。
3. 依赖校验：PREREQUISITE（前置已持有/在组合内）/ SEQUENCE（办理顺序）/ COMPLEMENTARY（协同）。
4. 冲突校验：MUTUAL_EXCLUSION（组合被拒绝）/ DUPLICATE（去重）/ SALES_BOUNDARY（专家复核）。
5. recommendationCategory 三态：IMMEDIATE_COMMUNICATE / SUPPLEMENT_FACTS_THEN_EVALUATE /
   EXPERT_REVIEW_REQUIRED（优先级：专家复核 > 补充事实 > 可直接沟通）。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from dkws.application.product_recommendation.eligibility import EligibilityResult

# ---------------------------------------------------------------------------
# 闭集枚举（对齐 portfolio-candidate.schema.json / SP-15 §3 步骤 6）
# ---------------------------------------------------------------------------
ROLE_CLOSED_SET = ("PRIMARY", "SUPPORTING")
DEPENDENCY_TYPE_CLOSED_SET = ("PREREQUISITE", "SEQUENCE", "COMPLEMENTARY")
CONFLICT_KIND_CLOSED_SET = ("MUTUAL_EXCLUSION", "DUPLICATE", "SALES_BOUNDARY")
RECOMMENDATION_CATEGORY_CLOSED_SET = (
    "IMMEDIATE_COMMUNICATE",
    "SUPPLEMENT_FACTS_THEN_EVALUATE",
    "EXPERT_REVIEW_REQUIRED",
)

# 三态优先级：专家复核 > 补充事实 > 可直接沟通（数值越大优先级越高）
_CATEGORY_RANK = {
    "IMMEDIATE_COMMUNICATE": 0,
    "SUPPLEMENT_FACTS_THEN_EVALUATE": 1,
    "EXPERT_REVIEW_REQUIRED": 2,
}


# ---------------------------------------------------------------------------
# 结果对象（对齐 portfolio-candidate.schema.json 字段）
# ---------------------------------------------------------------------------
@dataclass
class PortfolioMember:
    productId: str
    productVersion: str
    role: str
    servedNeedId: str | None = None
    evidenceRefs: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = {
            "productId": self.productId,
            "productVersion": self.productVersion,
            "role": self.role,
        }
        if self.servedNeedId:
            d["servedNeedId"] = self.servedNeedId
        if self.evidenceRefs:
            d["evidenceRefs"] = list(self.evidenceRefs)
        return d


@dataclass
class Dependency:
    source: str
    target: str
    type: str
    note: str | None = None

    def to_dict(self) -> dict:
        d = {"from": self.source, "to": self.target, "type": self.type}
        if self.note:
            d["note"] = self.note
        return d


@dataclass
class Conflict:
    productA: str
    productB: str
    kind: str
    reasonCode: str | None = None
    evidenceRefs: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = {"productA": self.productA, "productB": self.productB, "kind": self.kind}
        if self.reasonCode:
            d["reasonCode"] = self.reasonCode
        if self.evidenceRefs:
            d["evidenceRefs"] = list(self.evidenceRefs)
        return d


@dataclass
class PortfolioCandidate:
    schemaVersion: str = "1.0.0"
    portfolioId: str = ""
    primaryProduct: PortfolioMember | None = None
    supportingProducts: list[PortfolioMember] = field(default_factory=list)
    dependencies: list[Dependency] = field(default_factory=list)
    conflicts: list[Conflict] = field(default_factory=list)
    recommendationCategory: str = "SUPPLEMENT_FACTS_THEN_EVALUATE"
    rationale: str = ""
    evidenceRefs: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = {
            "schemaVersion": self.schemaVersion,
            "portfolioId": self.portfolioId,
            "primaryProduct": self.primaryProduct.to_dict() if self.primaryProduct else None,
            "supportingProducts": [m.to_dict() for m in self.supportingProducts],
            "dependencies": [x.to_dict() for x in self.dependencies],
            "conflicts": [c.to_dict() for c in self.conflicts],
            "recommendationCategory": self.recommendationCategory,
        }
        if self.rationale:
            d["rationale"] = self.rationale
        if self.evidenceRefs:
            d["evidenceRefs"] = list(self.evidenceRefs)
        return d


@dataclass
class PortfolioCheckResult:
    candidate: PortfolioCandidate | None = None
    violations: list[dict] = field(default_factory=list)
    removed_ineligible: list[dict] = field(default_factory=list)
    valid: bool = False
    fail_closed: bool = False
    fail_closed_reasons: list[dict] = field(default_factory=list)
    trace: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "candidate": self.candidate.to_dict() if self.candidate else None,
            "violations": list(self.violations),
            "removedIneligible": list(self.removed_ineligible),
            "valid": self.valid,
            "failClosed": self.fail_closed,
            "failClosedReasons": list(self.fail_closed_reasons),
            "trace": list(self.trace),
        }


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------
def _as_member(obj, *, default_role: str) -> PortfolioMember | None:
    if obj is None or not isinstance(obj, dict):
        return None
    pid = obj.get("productId")
    pv = obj.get("productVersion")
    if not pid or not pv:
        return None
    return PortfolioMember(
        productId=pid,
        productVersion=pv,
        role=obj.get("role") or default_role,
        servedNeedId=obj.get("servedNeedId"),
        evidenceRefs=list(obj.get("evidenceRefs") or []),
    )


def _normalize_eligibility(eligibility) -> dict[str, str]:
    """把 eligibility 输入规整为 {productId: 四态}。支持三种形态：
    - None
    - {productId: "ELIGIBLE"/"INELIGIBLE"/...}
    - list[EligibilityResult | dict]
    """
    out: dict[str, str] = {}
    if eligibility is None:
        return out
    if isinstance(eligibility, dict):
        for k, v in eligibility.items():
            if isinstance(v, dict):
                out[k] = v.get("eligibility", "UNKNOWN")
            elif isinstance(v, str):
                out[k] = v
            else:
                out[k] = "UNKNOWN"
        return out
    for item in eligibility:
        if isinstance(item, EligibilityResult):
            out[item.productId] = item.eligibility
        elif isinstance(item, dict):
            pid = item.get("productId")
            if pid:
                out[pid] = item.get("eligibility", "UNKNOWN")
    return out


def _normalize_fit_scores(fit_results) -> dict[str, float | None]:
    out: dict[str, float | None] = {}
    if fit_results is None:
        return out
    if isinstance(fit_results, dict):
        for k, v in fit_results.items():
            if isinstance(v, dict):
                out[k] = v.get("fitScore")
            else:
                out[k] = v
        return out
    for item in fit_results:
        if isinstance(item, dict) and item.get("productId"):
            out[item["productId"]] = item.get("fitScore")
    return out


def _card(product_cards, product_id: str) -> dict:
    if not product_cards:
        return {}
    return product_cards.get(product_id) or {}


def _ids(value) -> list[str]:
    if isinstance(value, str):
        return [value]
    return [str(x) for x in (value or []) if x]


def _prerequisite_ids(card: dict) -> list[str]:
    return _ids(card.get("prerequisiteProductIds") or card.get("prerequisites"))


def _mutex_ids(card: dict) -> list[str]:
    return _ids(card.get("mutexProductIds") or card.get("mutualExclusions"))


def _complementary_ids(card: dict) -> list[str]:
    return _ids(card.get("complementaryProductIds") or card.get("complementaryProducts"))


def _mandatory_expert(card: dict) -> bool:
    boundary = card.get("salesBoundary") or {}
    if isinstance(boundary, dict):
        return bool(boundary.get("mandatoryExpert"))
    return False


def _card_evidence(card: dict, product_id: str) -> list[str]:
    return list(card.get("evidenceRefs") or []) or [f"EV-{product_id}"]


def _has_conflict(conflicts: list[Conflict], a: str, b: str, kind: str) -> bool:
    pair = {a, b}
    for c in conflicts:
        if c.kind == kind and {c.productA, c.productB} == pair:
            return True
    return False


def _max_category(current: str, candidate: str) -> str:
    return candidate if _CATEGORY_RANK.get(candidate, 0) > _CATEGORY_RANK.get(current, 0) else current


# ---------------------------------------------------------------------------
# PortfolioConstraintChecker
# ---------------------------------------------------------------------------
class PortfolioConstraintChecker:
    """组合生成校验器：硬失败移除 + 结构/依赖/互斥/顺序校验 + recommendationCategory 三态。

    纯确定性函数：只消费 eligibility（准入）与产品卡（前置/互斥/销售边界）与存量，
    绝不消费 fitScore 判准入 —— fitScore 仅用于在移除 INELIGIBLE 时留痕，证明高分不能掩盖硬失败。
    """

    def check(self, portfolio, *, eligibility=None, fit_results=None,
              product_cards=None, held_products=None) -> PortfolioCheckResult:
        portfolio = portfolio or {}
        elig = _normalize_eligibility(eligibility)
        fit = _normalize_fit_scores(fit_results)
        held = set(held_products or [])

        result = PortfolioCheckResult()
        portfolio_id = portfolio.get("portfolioId") or ""
        result.trace.append({"step": "begin", "portfolioId": portfolio_id})

        primary = _as_member(portfolio.get("primaryProduct"), default_role="PRIMARY")
        supporting = [
            m for m in (
                _as_member(x, default_role="SUPPORTING")
                for x in (portfolio.get("supportingProducts") or [])
            ) if m is not None
        ]

        # ---- 1) 硬失败移除：INELIGIBLE 必须移除，不得以整体分数掩盖 ----
        if primary is not None:
            status = elig.get(primary.productId, "UNKNOWN")
            if status == "INELIGIBLE":
                result.removed_ineligible.append({
                    "productId": primary.productId,
                    "productVersion": primary.productVersion,
                    "role": "PRIMARY",
                    "eligibility": "INELIGIBLE",
                    "fitScore": fit.get(primary.productId),
                    "reason": "组合内核心产品硬失败（INELIGIBLE），必须移除，不得以整体分数掩盖",
                })
                result.violations.append({
                    "code": "INELIGIBLE_PRIMARY_REMOVED",
                    "productId": primary.productId,
                    "message": "核心产品 INELIGIBLE 已移除，组合无法成立",
                })
                result.trace.append({"step": "remove_ineligible",
                                     "productId": primary.productId, "role": "PRIMARY"})
                primary = None

        kept_supporting: list[PortfolioMember] = []
        for m in supporting:
            status = elig.get(m.productId, "UNKNOWN")
            if status == "INELIGIBLE":
                result.removed_ineligible.append({
                    "productId": m.productId,
                    "productVersion": m.productVersion,
                    "role": "SUPPORTING",
                    "eligibility": "INELIGIBLE",
                    "fitScore": fit.get(m.productId),
                    "reason": "组合内配套产品硬失败（INELIGIBLE），必须移除，不得以整体分数掩盖",
                })
                result.violations.append({
                    "code": "INELIGIBLE_SUPPORTING_REMOVED",
                    "productId": m.productId,
                    "message": "配套产品 INELIGIBLE 已从组合移除",
                })
                result.trace.append({"step": "remove_ineligible",
                                     "productId": m.productId, "role": "SUPPORTING"})
            else:
                kept_supporting.append(m)
        supporting = kept_supporting

        # ---- 2) 结构校验：每方案最多一个 PRIMARY ----
        for m in supporting:
            if m.role == "PRIMARY":
                result.violations.append({
                    "code": "MULTIPLE_PRIMARY",
                    "productId": m.productId,
                    "message": "每方案最多一个核心产品，多余 PRIMARY 降级为 SUPPORTING",
                })
                m.role = "SUPPORTING"

        if primary is not None and primary.role != "PRIMARY":
            result.violations.append({
                "code": "PRIMARY_ROLE_INVALID",
                "productId": primary.productId,
                "message": f"核心产品角色必须为 PRIMARY，实际为 {primary.role}",
            })

        # ---- 3) SUPPORTING 必须说明 servedNeedId（服务的次级需求/前置条件）----
        for m in supporting:
            if not m.servedNeedId:
                result.violations.append({
                    "code": "SUPPORTING_NEED_MISSING",
                    "productId": m.productId,
                    "message": "配套产品必须说明其服务的次级需求或前置条件（servedNeedId）",
                })

        # ---- 4) DUPLICATE 去重（同一 productId 重复出现 → 冲突 + 去重）----
        conflicts: list[Conflict] = []
        placed_ids: set[str] = set()
        if primary is not None:
            placed_ids.add(primary.productId)
        deduped_supporting: list[PortfolioMember] = []
        for m in supporting:
            if m.productId in placed_ids:
                conflicts.append(Conflict(
                    m.productId, m.productId, "DUPLICATE", reasonCode="DUPLICATE_PRODUCT"))
                result.violations.append({
                    "code": "DUPLICATE_PRODUCT",
                    "productId": m.productId,
                    "message": f"产品 {m.productId} 在组合中重复出现，已去除重复项",
                })
                result.trace.append({"step": "dedup", "productId": m.productId})
                continue
            placed_ids.add(m.productId)
            deduped_supporting.append(m)
        supporting = deduped_supporting

        # ---- 5) 成员集合与产品卡 ----
        members: list[PortfolioMember] = []
        if primary is not None:
            members.append(primary)
        members.extend(supporting)
        member_ids = {m.productId for m in members}

        # ---- 6) 互斥校验（MUTUAL_EXCLUSION）----
        # 成员 × 成员：组合被拒绝；成员 × 存量：冲突记录 + 专家复核。
        for m in members:
            for other in _mutex_ids(_card(product_cards, m.productId)):
                if other == m.productId:
                    continue
                if other in member_ids and not _has_conflict(
                        conflicts, m.productId, other, "MUTUAL_EXCLUSION"):
                    a, b = sorted([m.productId, other])
                    conflicts.append(Conflict(
                        a, b, "MUTUAL_EXCLUSION", reasonCode="MUTEX_CONFLICT",
                        evidenceRefs=_card_evidence(_card(product_cards, m.productId), m.productId),
                    ))
                    result.violations.append({
                        "code": "MUTUAL_EXCLUSION_REJECTED",
                        "productId": m.productId,
                        "message": f"产品 {m.productId} 与 {other} 互斥，组合被拒绝",
                    })
                elif other in held and not _has_conflict(
                        conflicts, m.productId, other, "MUTUAL_EXCLUSION"):
                    a, b = sorted([m.productId, other])
                    conflicts.append(Conflict(
                        a, b, "MUTUAL_EXCLUSION", reasonCode="MUTEX_WITH_HOLDING",
                        evidenceRefs=_card_evidence(_card(product_cards, m.productId), m.productId),
                    ))
                    result.violations.append({
                        "code": "MUTUAL_EXCLUSION_WITH_HOLDING",
                        "productId": m.productId,
                        "message": f"产品 {m.productId} 与存量产品 {other} 互斥，需专家复核",
                    })

        # ---- 7) 依赖校验（PREREQUISITE / COMPLEMENTARY，由产品卡派生）----
        dependencies: list[Dependency] = []
        unsatisfied_prereq = False
        for m in members:
            card = _card(product_cards, m.productId)
            for pre in _prerequisite_ids(card):
                dependencies.append(Dependency(pre, m.productId, "PREREQUISITE",
                                               note="前置产品需先持有/开立"))
                if pre not in held and pre not in member_ids:
                    unsatisfied_prereq = True
                    result.violations.append({
                        "code": "PREREQUISITE_UNSATISFIED",
                        "productId": m.productId,
                        "message": f"产品 {m.productId} 的前置 {pre} 未持有且不在组合内，形成有序待办",
                    })
            for comp in _complementary_ids(card):
                dependencies.append(Dependency(m.productId, comp, "COMPLEMENTARY",
                                               note="协同产品"))

        # ---- 8) 显式依赖（PREREQUISITE / SEQUENCE / COMPLEMENTARY）----
        for dep in portfolio.get("dependencies") or []:
            if not isinstance(dep, dict):
                continue
            frm = dep.get("from")
            to = dep.get("to")
            typ = dep.get("type")
            if typ not in DEPENDENCY_TYPE_CLOSED_SET:
                result.violations.append({
                    "code": "DEPENDENCY_TYPE_INVALID",
                    "message": f"依赖类型 {typ} 不在闭集 {DEPENDENCY_TYPE_CLOSED_SET}",
                })
                continue
            if not frm or not to or frm == to:
                result.violations.append({
                    "code": "DEPENDENCY_ENDPOINT_INVALID",
                    "message": f"依赖端点非法：from={frm} to={to}",
                })
                continue
            dependencies.append(Dependency(frm, to, typ, note=dep.get("note")))
            if typ == "PREREQUISITE" and frm not in held and frm not in member_ids:
                unsatisfied_prereq = True
                result.violations.append({
                    "code": "PREREQUISITE_UNSATISFIED",
                    "message": f"前置 {frm} 未持有且不在组合内（对 {to}）",
                })

        # ---- 9) 显式冲突（MUTUAL_EXCLUSION / DUPLICATE / SALES_BOUNDARY）----
        for c in portfolio.get("conflicts") or []:
            if not isinstance(c, dict):
                continue
            a = c.get("productA")
            b = c.get("productB")
            kind = c.get("kind")
            if kind not in CONFLICT_KIND_CLOSED_SET:
                result.violations.append({
                    "code": "CONFLICT_KIND_INVALID",
                    "message": f"冲突类型 {kind} 不在闭集 {CONFLICT_KIND_CLOSED_SET}",
                })
                continue
            if not a or not b or a == b:
                result.violations.append({
                    "code": "CONFLICT_ENDPOINT_INVALID",
                    "message": f"冲突端点非法：productA={a} productB={b}",
                })
                continue
            conflicts.append(Conflict(a, b, kind, reasonCode=c.get("reasonCode"),
                                      evidenceRefs=list(c.get("evidenceRefs") or [])))
            if kind == "MUTUAL_EXCLUSION" and a in member_ids and b in member_ids:
                result.violations.append({
                    "code": "MUTUAL_EXCLUSION_REJECTED",
                    "message": f"产品 {a} 与 {b} 互斥，组合被拒绝",
                })

        # ---- 10) recommendationCategory 三态 ----
        category = "IMMEDIATE_COMMUNICATE"
        member_mutex = any(c.kind == "MUTUAL_EXCLUSION"
                           and c.productA in member_ids and c.productB in member_ids
                           for c in conflicts)
        any_mutex = any(c.kind == "MUTUAL_EXCLUSION" for c in conflicts)
        sales_boundary_conflict = any(c.kind == "SALES_BOUNDARY" for c in conflicts)
        expert_member = any(_mandatory_expert(_card(product_cards, m.productId))
                            for m in members)
        review_member = any(elig.get(m.productId, "UNKNOWN") == "REVIEW_REQUIRED"
                            for m in members)

        if any_mutex or sales_boundary_conflict or expert_member or review_member:
            category = "EXPERT_REVIEW_REQUIRED"
        elif (unsatisfied_prereq
              or any(elig.get(m.productId, "UNKNOWN") == "UNKNOWN" for m in members)
              or any(not m.servedNeedId for m in supporting)
              or primary is None):
            category = "SUPPLEMENT_FACTS_THEN_EVALUATE"

        # ---- 11) 有效性判定 ----
        valid = True
        if primary is None:
            valid = False
            result.violations.append({
                "code": "PRIMARY_MISSING",
                "message": "组合缺少可用核心产品（PRIMARY），无法成立",
            })
        if member_mutex:
            valid = False

        # ---- 12) 组装候选 + 理由 ----
        rationale_bits = []
        if result.removed_ineligible:
            rationale_bits.append(
                f"移除 {len(result.removed_ineligible)} 个硬失败产品")
        if member_mutex:
            rationale_bits.append("组合存在互斥冲突，予以拒绝")
        if unsatisfied_prereq:
            rationale_bits.append("存在未满足的前置依赖，需补充事实/形成有序待办")
        if primary is None and not result.removed_ineligible:
            rationale_bits.append("缺少核心产品")

        evidence_refs: list[str] = []
        for m in members:
            evidence_refs.extend(_card_evidence(_card(product_cards, m.productId), m.productId))

        candidate = PortfolioCandidate(
            schemaVersion="1.0.0",
            portfolioId=portfolio_id,
            primaryProduct=primary,
            supportingProducts=supporting,
            dependencies=dependencies,
            conflicts=conflicts,
            recommendationCategory=category,
            rationale="；".join(rationale_bits) or "组合通过约束校验",
            evidenceRefs=sorted(set(evidence_refs)),
        )

        result.candidate = candidate
        result.valid = valid
        result.trace.append({
            "step": "end",
            "valid": valid,
            "category": category,
            "removedIneligible": len(result.removed_ineligible),
            "conflicts": len(conflicts),
        })
        return result

    def check_many(self, portfolios, **kwargs) -> list[PortfolioCheckResult]:
        return [self.check(p, **kwargs) for p in (portfolios or [])]
