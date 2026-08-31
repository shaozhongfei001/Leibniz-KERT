"""SP-15 第一段 Eligibility 执行器（确定性、无 LLM）。

状态块（CANDIDATE 交付）：
STATUS=CANDIDATE / FROZEN=NO / IMPLEMENTED=NO

依据：
- skills/product-recommendation/rules/README.md（八类规则 + 硬约束执行顺序 + 不变量）
- skills/product-recommendation/SP-15.md（三段式 §2「第一段：硬约束过滤」、§7 不变量、§6 失败码）
- skills/product-recommendation/contracts/recommendation-result.md（RuleResult 字段口径）
- gits-cbanking specs/product-recommendation/eligibility-result.schema.json（四态闭集 + RuleResult）
- gits-cbanking specs/product-recommendation/README.md（§4 KERT 错误码 → GITS 处理映射）

职责：
1. ProductUniverseResolver —— 从产品资产输入解析「有效产品全集」：
   仅纳入可被正面确认 ACTIVE、处于生效区间、且机构范围匹配的产品；
   非 ACTIVE / 过期 / 机构不符 / 卡片缺 Owner 或来源 → 排除（FAIL_CLOSED：默认拒绝，
   无法正面确认即不得进入全集）。
2. HardEligibilityRuleExecutor —— 按 6 类规则固定顺序执行（有效性 / 监管禁止 /
   客户准入 / 前置互斥 / 材料 / 销售边界），输出四态闭集
   ELIGIBLE / INELIGIBLE / UNKNOWN / REVIEW_REQUIRED + ruleResults
   （ruleId / ruleVersion / result / reasonCode / inputFactRefs / evidenceRefs）。

不变量（本模块机器可测）：
- INV-01 Active(ProductVersion)=false → 不得进入候选全集；
- INV-02 Eligibility=INELIGIBLE → 不得被软评分覆盖（本模块以聚合优先级 + eligible_for_fit 门禁保证）；
- INV-03 Eligibility=UNKNOWN → 不得按 ELIGIBLE 处理（聚合中 UNKNOWN 无法产出 ELIGIBLE）；
- 每条结论必须携带 ruleId+ruleVersion+inputFactRefs+result+reasonCode；
- 产品版本过期或规则版本缺失 → 整轮 fail_closed（不得产出可批准方案）。

本模块不调用 LLM，不产生任何网络/文件副作用，纯确定性函数。
"""
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# 闭集枚举（对齐 eligibility-result.schema.json / SP-15 §2）
# ---------------------------------------------------------------------------
ELIGIBILITY_CLOSED_SET = ("ELIGIBLE", "INELIGIBLE", "UNKNOWN", "REVIEW_REQUIRED")
RULE_RESULT_CLOSED_SET = ("PASS", "FAIL", "UNKNOWN", "REVIEW_REQUIRED")

# KERT_* 失败码（对齐 SP-15 §6；语义与 GITS 处理映射见 GITS specs/product-recommendation/README.md §4）
KERT_PERMISSION_DENIED = "KERT_PERMISSION_DENIED"
KERT_CONTEXT_INSUFFICIENT = "KERT_CONTEXT_INSUFFICIENT"
KERT_PRODUCT_KNOWLEDGE_STALE = "KERT_PRODUCT_KNOWLEDGE_STALE"
KERT_RULE_VERSION_MISSING = "KERT_RULE_VERSION_MISSING"
KERT_EVIDENCE_INCOMPLETE = "KERT_EVIDENCE_INCOMPLETE"

