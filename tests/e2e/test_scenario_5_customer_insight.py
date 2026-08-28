"""场景5: 客户洞察 (Customer Insight / KYC)

E2E 链路: GITS Frontend → GITS Backend → KERT Skill Execution
验证: 客户洞察→KYC 差距分析→风险信号→产品匹配 完整链路
"""

from __future__ import annotations

import uuid

import httpx
import pytest


class TestCustomerInsight:
    """客户洞察场景 E2E 测试。"""

    CUSTOMER_ID = "CUST-CORP-0001"

    # ---- 5.1 客户经营总览 ----

    def test_customer_operating_view(self, gits_client: httpx.Client) -> None:
        """获取客户经营总览，验证包含完整客户画像。"""
        resp = gits_client.get(
            f"/api/v1/engagement/customer/{self.CUSTOMER_ID}/operating-view"
        )
        assert resp.status_code == 200, (
            f"客户经营总览失败 {resp.status_code}: {resp.text[:300]}"
        )
        body = resp.json()
        customer = body.get("customer", body)
        # 验证客户画像关键字段
        assert customer.get("customerId") == self.CUSTOMER_ID
        assert "customerName" in customer or "customer_name" in customer
        assert "industry" in customer
        assert "riskLevel" in customer or "risk_level" in customer

    # ---- 5.2 KYC 差距分析 ----

    def test_kyc_gap_analysis(self, gits_client: httpx.Client) -> None:
        """启动旅程时获取 KYC 差距摘要。"""
        resp = gits_client.post(
            "/api/v1/engagement/journey/start",
            json={"customerId": self.CUSTOMER_ID},
        )
        assert resp.status_code in (200, 201), (
            f"启动旅程失败 {resp.status_code}: {resp.text[:300]}"
        )
        body = resp.json()
        # 验证 KYC 差距摘要
        kyc_gap = body.get("kycGapSummary", body.get("kyc_gap_summary"))
        assert kyc_gap is not None, (
            f"缺少 KYC 差距摘要: {body}"
        )

    # ---- 5.3 Gate 状态与洞察关联 ----

    def test_insight_gate_correlation(self, gits_client: httpx.Client) -> None:
        """验证 Gate 状态与客户洞察数据关联。"""
        # 获取 Gate 状态
        gates_resp = gits_client.get(
            f"/api/v14/gates/state/{self.CUSTOMER_ID}"
        )
        assert gates_resp.status_code == 200
        gates_body = gates_resp.json()
        checklist = gates_body.get("checklist", [])
        assert len(checklist) > 0, "Gate 清单为空"

        # 获取经营总览
        view_resp = gits_client.get(
            f"/api/v1/engagement/customer/{self.CUSTOMER_ID}/operating-view"
        )
        assert view_resp.status_code == 200
        view_body = view_resp.json()
        customer = view_body.get("customer", view_body)
        assert "riskLevel" in customer or "risk_level" in customer

    # ---- 5.4 KERT 直连洞察 skill ----

    def test_insight_via_kert(self, kert_client: httpx.Client) -> None:
        """直接调用 KERT gates skill 获取客户洞察。"""
        resp = kert_client.get(
            f"/api/skill/gates/{self.CUSTOMER_ID}"
        )
        assert resp.status_code == 200, (
            f"KERT gates 查询失败 {resp.status_code}: {resp.text[:300]}"
        )
        body = resp.json()
        assert isinstance(body, (dict, list)), (
            f"KERT gates 响应格式异常: {type(body)}"
        )

    # ---- 5.5 完整洞察链路 ----

    def test_full_insight_flow(self, gits_client: httpx.Client, kert_client: httpx.Client) -> None:
        """客户洞察完整链路：启动旅程→经营总览→Gate→建议书→供应链图谱。"""
        # Step 1: 启动旅程（含 KYC 差距分析）
        start_resp = gits_client.post(
            "/api/v1/engagement/journey/start",
            json={"customerId": self.CUSTOMER_ID},
        )
        assert start_resp.status_code in (200, 201), (
            f"启动旅程失败: {start_resp.text[:200]}"
        )

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

        # Step 4: 生成服务建议书
        proposal_resp = gits_client.post(
            "/api/v14/proposals",
            json={
                "requestId": f"E2E-CI-{uuid.uuid4().hex[:8]}",
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

        # Step 5: 获取供应链图谱
        graph_resp = gits_client.post(
            "/api/v1/engagement/supply-chain-graph",
            json={"customerId": self.CUSTOMER_ID},
        )
        assert graph_resp.status_code == 200, (
            f"供应链图谱失败: {graph_resp.text[:200]}"
        )

        # Step 6: KERT 直连验证
        kert_health = kert_client.get("/api/skill/health")
        assert kert_health.status_code == 200, "KERT 不可达"
