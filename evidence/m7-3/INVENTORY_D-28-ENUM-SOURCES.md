# 只读清单：合同 `enum` × 仓内权威源（D-28）

```text
ID       : M7-CLOSURE-C20-D28-ENUM-SOURCES
性质     : **只读分析产物** —— 未改合同、未改代码、未 commit
裁决依据 : D-28（TL 2026-09-16 登记：25 处 enum 的类级核对）
作者     : c20（契约/实现面）
DATE     : 2026-09-16
口径     : 合同 enum 取自 `specs/kert-openapi-v1.yaml`（YAML 节点行号，1-based）；
           仓内权威源 = `src/**/*.py` 中的 (a) 命名常量列表 (b) 调用实参 `enum=[…]`（含 FieldSpec）
           判定 = 值域集合**相等** ⇒ 一致；`合同 ⊂ 源` / `源 ⊂ 合同` / 部分重叠 ⇒ 漂移；
           无任何交集的等值源 ⇒ **无仓内权威源**（也须报：属「本该有源却手写」）
⚠ 注意 : 表 1 的「漂移」列是**机械关系**（与某源有交集但**不等**），**不等于**语义同域。
         其中多数经人工核为**语义域不同**（假阳性）⇒ **以 §2 的人工裁定为准**。
```

## 0. 计数

- 合同 `enum` 节点实测：**25 处**
- 仓内候选源实测：**100 条**（`src/**/*.py`）
- 判定汇总：一致 = 2；无仓内权威源 = 14；漂移（合同窄于仓内源） = 2；漂移（部分重叠） = 7

## 1. 逐处清单

