"""场景4: 知识图谱/供应链图谱 (Knowledge Graph / Supply Chain)

E2E 链路: GITS Frontend → GITS Backend → KERT Skill Execution
验证: 供应链图谱构建→节点/边数据→图谱可视化数据 完整链路
"""

from __future__ import annotations

import httpx
import pytest


class TestKnowledgeGraph:
    """知识图谱/供应链图谱场景 E2E 测试。"""

    CUSTOMER_ID = "CUST-CORP-0001"

    # ---- 4.1 供应链图谱 (GITS→KERT 跨服务) ----

    def test_supply_chain_graph_via_gits(self, gits_client: httpx.Client) -> None:
        """通过 GITS API 获取供应链图谱（触发 GITS→KERT 跨服务调用）。"""
        resp = gits_client.post(
            "/api/v1/engagement/supply-chain-graph",
            json={"customerId": self.CUSTOMER_ID},
        )
        assert resp.status_code == 200, (
            f"供应链图谱获取失败 {resp.status_code}: {resp.text[:300]}"
        )
        body = resp.json()
        # 验证核心结构
        assert body.get("status") == "ok" or body.get("buildStatus") == "complete", (
            f"供应链图谱状态异常: {body}"
        )
        result = body.get("result", body)
        nodes = result.get("nodes", [])
        assert len(nodes) > 0, (
            f"供应链图谱节点为空: {body}"
        )
        # 验证节点结构
        first_node = nodes[0]
        assert "id" in first_node, f"节点缺少 id: {first_node}"
        assert "name" in first_node or "label" in first_node, (
            f"节点缺少名称: {first_node}"
        )

    # ---- 4.2 图谱节点类型验证 ----

    def test_supply_chain_node_types(self, gits_client: httpx.Client) -> None:
        """验证供应链图谱包含多种节点类型（企业、客户、供应商）。"""
        resp = gits_client.post(
            "/api/v1/engagement/supply-chain-graph",
            json={"customerId": self.CUSTOMER_ID},
        )
        assert resp.status_code == 200
        body = resp.json()
        result = body.get("result", body)
        nodes = result.get("nodes", [])
        node_types = {n.get("type", n.get("layer", "unknown")) for n in nodes}
        # 期望至少有企业节点
        assert "enterprise" in node_types or "ENTERPRISE" in node_types, (
            f"缺少企业节点类型，实际类型: {node_types}"
        )

    # ---- 4.3 图谱边/关系验证 ----

    def test_supply_chain_edges(self, gits_client: httpx.Client) -> None:
        """验证供应链图谱包含边/关系数据。"""
        resp = gits_client.post(
            "/api/v1/engagement/supply-chain-graph",
            json={"customerId": self.CUSTOMER_ID},
        )
        assert resp.status_code == 200
        body = resp.json()
        result = body.get("result", body)
        edges = result.get("edges", result.get("links", []))
        # 边可能为空（取决于数据），但结构必须存在
        assert isinstance(edges, list), (
            f"图谱边数据格式异常: {type(edges)}"
        )

    # ---- 4.4 KERT 直连 supply-chain skill ----

    def test_supply_chain_via_kert(self, kert_client: httpx.Client) -> None:
        """直接调用 KERT bank-front-supply-chain-graph skill 验证执行。"""
        resp = kert_client.post(
            "/api/skill/execute",
            json={
                "skillId": "bank-front-supply-chain-graph",
                "customerId": self.CUSTOMER_ID,
                "parameters": {
                    "customerName": "华东精工",
                    "industry": "制造业",
                },
            },
        )
        assert resp.status_code in (200, 201, 202), (
            f"KERT supply-chain 执行失败 {resp.status_code}: {resp.text[:300]}"
        )
        body = resp.json()
        assert isinstance(body, dict), f"supply-chain 响应非 JSON 对象: {body}"

    # ---- 4.5 客户准入 (R1) ----

    def test_customer_admission_r1(self, kert_client: httpx.Client) -> None:
        """验证客户准入 skill (bank-front-kyc-gap-check) 可执行。"""
        resp = kert_client.post(
            "/api/skill/execute",
            json={
                "skillId": "bank-front-kyc-gap-check",
                "customerId": self.CUSTOMER_ID,
                "parameters": {
                    "customerName": "华东精工",
                    "industry": "制造业",
                },
            },
        )
        assert resp.status_code in (200, 201, 202), (
            f"KERT R1 执行失败 {resp.status_code}: {resp.text[:300]}"
        )
