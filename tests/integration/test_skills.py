"""Skill 运行平台测试（设计文档 D1-D6 + v1.3 数据所有权）。

v1.3：GITS 只传 customerId；evidence ok/skipped 只反映 DKWS 客户知识库
（customer_knowledge 服务投影）对该客户 + KI 是否取到数。
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
from dkws.infrastructure.adapters import llm as llm_mod

# 新 GITS 请求：只带 customerId（+ 可选 visitObjective / evidenceTimestamp）
OUTREACH_REQ = {"customerId": "CUST-CORP-0001"}
MEETING_REQ = {"customerId": "CUST-CORP-0001"}
PREVISIT_REQ = {"customerId": "CUST-CORP-0001", "evidenceTimestamp": "2026-08-22T10:00:00Z"}

CUSTOMER_ID = "CUST-CORP-0001"
KI_IDS = ["KI-009", "KI-FRONT-001", "KI-FRONT-002", "KI-FRONT-003",
          "KI-FRONT-004", "KI-FRONT-005", "KI-FRONT-006"]


@pytest.fixture
def svc():
    """无工作区服务：无客户知识库 → 证据全 skipped（fail-open 不阻塞）。"""
    return SkillExecutionService()


@pytest.fixture
def ws_seeded(ws):
    """已种入 CUST-CORP-0001 客户知识（customer_knowledge 投影）的工作区。"""
    from scripts.seed_customer_knowledge import seed_customer_knowledge
    seed_customer_knowledge(ws, quiet=True)
    return ws


@pytest.fixture
def svc_ck(ws_seeded):
    """接入客户知识库 + 外部 bank-front skill 包的服务。"""
    pkgs = Path(__file__).resolve().parents[2] / "examples" / "bank-front-skills"
    return SkillExecutionService(ws_seeded, skill_packages=pkgs)


class TestRegistry:
    def test_health_lists_three_skills(self, svc):
        reg = {s.skill_id: s for s in svc.registry()}
        assert set(reg) == {
            "skill-customer-outreach-script",
            "skill-customer-meeting-script",
            "skill-customer-previsit-report",
            "SP-20",
            "SP-21",
        }
        assert all(s.version == "1.0.0" for s in reg.values())


class TestExecute:
    def test_outreach_ok_no_library(self, svc):
        r = svc.execute("skill-customer-outreach-script", "t-out-1", OUTREACH_REQ)
        assert r.status == "ok"
        assert isinstance(r.data["sections"], list) and r.data["sections"]
        assert r.data["scriptTitle"]
        assert r.assembly_trace and r.model_calls
        assert r.model_calls[0]["model"] == "deterministic_fallback"

    def test_meeting_ok_no_library(self, svc):
        r = svc.execute("skill-customer-meeting-script", "t-mtg-1", MEETING_REQ)
        assert r.status == "ok"
        assert isinstance(r.data["agenda"], list) and r.data["agenda"]

    def test_unknown_skill(self, svc):
        r = svc.execute("skill-unknown", "t-u-1", {})
        assert r.status == "skill_error"
        assert r.errors[0]["code"] == "UNKNOWN_SKILL"

    def test_idempotent_replay(self, svc):
        svc.execute("skill-customer-outreach-script", "t-idem-1", OUTREACH_REQ)
        r2 = svc.execute("skill-customer-outreach-script", "t-idem-1", OUTREACH_REQ)
        assert any(t.get("phase") == "idempotency" for t in r2.assembly_trace)

    def test_fail_closed(self, svc, monkeypatch):
        class BoomAdapter(llm_mod.LlmAdapter):
            model_id = "boom"

            def complete(self, system, user):
                raise RuntimeError("模型不可用")

        monkeypatch.setattr(llm_mod, "create_llm_adapter", lambda kind: BoomAdapter())
        r = svc.execute("skill-customer-outreach-script", "t-fail-1", OUTREACH_REQ)
        assert r.status == "skill_error"
        assert r.errors[0]["code"] == "SKILL_EXECUTION_FAILED"
        assert r.data == {}  # fail-closed：无残缺半成品

    def test_old_request_fields_ignored(self, svc):
        """v1.3 兼容：旧字段（structuredFacts/knowledgeContext）被忽略，不作为 evidence 依据。"""
        req = {"customerId": "CUST-X",
               "structuredFacts": {"profile": {"name": "虚构客户"}},
               "knowledgeContext": "虚构上下文", "supplyChainMarkdown": "虚构图谱",
               "evidenceTimestamp": "2026-08-22T10:00:00Z"}
        r = svc.execute("skill-customer-previsit-report", "t-compat-1", req)
        assert r.status == "ok"
        msgs = [t.get("message", "") for t in r.assembly_trace]
        # 不得再出现「已使用 request.knowledgeContext / structuredFacts.profile」
        assert not any("已使用 request" in m for m in msgs)
        # 无知识库 → 全部 KI skipped（不以请求字段判定 ok）
        assert all("skipped" in m for m in msgs if "KI-" in m)


@pytest.fixture
def client(ws):
    app = create_app(ws)
    return TestClient(app)


class TestApi:
    def test_health(self, client):
        r = client.get("/api/skill/health")
        assert r.status_code == 200
        body = r.json()
        ids = [s["skillId"] for s in body["skills"]]
        assert "skill-customer-outreach-script" in ids
        assert "skill-customer-meeting-script" in ids
        assert "skill-customer-previsit-report" in ids

    def test_execute(self, client):
        r = client.post("/api/skill/execute", json={
            "skillId": "skill-customer-meeting-script",
            "requestId": "api-1",
            "request": MEETING_REQ,
        })
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert "assemblyTrace" in body and "modelCalls" in body
        assert "reportUrl" in body["data"]

    def test_execute_unknown_404(self, client):
        r = client.post("/api/skill/execute", json={
            "skillId": "skill-unknown", "requestId": "api-404", "request": {}})
        assert r.status_code == 404
        assert r.json()["status"] == "skill_error"

    def test_execute_invalid_json_400(self, client):
        r = client.post("/api/skill/execute",
                        content=b"{not-json",
                        headers={"Content-Type": "application/json"})
        assert r.status_code == 422  # FastAPI 请求体校验

    def test_execute_idempotent(self, client):
        payload = {"skillId": "skill-customer-outreach-script",
                   "requestId": "api-idem", "request": OUTREACH_REQ}
        client.post("/api/skill/execute", json=payload)
        r = client.post("/api/skill/execute", json=payload)
        assert any(t.get("phase") == "idempotency"
                   for t in r.json()["assemblyTrace"])


class TestDkwsCollaboration:
    def test_dkws_skipped_without_customer_knowledge(self, ws):
        """无 customer_knowledge 投影 → dkws skipped（fail-open，不阻塞执行）。"""
        svc = SkillExecutionService(ws)
        r = svc.execute("skill-customer-outreach-script", "t-fo-1", OUTREACH_REQ)
        assert r.status == "ok"
        assert any(t.get("phase") == "dkws" and t.get("status") == "skipped"
                   for t in r.assembly_trace)


class TestAssemblyTraceKi:
    """KI 级知识组装轨迹（v1.3：ok/skipped 由 DKWS 知识库决定）。"""

    def test_previsit_ki_all_ok_from_library(self, svc_ck):
        """知识库有 CUST-CORP-0001 全部 7 条 KI → evidence 全 ok（请求只带 customerId）。"""
        r = svc_ck.execute("skill-customer-previsit-report", "tr-ki-0",
                           {"customerId": CUSTOMER_ID, "evidenceTimestamp": "2026-08-22T10:00:00Z"})
        assert r.status == "ok", (r.status, r.errors)
        ki_ok = {t.get("kiId") for t in r.assembly_trace
                 if t.get("phase") == "evidence" and t.get("status") == "ok" and t.get("kiId")}
        assert ki_ok == set(KI_IDS), ki_ok
        # dkws 阶段命中（检索路径可用）
        assert any(t.get("phase") == "dkws" and t.get("status") == "ok"
                   for t in r.assembly_trace)

    def test_previsit_sections_per_ki(self, svc_ck):
        """每个命中的 KI 出一节：heading 含 KI 编号，content 为库中原文。"""
        r = svc_ck.execute("skill-customer-previsit-report", "tr-ki-sec",
                           {"customerId": CUSTOMER_ID, "evidenceTimestamp": "2026-08-22T10:00:01Z"})
        headings = [s["heading"] for s in r.data.get("sections", [])]
        assert len(headings) == len(KI_IDS)
        assert headings[0].startswith("KI-009")
        assert headings[1].startswith("KI-FRONT-001")
        # content 为库中原文（非假正文）
        assert "华鑫轴承材料集团" in r.data["sections"][1]["content"]

    def test_previsit_ki_all_skipped_unknown_customer(self, svc_ck):
        """库中无该客户 → 全部 KI skipped（不以请求字段判定），报告仍可生成（不虚构）。"""
        r = svc_ck.execute("skill-customer-previsit-report", "tr-ki-unk",
                           {"customerId": "CUST-NOPE", "evidenceTimestamp": "2026-08-22T10:00:02Z"})
        assert r.status == "ok"
        msgs = [t.get("message", "") for t in r.assembly_trace]
        for ki in KI_IDS:
            assert any(ki in m and "skipped" in m for m in msgs), (ki, msgs)
        assert r.data.get("sections") == []  # 未命中的 KI 不凑章节

    def test_previsit_evidence_independent_of_request_fields(self, svc_ck):
        """请求带旧字段也不影响 evidence：ok 只由知识库决定。"""
        req = {"customerId": CUSTOMER_ID,
               "structuredFacts": {"profile": {"name": "改名客户"}},
               "knowledgeContext": "任何内容", "supplyChainMarkdown": "任何内容",
               "evidenceTimestamp": "2026-08-22T10:00:03Z"}
        r = svc_ck.execute("skill-customer-previsit-report", "tr-ki-oldf", req)
        ki_ok = {t.get("kiId") for t in r.assembly_trace
                 if t.get("phase") == "evidence" and t.get("status") == "ok" and t.get("kiId")}
        assert ki_ok == set(KI_IDS)

    def test_outreach_meeting_evidence_from_library(self, svc_ck):
        ro = svc_ck.execute("skill-customer-outreach-script", "tr-ki-4",
                            {"customerId": CUSTOMER_ID})
        mo = svc_ck.execute("skill-customer-meeting-script", "tr-ki-5",
                            {"customerId": CUSTOMER_ID})
        for r in (ro, mo):
            assert r.status == "ok"
            msgs = [t.get("message", "") for t in r.assembly_trace]
            assert any("知识地图" in m for m in msgs)
            assert any("KI-009" in m and "知识库命中" in m for m in msgs)
            assert r.data.get("evidenceRefs"), r.data
            assert r.data["evidenceRefs"][0]["id"] == "KI-009"


class TestSupplyChainFromLibrary:
    """v1.3：bank-front-supply-chain-graph 只认 customerId，从 DKWS 库构建 data.result。"""

    def test_graph_complete_from_library(self, svc_ck):
        r = svc_ck.execute("bank-front-supply-chain-graph", "tr-sc-1",
                           {"customerId": CUSTOMER_ID})
        assert r.status == "ok", (r.status, r.errors)
        result = r.data["result"]
        assert result["buildStatus"] == "complete"
        assert len(result["nodes"]) == 7
        assert len(result["edges"]) == 6
        layers = {n["layer"] for n in result["nodes"]}
        assert layers == {"enterprise", "supplier", "customer"}
        # 金额/占比来自库（x_ 字段）
        sup = [n for n in result["nodes"] if n["layer"] == "supplier"]
        assert sup[0]["annualAmount"] == 85000000
        assert sup[0]["share"] == 0.34
        assert result["interpretation"]["concentrationRisk"]
        # 无 LLM 调用（库构建）
        assert r.model_calls[0]["model"] == "library"

    def test_graph_partial_unknown_customer(self, svc_ck):
        r = svc_ck.execute("bank-front-supply-chain-graph", "tr-sc-2",
                           {"customerId": "CUST-NOPE"})
        assert r.status == "ok"
        result = r.data["result"]
        assert result["buildStatus"] == "partial"
        assert result["nodes"] == []
        assert result["edges"] == []

    def test_graph_registered_skill(self, svc_ck):
        reg = {s.skill_id for s in svc_ck.registry()}
        assert "bank-front-supply-chain-graph" in reg


class TestNoNewEvidencePolicy:
    """R1 无新证据策略（v1.3 保留）：evidenceTimestamp 未传/未更新 → exit_policy_no_new_evidence。"""

    def test_r1_requires_evidence_timestamp(self, svc_ck):
        r = svc_ck.execute("skill-customer-previsit-report", "tr-nne-1",
                           {"customerId": CUSTOMER_ID})
        assert r.status == "exit_policy_no_new_evidence"
        assert r.data == {}

    def test_r1_stale_timestamp_blocked(self, svc_ck):
        r1 = svc_ck.execute("skill-customer-previsit-report", "tr-nne-2",
                            {"customerId": CUSTOMER_ID,
                             "evidenceTimestamp": "2026-08-22T10:00:00Z"})
        assert r1.status == "ok"
        r2 = svc_ck.execute("skill-customer-previsit-report", "tr-nne-3",
                            {"customerId": CUSTOMER_ID,
                             "evidenceTimestamp": "2026-08-22T10:00:00Z"})
        assert r2.status == "exit_policy_no_new_evidence"

    def test_r1_newer_timestamp_ok(self, svc_ck):
        r = svc_ck.execute("skill-customer-previsit-report", "tr-nne-4",
                           {"customerId": CUSTOMER_ID,
                            "evidenceTimestamp": "2026-08-22T11:00:00Z"})
        assert r.status == "ok"

    def test_other_skills_ignore_policy(self, svc_ck):
        r = svc_ck.execute("skill-customer-outreach-script", "tr-nne-5",
                           {"customerId": CUSTOMER_ID})
        assert r.status == "ok"


class TestSecondCustomer:
    """CUST-CORP-0002 华东新能源汽车（0001 的下游客户）示范用例。"""

    CID2 = "CUST-CORP-0002"

    def test_r1_ki_all_ok(self, svc_ck):
        r = svc_ck.execute("skill-customer-previsit-report", "tr-c2-r1",
                           {"customerId": self.CID2, "evidenceTimestamp": "2026-08-22T10:00:00Z"})
        assert r.status == "ok", (r.status, r.errors)
        ki_ok = {t.get("kiId") for t in r.assembly_trace
                 if t.get("phase") == "evidence" and t.get("status") == "ok" and t.get("kiId")}
        assert ki_ok == set(KI_IDS)
        headings = [s["heading"] for s in r.data.get("sections", [])]
        assert headings[0].startswith("KI-009") and headings[1].startswith("KI-FRONT-001")
        # 0002 的上游含 0001（身份一致）
        assert "华东精工装备集团有限公司" in r.data["sections"][1]["content"]

    def test_graph_complete_from_library(self, svc_ck):
        r = svc_ck.execute("bank-front-supply-chain-graph", "tr-c2-sc",
                           {"customerId": self.CID2})
        result = r.data["result"]
        assert result["buildStatus"] == "complete"
        assert len(result["nodes"]) == 7 and len(result["edges"]) == 6
        # 上游含 CUST-CORP-0001
        sup_ids = {n["id"] for n in result["nodes"] if n["layer"] == "supplier"}
        assert "CUST-CORP-0001" in sup_ids
        assert r.model_calls[0]["model"] == "library"

    def test_fixture_identity_consistent(self, svc_ck):
        """夹具 customerId/名称/信用代码/RM 与 KI-009 实体一致。"""
        import json
        from pathlib import Path
        fixture = json.load(open(
            Path(__file__).resolve().parents[2] / "examples" / "output" / "gits-crm-customer-master.json"))
        for c in fixture["customers"]:
            ent = svc_ck._ckp.entity(c["customerId"])
            assert ent is not None
            assert ent["name"] == c["customerName"]
            assert ent.get("x_credit_code") == c["unifiedSocialCreditCode"]
            assert ent.get("x_rm_id") == c["rmId"]
