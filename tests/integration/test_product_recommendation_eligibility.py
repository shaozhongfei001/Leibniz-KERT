"""WP2-3：SP-15 第一段 Eligibility 执行器集成测试。

状态块（CANDIDATE 交付）：
STATUS=CANDIDATE / FROZEN=NO / IMPLEMENTED=NO

覆盖用例（对齐派工 TC 编号）：
- TC-PR-001  ELIGIBLE 进入第二段（含完整 ruleResults 证据）
- TC-PR-002  监管禁止 → INELIGIBLE
- TC-PR-003  缺事实 → UNKNOWN（不得按 ELIGIBLE）
- TC-PR-004  版本失效 → FAIL_CLOSED（产品过期 / 规则版本缺失）
- TC-PR-005  互斥 → REVIEW_REQUIRED
- TC-PR-008  高分不能覆盖 INELIGIBLE（eligible_for_fit 门禁）
以及机构范围 / 材料缺口 / 聚合优先级等补充用例。
"""
from __future__ import annotations

from dkws.application.product_recommendation.eligibility import (
    ELIGIBILITY_CLOSED_SET,
    KERT_CONTEXT_INSUFFICIENT,
    KERT_PRODUCT_KNOWLEDGE_STALE,
    KERT_RULE_VERSION_MISSING,
    RULE_RESULT_CLOSED_SET,
    RULE_CATALOG,
    EligibilityResult,
    ExecutionResult,
    HardEligibilityRuleExecutor,
    ProductUniverseResolver,
    RuleResult,
    aggregate_eligibility,
    eligible_for_fit,
)

AS_OF = "2026-08-31"


def make_product(**overrides) -> dict:
    base = {
        "productId": "PROD-WC-001",
        "productVersion": "2.2",
        "name": "流动资金贷款",
        "productFamily": "FINANCING",
        "status": "ACTIVE",
        "effectiveFrom": "2026-01-01",
        "effectiveTo": "2026-12-31",
        "institutions": ["BRANCH-SH-001"],
        "owner": "FIN-OWNER-01",
        "source": "src://product-cards/PROD-WC-001",
        "evidenceRefs": ["EV-PROD-CARD-001"],
        "admissionCriteria": {
            "customerTypes": ["CORPORATE"],
            "minScale": "MEDIUM",
            "minRating": "A",
            "requiredAccountRelationship": "SETTLEMENT_ACCOUNT",
        },
        "prerequisites": ["PROD-DEPOSIT-001"],
        "mutualExclusions": [],
        "requiredMaterials": ["FINANCIAL_STATEMENT"],
        "salesBoundary": {"mandatoryExpert": False, "noCommitment": ["不得承诺利率"]},
    }
    base.update(overrides)
    return base


def make_facts(**overrides) -> dict:
    base = {
        "customerId": "CUST-001",
        "industry": "MANUFACTURING",
        "region": "CN",
        "useOfFunds": "WORKING_CAPITAL",
        "customerType": "CORPORATE",
        "scale": "MEDIUM",
        "rating": "AA",
        "accountRelationships": ["SETTLEMENT_ACCOUNT"],
        "heldProducts": ["PROD-DEPOSIT-001"],
        "materials": ["FINANCIAL_STATEMENT"],
    }
    base.update(overrides)
    return base


def _results_by_rule(er: EligibilityResult) -> dict:
    return {r.ruleId: r for r in er.ruleResults}


# ---------------------------------------------------------------------------
# 单元级：闭集与聚合
# ---------------------------------------------------------------------------
def test_closed_sets_match_contract():
    assert set(ELIGIBILITY_CLOSED_SET) == {"ELIGIBLE", "INELIGIBLE", "UNKNOWN", "REVIEW_REQUIRED"}
    assert set(RULE_RESULT_CLOSED_SET) == {"PASS", "FAIL", "UNKNOWN", "REVIEW_REQUIRED"}
    assert len(RULE_CATALOG) == 6


