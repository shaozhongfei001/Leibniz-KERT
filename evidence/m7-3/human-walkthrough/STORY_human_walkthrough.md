# 六环链路 · 人类走查（Playwright 原图 + 故事）

> 目的：把「知识地图 → skill 路由 → 本体模型 → 业务语义 → LightRAG → 本体物化」用**真人会用的两个界面**
> （KERT 的 API 控制台 + 外部知识库 WebUI）走一遍，逐步留**原图**，供人眼复核"它真的转起来了"。
>
> ⚠ **非声明**：本组图是**可见面复核**，**不替代**自动化断言。六环的机械断言在
> `tests/integration/test_six_ring_chain_end_to_end.py`（CI 上跑；CI 无知识库实例时走"具名不可达"分支，
> 见 ADR-017 ⑦-a）。LightRAG 的答案**措辞**由模型生成、不具确定性 ⇒ 判据一律取**引用出处/字段值**。

## 怎么复跑（**一键**，可复现）

```bash
scripts/run_human_walkthrough.sh                 # KERT 侧（Swagger 环1→环3 + 六环工作台）
scripts/run_human_walkthrough.sh --full-chain    # 先把完整链造出来（⇒ 工作台的环 5/6 能取回链）
scripts/run_human_walkthrough.sh --with-lightrag # 再加知识库侧（需外部 LightRAG 在跑）
```

脚本自己做完：**临时工作区 provision → 独立端口起本仓 KERT（拒绝复用任何外部实例）→ 等就绪（超时即失败，
不"跳过"）→ 跑走查 → 收尾杀掉自己起的进程**。产出仍是本目录下的 PNG（原图，未裁剪未美化）。

手动兜底（等价于脚本内部做的事）：

```bash
.venv/bin/python -c "import sys; sys.argv=['kert','provision','-w','/tmp/human-ws',\
'-s','examples/bank-front-knowledge-maps','--init']; from kert.cli.main import app; app()"
KERT_PROFILE=dev KERT_SKILL_PACKAGES=$PWD/examples/bank-front-skills \
  .venv/bin/python scripts/serve_skill_service.py --port 8123 --workspace /tmp/human-ws &
.venv/bin/python evidence/m7-3/human-walkthrough/run_walkthrough.py --only kert   # kert|workbench|lightrag|all
```

依赖：Playwright（`pip install playwright`）+ **系统 Chrome**（脚本用 `channel="chrome"`，失败回退自带
chromium）。**未**改 `pyproject.toml`（仅本地工具）。

**UI 侧的机械冒烟**（不是人走查，是 CI 闸门）：`scripts/ci/ui_smoke.py` —— 用真人浏览器验
「两个页面能开 + 同源 css/js 无 4xx/5xx + 页面 JS 无异常且能调通本地 API」；CI job 名
`UI Smoke (DSH pages reachable — NOT chain verification)`，**只验可达性，≠ 链路验证**。

---

## 故事

**主角**：企业客户经理「小李」。**任务**：给客户 `CUST-CORP-0001` 做一次**外联准备**，
并把结果**沉淀进知识库**，好让同事以后能检索到。

### 环节 0 · 他先看系统能干什么 —— `S01_kert_swagger_overview.png`
打开 KERT 的 API 控制台（Swagger）。看到的是**能力全景**：健康、抽取、作业、本体/图、知识地图、
路由计划、技能执行……（不是一堆散接口，而是有分层的面）。

### 环节 1 · 这类任务该按哪张地图走？ —— `S02_ring1_knowledge_maps.png`
调 `GET /v1/knowledge-maps`，返回**三张地图**：
`KM-CORP-RM-OUTREACH`（外联准备）、`KM-CORP-RM-MEETING`（会面）、`KM-CORP-RM-PREVISIT`（访前）。
⇒ **环 1（知识地图）**：地图是"按任务分"的，不是一句 prompt。

### 环节 2 · 系统给的不是答案，是"放行的计划" —— `S03_ring2_routing_plan.png`
调 `POST /v1/routing/plan`（`taskType=OUTREACH_PREPARATION`，`subjectId=CUST-CORP-0001`）：
- `allowed = true`，`planId = AP-KERT-OUTREACH_PREPARATION-…`；
- **版本行同时钉住三样东西**：知识地图 `KM-CORP-RM-OUTREACH@1.0.0`、路由策略 `RP-KERT-BANKFRONT-001@1.0.0`、
  本体 `CTR-SEM-002@sha256:705578d6…`。

