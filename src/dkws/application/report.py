"""Skill 执行结果的可视化报告渲染（服务内定制模板）。

- `bank-front-supply-chain-graph`（SK-FRONT-002）：定制「供应链图谱分析报告」——
  力导向图谱（vis-network，Neo4j 风格）+ 三段式节点/有向边 + 四类解读卡片 + 明细表；
- 其它 Skill：通用暗色 JSON 查看页兜底。

服务侧用法：执行后 `GET /api/skill/report/{requestId}` 即返回本 HTML（结果在幂等缓存
TTL 10 分钟内有效）。
"""
from __future__ import annotations

import html as _html
import json
from functools import lru_cache
from pathlib import Path

_VENDOR_JS = (Path(__file__).resolve().parents[3]
              / "examples" / "output" / "vendor" / "vis-network.min.js")

LAYER_COLOR = {"supplier": "#4d9fff", "enterprise": "#ef476f", "customer": "#2dd4a7"}
LAYER_CN = {"supplier": "上游供应商", "enterprise": "本企业", "customer": "下游客户"}
REL_CN = {"purchase": "采购", "sale": "销售"}
TREND_CN = {"up": "↑ 上升", "down": "↓ 下降", "flat": "→ 持平", "unknown": "— 未知"}


@lru_cache(maxsize=1)
def _vendor_js() -> str:
    if _VENDOR_JS.exists():
        return _VENDOR_JS.read_text(encoding="utf-8")
    return "/* vis-network 未随服务部署，图谱渲染降级为列表 */"


def _esc(value) -> str:
    return _html.escape(str(value if value is not None else ""))


def _js_safe(obj) -> str:
    return json.dumps(obj, ensure_ascii=False).replace("</", "<\\/")


def _fmt_amount(v) -> str:
    try:
        v = float(v or 0)
    except (TypeError, ValueError):
        return "—"
    if v >= 1e8:
        return f"{v / 1e8:.2f} 亿"
    if v >= 1e4:
        return f"{v / 1e4:.1f} 万"
    return f"{v:,.0f}"


def _fmt_share(v) -> str:
    try:
        v = float(v or 0)
    except (TypeError, ValueError):
        return "—"
    return f"{v * 100:.1f}%" if v <= 1 else f"{v:.1f}%"


def _text_block(value) -> str:
    """interpretation 字段可能为 str / dict / list，统一渲染为 HTML 片段。"""
    if value is None:
        return ""
    if isinstance(value, str):
        return f"<p>{_esc(value)}</p>"
    if isinstance(value, list):
        items = "".join(f"<li>{_esc(x)}</li>" for x in value if x)
        return f"<ul>{items}</ul>" if items else ""
    if isinstance(value, dict):
        rows = "".join(
            f'<div class="kv"><span>{_esc(k)}</span><b>{_esc(v)}</b></div>'
            for k, v in value.items() if v not in (None, ""))
        return f'<div class="kvwrap">{rows}</div>' if rows else ""
    return _esc(value)