def test_aggregate_precedence_fail_over_review_over_unknown():
    rules = [
        RuleResult("PR-REG-001", "2.0", "FAIL", "FORBIDDEN_INDUSTRY"),
        RuleResult("PR-PRE-001", "1.0", "REVIEW_REQUIRED", "MUTUAL_EXCLUSION_CONFLICT"),
        RuleResult("PR-ADM-004", "2.0", "UNKNOWN", "CUSTOMER_TYPE_MISSING"),
    ]
    # FAIL 优先级最高：即使同时存在 REVIEW_REQUIRED 与 UNKNOWN，仍为 INELIGIBLE
    assert aggregate_eligibility(rules) == "INELIGIBLE"
    # 无 FAIL 时，REVIEW_REQUIRED 压过 UNKNOWN
    assert aggregate_eligibility(rules[1:]) == "REVIEW_REQUIRED"
    # UNKNOWN 不得产出 ELIGIBLE
    assert aggregate_eligibility([rules[2]]) == "UNKNOWN"
    # 全 PASS → ELIGIBLE
    assert aggregate_eligibility([RuleResult("x", "1", "PASS", "OK")]) == "ELIGIBLE"
    # 空 → UNKNOWN（不得默认 ELIGIBLE）
    assert aggregate_eligibility([]) == "UNKNOWN"


# ---------------------------------------------------------------------------
# TC-PR-001：ELIGIBLE 进入（含完整规则证据）
# ---------------------------------------------------------------------------
def test_tc_pr_001_eligible_enters_fit_with_full_rule_evidence():
    product = make_product()
    facts = make_facts()
    resolution = ProductUniverseResolver().resolve([product], as_of=AS_OF,
                                                   institution="BRANCH-SH-001")
    assert not resolution.fail_closed
    assert [p["productId"] for p in resolution.universe] == ["PROD-WC-001"]

    result = HardEligibilityRuleExecutor().execute(
        resolution.universe, facts, as_of=AS_OF)
    assert isinstance(result, ExecutionResult)
    assert not result.fail_closed
    assert len(result.results) == 1

    er = result.results[0]
    assert er.productId == "PROD-WC-001"
    assert er.productVersion == "2.2"
    assert er.eligibility == "ELIGIBLE"
    assert er.unknowns == []
    assert er.reviewRequirements == []

    # 6 类规则全 PASS，每条结论含 ruleId+ruleVersion+result+reasonCode+inputFactRefs+evidenceRefs
    by_rule = _results_by_rule(er)
    assert list(by_rule) == [r["ruleId"] for r in RULE_CATALOG]
    for rr in er.ruleResults:
        assert rr.result == "PASS"
        assert rr.ruleVersion
        assert rr.reasonCode
        assert rr.inputFactRefs
        assert rr.evidenceRefs

    # 第二段门禁：仅 ELIGIBLE 进入
    assert eligible_for_fit(result.results) == [er]


# ---------------------------------------------------------------------------
# TC-PR-002：监管禁止 → INELIGIBLE
# ---------------------------------------------------------------------------
def test_tc_pr_002_regulatory_prohibition_is_ineligible():
    product = make_product(prohibitedIndustries=["GAMBLING", "MANUFACTURING"])
    facts = make_facts(industry="MANUFACTURING")
    resolution = ProductUniverseResolver().resolve([product], as_of=AS_OF,
                                                   institution="BRANCH-SH-001")
    result = HardEligibilityRuleExecutor().execute(
        resolution.universe, facts, as_of=AS_OF)
    er = result.results[0]
    assert er.eligibility == "INELIGIBLE"
    reg = _results_by_rule(er)["PR-REG-001"]
    assert reg.result == "FAIL"
    assert reg.reasonCode == "FORBIDDEN_INDUSTRY"
    # INELIGIBLE 不得进入第二段
    assert eligible_for_fit(result.results) == []


