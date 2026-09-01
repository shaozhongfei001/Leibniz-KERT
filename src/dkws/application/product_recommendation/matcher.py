"""SP-15 第二段 NeedCapabilityMatcher（确定性核心，无 LLM）。

状态块（CANDIDATE 交付）：
STATUS=CANDIDATE / FROZEN=NO / IMPLEMENTED=NO

依据：
- gits-cbanking specs/product-recommendation/product-fit-result.schema.json
  （维度闭集 CORE_NEED_FIT/SCENARIO_FIT/EXECUTABILITY/RELATIONSHIP_INCREMENT/
   PORTFOLIO_SYNERGY/EVIDENCE_SUFFICIENCY；维度结果 STRONG/MODERATE/WEAK/UNKNOWN；
   NeedStatus VERIFIED_FACT/HUMAN_CONFIRMED/INFERRED_NEED/UNKNOWN/CONFLICT；
   Reason 需 evidenceRefs minItems 1）
- skills/product-recommendation/SP-15.md §2 第二段（仅对 ELIGIBLE 计算；
  INFERRED_NEED 只作核实建议，不作强推介理由）
- skills/product-recommendation/rules/README.md（排序策略：FitScore=Σ(wi×mi)）

职责：
1. 仅对 ELIGIBLE 产品计算六个维度的分维度匹配（每维度 result + rationale + evidenceRefs）。
2. 生成推荐理由 / 不推荐理由，每条必带证据引用（INV-04）。
   - 推荐理由只由 VERIFIED_FACT / HUMAN_CONFIRMED 需求驱动；
   - INFERRED_NEED 只进入 conditions（条件化建议），绝不进入 recommendationReasons。
3. 组装 matchedNeeds / matchedCapabilities / materialGaps / riskNotes / salesBoundaries
   / expertCollaborationRequired / evidenceRefs。

不变量（本模块机器可测）：
- INV-02 Eligibility=INELIGIBLE → 不计算任何 dimensionMatches/reasons
  （fitScore 由 ranker 置 null，见 ranker.py）。
- INV-04 每条推荐/不推荐理由必须携带 ≥1 条 evidenceRef。
- INV-10 需求状态 CONFLICT → EVIDENCE_SUFFICIENCY=UNKNOWN（禁止确定性解读）。

本模块不调用 LLM，不产生任何网络/文件副作用，纯确定性函数。
"""
from __future__ import annotations

from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# 闭集枚举（对齐 product-fit-result.schema.json）
# ---------------------------------------------------------------------------
DIMENSION_CLOSED_SET = (
    "CORE_NEED_FIT",
    "SCENARIO_FIT",
    "EXECUTABILITY",
    "RELATIONSHIP_INCREMENT",
    "PORTFOLIO_SYNERGY",
    "EVIDENCE_SUFFICIENCY",
)
DIMENSION_RESULT_CLOSED_SET = ("STRONG", "MODERATE", "WEAK", "UNKNOWN")
NEED_STATUS_CLOSED_SET = (
    "VERIFIED_FACT",
    "HUMAN_CONFIRMED",
    "INFERRED_NEED",
    "UNKNOWN",
    "CONFLICT",
)
SOURCE_TYPE_CLOSED_SET = ("FACT", "KNOWLEDGE", "RULE", "INTERACTION")

# 可参与匹配的需求状态（UNKNOWN/CONFLICT 不参与确定性匹配）
_MATCHABLE_NEED_STATUSES = {"VERIFIED_FACT", "HUMAN_CONFIRMED", "INFERRED_NEED"}
# 可形成「强推介理由」的需求状态（INFERRED_NEED 被排除，见 INV/任务约束）
_STRONG_REASON_STATUSES = {"VERIFIED_FACT", "HUMAN_CONFIRMED"}
# 证据充分度优先级（越大越强）
_NEED_STATUS_PRECEDENCE = {
    "VERIFIED_FACT": 3,
    "HUMAN_CONFIRMED": 2,
    "INFERRED_NEED": 1,
    "UNKNOWN": 0,
    "CONFLICT": -1,
}


