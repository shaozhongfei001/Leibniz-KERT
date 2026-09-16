"""KERT 全部 13 个 Skill 执行验证

验证每个 skill 都能被正确调用并返回有效响应。
"""

from __future__ import annotations

import httpx
import pytest

# KERT 13 个 skill 的完整列表（来自 /api/skill/health 实际返回）
SKILL_IDS = [
    "skill-customer-previsit-report",
    "skill-customer-meeting-script",
    "skill-customer-outreach-script",
    "bank-front-kyc-gap-check",
    "bank-front-eight-dimension",
    "bank-front-fact-reconciliation",
    "bank-front-product-recommendation",
    "bank-front-commitment-script",
    "bank-front-report-assembler",
    "bank-front-supply-chain-graph",
    "SP-15",
    "SP-20",
    "SP-21",
]

# SP-15 需要契约输入（product/rule 快照引用），e2e 用最小合法 context 构造用例
SP15_MINIMAL_CONTEXT = {
    "schemaVersion": "1.0.0",
    "customerId": "CUST-CORP-0001",
    "needVersionIds": ["NEEDV-001"],
    "recommendationObjective": "补充流动资金与跨境结算方案",
    "requestedProductDomains": ["FINANCING", "SETTLEMENT"],
    "asOf": "2026-09-15T09:00:00+08:00",
    "customerFactSnapshotId": "CFS-CUST-CORP-0001",
    "productKnowledgeSnapshotRef": "PKS-20260831-0001",
    "ruleBundleRef": "RB-20260831-0001",
    "permissionDecisionId": "PERM-20260831-0001",
}

# SP-20 服务建议书：执行器要求 `context.enterpriseData`，缺失即 fail-closed。
# 实测错误串 `ContextPackage 缺失字段: …` 源自 src/kert/application/service_proposal.py:134-135；
# 既有独立期望见 tests/e2e/kert_api_validation.py:272 的 notes（"SP-20 需要 context.enterpriseData"）。
SP20_MINIMAL_CONTEXT = {
    "customerId": "CUST-CORP-0001",
    "customerName": "华东精工装备集团有限公司",
    "industry": "制造业-装备制造",
    "engagementPhase": "ACTIVE_ENGAGEMENT",
    "enterpriseData": {"basicInfo": {}, "financialSummary": {}},
}

# SP-21 交互记忆抽取：要求 `context.interactionId` + `context.interactionContent`，
# 缺失即 `SKILL_EXECUTION_FAILED: interactionId / interactionContent 缺失`；
# 既有独立期望见 tests/e2e/kert_api_validation.py:284 的 notes。
SP21_MINIMAL_CONTEXT = {
    "customerId": "CUST-CORP-0001",
    "interactionId": "INT-E2E-0001",
    "interactionContent": "客户对供应链融资产品表示兴趣，希望了解授信额度和利率",
}

# 业务结论白名单（D-22，2026-09-16 裁定）：**强制显式登记**。
# 断言语义 = 「errors 为空 且（status == "ok" 或 status 恰为该 skill 登记的白名单值）」，
# 所以**将来任何新出现的非 ok 业务结论都必须先加入本表**才可能通过，不会被自动放行。
# 每条必须有文档依据（不得在测试里"发明"合法结论）：
#   ① 实现侧：src/kert/application/skills.py:317-321 ——
#      "无新证据策略（仅 R1，v1.3 保留）：evidenceTimestamp 未传或未更新
#       → exit_policy_no_new_evidence"
#   ② 既有独立期望：tests/e2e/kert_api_validation.py:290 对同一 skill 写的就是本值
BUSINESS_OUTCOME_WHITELIST: dict[str, str] = {
    "skill-customer-previsit-report": "exit_policy_no_new_evidence",
}


class TestAllSkillsExecution:
    """验证 KERT 全部 13 个 skill 可执行。"""

    CUSTOMER_ID = "CUST-CORP-0001"
    BASE_PARAMS = {
        "customerName": "华东精工",
        "industry": "制造业",
    }

    @pytest.mark.parametrize("skill_id", SKILL_IDS, ids=SKILL_IDS)
    def test_skill_execute(self, kert_client: httpx.Client, skill_id: str) -> None:
        """验证每个 skill 都能被正确调用，且业务结论为成功。"""
        if skill_id == "SP-15":
            # SP-15 需要契约输入（product/rule 快照引用），用最小合法 context 构造
            payload = {"skillId": skill_id, "request": {"context": SP15_MINIMAL_CONTEXT}}
        elif skill_id == "SP-20":
            # SP-20 需 `context.enterpriseData`（缺则 ContextPackage 缺失字段 → skill_error）
            payload = {"skillId": skill_id, "request": {"context": SP20_MINIMAL_CONTEXT}}
        elif skill_id == "SP-21":
            # SP-21 需 `context.interactionId` + `context.interactionContent`
            payload = {"skillId": skill_id, "request": {"context": SP21_MINIMAL_CONTEXT}}
        else:
            payload = {
                "skillId": skill_id,
                "customerId": self.CUSTOMER_ID,
                "parameters": self.BASE_PARAMS,
            }
        resp = kert_client.post("/api/skill/execute", json=payload)
        # 同步执行恒为 200（src/kert/api/server.py:669-671 的同步返回路径）；
        # 202 仅当请求显式 `async=true` 时出现，本用例不构造异步请求。
        assert resp.status_code == 200, (
            f"Skill {skill_id} 执行失败 {resp.status_code}: {resp.text[:300]}"
        )
        body = resp.json()
        assert isinstance(body, dict), f"Skill {skill_id} 响应非 JSON 对象: {type(body)}"
        # 验证返回结构包含基本字段
        assert "skillId" in body or "status" in body or "jobId" in body, (
            f"Skill {skill_id} 响应缺少基本字段: {list(body.keys())}"
        )
        # 业务成功判定（D-22）：errors 为空 **且** status 为 ok 或**显式白名单**值。
        # 只断言 HTTP 状态码会让 `{"status": "skill_error"}` 这类信封"绿"过去（假绿），
        # 故必须同时断言业务结论。
        status = body.get("status")
        errors = body.get("errors") or []
        allowed = BUSINESS_OUTCOME_WHITELIST.get(skill_id)
        assert not errors, f"Skill {skill_id} 业务失败：status={status!r} errors={errors}"
        assert status == "ok" or (allowed is not None and status == allowed), (
            f"Skill {skill_id} 的非常规业务结论未被显式白名单放行：status={status!r}，"
            f"该 skill 白名单值={allowed!r}。新增结论必须先登记 BUSINESS_OUTCOME_WHITELIST"
            f"（并附文档依据），不得自动放行。"
        )

    def test_skill_list_completeness(self, kert_client: httpx.Client) -> None:
        """验证 /api/skill/health 返回的 skill 列表包含所有预期 skill。"""
        resp = kert_client.get("/api/skill/health")
        assert resp.status_code == 200
        body = resp.json()
        skills = body.get("skills", [])
        available_ids = {s["skillId"] for s in skills}
        missing = set(SKILL_IDS) - available_ids
        assert not missing, f"缺少 skill: {missing}，可用: {available_ids}"

    def test_gates_endpoint(self, kert_client: httpx.Client) -> None:
        """验证 gates 端点返回有效数据。"""
        resp = kert_client.get(f"/api/skill/gates/{self.CUSTOMER_ID}")
        assert resp.status_code == 200, (
            f"Gates 查询失败 {resp.status_code}: {resp.text[:300]}"
        )
        body = resp.json()
        assert isinstance(body, (dict, list)), f"Gates 响应格式异常: {type(body)}"
