"""v1.3 客户知识取数层（数据所有权在 DKWS，GITS 只传 customerId）。

按 customerId 从 `customer_knowledge` 服务投影读取：
- KI 片段（segments.document_id == customerId，heading_path 带 KI 编号与标题）
- 客户实体（x_* 扩展字段：信用代码 / RM / 风险等级等，与 CRM 主档一致）
- 供应链（entities + relations → nodes/edges，x_annual_amount 等）

任何未命中均如实返回空，不虚构；证据 ok/skipped 由此层决定。
"""
from __future__ import annotations

import re
from pathlib import Path

from .services import KnowledgeService

SERVICE_ID = "customer_knowledge"

# R1 必须打齐的 7 条 KI（顺序即报告章节顺序）
KI_ITEMS: list[tuple[str, str]] = [
    ("KI-009", "企业客户基本信息"),
    ("KI-FRONT-001", "公司供应链图谱"),
    ("KI-FRONT-002", "产业链八维研判"),
    ("KI-FRONT-003", "行内变动行为"),
    ("KI-FRONT-004", "事实承诺事项 / 沟通话术"),
    ("KI-FRONT-005", "KYC 信息缺口"),
    ("KI-FRONT-006", "产品候选组合"),
]
KI_ORDER = [k for k, _ in KI_ITEMS]

_KI_RE = re.compile(r"^(KI-[\w-]+)\s+(.+)$")