| # | 合同行号 | 上下文路径 | 当前值域 | 值数 | 仓内权威源（值域相等者） | 判定 |
|---|---|---|---|---|---|---|
| 1 | `specs:1003` | `components.schemas.HealthResponse.properties.status.enum` | ok, degraded | 2 | **（未找到值域相等的源）** | 无仓内权威源 |
| 2 | `specs:1030` | `components.schemas.SkillHealthResponse.properties.status.enum` | ok, degraded | 2 | **（未找到值域相等的源）** | 无仓内权威源 |
| 3 | `specs:1090` | `components.schemas.SkillParameter.properties.type.enum` | string, number, boolean, object, array | 5 | **（未找到值域相等的源）** | 无仓内权威源 |
| 4 | `specs:1183` | `components.schemas.SkillExecuteResponse.properties.status.enum` | ok, skill_error, exit_policy_no_new_evidence | 3 | **（未找到值域相等的源）** | 无仓内权威源 |
| 5 | `specs:1249` | `components.schemas.ServiceResult.properties.status.enum` | SUCCESS, PARTIAL | 2 | `parse_status`（FieldSpec，`src/kert/domain/contracts/specs.py:108`，4 值）；`status`（FieldSpec，`src/kert/domain/contracts/specs.py:479`，3 值） | 漂移（部分重叠） |
| 6 | `specs:1320` | `components.schemas.InteractionMemoryResult.properties.status.enum` | SUCCESS, PARTIAL | 2 | `parse_status`（FieldSpec，`src/kert/domain/contracts/specs.py:108`，4 值）；`status`（FieldSpec，`src/kert/domain/contracts/specs.py:479`，3 值） | 漂移（部分重叠） |
| 7 | `specs:1353` | `components.schemas.Citation.properties.factLabel.enum` | F, C, B, H, P, A | 6 | `_RATING_ORDER`（常量，`src/kert/application/product_recommendation/eligibility.py:77`，4 值） | 漂移（部分重叠） |
| 8 | `specs:1379` | `components.schemas.CandidateMemory.properties.category.enum` | PREFERENCE, DECISION_PATTERN, RELATIONSHIP, BUSINESS_SIGNAL, EMOTIONAL_STATE | 5 | `MEMORY_CATEGORIES`（常量，`src/kert/application/interaction_memory.py:18`，5 值） | 一致 |
| 9 | `specs:1389` | `components.schemas.CandidateMemory.properties.suggestedDecayRule.enum` | NONE, LINEAR, STEP | 3 | `DECAY_RULES`（常量，`src/kert/application/interaction_memory.py:20`，3 值） | 一致 |
| 10 | `specs:1400` | `components.schemas.MemoryUpdate.properties.action.enum` | REINFORCE | 1 | **（未找到值域相等的源）** | 无仓内权威源 |
| 11 | `specs:1428` | `components.schemas.RuleViolation.properties.severity.enum` | BLOCKING, WARNING | 2 | **（未找到值域相等的源）** | 无仓内权威源 |
| 12 | `specs:1445` | `components.schemas.GateRecommendations.properties.overallReadiness.enum` | READY, BLOCKED | 2 | `final_status`（FieldSpec，`src/kert/domain/contracts/specs.py:628`，4 值）；`decision`（FieldSpec，`src/kert/domain/contracts/specs.py:993`，5 值）；`JOB_STATES`（常量，`src/kert/domain/states.py:11`，9 值） | 漂移（部分重叠） |
| 13 | `specs:1462` | `components.schemas.GateChecklistItem.properties.state.enum` | PASSED, READY_FOR_REVIEW, BLOCKED, PENDING | 4 | `parse_status`（FieldSpec，`src/kert/domain/contracts/specs.py:108`，4 值）；`final_status`（FieldSpec，`src/kert/domain/contracts/specs.py:628`，4 值）；`verification_status`（FieldSpec，`src/kert/domain/contracts/specs.py:749`，3 值） | 漂移（部分重叠） |
| 14 | `specs:1487` | `components.schemas.AsyncAcceptedResponse.properties.status.enum` | PENDING | 1 | `parse_status`（FieldSpec，`src/kert/domain/contracts/specs.py:108`，4 值）；`verification_status`（FieldSpec，`src/kert/domain/contracts/specs.py:749`，3 值）；`JOB_STATES`（常量，`src/kert/domain/states.py:11`，9 值） | 漂移（合同窄于仓内源） |
| 15 | `specs:1537` | `components.schemas.JobStatusData.properties.schema.enum` | job_status/v1 | 1 | **（未找到值域相等的源）** | 无仓内权威源 |
| 16 | `specs:1548` | `components.schemas.JobStatusData.properties.status.enum` | PENDING, RUNNING, COMPLETED, FAILED | 4 | `JOB_STATES`（常量，`src/kert/domain/states.py:11`，9 值） | 漂移（合同窄于仓内源） |
| 17 | `specs:1672` | `components.schemas.GateAuditRequest.properties.decision.enum` | PASSED, BLOCKED, WAIVED | 3 | `final_status`（FieldSpec，`src/kert/domain/contracts/specs.py:628`，4 值）；`decision`（FieldSpec，`src/kert/domain/contracts/specs.py:993`，5 值）；`JOB_STATES`（常量，`src/kert/domain/states.py:11`，9 值） | 漂移（部分重叠） |
| 18 | `specs:1701` | `components.schemas.GateAuditResponse.properties.decision.enum` | PASSED, BLOCKED, WAIVED | 3 | `final_status`（FieldSpec，`src/kert/domain/contracts/specs.py:628`，4 值）；`decision`（FieldSpec，`src/kert/domain/contracts/specs.py:993`，5 值）；`JOB_STATES`（常量，`src/kert/domain/states.py:11`，9 值） | 漂移（部分重叠） |
| 19 | `specs:1803` | `components.schemas.ErrorResponse.properties.status.enum` | skill_error, exit_policy_no_new_evidence | 2 | **（未找到值域相等的源）** | 无仓内权威源 |
| 20 | `specs:1858` | `components.schemas.SkillExecuteErrorResponse.properties.status.enum` | skill_error | 1 | **（未找到值域相等的源）** | 无仓内权威源 |
| 21 | `specs:1914` | `components.schemas.ActivationPlan.properties.schema.enum` | activation_plan/v1 | 1 | **（未找到值域相等的源）** | 无仓内权威源 |
| 22 | `specs:2107` | `components.schemas.ExtractionsAcceptedResponse.properties.status.enum` | ACCEPTED | 1 | **（未找到值域相等的源）** | 无仓内权威源 |
| 23 | `specs:2203` | `components.schemas.SearchRequest.properties.mode.enum` | FULLTEXT, VECTOR, HYBRID | 3 | **（未找到值域相等的源）** | 无仓内权威源 |
| 24 | `specs:2254` | `components.schemas.GraphQueryRequest.properties.direction.enum` | OUT, IN, BOTH | 3 | **（未找到值域相等的源）** | 无仓内权威源 |
| 25 | `specs:2257` | `components.schemas.GraphQueryRequest.properties.mode.enum` | neighbor, closure, paths | 3 | **（未找到值域相等的源）** | 无仓内权威源 |

## 2. 人工裁定（对机械关系的语义过滤）

