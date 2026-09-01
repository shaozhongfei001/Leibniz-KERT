"""WP3-2：SP-15 第二段 NeedCapabilityMatcher + CandidateRanker 集成测试。

状态块（CANDIDATE 交付）：
STATUS=CANDIDATE / FROZEN=NO / IMPLEMENTED=NO

覆盖用例：
- 闭集契约（维度/维度结果/NeedStatus/sourceType/默认权重和=1.0）
- matcher：仅对 ELIGIBLE 计算分维度匹配（INV-02 门禁）
- matcher：六维度全量 result + rationale + evidenceRefs
- matcher：推荐理由每条带证据（INV-04）
- matcher：INFERRED_NEED 只作条件化建议，不作强推介理由
- matcher：不推荐理由每条带证据（INV-04）
- matcher：CONFLICT 需求 → EVIDENCE_SUFFICIENCY=UNKNOWN（INV-10）
- matcher：CORE_NEED_FIT STRONG / WEAK 判定
- ranker：默认权重 FitScore=Σ(wi×mi)
- ranker：外部权重覆盖
- ranker：ELIGIBLE 内部排序 + rank 1..n（稳定并列）
- ranker：INELIGIBLE/UNKNOWN/REVIEW_REQUIRED → fitScore=None（INV-02）
- ranker：负权重 / 未知维度 → ValueError
- 端到端：eligibility 执行器 → matcher → ranker 组合产出 schema 形状
"""
from __future__ import annotations

import pytest

