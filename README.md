# DKWS — 文件目录型数据知识服务模拟平台

依据 DKWS-SPEC-001 V1.0（`文件目录型数据知识服务模拟平台_详细需求与详细设计_V1.0.md`，状态 `DRAFT_CANDIDATE`）在 DSH 底座上实现的知识服务平台。

## 文档索引

| 文档 | 说明 |
|------|------|
| [START_HERE.md](START_HERE.md) | 快速上手指南 |
| [API 参考](docs/API.md) | HTTP API 端点 + CLI 命令完整参考 |
| [部署指南](docs/DEPLOYMENT.md) | 安装、配置、启动、Docker/Systemd 部署 |
| [架构说明](docs/architecture.md) | 系统架构图（分层/运行时/时序/部署拓扑） |
| [开发规范](docs/development/) | Agent 角色、流程、规则、Python/Java 标准 |
| [SKILL_PLATFORM_ARCH.md](SKILL_PLATFORM_ARCH.md) | Skill 平台架构设计 |
| [ADR.md](ADR.md) | 架构决策记录 |
| [REQUIREMENTS_MATRIX.md](REQUIREMENTS_MATRIX.md) | 需求追踪矩阵 |

## 定位

- 不依赖数据库、消息队列、分布式平台的**单工作区文件系统模拟平台**；
- 权威源为**契约化 Markdown**（`01_raw`/`02_work`/`03_core`/`04_serve`/`90_control` 五层）；
- 批量投影为 **Parquet**，服务交换为 **JSON**，原始事件日志为 `.log`；
- CLI 为强制接口（`dkws`），HTTP API 为可选薄层。

## 核心功能

| 功能 | 说明 |
|------|------|
| 工作区管理 | 五层目录结构（01_raw→02_work→03_core→04_serve，90_control 治理） |
| 数据接入 | CSV/JSON 接入、哈希校验、幂等控制、对账拒绝 |
| 结构化数据清洗 | 字段映射、Parquet 投影、血缘追踪 |
| 文档处理 | PDF/DOCX/TXT 解析、规范化、稳定切片 |
| 知识抽取与审核 | 候选抽取、同名/矛盾检测、审核消歧、规则 DSL |
| Core 发布 | Release+CURRENT 指针、版本回滚 |
| Serve 投影 | 实体/关系/声明/片段/向量/规则/数据集/图谱投影 |
| 知识服务 | 全文/向量/混合检索、数据查询、图谱查询、规则评估、证据溯源 |
| Skill 平台 | 外联脚本/会面脚本/服务建议书/交互记忆抽取等可插拔 Skill |
| Kùzu 图谱 | 嵌入式图数据库投影，Cypher 查询加速，自动回退内存 BFS |
| LLM 集成 | 可插拔 LLM 适配器（OpenAI 兼容），未配置时确定性回退 |
| 运行时加固 | API Key 认证、限流、并发控制、数据脱敏、可观测性 |

## 环境

- Python 3.11+（已用 3.11.7 验证）
- 依赖：typer、PyYAML、pyarrow、pypdf、python-docx（HTTP API 另需 fastapi/uvicorn）

## 安装

```bash
cd dkws
python3 -m venv --system-site-packages .venv
.venv/bin/pip install -e ".[dev]"
```

## 快速开始

```bash
# 初始化工作区
.venv/bin/dkws init --workspace ../demo_workspace --force
.venv/bin/dkws validate --workspace ../demo_workspace

# 端到端黄金场景演示（product 领域，规格 §18.3）
.venv/bin/python examples/product_demo/run_demo.py \
  --workspace ../demo_workspace --dkws .venv/bin/dkws
```

演示覆盖：接入（22 输入→20 通过/2 拒绝对账）→ 文档解析切片 → 候选抽取（全部 CANDIDATE）→ 同名/矛盾检测 → 审核消歧 → Core 发布（Release+CURRENT）→ Serve 投影（实体/关系/声明/片段/向量/规则/数据集）→ 查询/检索/规则/图谱/溯源 → 全量校验。

## 常用命令

