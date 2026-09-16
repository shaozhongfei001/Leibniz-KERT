# CANDIDATE：M7.1 KnowledgeSource typed capability（设计候选）

```text
DOC_ID          = CANDIDATE-M7-1-KNOWLEDGE-SOURCE
TASK_ID         = M7-1-KNOWLEDGE-SOURCE-TYPED-CAPABILITY-DESIGN
REPO            = Leibniz-KERT
BRANCH_AT_WRITE = feature/m7-3-knowledge-map-route
性质            = 只读设计候选（decision-ready）；**不是**实施、**不是** ADR、**不是**合同修订
授权依据        = WBS §M7.1（docs/development/KERT_WORK_BREAKDOWN_STRUCTURE_V1.0.md:169）
                  独立评审 §4.7 / §8.4（docs/dd/KERT_independent_architecture_review_2026-08-26_V1.0.md:348-404,686-698）
                  Owner 裁定 D1-A / D2-A / D3-A
                  （docs/governance/KERT_PENDING_OWNER_DECISION_M7_EVOLUTION_V1.0.md:22-44,117,136）
状态基线        = multi_knowledge_source_framework: DESIGNED_NOT_IMPLEMENTED
                  （docs/governance/KERT_STATUS_BASELINE_CANDIDATE.yaml:82-83）
```

## 0. 非声明与硬性边界（先写在最前）

**非声明**（原文照录任务包 §3）：

- 不是实施授权、不是 ADR、不是 Contract Owner 批准；不代表 `PRODUCTION_RELEASE_GATE` 变化。
- 本文不声称任何能力已完成、不声称 `PRODUCTION_READY` / `GITS_UAT_PASS`。
- 与 `specs/` 冲突时以 `specs/` 为准（本仓唯一合同权威：`specs/CONTRACT_INDEX` 同级纪律见 `AGENTS.md`）。

**执行边界（本任务实际遵守）**：

| 边界 | 落实情况 |
|---|---|
| 只写设计文档 | 本文**仅**写入 `evidence/m7-3/CANDIDATE-M7-1-KNOWLEDGE-SOURCE.md` |
| 不改 `src/**`、`tests/**`、`specs/**`、`docs/contracts/**` | 未修改（只读引用） |
| 不引入 LightRAG 或任何具名检索引擎作为实现路径（D2-A） | 设计路径只落在既有 03_core 文件 / 04_serve Parquet / Kùzu 投影 / 既有封装上 |
| 不建立第二份本体权威（D3-A） | 本设计不引入任何本体资产；能力声明是**读取绑定**，不是语义定义 |
| 不改 GITS 仓、不 push | 未触碰 `/home/szf/dev/gits-cbanking` |
| 每个"现状"结论有代码/文档行号 | 全文每一条现状事实均带 `文件:行号` |

---

## 1. 现状事实清单：KERT 今天"取数"实际走哪些通道

### 1.1 通道总表（含读取入口与权威级别）

权威级别用四级记法，来源是规格与 ADR 的明文口径：
**AUTH（权威）** / **PROJ（可重建投影）** / **CTL（控制面元数据）** / **RUNTIME（可变运行态，明确不含知识）**。

| # | 通道 | 物理位置 | 读取入口（代码） | 权威级别 | 关键证据 |
|---|---|---|---|---|---|
| 1 | 原始证据目录 | `01_raw/` | `WorkspaceWriter.read_text` / `KnowledgeService.trace` 回溯层 | AUTH（原始，只增） | `src/kert/domain/workspace.py:14`；`src/kert/infrastructure/fs.py:84-88`；`src/kert/application/services.py:400` |
| 2 | 工作目录（加工中间态） | `02_work/<domain>/run=*/normalized/*.parquet` | 仅被投影构建器复制，不直接对外读 | PROJ（可删除可重建） | `src/kert/infrastructure/fs.py:13-14,126-136`；`src/kert/application/projection.py:317-334` |
| 3 | **文本权威知识源** | `03_core/<domain>/version=*/{entities,relations,statements,segments,rules,documents}/*.md` | `ProjectionBuilder._load_core_assets` / `KnowledgeService._find_core_asset` | **AUTH（唯一知识权威）** | `src/kert/application/projection.py:57,62-64,161-180`；`src/kert/application/services.py:418-430`；`docs/adr/ADR-012-sqlite-runtime-store.md:18` |
| 4 | **Parquet 服务投影** | `04_serve/<service_id>/version=*/{entities,relations,statements,segments,rules,vectors,datasets/*}.parquet` + `PROJECTION.md` + `CURRENT.md` | `ProjectionBuilder.build`（写）/ `KnowledgeService._read_table`（读） | PROJ（只读消费面，绝不扫 Work） | `src/kert/application/projection.py:3-6,67-68,101-134,363-405`；`src/kert/application/services.py:1-6,45-67` |
| 5 | **Kùzu 图投影** | `04_serve/<service_id>/version=*/graph`（单文件）+ `graph.PROJECTION.json` | `KuzuGraphBuilder.build` / `KnowledgeService.graph` | PROJ（删除后仅凭 Core 投影可重建） | `src/kert/infrastructure/graph/kuzu_builder.py:1-8,44-105,131-137`；`src/kert/application/services.py:113-119` |
| 6 | **SQLite Runtime Store** | `90_control/runtime/*`（禁落 `01_raw/02_work/03_core/04_serve`） | `RuntimeStore`（幂等 / Job / evidence / gate 审计） | RUNTIME（**不保存知识内容本体**） | `src/kert/infrastructure/runtime_store.py:1-16,31,33-34,52-99,200-210`；`docs/adr/ADR-012-sqlite-runtime-store.md:14,18-21` |
| 7 | SQLite 三阶段持久化（同库不同表） | 同上库，`stage_sessions/stage_states/stage_transitions/stage_confirmations` | `StageStore`（P12→P13→P14 与确认失效） | RUNTIME（阶段态与审计） | `src/kert/infrastructure/stage_store.py:16-18,30-78,120-125,128,181-203,227-309` |
| 8 | **客户知识库封装** | 读的是通道 4 的 `customer_knowledge` 服务投影 | `CustomerKnowledgeProvider.ki_map/entity/supply_chain/interpretation` | PROJ（**当前唯一被技能实际使用的取数入口**） | `src/kert/application/customer_knowledge.py:1-9,17,34-49,53-69,73-77,81-152` |
| 9 | 控制面元数据 | `90_control/catalog/KM-*.json`、`90_control/schema/route_policy.json`、`ontology_reference.json` | `KnowledgeMapRegistry.load` / `load_route_policy` / `load_ontology_reference` | CTL（**只引用不复制**；不是知识权威） | `src/kert/domain/knowledge_map.py:12-13,26-30,124-138`；`src/kert/domain/route_policy.py:13-15,201-210`；`src/kert/application/provision.py:1-22` |
| 10 | 仓内技能包资源（**不在工作区内**） | `<repo>/skills/product-recommendation/rules/`、`<repo>/examples/product-recommendation-assets/` | `_default_rules_dir` / `_default_assets_dir` / `ProductKnowledgeSnapshotLoader` | 仓内文件（非工作区、非受控工作区布局） | `src/kert/application/product_recommendation/sp15_skill.py:21-24,132-153,353-358` |
| 11 | 外部 LLM 适配器 | 出网（OpenAI 兼容） | `llm_mod.OpenAiCompatibleLlmAdapter`；出站前脱敏 | 外部（不可作事实权威） | `src/kert/application/skills.py:92-98,115-131`；`src/kert/infrastructure/adapters/` |

