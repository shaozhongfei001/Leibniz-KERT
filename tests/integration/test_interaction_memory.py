"""SP-21 交互记忆抽取（Phase 3）测试：抽取/比对/规则 + SP-21→SP-20 UPDATE E2E 链路。"""

from __future__ import annotations

import pytest

from dkws.api.server import create_app
from dkws.application.skills import SkillExecutionService

EXISTING = [
    {"memoryId": "MEM-OLD-001", "category": "BUSINESS_SIGNAL",
     "content": "客户Q4有采购计划，预算约5000万", "confidence": 0.6},
    {"memoryId": "MEM-OLD-002", "category": "PREFERENCE",
     "content": "CFO 是关键决策人", "confidence": 0.9},
]

CTX = {
    "interactionId": "INT-20260823-001",
    "interactionContent": (
        "今日拜访华东精工财务总监与 CFO，对方表示 Q4 有采购计划，预算约 5000 万，"
        "偏好面对面沟通，正在考虑更换主办行；CFO 表示新授信方案需董事会审批。"),
    "existingMemories": EXISTING,
}


@pytest.fixture
def svc():
    return SkillExecutionService()


class TestSp21:
    def test_extract_candidates(self, svc):
        r = svc.execute("SP-21", "sp21-t-1", {"context": CTX})
        assert r.status == "ok", r.errors
        res = r.data["result"]
        assert res["skillId"] == "SP-21"
        assert res["status"] == "SUCCESS"
        cands = res["candidateMemories"]
        assert cands, "应抽取候选记忆"
        for c in cands:
            assert c["category"] in ("PREFERENCE", "DECISION_PATTERN", "RELATIONSHIP",
                                     "BUSINESS_SIGNAL", "EMOTIONAL_STATE")
            assert 0.0 <= c["confidence"] <= 1.0
            assert c["suggestedDecayRule"] in ("NONE", "LINEAR", "STEP")
            assert c.get("evidenceQuote")
        assert res["ruleViolations"] == []

    def test_reinforce_matching_memory(self, svc):
        """与已有记忆相似（10 字公共片段）→ REINFORCE（confidenceDelta）。"""
        r = svc.execute("SP-21", "sp21-t-2", {"context": CTX})
        updates = r.data["result"]["memoryUpdates"]
        assert any(u.get("action") == "REINFORCE" for u in updates), updates

    def test_negation_supersedes(self, svc):
        """新记忆含否定语义且与旧记忆相似 → SUPERSEDE。"""
        ctx = dict(CTX)
        ctx["interactionContent"] = (
            "客户表示 Q4 有采购计划，预算约 5000 万，但该计划已取消，不再考虑更换主办行，维持现有合作。")
        r = svc.execute("SP-21", "sp21-t-3", {"context": ctx})
        res = r.data["result"]
        supers = res["memorySupersessions"]
        # 旧记忆 MEM-OLD-001（Q4 采购计划）被否定
        assert any(s.get("memoryId") == "MEM-OLD-001" for s in supers), supers

    def test_rules_calibrate_confidence(self, svc):
        """CONFIDENCE_CALIBRATION / DECAY_RULE_APPLICATION / DUPLICATE_DETECTION。"""
        from dkws.application.interaction_memory import InteractionMemoryExecutor
        ex = InteractionMemoryExecutor()
        bad = [{"memoryId": "M-1", "content": "x", "category": "PREFERENCE",
                "confidence": 1.5, "suggestedDecayRule": "LINEAR"},
               {"memoryId": "M-2", "content": "x", "category": "PREFERENCE",
                "confidence": 0.5, "suggestedDecayRule": "EXP"},
               {"memoryId": "M-3", "content": "客户偏好面对面沟通", "category": "PREFERENCE",
                "confidence": 0.5, "suggestedDecayRule": "NONE"},
               {"memoryId": "M-4", "content": "客户偏好面对面沟通", "category": "PREFERENCE",
                "confidence": 0.5, "suggestedDecayRule": "NONE"}]
        violations = ex._check_rules(bad)
        assert any(v["ruleId"] == "CONFIDENCE_CALIBRATION" for v in violations)
        assert any(v["ruleId"] == "DECAY_RULE_APPLICATION" for v in violations)
        assert any(v["ruleId"] == "DUPLICATE_DETECTION" for v in violations)

    def test_missing_input_fail_closed(self, svc):
        r = svc.execute("SP-21", "sp21-t-4", {"context": {"interactionId": "I-1"}})
        assert r.status == "skill_error"

    def test_registered(self, svc):
        assert "SP-21" in {s.skill_id for s in svc.registry()}


class TestE2EMemoryToProposal:
    """E2E：交互 → SP-21 抽取 →（确认）→ SP-20 UPDATE（MAP_FIRST）→ 建议书更新。"""

    def test_full_chain(self, svc):
        # 1) SP-21 抽取候选
        r1 = svc.execute("SP-21", "e2e-mem-1", {"context": CTX})
        assert r1.status == "ok"
        cands = r1.data["result"]["candidateMemories"]
        assert cands
        # 2) 假设 GITS 确认，注入 SP-20 UPDATE
        ctx20 = {
            "customerId": "CUST-CORP-0001",
            "customerName": "华东精工装备集团有限公司",
            "industry": "制造业-装备制造",
            "engagementPhase": "ACTIVE_ENGAGEMENT",
            "enterpriseData": {"basicInfo": {}, "financialSummary": {},
                               "creditFacility": {}, "transactionSummary": {}},
            "publicData": {}, "interactionHistory": [],
            "interactionMemory": [{"memoryId": c["memoryId"], "category": c["category"],
                                   "content": c["content"], "confidence": c["confidence"]}
                                  for c in cands],
            "evidence": [],
            "proposalContext": {
                "proposalType": "UPDATE",
                "gateState": {"passed": ["G0", "G1", "G2", "G3"], "current": "G4"},
                "previousVersion": "# 上一版建议书\n\n（上一版内容）",
            },
        }
        r2 = svc.execute("SP-20", "e2e-sp20-1", {"context": ctx20})
        assert r2.status == "ok"
        res = r2.data["result"]
        # UPDATE 路由 MAP_FIRST
        trace = [t for t in r2.assembly_trace if t.get("phase") == "route"]
        assert any("MAP_FIRST" in t.get("message", "") for t in trace)
        # G1-G3 已过 → 对客版可放行
        assert res["content"]["customerVersion"]["releaseBlockedUntil"] == []
        # 交互记忆进入章节上下文（CH05/CH06 依赖 memory）→ citations 引用记忆来源
        mem_sources = [c for c in res["citations"] if c.get("source") and "interactionMemory" in c["source"]]
        assert mem_sources, "交互记忆应进入建议书引用"


class TestApi:
    def test_health_lists_sp21(self, ws):
        from fastapi.testclient import TestClient
        app = create_app(ws)
        with TestClient(app) as client:
            ids = [s["skillId"] for s in client.get("/api/skill/health").json()["skills"]]
            assert "SP-21" in ids

    def test_execute_sp21(self, ws):
        from fastapi.testclient import TestClient
        app = create_app(ws)
        with TestClient(app) as client:
            r = client.post("/api/skill/execute", json={
                "skillId": "SP-21", "requestId": "sp21-api-1",
                "request": {"context": CTX}})
            assert r.status_code == 200
            body = r.json()
            assert body["status"] == "ok"
            assert body["data"]["result"]["candidateMemories"]
            assert body["data"]["reportUrl"]
