"""WP3-3：SP-15 第三段（组合）PortfolioConstraintChecker 集成测试。

状态块（CANDIDATE 交付）：
STATUS=CANDIDATE / FROZEN=NO / IMPLEMENTED=NO

覆盖用例（对齐派工 TC 编号 + portfolio-candidate.schema.json 不变量）：
- TC-PR-005  互斥 → 组合被拒绝（MUTUAL_EXCLUSION）
- TC-PR-006  前置 → 形成有序依赖（PREREQUISITE，转组合依赖/待办）
- 硬失败移除：INELIGIBLE 必须移除，不得以整体分数掩盖（INV-02）
- 结构：每方案最多一个 PRIMARY；SUPPORTING 必须说明 servedNeedId
- 冲突：DUPLICATE 去重；SALES_BOUNDARY / 存量互斥 → 专家复核
- recommendationCategory 三态：IMMEDIATE_COMMUNICATE / SUPPLEMENT_FACTS_THEN_EVALUATE /
  EXPERT_REVIEW_REQUIRED
"""
from __future__ import annotations

from dkws.application.product_recommendation.portfolio import (
    CONFLICT_KIND_CLOSED_SET,
    DEPENDENCY_TYPE_CLOSED_SET,
    RECOMMENDATION_CATEGORY_CLOSED_SET,
    ROLE_CLOSED_SET,
    PortfolioConstraintChecker,
)


def make_member(product_id, version="2.2", role="SUPPORTING",
                served_need_id="NEED-001", **extra) -> dict:
    d = {"productId": product_id, "productVersion": version, "role": role}
    if served_need_id is not None:
        d["servedNeedId"] = served_need_id
    d.update(extra)
    return d


def make_card(**overrides) -> dict:
    base = {
        "evidenceRefs": ["EV-PROD-CARD-001"],
        "salesBoundary": {"mandatoryExpert": False},
    }
    base.update(overrides)
    return base


