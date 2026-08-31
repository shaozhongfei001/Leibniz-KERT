"""场景1: 客户经理持续经营 (Continuous Operation / Engagement Journey)

E2E 链路: GITS Frontend → GITS Backend → KERT Skill Execution
验证: 客户经理启动旅程→洞察分析→产品匹配→访前准备→访后跟进 完整闭环
"""

from __future__ import annotations

import uuid

import httpx


class TestContinuousOperation:
    """客户经理持续经营场景 E2E 测试。"""

    CUSTOMER_ID = "CUST-CORP-0001"

    # ---- 1.1 旅程启动 ----

    def test_start_journey(self, gits_client: httpx.Client) -> None:
        """启动客户持续经营旅程，验证返回有效 journeyId。"""
        resp = gits_client.post(
            "/api/v1/engagement/journey/start",
            json={"customerId": self.CUSTOMER_ID},
        )
        assert resp.status_code in (200, 201), (
            f"启动旅程失败 {resp.status_code}: {resp.text[:300]}"
        )
        body = resp.json()
        assert "journeyId" in body or "journey_id" in body, (
            f"响应缺少 journeyId: {body}"
        )
        # 保存 journeyId 供后续测试使用
        journey_id = body.get("journeyId", body.get("journey_id"))
        assert journey_id, f"journeyId 为空: {body}"

    # ---- 1.2 客户经营总览 ----

    def test_operating_view(self, gits_client: httpx.Client) -> None:
        """获取客户经营总览，验证包含客户基本信息和经营数据。"""
        resp = gits_client.get(
            f"/api/v1/engagement/customer/{self.CUSTOMER_ID}/operating-view"
        )
        assert resp.status_code == 200, (
            f"获取经营总览失败 {resp.status_code}: {resp.text[:300]}"
        )
        body = resp.json()
        # 验证关键字段
        customer = body.get("customer", body)
        assert customer.get("customerId") == self.CUSTOMER_ID, (
            f"客户ID不匹配: {customer}"
        )
        assert "customerName" in customer or "customer_name" in customer, (
            f"缺少客户名称: {customer}"
        )

    # ---- 1.3 Gate 状态查询 (GITS→KERT 跨服务) ----

    def test_gate_state_via_gits(self, gits_client: httpx.Client) -> None:
        """通过 GITS V14 API 查询 Gate 状态（触发 GITS→KERT 跨服务调用）。"""
        resp = gits_client.get(
            f"/api/v14/gates/state/{self.CUSTOMER_ID}"
        )
        assert resp.status_code == 200, (
            f"Gate 状态查询失败 {resp.status_code}: {resp.text[:300]}"
        )
        body = resp.json()
        assert "customerId" in body or "currentGate" in body, (
            f"Gate 响应格式异常: {body}"
        )
        # 验证 Gate 清单存在
        checklist = body.get("checklist", [])
        assert len(checklist) > 0, (
            f"Gate 清单为空: {body}"
        )

    # ---- 1.4 Gate 状态查询 (KERT 直连) ----

    def test_gate_state_via_kert(self, kert_client: httpx.Client) -> None:
        """直接查询 KERT gates 端点，验证 KERT 侧 Gate 数据。"""
        resp = kert_client.get(
            f"/api/skill/gates/{self.CUSTOMER_ID}"
        )
        assert resp.status_code == 200, (
            f"KERT gates 查询失败 {resp.status_code}: {resp.text[:300]}"
        )
        body = resp.json()
        assert isinstance(body, (dict, list)), (
            f"KERT gates 响应格式异常: {body}"
        )

    # ---- 1.5 完整闭环验证 ----

    def test_full_engagement_loop(self, gits_client: httpx.Client) -> None:
        """持续经营完整闭环：启动→洞察→建议→Gate 推进。"""
        # Step 1: 启动旅程
        start_resp = gits_client.post(
            "/api/v1/engagement/journey/start",
            json={"customerId": self.CUSTOMER_ID},
        )
        assert start_resp.status_code in (200, 201), (
            f"启动旅程失败: {start_resp.text[:200]}"
        )
        start_body = start_resp.json()
        journey_id = start_body.get("journeyId", start_body.get("journey_id"))
        assert journey_id

        # Step 2: 获取经营总览
        view_resp = gits_client.get(
            f"/api/v1/engagement/customer/{self.CUSTOMER_ID}/operating-view"
        )
        assert view_resp.status_code == 200, (
            f"经营总览失败: {view_resp.text[:200]}"
        )

        # Step 3: 查询 Gate 状态
        gates_resp = gits_client.get(
            f"/api/v14/gates/state/{self.CUSTOMER_ID}"
        )
        assert gates_resp.status_code == 200, (
            f"Gate 查询失败: {gates_resp.text[:200]}"
        )

        # Step 4: 生成服务建议书 (SP-20)
        proposal_resp = gits_client.post(
            "/api/v14/proposals",
            json={
                "requestId": f"E2E-CO-{uuid.uuid4().hex[:8]}",
                "customerId": self.CUSTOMER_ID,
                "context": {
                    "customerName": "华东精工",
                    "industry": "制造业",
                },
            },
        )
        assert proposal_resp.status_code == 200, (
            f"建议书生成失败: {proposal_resp.text[:200]}"
        )
        proposal_body = proposal_resp.json()
        assert proposal_body.get("status") == "SUCCESS" or "proposalDraft" in proposal_body.get("content", {}), (
            f"建议书内容异常: {proposal_body}"
        )