**读侧对外入口（HTTP）**：`/v1/entities/{id}`、`/v1/data/query`、`/v1/search`、`/v1/graph/query`、`/v1/rules/evaluate`、`/v1/evidence/{object_id}`、`/api/skill/*`、`/v1/knowledge-maps*`、`/v1/routing/plan`
（`src/kert/api/server.py:522,530,539,548,561,569,609,619,693,715,729`）。

### 1.2 现状两条真实取数链路（端到端，含行号）

**链路 A：R1 访前报告（技能 → 客户知识库 → Parquet 投影）**

1. `SkillExecutionService.execute` → `_executor(skill_id)`（`src/kert/application/skills.py:216-266,624-628`）
2. `_run_previsit/_run_outreach` 先解析**知识地图路由**，被拒即拒绝执行（fail-closed）
   （`src/kert/application/skills.py:632-685`；地图/策略侧见 `src/kert/domain/knowledge_map.py:291-327`、`src/kert/domain/route_policy.py:249-309`）
3. 计划里的资产清单被取成 `assetId` 序列：`_plan_assets(decision)`（`src/kert/application/skills.py:687-690`）
4. **但真正取数走的是另一条路**：`_load_ki` → `CustomerKnowledgeProvider.ki_map` → `KnowledgeService.segments(document_id=customerId)` → `04_serve/customer_knowledge/version=*/segments.parquet`
   （`src/kert/application/skills.py:504-521,715-723`；`src/kert/application/customer_knowledge.py:53-69`；`src/kert/application/services.py:302-305,45-67`）
5. `assetId` 与数据的对应靠**隐式字符串约定**：`heading_path[0]` 用 `^KI-([\w-]+)\s+(.+)$` 匹配出 `KI-*`
   （`src/kert/application/customer_knowledge.py:31,59-68`）
6. 逐条打轨迹 `ok / skipped`：`_trace_ki`（`src/kert/application/skills.py:699-711`）；标题回落自源码字面量 `KI_ITEMS`
   （`src/kert/application/customer_knowledge.py:20-28`；`src/kert/application/skills.py:692-697`）

**链路 B：SP-15 产品适配（技能 → 仓内资源目录，不经工作区）**

`ProductUniverseResolver.load_dir` → `examples/product-recommendation-assets/product-cards/`（`sp15_skill.py:353-358`），
规则来自 `skills/product-recommendation/rules/`（`sp15_skill.py:144-145`）；客户事实来自
`examples/product-recommendation-assets/03_core/customer-facts`（`sp15_skill.py:152-153`）。

### 1.3 现状缺口（每条均可被机械验证）

| # | 缺口 | 证据 |
|---|---|---|
| G1 | **`ActivationPlan.assets` 是"死字段"**：计划里能拿到 `assetId`，但全仓没有任何代码把 `assetId` 解析到某个数据源/能力；`_plan_assets` 的结果只用于（a）打 trace（b）过滤 `_ki_context` | 产出侧 `src/kert/domain/activation_plan.py:229-230`；消费侧 `src/kert/application/skills.py:687-690,719-723`；`src/kert/application/skills.py:523-532`（`only=` 过滤） |
| G2 | **取数失败是 fail-OPEN，与 M7.3 的 fail-closed 相反**：客户知识库不可用时静默返回空并只降级为 `skipped` | `src/kert/application/customer_knowledge.py:35`（"服务不可用时返回空（fail-open）"）、`:41-49`（吞异常置 `available=False`）、`:55-56,74-75,87-88`；`src/kert/application/skills.py:509-521`（`except Exception` → 返回 `{}`） |
| G3 | **"计划资产 ↔ 实际读取"的一致性只由 CI 测试守，运行时无约束**：一致性测试对着地图 `assetRefs` 与源码读取集做机械核对 | `tests/integration/test_control_plane_consistency.py:53-59`；地图侧注释也明示"不由本字段自述背书"（`examples/bank-front-knowledge-maps/90_control/catalog/KM-CORP-RM-PREVISIT.json` notes） |
| G4 | **资产 id 没有声明式目录**：`assetId` 只要求匹配 `^[A-Z][A-Z0-9_-]{2,127}$`，`KI-*` 的"是什么/从哪来"没有登记处 | `src/kert/domain/knowledge_map.py:400-403`；`src/kert/domain/ids.py:11` |
| G5 | **`required` 不参与运行时判定**（已知子决策未实施） | `src/kert/application/skills.py:645-646`；地图注释同载 |
| G6 | **状态基线落后**：`multi_knowledge_source_framework` 记 `DESIGNED_NOT_IMPLEMENTED`，而"文件/Parquet/Kùzu"已被独立评审判为 `PARTIAL`（统一接口尚未实现） | `docs/governance/KERT_STATUS_BASELINE_CANDIDATE.yaml:82-83`；`docs/dd/KERT_independent_architecture_review_2026-08-26_V1.0.md:217` |