def _graph_script(nodes: list, edges: list) -> str:
    """vis-network 力导向图谱渲染（Neo4j 风格，选中高亮最近邻、缩放/悬停显名）。"""
    node_items = []
    for n in nodes:
        layer = n.get("layer") or "enterprise"
        color = LAYER_COLOR.get(layer, "#8b9dc3")
        size = 16 if layer == "enterprise" else 11
        try:
            amt = float(n.get("annualAmount") or 0)
            size = min(26, max(10, size + (amt ** 0.5) / 60))
        except (TypeError, ValueError):
            pass
        node_items.append({
            "id": n.get("id") or n.get("name") or "",
            "label": n.get("name") or n.get("id") or "",
            "layer": layer,
            "amount": n.get("annualAmount"),
            "share": n.get("share"),
            "trend": n.get("trend"),
            "verify": n.get("verifyStatus"),
            "source": n.get("dataSource"),
            "size": size,
            "color": color,
        })
    edge_items = []
    for e in edges:
        edge_items.append({
            "id": e.get("id") or f"e{len(edge_items)}",
            "s": e.get("source"), "t": e.get("target"),
            "rel": e.get("relation"), "amount": e.get("annualAmount"),
            "share": e.get("share"), "settlement": e.get("settlement"),
        })
    return """
const NODES = __NODES__; const EDGES = __EDGES__;
const LC = { supplier:"#4d9fff", enterprise:"#ef476f", customer:"#2dd4a7" };
const LCN = { supplier:"上游供应商", enterprise:"本企业", customer:"下游客户" };
const RC = { purchase:"采购", sale:"销售" };
const TCN = { up:"↑ 上升", down:"↓ 下降", flat:"→ 持平", unknown:"—" };
const byId = new Map(NODES.map(n=>[n.id,n]));
const nei = new Map(NODES.map(n=>[n.id,new Set()]));
for (const e of EDGES) { if (byId.has(e.s)) nei.get(e.s).add(e.t); if (byId.has(e.t)) nei.get(e.t).add(e.s); }
const dsNodes = new vis.DataSet(NODES.map(n=>({
  id:n.id, label:n.label,
  color:{ background:n.color, border:"#fff", highlight:{background:"#ffd166",border:"#fff"}, hover:{background:n.color,border:"#fff"} },
  font:{ color:"#fff", size:12, face:"Noto Sans SC, Microsoft YaHei, sans-serif" },
  shadow:{ enabled:true, color:hexA(n.color,.55), size:16, x:0, y:0 },
  shape:"dot", size:n.size, opacity:1,
})));
const dsEdges = new vis.DataSet(EDGES.map((e,i)=>({
  id:e.id, from:e.s, to:e.t,
  color:{ color:"#4a5d85", highlight:"#ffd166", hover:"#9db8e8" },
  arrows:{ to:{ enabled:true, scaleFactor:.6 } },
  width:1, hoverWidth:2, selectionWidth:2,
  smooth:{ enabled:true, type:"continuous" }, label:"",
  font:{ color:"#a8b8d8", size:10, face:"Noto Sans SC, Microsoft YaHei, sans-serif" },
})));
const net = new vis.Network(document.getElementById("gnet"), { nodes:dsNodes, edges:dsEdges }, {
  autoResize:true,
  interaction:{ hover:true, tooltipDelay:120, selectConnectedEdges:true, hoverConnectedEdges:true, dragView:true, zoomView:true },
  nodes:{ borderWidth:1.5, borderWidthSelected:3, opacity:1, font:{ color:"#fff", size:12 } },
  edges:{ selectionWidth:2, hoverWidth:2, width:1 },
  physics:{ enabled:true, stabilization:{ iterations:260, updateInterval:20, fit:true },
    barnesHut:{ gravitationalConstant:-4200, centralGravity:.05, springLength:110, springConstant:.04, damping:.4 },
    minVelocity:.8, maxVelocity:40 },
});
function hexA(h,a){h=h.replace("#","");const r=parseInt(h.slice(0,2),16),g=parseInt(h.slice(2,4),16),b=parseInt(h.slice(4,6),16);return `rgba(${r},${g},${b},${a})`;}
function applyLabels(){
  const showAll = net.getScale() >= .55;
  const upd=[];
  for (const n of NODES){ const cur=dsNodes.get(n.id); const want = n.layer==="enterprise" || showAll;
    if (!!cur.label !== want) upd.push({id:n.id, label: want?n.label:""}); }
  if (upd.length) dsNodes.update(upd);
  net.redraw();
}
net.on("zoom", applyLabels);
net.on("animationFinished", applyLabels);
net.on("stabilizationIterationsDone", applyLabels);
let hv=null;
net.on("hoverNode", p=>{ hv=p.node; const cur=dsNodes.get(p.node); if(!cur.label) dsNodes.update({id:p.node,label:byId.get(p.node).label}); net.redraw(); });
net.on("blurNode", ()=>{ if(hv!==null){ const n=byId.get(hv); if(n.layer!=="enterprise" && net.getScale()<.55 && !net.isSelected(hv)) dsNodes.update({id:hv,label:""}); hv=null; net.redraw(); } });
function setDim(keep){ const upd=[]; for(const n of NODES){ const op = keep.has(n.id)?1:.12; const cur=dsNodes.get(n.id); if((cur.opacity??1)!==op) upd.push({id:n.id,opacity:op}); } if(upd.length) dsNodes.update(upd); net.redraw(); }
net.on("selectNode", p=>{ const id=p.nodes[0]; if(!id)return; setDim(new Set([id,...nei.get(id)])); });
net.on("deselectNode", ()=>setDim(new Set(NODES.map(n=>n.id))));
function edgeLabel(id,on){ if(!id)return; const e=dsEdges.get(id); const rel=RC[e.rel]||e.rel||""; const amt=e.amount?fmtAmt(e.amount):""; const want=on?`${rel} ${amt}`.trim():""; if(e.label!==want) dsEdges.update({id,label:want}); net.redraw(); }
net.on("hoverEdge", p=>edgeLabel(p.edge,true));
net.on("blurEdge", p=>edgeLabel(p.edge,false));
net.on("selectEdge", p=>p.edges.forEach(id=>edgeLabel(id,true)));
net.on("deselectEdge", p=>p.edges.forEach(id=>edgeLabel(id,false)));
document.getElementById("gfit").addEventListener("click", ()=>net.fit({animation:{duration:400}}));
document.getElementById("greset").addEventListener("click", ()=>net.unselectAll());
function fmtAmt(v){ v=Number(v||0); if(v>=1e8) return (v/1e8).toFixed(2)+" 亿"; if(v>=1e4) return (v/1e4).toFixed(1)+" 万"; return String(v); }
window.addEventListener("resize", ()=>net.fit());
""".replace("__NODES__", _js_safe(node_items)).replace("__EDGES__", _js_safe(edge_items))


