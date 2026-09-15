# KERT 待 Owner 裁定：M7 进化方向与技术取舍（V1.0 候选）

```text
STATUS            = PENDING_OWNER_DECISION（候选；本文档不构成决策，不替代 Owner 裁定）
DATE              = 2026-09-15
REQUESTED_BY      = Tech Lead（受工程师侧指令："尽快进化完成 KERT 体系内的
                    知识地图 / skill 路由 / LightRAG / 本体模型 / 语义层到数据源连接的完整实现"）
BRANCH_AT_REQUEST = feature/PI-ARCH-L10-L13 @ c49ddb5
前置依据          : docs/governance/KERT_STATUS_BASELINE_CANDIDATE.yaml（唯一权威状态源）
                    docs/development/KERT_WORK_BREAKDOWN_STRUCTURE_V1.0.md（WBS）
                    docs/dd/KERT_independent_architecture_review_2026-08-26_V1.0.md（独立评审 §4.7）
                    docs/evaluation-sqlite-graph-base.md（图引擎选型）
                    docs/graph-db-selection.md（轻量图 DB 选型调研）
```

> **背景**：收到"尽快进化完成"五块能力（知识地图 / skill 路由 / LightRAG / 本体模型 / 语义层到数据源连接）的指令。
> 经只读清点，**其中 3 块有仓内权威设计但位于 Phase 3（M7）**，**2 块在 WBS 中不存在且与既有硬约束冲突**。
> 按 `START_HERE.md` 第五步与 `RULES.md` 状态纪律，TL **不自行决策**，登记待裁定。

---

## 0. 只读清点结果（每项均有代码/文档证据）

| 指令要求的能力 | 仓内权威对应 | 现状（有证据） |
|---|---|---|
| **知识地图** | WBS **M7.3**（Skill/Route/ActivationPlan 治理） | `KERT_STATUS_BASELINE_CANDIDATE.yaml:78-79` → `knowledge_map_registry: DESIGNED_NOT_IMPLEMENTED`；代码里唯一"实现"是 `src/kert/application/skills.py:627-631` 的 **trace 字符串**，mapId 为**硬编码字面量**（`:651`/`:683`/`:717`）。无 registry / schema / 加载器 / 遍历 API / 版本合同 |
| **skill 路由** | WBS **M7.3** | **注册表 + 执行入口真实可运行**：`src/kert/application/skills.py:189-205`（registry）、`:215-285`（execute）、`src/kert/api/server.py:590-644`（`/api/skill/health|execute|report|gates`）。**选择/路由控制面缺失**：caller 直接传 `skillId`，SP-20 的 `routeMode` 只是内部检索选择（独立评审 §4.7 原文） |
| **LightRAG** | **WBS 无此项** | **全仓零命中**（`grep -i lightrag` 无结果）。图底座是 **Kùzu**：`src/kert/infrastructure/graph/kuzu_builder.py`；产物 `data/product_knowledge_graph.kuzu` |
| **本体模型** | **WBS 无此项** | KERT **零本体资产**：`find -name "*.ttl|*.owl|*.rdf"` 无结果；`src/` 内 `owl/shacl/sparql` 零命中。本体权威在 **gits 仓** `specs/semantic/gits-core.owl.ttl`（CTR-SEM-002） |
| **语义层到数据源连接** | WBS **M7.1** KnowledgeSource typed capability | 未开工。现状是**真实可运行**的替代形态：文件目录权威源 + Parquet 投影（`src/kert/domain/hashing.py`、`cli/main.py:203`）+ Kùzu 图（`kuzu_builder.py`）+ SQLite 运行时存储（`src/kert/infrastructure/stage_store.py`、ADR-012） |

**另发现一处状态失真（非本次裁定项，建议顺手修）**：
`KERT_STATUS_BASELINE_CANDIDATE.yaml:86-87` 记 `production_security: DESIGNED_NOT_IMPLEMENTED`、`auth_enabled: false`，
但 **M2.1/M2.2 已在代码中接线**：`src/kert/api/server.py:218-219`（`ApiKeyAuthMiddleware` / `RateLimitMiddleware`）。
⇒ **权威状态文件落后于代码**（该文件日期 2026-08-26）。按"唯一权威源"纪律，应由 TL 出修订候选，**不静默改写**。

**计划位**：`START_HERE.md` 明示当前第一个可执行任务是 **M2-P1**；`KERT_PHASE0_DECISION_RECORD.md` 与 `ADR-013` 均为
`CANDIDATE_*_FOR_OWNER_*`（**未签署**）；`PRODUCTION_RELEASE_GATE=BLOCKED`。

---

## 1. 需要裁定的三件事

### D1 —— 是否授权**跳期**：在 Phase 0 未签署、M2 未收口的情况下提前实施 M7？

| 方案 | 内容 | 影响 |
|---|---|---|
| **D1-A（TL 建议）** | 授权**提前实施 M7 中"零新依赖、不落盘、不改 GITS"的子集**：`KnowledgeMapRegistry` + `RoutePolicy` + `ActivationPlan`（含**可重放 plan hash**），即独立评审 §4.7 已给出的目标设计 | 不触碰规格禁令；不需要规格修订；为 M3/M4/M5 提供控制面；M2 收口并行推进 |
| D1-B | 严格按计划位：先收 M2（认证/限流/持久 Worker/可观测/备份等 10 项）再做 M7 | 最保守，但"尽快进化完成"无法达成 |
| D1-C | 全量跳期到 M7（含 M7.1–M7.5） | 需同时细化 M7 任务定义（当前 WBS 只有标题、无内容） |

