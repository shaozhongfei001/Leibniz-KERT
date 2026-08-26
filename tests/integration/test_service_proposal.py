"""SP-20 服务建议书（v1.4）测试：同步/异步/双版本/规则/报告。"""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from dkws.api.server import create_app
from dkws.application.skills import SkillExecutionService

CTX = {
    "schemaVersion": "1.0.0",
    "customerId": "CUST-CORP-0001",
    "customerName": "华东精工装备集团有限公司",
    "industry": "制造业-装备制造",
    "engagementPhase": "FIRST_CONTACT",
    "journeyId": "J-1", "operatingCaseId": "OC-1", "roundNumber": 1,
    "enterpriseData": {
        "basicInfo": {"registeredCapital": "5亿", "establishedDate": "2005-03-15",
                      "legalRepresentative": "张伟", "businessScope": "精密加工、智能装备",
                      "registeredAddress": "杭州市", "companyType": "集团"},
        "financialSummary": {"revenue": [{"year": "2023", "value": 850000000}],
                             "netProfit": [{"year": "2023", "value": 80000000}]},
        "creditFacility": {"totalApproved": 80000, "totalUsed": 60000,
                           "products": [{"productName": "流贷", "approvedAmount": 80000,
                                         "usedAmount": 60000}]},
        "transactionSummary": {"monthlyAvgVolume": 12000},
    },
    "publicData": {}, "interactionHistory": [], "interactionMemory": [], "evidence": [],
    "proposalContext": {"proposalType": "INITIAL", "gateState": {"passed": ["G0"], "current": "G1"}},
}


@pytest.fixture
def svc():
    return SkillExecutionService()


class TestSp20Sync:
    def test_execute_success(self, svc):
        r = svc.execute("SP-20", "sp20-t-1", {"context": CTX})
        assert r.status == "ok", r.errors
        res = r.data["result"]
        assert res["skillId"] == "SP-20"
        assert res["status"] in ("SUCCESS", "PARTIAL")
        # 8 章都有引用
        assert {c["chapterRef"] for c in res["citations"]} == \
            {f"CH{i:02d}" for i in range(1, 9)}
        assert res["content"]["internalVersion"]["factLabels"]
        # 对客版仅 F/A：C 标签断言不得出现在对客版
        custv = res["content"]["customerVersion"]
        assert custv is not None
        c_claims = [c["claim"] for c in res["citations"] if c["factLabel"] == "C"]
        for claim in c_claims:
            assert claim not in custv["content"], f"对客版泄漏 C 断言: {claim}"
        assert custv["releaseBlockedUntil"] == ["G1", "G2", "G3"]
        # 规则校验
        assert isinstance(res["ruleViolations"], list)
        # 闸门建议
        assert res["gateRecommendations"]["currentGate"] == "G1"

    def test_missing_context_fail_closed(self, svc):
        r = svc.execute("SP-20", "sp20-t-2", {"customerId": "CUST-CORP-0001"})
        assert r.status == "skill_error"
        assert r.errors[0]["code"] == "SKILL_EXECUTION_FAILED"

    def test_registered(self, svc):
        reg = {s.skill_id for s in svc.registry()}
        assert "SP-20" in reg

    def test_industry_mapping(self, svc):
        from dkws.application.service_proposal import ServiceProposalExecutor
        ex = ServiceProposalExecutor()
        assert ex._map_industry("信息技术-软件开发") == "TECHNOLOGY"
        assert ex._map_industry("制造业-装备制造") == "MANUFACTURING"
        assert ex._map_industry("未知行业") == "OTHER"


class TestSp20Async:
    def test_async_job_flow(self, ws):
        app = create_app(ws)
        with TestClient(app) as client:
            resp = client.post("/api/skill/execute", json={
                "skillId": "SP-20", "requestId": "sp20-a-1",
                "request": {"context": CTX}, "async": True,
            })
            assert resp.status_code == 202
            body = resp.json()
            assert body["status"] == "PENDING" and body["jobId"]
            job_id = body["jobId"]
            # 轮询完成（任务状态在响应 data 内）
            result = None
            for _ in range(60):
                time.sleep(0.5)
                st = client.get(f"/v1/jobs/{job_id}").json()["data"]
                if st.get("status") in ("COMPLETED", "FAILED"):
                    result = st
                    break
            assert result is not None and result["status"] == "COMPLETED", result
            assert "skill_result" in result
            assert result["skill_result"]["status"] == "ok"

    def test_async_report_url(self, ws):
        app = create_app(ws)
        with TestClient(app) as client:
            r = client.post("/api/skill/execute", json={
                "skillId": "SP-20", "requestId": "sp20-a-2",
                "request": {"context": CTX}, "async": True,
            })
            job_id = r.json()["jobId"]
            for _ in range(60):
                time.sleep(0.5)
                st = client.get(f"/v1/jobs/{job_id}").json()["data"]
                if st.get("status") == "COMPLETED":
                    break
            payload = st["skill_result"]
            assert payload["data"]["reportUrl"].startswith("/api/skill/report/")
            # 报告页可渲染（SP-20 定制模板）
            rid = payload["requestId"]
            rep = client.get(f"/api/skill/report/{rid}")
            assert rep.status_code == 200
            assert "对公客户服务建议书" in rep.text
            assert "内部版" in rep.text and "对客版" in rep.text


class TestGates:
    def test_gate_checklist_asset(self, ws):
        app = create_app(ws)
        with TestClient(app) as client:
            r = client.get("/api/skill/gates/CUST-CORP-0001")
            assert r.status_code == 200
            gates = r.json()["gates"]
            assert [g["gateId"] for g in gates] == [f"GATE-BIZ-G{i}" for i in range(6)]
            g1 = gates[1]
            assert g1["must"] and g1["forbidden"]

    def test_gate_audit_mirror(self, ws):
        app = create_app(ws)
        with TestClient(app) as client:
            r = client.post("/api/skill/gates/audit", json={
                "customerId": "CUST-CORP-0001", "gate": "G1", "decision": "PASSED",
                "decidedBy": "RM-ZW-001", "reason": "客户核验完成",
            })
            assert r.status_code == 200
            assert r.json()["recorded"] is True
            from pathlib import Path
            log = Path(ws) / "90_control" / "audit" / "gates.jsonl"
            assert log.is_file()
            assert "G1" in log.read_text(encoding="utf-8")

    def test_update_route_map_first(self, svc):
        """UPDATE 类型：routeMode=MAP_FIRST，previousVersion 注入。"""
        ctx = {**CTX, "proposalContext": {
            "proposalType": "UPDATE",
            "gateState": {"passed": ["G0", "G1", "G2", "G3"], "current": "G4"},
            "previousVersion": "# 上一版建议书\n\n（上一版内容）",
        }}
        r = svc.execute("SP-20", "sp20-upd-1", {"context": ctx})
        assert r.status == "ok"
        trace = [t for t in r.assembly_trace if t.get("phase") == "route"]
        assert any("MAP_FIRST" in t.get("message", "") for t in trace)
        res = r.data["result"]
        # G1-G3 已过 → 对客版不再 blocked
        custv = res["content"]["customerVersion"]
        assert custv is not None
        assert custv.get("releaseBlockedUntil") == []
