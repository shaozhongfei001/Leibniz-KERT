/* 六环工作台（vanilla JS，无框架；同源调本地 API）。
 *
 * 设计口径：
 * - **只做"人可点击 + 看原始响应"**：每个环一步，人话小结 + 原始 JSON（可展开）；
 * - **不伪造**：服务/工作区没就绪就如实显示错误码与原始响应（例如未供给控制面 ⇒
 *   环 2 应显示 fail-closed 拒绝，而不是"看起来成功"）；
 * - **同一 id 串链**：环 2 拿到的 `planId` 供环 5/6 取回整条链（与 /v1/evidence 同源）。
 *
 * ⚠ 非声明：本页是**人侧可见面**，不是机械断言；六环的断言在 tests/ 与 CI job 里。
 */
"use strict";

const API = "";                       // 同源：页面由 KERT 自己托管
const CUSTOMER = "CUST-CORP-0001";
const state = { planId: null, jobId: null };

const $ = (id) => document.getElementById(id);

function pill(id, kind, text) {
  const node = $(id);
  if (!node) return;
  node.className = "pill " + (kind === "ok" ? "pill-ok" : kind === "err" ? "pill-err" : "pill-idle");
  node.textContent = text;
}

function step(key, { ok, summary, raw }) {
  pill("pill-" + key, ok ? "ok" : "err", ok ? "通过" : "失败");
  $(("sum-" + key)).innerHTML = summary;
  if (raw !== undefined) {
    $(("raw-" + key)).querySelector("pre").textContent =
      typeof raw === "string" ? raw : JSON.stringify(raw, null, 2);
  }
}

/** 统一请求：**任何 HTTP 响应都算"可达"**（连 4xx/5xx 也要把响应体摆给人看）。 */
async function call(method, url, body) {
  const init = { method, headers: {} };
  if (body !== undefined) {
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(body);
  }
  const res = await fetch(API + url, init);
  const text = await res.text();
  let data;
  try { data = text ? JSON.parse(text) : {}; } catch (e) { data = { _raw: text }; }
  return { http: res.status, ok: res.ok, data };
}

function errCode(payload) {
  if (!payload) return "";
  if (Array.isArray(payload.errors) && payload.errors.length) return payload.errors[0].code || "";
  if (payload.detail) {
    if (typeof payload.detail === "string") return payload.detail;
    if (payload.detail.error) return payload.detail.error.code || "";
  }
  return "";
}