# ---------------------------------------------------------------------------
# 规则目录（6 类，固定执行顺序；规则版本为候选 RuleBundle 默认值，可被覆盖）
# ---------------------------------------------------------------------------
RULE_CATALOG = (
    {"ruleId": "PR-ELIG-001", "category": "VALIDITY", "ruleVersion": "1.3"},
    {"ruleId": "PR-REG-001", "category": "REGULATORY", "ruleVersion": "2.0"},
    {"ruleId": "PR-ADM-004", "category": "ADMISSION", "ruleVersion": "2.0"},
    {"ruleId": "PR-PRE-001", "category": "PREREQUISITE_EXCLUSION", "ruleVersion": "1.0"},
    {"ruleId": "PR-MAT-001", "category": "MATERIAL", "ruleVersion": "1.0"},
    {"ruleId": "PR-BND-001", "category": "SALES_BOUNDARY", "ruleVersion": "1.0"},
)

_DEFAULT_RULE_BUNDLE = {r["ruleId"]: r["ruleVersion"] for r in RULE_CATALOG}

# 企业规模有序刻度（越大越高级）；低于 minScale → 不满足准入
_SCALE_ORDER = ("MICRO", "SMALL", "MEDIUM", "LARGE")
# 评级有序刻度（越大越好）
_RATING_ORDER = ("BBB", "A", "AA", "AAA")

_UNKNOWN_QUESTIONS = {
    "PRODUCT_STATUS_UNKNOWN": ("产品版本状态缺失", "补录产品版本状态后重跑"),
    "AS_OF_MISSING": ("缺少业务时点 asOf", "补传 asOf（YYYY-MM-DD）"),
    "INDUSTRY_UNKNOWN": ("缺少客户行业事实", "核实客户所属行业"),
    "REGION_UNKNOWN": ("缺少客户经营地域事实", "核实客户经营地域"),
    "USE_UNKNOWN": ("缺少资金用途事实", "核实资金用途"),
    "CUSTOMER_TYPE_MISSING": ("缺少客户企业类型", "核实客户企业类型"),
    "CUSTOMER_SCALE_MISSING": ("缺少客户企业规模", "核实客户企业规模"),
    "CUSTOMER_RATING_MISSING": ("缺少客户评级", "核实客户评级"),
    "ACCOUNT_RELATIONSHIP_UNKNOWN": ("缺少客户账户关系事实", "核实客户账户关系"),
    "HELD_PRODUCTS_UNKNOWN": ("缺少客户存量产品事实", "核实客户已持有产品"),
    "MATERIAL_FACTS_MISSING": ("缺少客户材料提供情况", "核实客户已提供材料"),
}

_REVIEW_REQUIREMENTS = {
    "MUTUAL_EXCLUSION_CONFLICT": ("客户已持有互斥产品，需产品专家复核组合可行性", "产品专家"),
    "MATERIAL_GAP": ("必备材料缺失，需客户经理补齐并复核", "客户经理"),
    "EXPERT_REVIEW_REQUIRED": ("销售边界要求专家介入，强制人工门禁", "产品/合规专家"),
}


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------
def _as_date(value):
    """把日期/时间戳规整为 date；无法解析返回 None。"""
    if value is None:
        return None
    if isinstance(value, _dt.datetime):
        return value.date()
    if isinstance(value, _dt.date):
        return value
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        try:
            return _dt.date.fromisoformat(s[:10])
        except ValueError:
            return None
    return None


def _fact_refs(facts: dict, keys) -> list[str]:
    refs = facts.get("factRefs") or {}
    out = []
    for k in keys:
        out.append(refs.get(k) or f"FACT-{str(k).replace('-', '_').upper()}")
    return out


def _evidence_refs(product: dict) -> list[str]:
    return product.get("evidenceRefs") or [f"EV-{product.get('productId', 'PRODUCT')}"]


# ---------------------------------------------------------------------------
# 结果对象
# ---------------------------------------------------------------------------
@dataclass
class RuleResult:
    ruleId: str
    ruleVersion: str
    result: str
    reasonCode: str
    inputFactRefs: list[str] = field(default_factory=list)
    evidenceRefs: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "ruleId": self.ruleId,
            "ruleVersion": self.ruleVersion,
            "result": self.result,
            "reasonCode": self.reasonCode,
            "inputFactRefs": list(self.inputFactRefs),
            "evidenceRefs": list(self.evidenceRefs),
        }