**一句话现状**：KERT 今天能取数，但取数链是"**源码字面量 + 隐式字符串约定 + fail-open 兜底**"；
`ActivationPlan` 给出了资产清单，却没有"**资产 id → 数据源能力**"的解析链。

---

## 2. typed capability 模型

### 2.1 能力面字段（本设计的核心对象）

```text
KnowledgeSourceCapability（声明式，位于控制面）
  capability_id     : 能力唯一 ID           形态 'KS-<UPPER...>'（复用 ids.ID_RE，src/kert/domain/ids.py:11）
  title             : 人类可读名
  source_kind       : 数据源种类（闭集）：PARQUET_PROJECTION | GRAPH_PROJECTION | CORE_FILE | STAGE_STORE
  declared_types    : 本能力**会**返回的资产类型闭集（见 2.2）
  read_contract     : 受控读契约（见 2.3，**不接受调用方原始查询语句**）
  version           : semver（声明版本，进 binding 指纹）
  freshness         : 新鲜度声明（见 2.4）
  fail_closed       : 恒为 true（显式写出，避免默认值猜疑）
  enabled           : 开关（默认 true；停用能力等同未绑定）
```

**asset → capability 绑定**（同一控制面，独立文件）：

```text
assetId（如 KI-009 / KI-FRONT-001） → capabilityId + （可选）read 参数模板
```

### 2.2 `declared_types` 为什么是**闭集**

独立评审已经把方向钉死：`query(statement: str)` 过于宽泛，"容易演变成任意 SQL/Cypher/查询语言入口"，
生产接口应按 capability 拆分并使用受控 QuerySpec / 注册 Query ID
（`docs/dd/KERT_independent_architecture_review_2026-08-26_V1.0.md:352-361`），风险登记为 M-08"任意查询、证据断链和数据越界"（同文件 `:569`）。

据此，`declared_types` 取**闭集**（不是自由字符串字典），初版只允许：

| declared_type | 语义 | 对应现状实现 |
|---|---|---|
| `KNOWLEDGE_ITEM_TEXT` | 按资产 id 取知识条目**原文片段** | `CustomerKnowledgeProvider.ki_map()`（`customer_knowledge.py:53-69`） |
| `ENTITY_RECORD` | 取实体行（含 `x_*` 扩展字段） | `KnowledgeService.entities()`（`services.py:307-310`） |
| `RELATION_EDGE` | 取关系边 | `KnowledgeService.relations()`（`services.py:312-314`） |
| `GRAPH_NEIGHBORHOOD` | 邻域图（有界深度/节点数） | `KnowledgeService.graph()`（`services.py:113-119`） |
| `RULE_SET` | 规则集（只读） | `KnowledgeService._read_table("rules.parquet")`（`services.py:320`） |
| `STAGE_STATE` | P12/P13/P14 阶段态（**默认停用**） | `StageStore.latest_state`（`stage_store.py:218-224`） |

> 设计纪律：**新增 declared_type 需要走合同/设计变更**，不允许调用方自定义 type 字符串。
> 这与地图/策略"未知字段一律拒绝"的既有 fail-closed 风格一致（`knowledge_map.py:151-153`、`route_policy.py:142-144`）。

### 2.3 `read` 契约：受控 QuerySpec，不是自由语句

```text
ReadSpec（由调用方给出，字段闭集、有界）
  type        : declared_types 之一
  asset_id    : 仅 KNOWLEDGE_ITEM_TEXT 时需要（其余类型由能力自身决定取什么）
  subject_ref : 主体（如 customerId / entityId）
  limit       : 有界（默认 100，上限 1000；对齐 services.py:82-83 的既有上限）
  as_of       : 可选时点（对齐 services.py:104-105 的既有 as_of 语义）

ReadResult（成功）
  capability_id / source_kind / asset_id
  declared_type
  records     : list[dict]
  provenance  : { core_version, projection_version, source_path, content_sha256 }   ← 证据可回链
  freshness   : { built_at, projection_version, stale: bool, stale_reason }          ← 见 2.4
  truncated   : bool
  binding_sha256 : 本次解析所用的绑定声明指纹                                     ← 见 3.5
  code        : 'OK'

ReadDenial（失败；**没有第三态**）
  code        : 见 3.3 的拒绝码闭集
  reason      : 人类可读、含可排障信息
```

**为什么 `provenance` 必须回到 03_core**：既有 `KnowledgeService.trace` 已经把"服务结果 → 04_serve → 03_core → 02_work/01_raw → 90_control 决策"这条链实现出来
（`services.py:373-414`），`segments.parquet` 里也保留了 `source_path` / `content_sha256`（`projection.py:265-276`）。
typed capability 的 `provenance` 直接复用这条既有链，**不新建第二套溯源**。

### 2.4 freshness 口径（不发明新时间源）