```bash
dkws init --workspace W [--force]
dkws inspect --workspace W [--output json]
dkws ingest --workspace W --domain product --source f.csv --idempotency-key k
dkws process-data --workspace W --domain product --batch B --schema product \
  --mapping-json '{"key_policy":"product_id","field_mappings":[...]}'
dkws parse-doc --workspace W --domain product --batch B
dkws extract --workspace W --domain product --batch B --run-id R
dkws review --workspace W --domain product --objects <候选路径> \
  --decision APPROVE --reason 说明
dkws publish --workspace W --domain product --run-id R
dkws build-projection --workspace W --domain product
dkws query-data|search|get-entity|graph|evaluate-rule|trace --workspace W ...
dkws validate --workspace W --mode full
dkws job --job-id JOB-...
dkws rollback --workspace W --scope product --to-version V --reason 原因
```

退出码：`0` 成功；`2` 参数/合同错误；`3` 质量门禁失败；`4` 冲突/锁；`5` 内部错误（规格 §12.1）。

## HTTP API（可选）

```bash
# 启动服务（FastAPI 薄层，仅协议适配）
.venv/bin/python examples/product_demo/serve_api.py \
  --workspace ../demo_workspace --port 8100

# 端点见规格 §13（已运行时验证）：
# GET  /v1/health          GET  /v1/catalog
# POST /v1/search          POST /v1/data/query
# POST /v1/graph/query     POST /v1/rules/evaluate
# GET  /v1/entities/{id}   GET  /v1/evidence/{id}
# POST /v1/extractions     GET  /v1/jobs/{job_id}
```

## DSH 集成

运行 `dkws-1` 动态插件（DKWS 知识服务平台面板）后，在 Run 卡片中可直接：
- 查看工作区概览（五层目录、版本指针、过期锁）；
- 调用知识服务：检索（全文/向量/混合）、数据查询、规则评估、图谱、证据溯源；
- 执行任意 `dkws` 子命令（只读服务或写操作均可，服务层保证只读活动投影）。

## 测试

```bash
.venv/bin/python -m pytest tests/ -q    # 192 个测试：单元/合同/集成/E2E/安全/恢复
```

测试分布：unit（工作区/路径/哈希/Markdown/Schema）、contract（26 类合同合法非法样例）、
integration（接入/数据/文档/知识/发布/投影/服务/API）、e2e（§18.3 黄金场景）、
security（路径穿越/伪装/注入/DOCX 只读）、recovery（半发布/重建/幂等/回滚）。

## 阶段状态

| 阶段 | 内容 | 状态 |
|---|---|---|
| P0 | 项目骨架、工作区初始化（init/inspect/validate/recover） | 完成 |
| P1 | 契约化 Markdown 框架（26 类合同 + Schema 校验 + 状态机） | 完成 |
| P2 | Raw 接入（Manifest/哈希/幂等/任务控制/锁） | 完成 |
| P3 | 结构化数据清洗与 Parquet（对账/拒绝/血缘） | 完成 |
| P4 | 文档登记/规范化/稳定切片（PDF/DOCX/TXT 适配器） | 完成 |
| P5 | 知识候选/审核决定/冲突检测/规则 DSL | 完成 |
| P6 | Core 发布/Release/CURRENT/回滚 | 完成 |
| P7 | Serve 投影（实体/关系/声明/片段/向量/规则/数据集） | 完成 |
| P8 | CLI 服务命令 + HTTP API | 完成 |
| P9 | E2E 黄金场景 + 安全/恢复测试 + 文档 | 完成 |
| P10 | DSH 动态插件（知识服务平台 Web 界面） | 运行中 |

状态声明：`IMPLEMENTED_PENDING_QA`（规格 §20.5：独立 QA 尚未执行）。规格本身仍为 `DRAFT_CANDIDATE`，
未获 Owner 批准、未基线化、未验收。实现决策见 `ADR.md`，需求追踪见 `REQUIREMENTS_MATRIX.md`。

## 客户经理持续经营 Skill 平台（新增能力）

DKWS 工程内实现"客户经理持续经营 Skill 运行平台"（依据 `docs/dd/改造-客户经理持续经营Skill-v2-*` 两份设计）：