from dkws.application.product_recommendation.eligibility import (
    HardEligibilityRuleExecutor,
    ProductUniverseResolver,
    eligible_for_fit,
)
from dkws.application.product_recommendation.matcher import (
    DIMENSION_CLOSED_SET,
    DIMENSION_RESULT_CLOSED_SET,
    NEED_STATUS_CLOSED_SET,
    SOURCE_TYPE_CLOSED_SET,
    DimensionMatch,
    FitResult,
    NeedCapabilityMatcher,
    Reason,
)
from dkws.application.product_recommendation.ranker import (
    DEFAULT_WEIGHTS,
    CandidateRanker,
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
        "capabilities": ["WORKING_CAPITAL_FINANCING", "REVOLVING_CREDIT"],
        "applicableScenarios": ["PROCUREMENT", "WORKING_CAPITAL"],
        "complementaryProducts": ["PROD-DEPOSIT-001", "PROD-CASH-001"],
        "admissionCriteria": {
            "customerTypes": ["CORPORATE"],
            "minScale": "MEDIUM",
            "minRating": "A",
            "requiredAccountRelationship": "SETTLEMENT_ACCOUNT",
        },
        "prerequisites": ["PROD-DEPOSIT-001"],
        "mutualExclusions": [],
        "requiredMaterials": ["FINANCIAL_STATEMENT"],
        "riskNotes": ["额度与定价以审批为准"],
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


def make_needs(*needs) -> list[dict]:
    base = {
        "needId": "NEED-001",
        "needStatus": "VERIFIED_FACT",
        "needType": "FINANCING",
        "requiredCapabilities": ["WORKING_CAPITAL_FINANCING"],
        "scenario": "PROCUREMENT",
        "evidenceRefs": ["EV-NEED-001"],
    }
    out = []
    for n in needs:
        merged = dict(base)
        merged.update(n)
        out.append(merged)
    return out


# ---------------------------------------------------------------------------
# 1) 闭集契约
# ---------------------------------------------------------------------------
def test_closed_sets_and_default_weights_match_contract():
    assert set(DIMENSION_CLOSED_SET) == {
        "CORE_NEED_FIT", "SCENARIO_FIT", "EXECUTABILITY",
        "RELATIONSHIP_INCREMENT", "PORTFOLIO_SYNERGY", "EVIDENCE_SUFFICIENCY",
    }
    assert set(DIMENSION_RESULT_CLOSED_SET) == {"STRONG", "MODERATE", "WEAK", "UNKNOWN"}
    assert set(NEED_STATUS_CLOSED_SET) == {
        "VERIFIED_FACT", "HUMAN_CONFIRMED", "INFERRED_NEED", "UNKNOWN", "CONFLICT",
    }
    assert set(SOURCE_TYPE_CLOSED_SET) == {"FACT", "KNOWLEDGE", "RULE", "INTERACTION"}
    assert set(DEFAULT_WEIGHTS) == set(DIMENSION_CLOSED_SET)
    assert abs(sum(DEFAULT_WEIGHTS.values()) - 1.0) < 1e-9
    assert all(w >= 0 for w in DEFAULT_WEIGHTS.values())


# ---------------------------------------------------------------------------
# 2) matcher：INV-02 门禁（仅 ELIGIBLE 计算）
# ---------------------------------------------------------------------------
def test_matcher_skips_non_eligible_product_inv02():
    product = make_product()
    needs = make_needs({})
    matcher = NeedCapabilityMatcher()
    results = matcher.match([product], needs, make_facts(),
                            eligibility={"PROD-WC-001": "INELIGIBLE"})
    assert len(results) == 1
    fr = results[0]
    assert fr.eligibility == "INELIGIBLE"
    assert fr.dimensionMatches == []
    assert fr.recommendationReasons == []
    assert fr.matchedNeeds == []
    assert fr.fitScore is None


def test_matcher_unknown_eligibility_is_not_computed_when_map_missing():
    """fail-closed：传入 eligibility 映射但缺该 productId → 按 UNKNOWN，不计算匹配。"""
    product = make_product()
    results = NeedCapabilityMatcher().match(
        [product], make_needs({}), make_facts(),
        eligibility={"OTHER-PROD": "ELIGIBLE"})
    assert results[0].eligibility == "UNKNOWN"
    assert results[0].dimensionMatches == []


# ---------------------------------------------------------------------------
# 3) matcher：六维度全量 + rationale + evidenceRefs
# ---------------------------------------------------------------------------
def test_matcher_eligible_computes_six_dimensions_with_evidence():
    product = make_product()
    needs = make_needs({})
    results = NeedCapabilityMatcher().match(
        [product], needs, make_facts(), eligibility={"PROD-WC-001": "ELIGIBLE"})
    fr = results[0]
    assert fr.eligibility == "ELIGIBLE"
    assert {d.dimension for d in fr.dimensionMatches} == set(DIMENSION_CLOSED_SET)
    assert len(fr.dimensionMatches) == 6
    for dm in fr.dimensionMatches:
        assert dm.result in DIMENSION_RESULT_CLOSED_SET
        assert dm.rationale
        assert dm.evidenceRefs, f"{dm.dimension} 缺少 evidenceRefs"
    # 期望：需求全覆盖 → CORE_NEED_FIT STRONG；场景有交集 → SCENARIO_FIT STRONG
    by_dim = {d.dimension: d.result for d in fr.dimensionMatches}
    assert by_dim["CORE_NEED_FIT"] == "STRONG"
    assert by_dim["SCENARIO_FIT"] == "STRONG"


# ---------------------------------------------------------------------------
# 4) matcher：推荐理由每条带证据（INV-04）
# ---------------------------------------------------------------------------
def test_matcher_recommendation_reasons_carry_evidence_inv04():
    product = make_product()
    needs = make_needs({})
    results = NeedCapabilityMatcher().match(
        [product], needs, make_facts(), eligibility={"PROD-WC-001": "ELIGIBLE"})
    fr = results[0]
    assert fr.recommendationReasons, "应产出推荐理由"
    for reason in fr.recommendationReasons:
        assert isinstance(reason, Reason)
        assert reason.evidenceRefs, "推荐理由必须带证据（INV-04）"
        assert reason.sourceType in SOURCE_TYPE_CLOSED_SET
        assert reason.text


# ---------------------------------------------------------------------------
# 5) matcher：INFERRED_NEED 只作条件化建议
# ---------------------------------------------------------------------------
def test_matcher_inferred_need_goes_to_conditions_not_reasons():
    product = make_product()
    needs = make_needs({"needId": "NEED-INF-001", "needStatus": "INFERRED_NEED"})
    results = NeedCapabilityMatcher().match(
        [product], needs, make_facts(), eligibility={"PROD-WC-001": "ELIGIBLE"})
    fr = results[0]
    # INFERRED_NEED 不得形成强推介理由
    assert all("NEED-INF-001" not in r.text for r in fr.recommendationReasons)
    # 必须出现在 conditions（条件化建议）
    assert any("推断需求" in c and "NEED-INF-001" in c for c in fr.conditions)


# ---------------------------------------------------------------------------
# 6) matcher：不推荐理由每条带证据（INV-04）
# ---------------------------------------------------------------------------
def test_matcher_not_recommend_reasons_carry_evidence_inv04():
    product = make_product(requiredMaterials=["FINANCIAL_STATEMENT", "AUDIT_REPORT"])
    facts = make_facts(materials=["FINANCIAL_STATEMENT"])  # 缺 AUDIT_REPORT
    results = NeedCapabilityMatcher().match(
        [product], make_needs({}), facts, eligibility={"PROD-WC-001": "ELIGIBLE"})
    fr = results[0]
    assert fr.materialGaps == ["AUDIT_REPORT"]
    assert fr.notRecommendReasons, "材料缺口应产出不推荐理由"
    for reason in fr.notRecommendReasons:
        assert isinstance(reason, Reason)
        assert reason.evidenceRefs, "不推荐理由必须带证据（INV-04）"
    # schema 序列化：notRecommendReasons 为 string[]
    serialized = fr.to_dict()
    assert isinstance(serialized["notRecommendReasons"], list)
    assert all(isinstance(x, str) for x in serialized["notRecommendReasons"])


# ---------------------------------------------------------------------------
# 7) matcher：CONFLICT 需求 → EVIDENCE_SUFFICIENCY=UNKNOWN（INV-10）
# ---------------------------------------------------------------------------
def test_matcher_conflict_need_evidence_sufficiency_unknown_inv10():
    product = make_product()
    needs = make_needs({"needStatus": "CONFLICT"})
    results = NeedCapabilityMatcher().match(
        [product], needs, make_facts(), eligibility={"PROD-WC-001": "ELIGIBLE"})
    fr = results[0]
    by_dim = {d.dimension: d.result for d in fr.dimensionMatches}
    assert by_dim["EVIDENCE_SUFFICIENCY"] == "UNKNOWN"


# ---------------------------------------------------------------------------
# 8) matcher：CORE_NEED_FIT STRONG / WEAK 判定
# ---------------------------------------------------------------------------
def test_matcher_core_need_fit_strong_and_weak():
    matcher = NeedCapabilityMatcher()
    product = make_product()
    strong = matcher.match(
        [product], make_needs({"requiredCapabilities": ["WORKING_CAPITAL_FINANCING"]}),
        make_facts(), eligibility={"PROD-WC-001": "ELIGIBLE"})[0]
    weak = matcher.match(
        [product], make_needs({"requiredCapabilities": ["CROSS_BORDER_SETTLEMENT"]}),
        make_facts(), eligibility={"PROD-WC-001": "ELIGIBLE"})[0]
    by_strong = {d.dimension: d.result for d in strong.dimensionMatches}
    by_weak = {d.dimension: d.result for d in weak.dimensionMatches}
    assert by_strong["CORE_NEED_FIT"] == "STRONG"
    assert by_weak["CORE_NEED_FIT"] == "WEAK"


# ---------------------------------------------------------------------------
# 9) ranker：默认权重 FitScore=Σ(wi×mi)
# ---------------------------------------------------------------------------
def _fit_with(results_by_dim: dict[str, str], eligibility: str = "ELIGIBLE") -> FitResult:
    dims = [DimensionMatch(d, r, "rationale", ["EV-1"])
            for d, r in results_by_dim.items()]
    return FitResult(productId="P", productVersion="1", dimensionMatches=dims,
                     eligibility=eligibility)


def test_ranker_default_weights_fit_score():
    ranker = CandidateRanker()
    dims = {
        "CORE_NEED_FIT": "STRONG",      # 0.35 * 1.0 = 0.35
        "SCENARIO_FIT": "MODERATE",     # 0.15 * 0.5 = 0.075
        "EXECUTABILITY": "STRONG",      # 0.15 * 1.0 = 0.15
        "RELATIONSHIP_INCREMENT": "STRONG",  # 0.10 * 1.0 = 0.10
        "PORTFOLIO_SYNERGY": "MODERATE",     # 0.10 * 0.5 = 0.05
        "EVIDENCE_SUFFICIENCY": "STRONG",    # 0.15 * 1.0 = 0.15
    }
    expected = 0.35 + 0.075 + 0.15 + 0.10 + 0.05 + 0.15  # = 0.875
    fr = _fit_with(dims)
    assert ranker.fit_score(fr) == pytest.approx(expected, abs=1e-6)


def test_ranker_default_weights_all_strong_is_one():
    ranker = CandidateRanker()
    dims = {d: "STRONG" for d in DIMENSION_CLOSED_SET}
    assert ranker.fit_score(_fit_with(dims)) == pytest.approx(1.0, abs=1e-6)


# ---------------------------------------------------------------------------
# 10) ranker：外部权重覆盖
# ---------------------------------------------------------------------------
def test_ranker_custom_weights_override_default():
    ranker = CandidateRanker(weights={
        "CORE_NEED_FIT": 0.5,
        "SCENARIO_FIT": 0.0,
        "EXECUTABILITY": 0.0,
        "RELATIONSHIP_INCREMENT": 0.0,
        "PORTFOLIO_SYNERGY": 0.0,
        "EVIDENCE_SUFFICIENCY": 0.5,
    })
    dims = {
        "CORE_NEED_FIT": "STRONG",
        "SCENARIO_FIT": "WEAK",
        "EXECUTABILITY": "WEAK",
        "RELATIONSHIP_INCREMENT": "WEAK",
        "PORTFOLIO_SYNERGY": "WEAK",
        "EVIDENCE_SUFFICIENCY": "MODERATE",
    }
    # 0.5*1.0 + 0.5*0.5 = 0.75
    assert ranker.fit_score(_fit_with(dims)) == pytest.approx(0.75, abs=1e-6)


# ---------------------------------------------------------------------------
# 11) ranker：ELIGIBLE 内部排序 + rank 1..n（稳定并列）
# ---------------------------------------------------------------------------
def test_ranker_sorts_eligible_desc_and_assigns_rank():
    ranker = CandidateRanker()
    high = _fit_with({d: "STRONG" for d in DIMENSION_CLOSED_SET}, eligibility="ELIGIBLE")
    high.productId = "HIGH"
    low = _fit_with({d: "WEAK" for d in DIMENSION_CLOSED_SET}, eligibility="ELIGIBLE")
    low.productId = "LOW"
    mid = _fit_with({d: "MODERATE" for d in DIMENSION_CLOSED_SET}, eligibility="ELIGIBLE")
    mid.productId = "MID"

    ranked = ranker.rank([low, high, mid])
    assert [fr.productId for fr in ranked] == ["HIGH", "MID", "LOW"]
    assert [fr.rank for fr in ranked] == [1, 2, 3]
    assert ranked[0].fitScore > ranked[1].fitScore > ranked[2].fitScore


def test_ranker_stable_tie_preserves_input_order():
    ranker = CandidateRanker()
    a = _fit_with({d: "STRONG" for d in DIMENSION_CLOSED_SET}, eligibility="ELIGIBLE")
    a.productId = "A"
    b = _fit_with({d: "STRONG" for d in DIMENSION_CLOSED_SET}, eligibility="ELIGIBLE")
    b.productId = "B"
    ranked = ranker.rank([a, b])
    assert [fr.productId for fr in ranked] == ["A", "B"]
    assert ranked[0].fitScore == ranked[1].fitScore


# ---------------------------------------------------------------------------
# 12) ranker：非 ELIGIBLE → fitScore=None（INV-02）
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("status", ["INELIGIBLE", "UNKNOWN", "REVIEW_REQUIRED"])
def test_ranker_non_eligible_fit_score_none_inv02(status):
    ranker = CandidateRanker()
    eligible = _fit_with({d: "STRONG" for d in DIMENSION_CLOSED_SET}, eligibility="ELIGIBLE")
    eligible.productId = "OK"
    blocked = _fit_with({d: "STRONG" for d in DIMENSION_CLOSED_SET}, eligibility=status)
    blocked.productId = "BLOCKED"
    ranked = ranker.rank([blocked, eligible])
    by_id = {fr.productId: fr for fr in ranked}
    assert by_id["BLOCKED"].fitScore is None
    assert by_id["BLOCKED"].rank is None
    # 非 ELIGIBLE 不参与内部排序，排在 ELIGIBLE 之后
    assert [fr.productId for fr in ranked] == ["OK", "BLOCKED"]


# ---------------------------------------------------------------------------
# 13) ranker：非法权重 → ValueError
# ---------------------------------------------------------------------------
def test_ranker_rejects_negative_weight():
    with pytest.raises(ValueError):
        CandidateRanker(weights={"CORE_NEED_FIT": -0.1})


def test_ranker_rejects_unknown_dimension():
    with pytest.raises(ValueError):
        CandidateRanker(weights={"NOT_A_DIMENSION": 0.5})


# ---------------------------------------------------------------------------
# 14) 端到端：eligibility → matcher → ranker
# ---------------------------------------------------------------------------
def test_end_to_end_eligibility_matcher_ranker_schema_shape():
    product = make_product()
    facts = make_facts()
    needs = make_needs({})

    resolution = ProductUniverseResolver().resolve([product], as_of=AS_OF,
                                                   institution="BRANCH-SH-001")
    exec_result = HardEligibilityRuleExecutor().execute(
        resolution.universe, facts, as_of=AS_OF)
    eligible = eligible_for_fit(exec_result.results)
    assert len(eligible) == 1

    matcher = NeedCapabilityMatcher()
    fit_results = matcher.match([product], needs, facts, eligibility=eligible)
    assert len(fit_results) == 1
    assert fit_results[0].eligibility == "ELIGIBLE"

    ranked = CandidateRanker().rank(fit_results)
    fr = ranked[0]
    d = fr.to_dict()
    # schema 必填字段
    assert d["schemaVersion"] == "1.0.0"
    assert d["productId"] == "PROD-WC-001"
    assert d["productVersion"] == "2.2"
    assert d["rank"] == 1
    assert d["fitScore"] is not None
    assert 0.0 <= d["fitScore"] <= 1.0
    # 维度项必有 dimension+result
    for dm in d["dimensionMatches"]:
        assert dm["dimension"] in DIMENSION_CLOSED_SET
        assert dm["result"] in DIMENSION_RESULT_CLOSED_SET
    # 推荐理由每条证据引用（INV-04）
    for reason in d["recommendationReasons"]:
        assert len(reason["evidenceRefs"]) >= 1
