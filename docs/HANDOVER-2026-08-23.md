# DKWS 交接文档（截至 2026-08-23，新会话起点）

> 本文件面向**新开的 DSH 会话**：读完本文 + 指向的文档即可无缝接手 DKWS 全部工作。
> 工作区根：`/home/szf/dev/deepseek_harness/data_knowledge_ws`（以下简称 `$WS`）
> 项目根：`$WS/dkws`（以下简称 `$DKWS`）

---

## 0. 一句话定位

DKWS = 文件目录型数据知识服务模拟平台（DKWS-SPEC-001 V1.0）：**文件系统为权威源**（五层工作区），
提供知识管道（接入→解析→抽取→审核→发布→投影）、检索/图谱/规则/溯源服务、以及 Skill 执行平台
（客户经理持续经营 + 服务建议书 + 交互记忆）。与 GITS（Java 工作台）按契约 v1.3/v1.4 对接，
**知识在 DKWS、业务在 GITS**。

## 1. 工作区结构

```
$WS/
  文件目录型数据知识服务模拟平台_详细需求与详细设计_V1.0.md   ← 权威需求设计（1751 行）
  dkws/                         ← 工程（Python 3.11，venv 在 dkws/.venv）
  demo_workspace/               ← 演示数据工作区（五层：01_raw/02_work/03_core/04_serve/90_control）
  bank_front_ws/                ← 银行前端 7 个 Skill ZIP 迁移工作区
  research_cache/ research_out/ ← 研究缓存/产出
```

## 2. 架构总览

图：`$DKWS/docs/architecture.md` + `$DKWS/docs/assets/*.png`（4 张：分层/运行时/execute 时序/部署拓扑）

- **五层**：01_raw（原始输入）→ 02_work（加工现场，run_id 隔离）→ 03_core（不可变版本资产：
  entities/relations/statements/segments/rules + RELEASE.md）→ 04_serve（可重建投影：Parquet + Kùzu 图 +
  指纹）→ 90_control（decisions/gates/jobs/audit）。
- **运行时**：FastAPI `:8106`；`/v1/*` 知识服务 + `/api/skill/*` 技能服务；LLM 适配器（DeepSeek/
  确定性回退）；Kùzu 图后端（ADR-011 受控变更，内存 BFS 回退）。
- **黄金路径**：ingest→parse→extract→review(APPROVE)→publish→projection→query/graph/skill。

## 3. 已落地设计清单（按版本）

### 3.1 DKWS 核心（SPEC V1.0 + ADR-001~011）
- 26 个 SchemaSpec（`src/dkws/domain/contracts/specs.py`）；FR 码；退出码 0/2/3/4/5。
- 管道组件：`ingest / parse_doc / extract / review / publish / projection / rollback / jobs / gates`。
- 服务：`KnowledgeService`（search 全文/向量/混合、data_query、get_entity、graph(neighbor|closure|paths,
  Kùzu 后端+内存回退, max_depth≤10, 方向拆防环)、evaluate_rule、trace、catalog）。
- **ADR-011**：Kùzu 作为可重建投影层（单文件库 + `graph.PROJECTION.json` 指纹），非权威源。
- E2E：`tests/e2e/test_golden_scenario.py`（golden 场景，曾 197+ 用例全绿；含 LLM 慢用例）。

### 3.2 v1.3 数据所有权（2026-08-22）
- **知识全在 DKWS，GITS 只传 `customerId`**；旧字段（structuredFacts 等）忽略、不参与 evidence 判定。
- 客户知识库服务 `customer_knowledge`：`scripts/seed_customer_knowledge.py`（幂等，多客户结构）落库
  **CUST-CORP-0001 华东精工** 与 **CUST-CORP-0002 华东新能源**（互为上下游，7 条 KI/户 + 供应链图）。
- 取数层 `application/customer_knowledge.py`：`ki_map(entity/supply_chain/interpretation)`。
- R1 改造：evidence ok/skipped 只反映库命中；`data.sections` 按 KI 出章（heading 含 KI 编号）；
  无新证据策略保留（evidenceTimestamp 缺失/未更新 → `exit_policy_no_new_evidence`）。
