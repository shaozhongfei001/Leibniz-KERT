#!/usr/bin/env python3
"""生成供应链演示图谱（虚拟多级上下游数据，扩张 Kùzu 图谱规模）。

- 围绕杭州智造精密齿轮（HZB0000001234）构造三级上游 / 两级下游供应链；
- 全部为【合成演示数据】（source_ids=DEMO-SUPPLY-CHAIN-*），非真实客户事实；
- 走 DKWS 权威流程：候选 → 审核 APPROVE → 发布 → 投影（自动建 Kùzu 图）；
- 产物：demo_workspace 的 supply_chain 域 + supply_chain_graph 服务投影。

用法：python scripts/gen_supply_chain_demo.py --workspace <demo_workspace>
"""

from __future__ import annotations

import argparse
from pathlib import Path

from dkws.application.publish import Publisher
from dkws.application.projection import ProjectionBuilder
from dkws.application.review import ReviewService
from dkws.domain import ids, timeutil
from dkws.infrastructure import markdown
from dkws.infrastructure.fs import WorkspaceWriter

DOMAIN = "supply_chain"
SERVICE_ID = "supply_chain_graph"
RUN_ID = "RUN-DEMO-SUPPLY"
DEMO_SOURCE = "DEMO-SUPPLY-CHAIN-20260821"

# ---- 图谱定义（合成演示）----
# 节点: (id, name, type, 层级)
NODES = [
    ("CORE-GEAR", "杭州智造精密齿轮有限公司", "CUSTOMER", "中游核心"),
    # 一级上游
    ("SUP1-BEARING", "浙江轴承集团", "SUPPLIER", "一级上游"),
    ("SUP1-STEEL", "宁波特种钢公司", "SUPPLIER", "一级上游"),
    ("SUP1-SEAL", "星火密封件厂", "SUPPLIER", "一级上游"),
    ("SUP1-FASTENER", "联合紧固件制造", "SUPPLIER", "一级上游"),
    # 二级上游
    ("SUP2-BEARSTEEL", "轴承钢坯公司", "SUPPLIER", "二级上游"),
    ("SUP2-ROLL", "滚子钢坯厂", "SUPPLIER", "二级上游"),
    ("SUP2-IRON", "特种铁矿公司", "SUPPLIER", "二级上游"),
    ("SUP2-ALLOY", "合金材料厂", "SUPPLIER", "二级上游"),
    ("SUP2-RUBBER", "橡胶密封原料厂", "SUPPLIER", "二级上游"),
    # 三级上游
    ("SUP3-ORE-A", "东岭铁矿石集团", "SUPPLIER", "三级上游"),
    ("SUP3-ORE-B", "西南矿业铁矿", "SUPPLIER", "三级上游"),
    ("SUP3-COKE", "焦化能源公司", "SUPPLIER", "三级上游"),
    ("SUP3-NICKEL", "镍业资源公司", "SUPPLIER", "三级上游"),
    # 下游一级
    ("DOWN1-EV-A", "新能源汽车主机厂A", "CUSTOMER", "一级下游"),
    ("DOWN1-GEAR-B", "变速箱总成厂B", "CUSTOMER", "一级下游"),
    ("DOWN1-TRANS-C", "传动系统厂C", "CUSTOMER", "一级下游"),
    # 下游二级
    ("DOWN2-EV-PLANT", "主机厂A华东装配基地", "CUSTOMER", "二级下游"),
    ("DOWN2-EV-PLANT2", "主机厂A华南装配基地", "CUSTOMER", "二级下游"),
    ("DOWN2-VEHICLE-X", "华东整车集团", "CUSTOMER", "二级下游"),
    ("DOWN2-VEHICLE-Y", "华南整车集团", "CUSTOMER", "二级下游"),
    # 平级/配套（合成：同链节点以展示多分支）
    ("SUP1-SENSOR", "精密传感器厂", "SUPPLIER", "一级上游"),
    ("SUP2-WIRE", "特种线缆公司", "SUPPLIER", "二级上游"),
    ("SUP3-COPPER", "铜材冶炼集团", "SUPPLIER", "三级上游"),
]