def _dedup(values) -> list[str]:
    out: list[str] = []
    for v in values or []:
        if v and v not in out:
            out.append(v)
    return out


def _as_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value else []
    out: list[str] = []
    for item in value:
        if isinstance(item, str):
            out.append(item)
        elif isinstance(item, dict):
            out.append(item.get("capabilityId") or item.get("code")
                        or item.get("id") or item.get("value") or "")
    return [x for x in out if x]


# ---------------------------------------------------------------------------
# 结果对象（对齐 product-fit-result.schema.json）
# ---------------------------------------------------------------------------
@dataclass
class DimensionMatch:
    dimension: str
    result: str
    rationale: str = ""
    evidenceRefs: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "dimension": self.dimension,
            "result": self.result,
            "rationale": self.rationale,
            "evidenceRefs": list(self.evidenceRefs),
        }


@dataclass
class Reason:
    text: str
    evidenceRefs: list[str] = field(default_factory=list)
    sourceType: str = "FACT"

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "evidenceRefs": list(self.evidenceRefs),
            "sourceType": self.sourceType,
        }


@dataclass
class NeedReference:
    needId: str
    needStatus: str
    needVersionId: str = ""
    evidenceRefs: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = {
            "needId": self.needId,
            "needStatus": self.needStatus,
            "evidenceRefs": list(self.evidenceRefs),
        }
        if self.needVersionId:
            d["needVersionId"] = self.needVersionId
        return d


@dataclass
class FitResult:
    schemaVersion: str = "1.0.0"
    productId: str = ""
    productVersion: str = ""
    rank: int | None = None
    fitScore: float | None = None
    dimensionMatches: list[DimensionMatch] = field(default_factory=list)
    matchedNeeds: list[NeedReference] = field(default_factory=list)
    matchedCapabilities: list[str] = field(default_factory=list)
    recommendationReasons: list[Reason] = field(default_factory=list)
    notRecommendReasons: list[Reason] = field(default_factory=list)
    conditions: list[str] = field(default_factory=list)
    materialGaps: list[str] = field(default_factory=list)
    riskNotes: list[str] = field(default_factory=list)
    salesBoundaries: list[str] = field(default_factory=list)
    expertCollaborationRequired: bool = False
    evidenceRefs: list[str] = field(default_factory=list)
    # 内部门禁字段（不进入 schema 序列化；additionalProperties=false）
    eligibility: str = "ELIGIBLE"

    def to_dict(self) -> dict:
        d = {
            "schemaVersion": self.schemaVersion,
            "productId": self.productId,
            "productVersion": self.productVersion,
            "fitScore": self.fitScore,
            "dimensionMatches": [m.to_dict() for m in self.dimensionMatches],
            "matchedNeeds": [n.to_dict() for n in self.matchedNeeds],
            "matchedCapabilities": list(self.matchedCapabilities),
            "recommendationReasons": [r.to_dict() for r in self.recommendationReasons],
            # schema 中 notRecommendReasons 为 string[]；内部 Reason 承载证据（INV-04），
            # 序列化时只输出 text，证据统一并入顶层 evidenceRefs（见 _collect_evidence）。
            "notRecommendReasons": [r.text for r in self.notRecommendReasons],
            "conditions": list(self.conditions),
            "materialGaps": list(self.materialGaps),
            "riskNotes": list(self.riskNotes),
            "salesBoundaries": list(self.salesBoundaries),
            "expertCollaborationRequired": self.expertCollaborationRequired,
            "evidenceRefs": list(self.evidenceRefs),
        }
        if self.rank is not None:
            d["rank"] = self.rank
        return d