- 新鲜度来自**投影自身的确定性记录**：`04_serve/<service>/CURRENT.md` 的 `target_version`（`projection.py:383-405`；`services.py:45-53`）与 `PROJECTION.md` 的 `built_at`（`projection.py:363-381`）。
- `stale=true` 只允许出现在**显式阈值比较**之下（阈值待 Owner 给，见 §7 O-3）；第一片**只读出不判定**，避免发明"多少天算旧"的业务口径。
- 与 `graph.PROJECTION.json` 的 `fingerprint`（`kuzu_builder.py:88-101,110-118`）同源思路：新鲜度/指纹都是**可比较的确定性元数据**，不是语义。

### 2.5 为什么是"类型化能力"而不是"插件"

| 维度 | 插件模型（被否决） | 类型化能力（本设计） |
|---|---|---|
| 接口面 | 开放方法（`query(statement)`）→ 任意 SQL/Cypher 入口 | **闭集** `declared_types` + 有界 `ReadSpec`；由 2.2/2.3 钉死 |
| 代码来源 | 需要动态装载第三方代码 | **零动态装载**：能力实现留在 KERT 内部（`src/kert/infrastructure/**` 既有适配器位置），声明只选"用哪个能力" |
| 与 D2-A 的关系 | 插件容易变成"把具名检索引擎塞进来"（LightRAG 类形态） | 检索增强落在**既有 Kùzu 投影 + 既有确定性向量/全文打分**上（`projection.py:433-453`；`services.py:242-298`），不引入具名引擎 |
| 与 D3-A 的关系 | 插件自带语义定义 → 事实上形成第二份本体权威 | 能力只声明**读取绑定**（`assetId → capabilityId + read 契约`），**不定义资产语义**；语义权威仍在 03_core 与控制面地图 |
| 声明位置 | 常落成"配置里塞脚本路径/DSN"，与工作区纪律冲突 | 与控制面同址（`90_control/schema/`），与 `route_policy.json` 同一套加载/校验纪律（`provision.py:1-22,123-156`） |
| 可审计性 | 行为取决于外部代码版本 | 行为取决于**声明指纹 + 代码版本**，两者都可重放（对齐 `activation_plan.py:8-13` 的可重放纪律） |
| 失败语义 | 插件异常易被 `try/except` 吞成"空结果" | `ReadDenial` 显式拒绝（见 §3.3），**不得**静默返回 `[]` |

补充依据（仓内明文）：

- 独立评审要求"typed KnowledgeSource capability 与注册查询"、"provenance/snapshot/security/freshness 完整 SourceResult"、"插件包签名、版本兼容和停用机制"（`docs/dd/KERT_independent_architecture_review_2026-08-26_V1.0.md:690-698`）。
- 既有演进设计已给出 `KnowledgeSource Protocol` + `SourceResult` + `KnowledgeSourceRegistry`（`docs/production-evolution-plan.md:644-704`）与"何时该用统一 Source 接口"的映射表（同文件 `:783-792`）。
- 生产评审同时强调 Java Runtime **不应**拥有第二套 Source 凭据/模板/脱敏/证据逻辑（`docs/dd/KERT_生产级混合架构独立评审报告_2026-08-26_V1.0.md:260-262`）——类型化能力把这一点变成"唯一实现点"。

> **与既有设计的差异（必须显式登记）**：既有演进设计给的 `SourceResult` 只有 `records/meta/truncated/latency_ms/source`
> （`docs/production-evolution-plan.md:659-667`），**不足以**支撑本设计要求的
> `declared_type / provenance / freshness / binding 指纹 / 显式拒绝`（独立评审 `:363-373` 的补充清单即为此）。
> 本设计在**不推翻**既有 `KnowledgeSource` 形态的前提下，把 `SourceResult` 加厚为 §2.3 的 `ReadResult`；
> 该差异是**设计增量**，不是替换既有计划。

### 2.6 边界确认：不建第二权威、不建第二持久化

- **不建第二份本体权威（D3-A）**：本设计不引入任何 OWL/SHACL 资产；KERT 对本体仍只做"契约引用 + 内容哈希版本"
  （`src/kert/domain/ontology_reference.py:71-74`；`docs/governance/KERT_PENDING_OWNER_DECISION_M7_EVOLUTION_V1.0.md:136`）。
- **不建第二套持久化**：若第一片之后需要落读取审计，**必须复用同一 Runtime Store 库的追加式 migration**
  （`runtime_store.py:140-141` "顺序 migration；只能追加不可修改"），与 `StageStore` 的既有先例一致
  （`stage_store.py:16-18` "复用既有 SQLite 运行时存储（同库不同表），不新建第二套持久化设施"）。
- **不新增知识数据目录**：Runtime Store 路径禁落 `01_raw/02_work/03_core/04_serve`
  （`runtime_store.py:33-34,200-210`；`ADR-012:20`）。

---

## 3. 与 M7.3 的衔接：`ActivationPlan.assets` → 能力 → 真实数据源

### 3.1 解析链（5 步，每步都有确定输入/输出）

```text
[1] taskType ──RouteResolver.resolve──▶ KnowledgeMap（含 assetRefs 按 sequence）
        src/kert/domain/route_policy.py:249-309
[2] map.assetRefs ──ActivationPlanBuilder.build──▶ ActivationPlan.assets: tuple[PlanAsset(asset_id, required, sequence)]
        src/kert/domain/activation_plan.py:209-260（assets 见 :229-230）
[3] plan.assets[] ──AssetBindingResolver.resolve(asset_id)──▶ KnowledgeSourceCapability（或 ReadDenial）
        ★ 新增（本设计）；声明来自 90_control/schema/knowledge_sources.json
[4] capability ──ReadSpec──▶ ReadResult（records + provenance + freshness + binding_sha256）
        ★ 新增；实现落在既有 04_serve / Kùzu / 03_core 读入口
[5] records ──既有技能装配──▶ _ki_context / 卡片装配（行为保持不变）
        src/kert/application/skills.py:523-532
```