# 边: (src, dst)
EDGES = [
    ("SUP1-BEARING", "CORE-GEAR"), ("SUP1-STEEL", "CORE-GEAR"),
    ("SUP1-SEAL", "CORE-GEAR"), ("SUP1-FASTENER", "CORE-GEAR"),
    ("SUP1-SENSOR", "CORE-GEAR"),
    ("SUP2-BEARSTEEL", "SUP1-BEARING"), ("SUP2-ROLL", "SUP1-BEARING"),
    ("SUP2-IRON", "SUP1-STEEL"), ("SUP2-ALLOY", "SUP1-STEEL"),
    ("SUP2-RUBBER", "SUP1-SEAL"), ("SUP2-WIRE", "SUP1-SENSOR"),
    ("SUP3-ORE-A", "SUP2-IRON"), ("SUP3-ORE-B", "SUP2-IRON"),
    ("SUP3-COKE", "SUP2-IRON"), ("SUP3-NICKEL", "SUP2-ALLOY"),
    ("SUP3-COPPER", "SUP2-WIRE"),
    ("CORE-GEAR", "DOWN1-EV-A"), ("CORE-GEAR", "DOWN1-GEAR-B"),
    ("CORE-GEAR", "DOWN1-TRANS-C"),
    ("DOWN1-EV-A", "DOWN2-EV-PLANT"), ("DOWN1-EV-A", "DOWN2-EV-PLANT2"),
    ("DOWN1-TRANS-C", "DOWN2-VEHICLE-X"), ("DOWN1-TRANS-C", "DOWN2-VEHICLE-Y"),
    ("DOWN2-EV-PLANT", "DOWN2-VEHICLE-X"), ("DOWN2-EV-PLANT2", "DOWN2-VEHICLE-Y"),
]


def _entity_md(eid: str, name: str, etype: str, layer: str) -> str:
    fm = {
        "schema": "entity/v1",
        "entity_id": eid,
        "entity_type": etype,
        "name": name,
        "aliases": [],
        "description": f"{layer}（合成演示数据）",
        "domain": DOMAIN,
        "source_ids": [DEMO_SOURCE],
        "validation_status": "CANDIDATE",
        "status": "ACTIVE",
        "version": "1.0",
    }
    body = (f"# {name}\n\n## 定义\n\n{layer}供应链企业（合成演示）。\n\n"
            "## 业务说明\n\n用于供应链图谱演示。\n\n"
            "## 来源证据\n\n合成演示数据源，非真实客户事实。\n\n## 审核说明\n\n待审核。\n")
    return markdown.render_contract_md(fm, body)


def _relation_md(rid: str, src: str, tgt: str) -> str:
    fm = {
        "schema": "relation/v1",
        "relation_id": rid,
        "source_id": src,
        "relation_type": "SUPPLIES",
        "target_id": tgt,
        "direction": "DIRECTED",
        "source_ids": [DEMO_SOURCE],
        "validation_status": "CANDIDATE",
        "status": "ACTIVE",
        "version": "1.0",
    }
    body = (f"# {src} 供应 {tgt}\n\n## 语义\n\n供应链供应关系（合成演示）。\n\n"
            "## 来源证据\n\n合成演示数据源。\n\n## 审核说明\n\n待审核。\n")
    return markdown.render_contract_md(fm, body)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace", "-w", required=True)
    args = ap.parse_args()
    ws = Path(args.workspace).resolve()
    writer = WorkspaceWriter(ws)

    cand_base = f"02_work/{DOMAIN}/run={RUN_ID}/candidates"
    print(f"== 生成演示图谱：{len(NODES)} 节点 / {len(EDGES)} 边（合成，源={DEMO_SOURCE}）==")

    # 1) 候选
    refs = []
    for eid, name, etype, layer in NODES:
        rel = f"{cand_base}/entities/{eid}.md"
        writer.write_text(rel, _entity_md(eid, name, etype, layer))
        refs.append(rel)
    for i, (s, t) in enumerate(EDGES, start=1):
        rid = f"REL-SC-{i:03d}"
        rel = f"{cand_base}/relations/{rid}.md"
        writer.write_text(rel, _relation_md(rid, s, t))
        refs.append(rel)
    print(f"  候选 {len(refs)} 个")

    # 2) 审核 APPROVE
    ReviewService(ws).review(DOMAIN, run_id=RUN_ID, object_refs=refs,
                             decision="APPROVE", reason="合成演示数据审核", decided_by="svc_demo")
    print("  审核 APPROVE 完成")

    # 3) 发布
    pub = Publisher(ws).publish(DOMAIN, run_id=RUN_ID)
    print(f"  发布 version={pub.release_version}（资产 {pub.asset_count}）")

    # 4) 投影（自动建 Kùzu 图）
    prj = ProjectionBuilder(ws).build(DOMAIN, service_id=SERVICE_ID)
    print(f"  投影 {SERVICE_ID} version={prj.projection_version}")

    # 5) 图规模验证
    from dkws.infrastructure.graph.kuzu_builder import KuzuGraphBuilder
    b = KuzuGraphBuilder(ws, service_id=SERVICE_ID)
    fp = b.fingerprint_of(b._active_version())
    print(f"  Kùzu 图谱: {fp['nodes']} 节点 / {fp['edges']} 边（指纹 {fp['hash'][:12]}…）")


if __name__ == "__main__":
    main()
