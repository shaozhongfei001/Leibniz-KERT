"""WP3-4：SP-15 第八步 EvidenceBundleAssembler 集成测试。

状态块（CANDIDATE 交付）：
STATUS=CANDIDATE / FROZEN=NO / IMPLEMENTED=NO

覆盖用例：
- 必填证据 100% 覆盖时产出 EvidenceBundle；
- 必填快照/身份字段缺失 → 不产出（返回缺项清单，fail-closed）；
- 每条推荐理由 factRefs+knowledgeRefs 覆盖 100%；
- "模型置信度/fitScore"不得替代证据充分度；
- contentHash 确定性（同证据同哈希、键序无关、不含易变元数据）；
- 与 eligibility.py 的集成链路；
- unknowns/conflicts 聚合、to_dict 形状。
"""
from __future__ import annotations

from dkws.application.product_recommendation.evidence import (
    MISSING_PROMPT_VERSION,
    MISSING_SKILL_FIELD,
    MISSING_SNAPSHOT_FIELD,
    REASON_MISSING_FACT_REFS,
    REASON_MISSING_KNOWLEDGE_REFS,
    EvidenceAssemblyResult,
    EvidenceBundleAssembler,
)

AS_OF = "2026-08-31"
INSTITUTION = "BRANCH-SH-001"


def make_context(**overrides) -> dict:
    base = {
        "customerFactSnapshotId": "CFS-001",
        "productKnowledgeSnapshotRef": "PKS-001",
        "ruleExecutionRef": "RULE-RUN-001",
        "skillId": "SP-15",
        "skillVersion": "2.0.0-candidate",
        "permissionDecisionId": "PD-001",
    }
    base.update(overrides)
    return base


def make_eligibility_results() -> list[dict]:
    """与 eligibility.py 输出的 RuleResult 字段口径一致。"""
    return [
        {
            "productId": "PROD-WC-001",
            "productVersion": "2.2",
            "eligibility": "ELIGIBLE",
            "ruleResults": [
                {"ruleId": "PR-ELIG-001", "ruleVersion": "1.3", "result": "PASS",
                 "reasonCode": "CUSTOMER_TYPE_ALLOWED",
                 "inputFactRefs": ["FACT-CUST-001"], "evidenceRefs": ["EV-PROD-001"]},
                {"ruleId": "PR-REG-001", "ruleVersion": "2.0", "result": "PASS",
                 "reasonCode": "INDUSTRY_NOT_PROHIBITED",
                 "inputFactRefs": ["FACT-CUST-002"], "evidenceRefs": ["EV-REG-001"]},
            ],
            "unknowns": [],
            "reviewRequirements": [],
        }
    ]


def make_fit_results(**overrides) -> list[dict]:
    base = [
        {
            "productId": "PROD-WC-001",
            "productVersion": "2.2",
            "rank": 1,
            "fitScore": 0.82,
            "dimensionMatches": [
                {"dimension": "CORE_NEED_FIT", "result": "STRONG",
                 "evidenceRefs": ["EV-NEED-001"]},
            ],
            "matchedNeeds": [
                {"needId": "NEED-001", "needStatus": "VERIFIED_FACT",
                 "evidenceRefs": ["EV-NEED-001"]},
            ],
            "recommendationReasons": [
                {"text": "流动资金贷款覆盖补充营运资金需求",
                 "evidenceRefs": ["EV-NEED-001", "EV-PROD-001"], "sourceType": "FACT"},
            ],
            "conditions": [], "materialGaps": [], "riskNotes": [], "salesBoundaries": [],
        }
    ]
    if overrides:
        base[0].update(overrides)
    return base


def make_portfolio_candidates() -> list[dict]:
    return [
        {
            "portfolioId": "PORT-001",
            "primaryProduct": {"productId": "PROD-WC-001", "productVersion": "2.2",
                               "role": "PRIMARY", "servedNeedId": "NEED-001"},
            "supportingProducts": [], "dependencies": [], "conflicts": [],
            "recommendationCategory": "IMMEDIATE_COMMUNICATE",
        }
    ]


def make_need_profile() -> list[dict]:
    return [{"needId": "NEED-001", "needStatus": "VERIFIED_FACT",
             "evidenceRefs": ["EV-NEED-001"]}]


def _assemble(**kwargs) -> EvidenceAssemblyResult:
    assembler = EvidenceBundleAssembler()
    params = dict(
        context=make_context(),
        eligibility_results=make_eligibility_results(),
        fit_results=make_fit_results(),
        portfolio_candidates=make_portfolio_candidates(),
        need_profile=make_need_profile(),
        evidence_bundle_id="EVB-001",
        trace_id="TRACE-001",
        generated_at="2026-08-31T09:00:00+08:00",
    )
    params.update(kwargs)
    return assembler.assemble(**params)