# ---------------------------------------------------------------------------
# NeedCapabilityMatcher
# ---------------------------------------------------------------------------
class NeedCapabilityMatcher:
    """仅对 ELIGIBLE 产品计算六个维度匹配（确定性，无 LLM）。"""

    def match(self, products, needs=None, facts=None, *, eligibility=None) -> list[FitResult]:
        """对每个产品产出 FitResult。

        - eligibility=None：视为调用方已把输入限定为 ELIGIBLE 集合（默认 ELIGIBLE）；
        - eligibility 传入 dict {productId: status} 或 list[EligibilityResult|dict]：
          未出现在映射中的 productId 一律按 UNKNOWN 处理（fail-closed，不计算匹配）。
        """
        products = products or []
        needs = needs or []
        facts = facts or {}
        elig_map = self._eligibility_map(products, eligibility)

        results: list[FitResult] = []
        for product in products:
            if not isinstance(product, dict):
                continue
            pid = product.get("productId", "")
            status = elig_map.get(pid)
            if status != "ELIGIBLE":
                # 门禁：非 ELIGIBLE 不计算任何维度/理由（INV-02）
                results.append(FitResult(
                    productId=pid,
                    productVersion=product.get("productVersion", ""),
                    eligibility=status or "UNKNOWN",
                ))
                continue
            results.append(self._match_eligible(product, needs, facts))
        return results

    @staticmethod
    def _eligibility_map(products, eligibility) -> dict:
        if eligibility is None:
            return {p.get("productId"): p.get("eligibility", "ELIGIBLE")
                    for p in products if isinstance(p, dict)}
        if isinstance(eligibility, dict):
            return dict(eligibility)
        out: dict = {}
        for item in eligibility:
            if hasattr(item, "eligibility"):
                out[item.productId] = item.eligibility
            elif isinstance(item, dict):
                out[item.get("productId")] = item.get("eligibility", "UNKNOWN")
        return out

    # ---- 主装配 ----

    def _match_eligible(self, product: dict, needs: list, facts: dict) -> FitResult:
        caps = self._capability_codes(product)
        dims = [
            self._dim_core_need_fit(product, needs, caps),
            self._dim_scenario_fit(product, needs, facts),
            self._dim_executability(product, facts),
            self._dim_relationship_increment(product, facts),
            self._dim_portfolio_synergy(product, facts),
            self._dim_evidence_sufficiency(product, needs),
        ]
        matched_needs = self._matched_needs(product, needs, caps)
        matched_caps = self._matched_capabilities(needs, caps)
        rec_reasons = self._recommendation_reasons(product, needs, matched_needs)
        not_rec_reasons, material_gaps = self._not_recommend_reasons_and_gaps(product, facts, dims)
        conditions = self._conditions(product, needs)
        sales_boundaries, expert_required = self._sales_boundary(product)
        evidence = self._collect_evidence(product, dims, rec_reasons, not_rec_reasons)

        return FitResult(
            productId=product.get("productId", ""),
            productVersion=product.get("productVersion", ""),
            dimensionMatches=dims,
            matchedNeeds=matched_needs,
            matchedCapabilities=matched_caps,
            recommendationReasons=rec_reasons,
            notRecommendReasons=not_rec_reasons,
            conditions=conditions,
            materialGaps=material_gaps,
            riskNotes=_as_list(product.get("riskNotes")),
            salesBoundaries=sales_boundaries,
            expertCollaborationRequired=expert_required,
            evidenceRefs=evidence,
            eligibility="ELIGIBLE",
        )

    # ---- 六个维度 ----

    def _dim_core_need_fit(self, product, needs, caps) -> DimensionMatch:
        matchable = [n for n in needs if n.get("needStatus") in _MATCHABLE_NEED_STATUSES]
        rated: list[tuple[float, dict]] = []
        for n in matchable:
            required = _as_list(n.get("requiredCapabilities"))
            if not required:
                continue
            covered = [c for c in required if c in caps]
            rated.append((len(covered) / len(required), n))
        if not rated:
            return DimensionMatch(
                "CORE_NEED_FIT", "UNKNOWN",
                "缺少可匹配的需求能力信号（requiredCapabilities）",
                self._need_evidence(matchable))

        best_coverage, best_need = max(rated, key=lambda t: t[0])
        evidence = _dedup(self._need_evidence([best_need]) + self._product_evidence(product))
        need_id = best_need.get("needId", "?")
        if best_coverage >= 1.0:
            return DimensionMatch("CORE_NEED_FIT", "STRONG",
                                  f"产品能力全覆盖需求 {need_id} 的能力要求", evidence)
        if best_coverage > 0:
            return DimensionMatch("CORE_NEED_FIT", "MODERATE",
                                  f"产品能力部分覆盖需求 {need_id} 的能力要求", evidence)
        return DimensionMatch("CORE_NEED_FIT", "WEAK",
                              f"产品能力未覆盖需求 {need_id} 的能力要求", evidence)

    def _dim_scenario_fit(self, product, needs, facts) -> DimensionMatch:
        prod_scen = _as_list(product.get("applicableScenarios") or product.get("scenarios"))
        cust_scen = self._customer_scenarios(needs, facts)
        evidence = _dedup(self._product_evidence(product) + self._need_evidence(needs))
        if not prod_scen:
            return DimensionMatch("SCENARIO_FIT", "UNKNOWN",
                                  "产品卡未声明适用场景", evidence)
        if not cust_scen:
            return DimensionMatch("SCENARIO_FIT", "UNKNOWN",
                                  "缺少客户场景事实", evidence)
        inter = sorted(set(prod_scen) & set(cust_scen))
        if inter:
            return DimensionMatch("SCENARIO_FIT", "STRONG",
                                  f"客户场景与产品适用场景交集：{inter}", evidence)
        fam = product.get("productFamily")
        if fam and any((n.get("needType") or n.get("domain")) == fam for n in needs):
            return DimensionMatch("SCENARIO_FIT", "MODERATE",
                                  "场景无直接交集，但产品族与需求域一致", evidence)
        return DimensionMatch("SCENARIO_FIT", "WEAK",
                              "产品适用场景与客户场景无交集", evidence)

    def _dim_executability(self, product, facts) -> DimensionMatch:
        required = _as_list(product.get("requiredMaterials"))
        prereq = _as_list(product.get("prerequisites"))
        evidence = self._product_evidence(product)
        if not required and not prereq:
            return DimensionMatch("EXECUTABILITY", "STRONG",
                                  "无材料/前置要求，可执行性无硬阻碍", evidence)
        if required and "materials" not in facts:
            return DimensionMatch("EXECUTABILITY", "UNKNOWN",
                                  "缺少客户材料提供情况", evidence)
        if prereq and "heldProducts" not in facts:
            return DimensionMatch("EXECUTABILITY", "UNKNOWN",
                                  "缺少客户存量产品事实", evidence)
        provided = set(_as_list(facts.get("materials")))
        held = set(_as_list(facts.get("heldProducts")))
        missing = [m for m in required if m not in provided]
        missing_prereq = [p for p in prereq if p not in held]
        if missing_prereq:
            return DimensionMatch("EXECUTABILITY", "WEAK",
                                  f"前置产品未满足：{missing_prereq}", evidence)
        if missing:
            return DimensionMatch("EXECUTABILITY", "MODERATE",
                                  f"材料缺口（非阻断）：{missing}", evidence)
        return DimensionMatch("EXECUTABILITY", "STRONG",
                              "材料齐备、前置满足", evidence)

    def _dim_relationship_increment(self, product, facts) -> DimensionMatch:
        pid = product.get("productId", "")
        evidence = self._product_evidence(product)
        if "heldProducts" not in facts:
            return DimensionMatch("RELATIONSHIP_INCREMENT", "UNKNOWN",
                                  "缺少客户存量产品事实", evidence)
        held = _as_list(facts.get("heldProducts"))
        rels = _as_list(facts.get("accountRelationships") or facts.get("accountRelationship"))
        if pid in held:
            return DimensionMatch("RELATIONSHIP_INCREMENT", "WEAK",
                                  "客户已持有该产品，增量价值有限", evidence)
        if rels:
            return DimensionMatch("RELATIONSHIP_INCREMENT", "STRONG",
                                  "客户已有账户关系，交叉销售具备增量基础", evidence)
        return DimensionMatch("RELATIONSHIP_INCREMENT", "MODERATE",
                              "客户尚无账户关系，属新客获取", evidence)

    def _dim_portfolio_synergy(self, product, facts) -> DimensionMatch:
        comp = _as_list(product.get("complementaryProducts") or product.get("complementProducts"))
        evidence = self._product_evidence(product)
        if not comp:
            return DimensionMatch("PORTFOLIO_SYNERGY", "UNKNOWN",
                                  "产品卡未声明配套产品", evidence)
        if "heldProducts" not in facts:
            return DimensionMatch("PORTFOLIO_SYNERGY", "UNKNOWN",
                                  "缺少客户存量产品事实", evidence)
        held = set(_as_list(facts.get("heldProducts")))
        synergy = [c for c in comp if c in held]
        if synergy:
            return DimensionMatch("PORTFOLIO_SYNERGY", "STRONG",
                                  f"与存量产品形成组合协同：{synergy}", evidence)
        return DimensionMatch("PORTFOLIO_SYNERGY", "WEAK",
                              "与存量产品暂无组合协同信号", evidence)

    def _dim_evidence_sufficiency(self, product, needs) -> DimensionMatch:
        if not needs:
            return DimensionMatch("EVIDENCE_SUFFICIENCY", "UNKNOWN",
                                  "缺少需求画像", self._product_evidence(product))
        statuses = {n.get("needStatus") for n in needs}
        if "CONFLICT" in statuses:
            return DimensionMatch("EVIDENCE_SUFFICIENCY", "UNKNOWN",
                                  "需求事实存在冲突，禁止确定性解读（INV-10）",
                                  self._need_evidence(needs))
        best = max(needs, key=lambda n: _NEED_STATUS_PRECEDENCE.get(n.get("needStatus"), -2))
        bs = best.get("needStatus")
        if bs == "UNKNOWN":
            return DimensionMatch("EVIDENCE_SUFFICIENCY", "UNKNOWN",
                                  "需求状态未知", self._need_evidence(needs))
        evidence = _dedup(self._need_evidence(
            [n for n in needs if n.get("needStatus") == bs]) + self._product_evidence(product))
        if bs == "VERIFIED_FACT":
            return DimensionMatch("EVIDENCE_SUFFICIENCY", "STRONG",
                                  "核心需求为已核实事实且带证据", evidence)
        if bs == "HUMAN_CONFIRMED":
            return DimensionMatch("EVIDENCE_SUFFICIENCY", "STRONG",
                                  "核心需求经人工确认且带证据", evidence)
        if bs == "INFERRED_NEED":
            return DimensionMatch("EVIDENCE_SUFFICIENCY", "MODERATE",
                                  "核心需求为推断需求，仅作核实建议", evidence)
        return DimensionMatch("EVIDENCE_SUFFICIENCY", "UNKNOWN",
                              "无法判定证据充分度", evidence)

    # ---- 匹配装配 ----

    def _matched_needs(self, product, needs, caps) -> list[NeedReference]:
        fam = product.get("productFamily")
        out: list[NeedReference] = []
        for n in needs:
            status = n.get("needStatus")
            if status not in _MATCHABLE_NEED_STATUSES:
                continue
            required = _as_list(n.get("requiredCapabilities"))
            if required:
                if not any(c in caps for c in required):
                    continue
            else:
                nt = n.get("needType") or n.get("domain")
                if nt and fam and nt != fam:
                    continue
            out.append(NeedReference(
                needId=n.get("needId", ""),
                needStatus=status,
                needVersionId=n.get("needVersionId") or "",
                evidenceRefs=_as_list(n.get("evidenceRefs")),
            ))
        return out

    @staticmethod
    def _matched_capabilities(needs, caps) -> list[str]:
        out: set[str] = set()
        for n in needs:
            if n.get("needStatus") not in _MATCHABLE_NEED_STATUSES:
                continue
            for c in _as_list(n.get("requiredCapabilities")):
                if c in caps:
                    out.add(c)
        return sorted(out)

    def _recommendation_reasons(self, product, needs, matched_needs) -> list[Reason]:
        reasons: list[Reason] = []
        prod_ev = self._product_evidence(product)
        matched_ids = {m.needId for m in matched_needs}
        for n in needs:
            status = n.get("needStatus")
            if status not in _STRONG_REASON_STATUSES:
                continue
            if n.get("needId") not in matched_ids:
                continue
            evidence = _dedup(_as_list(n.get("evidenceRefs")) + prod_ev)
            if not evidence:
                continue  # INV-04：无证据不得产出推荐理由（fail-closed）
            source = "FACT" if status == "VERIFIED_FACT" else "INTERACTION"
            reasons.append(Reason(
                text=f"产品能力覆盖客户需求 {n.get('needId')}（{self._need_label(n)}）",
                evidenceRefs=evidence,
                sourceType=source,
            ))
        return reasons

    def _not_recommend_reasons_and_gaps(self, product, facts, dims) -> tuple[list[Reason], list[str]]:
        reasons: list[Reason] = []
        gaps: list[str] = []
        pid = product.get("productId", "")
        prod_ev = self._product_evidence(product)

        if pid in _as_list(facts.get("heldProducts")):
            reasons.append(Reason("客户已持有该产品，增量价值有限", prod_ev, "FACT"))

        required = _as_list(product.get("requiredMaterials"))
        provided = set(_as_list(facts.get("materials")))
        missing = [m for m in required if m not in provided]
        if missing:
            gaps.extend(missing)
            reasons.append(Reason(f"材料缺口：{missing}", prod_ev, "KNOWLEDGE"))

        synergy = self._find_dim(dims, "PORTFOLIO_SYNERGY")
        if synergy and synergy.result == "WEAK":
            reasons.append(Reason("与存量产品暂无组合协同信号", prod_ev, "KNOWLEDGE"))

        return reasons, gaps

    def _conditions(self, product, needs) -> list[str]:
        out: list[str] = []
        for n in needs:
            if n.get("needStatus") == "INFERRED_NEED":
                out.append(f"需求 {n.get('needId')} 为推断需求，仅作核实建议，不作强推介理由")
        prereq = _as_list(product.get("prerequisites"))
        if prereq:
            out.append(f"适用前提：需已满足前置产品 {prereq}")
        return out

    def _sales_boundary(self, product) -> tuple[list[str], bool]:
        boundary = product.get("salesBoundary") or {}
        if isinstance(boundary, dict):
            return _as_list(boundary.get("noCommitment")), bool(boundary.get("mandatoryExpert"))
        return [], False

    def _collect_evidence(self, product, dims, rec_reasons, not_rec_reasons) -> list[str]:
        out: list[str] = list(self._product_evidence(product))
        for d in dims:
            out = _dedup(out + list(d.evidenceRefs))
        for r in rec_reasons:
            out = _dedup(out + list(r.evidenceRefs))
        for r in not_rec_reasons:
            out = _dedup(out + list(r.evidenceRefs))
        return out

    # ---- 工具 ----

    def _capability_codes(self, product) -> list[str]:
        return _as_list(product.get("capabilities") or product.get("offersCapability"))

    @staticmethod
    def _product_evidence(product) -> list[str]:
        return _as_list(product.get("evidenceRefs")) or [
            f"EV-{product.get('productId', 'PRODUCT')}"
        ]

    @staticmethod
    def _need_evidence(needs) -> list[str]:
        return _dedup([e for n in needs for e in _as_list(n.get("evidenceRefs"))])

    @staticmethod
    def _customer_scenarios(needs, facts) -> list[str]:
        out: list[str] = []
        for key in ("scenarios", "customerScenarios"):
            out.extend(_as_list(facts.get(key)))
        out.extend(_as_list(facts.get("scenario")))
        for n in needs:
            out.extend(_as_list(n.get("scenario")))
        return _dedup(out)

    @staticmethod
    def _find_dim(dims, dimension) -> DimensionMatch | None:
        for d in dims:
            if d.dimension == dimension:
                return d
        return None

    @staticmethod
    def _need_label(n) -> str:
        return n.get("needType") or n.get("domain") or n.get("needId", "?")