⇒ **环 2（skill 路由/计划门禁）** + **环 3（本体模型）**：**"能不能做、按什么做、依据哪个本体版本"在同一个计划里对齐**；
不填/不合法 ⇒ 拒绝（不是默认放行）。

### 环节 3 · 让技能出结果 —— `S04_ring3_skill_report.png`
调 `POST /api/skill/execute`（`skill-customer-previsit-report`，带 `evidenceTimestamp`）：
得到 `status=ok` 的**业务报告**（`reportTitle` / `executiveSummary` / `evidenceRefs` / `reportUrl`）。
⇒ **环 4（业务语义）**：出来的是**业务化的产物**（标题、摘要、证据引用），不是原始数据堆。

### 环节 4 · 没给新证据，系统**就是不出** —— `S05_policy_controlled_exit.png`
同一个技能，这次**只给 customerId**：
`status = exit_policy_no_new_evidence`，`assemblyTrace` 里 `evidence: blocked`。
⇒ 这是**受控退出**，不是报错：**"没有新证据就不产出结论"**是一条策略，而不是尽力而为。

### 环节 5 · 异步作业与业务状态 —— `S06a_job_accepted_202.png` / `S06b_job_status.png`
把任务丢成异步：受理返回 `jobId + status=PENDING`；再查作业端点看到**业务状态机**取值
（该值域已在合同侧由 4 值扩到 9 值，见 D-27）。
⇒ 长任务有**受理/状态**语义，人能"回来看它走到哪了"。

### 环节 6 · 换个工作面：知识库 —— `S07_lightrag_login.png`
他切到**知识库**（外部 LightRAG 实例的 WebUI，`v1.5.7`）——**另一个进程**，不是 KERT 的一个页面。

### 环节 7 · 知识库里躺着 KERT 的物化产物 —— `S08_lightrag_documents.png`
文档列表里能直接看到 KERT 的**本体物化产物**，其正文开头就是 KERT 自己写的**出处头**：
`- 产物路径: 04_serve/product_knowledge/version=2026.09.16.1/ONTOLOGY.md` +
`- sha256: 9d2ebc4c…`。
⇒ **环 6（本体物化）→ 环 5（发布）**：知识库里那条**就是**工作区里的那件产物（路径 + 摘要可核），
不是"另抄一份"。

### 环节 8 · 用大白话问，答案带着出处 —— `S09_lightrag_answer_with_citations.png`
他在检索框里问："客户 CUST-CORP-0001 的客户画像 与 产品利率 是什么？"
- **能答的部分**：给出经营与结算数据、数据治理信息（`数据来源种子`、`提取器`、`置信度 0.9`、`验证状态 APPROVED`、`版本 1.0`）；
- **答不了的部分**：明确写"**在提供的知识库中，未包含任何关于『产品利率』的信息**"，并建议去查别的数据源
  —— **不编造**；
- **出处摊开**：`References` 回指 KERT 产物路径：
  `03_core__customer__…CUST-CORP-0001.md`、`04_serve__product_knowledge__…__ONTOLOGY.md`、
  `04_serve__customer_knowledge__…__PROJECTION.md`。

⇒ **环 5（LightRAG）**：检索**可回溯到 KERT 产物**；且"不知道就说不知道"。

### 环节 9 · 看一眼全局 —— `S10_lightrag_graph.png`
知识图谱里同时站着两侧的东西：
- **KERT 产物侧**：`Projection`、`PROJECTION.md`、`Product Knowledge`；
- **本体侧**：`Ontology`、`Owl`、`Gits-Cbanking`（本体权威来自 gits 仓）。

左下角 `节点 78 / 边 86`（与实例 graphml 计数一致）。

### 环节 10 · 我们自己也有工作面：六环工作台 —— `S11_workbench_overview.png` / `S12_workbench_after_run.png`

前 9 步他要么在 **Swagger**（别人的界面）里逐个 Try it out，要么跳到**外部知识库**。
今年（2026-09-17）KERT 自己多了一个页面：`/dsh/rings` —— **按「环」组织**的工作台，点一次
「一键走一遍」就把 0 → 环 1 → 环 2/3 → 环 4 → 环 5/6 → 作业逐步走完，每步给人话小结 + 原始 JSON。