- **两个独立 Skill**：外联脚本 / 会面脚本（`skills/customer-engagement/` 资产 + `application/skills.py` 执行器；R1 拜访报告已于 2026-08-21 下线移除）；
- **端点**（DKWS HTTP API）：`POST /api/skill/execute`、`GET /api/skill/health`；
- **治理**：fail-closed、requestId 幂等、assemblyTrace/modelCalls、日志脱敏；
- **模型**：可插拔 LLM 适配器（`infrastructure/adapters/llm.py`）——配置 `DKWS_LLM_BASE_URL/API_KEY/MODEL` 走 OpenAI 兼容；未配置时确定性适配器端到端；
- **DKWS 协作**：skill 执行前经平台知识服务检索客户片段，注入知识上下文与证据引用（fail-open）；
- **DSH 资产**：SKILL.md 同步于 `deepseek-harness/skills/customer-engagement/` 供 DSH `ctx.skills` 发现。

验证：`tests/integration/test_skills.py`（13 项）+ `examples/skill_e2e.py`（D1-D6 真实 HTTP，12/12 PASS）。
详见 `SKILL_PLATFORM_ARCH.md`。

## bank-front Skill 族加载与示例数据迁移（新增）

从 `袁阳` 目录加载 7 个 Skill ZIP（`bank-front-*`：承诺话术/八维/事实对账/KYC 缺口/产品推荐/报告组装/供应链图谱），每个含 `SKILL.md` + `assets/example-input.json` + `references/{input-schema, mock-input-data, output-schema}`。

- **加载**：`scripts/unzip_skills.py` 安全解压（防路径穿越/超限）到 `examples/bank-front-skills/`；DKWS Skill 平台自动发现并注册（`application/skills.py` 外部包加载器：读 SKILL.md 指令 + output-schema 约束，通用契约 executor），`/api/skill/health` 列出 10 个 Skill，示例输入执行 **7/7 运行成功**。
- **示例数据迁移**（DKWS 五层规划）：`scripts/migrate_bank_front_data.py`
  - `01_raw/bank_front/batch=*`：每 Skill 一个不可变批次（example_input.json + mock_input_data.json + MANIFEST.md + SHA-256）
  - `02_work/bank_front/run=*`：JSON→Parquet 规范化（主键 customerId，血缘列完整）
  - `04_serve/bank_front_data/version=*`：7 个数据集投影 + PROJECTION.md + CURRENT.md
  - 工作区一致性校验 **PASS（0 项发现）**
- 迁移目标工作区：`../bank_front_ws`（干净工作区，避免 demo_workspace 外部文件干扰）

## Kùzu 图谱投影（IMP-ADR-011 受控变更，2026-08-21）

业务方确认方案 B：DKWS 引入 **Kùzu 嵌入式图数据库**作为知识图谱查询加速层（投影，非权威源）。

- **构建**：`build-projection` 自动从 entities/relations 投影构建 Kùzu 图（`04_serve/<svc>/version=*/graph` 单文件 + `graph.PROJECTION.json` 指纹）；
- **查询**：`graph()` 新增 Kùzu 后端（Cypher），`mode=neighbor|closure|paths`，深度上限放宽到 10；kuzu 不可用自动回退内存 BFS（fail-open）；
- **边界**：图库仅从 `03_core` 投影构建、位于 `04_serve` 可重建层、查询回传权威 ID+证据、纳入可重建性测试；`03_core` 仍为唯一权威源；
- CLI：`dkws graph --start <实体ID> --depth 3 --mode paths`；
- 测试：`tests/integration/test_kuzu_graph.py`（构建/可重建/查询后端/validate 豁免）。

## 供应链演示图谱（2026-08-21）

`scripts/gen_supply_chain_demo.py` 生成**合成演示**多级供应链图谱（源 `DEMO-SUPPLY-CHAIN-20260821`，非真实客户事实）：
- 24 节点 / 25 边：杭州智造精密齿轮（中游）± 3 级上游（轴承/特钢/密封/传感器→钢坯/铁矿/合金→矿石/焦化/镍/铜）+ 2 级下游（主机厂/总成→整车/装配基地）；
- 发布到 `demo_workspace` 的 `supply_chain` 域，服务 `supply_chain_graph`（投影自动建 Kùzu 图，指纹 `{nodes:24, edges:25}`）；
- 对外查询（8106）：`POST /v1/graph/query` 传 `"service":"supply_chain_graph"` + `mode:closure/paths`；
- 示例：核心企业上游闭包 17 节点（3 级）；铁矿石→核心→整车路径枚举 12 条。

## 规模化供应链模拟图谱（2026-08-21，1064 节点 / 1056 边）