**关键性质**：

- 步骤 1-2 **已实现且 fail-closed**（`route_policy.py:249-309`、`activation_plan.py:113-129`），本设计**不动**它们。
- 步骤 3-4 是**当前缺失的那一段**（G1）。
- 步骤 5 在第一片**不接线**，因此既有行为零变化（见 §6）。

### 3.2 解析链的确定性要求

- 同一 `(asset_id, 声明内容, 能力实现版本)` ⇒ 同一解析结果，**逐字段可重放**（对齐 `activation_plan.py:8-13` 的可重放纪律、`:132-166` 的 canonical 内容思路）。
- 声明文件集合的内容哈希 = `binding_sha256`，必须能被读出并写入 `ReadResult`（§3.5）。
- 解析顺序：按 `plan.assets` 的 `sequence` 升序（`knowledge_map.py:388-418` 已保证 `assetRefs` 按 sequence 排序）。

### 3.3 失败与拒绝码（默认拒绝、无第三态、码可区分）

**设计原则（最重要的一条）**：把两类完全不同的失败**分开**，绝不合并：

| 类别 | 语义 | 处置 | 理由 |
|---|---|---|---|
| **(R) 解析失败** | 资产**没有可用的读取能力**（未绑定/歧义/声明非法/能力停用/能力不可用） | **fail-closed 拒绝**（`ReadDenial`），调用方必须显式处理 | "读不出来"不是"没有数据"；把前者伪装成 `skipped` 会把配置错误读成业务空值（`docs/dd/...review...V1.0.md:344-346` 同精神："不得以顶层 ok 隐藏降级"） |
| **(D) 数据未命中** | 能力**正常**，但该主体确实没有这条资产 | 保持既有 **evidence `ok/skipped`** 语义，**不**升级为拒绝 | v1.3 纪律：`ok/skipped` 只反映"库里有/没有"，不得扩义（`src/kert/application/skills.py:699-711`；`customer_knowledge.py:8`"任何未命中均如实返回空，不虚构"） |

**拒绝码闭集**（新族 `KNOWLEDGE_SOURCE_*`，与既有三族并列、**不复用**）：

| 码 | 含义 | 对应现状缺口 |
|---|---|---|
| `KNOWLEDGE_SOURCE_DECLARATION_ABSENT` | 控制面没有 `knowledge_sources.json` | 有 `route_policy.json` 缺失即默认拒绝的先例（`route_policy.py:258-261`） |
| `KNOWLEDGE_SOURCE_DECLARATION_INVALID` | 声明结构/取值非法（含未知字段、非法 ID/semver/declared_type） | 对齐 `knowledge_map.py:148-161`、`route_policy.py:137-198` |
| `KNOWLEDGE_SOURCE_UNBOUND` | 该 `assetId` 未绑定任何能力（**默认拒绝，不回落**） | G1/G4 |
| `KNOWLEDGE_SOURCE_AMBIGUOUS` | 同一 `assetId` 被同优先级多能力绑定，歧义不可裁决 | 对齐 `knowledge_map.py:318-326`、`route_policy.py:275-283` |
| `KNOWLEDGE_SOURCE_DISABLED` | 命中的能力 `enabled=false` | 独立评审要求"停用机制"（`:697`） |
| `KNOWLEDGE_SOURCE_UNAVAILABLE` | 能力可用但底层源不可读（投影缺失/图缺失/CURRENT 指针非法） | **直接对治 G2** |
| `KNOWLEDGE_SOURCE_CONTRACT_MISMATCH` | `ReadSpec.type` 不在能力 `declared_types` 内 | 闭集纪律（§2.2） |
| `KNOWLEDGE_SOURCE_LIMIT_EXCEEDED` | `limit` 越界（>1000） | 对齐 `services.py:82-83` |

**无第三态**：解析结果类型是 `ReadResult | ReadDenial`（对齐 `activation_plan.py:128-129` 的 `PlanDecision` 写法）；
`allowed` 语义只可能是"有结果"或"有拒绝"，**不允许** `None`/空 dict/`skipped` 冒充成功。

**码的可用性约束（反空转）**：每个码必须**至少有一个可构造的输入**能触发（§5.3 变异矩阵逐码覆盖）；
无法被触发的码不得进入合同枚举（对齐既有纪律：负例"必须真的被拒绝"，见 §5.2）。

### 3.4 现有 gate 顺序不变（归因正确）

`ActivationPlanBuilder.build` 的门禁顺序是"**先路由、后本体引用**"，其理由写在代码里：
本体声明属工作区**配置**问题，不应因一个未映射任务而误报为配置错误（`activation_plan.py:174-180`）。

**本设计的插入点**：能力解析**必须晚于**本体门禁（即计划已经产出之后），
因为能力解析消费的是 `plan.assets`，而 `plan.assets` 只有在路由 + 本体都放行后才存在。
⇒ 能力解析**不改变**既有拒绝码的归因（路由问题仍是 `ROUTE_*`，本体问题仍是 `ONTOLOGY_REFERENCE_*`），
只是在计划之内新增 `KNOWLEDGE_SOURCE_*`。

### 3.5 plan hash 影响分析（本设计最容易踩雷处，须裁决）

**事实**：`plan_hash` 只覆盖确定性字段 `schema/task/policy/map/ontology/assets(assetId)/skills`
（`activation_plan.py:132-161,237-239`），**不含** `versions` 字典；`versions` 只是响应快照
（`:240-245`；合同见 `specs/kert-openapi-v1.yaml:1177-1192`）。

**设计选项**：