@dataclass
class EligibilityResult:
    schemaVersion: str = "1.0.0"
    productId: str = ""
    productVersion: str = ""
    eligibility: str = "UNKNOWN"
    ruleResults: list[RuleResult] = field(default_factory=list)
    unknowns: list[dict] = field(default_factory=list)
    reviewRequirements: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "schemaVersion": self.schemaVersion,
            "productId": self.productId,
            "productVersion": self.productVersion,
            "eligibility": self.eligibility,
            "ruleResults": [r.to_dict() for r in self.ruleResults],
            "unknowns": list(self.unknowns),
            "reviewRequirements": list(self.reviewRequirements),
        }


@dataclass
class UniverseResolution:
    universe: list[dict] = field(default_factory=list)
    excluded: list[dict] = field(default_factory=list)
    fail_closed: bool = False
    fail_closed_reasons: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "universe": list(self.universe),
            "excluded": list(self.excluded),
            "failClosed": self.fail_closed,
            "failClosedReasons": list(self.fail_closed_reasons),
        }


@dataclass
class ExecutionResult:
    results: list[EligibilityResult] = field(default_factory=list)
    fail_closed: bool = False
    fail_closed_reasons: list[dict] = field(default_factory=list)
    trace: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "results": [r.to_dict() for r in self.results],
            "failClosed": self.fail_closed,
            "failClosedReasons": list(self.fail_closed_reasons),
            "trace": list(self.trace),
        }

    def eligible(self) -> list[EligibilityResult]:
        return [r for r in self.results if r.eligibility == "ELIGIBLE"]


def aggregate_eligibility(rule_results: list[RuleResult]) -> str:
    """把规则结果聚合为四态闭集。

    优先级：FAIL(→INELIGIBLE) > REVIEW_REQUIRED > UNKNOWN > PASS(→ELIGIBLE)。
    由此保证 INELIGIBLE 不被任何软信号覆盖、UNKNOWN 不会被当作 ELIGIBLE。
    """
    if not rule_results:
        return "UNKNOWN"
    states = [r.result for r in rule_results]
    if "FAIL" in states:
        return "INELIGIBLE"
    if "REVIEW_REQUIRED" in states:
        return "REVIEW_REQUIRED"
    if "UNKNOWN" in states:
        return "UNKNOWN"
    return "ELIGIBLE"


def eligible_for_fit(results: list[EligibilityResult]) -> list[EligibilityResult]:
    """第二段（Fit）只允许 ELIGIBLE 进入；INELIGIBLE/UNKNOWN/REVIEW_REQUIRED 一律排除。"""
    return [r for r in results if r.eligibility == "ELIGIBLE"]


