"""场景2: 访前报告生成 (Pre-visit Report / SP-21)

E2E 链路: GITS Frontend → GITS Backend → KERT Skill Execution
验证: 交互记忆抽取→访前报告生成 完整链路
"""

from __future__ import annotations

import uuid

import httpx


class TestPrevisitReport:
    """访前报告生成场景 E2E 测试。"""

    CUSTOMER_ID = "CUST-CORP-0001"

    # ---- 2.1 交互记忆抽取 (SP-21) ----

    def test_memory_extraction(self, gits_client: httpx.Client) -> None:
        """通过 GITS V14 API 调用交互记忆抽取（触发 GITS→KERT 跨服务调用）。"""
        interaction_id = f"INT-E2E-{uuid.uuid4().hex[:8]}"
        resp = gits_client.post(
            "/api/v14/memories/extract",
            json={
                "interactionId": interaction_id,
                "customerId": self.CUSTOMER_ID,
            },
        )
        assert resp.status_code == 200, (
            f"交互记忆抽取失败 {resp.status_code}: {resp.text[:300]}"
        )
        body = resp.json()
        # 验证返回结构
        assert "status" in body or "schemaVersion" in body, (
            f"记忆抽取响应格式异常: {body}"
        )
        status = body.get("status", "")
        assert status in ("SUCCESS", "PARTIAL", "NO_DATA", ""), (
            f"记忆抽取状态异常: {body}"
        )

    # ---- 2.2 访前报告生成 (KERT 直连) ----

    def test_previsit_report_via_kert(self, kert_client: httpx.Client) -> None:
        """直接调用 KERT SP-21 skill 生成访前报告。"""
        resp = kert_client.post(
            "/api/skill/execute",
            json={
                "skillId": "SP-21",
                "customerId": self.CUSTOMER_ID,
                "parameters": {
                    "customerName": "华东精工",
                    "industry": "制造业",
                    "visitPurpose": "季度回顾",
                },
            },
        )
        assert resp.status_code in (200, 201, 202), (
            f"KERT SP-21 执行失败 {resp.status_code}: {resp.text[:300]}"
        )
        body = resp.json()
        # 验证返回结构
        assert isinstance(body, dict), f"SP-21 响应非 JSON 对象: {body}"

    # ---- 2.3 完整访前准备链路 ----

    def test_full_previsit_flow(self, gits_client: httpx.Client) -> None:
        """访前准备完整链路：获取经营总览→抽取记忆→查询 Gate→生成建议书。"""
        # Step 1: 获取经营总览
        view_resp = gits_client.get(
            f"/api/v1/engagement/customer/{self.CUSTOMER_ID}/operating-view"
        )
        assert view_resp.status_code == 200, (
            f"经营总览失败: {view_resp.text[:200]}"
        )

        # Step 2: 抽取交互记忆
        interaction_id = f"INT-PREVISIT-{uuid.uuid4().hex[:8]}"
        mem_resp = gits_client.post(
            "/api/v14/memories/extract",
            json={
                "interactionId": interaction_id,
                "customerId": self.CUSTOMER_ID,
            },
        )
        assert mem_resp.status_code == 200, (
            f"记忆抽取失败: {mem_resp.text[:200]}"
        )

        # Step 3: 查询 Gate 状态
        gates_resp = gits_client.get(
            f"/api/v14/gates/state/{self.CUSTOMER_ID}"
        )
        assert gates_resp.status_code == 200, (
            f"Gate 查询失败: {gates_resp.text[:200]}"
        )

        # Step 4: 生成服务建议书（访前报告核心输出）
        proposal_resp = gits_client.post(
            "/api/v14/proposals",
            json={
                "requestId": f"E2E-PV-{uuid.uuid4().hex[:8]}",
                "customerId": self.CUSTOMER_ID,
                "context": {
                    "customerName": "华东精工",
                    "industry": "制造业",
                    "visitPurpose": "季度回顾",
                },
            },
        )
        assert proposal_resp.status_code == 200, (
            f"建议书生成失败: {proposal_resp.text[:200]}"
        )
        proposal_body = proposal_resp.json()
        content = proposal_body.get("content", {})
        assert "proposalDraft" in content, (
            f"建议书缺少 proposalDraft: {proposal_body}"
        )