function esc(s) {
  return String(s === undefined || s === null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

/* ── 0 · 服务与工作区 ─────────────────────────────────────────── */
async function runHealth() {
  try {
    const h = await call("GET", "/v1/health");
    const d = await call("GET", "/dsh/api/dashboard");
    const data = h.data.data || {};
    const dash = d.data || {};
    const runtime = data.runtime || {};
    step("health", {
      ok: h.ok && h.http === 200,
      summary: [
        `服务：<b>${esc(data.status)}</b>（v${esc(data.service_version)}）`,
        `活动投影版本：<code>${esc(data.data_version || "无")}</code>`,
        `profile=<code>${esc(runtime.profile)}</code> 鉴权=${runtime.auth_enabled ? "开" : "关"}`,
        `工作区：实体 <b>${esc(dash.entity_count)}</b> / 关系 <b>${esc(dash.relation_count)}</b>` +
          ` / 声明 ${esc(dash.statement_count)} / 规则 ${esc(dash.rule_count)}`,
        `已注册技能：<b>${esc(dash.skill_count)}</b>（作业：运行中 ${esc(dash.jobs_running)}，完成 ${esc(dash.jobs_completed)}）`,
        data.data_version
          ? ""
          : "<span style='color:#8c1d1d'>无活动投影 ⇒ 环 4 的技能可能走「无新证据」退出</span>",
      ].filter(Boolean).join("<br>"),
      raw: { "/v1/health": h.data, "/dsh/api/dashboard": d.data },
    });
    connPill(h.ok);
    return h.ok;
  } catch (e) {
    step("health", { ok: false, summary: `请求失败：${esc(e.message)}（服务未启动或端口不对？）` });
    connPill(false);
    return false;
  }
}

function connPill(ok) {
  const node = $("conn-pill");
  node.className = "pill " + (ok ? "pill-ok" : "pill-err");
  node.textContent = ok ? "已连接" : "不可达";
}

/* ── 环 1 · 知识地图 ─────────────────────────────────────────── */
async function runRing1() {
  try {
    const r = await call("GET", "/v1/knowledge-maps");
    const data = r.data.data || {};
    const maps = data.maps || [];
    const policy = data.policy;
    step("ring1", {
      ok: r.ok,
      summary: maps.length
        ? `共 <b>${maps.length}</b> 张地图：` + maps.map((m) =>
            `<code>${esc(m.mapId)}@${esc(m.version)}</code>`).join("、") +
          (policy ? `<br>路由策略 <code>${esc(policy.policyId)}@${esc(policy.version)}</code>` +
            `（默认裁决 <code>${esc(policy.defaultDecision)}</code>）` : "")
        : `地图数 = <b>0</b>：控制面未注册（多数地图为空不代表"可用"）⇒ 环 2 会按 fail-closed **拒绝**。`,
      raw: r.data,
    });
    return r.ok;
  } catch (e) {
    step("ring1", { ok: false, summary: `请求失败：${esc(e.message)}` });
    return false;
  }
}

/* ── 环 2/3 · 路由计划 ───────────────────────────────────────── */
async function runRing2() {
  const taskType = $("task-type").value;
  try {
    const r = await call("POST", "/v1/routing/plan", { taskType, subjectId: CUSTOMER });
    const data = r.data.data || {};
    if (data.allowed && data.plan) {
      const p = data.plan;
      state.planId = p.planId;
      const v = p.versions || {};
      step("ring2", {
        ok: true,
        summary: `<b>放行</b>：<code>planId=${esc(p.planId)}</code>（planHash <code>${esc(p.planHash)}</code>）<br>` +
          `版本同时钉住三样：地图 <code>${esc(v.knowledgeMap)}</code>、策略 <code>${esc(v.routePolicy)}</code>、` +
          `本体 <code>${esc(v.ontology)}</code><br>` +
          `<span class="chain-note">⇒ 环 5/6 会用这个 planId 把整条链取回来</span>`,
        raw: r.data,
      });
    } else {
      const d = data.denial || {};
      step("ring2", {
        ok: true,
        summary: `<b>拒绝（预期业务结果，HTTP ${r.http}）</b>：<code>${esc(d.code)}</code> — ${esc(d.reason)}<br>` +
          `<span class="chain-note">拒绝是 fail-closed 的**正确**行为，不是故障。</span>`,
        raw: r.data,
      });
    }
    return true;
  } catch (e) {
    step("ring2", { ok: false, summary: `请求失败：${esc(e.message)}` });
    return false;
  }
}

/* ── 环 4 · 业务技能（含受控退出） ───────────────────────────── */
async function runRing4(withEvidence) {
  const req = { customerId: CUSTOMER };
  if (withEvidence) req.evidenceTimestamp = new Date().toISOString();
  try {
    const r = await call("POST", "/api/skill/execute", {
      skillId: "skill-customer-previsit-report", request: req,
    });
    const data = r.data || {};
    const trace = (data.assemblyTrace || []).map((t) => `${esc(t.phase)}:${esc(t.status)}`).join("、");
    const code = errCode(data);
    step("ring4", {
      ok: r.http === 200 && data.status === "ok",
      summary: `HTTP ${r.http}；<code>status=${esc(data.status)}</code>` +
        (code ? `（<code>${esc(code)}</code>）` : "") +
        (data.data && data.data.reportTitle ? `<br>报告标题：<b>${esc(data.data.reportTitle)}</b>` : "") +
        (data.data && data.data.evidenceRefs ? `<br>证据引用：${data.data.evidenceRefs.length} 条` : "") +
        (trace ? `<br>装配追踪：${trace}` : "") +
        `<br><span class="chain-note">不给证据时间 ⇒ 应为 <code>exit_policy_no_new_evidence</code>（受控退出，不是报错）</span>`,
      raw: r.data,
    });
    return r.http === 200;
  } catch (e) {
    step("ring4", { ok: false, summary: `请求失败：${esc(e.message)}` });
    return false;
  }
}

/* ── 环 5/6 · 用同一 id 取回链 ───────────────────────────────── */
async function runRing56() {
  if (!state.planId) {
    step("ring56", { ok: false, summary: `还没有 <code>planId</code> ⇒ 先执行"环 2/3"（本页刻意不猜 id）。` });
    return false;
  }
  try {
    const r = await call("GET", "/v1/evidence/" + encodeURIComponent(state.planId));
    const data = r.data.data || {};
    const chain = data.chain || [];
    const layers = chain.map((c) => esc(c.layer)).join(" → ");
    const anchor = chain.find((c) => c.layer === "04_serve/egress");
    if (!r.ok) {
      const code = errCode(r.data) || ("HTTP " + r.http);
      step("ring56", {
        ok: false,
        summary: `取回失败：<code>${esc(code)}</code>` +
          `<br><span class="chain-note">常见原因：本工作区**尚无活动投影**` +
          `（<code>04_serve/&lt;svc&gt;/CURRENT.md</code> 不存在）⇒ ` +
          `先用 <code>kert build-projection</code> / <code>materialize_from_plan</code> 产出投影；` +
          `**这不是链路缺陷**，是"这条链还没走到物化"。</span>`,
        raw: r.data,
      });
      return false;
    }
    step("ring56", {
      ok: data.complete === true,
      summary: `查询 id：<code>${esc(data.object_id)}</code>；complete=<b>${esc(data.complete)}</b><br>` +
        `链：${layers || "（空）"}（${chain.length} 段）` +
        (anchor ? `<br>出口锚点：<code>${esc(anchor.file_source)}</code>` +
          `<br><span class="chain-note">发布/检索的**状态**不在本地留痕 ⇒ 这里给的是与发布结果/检索引用**同名同值**的锚点</span>`
          : (data.blocker ? `<br>blocker：${esc(data.blocker)}` : "")),
      raw: r.data,
    });
    return r.ok;
  } catch (e) {
    step("ring56", { ok: false, summary: `请求失败：${esc(e.message)}` });
    return false;
  }
}

/* ── 作业状态 ───────────────────────────────────────────────── */
async function runJobs() {
  const jobId = ($("job-id").value || "").trim();
  try {
    if (jobId) {
      const r = await call("GET", "/v1/jobs/" + encodeURIComponent(jobId));
      const fm = r.data.data || {};
      step("jobs", {
        ok: r.ok,
        summary: `作业 <code>${esc(jobId)}</code>：状态 <b>${esc(fm.status)}</b>，` +
          `进度 ${esc(fm.progress)}%，发布 ${esc(fm.publish_status)}`,
        raw: r.data,
      });
      return r.ok;
    }
    const r = await call("GET", "/dsh/api/jobs");
    const jobs = (r.data.jobs || []);
    step("jobs", {
      ok: r.ok,
      summary: jobs.length
        ? `共 <b>${jobs.length}</b> 个作业：` + jobs.slice(-8).map((j) =>
            `<code>${esc(j.job_id)}</code>(${esc(j.status)})`).join("、")
        : `目录下暂无作业（异步受理后会出现在这里）。`,
      raw: r.data,
    });
    return r.ok;
  } catch (e) {
    step("jobs", { ok: false, summary: `请求失败：${esc(e.message)}` });
    return false;
  }
}

/* ── 一键走一遍 ─────────────────────────────────────────────── */
async function runAll() {
  $("run-summary").textContent = "执行中…（0 → 1 → 2 → 4 → 5/6 → 作业）";
  const steps = [
    ["0 服务", runHealth],
    ["环 1", runRing1],
    ["环 2/3", runRing2],
    ["环 4", () => runRing4(true)],
    ["环 5/6", runRing56],
    ["作业", runJobs],
  ];
  const failed = [];
  for (const [label, fn] of steps) {
    let ok = false;
    try { ok = await fn(); } catch (e) { ok = false; }
    if (!ok) failed.push(label);
  }
  const passed = steps.length - failed.length;
  $("run-summary").innerHTML = failed.length
    ? `<b>走完 ${passed}/${steps.length} 步</b>；未通过：${failed.map(esc).join("、")} ` +
      `<span class="chain-note">（未通过不一定是缺陷：例如未供给控制面时环 2 应"拒绝"、环 4 应"受控退出"）</span>`
    : `<b>走完 ${passed}/${steps.length} 步，全部通过</b>。`;
}

/* ── 绑定 ───────────────────────────────────────────────────── */
document.querySelectorAll("[data-run]").forEach((btn) => {
  btn.addEventListener("click", () => {
    const k = btn.getAttribute("data-run");
    if (k === "health") runHealth();
    else if (k === "ring1") runRing1();
    else if (k === "ring2") runRing2();
    else if (k === "ring4-ok") runRing4(true);
    else if (k === "ring4-blocked") runRing4(false);
    else if (k === "ring56") runRing56();
    else if (k === "jobs") runJobs();
  });
});
$("run-all").addEventListener("click", runAll);
$("show-raw").addEventListener("click", () => {
  document.querySelectorAll(".ring-raw").forEach((n) => n.classList.toggle("show"));
});
document.querySelectorAll("[data-jump]").forEach((a) => {
  a.addEventListener("click", (ev) => {
    ev.preventDefault();
    document.querySelectorAll(".nav-link").forEach((n) => n.classList.remove("active"));
    a.classList.add("active");
    const target = $(a.getAttribute("data-jump"));
    if (target) target.scrollIntoView({ behavior: "smooth", block: "start" });
  });
});
runHealth();     // 进页面即探测一次，让"不可达"立刻可见（不静默）