def render_supply_chain_report(result, payload: dict) -> str:
    data = payload.get("data") or {}
    graph = data.get("result") or {}
    nodes: list = graph.get("nodes") or []
    edges: list = graph.get("edges") or []
    interp: dict = graph.get("interpretation") or {}
    ent = next((n for n in nodes if n.get("layer") == "enterprise"), {})
    customer = ent.get("name") or graph.get("customerName") or graph.get("customerId") or "—"
    n_sup = sum(1 for n in nodes if n.get("layer") == "supplier")
    n_cus = sum(1 for n in nodes if n.get("layer") == "customer")
    build_status = graph.get("buildStatus") or "partial"
    confidence = interp.get("confidence")
    model_calls = payload.get("modelCalls") or []
    mc = model_calls[0] if model_calls else {}

    def card(title: str, value) -> str:
        return (f'<div class="card"><div class="card-v">{_esc(value)}</div>'
                f'<div class="card-k">{_esc(title)}</div></div>')

    def _fmt_conf(v) -> str:
        if v in (None, ""):
            return "—"
        if isinstance(v, dict):
            return "；".join(f"{k}={val}" for k, val in v.items() if val not in (None, ""))
        return str(v)

    stats_cards = "".join([
        card("节点总数", len(nodes)),
        card("关系边", len(edges)),
        card("上游供应商", n_sup),
        card("下游客户", n_cus),
        card("本企业", customer),
        card("置信度", _fmt_conf(confidence)),
    ])

    interp_html = ""
    for title, key in (("供应链位置", "supplyChainPosition"),
                       ("议价能力", "bargainingPower"),
                       ("集中度风险", "concentrationRisk"),
                       ("关键变动", "keyChanges"),
                       ("综合研判", "overallAssessment"),
                       ("访前必问事项", "followUpQuestions")):
        v = interp.get(key)
        if v in (None, "", [], {}):
            continue
        interp_html += (f'<section class="isec"><h3>{_esc(title)}</h3>'
                        f'{_text_block(v)}</section>')

    node_rows = "".join(
        f"<tr><td>{_esc(n.get('name') or n.get('id'))}</td>"
        f"<td><span class='tag t-{_esc(n.get('layer',''))}'>{_esc(LAYER_CN.get(n.get('layer'), n.get('layer')))}</span></td>"
        f"<td>{_fmt_amount(n.get('annualAmount'))}</td>"
        f"<td>{_fmt_share(n.get('share'))}</td>"
        f"<td>{_esc(TREND_CN.get(n.get('trend'), n.get('trend') or '—'))}</td>"
        f"<td>{_esc(n.get('verifyStatus') or '—')}</td>"
        f"<td>{_esc(n.get('dataSource') or '—')}</td></tr>"
        for n in nodes)
    edge_rows = "".join(
        f"<tr><td>{_esc(by_name(nodes, e.get('source')))}</td>"
        f"<td>→</td><td>{_esc(by_name(nodes, e.get('target')))}</td>"
        f"<td>{_esc(REL_CN.get(e.get('relation'), e.get('relation') or '—'))}</td>"
        f"<td>{_fmt_amount(e.get('annualAmount'))}</td>"
        f"<td>{_fmt_share(e.get('share'))}</td>"
        f"<td>{_esc(e.get('settlement') or '—')}</td></tr>"
        for e in edges)

    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>供应链图谱分析报告 · {_esc(customer)}</title>