# ---------------------------------------------------------------------------
# 必填证据 100% 覆盖 → 产出
# ---------------------------------------------------------------------------
def test_assembles_bundle_with_full_coverage():
    result = _assemble()
    assert isinstance(result, EvidenceAssemblyResult)
    assert result.ok
    assert result.fail_closed is False
    assert result.missing == []

    bundle = result.bundle
    assert bundle.schemaVersion == "1.0.0"
    assert bundle.evidenceBundleId == "EVB-001"
    assert bundle.customerFactSnapshotId == "CFS-001"
    assert bundle.productKnowledgeSnapshotRef == "PKS-001"
    assert bundle.ruleExecutionRef == "RULE-RUN-001"
    assert bundle.skillId == "SP-15"
    assert bundle.skillVersion == "2.0.0-candidate"
    assert bundle.permissionDecisionId == "PD-001"
    assert bundle.contentHash.startswith("sha256:")
    assert bundle.traceId == "TRACE-001"
    assert bundle.generatedAt == "2026-08-31T09:00:00+08:00"


def test_reason_coverage_100_percent_fact_and_knowledge_refs():
    result = _assemble()
    assert result.ok
    assert len(result.bundle.reasonEvidence) == 1
    re_ = result.bundle.reasonEvidence[0]
    assert re_.reason_key == "PROD-WC-001#0"
    # 每条理由都必须同时持有非空 factRefs 与 knowledgeRefs
    assert re_.factRefs
    assert re_.knowledgeRefs
    # factRefs 来自 eligibility 的 inputFactRefs，knowledgeRefs 含产品卡/规则证据
    assert set(re_.factRefs) == {"FACT-CUST-001", "FACT-CUST-002"}
    assert "EV-PROD-001" in re_.knowledgeRefs


# ---------------------------------------------------------------------------
# 必填缺失 → 不产出（fail-closed，返回缺项清单）
# ---------------------------------------------------------------------------
def test_missing_customer_fact_snapshot_rejected():
    result = _assemble(context=make_context(customerFactSnapshotId=""))
    assert not result.ok
    assert result.fail_closed
    assert result.bundle is None
    assert any(m["code"] == MISSING_SNAPSHOT_FIELD
               and m["field"] == "customerFactSnapshotId" for m in result.missing)


def test_missing_permission_decision_rejected():
    result = _assemble(context=make_context(permissionDecisionId=None))
    assert not result.ok
    assert any(m["code"] == MISSING_SNAPSHOT_FIELD
               and m["field"] == "permissionDecisionId" for m in result.missing)


def test_missing_skill_version_rejected():
    result = _assemble(context=make_context(skillVersion=""))
    assert not result.ok
    assert any(m["code"] == MISSING_SKILL_FIELD
               and m["field"] == "skillVersion" for m in result.missing)


def test_model_requires_prompt_version():
    result = _assemble(context=make_context(model="recommend-v1", promptVersion=""))
    assert not result.ok
    assert any(m["code"] == MISSING_PROMPT_VERSION for m in result.missing)


# ---------------------------------------------------------------------------
# 每条理由 factRefs+knowledgeRefs 缺失 → 不产出
# ---------------------------------------------------------------------------
def test_reason_missing_fact_and_knowledge_refs_rejected():
    # 无 eligibility 证据兜底 + 理由自身无 refs → 两条缺项
    result = _assemble(
        eligibility_results=[],
        fit_results=[{
            "productId": "PROD-WC-001", "productVersion": "2.2",
            "recommendationReasons": [{"text": "无任何证据引用"}],
        }],
        portfolio_candidates=[], need_profile=[],
    )
    assert not result.ok
    assert any(m["code"] == REASON_MISSING_FACT_REFS for m in result.missing)
    assert any(m["code"] == REASON_MISSING_KNOWLEDGE_REFS for m in result.missing)


def test_model_confidence_does_not_substitute_evidence():
    # 高 fitScore / 模型置信度不能替代证据充分度
    result = _assemble(
        eligibility_results=[],
        fit_results=[{
            "productId": "PROD-WC-001", "productVersion": "2.2",
            "fitScore": 0.99, "modelConfidence": 0.98,
            "recommendationReasons": [{"text": "高置信度但无证据"}],
        }],
        portfolio_candidates=[], need_profile=[],
    )
    assert not result.ok
    assert result.bundle is None
    assert any(m["code"] == REASON_MISSING_FACT_REFS for m in result.missing)


# ---------------------------------------------------------------------------
# contentHash 确定性
# ---------------------------------------------------------------------------
def test_content_hash_deterministic_and_key_order_independent():
    r1 = _assemble()
    # 相同证据、不同字典键序 → 同一哈希
    r2 = _assemble(context=make_context(skillId="SP-15",
                                        skillVersion="2.0.0-candidate",
                                        permissionDecisionId="PD-001",
                                        productKnowledgeSnapshotRef="PKS-001",
                                        ruleExecutionRef="RULE-RUN-001",
                                        customerFactSnapshotId="CFS-001"))
    assert r1.bundle.contentHash == r2.bundle.contentHash


