"""KERT 全部 12 个 Skill 执行验证

验证每个 skill 都能被正确调用并返回有效响应。
"""

from __future__ import annotations

import httpx
import pytest

# KERT 12 个 skill 的完整列表（来自 /api/skill/health 实际返回）
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
    "SP-20",
    "SP-21",
]


class TestAllSkillsExecution:
    """验证 KERT 全部 12 个 skill 可执行。"""

    CUSTOMER_ID = "CUST-CORP-0001"
    BASE_PARAMS = {
        "customerName": "华东精工",
        "industry": "制造业",
    }

    @pytest.mark.parametrize("skill_id", SKILL_IDS, ids=SKILL_IDS)
    def test_skill_execute(self, kert_client: httpx.Client, skill_id: str) -> None:
        """验证每个 skill 都能被正确调用。"""
        resp = kert_client.post(
            "/api/skill/execute",
            json={
                "skillId": skill_id,
                "customerId": self.CUSTOMER_ID,
                "parameters": self.BASE_PARAMS,
            },
        )
        # 接受 200/201/202（同步/异步）
        assert resp.status_code in (200, 201, 202), (
            f"Skill {skill_id} 执行失败 {resp.status_code}: {resp.text[:300]}"
        )
        body = resp.json()
        assert isinstance(body, dict), f"Skill {skill_id} 响应非 JSON 对象: {type(body)}"
        # 验证返回结构包含基本字段
        assert "skillId" in body or "status" in body or "jobId" in body, (
            f"Skill {skill_id} 响应缺少基本字段: {list(body.keys())}"
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
