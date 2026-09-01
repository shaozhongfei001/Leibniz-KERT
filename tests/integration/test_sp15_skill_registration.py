"""WP6-2：SP-15 Skill 平台注册集成测试。

状态块（CANDIDATE 交付）：
STATUS=CANDIDATE / FROZEN=NO / IMPLEMENTED=NO

覆盖（对齐派工步骤 4）：
- ``GET /api/skill/health`` 列出 SP-15（skillId=SP-15、version=2.0.0-candidate）；
- 进程内 TestClient 调 ``POST /api/skill/execute``，传 skillId=SP-15 + 最小合法
  ``request.context`` → ``status=ok`` 且 ``data.result`` 含 ProductRecommendationResult
  8 个必填字段 + 6 个关键数组；
- 缺输入 → ``skill_error`` + KERT_* 错误码（KERT_CONTEXT_INSUFFICIENT）。

附带证明（非派工硬性要求，用于自证流水线非空转）：
- 注入 ACTIVE 产品卡 + 客户事实快照 → 六组件端到端产出非空
  eligibilityResults/fitResults/portfolioCandidates（证明 executor 真实接入三段式流水线，
  而非返回空壳）。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

SRC = Path(__file__).resolve().parent.parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from dkws.api.server import create_app
from dkws.application.skills import SkillExecutionService

# 契约 vNext §3.1 的最小合法 request.context（含三快照引用 + 权限决策 + 激活合同）
SP15_MINIMAL_CONTEXT = {
    "runId": "REC-20260831-0001",
    "schemaVersion": "1.0.0",
    "customerId": "CUST-001",
    "needVersionIds": ["NEEDV-001"],
    "recommendationObjective": "补充流动资金与跨境结算方案",
    "requestedProductDomains": ["FINANCING", "SETTLEMENT"],
    "asOf": "2026-08-31T09:00:00+08:00",
    "customerFactSnapshotId": "CFS-20260831-0001",
    "productKnowledgeSnapshotRef": "PKS-20260831-0001",
    "ruleBundleRef": "RB-20260831-0001",
    "permissionDecisionId": "PERM-20260831-0001",
}

# recommendation-result.schema.json "required" 的 8 个必填字段
REQUIRED_RESULT_FIELDS = (
    "schemaVersion", "runId", "productKnowledgeSnapshotRef", "ruleExecutionRef",
    "evidenceBundleId", "contentHash", "traceId", "generatedAt",
)
# 契约 §4.1 的 6 个关键数组
KEY_RESULT_ARRAYS = (
    "eligibilityResults", "fitResults", "portfolioCandidates",
    "needProfile", "unknowns", "conflicts",
)


@pytest.fixture
def client(ws):
    """进程内 TestClient（create_app 注入工作区 → SP-15 注册）。"""
    app = create_app(ws)
    return TestClient(app)


def _active_product() -> dict:
    """构造一张 ACTIVE 产品卡（供注入 productKnowledgeSnapshot，证明流水线真实产出）。"""
    return {
        "productId": "PROD-WC-001", "productVersion": "2.2", "name": "流动资金贷款",
        "productFamily": "FINANCING", "status": "ACTIVE",
        "effectiveFrom": "2026-01-01", "effectiveTo": "2026-12-31",
        "institutions": ["BRANCH-SH-001"], "owner": "FIN-OWNER-01",
        "source": "src://product-cards/PROD-WC-001",
        "evidenceRefs": ["EV-PROD-CARD-001"],
        "capabilities": ["WORKING_CAPITAL_LOAN"],
        "admissionCriteria": {
            "customerTypes": ["CORPORATE"], "minScale": "MEDIUM",
            "minRating": "A", "requiredAccountRelationship": "SETTLEMENT_ACCOUNT",
        },
        "prerequisites": ["PROD-DEPOSIT-001"], "mutualExclusions": [],
        "requiredMaterials": ["FINANCIAL_STATEMENT"],
        "salesBoundary": {"mandatoryExpert": False, "noCommitment": ["不得承诺利率"]},
    }


def _active_facts() -> dict:
    """构造满足准入的客户事实快照（含需求能力信号，供匹配段产出推荐理由）。"""
    return {
        "customerId": "CUST-001", "industry": "MANUFACTURING", "region": "CN",
        "useOfFunds": "WORKING_CAPITAL", "customerType": "CORPORATE",
        "scale": "MEDIUM", "rating": "AA",
        "accountRelationships": ["SETTLEMENT_ACCOUNT"],
        "heldProducts": ["PROD-DEPOSIT-001"],
        "materials": ["FINANCIAL_STATEMENT"],
        "needs": [{
            "needId": "NEED-001", "needStatus": "VERIFIED_FACT",
            "requiredCapabilities": ["WORKING_CAPITAL_LOAN"],
            "evidenceRefs": ["EV-NEED-001"],
        }],
    }


class TestSp15Registration:
    def test_health_lists_sp15(self, client):
        r = client.get("/api/skill/health")
        assert r.status_code == 200
        skills = {s["skillId"]: s for s in r.json()["skills"]}
        assert "SP-15" in skills, f"health 未列出 SP-15，可用: {sorted(skills)}"
        assert skills["SP-15"]["version"] == "2.0.0-candidate"
        assert skills["SP-15"]["name"]

    def test_registry_includes_sp15_with_workspace(self, ws):
        reg = {s.skill_id: s for s in SkillExecutionService(ws).registry()}
        assert "SP-15" in reg
        assert reg["SP-15"].version == "2.0.0-candidate"

    def test_execute_sp15_ok_minimal_context(self, client):
        r = client.post("/api/skill/execute", json={
            "skillId": "SP-15",
            "requestId": "REC-20260831-0001",
            "request": {"context": SP15_MINIMAL_CONTEXT},
        })
        assert r.status_code == 200, r.text[:300]
        body = r.json()
        assert body["status"] == "ok", body.get("errors")
        assert body["errors"] == []

        data = body["data"]
        assert data["skillId"] == "SP-15"
        assert "reportUrl" in data

        result = data["result"]
        for field in REQUIRED_RESULT_FIELDS:
            assert field in result, f"缺必填字段 {field}"
            assert result[field] not in (None, ""), f"必填字段为空 {field}"
        assert result["skillId"] == "SP-15"
        assert result["skillVersion"] == "2.0.0-candidate"
        assert result["contentHash"].startswith("sha256:")
        for arr in KEY_RESULT_ARRAYS:
            assert isinstance(result[arr], list), f"{arr} 非数组: {type(result[arr])}"

    def test_execute_sp15_missing_context_returns_kert_error(self, client):
        r = client.post("/api/skill/execute", json={
            "skillId": "SP-15", "requestId": "REC-MISSING-1", "request": {}})
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "skill_error"
        # fail-closed：失败时无 result（服务端统一追加 reportUrl，不影响失败语义）
        assert "result" not in body["data"]
        codes = {e.get("code") for e in body["errors"]}
        assert "KERT_CONTEXT_INSUFFICIENT" in codes, f"错误码缺失: {codes}"

    def test_execute_sp15_pipeline_produces_non_empty_result(self, client):
        """注入 ACTIVE 产品 + 客户事实 → 六组件端到端产出非空结果（自证流水线非空转）。"""
        ctx = dict(SP15_MINIMAL_CONTEXT)
        ctx["runId"] = "REC-20260831-0002"
        ctx["institution"] = "BRANCH-SH-001"
        ctx["productKnowledgeSnapshot"] = [_active_product()]
        ctx["customerFactSnapshot"] = {"facts": _active_facts()}

        r = client.post("/api/skill/execute", json={
            "skillId": "SP-15", "requestId": "REC-20260831-0002",
            "request": {"context": ctx},
        })
        assert r.status_code == 200, r.text[:300]
        body = r.json()
        assert body["status"] == "ok", body.get("errors")

        result = body["data"]["result"]
        assert result["eligibilityResults"], "eligibilityResults 应为非空"
        assert result["eligibilityResults"][0]["eligibility"] == "ELIGIBLE"
        assert result["fitResults"], "fitResults 应为非空"
        assert result["fitResults"][0]["fitScore"] is not None
        assert result["portfolioCandidates"], "portfolioCandidates 应为非空"
        assert result["portfolioCandidates"][0]["primaryProduct"]["productId"] == "PROD-WC-001"