# ---------------------------------------------------------------------------
# TC-PR-003：缺事实 → UNKNOWN（不得按 ELIGIBLE）
# ---------------------------------------------------------------------------
def test_tc_pr_003_missing_fact_is_unknown_not_eligible():
    product = make_product()
    facts = make_facts()
    del facts["customerType"]  # 客户准入缺少企业类型
    resolution = ProductUniverseResolver().resolve([product], as_of=AS_OF,
                                                   institution="BRANCH-SH-001")
    result = HardEligibilityRuleExecutor().execute(
        resolution.universe, facts, as_of=AS_OF)
    er = result.results[0]
    assert er.eligibility == "UNKNOWN"
    adm = _results_by_rule(er)["PR-ADM-004"]
    assert adm.result == "UNKNOWN"
    assert adm.reasonCode == "CUSTOMER_TYPE_MISSING"
    # UNKNOWN 不得按 ELIGIBLE 处理（不进入第二段）
    assert eligible_for_fit(result.results) == []
    assert er.unknowns  # 生成待核实问题


# ---------------------------------------------------------------------------
# TC-PR-004：版本失效 → FAIL_CLOSED
# ---------------------------------------------------------------------------
def test_tc_pr_004_expired_product_version_fail_closed():
    # 产品在 asOf 已过期（effectiveTo 早于 asOf）
    product = make_product(effectiveTo="2026-06-30")
    resolution = ProductUniverseResolver().resolve([product], as_of=AS_OF,
                                                   institution="BRANCH-SH-001")
    # 解析器层：过期产品被排除 + 整轮 fail-closed
    assert resolution.fail_closed
    assert resolution.universe == []
    assert any(x["reasonCode"] == "PRODUCT_VERSION_EXPIRED"
               for x in resolution.excluded)
    assert any(x["errorCode"] == KERT_PRODUCT_KNOWLEDGE_STALE
               for x in resolution.fail_closed_reasons)


def test_tc_pr_004_missing_rule_version_fail_closed():
    product = make_product()
    facts = make_facts()
    resolution = ProductUniverseResolver().resolve([product], as_of=AS_OF,
                                                   institution="BRANCH-SH-001")
    # 传入不完整规则包：缺 PR-REG-001 版本 → RULE_VERSION_MISSING fail-closed
    partial_bundle = {r["ruleId"]: r["ruleVersion"] for r in RULE_CATALOG
                      if r["ruleId"] != "PR-REG-001"}
    result = HardEligibilityRuleExecutor().execute(
        resolution.universe, facts, as_of=AS_OF, rule_bundle=partial_bundle)
    assert result.fail_closed
    er = result.results[0]
    reg = _results_by_rule(er)["PR-REG-001"]
    assert reg.result == "FAIL"
    assert reg.reasonCode == "RULE_VERSION_MISSING"
    assert er.eligibility == "INELIGIBLE"
    assert any(x["errorCode"] == KERT_RULE_VERSION_MISSING
               for x in result.fail_closed_reasons)


# ---------------------------------------------------------------------------
# TC-PR-008：高分不能覆盖 INELIGIBLE
# ---------------------------------------------------------------------------
def test_tc_pr_008_high_fit_cannot_override_ineligible():
    # 产品能力与需求高度匹配（假设软评分会给出高分），但命中监管禁止
    product = make_product(prohibitedIndustries=["GAMBLING"])
    facts = make_facts(industry="GAMBLING")
    resolution = ProductUniverseResolver().resolve([product], as_of=AS_OF,
                                                   institution="BRANCH-SH-001")
    result = HardEligibilityRuleExecutor().execute(
        resolution.universe, facts, as_of=AS_OF)
    er = result.results[0]
    assert er.eligibility == "INELIGIBLE"
    # 即便"高分"候选，eligible_for_fit 也绝不放行（INV-02 门禁）
    assert eligible_for_fit(result.results) == []
    # ruleResults 记录排除证据，fit 段无法为其赋分
    assert any(r.result == "FAIL" and r.reasonCode == "FORBIDDEN_INDUSTRY"
               for r in er.ruleResults)


