"""WP6-3：SP-15 契约符合性测试（对组件输出与契约样例做只读符合性断言）。

状态块（CANDIDATE 交付）：
STATUS=CANDIDATE / FROZEN=NO / IMPLEMENTED=NO / REAL_E2E_PASS=NO

只读依赖（本测试不改动、不新增任何生产代码）：
- KERT skills/product-recommendation/contracts/recommendation-result.md（最小结构 + 8 必填字段）
- KERT skills/product-recommendation/contracts/examples/{valid,invalid}-sp15-result.json（正/反样例）
- KERT specs/dkws-openapi-v1.yaml（8 个 KERT_* 错误码登记）
- GITS specs/product-recommendation/{recommendation-result,eligibility-result,
  product-fit-result,portfolio-candidate}.schema.json（仅读，用于 jsonschema 校验）
- 已验收组件：eligibility / matcher / ranker / evidence / need_profile / portfolio

范围说明（如实标注，不伪装通过）：
1. `sp15_skill.py`（三段式总装编排器）尚未落地，本测试针对**各组件输出形状**做符合性断言，
   并对契约样例做结构断言（依赖：总装器落地后需追加端到端 data.result 全量断言）。
2. `KERT_PERMISSION_DENIED` 的生产点（RecommendationInputValidator 步骤 0 权限决策门禁）
   在基线组件中尚未接线；`KERT_EVIDENCE_INCOMPLETE` 在 evidence.py 中以内部 MISSING_* 缺项码
   表达（fail-closed 不产出 bundle），KERT→GITS 语义映射为 KERT_EVIDENCE_INCOMPLETE。两者均
   按「常量已定义 + openapi 已登记 + 语义路径」断言，并在用例内标注依赖。
3. 契约样例 examples/*.json 的嵌套 fitResults/portfolioCandidates 未含 schemaVersion（样例
   自身细节，不在本任务 8 必填字段/闭集/ruleResults/INV-02 检查清单内），故对样例仅做
   检查清单内的结构断言；对**组件输出**则做完整 jsonschema 校验（组件 to_dict 均含 schemaVersion）。
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest

from dkws.application.product_recommendation.eligibility import (
    ELIGIBILITY_CLOSED_SET,
    KERT_CONTEXT_INSUFFICIENT,
    KERT_EVIDENCE_INCOMPLETE,
    KERT_PERMISSION_DENIED,
    KERT_PRODUCT_KNOWLEDGE_STALE,
    KERT_RULE_VERSION_MISSING,
    RULE_CATALOG,
    HardEligibilityRuleExecutor,
    ProductUniverseResolver,
)
from dkws.application.product_recommendation.evidence import (
    MISSING_SNAPSHOT_FIELD,
    EvidenceBundleAssembler,
)
from dkws.application.product_recommendation.matcher import NeedCapabilityMatcher
from dkws.application.product_recommendation.ranker import CandidateRanker

# ---------------------------------------------------------------------------
# 常量与路径
# ---------------------------------------------------------------------------
KERT_ROOT = Path(__file__).resolve().parents[2]  # tests/integration -> repo root
EXAMPLES_DIR = KERT_ROOT / "skills" / "product-recommendation" / "contracts" / "examples"
OPENAPI_SPEC = KERT_ROOT / "specs" / "dkws-openapi-v1.yaml"

# 8 必填字段（对齐 GITS recommendation-result.schema.json `required` 与 contracts §4.1）
REQUIRED_RESULT_FIELDS = (
    "schemaVersion",
    "runId",
    "productKnowledgeSnapshotRef",
    "ruleExecutionRef",
    "evidenceBundleId",
    "contentHash",
    "traceId",
    "generatedAt",
)

# ruleResults 完整字段（对齐 eligibility-result.schema.json RuleResult + contracts §4.1）
RULE_RESULT_FIELDS = ("ruleId", "ruleVersion", "result", "reasonCode",
                      "inputFactRefs", "evidenceRefs")

# SP-15 专属 8 个 KERT_* 错误码（对齐 dkws-openapi-v1.yaml ErrorDetail.code）
ALL_KERT_ERROR_CODES = {
    "KERT_PERMISSION_DENIED",
    "KERT_CONTEXT_INSUFFICIENT",
    "KERT_PRODUCT_KNOWLEDGE_STALE",
    "KERT_RULE_VERSION_MISSING",
    "KERT_EXECUTION_TIMEOUT",
    "KERT_CONTRACT_MISMATCH",
    "KERT_EVIDENCE_INCOMPLETE",
    "KERT_INTERNAL_ERROR",
}

# 本任务派工明确要求覆盖的 5 个错误码
REQUIRED_ERROR_CODES = {
    "KERT_CONTEXT_INSUFFICIENT",
    "KERT_PERMISSION_DENIED",
    "KERT_PRODUCT_KNOWLEDGE_STALE",
    "KERT_RULE_VERSION_MISSING",
    "KERT_EVIDENCE_INCOMPLETE",
}

AS_OF = "2026-08-31"
INSTITUTION = "BRANCH-SH-001"


# ---------------------------------------------------------------------------
# 夹具加载与通用工具
# ---------------------------------------------------------------------------
def _load_example(name: str) -> dict:
    path = EXAMPLES_DIR / name
    assert path.is_file(), f"契约样例缺失：{path}"
    return json.loads(path.read_text(encoding="utf-8"))


def _registered_kert_codes() -> set[str]:
    assert OPENAPI_SPEC.is_file(), f"openapi 契约缺失：{OPENAPI_SPEC}"
    text = OPENAPI_SPEC.read_text(encoding="utf-8")
    return set(re.findall(r"\bKERT_[A-Z_]+\b", text))


def _inv02_violations(result: dict) -> list[str]:
    """INV-02 检查器：非 ELIGIBLE 产品的 fitScore 必须为 null（/缺省）。返回违规清单。"""
    elig = {e.get("productId"): e.get("eligibility")
            for e in result.get("eligibilityResults") or []}
    violations: list[str] = []
    for fr in result.get("fitResults") or []:
        status = elig.get(fr.get("productId"), "UNKNOWN")
        score = fr.get("fitScore")
        if status != "ELIGIBLE" and score is not None:
            violations.append(f"{fr.get('productId')}:{status}:fitScore={score}")
    return violations


def _make_product(pid: str = "PROD-WC-001", **overrides) -> dict:
    base = {
        "productId": pid,
        "productVersion": "2.2",
        "name": "流动资金贷款",
        "status": "ACTIVE",
        "effectiveFrom": "2026-01-01",
        "effectiveTo": "2026-12-31",
        "institutions": [INSTITUTION],
        "owner": "FIN-OWNER-01",
        "source": f"src://product-cards/{pid}",
        "evidenceRefs": [f"EV-{pid}"],
        "capabilities": ["WORKING_CAPITAL_LOAN"],
    }
    base.update(overrides)
    return base


def _make_facts(**overrides) -> dict:
    base = {
        "customerId": "CUST-001",
        "industry": "MANUFACTURING",
        "region": "CN",
        "useOfFunds": "WORKING_CAPITAL",
        "customerType": "CORPORATE",
        "scale": "MEDIUM",
        "rating": "AA",
        "accountRelationships": ["SETTLEMENT_ACCOUNT"],
        "heldProducts": [],
        "materials": [],
    }
    base.update(overrides)
    return base


def _make_needs() -> list[dict]:
    return [{
        "needId": "NEED-001",
        "needStatus": "VERIFIED_FACT",
        "requiredCapabilities": ["WORKING_CAPITAL_LOAN"],
        "evidenceRefs": ["EV-NEED-001"],
    }]


# 四种状态（每个 product 独立跑一次 resolver+executor，得到单一 EligibilityResult）
def _four_state_eligibility() -> tuple[list[dict], list]:
    cases = [
        # ELIGIBLE
        (_make_product("P-ELIGIBLE"), _make_facts()),
        # INELIGIBLE（监管禁止）
        (_make_product("P-INELIGIBLE", prohibitedIndustries=["GAMBLING"]),
         _make_facts(industry="GAMBLING")),
        # UNKNOWN（缺行业事实）
        (_make_product("P-UNKNOWN", prohibitedIndustries=["GAMBLING"]),
         _make_facts(industry=None)),
        # REVIEW_REQUIRED（互斥冲突）
        (_make_product("P-REVIEW", mutualExclusions=["PROD-CR-001"]),
         _make_facts(heldProducts=["PROD-CR-001"])),
    ]
    resolver = ProductUniverseResolver()
    executor = HardEligibilityRuleExecutor()
    products: list[dict] = []
    elig = []
    for product, facts in cases:
        resolution = resolver.resolve([product], as_of=AS_OF, institution=INSTITUTION)
        assert not resolution.fail_closed, resolution.fail_closed_reasons
        products.append(resolution.universe[0])
        elig.append(executor.execute(resolution.universe, facts, as_of=AS_OF).results[0])
    return products, elig


# ---------------------------------------------------------------------------
# 1) 8 必填字段
# ---------------------------------------------------------------------------
def test_required_eight_fields_present_in_valid_example():
    example = _load_example("valid-sp15-result.json")
    for field in REQUIRED_RESULT_FIELDS:
        assert field in example, f"必填字段缺失：{field}"
        assert example[field] not in (None, ""), f"必填字段为空：{field}"
    assert example["schemaVersion"] == "1.0.0"
    assert example["skillId"] == "SP-15"
    assert example["contentHash"].startswith("sha256:")


def test_required_eight_fields_closed_set_matches_contract():
    assert set(REQUIRED_RESULT_FIELDS) == {
        "schemaVersion", "runId", "productKnowledgeSnapshotRef",
        "ruleExecutionRef", "evidenceBundleId", "contentHash", "traceId", "generatedAt",
    }


# ---------------------------------------------------------------------------
# 2) eligibilityResults 四态闭集 + ruleResults 完整（契约样例）
# ---------------------------------------------------------------------------
def test_valid_example_eligibility_closed_set_and_rule_results_complete():
    example = _load_example("valid-sp15-result.json")
    er = example["eligibilityResults"][0]
    assert er["eligibility"] in ELIGIBILITY_CLOSED_SET
    assert er["eligibility"] == "ELIGIBLE"
    for rr in er["ruleResults"]:
        assert set(rr.keys()) == set(RULE_RESULT_FIELDS), f"ruleResults 字段不完整：{rr.keys()}"
        for f in ("ruleId", "ruleVersion", "result", "reasonCode"):
            assert rr[f] not in (None, ""), f"ruleResults.{f} 为空"
        assert isinstance(rr["inputFactRefs"], list) and rr["inputFactRefs"]
        assert isinstance(rr["evidenceRefs"], list) and rr["evidenceRefs"]


def test_eligibility_closed_set_exact_four_states():
    assert set(ELIGIBILITY_CLOSED_SET) == {"ELIGIBLE", "INELIGIBLE", "UNKNOWN", "REVIEW_REQUIRED"}


# ---------------------------------------------------------------------------
# 3) 组件输出：四态闭集全覆盖 + ruleResults 完整
# ---------------------------------------------------------------------------
def test_component_output_covers_all_four_eligibility_states():
    _, elig = _four_state_eligibility()
    assert {e.eligibility for e in elig} == set(ELIGIBILITY_CLOSED_SET)


def test_component_rule_results_complete_across_all_states():
    _, elig = _four_state_eligibility()
    for er in elig:
        assert er.ruleResults, f"{er.productId} 缺少 ruleResults"
        for rr in er.ruleResults:
            d = rr.to_dict()
            assert set(d.keys()) == set(RULE_RESULT_FIELDS), f"字段不完整：{d.keys()}"
            assert d["ruleId"] and d["ruleVersion"] and d["result"] and d["reasonCode"]
            assert d["result"] in ("PASS", "FAIL", "UNKNOWN", "REVIEW_REQUIRED")
            assert isinstance(d["inputFactRefs"], list) and d["inputFactRefs"]
            assert isinstance(d["evidenceRefs"], list) and d["evidenceRefs"]


# ---------------------------------------------------------------------------
# 4) INV-02：仅 ELIGIBLE 有 fitScore，其余为 null
# ---------------------------------------------------------------------------
def test_inv02_only_eligible_has_fit_score_end_to_end():
    products, elig = _four_state_eligibility()
    fit_results = NeedCapabilityMatcher().match(
        products, _make_needs(), {}, eligibility=elig)
    ranked = CandidateRanker().rank(fit_results)

    by_pid = {fr.productId: fr for fr in ranked}
    # ELIGIBLE：有数值 fitScore 与 rank
    eligible = by_pid["P-ELIGIBLE"]
    assert eligible.eligibility == "ELIGIBLE"
    assert isinstance(eligible.fitScore, float)
    assert eligible.rank == 1
    # 其余三态：fitScore / rank 均为 None
    for pid in ("P-INELIGIBLE", "P-UNKNOWN", "P-REVIEW"):
        fr = by_pid[pid]
        assert fr.fitScore is None, f"{pid} 应 fitScore=None，实际 {fr.fitScore}"
        assert fr.rank is None


def test_inv02_ranker_forces_non_eligible_fit_score_null():
    from dkws.application.product_recommendation.matcher import FitResult

    frs = [
        FitResult(productId="P-A", productVersion="2.2", eligibility="ELIGIBLE",
                  dimensionMatches=[]),
        FitResult(productId="P-B", productVersion="2.2", eligibility="INELIGIBLE"),
        FitResult(productId="P-C", productVersion="2.2", eligibility="UNKNOWN"),
        FitResult(productId="P-D", productVersion="2.2", eligibility="REVIEW_REQUIRED"),
    ]
    ranked = CandidateRanker().rank(frs)
    for fr in ranked:
        if fr.eligibility == "ELIGIBLE":
            assert fr.fitScore is not None
        else:
            assert fr.fitScore is None and fr.rank is None


def test_invalid_example_violates_inv02_detected():
    example = _load_example("invalid-sp15-ineligible-with-score.json")
    # 反例：INELIGIBLE 产品在 fitResults 中 fitScore 非 null → INV-02 违规
    assert _inv02_violations(example), "反例应命中 INV-02 违规"


def test_valid_example_satisfies_inv02():
    example = _load_example("valid-sp15-result.json")
    assert _inv02_violations(example) == []


# ---------------------------------------------------------------------------
# 5) EvidenceBundle 必填覆盖 100%（缺失→不产出） + contentHash 确定性
# ---------------------------------------------------------------------------
def _make_evidence_context(**overrides) -> dict:
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


def _make_eligibility_results() -> list[dict]:
    return [{
        "productId": "P-ELIGIBLE", "productVersion": "2.2", "eligibility": "ELIGIBLE",
        "ruleResults": [{
            "ruleId": "PR-ELIG-001", "ruleVersion": "1.0.0-candidate", "result": "PASS",
            "reasonCode": "CUSTOMER_TYPE_ALLOWED",
            "inputFactRefs": ["FACT-CUST-001"], "evidenceRefs": ["EV-P-ELIGIBLE"],
        }],
        "unknowns": [], "reviewRequirements": [],
    }]


def _make_fit_results() -> list[dict]:
    return [{
        "productId": "P-ELIGIBLE", "productVersion": "2.2", "fitScore": 0.82,
        "recommendationReasons": [{
            "text": "流动资金贷款覆盖补充营运资金需求",
            "evidenceRefs": ["EV-NEED-001", "EV-P-ELIGIBLE"], "sourceType": "FACT",
        }],
    }]


def test_evidence_bundle_full_coverage_produces():
    result = EvidenceBundleAssembler().assemble(
        context=_make_evidence_context(),
        eligibility_results=_make_eligibility_results(),
        fit_results=_make_fit_results(),
        evidence_bundle_id="EVB-001", trace_id="TRACE-001",
        generated_at="2026-08-31T09:00:00+08:00",
    )
    assert result.ok and result.fail_closed is False
    assert result.missing == []
    assert result.bundle is not None
    # 必填快照/身份字段全覆盖（§6 必含项）
    assert result.bundle.customerFactSnapshotId == "CFS-001"
    assert result.bundle.productKnowledgeSnapshotRef == "PKS-001"
    assert result.bundle.ruleExecutionRef == "RULE-RUN-001"
    assert result.bundle.skillId == "SP-15"
    assert result.bundle.skillVersion == "2.0.0-candidate"
    assert result.bundle.permissionDecisionId == "PD-001"
    assert result.bundle.contentHash.startswith("sha256:")


def test_evidence_bundle_missing_required_not_produced():
    # 任一必填快照缺失 → fail-closed 不产出（§6 缺失 → KERT_EVIDENCE_INCOMPLETE 语义）
    result = EvidenceBundleAssembler().assemble(
        context=_make_evidence_context(customerFactSnapshotId=""),
        eligibility_results=_make_eligibility_results(),
        fit_results=_make_fit_results(),
    )
    assert not result.ok and result.fail_closed
    assert result.bundle is None
    assert any(m["code"] == MISSING_SNAPSHOT_FIELD
               and m["field"] == "customerFactSnapshotId" for m in result.missing)


def test_content_hash_deterministic_same_input():
    a = EvidenceBundleAssembler().assemble(
        context=_make_evidence_context(), eligibility_results=_make_eligibility_results(),
        fit_results=_make_fit_results(), evidence_bundle_id="EVB-001", trace_id="TRACE-001",
        generated_at="2026-08-31T09:00:00+08:00")
    b = EvidenceBundleAssembler().assemble(
        context=_make_evidence_context(), eligibility_results=_make_eligibility_results(),
        fit_results=_make_fit_results(), evidence_bundle_id="EVB-001", trace_id="TRACE-001",
        generated_at="2026-08-31T09:00:00+08:00")
    assert a.ok and b.ok
    assert a.bundle.contentHash == b.bundle.contentHash
    assert a.bundle.contentHash.startswith("sha256:")


def test_content_hash_changes_when_evidence_changes():
    a = EvidenceBundleAssembler().assemble(
        context=_make_evidence_context(), eligibility_results=_make_eligibility_results(),
        fit_results=_make_fit_results())
    b = EvidenceBundleAssembler().assemble(
        context=_make_evidence_context(customerFactSnapshotId="CFS-OTHER"),
        eligibility_results=_make_eligibility_results(), fit_results=_make_fit_results())
    assert a.ok and b.ok
    assert a.bundle.contentHash != b.bundle.contentHash


# ---------------------------------------------------------------------------
# 6) 错误码路径（5 个派工要求码）
# ---------------------------------------------------------------------------
def test_error_code_kert_context_insufficient_path():
    product = _make_product()
    resolution = ProductUniverseResolver().resolve([product], as_of=AS_OF, institution=None)
    assert resolution.fail_closed
    codes = {r.get("errorCode") for r in resolution.fail_closed_reasons}
    assert KERT_CONTEXT_INSUFFICIENT in codes


def test_error_code_kert_product_knowledge_stale_path():
    product = _make_product(effectiveTo="2026-06-30")  # asOf=2026-08-31 已过期
    resolution = ProductUniverseResolver().resolve([product], as_of=AS_OF,
                                                   institution=INSTITUTION)
    assert resolution.fail_closed
    codes = {r.get("errorCode") for r in resolution.fail_closed_reasons}
    assert KERT_PRODUCT_KNOWLEDGE_STALE in codes


def test_error_code_kert_rule_version_missing_path():
    product = _make_product()
    resolution = ProductUniverseResolver().resolve([product], as_of=AS_OF,
                                                   institution=INSTITUTION)
    partial_bundle = {r["ruleId"]: r["ruleVersion"] for r in RULE_CATALOG
                      if r["ruleId"] != "PR-REG-001"}
    result = HardEligibilityRuleExecutor().execute(
        resolution.universe, _make_facts(), as_of=AS_OF, rule_bundle=partial_bundle)
    assert result.fail_closed
    codes = {r.get("errorCode") for r in result.fail_closed_reasons}
    assert KERT_RULE_VERSION_MISSING in codes


def test_error_code_kert_permission_denied_registered_and_constant():
    # 依赖标注：权限决策门禁（RecommendationInputValidator 步骤 0）在基线组件中尚未接线，
    # 无组件级生产点；此处按契约断言常量已定义 + openapi 已登记。
    assert KERT_PERMISSION_DENIED == "KERT_PERMISSION_DENIED"
    assert KERT_PERMISSION_DENIED in _registered_kert_codes()


def test_error_code_kert_evidence_incomplete_semantics():
    # 依赖标注：evidence.py 以内部 MISSING_* 缺项码表达「缺失→不产出」（fail-closed），
    # KERT→GITS 语义映射为 KERT_EVIDENCE_INCOMPLETE（§6）。
    assert KERT_EVIDENCE_INCOMPLETE == "KERT_EVIDENCE_INCOMPLETE"
    assert KERT_EVIDENCE_INCOMPLETE in _registered_kert_codes()
    result = EvidenceBundleAssembler().assemble(
        context=_make_evidence_context(permissionDecisionId=None),
        eligibility_results=_make_eligibility_results(), fit_results=_make_fit_results())
    assert not result.ok and result.bundle is None  # 缺失 → 不产出


def test_error_codes_registered_in_openapi_full_eight():
    registered = _registered_kert_codes()
    assert REQUIRED_ERROR_CODES <= registered
    assert registered == ALL_KERT_ERROR_CODES


def test_error_code_constants_defined_in_eligibility_module():
    for code in REQUIRED_ERROR_CODES:
        assert code in {
            KERT_PERMISSION_DENIED, KERT_CONTEXT_INSUFFICIENT,
            KERT_PRODUCT_KNOWLEDGE_STALE, KERT_RULE_VERSION_MISSING,
            KERT_EVIDENCE_INCOMPLETE,
        }, f"错误码常量未定义：{code}"


# ---------------------------------------------------------------------------
# 7) 组件输出 jsonschema 符合性（读 GITS 契约，缺失则跳过）
# ---------------------------------------------------------------------------
def _load_gits_schemas() -> dict[str, dict] | None:
    files = {
        "recommendation-result": "recommendation-result.schema.json",
        "eligibility-result": "eligibility-result.schema.json",
        "product-fit-result": "product-fit-result.schema.json",
        "portfolio-candidate": "portfolio-candidate.schema.json",
    }
    candidates: list[Path] = []
    env = os.environ.get("GITS_SPECS_DIR")
    if env:
        candidates.append(Path(env).expanduser())
    candidates.append(Path.home() / "dev" / "gits-cbanking" / "specs" / "product-recommendation")
    for d in candidates:
        if not (d / "recommendation-result.schema.json").is_file():
            continue
        return {k: json.loads((d / fname).read_text(encoding="utf-8"))
                for k, fname in files.items()}
    return None


def _draft_validator(schemas: dict, key: str):
    from jsonschema import Draft202012Validator
    from referencing import Registry, Resource

    registry = Registry().with_resources(
        [(s["$id"], Resource.from_contents(s)) for s in schemas.values()])
    return Draft202012Validator(schemas[key], registry=registry)


def test_component_outputs_validate_against_gits_schemas():
    schemas = _load_gits_schemas()
    if schemas is None:
        pytest.skip("GITS product-recommendation schemas 不存在（只读契约未就位）")

    from dkws.application.product_recommendation.portfolio import PortfolioConstraintChecker

    products, elig = _four_state_eligibility()
    fit_results = NeedCapabilityMatcher().match(products, _make_needs(), {}, eligibility=elig)
    ranked = CandidateRanker().rank(fit_results)

    eligibility_validator = _draft_validator(schemas, "eligibility-result")
    fit_validator = _draft_validator(schemas, "product-fit-result")
    portfolio_validator = _draft_validator(schemas, "portfolio-candidate")

    for er in elig:
        eligibility_validator.validate(er.to_dict())
    for fr in ranked:
        fit_validator.validate(fr.to_dict())

    # 组合：对 ELIGIBLE 产品构造合法组合候选
    pc_result = PortfolioConstraintChecker().check({
        "portfolioId": "PORT-001",
        "primaryProduct": {"productId": "P-ELIGIBLE", "productVersion": "2.2",
                           "role": "PRIMARY", "servedNeedId": "NEED-001"},
    }, eligibility=elig)
    portfolio_validator.validate(pc_result.candidate.to_dict())