| 选项 | 做法 | 代价 | 结论 |
|---|---|---|---|
| **O-A（推荐）** | **绑定/能力版本不进 plan hash**；`binding_sha256` 只出现在 `ReadResult.provenance`/trace | 同一计划在不同绑定下 hash 相同 —— 但**可被发现**（provenance 里有指纹） | 第一片采用。理由：绑定是**读取实现**，不是计划内容；D1-A 的"零冲突子集"要求不扩大 hash 覆盖面 |
| O-B | 把 `versions.knowledgeSources = <bindingBundleSha256>` 加进响应 | 需改 `ActivationPlan` schema（additive）+ 需 Contract Owner；`plan_hash` **本身不变**（`versions` 不入 hash） | 列为**提案**（§4.1），第一片不实施 |
| O-C | 把绑定指纹并入 `canonical_content`（⇒ 计划必变） | 改变对外 `planHash` 语义 → **必须** Owner + 合同修订；且与 gits 侧 CTR-PLAN-001 口径对齐难度上升 | **否决**（第一片不做） |

> ⚠ 关于"只改本体 ⇒ 计划必变"（gits 侧判据 V2，`activation_plan.py:26-30`）：该判据**只针对本体**。
> 本设计**不**顺手把绑定塞进 hash —— 那会静默改变对外合同字段语义，属越权。

---

## 4. 契约面影响（**仅提案**，未改任何合同）

### 4.1 可复用面（好消息：内部 schema 已有槽位）

`docs/contracts/internal/schemas/execution-plan.schema.json:73-78` **已经声明** `knowledgeSourceRefs: string[]`
（当前未被任何 RPC 使用，也不在 `required` 列表 `:5-19`）。

⇒ 提案 P-1：该槽位的语义**收敛**为"本次执行允许使用的 capabilityId 集合"，
由 `ActivationPlan` + 资产绑定解析得出，**不新增字段、不新增端点**。
（该文件属 `docs/contracts/**`，本次**未修改**；收敛动作需 Contract Owner。）

### 4.2 提案清单（每条都需 Contract Owner 裁决后才可实施）

| 提案 | 内容 | 兼容性判断 | 依据 |
|---|---|---|---|
| **P-2** | `/v1/routing/plan` 响应中 `plan.versions` **新增可选键** `knowledgeSources`（值为 `bindingBundleSha256`） | additive：`versions` 既未声明 `additionalProperties:false`，也未把新键列入 `required`（`specs/kert-openapi-v1.yaml:1177-1192`）；但**严格 codegen 消费方**需要合同声明才能看到该字段 ⇒ 按 additive 提案走 | §3.5 O-B |
| **P-3** | `PlanDenial.code` 的支持码描述**新增一族** `KNOWLEDGE_SOURCE_*` | additive：现状描述已列三族（`specs/kert-openapi-v1.yaml:1149-1153`） | §3.3 |
| **P-4** | 能力**健康/清单**只读端点（如 `/v1/knowledge-sources`，返回能力清单 + 健康 + 绑定指纹） | additive 新端点，需先登记 `specs/CONTRACT_INDEX`（AGENTS.md "合同源变更先于生成物与实现"） | 独立评审要求"插件包签名、版本兼容和停用机制"与"Source/Tool contract tests 和故障注入"（`docs/dd/KERT_independent_architecture_review_2026-08-26_V1.0.md:696-698`）；"每个 Source 有独立健康检查"（`docs/production-evolution-plan.md:702-704`）。现状 `/readyz` 已把 `knowledge_projection` 记为**非阻断**（`src/kert/api/server.py:343,365-370`），故健康面**不**改 `/readyz` 语义 |
| **P-5** | 错误码族扩展需在消费者侧（GITS）登记迁移说明 | 需跨仓协调（本任务**不动** GITS） | `AGENTS.md` 规则 #1、#10 |

### 4.3 明确**不**提案的东西

- 不提案 `query(statement)`/任意 SQL/Cypher 入口（M-08 已登记为高危，`docs/dd/...review...V1.0.md:569`）。
- 不提案把能力声明并入 `specs/kert-openapi-v1.yaml` 的**请求体**（避免把"读什么"暴露成调用方自由输入）。
- 不提案改动 `/readyz` 的**阻断语义**（现状知识投影缺失只 degraded，理由写在 `server.py:343-348`；若把能力可用性设为硬阻断，会让"未供给"的实例永远不就绪——这正是既有设计刻意避免的）。
- 不提案新增数据库/引持久层（`ADR-012:21`、`runtime_store.py:9`）。

---

## 5. 验证计划（含**反空转**与**变异自证**）

> 口径来源：任务包 §1.5 要求"可执行用例清单（含反空转与变异自证）"；
> 仓内既有验证脚本风格见 `scripts/verify_m2p2_worker.py:1-42`（逐条 `PASS/FAIL` + 报告落盘）。
> **反空转红线**：任何"否定式断言"（不得静默降级、不得回落、必须拒绝）若只跑正例夹具，其断言恒真 —— 必须配**能触发拒绝的负例夹具**，且**夹具缺失即判 FAIL（fail-closed 门禁）**。

### 5.1 单元层（`tests/unit/test_knowledge_source_capability.py`）