# ---------------------------------------------------------------------------
# 1) 产品全集解析器
# ---------------------------------------------------------------------------
class ProductUniverseResolver:
    """从产品资产/规则输入解析「有效产品全集」（确定性，FAIL_CLOSED）。"""

    def resolve(self, products, *, as_of=None, institution=None) -> UniverseResolution:
        resolution = UniverseResolution()
        if products is None:
            return resolution
        for product in products:
            if not isinstance(product, dict):
                continue
            pid = product.get("productId")
            pv = product.get("productVersion")
            if not pid or not pv:
                self._exclude(resolution, product, "PRODUCT_CARD_INVALID",
                              KERT_PRODUCT_KNOWLEDGE_STALE, fail_closed=True,
                              message="产品卡缺少 productId / productVersion")
                continue
            if not product.get("owner") or not product.get("source"):
                self._exclude(resolution, product, "PRODUCT_CARD_INCOMPLETE",
                              KERT_PRODUCT_KNOWLEDGE_STALE, fail_closed=True,
                              message=f"产品 {pid} 缺少 Owner 或来源，不得进入生产推荐全集")
                continue

            status = product.get("status")
            if status is None:
                self._exclude(resolution, product, "PRODUCT_STATUS_UNKNOWN",
                              KERT_PRODUCT_KNOWLEDGE_STALE, fail_closed=True,
                              message=f"产品 {pid} 状态缺失，默认拒绝")
                continue
            if status != "ACTIVE":
                self._exclude(resolution, product, "PRODUCT_NOT_ACTIVE", None,
                              fail_closed=False, message=f"产品 {pid} 状态 {status} 非 ACTIVE")
                continue

            # 生效区间（过期 → FAIL_CLOSED：知识版本失效，整轮不得产出可批准方案）
            eff_from = _as_date(product.get("effectiveFrom"))
            eff_to = _as_date(product.get("effectiveTo"))
            aod = _as_date(as_of)
            if (eff_from is not None or eff_to is not None) and aod is None:
                self._exclude(resolution, product, "AS_OF_MISSING",
                              KERT_CONTEXT_INSUFFICIENT, fail_closed=True,
                              message=f"产品 {pid} 含生效区间但缺少 asOf，默认拒绝")
                continue
            if aod is not None and (
                (eff_from is not None and aod < eff_from)
                or (eff_to is not None and aod > eff_to)
            ):
                self._exclude(resolution, product, "PRODUCT_VERSION_EXPIRED",
                              KERT_PRODUCT_KNOWLEDGE_STALE, fail_closed=True,
                              message=f"产品 {pid}@{pv} 在 asOf={aod.isoformat()} 已过期")
                continue

            # 机构范围（FAIL_CLOSED：无法确认机构 → 默认拒绝；明确不符 → 排除）
            allowed = product.get("institutions") or []
            if allowed:
                if institution is None:
                    self._exclude(resolution, product, "INSTITUTION_UNKNOWN",
                                  KERT_CONTEXT_INSUFFICIENT, fail_closed=True,
                                  message=f"产品 {pid} 限定机构但客户机构缺失，默认拒绝")
                    continue
                if institution not in allowed:
                    self._exclude(resolution, product, "INSTITUTION_MISMATCH", None,
                                  fail_closed=False,
                                  message=f"机构 {institution} 不在产品 {pid} 机构范围")
                    continue

            resolution.universe.append(product)

        resolution.fail_closed = bool(resolution.fail_closed_reasons)
        return resolution

    @staticmethod
    def _exclude(resolution: UniverseResolution, product: dict, reason_code: str,
                 error_code: str | None, *, fail_closed: bool, message: str) -> None:
        entry = {
            "productId": product.get("productId"),
            "productVersion": product.get("productVersion"),
            "reasonCode": reason_code,
            "message": message,
        }
        if error_code:
            entry["errorCode"] = error_code
        resolution.excluded.append(entry)
        if fail_closed:
            resolution.fail_closed_reasons.append({
                "errorCode": error_code,
                "reasonCode": reason_code,
                "productId": product.get("productId"),
                "message": message,
            })