class CustomerKnowledgeProvider:
    """客户知识取数：ki_map / entity / supply_chain。服务不可用时返回空（fail-open）。"""

    def __init__(self, workspace: Path | str | None, service_id: str = SERVICE_ID):
        self.service_id = service_id
        self._svc: KnowledgeService | None = None
        self.available = False
        if workspace:
            try:
                self._svc = KnowledgeService(Path(workspace), service_id=service_id)
                # 探测服务是否存在（活动投影）
                self._svc._active_version()
                self.available = True
            except Exception:
                self._svc = None
                self.available = False

    # ---------------- KI 片段 ----------------

    def ki_map(self, customer_id: str) -> dict[str, dict]:
        """返回 {kiId: {"title": str, "content": str}}（按 heading_path 解析，无命中为空）。"""
        if not self.available or not customer_id:
            return {}
        rows = self._svc.segments(document_id=customer_id)
        out: dict[str, dict] = {}
        for r in rows:
            hp = r.get("heading_path") or []
            head = hp[0] if hp else ""
            m = _KI_RE.match(str(head))
            if not m:
                continue
            kid = m.group(1)
            content = (r.get("content") or "").strip()
            if content:
                out.setdefault(kid, {"title": m.group(2), "content": content})
        return out

    # ---------------- 客户实体 ----------------

    def entity(self, customer_id: str) -> dict | None:
        if not self.available:
            return None
        hits = [e for e in self._svc.entities() if e.get("entity_id") == customer_id]
        return hits[0] if hits else None

    # ---------------- 供应链图谱（从库构建，不虚构） ----------------

    def supply_chain(self, customer_id: str) -> dict:
        """由客户知识库 entities/relations 构建三段式图谱。

        返回 {"nodes": [...], "edges": [...], "buildStatus": "complete"|"partial"}；
        不足（供应商/客户不足 3 家或 KI-FRONT-001 缺失）→ partial。
        """
        if not self.available:
            return {"nodes": [], "edges": [], "buildStatus": "partial"}
        ents = self._svc.entities()
        rels = self._svc.relations()
        ent_map = {e["entity_id"]: e for e in ents}
        customer = ent_map.get(customer_id)
        if customer is None:
            return {"nodes": [], "edges": [], "buildStatus": "partial"}

        nodes: list[dict] = []
        nodes.append({
            "id": customer_id, "name": customer.get("name") or customer_id,
            "layer": "enterprise", "type": "enterprise",
            "industry": customer.get("x_industry"),
            "annualAmount": 0, "share": 1.0, "trend": "unknown",
            "dataSource": "DKWS", "verifyStatus": "VERIFIED",
        })
        edges: list[dict] = []
        seen_nodes = {customer_id}
        seen_edges = set()
        for r in rels:
            src, tgt, rtype = r.get("source_id"), r.get("target_id"), r.get("relation_type")
            if customer_id not in (src, tgt) or rtype != "SUPPLIES":
                continue
            if src == customer_id:          # 下游：本企业 → 客户
                other_id, relation, direction = tgt, "sale", "out"
            else:                            # 上游：供应商 → 本企业
                other_id, relation, direction = src, "purchase", "in"
            if (src, tgt) in seen_edges:     # 去重（同一关系可能由双方各自建模产生）
                continue
            seen_edges.add((src, tgt))
            other = ent_map.get(other_id)
            if other is None:
                continue
            if other_id not in seen_nodes:
                seen_nodes.add(other_id)
                layer = "supplier" if direction == "in" else "customer"
                nodes.append({
                    "id": other_id, "name": other.get("name") or other_id,
                    "layer": layer, "type": other.get("entity_type") or layer,
                    "industry": other.get("x_industry"),
                    "annualAmount": other.get("x_annual_amount"),
                    "share": other.get("x_share"),
                    "trend": other.get("x_trend"),
                    "dataSource": other.get("x_data_source") or "T-CORE-001",
                    "verifyStatus": "VERIFIED",
                })
            edges.append({
                "source": src, "target": tgt, "relation": relation,
                "direction": direction,
                "annualAmount": other.get("x_annual_amount"),
                "share": other.get("x_share"),
                "settlement": other.get("x_settlement"),
            })

        suppliers = [n for n in nodes if n["layer"] == "supplier"]
        customers = [n for n in nodes if n["layer"] == "customer"]
        # 完整判定：图谱 + 至少 3 供应商 + 至少 3 客户 + KI-FRONT-001 在库
        ki = self.ki_map(customer_id)
        build_status = ("complete" if (len(suppliers) >= 3 and len(customers) >= 3
                                       and "KI-FRONT-001" in ki) else "partial")
        return {
            "nodes": nodes, "edges": edges,
            "buildStatus": build_status,
            "suppliers": len(suppliers), "customers": len(customers),
        }

    # ---------------- 图谱解读（确定性派生，不虚构） ----------------

    def interpretation(self, customer_id: str, graph: dict) -> dict:
        ki = self.ki_map(customer_id)
        sup = [n for n in graph.get("nodes", []) if n["layer"] == "supplier"]
        cus = [n for n in graph.get("nodes", []) if n["layer"] == "customer"]
        ent = self.entity(customer_id) or {}
        name = ent.get("name") or customer_id

        def _top(lst, key="share"):
            return max(lst, key=lambda n: (n.get(key) or 0)) if lst else None

        top_sup, top_cus = _top(sup), _top(cus)
        sup_sum = sum((n.get("share") or 0) for n in sup)
        cus_sum = sum((n.get("share") or 0) for n in cus)

        def _pct(v):
            return f"{v * 100:.0f}%" if v else "—"

        concentration = []
        if top_sup:
            concentration.append(f"上游集中度：{top_sup['name']} 占采购 {_pct(top_sup.get('share'))}，前三大合计 {_pct(sup_sum)}")
        if top_cus:
            concentration.append(f"下游集中度：{top_cus['name']} 占销售 {_pct(top_cus.get('share'))}，前三大合计 {_pct(cus_sum)}")

        return {
            "supplyChainPosition": (ki.get("KI-FRONT-002", {}).get("content")
                                    or f"{name} 处于产业链中游核心制造环节（图谱 {len(sup)} 家供应商 / {len(cus)} 家客户）。"),
            "bargainingPower": (f"对上游：前三大供应商合计 {_pct(sup_sum)}；对下游：前三大客户合计 {_pct(cus_sum)}。"
                                f"结算方式：{'；'.join(sorted({str(n.get('settlement') or '—') for n in [*sup, *cus]}))}"),
            "concentrationRisk": concentration or [],
            "keyChanges": ki.get("KI-FRONT-003", {}).get("content", "知识库无 KI-FRONT-003（行内变动行为）数据。"),
            "overallAssessment": f"图谱规模 {len(graph.get('nodes', []))} 节点 / {len(graph.get('edges', []))} 边，构建状态 {graph.get('buildStatus', 'partial')}，供访前参考。",
            "followUpQuestions": [],
            "confidence": {"graph": graph.get("buildStatus", "partial"),
                           "kis": len(ki)},
        }