`scripts/gen_bank_supply_chain_scale.py` 生成**合成**多客户多级供应链图谱（源 `DEMO-BANK-SC-20260821`，非真实事实）：
- 8 核心客户 × 4 级上游(3 分支=120 供应商) + 2 级下游(3 分支=12 客户)，共 1064 节点 / 1056 边；
- 拓扑：上游边 `供应商→核心`（IN 可达上游）、下游边 `核心→客户`（OUT 可达下游）；
- 发布 `supply_chain` 域 → 服务 `supply_chain_graph`（Kùzu 图，指纹 `{nodes:1064, edges:1056}`）；
- **性能实测**（Kùzu 后端）：上游闭包 121 节点 **75ms**、下游闭包 13 节点 77ms、路径枚举 60ms、邻居 72ms（中位，含连接开销；查询本身毫秒级）；
- 对外：`POST /v1/graph/query` + `"service":"supply_chain_graph"`，8106 实测闭包 121 节点；
- 脚本参数：`--customers/--up-levels/--branch/--down-levels` 可调规模。

修复记录：下游边方向拓扑缺陷（原统一 child→parent 致核心无出边）、publish 幂等键纳入 run_id（失败可重试）、paths 环路修复（BOTH 拆方向）。

## 图谱可视化（Neo4j 风格，2026-08-21）

`scripts/gen_supply_chain_view.py` 从最新图谱版本 parquet 生成**自包含**浏览器可视化
`examples/output/supply_chain_graph_1064.html`（引用同目录 `vendor/vis-network.min.js`，离线可用）：
- **力导向布局**（vis-network barnesHut 物理模拟，Neo4j Browser 同款风格）：暗色画布、节点彩色发光（核心红/上游蓝/下游青）、带箭头有向边、选中高亮最近邻（其余变暗）、关系标签（悬停/选中显示 SUPPLIES）、缩放或悬停显示节点名、搜索定位、拖拽/缩放/双击聚焦、复位视图、力导向开关；
- 用法：`.venv/bin/python scripts/gen_supply_chain_view.py [--version DIR]`；
- 本地预览：`python3 -m http.server 8090 --directory examples/output` → `http://127.0.0.1:8090/supply_chain_graph_1064.html`（或直接双击 HTML）。

## v1.3 数据所有权改造（2026-08-22）

知识全在 DKWS，GITS 只传 `customerId`（+ 可选 `visitObjective`/`evidenceTimestamp`）：
- **客户知识库服务 `customer_knowledge`**：`scripts/seed_customer_knowledge.py` 落库主客户
  `CUST-CORP-0001 华东精工装备集团有限公司`（7 条 KI 片段 + 客户实体 + 6 供应链对手方 + 6 条 SUPPLIES 关系，
  经 review→publish→projection 全链路，Kùzu 图 7 节点/6 边）；投影器新增 `x_*` 扩展字段透传。
- **取数层 `application/customer_knowledge.py`**：`ki_map(customerId)`（KI 片段）、`entity`、
  `supply_chain(customerId)`（nodes/edges/buildStatus）、`interpretation`（确定性派生，不虚构）。
- **R1 previsit**：evidence ok/skipped 只反映知识库对该客户+KI 是否取到数；`data.sections` 按命中的 KI 出章
  （heading 含 KI 编号、content 为库中原文）；无新证据策略保留（`evidenceTimestamp` 未传/未更新 → `exit_policy_no_new_evidence`）。
- **bank-front-supply-chain-graph**：只认 `customerId`，从库构建 `data.result`（无 LLM，`model=library`），
  输入不足 → `partial` 且不虚构。
- **外联/会面**：同一数据所有权（KI-009/004/005/006 取数）。
- **CRM 主档投影（交付物 A）**：`examples/output/gits-crm-customer-master.json`（20 字段、camelCase、无知识字段），
  已同步 gits `docs/dd/gits-crm-customer-master.json`；造数脚本即交付物 B（可复现落库）。
- 测试：`tests/integration/test_skills.py`（25 用例：库命中/未知客户/旧字段兼容/无新证据策略/库构建图谱）。

## 系统架构图（2026-08-23）