关键的一点：**环 5/6 用的是环 2 拿到的 `planId`** ——

- `S12` 里环 2 的小结：`放行：planId=AP-KERT-OUTREACH_PREPARATION-889e838c（planHash 889e838ca27c74d3）`；
- 环 5/6 的小结：`查询 id：AP-KERT-OUTREACH_PREPARATION-889e838c；complete=true`，
  链为 `plan → 04_serve → 04_serve/egress`。
⇒ **同一个 id 把「计划 → 物化 → 数据出口锚点」串起来了**（`scripts/run_human_walkthrough.sh --full-chain`
可一键复现；不带 `--full-chain` 时该工作区**没有活动投影**，环 5/6 会**如实**显示
`SERVICE_NOT_READY` 并说明"这条链还没走到物化"——**不装作成功**）。

---

## 一页对照表

| 原图 | 人做了什么 | 对应环 | 可核判据 |
|---|---|---|---|
`S01` | 打开 API 控制台 | — | 端点清单 |
`S02` | 查知识地图 | 环 1 | 三张 `KM-CORP-RM-*` |
`S03` | 要一个路由计划 | 环 2 + 环 3 | `allowed=true`；`planId`；`versions.ontology=CTR-SEM-002@sha256:…` |
`S04` | 让技能出报告 | 环 4 | `status=ok` + 业务字段 |
`S05` | 不给新证据 | 策略 | `exit_policy_no_new_evidence` + `evidence: blocked` |
`S06a/b` | 异步受理 + 查状态 | 作业 | `202 + jobId/PENDING`；`data.status` 状态机 |
`S07` | 切到知识库 | 环 5 入口 | 外部实例 WebUI `v1.5.7` |
`S08` | 看文档列表 | 环 6 → 环 5 | 产物路径 + `sha256` 出处头 |
`S09` | 自然语言提问 | 环 5 | `References` 回指 KERT 产物；无信息处**明说没有** |
`S10` | 看知识图谱 | 总览 | `节点 78 / 边 86`；含 KERT 产物节点与本体节点 |
`S11` | 打开六环工作台 | 总览 | 六个环各自的「执行」按钮 + 连接状态 |
`S12` | 点一次「一键走一遍」 | 环 1→环 5/6 | 环 2 的 `planId` **==** 环 5/6 查询用的 id；`complete=true` |

## 卫生与边界

- KERT 侧用**独立端口 8123** + `/tmp/human-ws` 供给态工作区，**未触碰**任何他人实例（8106）；
- 知识库侧**只做检索/浏览**：**未发布、未撤回、未清空**任何文档 ⇒ 共享语料零改动；
- 本轮开始时实例为 `5 篇文档 / graphml 78-86`，结束时**仍是**（与 D-34 复核口径一致）；
- 一键脚本会**拒绝**在已被占用的端口上跑（不复用外部实例），并在退出时杀掉**自己**起的 KERT。

## 附：做"工作台 + UI 冒烟"时**立刻抓到**的两个真缺陷（页面 200，界面却不可用）

浏览器一上来就暴露了两类"纯 HTTP 断言发现不了"的故障 —— `GET /dsh/ = 200` 一直是绿的：

1. **`/dsh/static/*` 全部 404**：`mount_dsh` 把静态挂载放在 SPA 兜底**之后** ⇒ 兜底先匹配并 404。
   实测：`/dsh/static/style.css` = 404、`/dsh/static/app.js` = 404 ⇒ 页面能开但**无样式、无脚本**。
   **已修**：`src/kert/dsh/app.py` —— 静态**先挂载**（先匹配），兜底只兜非静态路径。
2. **非 editable 安装不含 `kert/dsh/static/*`**：`pyproject.toml` 未声明 `package-data`。
   实测：`site-packages/kert/dsh/` 下**没有** `static/` ⇒ 界面恒 **503**（"DSH 界面未安装"）
   ⇒ 非 editable 安装/部署下 UI 不可用。
   **未修**（改 `pyproject.toml` 按本轮纪律需先报批）：建议补
   `[tool.setuptools.package-data]` → `"kert.dsh" = ["static/*"]`。
   ⇒ UI 冒烟 job 因此用 **editable 安装**（它验的是**本仓代码**的界面），该包装缺陷另行上报。
