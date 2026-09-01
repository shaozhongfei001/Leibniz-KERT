"""WP6-1：SP-15 执行器组装（五段流水线）集成测试。

状态块（CANDIDATE 交付）：
STATUS=CANDIDATE / FROZEN=NO / IMPLEMENTED=NO

覆盖：
- 黄金链路（ELIGIBLE → 匹配 → 组合 → 证据 → 确定性 contentHash）
- 错误码路径（输入不足 / 权限 / 知识陈旧 / 规则缺失）
- 输出契约 8 必填字段 + skillId=SP-15
- assemblyTrace 步骤轨迹 与 contentHash 确定性
- 资源 loader（rules/ 与 examples/ 资产，best-effort）
"""
from __future__ import annotations

from pathlib import Path

from dkws.application.product_recommendation.eligibility import (
    KERT_CONTEXT_INSUFFICIENT,
    KERT_PERMISSION_DENIED,
    KERT_PRODUCT_KNOWLEDGE_STALE,
    KERT_RULE_VERSION_MISSING,
)
from dkws.application.product_recommendation.sp15_skill import (
    CONTENT_HASH_PREFIX,
    RESULT_REQUIRED_FIELDS,
    SKILL_ID,
    ProductKnowledgeLoader,
    RecommendationInputValidator,
    RuleBundleLoader,
    Sp15ExecutionResult,
    Sp15SkillExecutor,
)

AS_OF = "2026-08-31"

COMPLETE_RULE_BUNDLE = {
    "PR-VALID-001": "1.0.0-candidate",
    "PR-REG-001": "1.0.0-candidate",
    "PR-ELIG-001": "1.0.0-candidate",
    "PR-PRMUTEX-001": "1.0.0-candidate",
    "PR-MAT-001": "1.0.0-candidate",
    "PR-SALES-001": "1.0.0-candidate",
}


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
        "evidenceRefs": ["EV-PROD-001"],
        "capabilities": ["WORKING_CAPITAL_FINANCING"],
        "prohibitedIndustries": ["REAL_ESTATE", "GAMBLING"],
        "prohibitedRegions": [],
        "prohibitedUses": [],
        "admissionCriteria": {
            "customerTypes": ["CORPORATE"],
            "minScale": "MEDIUM",
            "minRating": "A",
            "requiredAccountRelationship": "SETTLEMENT_ACCOUNT",
        },
        "prerequisites": [],
        "mutualExclusions": [],
        "requiredMaterials": ["FINANCIAL_STATEMENT"],
        "salesBoundary": {"mandatoryExpert": False, "noCommitment": ["不得承诺利率"]},
    }
    base.update(overrides)
    return base


def make_facts(**overrides) -> dict:
    base = {
        "customerId": "CUST-001",
        "institution": "BRANCH-SH-001",
        "industry": "MANUFACTURING",
        "region": "CN",
        "useOfFunds": "WORKING_CAPITAL",
        "customerType": "CORPORATE",
        "scale": "MEDIUM",
        "rating": "AA",
        "accountRelationships": ["SETTLEMENT_ACCOUNT"],
        "heldProducts": ["PROD-DEPOSIT-001"],
        "materials": ["FINANCIAL_STATEMENT"],
        "needs": [
            {
                "needId": "NEED-001",
                "needType": "FINANCING",
                "needStatus": "VERIFIED_FACT",
                "requiredCapabilities": ["WORKING_CAPITAL_FINANCING"],
                "evidenceRefs": ["EV-CUST-001"],
            }
        ],
    }
    base.update(overrides)
    return base


def make_context(**overrides) -> dict:
    base = {
        "schemaVersion": "1.0.0",
        "customerId": "CUST-001",
        "needVersionIds": ["NEED-001"],
        "recommendationObjective": "补充流动资金方案",
        "requestedProductDomains": ["FINANCING"],
        "asOf": AS_OF,
        "customerFactSnapshotId": "CFS-20260831-0001",
        "productKnowledgeSnapshotRef": "PKS-20260831-0001",
        "ruleBundleRef": "RB-20260831-0001",
        "permissionDecisionId": "PERM-20260831-0001",
        "activationContract": "AC-PRODUCT-RECOMMEND-001",
        "runId": "REC-20260831-0001",
        "productKnowledgeSnapshot": {"products": [make_product()]},
        "ruleBundle": dict(COMPLETE_RULE_BUNDLE),
        "customerFactSnapshot": make_facts(),
        "generatedAt": "2026-08-31T09:00:00+08:00",
    }
    base.update(overrides)
    return base


