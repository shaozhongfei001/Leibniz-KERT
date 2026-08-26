#!/usr/bin/env python3
"""规模化模拟银行企业上下游图谱生成（数百/上千节点，性能展示用）。

- 多核心客户 × 多级上游/下游分支树（合成演示数据，源 DEMO-BANK-SC-*，非真实事实）；
- 走 DKWS 权威流程：候选 → 审核 APPROVE → 发布 → 投影 → Kùzu 建图；
- 默认：8 核心客户 × 4 级上游(3 分支) + 2 级下游(3 分支) ≈ 1000+ 节点 / 1000+ 边。

用法：python scripts/gen_bank_supply_chain_scale.py --workspace <demo_workspace>
      [--customers 8] [--up-levels 4] [--branch 3] [--down-levels 2]
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

from dkws.application.publish import Publisher
from dkws.application.projection import ProjectionBuilder
from dkws.application.review import ReviewService
from dkws.domain import timeutil
from dkws.infrastructure import markdown
from dkws.infrastructure.fs import WorkspaceWriter

DOMAIN = "supply_chain"
SERVICE_ID = "supply_chain_graph"
import time as _t
RUN_ID = f"RUN-DEMO-SCALE-{int(_t.time())}"

UP_PRODUCTS = ["轴承", "齿轮", "锻造", "铸造", "电镀", "冲压", "热处理", "密封件",
               "紧固件", "传感器", "线缆", "橡胶件", "塑料件", "液压件", "气动件",
               "模具", "刀具", "润滑", "包装", "物流"]
DOWN_PRODUCTS = ["整车", "变速箱", "传动系统", "电机", "电控", "底盘", "车桥",
                 "电池包", "充电桩", "售后市场"]

T0 = time.monotonic()


def log(msg: str) -> None:
    print(f"[{time.monotonic()-T0:6.1f}s] {msg}", flush=True)


def gen_tree(root_id: str, levels: int, branch: int, prefix: str,
             products: list[str], etype: str, counter: list[int],
             edge_to_parent: bool = True) -> tuple[list, list]:
    """生成一棵分支树：返回 (nodes, edges)。

    edge_to_parent=True（上游）：边 child→parent（供应商→核心，IN 方向可达上游）；
    edge_to_parent=False（下游）：边 parent→child（核心→客户，OUT 方向可达下游）。
    """
    nodes: list[dict] = []
    edges: list[tuple[str, str]] = []
    level_nodes = [root_id]
    for lv in range(1, levels + 1):
        next_level: list[str] = []
        for parent in level_nodes:
            for b in range(branch):
                counter[0] += 1
                nid = f"{prefix}{counter[0]:04d}"
                name = f"{products[counter[0] % len(products)]}企业{counter[0]:04d}"
                nodes.append({"id": nid, "name": name, "etype": etype, "layer": f"第{lv}级"})
                edges.append((nid, parent) if edge_to_parent else (parent, nid))
                next_level.append(nid)
        level_nodes = next_level
    return nodes, edges


def entity_md(eid, name, etype, layer) -> str:
    fm = {"schema": "entity/v1", "entity_id": eid, "entity_type": etype, "name": name,
          "aliases": [], "description": f"{layer}（合成规模演示）", "domain": DOMAIN,
          "source_ids": ["DEMO-BANK-SC-20260821"], "validation_status": "CANDIDATE",
          "status": "ACTIVE", "version": "1.0"}
    body = (f"# {name}\n\n## 定义\n\n{layer}供应链企业（合成规模演示）。\n\n"
            "## 业务说明\n\n用于图谱性能展示。\n\n## 来源证据\n\n合成演示数据源，非真实客户事实。\n\n"
            "## 审核说明\n\n待审核。\n")
    return markdown.render_contract_md(fm, body)


def relation_md(rid, src, tgt) -> str:
    fm = {"schema": "relation/v1", "relation_id": rid, "source_id": src,
          "relation_type": "SUPPLIES", "target_id": tgt, "direction": "DIRECTED",
          "source_ids": ["DEMO-BANK-SC-20260821"], "validation_status": "CANDIDATE",
          "status": "ACTIVE", "version": "1.0"}
    body = (f"# {src} 供应 {tgt}\n\n## 语义\n\n供应链供应关系（合成规模演示）。\n\n"
            "## 来源证据\n\n合成演示数据源。\n\n## 审核说明\n\n待审核。\n")
    return markdown.render_contract_md(fm, body)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace", "-w", required=True)
    ap.add_argument("--customers", type=int, default=8)
    ap.add_argument("--up-levels", type=int, default=4)
    ap.add_argument("--branch", type=int, default=3)
    ap.add_argument("--down-levels", type=int, default=2)
    args = ap.parse_args()
    ws = Path(args.workspace).resolve()
    writer = WorkspaceWriter(ws)

    cand_base = f"02_work/{DOMAIN}/run={RUN_ID}/candidates"
    all_refs: list[str] = []
    node_total = 0
    edge_total = 0

    for c in range(args.customers):
        core_id = f"CORE-{c:03d}"
        core_name = f"模拟核心制造企业{c:03d}"
        writer.write_text(f"{cand_base}/entities/{core_id}.md",
                          entity_md(core_id, core_name, "CUSTOMER", "核心中游"))
        all_refs.append(f"{cand_base}/entities/{core_id}.md")
        node_total += 1
        # 上游树（供应商→核心）
        counter = [c * 10_000]
        up_nodes, up_edges = gen_tree(core_id, args.up_levels, args.branch,
                                      f"UP{c:02d}-", UP_PRODUCTS, "SUPPLIER", counter)
        for n in up_nodes:
            writer.write_text(f"{cand_base}/entities/{n['id']}.md",
                              entity_md(n["id"], n["name"], n["etype"], n["layer"]))
            all_refs.append(f"{cand_base}/entities/{n['id']}.md")
        node_total += len(up_nodes)
        # 下游树（核心→客户，边方向 core→child）
        counter2 = [c * 10_000 + 5000]
        down_nodes, down_edges = gen_tree(core_id, args.down_levels, args.branch,
                                          f"DN{c:02d}-", DOWN_PRODUCTS, "CUSTOMER", counter2,
                                          edge_to_parent=False)
        for n in down_nodes:
            writer.write_text(f"{cand_base}/entities/{n['id']}.md",
                              entity_md(n["id"], n["name"], n["etype"], n["layer"]))
            all_refs.append(f"{cand_base}/entities/{n['id']}.md")
        node_total += len(down_nodes)
        # 边（up/down 边各生成一次）
        for edges in (up_edges, down_edges):
            for s, t in edges:
                edge_total += 1
                rid = f"REL-SC-{edge_total:05d}"
                writer.write_text(f"{cand_base}/relations/{rid}.md",
                                  relation_md(rid, s, t))
                all_refs.append(f"{cand_base}/relations/{rid}.md")
        log(f"客户 {core_id} 完成（累计节点 {node_total} / 边 {edge_total}）")

    log(f"候选生成完成：{node_total} 节点 / {edge_total} 边 / {len(all_refs)} 资产文件")
    log("开始审核 APPROVE（批量）…")
    ReviewService(ws).review(DOMAIN, run_id=RUN_ID, object_refs=all_refs,
                             decision="APPROVE", reason="合成规模演示数据审核", decided_by="svc_demo")
    log("审核完成，开始发布…")
    pub = Publisher(ws).publish(DOMAIN, run_id=RUN_ID)
    log(f"发布 version={pub.release_version}（资产 {pub.asset_count}）")
    log("构建投影与 Kùzu 图…")
    ProjectionBuilder(ws).build(DOMAIN, service_id=SERVICE_ID, idempotency_key="scale-demo-1")
    from dkws.infrastructure.graph.kuzu_builder import KuzuGraphBuilder
    b = KuzuGraphBuilder(ws, service_id=SERVICE_ID)
    fp = b.fingerprint_of(b._active_version())
    log(f"Kùzu 图谱: {fp['nodes']} 节点 / {fp['edges']} 边（指纹 {fp['hash'][:12]}…）")
    log(f"完成，总耗时 {time.monotonic()-T0:.1f}s")


if __name__ == "__main__":
    main()
