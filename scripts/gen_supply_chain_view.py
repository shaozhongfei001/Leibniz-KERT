#!/usr/bin/env python3
"""生成供应链图谱 Neo4j 风格浏览器可视化（vis-network 力导向布局，自包含+本地 vendor）。

读取 demo_workspace 最新 supply_chain_graph 版本的 entities/relations parquet，
产出 dkws/examples/output/supply_chain_graph_1064.html（引用了同目录 vendor/vis-network.min.js）。
用法: .venv/bin/python scripts/gen_supply_chain_view.py [--version DIR]
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict, deque
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT.parent
OUT = ROOT / "examples" / "output" / "supply_chain_graph_1064.html"


def load_latest_version_dir() -> Path:
    base = WORKSPACE / "demo_workspace" / "04_serve" / "supply_chain_graph"
    versions = sorted(base.glob("version=*"))
    if not versions:
        sys.exit(f"未找到图谱版本目录: {base}")
    return versions[-1]


def build(vdir: Path) -> dict:
    import pandas as pd

    entities = pd.read_parquet(vdir / "entities.parquet").to_dict("records")
    relations = pd.read_parquet(vdir / "relations.parquet").to_dict("records")

    nodes: list[dict] = []
    for e in entities:
        eid = e["entity_id"]
        prefix = eid[:3]
        role = "CORE" if prefix == "COR" else ("SUPPLIER" if prefix == "UP0" else "DISTRIBUTOR")
        nodes.append({
            "id": eid,
            "name": e.get("name") or eid,
            "role": role,
            "desc": e.get("description") or "",
            "type": e.get("entity_type") or "",
        })

    edges: list[dict] = []
    for i, r in enumerate(relations):
        edges.append({"id": f"e{i}", "s": r["source_id"], "t": r["target_id"],
                      "rel": r.get("relation_type") or "SUPPLIES"})

    # 层级（仅用于信息面板展示，布局交给力导向）
    adj_out: dict[str, list[str]] = defaultdict(list)
    adj_in: dict[str, list[str]] = defaultdict(list)
    for ed in edges:
        adj_out[ed["s"]].append(ed["t"])
        adj_in[ed["t"]].append(ed["s"])
    tier: dict[str, int] = {}
    cores = [n["id"] for n in nodes if n["role"] == "CORE"]
    for c in cores:
        tier[c] = 0
    q = deque(cores)
    while q:
        cur = q.popleft()
        for src in adj_in.get(cur, []):
            if src not in tier:
                tier[src] = tier[cur] - 1
                q.append(src)
    q = deque(cores)
    while q:
        cur = q.popleft()
        for tgt in adj_out.get(cur, []):
            if tgt not in tier:
                tier[tgt] = tier[cur] + 1
                q.append(tgt)
    for n in nodes:
        n["tier"] = tier.get(n["id"], -99)
    return {"nodes": nodes, "edges": edges}


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>供应链图谱 · Neo4j 风格 · 1064 节点（模拟银行企业上下游图谱）</title>
<style>
  :root { --core:#ef476f; --supplier:#4d9fff; --distributor:#2dd4a7; --bg:#0b1322; }
  * { box-sizing:border-box; }
  body { margin:0; font-family:"Noto Sans SC","Microsoft YaHei",system-ui,sans-serif; background:var(--bg); color:#e2e8f0; overflow:hidden; }
  header { display:flex; align-items:center; gap:16px; padding:10px 18px; background:#0e1a30; border-bottom:1px solid #1c2f52; flex-wrap:wrap; }
  header h1 { font-size:15px; margin:0; color:#f1f5f9; white-space:nowrap; }
  header h1 em { font-style:normal; color:#7c9bd1; font-size:12px; margin-left:8px; }
  .stats { display:flex; gap:14px; font-size:12px; color:#8ba3c7; }
  .stats b { color:#fbbf24; }
  .legend { display:flex; gap:14px; font-size:12px; align-items:center; margin-left:auto; }
  .legend span { display:inline-flex; align-items:center; gap:6px; color:#cbd5e1; }
  .dot { width:11px; height:11px; border-radius:50%; display:inline-block; box-shadow:0 0 8px 1px currentColor; }
  #wrap { position:relative; width:100vw; height:calc(100vh - 56px); }
  #net { width:100%; height:100%; }
  #info { position:absolute; right:14px; top:14px; width:286px; background:rgba(10,18,34,.94); border:1px solid #243a63; border-radius:10px; padding:12px 14px; font-size:12px; display:none; box-shadow:0 10px 34px rgba(0,0,0,.6); backdrop-filter:blur(4px); z-index:5; }
  #info h3 { margin:0 0 6px; font-size:14px; color:#ffd166; word-break:break-all; }
  #info .row { display:flex; justify-content:space-between; margin:3px 0; color:#8ba3c7; }
  #info .row b { color:#e2e8f0; font-weight:600; }
  #info .nei { margin-top:8px; color:#8ba3c7; max-height:140px; overflow:auto; }
  #info .nei li { margin:2px 0; word-break:break-all; }
  #search { margin-left:10px; background:#0b1322; border:1px solid #2a3f68; color:#e2e8f0; border-radius:6px; padding:4px 10px; font-size:12px; width:200px; }
  #search:focus { outline:none; border-color:#ffd166; }
  #nav { display:flex; gap:6px; }
  #nav button { background:#16233f; color:#cbd5e1; border:1px solid #2a3f68; border-radius:6px; padding:4px 10px; font-size:12px; cursor:pointer; }
  #nav button:hover { border-color:#ffd166; color:#ffd166; }
  #legend-zoom { position:absolute; left:14px; bottom:12px; font-size:11px; color:#5c7299; }
</style>
</head>
<body>
<header>
  <h1>🔗 供应链图谱 <em>Neo4j 风格 · 力导向布局</em></h1>
  <div class="stats">
    <span>节点 <b>__STATS_N__</b></span><span>边 <b>__STATS_E__</b></span>
    <span>核心企业 <b>__STATS_C__</b></span><span>上游供应商 <b>__STATS_S__</b></span>
    <span>下游分销 <b>__STATS_D__</b></span><span>层级 <b>__STATS_T__</b></span>
  </div>
  <div class="legend">
    <span><i class="dot" style="background:var(--core);color:var(--core)"></i>核心企业</span>
    <span><i class="dot" style="background:var(--supplier);color:var(--supplier)"></i>上游供应商</span>
    <span><i class="dot" style="background:var(--distributor);color:var(--distributor)"></i>下游分销商</span>
  </div>
  <input id="search" placeholder="搜索节点（名称/ID 子串）">
  <div id="nav"><button id="fit">复位视图</button><button id="phys">力导向：开</button></div>
</header>
<div id="wrap">
  <div id="net"></div>
  <div id="info"></div>
  <div id="legend-zoom">滚轮缩放 · 拖拽平移（可拖节点）· 点击节点高亮上下游 · 缩放或悬停显示名称 · 双击聚焦</div>
</div>
<script src="vendor/vis-network.min.js"></script>
<script>
"use strict";
const NODES = __NODES__;
const EDGES = __EDGES__;
const COLOR = { CORE:"#ef476f", SUPPLIER:"#4d9fff", DISTRIBUTOR:"#2dd4a7" };
const ROLE_CN = { CORE:"核心企业", SUPPLIER:"上游供应商", DISTRIBUTOR:"下游分销商" };

const byId = new Map(NODES.map(n => [n.id, n]));
const deg = new Map(NODES.map(n => [n.id, {in:0, out:0}]));
const nei = new Map(NODES.map(n => [n.id, new Set()]));
for (const e of EDGES) {
  deg.get(e.s).out++; deg.get(e.t).in++;
  nei.get(e.s).add(e.t); nei.get(e.t).add(e.s);
}

const nodes = new vis.DataSet(NODES.map(n => ({
  id: n.id,
  label: n.role === "CORE" ? n.name : "",
  color: {
    background: COLOR[n.role],
    border: "#ffffff",
    highlight: { background: "#ffd166", border: "#ffffff" },
    hover: { background: COLOR[n.role], border: "#ffffff" },
  },
  font: { color: "#ffffff", face: "Noto Sans SC, Microsoft YaHei, sans-serif" },
  shadow: { enabled: true, color: hexA(COLOR[n.role], 0.55), size: 18, x: 0, y: 0 },
  shape: "dot",
  size: n.role === "CORE" ? 20 : 11,
  scaling: { min: 8, max: 24 },
  value: n.role === "CORE" ? 3 : 1,
})));
const edges = new vis.DataSet(EDGES.map(e => ({
  id: e.id, from: e.s, to: e.t, raw_rel: e.rel,
  color: { color: "#4a5d85", highlight: "#ffd166", hover: "#9db8e8" },
  arrows: { to: { enabled: true, scaleFactor: 0.7 } },
  width: 1, hoverWidth: 2, selectionWidth: 2,
  smooth: { enabled: true, type: "continuous" },
  label: "",
  font: { color: "#a8b8d8", size: 10, face: "Noto Sans SC, Microsoft YaHei, sans-serif" },
})));

const container = document.getElementById("net");
const network = new vis.Network(container, { nodes, edges }, {
  autoResize: true,
  interaction: {
    hover: true, tooltipDelay: 120,
    selectConnectedEdges: true, hoverConnectedEdges: true,
    dragView: true, zoomView: true,
  },
  nodes: {
    borderWidth: 1.6, borderWidthSelected: 3,
    opacity: 1,
    font: { color: "#ffffff", size: 13, face: "Noto Sans SC, Microsoft YaHei, sans-serif" },
  },
  edges: { selectionWidth: 2, hoverWidth: 2, width: 1 },
  physics: {
    enabled: true,
    stabilization: { iterations: 320, updateInterval: 20, fit: true },
    barnesHut: {
      gravitationalConstant: -5200, centralGravity: 0.06,
      springLength: 100, springConstant: 0.05, damping: 0.4,
    },
    minVelocity: 0.8, maxVelocity: 40,
  },
});
window.network = network; // 便于控制台调试与外部脚本访问

// ---- 标签显示策略（Neo4j 风格：核心常显，其余缩放/悬停/选中显示） ----
function labelSize(role) { return role === "CORE" ? 14 : 9; }
function applyLabels(forceAll) {
  const scale = network.getScale();
  const showAll = forceAll === true || scale >= 0.5;
  const upd = [];
  for (const n of NODES) {
    const want = n.role === "CORE" || showAll;
    const cur = nodes.get(n.id);
    const has = !!cur.label;
    if (want !== has) {
      upd.push({ id: n.id, label: want ? n.name : "" });
    }
  }
  if (upd.length) nodes.update(upd);
  network.redraw();
}
network.on("zoom", () => applyLabels(false));
network.on("stabilizationIterationsDone", () => applyLabels(false));
network.on("animationFinished", () => applyLabels(false));
network.on("afterDrawing", () => { /* keep */ });

// 悬停显示名称
let hovered = null;
network.on("hoverNode", p => {
  hovered = p.node;
  const cur = nodes.get(p.node);
  if (!cur.label) nodes.update({ id: p.node, label: byId.get(p.node).name });
  network.redraw();
});
network.on("blurNode", () => {
  if (hovered !== null) {
    const cur = nodes.get(hovered);
    const role = byId.get(hovered).role;
    if (role !== "CORE" && network.getScale() < 0.5 && !network.isSelected(hovered)) {
      nodes.update({ id: hovered, label: "" });
    }
    hovered = null;
    network.redraw();
  }
});

// ---- 选择：信息面板 + Neo4j 风格高亮最近邻（选中者及其直连变亮，其余变暗） ----
function setDim(keep) {
  const upd = [];
  for (const n of NODES) {
    const op = keep.has(n.id) ? 1 : 0.12;
    if (nodes.get(n.id).opacity !== op) upd.push({ id: n.id, opacity: op });
  }
  if (upd.length) nodes.update(upd);
  network.redraw();
}
function tierText(t) {
  if (t === 0) return "核心层";
  return t < 0 ? `上游 -${-t} 级` : `下游 +${t} 级`;
}
function showNodeInfo(id) {
  const n = byId.get(id);
  const nb = [...nei.get(id)];
  setDim(new Set([id, ...nb]));
  const sup = nb.filter(x => byId.get(x).tier < n.tier).map(x => byId.get(x).name);
  const down = nb.filter(x => byId.get(x).tier > n.tier).map(x => byId.get(x).name);
  const info = document.getElementById("info");
  info.style.display = "block";
  info.innerHTML =
    `<h3>${esc(n.name)}</h3>` +
    `<div class="row"><span>实体ID</span><b>${esc(n.id)}</b></div>` +
    `<div class="row"><span>角色</span><b>${ROLE_CN[n.role]}</b></div>` +
    `<div class="row"><span>层级</span><b>${tierText(n.tier)}</b></div>` +
    `<div class="row"><span>入边 / 出边</span><b>${deg.get(id).in} / ${deg.get(id).out}</b></div>` +
    (n.desc ? `<div class="row" style="display:block;margin-top:6px">${esc(n.desc)}</div>` : "") +
    (sup.length ? `<div class="nei">上游直接相连（${sup.length}）<ul>${sup.slice(0,10).map(x=>`<li>${esc(x)}</li>`).join("")}${sup.length>10?"<li>…</li>":""}</ul></div>` : "") +
    (down.length ? `<div class="nei">下游直接相连（${down.length}）<ul>${down.slice(0,10).map(x=>`<li>${esc(x)}</li>`).join("")}${down.length>10?"<li>…</li>":""}</ul></div>` : "");
}
network.on("selectNode", p => { if (p.nodes[0]) showNodeInfo(p.nodes[0]); });
network.on("deselectNode", () => {
  document.getElementById("info").style.display = "none";
  setDim(new Set(NODES.map(n => n.id)));
});

// 边悬停/选中显示关系标签
function edgeLabel(id, on) {
  if (!id) return;
  const e = edges.get(id);
  const want = on ? (e.raw_rel || "SUPPLIES") : "";
  if (e.label !== want) edges.update({ id, label: want });
  network.redraw();
}
network.on("hoverEdge", p => edgeLabel(p.edge, true));
network.on("blurEdge", p => edgeLabel(p.edge, false));
network.on("selectEdge", p => p.edges.forEach(id => edgeLabel(id, true)));
network.on("deselectEdge", p => p.edges.forEach(id => edgeLabel(id, false)));

// ---- 搜索 ----
const search = document.getElementById("search");
search.addEventListener("input", () => {
  const q = search.value.trim().toLowerCase();
  network.unselectAll();
  if (!q) return;
  const hit = NODES.filter(n => n.name.toLowerCase().includes(q) || n.id.toLowerCase().includes(q))[0];
  if (!hit) return;
  network.selectNodes([hit.id], true);
  showNodeInfo(hit.id);
  network.focus(hit.id, { scale: 1.6, animation: { duration: 500, easingFunction: "easeInOutQuad" } });
  const cur = nodes.get(hit.id);
  if (!cur.label) nodes.update({ id: hit.id, label: hit.name });
  network.redraw();
});

// ---- 按钮 ----
document.getElementById("fit").addEventListener("click", () => network.fit({ animation: { duration: 400 } }));
const physBtn = document.getElementById("phys");
physBtn.addEventListener("click", () => {
  const on = !network.getOptions().physics.enabled;
  network.setOptions({ physics: { enabled: on } });
  physBtn.textContent = "力导向：" + (on ? "开" : "关");
});

// ---- 工具 ----
function hexA(hex, a) {
  const h = hex.replace("#", "");
  const r = parseInt(h.slice(0,2),16), g = parseInt(h.slice(2,4),16), b = parseInt(h.slice(4,6),16);
  return `rgba(${r},${g},${b},${a})`;
}
function esc(s) { return String(s).replace(/[&<>"]/g, c => ({ "&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;" }[c])); }
window.addEventListener("resize", () => network.fit());
</script>
</body>
</html>
"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", default=None, help="指定 version= 目录；缺省取最新")
    args = ap.parse_args()
    vdir = Path(args.version) if args.version else load_latest_version_dir()
    print(f"读取版本目录: {vdir}")
    data = build(vdir)
    stats = {
        "n": len(data["nodes"]), "e": len(data["edges"]),
        "c": sum(1 for n in data["nodes"] if n["role"] == "CORE"),
        "s": sum(1 for n in data["nodes"] if n["role"] == "SUPPLIER"),
        "d": sum(1 for n in data["nodes"] if n["role"] == "DISTRIBUTOR"),
        "t": len({n["tier"] for n in data["nodes"]}),
    }
    html = (HTML_TEMPLATE
            .replace("__NODES__", json.dumps(data["nodes"], ensure_ascii=False))
            .replace("__EDGES__", json.dumps(data["edges"], ensure_ascii=False))
            .replace("__STATS_N__", str(stats["n"]))
            .replace("__STATS_E__", str(stats["e"]))
            .replace("__STATS_C__", str(stats["c"]))
            .replace("__STATS_S__", str(stats["s"]))
            .replace("__STATS_D__", str(stats["d"]))
            .replace("__STATS_T__", str(stats["t"])))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html, encoding="utf-8")
    print(f"已生成: {OUT} ({OUT.stat().st_size/1024:.1f} KB)")


if __name__ == "__main__":
    main()