def make_request(**ctx_overrides) -> dict:
    return {"context": make_context(**ctx_overrides)}


def run(request) -> Sp15ExecutionResult:
    return Sp15SkillExecutor().execute(request)


# ---------------------------------------------------------------------------
# 步骤 0：RecommendationInputValidator
# ---------------------------------------------------------------------------
def test_input_validator_accepts_complete_context():
    v = RecommendationInputValidator().validate(make_context())
    assert v.valid is True
    assert v.errors == []


def test_input_validator_missing_required_field_context_insufficient():
    ctx = make_context()
    del ctx["customerId"]
    v = RecommendationInputValidator().validate(ctx)
    assert v.valid is False
    assert any(e["code"] == KERT_CONTEXT_INSUFFICIENT and e["field"] == "customerId"
               for e in v.errors)


def test_input_validator_missing_snapshot_ref_context_insufficient():
    ctx = make_context()
    del ctx["productKnowledgeSnapshotRef"]
    v = RecommendationInputValidator().validate(ctx)
    assert v.valid is False
    assert any(e["code"] == KERT_CONTEXT_INSUFFICIENT
               and e["field"] == "productKnowledgeSnapshotRef" for e in v.errors)


def test_input_validator_missing_permission_denied():
    ctx = make_context()
    del ctx["permissionDecisionId"]
    v = RecommendationInputValidator().validate(ctx)
    assert v.valid is False
    assert any(e["code"] == KERT_PERMISSION_DENIED for e in v.errors)


# ---------------------------------------------------------------------------
# 黄金链路
# ---------------------------------------------------------------------------
def test_golden_chain_produces_contract_result():
    res = run(make_request())
    assert res.ok is True
    assert res.errors == []
    data = res.data
    assert data is not None

    # 输出契约 8 必填字段 + skillId
    for f in RESULT_REQUIRED_FIELDS:
        assert f in data, f"缺少必填字段 {f}"
    assert data["schemaVersion"] == "1.0.0"
    assert data["skillId"] == SKILL_ID
    assert data["skillVersion"] == "2.0.0-candidate"
    assert data["contentHash"].startswith(CONTENT_HASH_PREFIX + ":")
    assert data["traceId"]
    assert data["evidenceBundleId"]

    # 关键数组非空
    assert data["eligibilityResults"]
    assert data["fitResults"]
    assert data["portfolioCandidates"]
    assert data["needProfile"]

    # 至少一个 ELIGIBLE 且 fitScore 非 null
    elig = {r["productId"]: r["eligibility"] for r in data["eligibilityResults"]}
    assert any(v == "ELIGIBLE" for v in elig.values())
    assert any(fr.get("fitScore") is not None for fr in data["fitResults"])

    # 组合候选有 PRIMARY
    primary = data["portfolioCandidates"][0]["primaryProduct"]
    assert primary["role"] == "PRIMARY"
    assert primary["servedNeedId"]

    # needProfile 需求状态为 VERIFIED_FACT（不冒充事实）
    assert data["needProfile"][0]["needStatus"] == "VERIFIED_FACT"

    # 无 LLM 调用
    assert res.model_calls == []


def test_golden_chain_ineligible_fit_score_null():
    # 命中监管禁止 → INELIGIBLE；fitResults 中该产品 fitScore 必须为 null（INV-02）
    ctx = make_context(
        productKnowledgeSnapshot={"products": [make_product(
            prohibitedIndustries=["MANUFACTURING"])]},
    )
    res = run({"context": ctx})
    assert res.ok is True  # 无 fail-closed，结果仍产出
    elig = {r["productId"]: r["eligibility"] for r in res.data["eligibilityResults"]}
    assert elig["PROD-WC-001"] == "INELIGIBLE"
    fit = {f["productId"]: f for f in res.data["fitResults"]}
    assert fit["PROD-WC-001"]["fitScore"] is None
    assert fit["PROD-WC-001"].get("rank") is None
    # 无已合格候选 → 组合为空
    assert res.data["portfolioCandidates"] == []


# ---------------------------------------------------------------------------
# 错误码路径
# ---------------------------------------------------------------------------
def test_chain_permission_denied_returns_no_result():
    ctx = make_context()
    del ctx["permissionDecisionId"]
    res = run({"context": ctx})
    assert res.ok is False
    assert res.data is None
    assert any(e["code"] == KERT_PERMISSION_DENIED for e in res.errors)