| ID | 用例 | 决定性断言（不可空转） |
|---|---|---|
| U1 | 合法声明 → 注册表加载 | 能力条数、`capability_id` 集合逐项相等 |
| U2 | 声明含未知字段 / 非法 `capability_id` / 非法 semver / 未知 `declared_type` | 抛 `SchemaValidationError`，且**错误信息含字段名** |
| U3 | 未绑定的 `assetId` | 返回 `ReadDenial`，`code == 'KNOWLEDGE_SOURCE_UNBOUND'`（**不是** 空列表、**不是** OK） |
| U4 | 同 `assetId` 被同优先级两能力绑定 | `KNOWLEDGE_SOURCE_AMBIGUOUS`，`reason` 含两个 capabilityId |
| U5 | `ReadSpec.type ∉ declared_types` | `KNOWLEDGE_SOURCE_CONTRACT_MISMATCH` |
| U6 | 能力正常但主体无数据 | `code == 'OK'` 且 `records == []`（证明"数据未命中"**不**是拒绝） |
| U7 | 底层投影缺失（临时清空 `04_serve/<svc>/CURRENT.md`） | `KNOWLEDGE_SOURCE_UNAVAILABLE`（证明**不**静默返回 `[]`） |
| U8 | `provenance/freshness` 字段 | 与 `CURRENT.md` 的 `target_version` **逐字节相等**；`binding_sha256` 与声明内容哈希相等 |
| U9 | 可重放 | 同输入两次解析 `to_dict()` 完全相等（含指纹） |
| U10 | 无第三态 | 结果类型 ∈ `{ReadResult, ReadDenial}`；`bool` 化/`None` 路径不存在 |
| U11 | 停用能力 | `KNOWLEDGE_SOURCE_DISABLED` |
| U12 | `limit > 1000` | `KNOWLEDGE_SOURCE_LIMIT_EXCEEDED` |

### 5.2 集成层（`tests/integration/test_knowledge_source_resolution.py`）

| ID | 用例 | 说明 |
|---|---|---|
| I1 | 供给 `examples/bank-front-knowledge-maps` 到临时工作区 → `plan(PRE_VISIT_PREPARATION).assets`（7 条）**逐条**解析 | 断言 `capability_id` 序列与 `sequence` 单调一致；7 条全部解析（不允许 `skipped` 冒充） |
| I2 | 从声明中删掉 `KI-FRONT-005` → 再解析 | 该条必须是 `KNOWLEDGE_SOURCE_UNBOUND`（拒绝），**且**同一计划其余条仍正常（爆炸半径最小化，对齐 `route_policy.py:194-196` 的既有取舍） |
| I3 | 删除整个声明文件 → 解析 | `KNOWLEDGE_SOURCE_DECLARATION_ABSENT`，**不回落**任何内置默认 |
| I4 | 与既有地图声明的一致性 | 断言 `∪(maps.assetRefs) ⊆ 声明绑定集`；与 `tests/integration/test_control_plane_consistency.py:53-59` 的口径互补（后者核"地图 ↔ 源码读取集"） |
| I5 | 真实数据贯通 | 对 `KI-FRONT-001` 读出的 `records[0].content` 必须能在 `03_core/.../segments/*.md` 原文中命中（证明"读的是权威源的可重建投影"，而非虚构） |
| I6 | 反例夹具存在性 | **门禁式断言**：负例声明集文件必须存在且至少覆盖 U2/U3/U4/U5/U7/U11 六类；**缺失即 FAIL**（反空转硬要求） |

### 5.3 变异自证矩阵（每个变异必须让至少一条断言 FAIL；恢复后 PASS）

| 变异 | 手法 | 期望结果 |
|---|---|---|
| M1 | 删除 `knowledge_sources.json` | U/I3（ABSENT）**FAIL** |
| M2 | 把 `KI-FRONT-001` 绑到 `ENTITY_RECORD` 能力 | I1（顺序/类型）**FAIL** |
| M3 | 让能力在投影缺失时 `return []` 而非拒绝 | U7 **FAIL** |
| M4 | 让解析器在缺绑定时"回落内置清单" | U3/I2 **FAIL** |
| M5 | 去掉未知字段拒绝 | U2 **FAIL** |
| M6 | 把歧义改成"取第一个" | U4 **FAIL** |
| M7 | 把 `ReadResult.code` 恒置 `'OK'` | U3/U5/U7/U11 **FAIL** |
| M8 | `freshness.projection_version` 写死常量 | U8 **FAIL** |
| M9 | 把 `KNOWLEDGE_SOURCE_UNAVAILABLE` 降级为 `skipped` | U7 + I3 **FAIL** |
| M10 | 删除负例夹具文件 | I6 **FAIL**（门禁 fail-closed） |
| M11 | 读取顺序改为字典序而非 `sequence` | I1 **FAIL** |

> **空转自检**：每条"必须拒绝"的断言都要求**具名拒绝码**（不接受仅断言 `allowed is False`），
> 并对 M7 专门设卡（把码恒置 OK）——这是最容易被写空的断言形态。

### 5.4 端到端脚本与证据落盘

- `scripts/verify_m7p1_knowledge_source.py`（新，第二片起）：3 场景（正常解析 / 缺绑定 / 源不可用）+ 变异自证，逐条 `[PASS|FAIL]`，报告落 `evidence/m7-p1/`（命名沿用 `evidence/m2-p2/` 先例，见 `scripts/verify_m2p2_worker.py:17`）。
- 复用既有故障注入工具做"源不可用"场景：`scripts/chaos_injector.py`、`scripts/run_chaos_test.sh`。
- 证据要求（对齐任务包精神）：原始命令 + 退出码 + 夹具哈希 + 变异前/后两次输出。

---

## 6. 分期建议

### 第一片（**1 个可审查原子**）：`M7.1-A 资产→能力绑定解析链（fail-closed，只读、不接线）`

**范围（只做这四件，一件都不多）**：

1. **声明形态**：`90_control/schema/knowledge_sources.json`（能力清单 + `assetId → capabilityId` 绑定），
   与 `route_policy.json` 同址同纪律（`route_policy.py:13-15,127-134`）。
2. **加载/校验/解析**：`src/kert/domain/knowledge_source.py`
   —— 严格校验（未知字段拒绝、ID/semver/闭集 `declared_type`）、确定性、`ReadDenial` 码闭集（§3.3）。