`docs/architecture.md`（Mermaid 源 + 分层/组件/数据流说明），PNG 渲染见 `docs/assets/`：
- `dkws-architecture-layers.png`：五层工作区 + 数据管道（01_raw→02_work→03_core→04_serve，90_control 治理）
- `dkws-architecture-runtime.png`：运行时服务架构（消费方 / API / 应用层 / 基础设施 / 数据 / 外部集成）
- `dkws-sequence-execute.png`：时序图（GITS 调 execute 完整链路：customerId→取数→evidence→LLM→sections 回传）
- `dkws-deployment-topology.png`：部署拓扑（8106 / DSH :3080 / GITS :8080 / H2 内存库）

## v1.4 SP-20 服务建议书（Phase 1，2026-08-23）

- **技能**：`SP-20 对公客户服务建议书生成`（HYBRID：确定性装配 + 逐章并行 LLM + 规则校验 + 确定性双版本过滤）
- **资产**：`skills/service-proposal/`（8 章模板 + 5 配套表 + 行业框架 3 类演示 + 财务框架 + AC-SERVICE-PROPOSAL-001）
- **契约 v1.4**：`/api/skill/execute` 支持 `request.context`（ContextPackage）与 `"async":true`（202+jobId，轮询 `/v1/jobs/{id}`）；响应 `data.result`=ServiceResult + `data.ruleViolations`
- **规则**：6 条 BLOCKING（CITATION_REQUIRED / NO_UNDISCLOSED_DEGRADATION / DUAL_VERSION_PRINCIPLE / GATE_SEQUENCING / FACT_LABEL_MANDATORY / NO_COMMITMENT_WITHOUT_APPROVAL）
- **双版本**：内部版（全标签+内部判断/待审批）+ 对客版（段落级仅 F/A + filteringNotes + releaseBlockedUntil G1-G3，放行权在 GITS）
- 测试：`tests/integration/test_service_proposal.py`（同步/异步/双版本/规则/报告）
- 实时验证：真实 DeepSeek 8 章并行 27s 完成，67 条引用/36 未知项/0 违规，报告页见 `sp20-report.png`

## v1.4 SP-20 Phase 2（闸门协作，2026-08-23）

- **闸门清单资产**：`skills/service-proposal/gates/GATE-BIZ-G0..G5.md`（权威清单，GITS 只读/推进）
- **端点**：`GET /api/skill/gates/{customerId}`（清单资产）；`POST /api/skill/gates/audit`（业务闸门决策**镜像**，非权威，追加 `90_control/audit/gates.jsonl`；权威在 GITS）
- **SP-20 UPDATE 路径**：`proposalType=UPDATE` → routeMode=MAP_FIRST（交互记忆优先 + previousVersion 注入）；G1-G3 已过 → `releaseBlockedUntil=[]`（对客版可放行，放行动作仍由 GITS 发起）
- 测试：`test_service_proposal.py` 9 用例（+闸门清单/审计/UPDATE 放行）；全量集成 129 用例绿

## v1.4 Phase 3（SP-21 交互记忆抽取，2026-08-23）

- **技能**：`SP-21 交互记忆抽取`（LLM 抽取候选 + 确定性比对 + 3 规则校验；**DKWS 不存记忆**，candidates/updates/supersessions 交 GITS `InteractionMemoryPort` 持久化）
- **输入**：`request.context = {interactionId, interactionContent, existingMemories[]}`；输出：`candidateMemories[]`（类别/置信度/建议衰减规则/原文引用）+ `memoryUpdates[]`（REINFORCE）+ `memorySupersessions[]`（否定取代）
- **规则**：CONFIDENCE_CALIBRATION / DECAY_RULE_APPLICATION / DUPLICATE_DETECTION
- **激活合同**：`AC-SERVICE-PROPOSAL-002`（UPDATE/MAP_FIRST）+ `AC-ONGOING-ENGAGEMENT-001`（持续经营记忆积累）
- **E2E 链路**：交互 → SP-21 抽取 →（确认）→ SP-20 UPDATE（MAP_FIRST + 记忆注入引用）→ 对客版放行
- 测试：`test_interaction_memory.py` 9 用例；全量集成 137 用例绿
- 实时验证：真实 DeepSeek 抽取 4 候选（BUSINESS_SIGNAL/PREFERENCE/DECISION_PATTERN），自动 REINFORCE 旧记忆（相似度 1.00），0 违规