| # | 合同行号 | 机械关系 | 人工裁定 | 依据（同域产生点 / 命名源） |
|---|---|---|---|---|
| 5, 6 | `:1249`, `:1320` | 与 `parse_status`(`specs.py:108`)、`status`(`specs.py:479`) 有交集 | **假阳性 ⇒ 无同域命名源**（同域值由**字面量**产生） | `service_proposal.py:180`、`interaction_memory.py:102` 均写作 `"SUCCESS" if … else "PARTIAL"` |
| 7 | `:1353` | 与 `_RATING_ORDER`(`eligibility.py:77`) 有交集 | **假阳性 ⇒ 无同域命名源** | 同域字面量在 `service_proposal.py:299-300`（`includes:["F","A"]` / `excludes:["C","B","H","P"]`）、`:322-323`、`:341` |
| 12, 13 | `:1445`, `:1462` | 与 `JOB_STATES`/`final_status`/`parse_status` 有交集 | **假阳性 ⇒ 无同域命名源** | 同域字面量在 `service_proposal.py:358`(`"PASSED"`)、`:363`(`BLOCKED`/`READY_FOR_REVIEW`)、`:369`(`PENDING`)、`:372`(`READY`/`BLOCKED`)；**同一域还被第二处字面量地图复制**（`report.py:390`） |
| 17, 18 | `:1672`, `:1701` | 同上 | **假阳性 ⇒ 无同域命名源**；另见 §3 附带发现① | 同上；`WAIVED` 在 `src/**` **零命中** |
| 14 | `:1487` | 与 `JOB_STATES`/`parse_status`/`verification_status` 有交集 | **假阳性 ⇒ 无同域命名源**（同域值 = 字面量 `"PENDING"`） | `server.py:659` |
| **16** | **`:1548`** | 与 `JOB_STATES`(`states.py:11`，9 值) 构成**真超集** | ✅ **真漂移 = D-27**（合同 4 值 ⊂ 仓内权威 9 值） | 同域权威源确为 `JOB_STATES`（文件契约 `job_status/v1` 直接取 `list(JOB_STATES)`，`contracts/specs.py:585`） |
| 8, 9 | `:1379`, `:1389` | 值域**完全相等** | ✅ **一致（正面模型）** | `MEMORY_CATEGORIES`(`interaction_memory.py:18`)、`DECAY_RULES`(`:20`)；且实现**用后者做校验**（`:171`） |
| 1–4, 10, 11, 15, 19–25 | `:1003` … `:2257` | 无任何交集候选 | **无仓内权威源**（本轮未在其同域找到命名源；其实现侧产生点**未逐处取证**） | 未扫描其它形态（见 §4） |

## 3. 结论：**系统性**，不是单点

- **能对到「值域相等」命名源的只有 2/25**（`MEMORY_CATEGORIES`、`DECAY_RULES`），且这两处实现**都在用该源做校验** ⇒ 可直接作"**立源**"的模板。
- **真漂移仅 1 处**：`JobStatusData.status`（合同 4 值 ⊂ `JOB_STATES` 9 值）= **D-27**。
- **其余 22/25 处「无等值仓内源」**，其中已取证者显示：同域值**只以字面量 / 字面量地图散布**
  （`SUCCESS|PARTIAL`、`F|C|B|H|P|A`、gate 的 `PASSED|READY_FOR_REVIEW|BLOCKED|PENDING`、
  `ok|degraded`、`ACCEPTED`…）。⇒ 这正是 TL 所指的「**本该有源却手写**」那一类，且**是系统性的**：
  在现仓形态下，「合同 enum ↔ 实现值域」的机械核对**大多没有可比对的源**，只能退化为逐处人工比对。
- **可操作收口方向（供登记，本轮不做）**：按 `MEMORY_CATEGORIES` / `DECAY_RULES` 的形态把上述值域**立为命名源**，
  再让类级核对「**合同 enum == 命名源**」成为可执行断言。
- **两条附带发现（供裁）**：① `GateAuditRequest.decision` 的 **`WAIVED` 在 `src/**` 零出现**（合同独有值，
  是否"只声明未落实现"须裁）；② 同一语义域（gate state/decision）在 `service_proposal.py:358-372` 与
  `report.py:390` **两处各自维护字面量地图**（重复源）。

## 4. 非声明

本文件为只读分析产物，**不主张**已穷尽仓内权威源（扫描口径限 `src/**/*.py` 的「命名常量列表」与「调用实参 `enum=[…]`」两种形态；其它形态（如散落字面量、文档声明、skill 资产内的类别枚举）**不在本轮扫描口径内**）；**不代表** D-28 已关闭。