3. **零个数据适配器**：第一片**不实现**任何真实读取（不碰 Parquet/Kùzu），只解析到"能力已解析 + 读取契约已校验"。
   （把"能不能读"与"读出来对不对"分成两个原子，避免一个原子同时承担两侧风险。）
4. **测试**：U1-U5、U8-U12 + I2/I3/I4/I6 + 变异 M1/M2/M4/M5/M6/M7/M10/M11。

**第一片的硬性约束**（与 D1-A 的"零冲突子集"逐条对齐，`docs/governance/KERT_PENDING_OWNER_DECISION_M7_EVOLUTION_V1.0.md:35-36,97`）：

| 约束 | 落实 |
|---|---|
| 零新依赖 | 只用 stdlib + 既有 `kert.domain.ids/errors` |
| 不落盘 | 声明是控制面 JSON；本片不写任何运行态 |
| 不改 GITS | 无跨仓调用 |
| 不启用隔离资产 | 无 Oracle/Ossie 触点 |
| 不改既有调用路径 | `skills.py` / `server.py` 零改动 ⇒ 现有 137 集成用例行为不变 |
| 只读 | 不解任何写锁 |

**第一片的可审查产出**：声明 schema + `knowledge_source.py` + 单元/集成测试 + 一份"拒绝码 × 触发输入"对照表。

### 后续片（各自 1 个原子，需独立派工）

| 片 | 内容 | 关键风险控制 |
|---|---|---|
| M7.1-B | 第 1 个真实能力：`PARQUET_PROJECTION / KNOWLEDGE_ITEM_TEXT`（对齐 `customer_knowledge.ki_map`，含 `heading_path` 解析） | **行为等价性回归**：必须证明替换后 `ok/skipped` 与现状逐条相同（对治 G2，但不改变 v1.3 语义） |
| M7.1-C | 接线 `skills._route_plan` → 能力解析：`KNOWLEDGE_SOURCE_*` 拒绝 ⇒ `SkillError`，trace 增 `capabilityId/bindingSha256` | 保留 `KERT_PERMISSION_DENIED` + `detail.routeCode` 的既有错误映射（`skills.py:642-643`），不单方面扩合同错误码 |
| M7.1-D | 第 2 个能力：`GRAPH_PROJECTION / GRAPH_NEIGHBORHOOD`（Kùzu，`kuzu_builder.py:44-105`） | 有界深度/节点；图不可用 ⇒ `UNAVAILABLE` 而非空图 |
| M7.1-E | 健康与指标（能力级 `kert_source_calls_total` / `kert_source_duration_seconds`，命名沿用 `docs/production-evolution-plan.md:606-611`） | 不改 `/readyz` 阻断语义 |
| M7.1-F | 合同提案落地（P-1/P-2/P-3/P-4） | 必须 Contract Owner 先行；与 C-20（v1↔v2 归并）**不同轨**，不得借归并顺带 |

### 与 `(B)` 子决策的关系（不抢跑）

`required: true/false 是否参与运行时判定`是**既有未实施的子决策**
（`src/kert/application/skills.py:645-646`；`KM-CORP-RM-PREVISIT.json` notes）。
本设计**不**在 M7.1-A/B/C 中顺手升级 `required` 语义；它需要独立裁决 + 独立的兼容性评估（因为会改变对外 `ok/skipped` 观感）。

---

## 7. 开放项（需 Owner / Contract Owner 裁决）

| ID | 问题 | 影响 | 建议 |
|---|---|---|---|
| O-1 | §3.5 的 O-A/O-B/O-C：绑定指纹是否要进 `versions` / 是否改 `planHash` 语义 | 对外合同字段 | 建议 O-A（第一片），O-B 作为后续合同提案 |
| O-2 | §3.3 的 (R)/(D) 分野是否被接受（即"能力解析失败 must fail-closed，数据未命中保持 skipped"） | 决定 M7.1 与 v1.3 evidence 纪律的边界 | 建议接受；否则需明确"降级必须显式 `DEGRADED`"的替代形态（独立评审 `:344-346` 同源） |
| O-3 | `freshness.stale` 的阈值从哪来 | 现无仓内权威阈值 | 第一片只读出不判定；阈值待 Owner/数据 Owner 给 |
| O-4 | 声明文件的**唯一权威位置**是否就是 `90_control/schema/`（与 `route_policy.json` 同址） | 决定供给（`provision.py`）是否要纳入第 4 类文件 | 建议同址同供（`provision.py:8,123-134` 现管地图 + 策略 + 本体引用三类） |
| O-5 | 第一片是否落在 D1-A 授权内 | 决定能否开工 | 本设计判为**在**（零冲突子集口径逐条对照见 §6）；如 TL/Owner 认为超范围，请显式退回 |
| O-6 | 仓内技能包资源（通道 10，`sp15_skill.py:132-153`）是否也要纳入能力面 | SP-15 目前**绕过工作区**读仓内文件 | 建议**不在**第一片处理，单独立项（涉及"哪些仓内文件算受控知识"的定性问题） |

---

## 8. 非声明（再次，原文照录）

- 本文**不是** Owner 决策、**不是**规格修订、**不是** ADR、**不是** Contract Owner 批准；
  `PENDING_OWNER_DECISION` 状态的项**不得**被当作已批准。
- 本文**不**声称任何能力已完成、**不**声称 `PRODUCTION_READY` / `GITS_UAT_PASS`；
  `PRODUCTION_RELEASE_GATE=BLOCKED` 不变。
- 本文的"现状"均为**只读清点**结论，附文件与行号；未复核项已标注。
- 未修改 `src/**`、`tests/**`、`specs/**`、`docs/contracts/**`；未修改 GITS 仓库；未 push。
- 归并/激活类事项（v1↔v2、激活合同）**不在**本文范围；本文不产生合同效力。