<style>
  * {{ box-sizing:border-box; }}
  body {{ margin:0; font-family:"Noto Sans SC","Microsoft YaHei",system-ui,sans-serif; background:#0b1322; color:#e2e8f0; }}
  header {{ padding:18px 26px; background:linear-gradient(135deg,#101c33,#0e1630); border-bottom:1px solid #1c2f52; }}
  header h1 {{ margin:0; font-size:19px; color:#f1f5f9; }}
  header h1 small {{ color:#7c9bd1; font-weight:400; font-size:13px; margin-left:10px; }}
  .meta {{ margin-top:8px; font-size:12px; color:#8ba3c7; display:flex; gap:18px; flex-wrap:wrap; }}
  .badge {{ display:inline-block; padding:2px 10px; border-radius:20px; font-size:11px; font-weight:600; }}
  .b-complete {{ background:rgba(45,212,167,.15); color:#2dd4a7; border:1px solid rgba(45,212,167,.4); }}
  .b-partial {{ background:rgba(251,191,36,.15); color:#fbbf24; border:1px solid rgba(251,191,36,.4); }}
  .wrap {{ padding:20px 26px; max-width:1400px; margin:0 auto; }}
  .cards {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:12px; margin-bottom:18px; }}
  .card {{ background:#0f1b33; border:1px solid #1e2f55; border-radius:10px; padding:12px 14px; }}
  .card-v {{ font-size:17px; font-weight:700; color:#fbbf24; word-break:break-all; }}
  .card-k {{ font-size:11px; color:#8ba3c7; margin-top:3px; }}
  #gcard {{ background:#0d1728; border:1px solid #1e2f55; border-radius:12px; padding:12px; margin-bottom:18px; position:relative; }}
  #gcard h2 {{ margin:4px 8px 8px; font-size:14px; color:#cbd5e1; }}
  #gcard h2 span {{ color:#64748b; font-weight:400; font-size:12px; margin-left:8px; }}
  #gnet {{ width:100%; height:520px; }}
  .gbar {{ position:absolute; right:16px; top:12px; display:flex; gap:6px; }}
  .gbar button {{ background:#16233f; color:#cbd5e1; border:1px solid #2a3f68; border-radius:6px; padding:3px 10px; font-size:11px; cursor:pointer; }}
  .gbar button:hover {{ border-color:#fbbf24; color:#fbbf24; }}
  .legend {{ display:flex; gap:14px; font-size:11px; color:#94a3b8; padding:0 8px 6px; flex-wrap:wrap; }}
  .legend i {{ width:9px; height:9px; border-radius:50%; display:inline-block; margin-right:4px; }}
  .isec {{ background:#0f1b33; border:1px solid #1e2f55; border-left:3px solid #4d9fff; border-radius:8px; padding:12px 16px; margin-bottom:12px; }}
  .isec:nth-child(odd) {{ border-left-color:#2dd4a7; }}
  .isec h3 {{ margin:0 0 8px; font-size:14px; color:#ffd166; }}
  .isec p {{ margin:6px 0; line-height:1.7; font-size:13px; color:#dbe4f3; }}
  .isec ul {{ margin:6px 0; padding-left:20px; font-size:13px; color:#dbe4f3; line-height:1.8; }}
  .kvwrap {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(240px,1fr)); gap:8px; }}
  .kv {{ display:flex; justify-content:space-between; background:#0d1a33; border:1px solid #1e2f55; border-radius:6px; padding:6px 10px; font-size:12px; }}
  .kv span {{ color:#8ba3c7; }} .kv b {{ color:#e2e8f0; font-weight:600; }}
  details {{ background:#0f1b33; border:1px solid #1e2f55; border-radius:8px; margin-bottom:12px; }}
  summary {{ padding:10px 16px; cursor:pointer; color:#cbd5e1; font-size:13px; }}
  .tblwrap {{ overflow:auto; max-height:360px; padding:0 12px 12px; }}
  table {{ border-collapse:collapse; width:100%; font-size:12px; }}
  th,td {{ border:1px solid #1e2f55; padding:6px 9px; text-align:left; white-space:nowrap; }}
  th {{ background:#132242; color:#8ba3c7; position:sticky; top:0; }}
  td {{ color:#dbe4f3; }}
  .tag {{ padding:1px 8px; border-radius:12px; font-size:11px; }}
  .t-supplier {{ background:rgba(77,159,255,.15); color:#7db4ff; }}
  .t-enterprise {{ background:rgba(239,71,111,.15); color:#ff8fa5; }}
  .t-customer {{ background:rgba(45,212,167,.15); color:#5ce0b8; }}
  footer {{ padding:14px 26px 26px; font-size:11px; color:#5c7299; }}
</style></head>
<body>
<header>
  <h1>供应链图谱分析报告 <small>SK-FRONT-002 · bank-front-supply-chain-graph</small></h1>
  <div class="meta">
    <span>客户：<b style="color:#e2e8f0">{_esc(customer)}</b></span>
    <span>客户ID：{_esc(graph.get('customerId') or '—')}</span>
    <span>生成时间：{_esc(graph.get('generatedAt') or '—')}</span>
    <span class="badge {'b-complete' if build_status=='complete' else 'b-partial'}">{_esc(build_status)}</span>
    <span>请求ID：{_esc(payload.get('requestId') or '—')}</span>
  </div>
</header>
<div class="wrap">
  <div class="cards">{stats_cards}</div>
  <div id="gcard">
    <h2>三段式供应链图谱 <span>滚轮缩放 · 拖拽平移 · 点击节点高亮上下游 · 缩放/悬停显示名称</span></h2>
    <div class="gbar"><button id="greset">取消选中</button><button id="gfit">复位视图</button></div>
    <div class="legend">
      <span><i style="background:#4d9fff"></i>上游供应商</span>
      <span><i style="background:#ef476f"></i>本企业</span>
      <span><i style="background:#2dd4a7"></i>下游客户</span>
      <span>边标签：关系 + 金额（选中/悬停显示）</span>
    </div>
    <div id="gnet"></div>
  </div>
  {interp_html}
  <details><summary>节点明细（{len(nodes)}）</summary>
    <div class="tblwrap"><table><thead><tr><th>名称</th><th>层级</th><th>年金额</th><th>占比</th><th>趋势</th><th>核验</th><th>数据源</th></tr></thead>
    <tbody>{node_rows or '<tr><td colspan="7" style="color:#64748b">无节点数据（输入不足时按 Skill 降级，不虚构）</td></tr>'}</tbody></table></div>
  </details>
  <details><summary>关系边明细（{len(edges)}）</summary>
    <div class="tblwrap"><table><thead><tr><th>来源</th><th></th><th>目标</th><th>关系</th><th>年金额</th><th>占比</th><th>结算/账期</th></tr></thead>
    <tbody>{edge_rows or '<tr><td colspan="7" style="color:#64748b">无关系数据</td></tr>'}</tbody></table></div>
  </details>
</div>
<footer>
  模型：{_esc(mc.get('model') or '—')} · 输入 {mc.get('inputTokens', '—')} tokens / 输出 {mc.get('outputTokens', '—')} tokens / 耗时 {mc.get('latencyMs', '—')} ms ·
  本报告由 DKWS Skill 服务生成，仅供行内访前准备与初步判断参考，不作为对外法律效力文件。
</footer>
<script>{_vendor_js()}</script>
<script>{_graph_script(nodes, edges)}</script>
</body></html>"""


def by_name(nodes: list, node_id) -> str:
    for n in nodes:
        if n.get("id") == node_id:
            return str(n.get("name") or node_id)
    return str(node_id or "—")


def render_generic_report(payload: dict) -> str:
    body = json.dumps(payload, ensure_ascii=False, indent=2)
    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>Skill 执行结果 · {_esc(payload.get('requestId') or '')}</title>
<style>
  body {{ margin:0; background:#0b1322; color:#e2e8f0; font-family:ui-monospace,Consolas,monospace; }}
  h1 {{ font-family:"Noto Sans SC",sans-serif; font-size:15px; padding:14px 20px; border-bottom:1px solid #1e2f55; color:#cbd5e1; }}
  pre {{ padding:16px 22px; font-size:12px; line-height:1.6; color:#a5d6ff; overflow:auto; }}
</style></head>
<body><h1>Skill 执行结果 · {_esc(payload.get('requestId') or '')} · status={_esc(payload.get('status') or '')}</h1>
<pre>{_esc(body)}</pre></body></html>"""


def render_report(result) -> str:
    payload = result.as_dict()
    if getattr(result, "skill_id", "") == "bank-front-supply-chain-graph":
        return render_supply_chain_report(result, payload)
    return render_generic_report(payload)


# ---------------- SP-20 服务建议书报告（v1.4） ----------------

LABEL_CN = {"F": "已核验事实", "C": "推断结论", "B": "行为事实", "H": "假设", "P": "计划承诺", "A": "已批准"}
LABEL_COLOR = {"F": "#2dd4a7", "C": "#4d9fff", "B": "#fbbf24", "H": "#a78bfa", "P": "#f97316", "A": "#34d399"}


def _md_to_html(text: str) -> str:
    """极简 Markdown → HTML（标题/段落/列表/引用），够报告展示即可。"""
    out = []
    for line in (text or "").split("\n"):
        s = line.strip()
        if not s:
            continue
        if s.startswith("# "):
            out.append(f"<h2>{_esc(s[2:])}</h2>")
        elif s.startswith("## "):
            out.append(f"<h3>{_esc(s[3:])}</h3>")
        elif s.startswith("### "):
            out.append(f"<h4>{_esc(s[4:])}</h4>")
        elif s.startswith("- "):
            out.append(f"<li>{_esc(s[2:])}</li>")
        elif s.startswith("> "):
            out.append(f"<blockquote>{_esc(s[2:])}</blockquote>")
        else:
            out.append(f"<p>{_esc(s)}</p>")
    return "\n".join(out)


def render_proposal_report(result, payload: dict) -> str:
    data = payload.get("data") or {}
    res = data.get("result") or {}
    content = res.get("content") or {}
    intv = content.get("internalVersion") or {}
    custv = content.get("customerVersion")
    ctx = res.get("gateRecommendations") or {}
    violations = res.get("ruleViolations") or []

    def chip(gate: dict) -> str:
        st = gate.get("state", "")
        cls = {"PASSED": "g-pass", "READY_FOR_REVIEW": "g-ready", "BLOCKED": "g-block",
               "PENDING": "g-pend"}.get(st, "g-pend")
        return f'<span class="gate {cls}">{_esc(gate.get("gate", ""))}:{_esc(st)}</span>'

    gate_bar = "".join(chip(g) for g in (ctx.get("checklist") or []))
    vio_html = ""
    if violations:
        vio_html = ('<div class="vio"><b>规则违规（BLOCKING）</b><ul>' +
                    "".join(f"<li>{_esc(v.get('ruleId'))}: {_esc(v.get('message'))}</li>"
                            for v in violations) + "</ul></div>")

    claims = []
    for c in res.get("citations", []):
        claims.append(c)
    claims_rows = "".join(
        f"<tr><td>{_esc(c.get('claim',''))}</td>"
        f"<td><span class='lbl' style='background:{LABEL_COLOR.get(c.get('factLabel'),'#888')}'>{_esc(c.get('factLabel',''))}</span></td>"
        f"<td>{_esc(c.get('source',''))}</td><td>{_esc(c.get('date',''))}</td>"
        f"<td>{_esc(c.get('chapterRef',''))}</td></tr>"
        for c in claims)
    unknown_rows = "".join(
        f"<li><b>{_esc(u.get('id',''))}</b> {_esc(u.get('description',''))} → {_esc(u.get('suggestedAction',''))}</li>"
        for u in res.get("unknowns", [])) or "<li>无</li>"

    cust_html = "<p style='color:#64748b'>对客版未生成</p>"
    if custv:
        notes = "".join(f"<li>{_esc(n)}</li>" for n in (custv.get("filteringNotes") or [])) or "<li>无移除</li>"
        cust_html = f"""<div class="cust-notes">过滤说明：<ul>{notes}</ul>
        <div style="color:#8ba3c7;font-size:12px">放行前置闸门：{_esc('、'.join(custv.get('releaseBlockedUntil') or []))}</div></div>
        <div class="md">{_md_to_html(custv.get('content',''))}</div>"""

    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>服务建议书 · {_esc(payload.get('requestId') or '')}</title>
<style>
  * {{ box-sizing:border-box; }}
  body {{ margin:0; font-family:"Noto Sans SC","Microsoft YaHei",system-ui,sans-serif; background:#0b1322; color:#e2e8f0; }}
  header {{ padding:16px 26px; background:linear-gradient(135deg,#101c33,#0e1630); border-bottom:1px solid #1c2f52; }}
  header h1 {{ margin:0; font-size:18px; color:#f1f5f9; }}
  header h1 small {{ color:#7c9bd1; font-size:12px; margin-left:10px; }}
  .meta {{ margin-top:8px; font-size:12px; color:#8ba3c7; display:flex; gap:16px; flex-wrap:wrap; }}
  .wrap {{ padding:18px 26px; max-width:1200px; margin:0 auto; }}
  .gates {{ display:flex; gap:8px; flex-wrap:wrap; margin-bottom:14px; }}
  .gate {{ padding:3px 10px; border-radius:14px; font-size:11px; border:1px solid #2a3f68; }}
  .g-pass {{ background:rgba(45,212,167,.15); color:#2dd4a7; }}
  .g-ready {{ background:rgba(251,191,36,.15); color:#fbbf24; }}
  .g-block {{ background:rgba(239,71,111,.15); color:#ef476f; }}
  .g-pend {{ background:#16233f; color:#64748b; }}
  .vio {{ background:rgba(239,71,111,.1); border:1px solid #ef476f; border-radius:8px; padding:10px 14px; margin-bottom:14px; font-size:13px; color:#ffb3c1; }}
  .vio ul {{ margin:6px 0 0; padding-left:20px; }}
  .tabs {{ display:flex; gap:8px; margin-bottom:10px; }}
  .tabs button {{ background:#16233f; color:#cbd5e1; border:1px solid #2a3f68; border-radius:6px; padding:5px 14px; font-size:12px; cursor:pointer; }}
  .tabs button.on {{ border-color:#fbbf24; color:#fbbf24; }}
  .md {{ background:#0f1b33; border:1px solid #1e2f55; border-radius:10px; padding:16px 20px; font-size:13px; line-height:1.8; color:#dbe4f3; }}
  .md h2 {{ color:#ffd166; font-size:16px; border-bottom:1px solid #1e2f55; padding-bottom:6px; }}
  .md h3 {{ color:#7db4ff; font-size:14px; }}
  .md li {{ margin-left:18px; }}
  .cust-notes {{ background:#0f1b33; border:1px solid #1e2f55; border-radius:8px; padding:10px 14px; margin-bottom:12px; font-size:12px; color:#8ba3c7; }}
  details {{ background:#0f1b33; border:1px solid #1e2f55; border-radius:8px; margin:12px 0; }}
  summary {{ padding:10px 16px; cursor:pointer; color:#cbd5e1; font-size:13px; }}
  .tblwrap {{ overflow:auto; max-height:360px; padding:0 12px 12px; }}
  table {{ border-collapse:collapse; width:100%; font-size:12px; }}
  th,td {{ border:1px solid #1e2f55; padding:6px 9px; text-align:left; }}
  th {{ background:#132242; color:#8ba3c7; position:sticky; top:0; }}
  td {{ color:#dbe4f3; }}
  .lbl {{ color:#0b1322; font-weight:700; padding:1px 7px; border-radius:10px; font-size:11px; }}
</style></head>
<body>
<header>
  <h1>对公客户服务建议书 <small>SP-20 · {_esc(res.get('status') or '')} · {_esc(res.get('runId') or '')}</small></h1>
  <div class="meta">
    <span>请求ID：{_esc(payload.get('requestId') or '')}</span>
    <span>时间：{_esc(res.get('timestamp') or '')}</span>
    <span>类型：{_esc((data.get('proposalType') or ctx.get('currentGate')) or '')}</span>
    <span>当前闸门：{_esc(ctx.get('currentGate') or '')}（就绪度 {_esc(ctx.get('overallReadiness') or '')}）</span>
  </div>
</header>
<div class="wrap">
  <div class="gates">{gate_bar}</div>
  {vio_html}
  <div class="tabs">
    <button class="on" onclick="showTab('intv',this)">内部版</button>
    <button onclick="showTab('cust',this)">对客版</button>
  </div>
  <div id="tab-intv" class="md">{_md_to_html(intv.get('content', ''))}</div>
  <div id="tab-cust" style="display:none">{cust_html}</div>
  <details open><summary>断言与引用（{len(claims)}）</summary>
    <div class="tblwrap"><table><thead><tr><th>断言</th><th>标签</th><th>来源</th><th>日期</th><th>章节</th></tr></thead>
    <tbody>{claims_rows or '<tr><td colspan="5" style="color:#64748b">无断言</td></tr>'}</tbody></table></div>
  </details>
  <details><summary>未知项（{len(res.get('unknowns') or [])}）</summary><ul style="font-size:13px;padding:8px 24px">{unknown_rows}</ul></details>
  <details><summary>限制说明</summary><ul style="font-size:12px;padding:8px 24px;color:#8ba3c7">
    {''.join(f'<li>{_esc(x)}</li>' for x in res.get('limitations') or [])}</ul></details>
</div>
<script>
function showTab(id, btn) {{
  document.getElementById('tab-intv').style.display = id==='intv' ? 'block' : 'none';
  document.getElementById('tab-cust').style.display = id==='cust' ? 'block' : 'none';
  document.querySelectorAll('.tabs button').forEach(b => b.classList.remove('on'));
  btn.classList.add('on');
}}
</script>
</body></html>"""


def render_report(result) -> str:
    payload = result.as_dict()
    if getattr(result, "skill_id", "") == "bank-front-supply-chain-graph":
        return render_supply_chain_report(result, payload)
    if getattr(result, "skill_id", "") == "SP-20":
        return render_proposal_report(result, payload)
    return render_generic_report(payload)