- 图谱 Skill：只认 customerId，库构建 `data.result`（model=library，无 LLM）。
- **CRM 主档投影（交付物 A）**：`examples/output/gits-crm-customer-master.json`（20 字段 camelCase、
  枚举/日期/金额内建校验）→ 同步 gits `docs/dd/`；交付物 B = 造数脚本（--gits-base 可 PUT upsert）。
- 契约 v1.3：`docs/skill-execute-api-contract.md`（同步 gits docs/dd/）；回传包 `docs/v13-return-to-gits.md`。

### 3.3 v1.4 SP-20/SP-21（2026-08-23，Phase 1-3 全部完成）
- **SP-20 对公客户服务建议书**：`application/service_proposal.py` + `proposal_rules.py`
  - 资产 `skills/service-proposal/`：8 章模板 + 5 配套表 + 行业框架（TAXONOMY≈15 类 + 3 类演示）+
    财务框架 + 激活合同（AC-SERVICE-PROPOSAL-001/002、AC-ONGOING-ENGAGEMENT-001）+ 闸门资产
    `gates/GATE-BIZ-G0..G5.md`。
  - 逐章并行（≤3 路 LLM）→ 结构化 claims（F/C/B/H/P/A 事实标签）→ 6 条 BLOCKING 规则校验
    → 内部版 + 对客版（段落级仅 F/A + filteringNotes + releaseBlockedUntil）→ gateRecommendations。
  - **异步**：`"async":true` → 202+jobId → 轮询 `GET /v1/jobs/{id}`（完成含 `data.skill_result`）。
- **SP-21 交互记忆抽取**：`application/interaction_memory.py`
  - LLM 抽取候选（5 类别/置信度/衰减规则 NONE|LINEAR|STEP/原文引用）+ 确定性比对（REINFORCE/SUPERSEDE）
    + 3 规则（CONFIDENCE_CALIBRATION/DECAY_RULE_APPLICATION/DUPLICATE_DETECTION）。
  - **DKWS 不存记忆**：结果交 GITS InteractionMemoryPort 持久化。
- **闸门协作端点**：`GET /api/skill/gates/{customerId}`（清单资产）、`POST /api/skill/gates/audit`
  （决策镜像，非权威，追加 `90_control/audit/gates.jsonl`）。**闸门状态机权威在 GITS**。
- 契约 v1.4：`docs/skill-execute-api-contract-v1.4.md`（同步 gits docs/dd/）。
- 真实样例：`docs/gits-integration-samples-v14.md` → gits `docs/architecture/DKWS-V1.4-GITS-INTEGRATION-SAMPLES.md`。
- 联调计划：`docs/v14-joint-debugging-plan.md` → gits `docs/architecture/DKWS-V1.4-JOINT-DEBUGGING-PLAN.md`。

### 3.4 DSH 集成与其它
- **DSH Computer Use**：Playwright MCP 桥接（`~/.dsh/profiles/web/cordis.patch.yml` 的 mcp-computer 行，
  headless chrome），工具 `mcp__computer__*`；安装记录 `docs/dsh-computer-use-install.md`。
- **dkws-1 面板插件**（动态插件，会话内定义；刷新后需重新激活）。
- **供应链图谱演示**：`scripts/gen_supply_chain_demo.py`（24 节点）、`gen_bank_supply_chain_scale.py`
  （1064 节点/1056 边，supply_chain_graph 服务）、`gen_supply_chain_view.py`（Neo4j 风格可视化 HTML，
  `examples/output/supply_chain_graph_1064.html` + vendor/vis-network.min.js）。

## 4. 契约速查（GITS 对接用）

| 版本 | 要点 | 文档 |
|---|---|---|
| v1.3 | R1/图谱只传 customerId；sections 按 KI；无新证据策略 | `docs/skill-execute-api-contract.md` |
| v1.4 | SP-20（ContextPackage+async+ServiceResult+ruleViolations）、SP-21、闸门端点 | `docs/skill-execute-api-contract-v1.4.md` |

响应顶层：`{requestId, status(ok|skill_error|exit_policy_no_new_evidence), data, errors, assemblyTrace, modelCalls}`
（v1.4 不新增顶层枚举；SP-20 用 `data.result.status=SUCCESS|PARTIAL`）。错误：未知技能 404、坏请求 422、
幂等同 requestId TTL 10min、SP-20 必须 async（202+轮询 3s/3min）。

## 5. 运行状态与环境