def test_chain_context_insufficient_returns_no_result():
    ctx = make_context()
    del ctx["asOf"]
    res = run({"context": ctx})
    assert res.ok is False
    assert res.data is None
    assert any(e["code"] == KERT_CONTEXT_INSUFFICIENT for e in res.errors)


def test_chain_rule_version_missing_fail_closed():
    partial = {k: v for k, v in COMPLETE_RULE_BUNDLE.items() if k != "PR-REG-001"}
    ctx = make_context(ruleBundle=partial)
    res = run({"context": ctx})
    assert res.ok is False
    assert res.data is None
    assert any(e["code"] == KERT_RULE_VERSION_MISSING for e in res.errors)


def test_chain_product_knowledge_stale_fail_closed():
    ctx = make_context(productKnowledgeSnapshot={"products": [make_product(
        effectiveTo="2026-06-30")]})
    res = run({"context": ctx})
    assert res.ok is False
    assert res.data is None
    assert any(e["code"] == KERT_PRODUCT_KNOWLEDGE_STALE for e in res.errors)


# ---------------------------------------------------------------------------
# assemblyTrace 与 contentHash 确定性
# ---------------------------------------------------------------------------
def test_assembly_trace_records_all_phases():
    res = run(make_request())
    phases = [t["phase"] for t in res.assembly_trace]
    for expected in ("VALIDATE", "RESOLVE_UNIVERSE", "ELIGIBILITY", "NEED_PROFILE",
                     "MATCH", "RANK", "PORTFOLIO", "EXPLAIN", "EVIDENCE"):
        assert expected in phases, f"assemblyTrace 缺少 {expected}"


def test_content_hash_deterministic():
    r1 = run(make_request())
    r2 = run(make_request())
    assert r1.ok and r2.ok
    # 相同输入 → 相同 contentHash 与完整一致的结果（generatedAt 固定）
    assert r1.data["contentHash"] == r2.data["contentHash"]
    assert r1.data == r2.data

    # 内容哈希不含 generatedAt 自身：generatedAt 变化不影响重放哈希
    ctx = make_context()
    ctx.pop("generatedAt", None)
    r3 = run({"context": ctx})
    assert r3.ok
    assert r3.data["contentHash"] == r1.data["contentHash"]


# ---------------------------------------------------------------------------
# 资源 loader（best-effort）
# ---------------------------------------------------------------------------
def test_rule_bundle_loader_from_dir():
    bundle, errs = RuleBundleLoader().load_dir()
    assert errs == []
    assert set(bundle) == set(COMPLETE_RULE_BUNDLE)
    assert all(v == "1.0.0-candidate" for v in bundle.values())


def test_product_loader_from_assets():
    products, errs = ProductKnowledgeLoader().load_dir()
    assert errs == []
    assert len(products) >= 3
    for p in products:
        assert p["productId"]
        assert p["owner"]
        assert p["source"]
        assert p["evidenceRefs"], f"{p['productId']} 缺少证据引用"
    # OQ-02：试点资产已激活为 ACTIVE，进入生产推荐全集
    assert all(p["status"] == "ACTIVE" for p in products)


def test_rule_loader_missing_dir_error():
    bundle, errs = RuleBundleLoader().load_dir(Path("/nonexistent/rules-xyz"))
    assert bundle == {}
    assert any(e["code"] == KERT_RULE_VERSION_MISSING for e in errs)


def test_product_loader_missing_dir_error():
    products, errs = ProductKnowledgeLoader().load_dir(Path("/nonexistent/assets-xyz"))
    assert products == []
    assert any(e["code"] == KERT_PRODUCT_KNOWLEDGE_STALE for e in errs)


def test_rule_bundle_parse_passed_in_input():
    bundle, errs = RuleBundleLoader().parse({"rules": COMPLETE_RULE_BUNDLE})
    assert errs == []
    assert bundle == COMPLETE_RULE_BUNDLE
    # 列表形态
    bundle2, errs2 = RuleBundleLoader().parse(
        [{"ruleId": rid, "ruleVersion": v} for rid, v in COMPLETE_RULE_BUNDLE.items()])
    assert errs2 == []
    assert bundle2 == COMPLETE_RULE_BUNDLE