def make_portfolio(**overrides) -> dict:
    base = {
        "portfolioId": "PORT-001",
        "primaryProduct": make_member("PROD-FIN-WC-001", role="PRIMARY",
                                      served_need_id=None),
        "supportingProducts": [],
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# 单元级：闭集对齐 contract
# ---------------------------------------------------------------------------
def test_closed_sets_match_contract():
    assert set(ROLE_CLOSED_SET) == {"PRIMARY", "SUPPORTING"}
    assert set(DEPENDENCY_TYPE_CLOSED_SET) == {"PREREQUISITE", "SEQUENCE", "COMPLEMENTARY"}
    assert set(CONFLICT_KIND_CLOSED_SET) == {"MUTUAL_EXCLUSION", "DUPLICATE", "SALES_BOUNDARY"}
    assert set(RECOMMENDATION_CATEGORY_CLOSED_SET) == {
        "IMMEDIATE_COMMUNICATE", "SUPPLEMENT_FACTS_THEN_EVALUATE", "EXPERT_REVIEW_REQUIRED"}


# ---------------------------------------------------------------------------
# TC-PR-005：互斥 → 组合被拒绝并解释原因
# ---------------------------------------------------------------------------
def test_tc_pr_005_mutual_exclusion_rejects_combination():
    portfolio = make_portfolio(supportingProducts=[
        make_member("PROD-FIN-WC-002", served_need_id="NEED-002"),
    ])
    cards = {
        "PROD-FIN-WC-001": make_card(mutexProductIds=["PROD-FIN-WC-002"]),
        "PROD-FIN-WC-002": make_card(),
    }
    elig = {"PROD-FIN-WC-001": "ELIGIBLE", "PROD-FIN-WC-002": "ELIGIBLE"}
    result = PortfolioConstraintChecker().check(
        portfolio, eligibility=elig, product_cards=cards, held_products=[])

    assert result.valid is False
    assert result.candidate.recommendationCategory == "EXPERT_REVIEW_REQUIRED"
    assert any(c.kind == "MUTUAL_EXCLUSION" for c in result.candidate.conflicts)
    assert any(v["code"] == "MUTUAL_EXCLUSION_REJECTED" for v in result.violations)


def test_mutex_with_held_product_forces_expert_review():
    portfolio = make_portfolio()
    cards = {"PROD-FIN-WC-001": make_card(mutexProductIds=["PROD-FIN-CR-001"])}
    elig = {"PROD-FIN-WC-001": "ELIGIBLE"}
    result = PortfolioConstraintChecker().check(
        portfolio, eligibility=elig, product_cards=cards,
        held_products=["PROD-FIN-CR-001"])

    # 存量互斥不拒绝组合，但需专家复核
    assert result.valid is True
    assert result.candidate.recommendationCategory == "EXPERT_REVIEW_REQUIRED"
    assert any(c.kind == "MUTUAL_EXCLUSION"
               and c.reasonCode == "MUTEX_WITH_HOLDING"
               for c in result.candidate.conflicts)


# ---------------------------------------------------------------------------
# TC-PR-006：前置 → 形成有序依赖（转组合依赖/待办）
# ---------------------------------------------------------------------------
def test_tc_pr_006_prerequisite_forms_ordered_dependency():
    portfolio = make_portfolio(primaryProduct=make_member(
        "PROD-FIN-SC-001", version="3.0", role="PRIMARY", served_need_id=None))
    cards = {"PROD-FIN-SC-001": make_card(prerequisiteProductIds=["PROD-FIN-DEP-001"])}
    elig = {"PROD-FIN-SC-001": "ELIGIBLE"}
    result = PortfolioConstraintChecker().check(
        portfolio, eligibility=elig, product_cards=cards, held_products=[])

    # 前置未持有且不在组合内 → 形成「先开立 DEP → 再申请 SC」的有序依赖
    prereqs = [d for d in result.candidate.dependencies if d.type == "PREREQUISITE"]
    assert any(d.source == "PROD-FIN-DEP-001" and d.target == "PROD-FIN-SC-001"
               for d in prereqs)
    assert result.candidate.recommendationCategory == "SUPPLEMENT_FACTS_THEN_EVALUATE"
    assert any(v["code"] == "PREREQUISITE_UNSATISFIED" for v in result.violations)
    assert result.valid is True  # 组合仍成立，仅需先补充前置


def test_prerequisite_already_held_is_satisfied():
    portfolio = make_portfolio(primaryProduct=make_member(
        "PROD-FIN-SC-001", version="3.0", role="PRIMARY", served_need_id=None))
    cards = {"PROD-FIN-SC-001": make_card(prerequisiteProductIds=["PROD-FIN-DEP-001"])}
    elig = {"PROD-FIN-SC-001": "ELIGIBLE"}
    result = PortfolioConstraintChecker().check(
        portfolio, eligibility=elig, product_cards=cards,
        held_products=["PROD-FIN-DEP-001"])

    assert not any(v["code"] == "PREREQUISITE_UNSATISFIED" for v in result.violations)
    assert result.candidate.recommendationCategory == "IMMEDIATE_COMMUNICATE"


# ---------------------------------------------------------------------------
# 硬失败移除：INELIGIBLE 必须移除，不得以整体分数掩盖（INV-02）
# ---------------------------------------------------------------------------
def test_ineligible_primary_removed_not_masked_by_score():
    portfolio = make_portfolio(supportingProducts=[
        make_member("PROD-FIN-SET-001", served_need_id="NEED-002"),
    ])
    elig = {"PROD-FIN-WC-001": "INELIGIBLE", "PROD-FIN-SET-001": "ELIGIBLE"}
    fit = {"PROD-FIN-WC-001": 0.90, "PROD-FIN-SET-001": 0.60}
    result = PortfolioConstraintChecker().check(
        portfolio, eligibility=elig, fit_results=fit)

    # 核心 INELIGIBLE → 移除 → 组合不成立
    assert result.valid is False
    assert result.candidate.primaryProduct is None
    removed = [r for r in result.removed_ineligible
               if r["productId"] == "PROD-FIN-WC-001"]
    assert len(removed) == 1
    # 即便 fitScore=0.90，仍被移除：高分不能掩盖 INELIGIBLE（INV-02）
    assert removed[0]["fitScore"] == 0.90
    assert removed[0]["eligibility"] == "INELIGIBLE"
    assert result.candidate.recommendationCategory == "SUPPLEMENT_FACTS_THEN_EVALUATE"


def test_ineligible_supporting_removed_primary_kept():
    portfolio = make_portfolio(supportingProducts=[
        make_member("PROD-FIN-SET-001", served_need_id="NEED-002"),
        make_member("PROD-FIN-SC-001", served_need_id="NEED-003"),
    ])
    elig = {
        "PROD-FIN-WC-001": "ELIGIBLE",
        "PROD-FIN-SET-001": "ELIGIBLE",
        "PROD-FIN-SC-001": "INELIGIBLE",
    }
    result = PortfolioConstraintChecker().check(portfolio, eligibility=elig)

    assert result.valid is True
    assert result.candidate.primaryProduct.productId == "PROD-FIN-WC-001"
    assert [m.productId for m in result.candidate.supportingProducts] == ["PROD-FIN-SET-001"]
    assert [r["productId"] for r in result.removed_ineligible] == ["PROD-FIN-SC-001"]
    # 无冲突无缺口 → IMMEDIATE_COMMUNICATE
    assert result.candidate.recommendationCategory == "IMMEDIATE_COMMUNICATE"


# ---------------------------------------------------------------------------
# 结构校验：最多一个 PRIMARY；SUPPORTING 必须说明 servedNeedId
# ---------------------------------------------------------------------------
def test_at_most_one_primary():
    portfolio = make_portfolio(supportingProducts=[
        make_member("PROD-FIN-SET-001", role="PRIMARY", served_need_id="NEED-002"),
    ])
    elig = {"PROD-FIN-WC-001": "ELIGIBLE", "PROD-FIN-SET-001": "ELIGIBLE"}
    result = PortfolioConstraintChecker().check(portfolio, eligibility=elig)

    assert any(v["code"] == "MULTIPLE_PRIMARY" for v in result.violations)
    # 多余 PRIMARY 降级为 SUPPORTING，仍保持最多一个核心
    assert all(m.role == "SUPPORTING" for m in result.candidate.supportingProducts)


def test_supporting_requires_served_need():
    portfolio = make_portfolio(supportingProducts=[
        make_member("PROD-FIN-SET-001", served_need_id=None),
    ])
    elig = {"PROD-FIN-WC-001": "ELIGIBLE", "PROD-FIN-SET-001": "ELIGIBLE"}
    result = PortfolioConstraintChecker().check(portfolio, eligibility=elig)

    assert result.valid is True
    assert any(v["code"] == "SUPPORTING_NEED_MISSING" for v in result.violations)
    assert result.candidate.recommendationCategory == "SUPPLEMENT_FACTS_THEN_EVALUATE"


# ---------------------------------------------------------------------------
# DUPLICATE：重复产品 → 冲突 + 去重
# ---------------------------------------------------------------------------
def test_duplicate_product_conflict_and_dedup():
    portfolio = make_portfolio(supportingProducts=[
        make_member("PROD-FIN-SET-001", served_need_id="NEED-002"),
        make_member("PROD-FIN-SET-001", served_need_id="NEED-003"),
    ])
    elig = {"PROD-FIN-WC-001": "ELIGIBLE", "PROD-FIN-SET-001": "ELIGIBLE"}
    result = PortfolioConstraintChecker().check(portfolio, eligibility=elig)

    assert any(v["code"] == "DUPLICATE_PRODUCT" for v in result.violations)
    assert any(c.kind == "DUPLICATE" for c in result.candidate.conflicts)
    assert [m.productId for m in result.candidate.supportingProducts].count(
        "PROD-FIN-SET-001") == 1


# ---------------------------------------------------------------------------
# recommendationCategory 三态
# ---------------------------------------------------------------------------
def test_all_clear_is_immediate_communicate():
    portfolio = make_portfolio(supportingProducts=[
        make_member("PROD-FIN-SET-001", served_need_id="NEED-002"),
    ])
    cards = {
        "PROD-FIN-WC-001": make_card(),
        "PROD-FIN-SET-001": make_card(),
    }
    elig = {"PROD-FIN-WC-001": "ELIGIBLE", "PROD-FIN-SET-001": "ELIGIBLE"}
    result = PortfolioConstraintChecker().check(
        portfolio, eligibility=elig, product_cards=cards)

    assert result.valid is True
    assert result.candidate.conflicts == []
    assert result.candidate.recommendationCategory == "IMMEDIATE_COMMUNICATE"


def test_sales_boundary_mandatory_expert_forces_review():
    portfolio = make_portfolio()
    cards = {"PROD-FIN-WC-001": make_card(
        salesBoundary={"mandatoryExpert": True, "noCommitment": ["不得承诺利率"]})}
    elig = {"PROD-FIN-WC-001": "ELIGIBLE"}
    result = PortfolioConstraintChecker().check(
        portfolio, eligibility=elig, product_cards=cards)

    assert result.valid is True
    assert result.candidate.recommendationCategory == "EXPERT_REVIEW_REQUIRED"


def test_review_required_eligibility_forces_expert_review():
    portfolio = make_portfolio()
    elig = {"PROD-FIN-WC-001": "REVIEW_REQUIRED"}
    result = PortfolioConstraintChecker().check(portfolio, eligibility=elig)

    assert result.valid is True
    assert result.candidate.recommendationCategory == "EXPERT_REVIEW_REQUIRED"


def test_unknown_eligibility_is_supplement_facts():
    portfolio = make_portfolio()
    elig = {"PROD-FIN-WC-001": "UNKNOWN"}
    result = PortfolioConstraintChecker().check(portfolio, eligibility=elig)

    assert result.valid is True
    assert result.candidate.recommendationCategory == "SUPPLEMENT_FACTS_THEN_EVALUATE"


# ---------------------------------------------------------------------------
# SEQUENCE 办理顺序：显式依赖校验
# ---------------------------------------------------------------------------
def test_sequence_dependency_validated_and_kept():
    portfolio = make_portfolio(dependencies=[
        {"from": "PROD-FIN-DEP-001", "to": "PROD-FIN-WC-001", "type": "SEQUENCE"},
    ])
    elig = {"PROD-FIN-WC-001": "ELIGIBLE"}
    result = PortfolioConstraintChecker().check(portfolio, eligibility=elig)

    seq = [d for d in result.candidate.dependencies if d.type == "SEQUENCE"]
    assert any(d.source == "PROD-FIN-DEP-001" and d.target == "PROD-FIN-WC-001"
               for d in seq)
    assert result.valid is True
    assert result.candidate.recommendationCategory == "IMMEDIATE_COMMUNICATE"


def test_invalid_dependency_type_reported():
    portfolio = make_portfolio(dependencies=[
        {"from": "A", "to": "B", "type": "NOT_A_REAL_TYPE"},
    ])
    elig = {"PROD-FIN-WC-001": "ELIGIBLE"}
    result = PortfolioConstraintChecker().check(portfolio, eligibility=elig)
    assert any(v["code"] == "DEPENDENCY_TYPE_INVALID" for v in result.violations)


# ---------------------------------------------------------------------------
# 序列化形状（对齐 portfolio-candidate.schema.json）
# ---------------------------------------------------------------------------
def test_portfolio_check_result_to_dict_shape():
    portfolio = make_portfolio(supportingProducts=[
        make_member("PROD-FIN-SET-001", served_need_id="NEED-002"),
    ], dependencies=[
        {"from": "PROD-FIN-DEP-001", "to": "PROD-FIN-WC-001", "type": "SEQUENCE"},
    ])
    elig = {"PROD-FIN-WC-001": "ELIGIBLE", "PROD-FIN-SET-001": "ELIGIBLE"}
    result = PortfolioConstraintChecker().check(portfolio, eligibility=elig)

    d = result.to_dict()
    assert d["valid"] is True
    assert d["removedIneligible"] == []
    cand = d["candidate"]
    for k in ("schemaVersion", "portfolioId", "primaryProduct", "supportingProducts",
              "dependencies", "conflicts", "recommendationCategory"):
        assert k in cand
    assert cand["primaryProduct"]["role"] == "PRIMARY"
    assert cand["primaryProduct"]["productId"] == "PROD-FIN-WC-001"
    assert cand["supportingProducts"][0]["servedNeedId"] == "NEED-002"
    assert cand["dependencies"][0]["from"] == "PROD-FIN-DEP-001"
    assert cand["dependencies"][0]["to"] == "PROD-FIN-WC-001"
    assert cand["dependencies"][0]["type"] == "SEQUENCE"
    assert cand["recommendationCategory"] in RECOMMENDATION_CATEGORY_CLOSED_SET