| 项 | 值 |
|---|---|
| 服务 | systemd 用户服务 `dkws-skill`（`systemctl --user status/restart dkws-skill`；需 `export XDG_RUNTIME_DIR=/run/user/$(id -u)` + 全权限） |
| 端口 | 8106（0.0.0.0）；DSH GUI 3080 |
| **当前 LAN IP** | `192.168.31.220`（**旧 172.22.90.134 已失效**；GITS 设 `DSH_BASE_URL=http://192.168.31.220:8106`） |
| LLM | DeepSeek（`~/.dsh/.credentials.yaml` 密钥由 `serve_skill_service.py` 注入，不落盘）；未配置自动回退确定性适配器 |
| 造数 | CUST-CORP-0001/0002 已落库（customer_knowledge 最新投影）+ CRM 夹具 2 户 |
| 测试 | 集成 137 用例全绿（`cd $DKWS && .venv/bin/python -m pytest tests/integration -q`）；e2e golden 场景含 LLM 慢用例，单独跑 |

## 6. 关键命令

```bash
# 测试
cd $DKWS && .venv/bin/python -m pytest tests/integration -q
# 造数（幂等；GITS upsert 发布后加 --gits-base）
.venv/bin/python scripts/seed_customer_knowledge.py -w ../demo_workspace
# 服务重启
export XDG_RUNTIME_DIR=/run/user/$(id -u) && systemctl --user restart dkws-skill
# 健康/技能
curl -s http://127.0.0.1:8106/api/skill/health
# 图谱可视化静态服务（examples/output）
python3 -m http.server 8090 --directory examples/output   # 后台运行
# 时序/部署图渲染（mmdc，需 puppeteer 配置指向系统 chrome）
mmdc -i x.mmd -o x.png -p /tmp/puppeteer.json -b transparent -w 1600
```

## 7. 已知坑与约束（务必先读）

1. **bash 的 /tmp 每次命令隔离**：跨命令共享临时文件要用 `$WS` 下持久路径。
2. **沙箱**：工作区外写入（`~/.dsh`、`~/dev/gits-*`）需要更宽权限；本会话曾全程 danger-full-access
   （审批策略已改 never：文件策略 danger-full-access，禁止再请求升级，直接写）。
3. **H2/GITS**：GITS H2 内存库重启需重灌 `gits-crm-customer-master.json`。
4. **报告页非契约**：`reportUrl` 仅调试跳转；GITS 只消费 execute JSON。
5. **幂等/作业**：execute 同 requestId 10min；异步同 requestId 复用 job（job id 已修复撞号：
   `_resolve_job_id` 扫描同类型最大 seq+1）。
6. **投影器**：x_* 扩展字段透传（含 `_pad_x_fields` 补键，防止 from_pylist 丢列）；客户实体 x_ 字段=
   CRM 身份 + 对手方金额合并。
7. **行业映射**：ContextPackage.industry（"一级-二级"）→ INDUSTRY-TAXONOMY 代码，未命中 OTHER。

## 8. 未完成 / 待办（下一步）

- **GITS 侧联调**（主要）：GITS 已收全套材料（契约 v1.3/v1.4、样例包、联调计划、架构评审、
  CodeBuddy Tech Lead 提示词 `codebuddy-techlead-prompt-v14.txt`）。联调时若契约/行为不一致，
  DKWS 侧定位修复即可。可选项：起一个 execute 请求/响应监听便于对账。
- 可选小项：SP-21 记忆候选报告模板（`/api/skill/report` 卡片）；行业框架从 3 类扩到 15 类；
  1064 节点图谱客户按流程出 CRM 投影（如需）；建议书落库（03_core 知识化 segments/statements）尚未做
  （当前 SP-20 只生成不落权威库，符合 v1.4 边界）。
- 无遗留红测：`tests/integration` 全绿。

## 9. 新会话起步建议

1. 读本文档 + `docs/architecture.md`（含 4 张 PNG）；
2. 跑一次 `pytest tests/integration -q` 确认环境自洽；
3. `curl 127.0.0.1:8106/api/skill/health` 确认 12 技能在线；
4. 需要看真实链路：按 `docs/v14-joint-debugging-plan.md` 的 L-02/L-03/L-10 各打一遍；
5. 接手新任务前先 `git status`/`git log` 风格盘点（本目录无 git 历史，以文档为准）。