# ---------------------------------------------------------------------------
# TC-PR-005：互斥 → REVIEW_REQUIRED
# ---------------------------------------------------------------------------
def test_tc_pr_005_mutual_exclusion_is_review_required():
    product = make_product(mutualExclusions=["PROD-CR-001"])
    facts = make_facts(heldProducts=["PROD-DEPOSIT-001", "PROD-CR-001"])
    resolution = ProductUniverseResolver().resolve([product], as_of=AS_OF,
                                                   institution="BRANCH-SH-001")
    result = HardEligibilityRuleExecutor().execute(
        resolution.universe, facts, as_of=AS_OF)
    er = result.results[0]
    assert er.eligibility == "REVIEW_REQUIRED"
    pre = _results_by_rule(er)["PR-PRE-001"]
    assert pre.result == "REVIEW_REQUIRED"
    assert pre.reasonCode == "MUTUAL_EXCLUSION_CONFLICT"
    assert er.reviewRequirements
    # REVIEW_REQUIRED 也非 ELIGIBLE，不得进入第二段
    assert eligible_for_fit(result.results) == []


# ---------------------------------------------------------------------------
# 补充：机构范围（FAIL_CLOSED 语义）
# ---------------------------------------------------------------------------
def test_institution_mismatch_excludes_product():
    product = make_product(institutions=["BRANCH-BJ-001"])
    resolution = ProductUniverseResolver().resolve([product], as_of=AS_OF,
                                                   institution="BRANCH-SH-001")
    assert resolution.universe == []
    assert any(x["reasonCode"] == "INSTITUTION_MISMATCH"
               for x in resolution.excluded)


def test_institution_unknown_fail_closed():
    product = make_product(institutions=["BRANCH-SH-001"])
    resolution = ProductUniverseResolver().resolve([product], as_of=AS_OF,
                                                   institution=None)
    assert resolution.fail_closed
    assert resolution.universe == []
    assert any(x["reasonCode"] == "INSTITUTION_UNKNOWN"
               for x in resolution.fail_closed_reasons)
    assert any(x["errorCode"] == KERT_CONTEXT_INSUFFICIENT
               for x in resolution.fail_closed_reasons)


# ---------------------------------------------------------------------------
# 补充：材料缺口 → REVIEW_REQUIRED
# ---------------------------------------------------------------------------
def test_material_gap_is_review_required():
    product = make_product(requiredMaterials=["FINANCIAL_STATEMENT", "AUDIT_REPORT"])
    facts = make_facts(materials=["FINANCIAL_STATEMENT"])
    resolution = ProductUniverseResolver().resolve([product], as_of=AS_OF,
                                                   institution="BRANCH-SH-001")
    result = HardEligibilityRuleExecutor().execute(
        resolution.universe, facts, as_of=AS_OF)
    er = result.results[0]
    assert er.eligibility == "REVIEW_REQUIRED"
    mat = _results_by_rule(er)["PR-MAT-001"]
    assert mat.result == "REVIEW_REQUIRED"
    assert mat.reasonCode == "MATERIAL_GAP"


def test_execution_result_to_dict_shape():
    product = make_product()
    facts = make_facts()
    resolution = ProductUniverseResolver().resolve([product], as_of=AS_OF,
                                                   institution="BRANCH-SH-001")
    result = HardEligibilityRuleExecutor().execute(
        resolution.universe, facts, as_of=AS_OF)
    d = result.to_dict()
    assert d["failClosed"] is False
    assert d["results"][0]["eligibility"] == "ELIGIBLE"
    assert set(d["results"][0].keys()) == {
        "schemaVersion", "productId", "productVersion", "eligibility",
        "ruleResults", "unknowns", "reviewRequirements"}