def test_content_hash_changes_when_evidence_changes():
    r1 = _assemble()
    r2 = _assemble(context=make_context(customerFactSnapshotId="CFS-OTHER"))
    assert r1.bundle.contentHash != r2.bundle.contentHash


def test_content_hash_excludes_volatile_metadata():
    # 仅 traceId/generatedAt/evidenceBundleId 变化 → 证据内容哈希不变
    r1 = _assemble(evidence_bundle_id="EVB-001", trace_id="TRACE-001",
                   generated_at="2026-08-31T09:00:00+08:00")
    r2 = _assemble(evidence_bundle_id="EVB-999", trace_id="TRACE-999",
                   generated_at="2026-09-01T10:00:00+08:00")
    assert r1.bundle.contentHash == r2.bundle.contentHash
    assert r1.bundle.evidenceBundleId != r2.bundle.evidenceBundleId


# ---------------------------------------------------------------------------
# 与 eligibility.py 的集成链路
# ---------------------------------------------------------------------------
def test_integration_with_eligibility_module():
    from dkws.application.product_recommendation.eligibility import (
        HardEligibilityRuleExecutor,
        ProductUniverseResolver,
    )

    product = {
        "productId": "PROD-WC-001", "productVersion": "2.2",
        "name": "流动资金贷款", "status": "ACTIVE",
        "effectiveFrom": "2026-01-01", "effectiveTo": "2026-12-31",
        "institutions": [INSTITUTION], "owner": "FIN-OWNER-01",
        "source": "src://product-cards/PROD-WC-001",
        "evidenceRefs": ["EV-PROD-CARD-001"],
        "admissionCriteria": {"customerTypes": ["CORPORATE"]},
    }
    facts = {
        "customerType": "CORPORATE", "industry": "MANUFACTURING",
        "region": "CN", "useOfFunds": "WORKING_CAPITAL",
    }
    resolution = ProductUniverseResolver().resolve([product], as_of=AS_OF,
                                                   institution=INSTITUTION)
    exec_result = HardEligibilityRuleExecutor().execute(
        resolution.universe, facts, as_of=AS_OF)

    result = _assemble(
        eligibility_results=[r.to_dict() for r in exec_result.results],
        fit_results=make_fit_results(),
    )
    assert result.ok
    # 理由的 factRefs 由 eligibility inputFactRefs 兜底提供
    assert result.bundle.reasonEvidence[0].factRefs
    assert result.bundle.reasonEvidence[0].knowledgeRefs


# ---------------------------------------------------------------------------
# unknowns / conflicts 聚合与 to_dict 形状
# ---------------------------------------------------------------------------
def test_aggregates_unknowns_and_conflicts():
    result = _assemble(
        eligibility_results=[{
            "productId": "PROD-WC-001", "productVersion": "2.2",
            "eligibility": "REVIEW_REQUIRED",
            "ruleResults": [],
            "unknowns": [{"question": "缺少客户行业事实"}],
            "reviewRequirements": [{"reason": "客户已持有互斥产品，需复核"}],
        }],
        fit_results=[{
            "productId": "PROD-WC-001", "productVersion": "2.2",
            "materialGaps": ["尚未取得最新审计报告"],
            "recommendationReasons": [{
                "text": "覆盖营运资金需求",
                "factRefs": ["FACT-CUST-001"],
                "knowledgeRefs": ["EV-PROD-001"],
            }],
        }],
        portfolio_candidates=[{
            "portfolioId": "PORT-001",
            "primaryProduct": {"productId": "PROD-WC-001", "productVersion": "2.2",
                               "role": "PRIMARY", "servedNeedId": "NEED-001"},
            "conflicts": [{"productA": "PROD-WC-001", "productB": "PROD-CR-001",
                           "kind": "MUTUAL_EXCLUSION"}],
        }],
        need_profile=[{"needId": "NEED-002", "needStatus": "CONFLICT"}],
    )
    assert result.ok
    assert "缺少客户行业事实" in result.bundle.unknowns
    assert "尚未取得最新审计报告" in result.bundle.unknowns
    assert "客户已持有互斥产品，需复核" in result.bundle.conflicts
    assert "PROD-WC-001×PROD-CR-001:MUTUAL_EXCLUSION" in result.bundle.conflicts
    assert "NEED_CONFLICT:NEED-002" in result.bundle.conflicts


def test_to_dict_shape():
    result = _assemble()
    assert result.ok
    d = result.to_dict()
    assert d["failClosed"] is False
    assert d["missing"] == []
    assert d["bundle"]["evidenceBundleId"] == "EVB-001"
    assert d["bundle"]["contentHash"].startswith("sha256:")
    assert set(d["bundle"].keys()) == {
        "schemaVersion", "evidenceBundleId", "customerFactSnapshotId",
        "productKnowledgeSnapshotRef", "ruleExecutionRef", "skillId",
        "skillVersion", "permissionDecisionId", "factRefs", "knowledgeRefs",
        "reasonEvidence", "unknowns", "conflicts", "contentHash", "traceId",
        "generatedAt"}