# ---------------------------------------------------------------------------
# 2) 硬约束规则执行器
# ---------------------------------------------------------------------------
class HardEligibilityRuleExecutor:
    """按 6 类规则固定顺序执行，输出四态闭集 + ruleResults（确定性，无 LLM）。"""

    def execute(self, universe, facts=None, *, as_of=None, rule_bundle=None) -> ExecutionResult:
        facts = facts or {}
        aod = as_of if as_of is not None else facts.get("asOf")
        bundle = self._resolve_bundle(rule_bundle)
        exec_result = ExecutionResult()

        for product in universe:
            if not isinstance(product, dict):
                continue
            er, reasons = self._evaluate_product(product, facts, as_of=aod, bundle=bundle)
            exec_result.results.append(er)
            exec_result.fail_closed_reasons.extend(reasons)

        exec_result.fail_closed = bool(exec_result.fail_closed_reasons)
        return exec_result

    @staticmethod
    def _resolve_bundle(rule_bundle) -> dict:
        if rule_bundle is None:
            return dict(_DEFAULT_RULE_BUNDLE)
        out: dict = {}
        for rid, val in (rule_bundle or {}).items():
            if isinstance(val, dict):
                out[rid] = val.get("ruleVersion")
            else:
                out[rid] = val
        return out

    def _evaluate_product(self, product, facts, *, as_of, bundle) -> tuple[EligibilityResult, list[dict]]:
        pid = product.get("productId", "")
        pv = product.get("productVersion", "")
        rule_results: list[RuleResult] = []
        unknowns: list[dict] = []
        review_requirements: list[dict] = []
        fail_closed_reasons: list[dict] = []

        for meta in RULE_CATALOG:
            rid = meta["ruleId"]
            rv = bundle.get(rid)
            if rv is None:
                rr = RuleResult(rid, "", "FAIL", "RULE_VERSION_MISSING",
                                _fact_refs(facts, ["ruleBundle"]), _evidence_refs(product))
                rule_results.append(rr)
                fail_closed_reasons.append({
                    "errorCode": KERT_RULE_VERSION_MISSING,
                    "reasonCode": "RULE_VERSION_MISSING",
                    "productId": pid,
                    "message": f"规则 {rid} 版本缺失，本轮不得产出可批准方案",
                })
                continue

            rr = self._eval_rule(meta, rv, product, facts, as_of)
            rule_results.append(rr)

            if rr.result == "UNKNOWN":
                question, action = _UNKNOWN_QUESTIONS.get(
                    rr.reasonCode, (rr.reasonCode, "补充事实"))
                unknowns.append({
                    "question": question,
                    "relatedFactRef": rr.inputFactRefs[0] if rr.inputFactRefs else None,
                    "suggestedAction": action,
                })
            elif rr.result == "REVIEW_REQUIRED":
                reason, expertise = _REVIEW_REQUIREMENTS.get(
                    rr.reasonCode, (rr.reasonCode, "产品专家"))
                review_requirements.append({
                    "reason": reason,
                    "requiredExpertise": expertise,
                    "ruleId": rr.ruleId,
                })
            elif rr.result == "FAIL" and rr.reasonCode in (
                    "PRODUCT_VERSION_EXPIRED", "PRODUCT_VERSION_INACTIVE"):
                fail_closed_reasons.append({
                    "errorCode": KERT_PRODUCT_KNOWLEDGE_STALE,
                    "reasonCode": rr.reasonCode,
                    "productId": pid,
                    "message": f"产品 {pid}@{pv} 版本失效（{rr.reasonCode}）",
                })

        eligibility = aggregate_eligibility(rule_results)
        er = EligibilityResult(
            schemaVersion="1.0.0",
            productId=pid,
            productVersion=pv,
            eligibility=eligibility,
            ruleResults=rule_results,
            unknowns=unknowns,
            reviewRequirements=review_requirements,
        )
        return er, fail_closed_reasons

    # ---- 6 类规则求值（顺序即 RULE_CATALOG） ----

    def _eval_rule(self, meta: dict, rv: str, product: dict, facts: dict, as_of) -> RuleResult:
        category = meta["category"]
        rid = meta["ruleId"]
        if category == "VALIDITY":
            return self._eval_validity(rid, rv, product, facts, as_of)
        if category == "REGULATORY":
            return self._eval_regulatory(rid, rv, product, facts)
        if category == "ADMISSION":
            return self._eval_admission(rid, rv, product, facts)
        if category == "PREREQUISITE_EXCLUSION":
            return self._eval_prerequisite_exclusion(rid, rv, product, facts)
        if category == "MATERIAL":
            return self._eval_material(rid, rv, product, facts)
        if category == "SALES_BOUNDARY":
            return self._eval_sales_boundary(rid, rv, product, facts)
        return RuleResult(rid, rv, "UNKNOWN", "RULE_NOT_IMPLEMENTED",
                          [], _evidence_refs(product))

    def _eval_validity(self, rid, rv, product, facts, as_of) -> RuleResult:
        refs = _fact_refs(facts, ["productVersion", "asOf"])
        ev = _evidence_refs(product)
        status = product.get("status")
        if status is None:
            return RuleResult(rid, rv, "UNKNOWN", "PRODUCT_STATUS_UNKNOWN", refs, ev)
        if status != "ACTIVE":
            return RuleResult(rid, rv, "FAIL", "PRODUCT_VERSION_INACTIVE", refs, ev)
        eff_from = _as_date(product.get("effectiveFrom"))
        eff_to = _as_date(product.get("effectiveTo"))
        aod = _as_date(as_of)
        if eff_from is not None or eff_to is not None:
            if aod is None:
                return RuleResult(rid, rv, "UNKNOWN", "AS_OF_MISSING", refs, ev)
            if (eff_from is not None and aod < eff_from) or (eff_to is not None and aod > eff_to):
                return RuleResult(rid, rv, "FAIL", "PRODUCT_VERSION_EXPIRED", refs, ev)
        return RuleResult(rid, rv, "PASS", "PRODUCT_VERSION_ACTIVE", refs, ev)

    def _eval_regulatory(self, rid, rv, product, facts) -> RuleResult:
        refs = _fact_refs(facts, ["industry", "region", "useOfFunds"])
        ev = _evidence_refs(product)
        industry = facts.get("industry")
        region = facts.get("region")
        use = facts.get("useOfFunds")

        prohibited_industries = product.get("prohibitedIndustries") or []
        prohibited_regions = product.get("prohibitedRegions") or []
        prohibited_uses = product.get("prohibitedUses") or []

        if prohibited_industries:
            if industry is None:
                return RuleResult(rid, rv, "UNKNOWN", "INDUSTRY_UNKNOWN", refs, ev)
            if industry in prohibited_industries:
                return RuleResult(rid, rv, "FAIL", "FORBIDDEN_INDUSTRY", refs, ev)
        if prohibited_regions:
            if region is None:
                return RuleResult(rid, rv, "UNKNOWN", "REGION_UNKNOWN", refs, ev)
            if region in prohibited_regions:
                return RuleResult(rid, rv, "FAIL", "FORBIDDEN_REGION", refs, ev)
        if prohibited_uses:
            if use is None:
                return RuleResult(rid, rv, "UNKNOWN", "USE_UNKNOWN", refs, ev)
            if use in prohibited_uses:
                return RuleResult(rid, rv, "FAIL", "FORBIDDEN_USE", refs, ev)
        return RuleResult(rid, rv, "PASS", "INDUSTRY_NOT_PROHIBITED", refs, ev)

    def _eval_admission(self, rid, rv, product, facts) -> RuleResult:
        refs = _fact_refs(facts, ["customerType", "scale", "rating", "accountRelationships"])
        ev = _evidence_refs(product)
        criteria = product.get("admissionCriteria") or {}

        allowed_types = criteria.get("customerTypes") or []
        customer_type = facts.get("customerType")
        if allowed_types:
            if customer_type is None:
                return RuleResult(rid, rv, "UNKNOWN", "CUSTOMER_TYPE_MISSING", refs, ev)
            if customer_type not in allowed_types:
                return RuleResult(rid, rv, "FAIL", "CUSTOMER_TYPE_NOT_ALLOWED", refs, ev)

        min_scale = criteria.get("minScale")
        if min_scale:
            scale = facts.get("scale")
            if scale is None:
                return RuleResult(rid, rv, "UNKNOWN", "CUSTOMER_SCALE_MISSING", refs, ev)
            if _SCALE_ORDER.index(scale) < _SCALE_ORDER.index(min_scale):
                return RuleResult(rid, rv, "FAIL", "CUSTOMER_SCALE_NOT_ALLOWED", refs, ev)

        min_rating = criteria.get("minRating")
        if min_rating:
            rating = facts.get("rating")
            if rating is None:
                return RuleResult(rid, rv, "UNKNOWN", "CUSTOMER_RATING_MISSING", refs, ev)
            if _RATING_ORDER.index(rating) < _RATING_ORDER.index(min_rating):
                return RuleResult(rid, rv, "FAIL", "CUSTOMER_RATING_NOT_ALLOWED", refs, ev)

        required_rel = criteria.get("requiredAccountRelationship")
        if required_rel:
            if "accountRelationships" not in facts and "accountRelationship" not in facts:
                return RuleResult(rid, rv, "UNKNOWN", "ACCOUNT_RELATIONSHIP_UNKNOWN", refs, ev)
            rels = facts.get("accountRelationships") or facts.get("accountRelationship") or []
            if required_rel not in rels:
                return RuleResult(rid, rv, "FAIL", "ACCOUNT_RELATIONSHIP_MISSING", refs, ev)

        return RuleResult(rid, rv, "PASS", "CUSTOMER_TYPE_ALLOWED", refs, ev)

    def _eval_prerequisite_exclusion(self, rid, rv, product, facts) -> RuleResult:
        refs = _fact_refs(facts, ["heldProducts"])
        ev = _evidence_refs(product)
        exclusions = product.get("mutualExclusions") or []
        prerequisites = product.get("prerequisites") or []

        held_known = "heldProducts" in facts
        held_set = set(facts.get("heldProducts") or [])

        # 互斥优先：客户已持有互斥产品 → 需专家复核（REVIEW_REQUIRED，不自动排除也不自动通过）
        if exclusions:
            if not held_known:
                return RuleResult(rid, rv, "UNKNOWN", "HELD_PRODUCTS_UNKNOWN", refs, ev)
            conflicts = [x for x in exclusions if x in held_set]
            if conflicts:
                return RuleResult(rid, rv, "REVIEW_REQUIRED", "MUTUAL_EXCLUSION_CONFLICT", refs, ev)

        if prerequisites:
            if not held_known:
                return RuleResult(rid, rv, "UNKNOWN", "HELD_PRODUCTS_UNKNOWN", refs, ev)
            missing = [p for p in prerequisites if p not in held_set]
            if missing:
                return RuleResult(rid, rv, "FAIL", "PREREQUISITE_MISSING", refs, ev)

        return RuleResult(rid, rv, "PASS", "PREREQUISITE_SATISFIED", refs, ev)

    def _eval_material(self, rid, rv, product, facts) -> RuleResult:
        refs = _fact_refs(facts, ["materials"])
        ev = _evidence_refs(product)
        required = product.get("requiredMaterials") or []
        if not required:
            return RuleResult(rid, rv, "PASS", "MATERIALS_NOT_REQUIRED", refs, ev)
        if "materials" not in facts:
            return RuleResult(rid, rv, "UNKNOWN", "MATERIAL_FACTS_MISSING", refs, ev)
        provided = set(facts.get("materials") or [])
        missing = [m for m in required if m not in provided]
        if missing:
            return RuleResult(rid, rv, "REVIEW_REQUIRED", "MATERIAL_GAP", refs, ev)
        return RuleResult(rid, rv, "PASS", "MATERIALS_COMPLETE", refs, ev)

    def _eval_sales_boundary(self, rid, rv, product, facts) -> RuleResult:
        refs = _fact_refs(facts, ["salesBoundary"])
        ev = _evidence_refs(product)
        boundary = product.get("salesBoundary") or {}
        mandatory_expert = False
        if isinstance(boundary, dict):
            mandatory_expert = bool(boundary.get("mandatoryExpert"))
        if mandatory_expert:
            return RuleResult(rid, rv, "REVIEW_REQUIRED", "EXPERT_REVIEW_REQUIRED", refs, ev)
        return RuleResult(rid, rv, "PASS", "SALES_BOUNDARY_OK", refs, ev)
