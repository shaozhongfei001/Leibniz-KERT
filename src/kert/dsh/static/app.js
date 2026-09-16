/* DSH — 知识服务平台前端逻辑 */
(function () {
  "use strict";

  const API = "/dsh/api";

  // ── 导航切换 ──
  const navLinks = document.querySelectorAll(".nav-link");
  const views = document.querySelectorAll(".view");

  function switchView(name) {
    views.forEach(v => v.classList.toggle("active", v.id === "view-" + name));
    navLinks.forEach(a => a.classList.toggle("active", a.dataset.view === name));
    if (name === "dashboard") loadDashboard();
    if (name === "skills") loadSkills();
    if (name === "jobs") loadJobs();
  }

  navLinks.forEach(a => a.addEventListener("click", e => {
    e.preventDefault();
    switchView(a.dataset.view);
  }));

  // ── 仪表盘 ──
  async function loadDashboard() {
    try {
      const res = await fetch(API + "/dashboard");
      const d = await res.json();
      setText("stat-entities", d.entity_count ?? "—");
      setText("stat-relations", d.relation_count ?? "—");
      setText("stat-statements", d.statement_count ?? "—");
      setText("stat-rules", d.rule_count ?? "—");
      setText("stat-skills", d.skill_count ?? "—");
      setText("stat-jobs-running", d.jobs_running ?? "—");
      setText("stat-jobs-completed", d.jobs_completed ?? "—");
      setText("stat-jobs-failed", d.jobs_failed ?? "—");
      const info = `工作区: ${d.workspace || "—"}` +
        (d.data_version ? ` | 数据版本: ${d.data_version}` : "") +
        (d.service_id ? ` | 服务: ${d.service_id}` : "") +
        ` | 投影就绪: ${d.projections_ready ? "是" : "否"}`;
      setText("workspace-info", info);
    } catch (e) {
      setText("workspace-info", "加载失败: " + e.message);
    }
  }

  // ── 技能管理 ──
  let allSkills = [];

  async function loadSkills() {
    try {
      const res = await fetch(API + "/skills");
      const d = await res.json();
      allSkills = d.skills || [];
      renderSkills(allSkills);
    } catch (e) {
      document.getElementById("skill-list").innerHTML =
        '<div class="empty-state">加载失败: ' + esc(e.message) + "</div>";
    }
  }

  function renderSkills(skills) {
    const el = document.getElementById("skill-list");
    if (!skills.length) {
      el.innerHTML = '<div class="empty-state">暂无已注册技能</div>';
      return;
    }
    el.innerHTML = skills.map(s =>
      '<div class="list-item" data-skill-id="' + esc(s.skillId) + '">' +
        '<span class="item-id">' + esc(s.skillId) + '</span>' +
        '<span class="item-meta">' + esc(s.name || "") + " v" + esc(s.version || "?") + '</span>' +
      "</div>"
    ).join("");
    el.querySelectorAll(".list-item").forEach(item => {
      item.addEventListener("click", () => openExecPanel(item.dataset.skillId));
    });
  }

  document.getElementById("skill-search").addEventListener("input", e => {
    const q = e.target.value.toLowerCase();
    renderSkills(allSkills.filter(s =>
      s.skillId.toLowerCase().includes(q) || (s.name || "").toLowerCase().includes(q)
    ));
  });

  function openExecPanel(skillId) {
    const panel = document.getElementById("skill-exec-panel");
    panel.classList.remove("hidden");
    document.getElementById("exec-skill-id").value = skillId;
    document.getElementById("exec-result").classList.add("hidden");
  }

  document.getElementById("exec-btn").addEventListener("click", async () => {
    const skillId = document.getElementById("exec-skill-id").value;
    const requestId = document.getElementById("exec-request-id").value || undefined;
    let reqData;
    try {
      reqData = JSON.parse(document.getElementById("exec-request").value || "{}");
    } catch (e) {
      alert("请求参数 JSON 格式错误");
      return;
    }
    const resultEl = document.getElementById("exec-result");
    resultEl.classList.remove("hidden");
    resultEl.textContent = "执行中…";
    try {
      const res = await fetch(API + "/skills/execute", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ skillId, requestId, request: reqData }),
      });
      const d = await res.json();
      resultEl.textContent = JSON.stringify(d, null, 2);
    } catch (e) {
      resultEl.textContent = "执行失败: " + e.message;
    }
  });

  // ── 知识浏览 ──
  let currentAsset = "entities";

  document.querySelectorAll(".tab").forEach(tab => {
    tab.addEventListener("click", () => {
      document.querySelectorAll(".tab").forEach(t => t.classList.remove("active"));
      tab.classList.add("active");
      currentAsset = tab.dataset.asset;
      loadKnowledge(currentAsset);
    });
  });

  async function loadKnowledge(asset) {
    const el = document.getElementById("knowledge-list");
    el.innerHTML = '<div class="empty-state">加载中…</div>';
    try {
      const res = await fetch(API + "/knowledge/" + asset + "?limit=50");
      const d = await res.json();
      const records = d.records || [];
      if (!records.length) {
        el.innerHTML = '<div class="empty-state">暂无数据</div>';
        return;
      }
      el.innerHTML = records.map(r => {
        const id = r.entity_id || r.relation_id || r.statement_id || r.rule_id || r.id || "—";
        const meta = Object.entries(r).filter(([k]) => !k.endsWith("_id") && k !== "id")
          .slice(0, 3).map(([k, v]) => k + "=" + v).join(", ");
        return '<div class="list-item">' +
          '<span class="item-id">' + esc(String(id)) + '</span>' +
          '<span class="item-meta">' + esc(meta) + '</span>' +
        "</div>";
      }).join("");
    } catch (e) {
      el.innerHTML = '<div class="empty-state">加载失败: ' + esc(e.message) + "</div>";
    }
  }

  // ── 任务监控 ──
  async function loadJobs() {
    const filter = document.getElementById("job-filter").value;
    const el = document.getElementById("job-list");
    el.innerHTML = '<div class="empty-state">加载中…</div>';
    try {
      const url = API + "/jobs" + (filter ? "?status=" + filter : "");
      const res = await fetch(url);
      const d = await res.json();
      const jobs = d.jobs || [];
      if (!jobs.length) {
        el.innerHTML = '<div class="empty-state">暂无任务</div>';
        return;
      }
      el.innerHTML = jobs.map(j => {
        const bc = statusBadgeClass(j.status);
        return '<div class="list-item" data-job-id="' + esc(j.job_id) + '">' +
          '<span class="item-id">' + esc(j.job_id) + '</span>' +
          '<span class="badge ' + bc + '">' + esc(j.status) + '</span>' +
        "</div>";
      }).join("");
      el.querySelectorAll(".list-item").forEach(item => {
        item.addEventListener("click", () => showJobDetail(item.dataset.jobId));
      });
    } catch (e) {
      el.innerHTML = '<div class="empty-state">加载失败: ' + esc(e.message) + "</div>";
    }
  }

  document.getElementById("job-filter").addEventListener("change", loadJobs);
  document.getElementById("job-refresh").addEventListener("click", loadJobs);

  async function showJobDetail(jobId) {
    try {
      const res = await fetch(API + "/jobs/" + encodeURIComponent(jobId));
      const d = await res.json();
      alert(JSON.stringify(d, null, 2));
    } catch (e) {
      alert("获取任务详情失败: " + e.message);
    }
  }

  function statusBadgeClass(s) {
    if (s === "RUNNING") return "badge-running";
    if (s === "COMPLETED") return "badge-completed";
    if (s === "FAILED" || s === "CANCELLED") return "badge-failed";
    if (s === "BLOCKED") return "badge-blocked";
    return "";
  }

  // ── 工具 ──
  function setText(id, t) { document.getElementById(id).textContent = t; }
  function esc(s) { const d = document.createElement("div"); d.textContent = s; return d.innerHTML; }

  // ── 初始化 ──
  loadDashboard();
})();