**依据**：独立评审 `docs/dd/KERT_independent_architecture_review_2026-08-26_V1.0.md:395-404` 已把
`KnowledgeMapRegistry / RoutePolicy / ActivationPlan` 的目标设计写清（ID/版本/资产引用、capability catalog、
RoutePolicy 输入/优先级/**歧义拒绝**/**默认拒绝**、ActivationPlan 资产/Skill/工具/权限/版本快照、
**可重放 plan hash**、同优先级歧义 fail-closed）。⇒ D1-A 是**实施既有设计**，不是发明范围。

### D2 —— **LightRAG** 是否引入？（TL 无法自决，与现有硬约束直接冲突）

| 冲突证据 | 原文 |
|---|---|
| KERT-SPEC-001 §1.5/§2.2/§6.3/§15.4/**§18.5**/ADR-002 | **禁止持久化数据库**（`docs/evaluation-sqlite-graph-base.md:6` 引述） |
| 图引擎选型结论 | "技术上合理，但与规格硬约束冲突，**默认不可引入**；如确有需要，必须走**受控变更（Owner 决策 + 规格修订 + ADR 记录）**，或仅以**"内存 SQLite 查询加速层（不落盘、可重建）"**形态出现并明确声明" |
| 选型推荐路径 | **方案 A**：维持文件化图谱 + 内存增强（零冲突、保验收） |
| WBS | **LightRAG 不在 M1–M9 任何任务项中** |

| 方案 | 内容 | 代价 |
|---|---|---|
| **D2-A** | **不引入 LightRAG**，按选型报告方案 A：文件化图谱 + 内存加速（Kùzu）强化，并把"检索增强"落在**已规划的 M7.1 KnowledgeSource typed capability** 上 | 与现状一致；但"LightRAG"作为**具名技术**不被采用 |
| D2-B | 引入 LightRAG，且**仅作内存/可重建加速层**（不落盘），显式声明 | 需确认 LightRAG 是否可满足"不落盘"；其索引形态需评估 |
| D2-C | 引入 LightRAG 并落盘 | **需规格修订 + 新 ADR + Owner 决策**；将影响 §18.5 验收 |

> ⚠ TL 特别提示：**gits 侧已有 LightRAG 相关交付**（GK-KE 程序含 `GK10-l5-2-lightrag` Loop），
> 而 gits 侧另一 Loop 又记有"LightRAG 启用（`abc_comparison` 已判未启用）"的相反口径。
> ⇒ 跨仓**口径可能不一致**，请 Owner 一并明确"LightRAG 归哪个仓、以何种形态"。

### D3 —— **本体模型**是否进 KERT？以何种角色进？

| 冲突证据 | 说明 |
|---|---|
| KERT `AGENTS.md` 规则 #1 | **不得修改 GITS 仓库** |
| 本体权威归属 | 本体资产（OWL/LinkML/SHACL）在 **gits**：`specs/semantic/gits-core.owl.ttl`（CTR-SEM-002，实测 32 类 / 34 对象属性 / 1 数据类型属性 / 0 个体）；gits 侧已建成 `OntologyPort` + Jena 适配器 + **fail-closed** 装载（GK17 / W2） |
| KERT 定位 | "Python Core：唯一公共入口、控制面、**知识/数据权威源**" —— 与"本体权威"是否分离未明示 |
| WBS | **本体模型不在 M1–M9 任何任务项中** |

| 方案 | 内容 | 影响 |
|---|---|---|
| **D3-A（TL 建议）** | KERT **不内置本体定义**，而是通过**只读消费** gits 的本体（契约引用 + 版本哈希，如 `CTR-SEM-002@sha256:…`）参与路由裁决 | 零跨仓越权；与 gits 已建成的 `OntologyPort` 口径一致；KERT 侧只需"引用 + 版本锚定" |
| D3-B | KERT 内置一份**自有**本体（与 gits 并存） | 产生**双权威**，须解决一致性/归属；违背"单一权威源"倾向 |
| D3-C | 把本体权威迁到 KERT | **跨仓架构变更**，须 Owner + ADR |

---

## 2. TL 的建议（供裁定参考，**不是**决定）

1. **D1-A**：授权提前实施 M7 的零冲突子集（`KnowledgeMapRegistry` / `RoutePolicy` / `ActivationPlan` + 可重放 plan hash），
   依据是 KERT **自己的**独立评审 §4.7 已给出目标设计；
2. **D2-A**：不引入 LightRAG 具名技术；"检索增强"落在 M7.1 KnowledgeSource typed capability + 既有 Kùzu/Parquet 形态上；
   若确需 LightRAG，请至少指定其为**D2-B（不落盘加速层）**；
3. **D3-A**：KERT 只读消费 gits 本体（契约引用 + 内容哈希版本），**不内置第二份本体定义**。

## 3. TL **已经在做**（无需上述裁定，不越线）

- 按独立评审 §4.7 的目标设计，实施 **`KnowledgeMapRegistry` + `RoutePolicy` + `ActivationPlan`**：
  全部落在**文件目录权威源 + 内存**内，**零新依赖、不落盘、不修改 GITS**、不触发 `autoReload`、不做生产写回；
- 同步出 `KERT_STATUS_BASELINE_CANDIDATE.yaml` 的**修订候选**（修 M2.1/M2.2 状态失真），**不静默改写**受控文件。

## 4. 非声明

- 本文档**不是** Owner 决策、**不是**规格修订、**不是** ADR；`PENDING_OWNER_DECISION` 状态的项**不得**被当作已批准；
- 本文档**不**声称任何能力已完成、**不**声称 `PRODUCTION_READY` / `GITS_UAT_PASS`；
- 本节所列"现状"均为**只读清点**结论，附文件与行号；未复核项已标注；
- 未修改 GITS 仓库（`AGENTS.md` 规则 #1）；未删除/覆盖任何历史文档。
