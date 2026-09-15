# 候选方案：v1 ↔ v2 契约归并（冲突 C-20 收口）

> **行号说明（2026-09-16，D-8；TL 授权仅加本句）**：本文件内所有行号引用（`v1:NNN` / `server.py:NNN`）均系**该时点快照**；
> 此后 spec 净 **+166/−5**（本批增删），且 `server.py` 另有 **+2 / +28** 分段位移 ⇒ **勿按固定偏移换算**。

```text
TASK_ID     : M7-CLOSURE-C20-CONTRACT-MERGE-CANDIDATE
TASK_PACKAGE: evidence/m7-3/TASK_PACKAGE_C20-CONTRACT-MERGE-CANDIDATE.md
性质        : 只读分析 + 候选方案（decision-ready）；**不产生合同效力**
AUTHORITY   : Contract Owner 2026-09-15 批准"将 v1↔v2 双权威归并列入 W8/Phase 0 收口"
              登记：docs/governance/KERT_PENDING_OWNER_DECISION_M7_EVOLUTION_V1.0.md §0.1:52-54
              冲突：docs/governance/KERT_DOCUMENT_CONFLICT_REGISTER.md C-20:44
HEAD_ANCHOR : 分支 feature/m7-3-knowledge-map-route（本分析未提交、未 push）
DATE        : 2026-09-16
```

> **本文件不修改任何合同/源码/测试**：全部结论来自对 `specs/**`、`docs/contracts/**`、`src/**`、
> `tests/**`、`scripts/**`、`examples/**`（KERT 仓，只读）与 `gits-cbanking`（GITS 仓，只读）
> 的逐行引用。归并**未执行**。

---

## 0. 结论摘要（供 Contract Owner 直接裁决）

| # | 问题 | 推荐结论 | 一句话理由（证据见 §2） |
|---|---|---|---|
| D1 | 单一权威选谁 | **选 v1（`specs/kert-openapi-v1.yaml`，1.5.0）为"服务面权威"** | 服务实际实现走 v1 面（`src/kert/api/server.py:607-747`），GITS 现行调用面 6 条全部命中 v1，且 4 个测试把 v1 当合同源（§1.4） |
| D2 | `/api/skill/*` 与 `/v1/*` 与 `/api/v2/*` 如何收敛 | `/api/skill/*` + `/v1/*` = **v1 之内**；`/api/v2/*` = **未实现候选命名空间，本轮不并入 v1** | 实现中 `/api/v2/*` **零命中**（§2.5-F9）；`/v1/*` 是已实现控制面（`server.py:471-605`） |
| D3 | `docs/contracts/schemas/*.json` 与 v1 内联 schema 的关系 | 保留为**细节 canonical 层**，v1 以引用方式指向（`assembly-trace` 已是先例），**不**与 v1 并列成为第二权威 | v1:709-719 已明确"权威定义见 schemas/assembly-trace.schema.json，本处不复写"；README:14-15 同口径 |
| D4 | `scripts/validate_contract_bundle.py` 应校验哪一份 | **改指向 v1**（或改为 v1 → schemas 的有向 bundle） | 该脚本现只校验 v2（`validate_contract_bundle.py:21`），于是在校验层面**再次**确认了 v2 的权威性，正是 C-20 的成因之一 |
| D5 | 归并是否纯 additive | **不是**，必须分期 | v1/v2 在 6 条共路径 + 错误信封 + 鉴权模型上互相冲突（§2.1-§2.4），且 v1 自身有 5 处与实现失实（§2.5） |
| D6 | 本轮最大风险 | **GITS 活动调用被静默破坏**：v2 未声明 `/api/skill/report/{requestId}`，且把 `skill_result` 提到响应顶层 | v2 路径清单（v2:28-220）无 report 路径；GITS `DshJobPoller.java:122-126` 读 `data.skill_result` |

**推荐方案：A（见 §3.1），分 4 期（§5.3）。否决 B、C 的理由见 §3.2 / §3.3。**

---

## 1. 事实基线（逐项核对，不凭记忆）

### 1.1 任务包 §3 前提核对结果：**全部成立**（1 项需补充说明）

| # | 任务包所述事实 | 核对结果 | 证据 |
|---|---|---|---|
| 1 | v2 自述"Phase 0 候选，不表示生产合同已批准" | ✅ 成立 | `docs/contracts/openapi/kert-openapi-v2.yaml:5-7`（`description` 原文）、`:4`（`version: 2.0.0-candidate`）、`:8`（`x-contract-version: 2.0.0-candidate`） |
| 2 | `docs/contracts/README.md` 原称"唯一权威源"，已于 2026-09-15 修正 | ✅ 成立（修正已落地） | 现文 `docs/contracts/README.md:5`（"权威声明修正于 2026-09-15"）、`:9-11`（运行中权威 = v1）、`:12-13`（v2 未批准）、`:17-20`（原文修正说明 + C-20） |
| 3 | 状态基线记 v13/v14 = CONFLICTING、v2 候选 = DESIGNED_AS_CANDIDATE | ✅ 成立 | `docs/governance/KERT_STATUS_BASELINE_CANDIDATE.yaml:98-100`（v13）、`:101-103`（v14）、`:104-106`（openapi_v2_candidate）、`:107-109`（json_schema_candidate） |
| 4 | C-20 条目与处理方式 | ✅ 成立 | `KERT_DOCUMENT_CONFLICT_REGISTER.md:44`（判定"v1.5 为运行中权威；v2 仍未批准候选"，状态 `OPEN`） |
| 5 | v1.5 增量与追认范围 | ✅ 成立 | `evidence/m7-3/CONTRACT_CHANGE_PROPOSAL_ROUTING_API.md:8-13`（STATUS=已追认）、`KERT_PENDING_OWNER_DECISION_M7_EVOLUTION_V1.0.md:47-67`（§0.1 三项追认） |
| 6 | 校验工具只校验 v2 bundle | ✅ 成立 | `scripts/validate_contract_bundle.py:21`（`OPENAPI = docs/contracts/openapi/kert-openapi-v2.yaml`）、`:75-76`（硬要求 `3.1.0`）；`scripts/contract_bundle_hash.py:20-33`（白名单首项即 v2） |

> **补充偏差（须报告）**：`KERT_DOCUMENT_CONFLICT_REGISTER.md:28` 的"替代关系汇总"仍保留**修正前**口径——
> "契约 v1/v2 替代关系以 OpenAPI/JSON Schema 候选为唯一权威源，v1 保留兼容层"。
> 即 2026-09-15 的修正只改了 `docs/contracts/README.md`，**未同步该行**。这与同行 C-20 判定直接矛盾，
> 属"同一登记册内双口径"，建议随归并一并消除（本任务不改该文件）。

### 1.2 两份规范的身份与体量（只读清点）

| 项 | v1（运行中权威） | v2（未批准候选） |
|---|---|---|
| 路径 | `specs/kert-openapi-v1.yaml` | `docs/contracts/openapi/kert-openapi-v2.yaml` |
| 大小 | 38.23 KB | 13.54 KB |
| OpenAPI 方言 | `3.0.3`（v1:1） | `3.1.0`（v2:1） |
| `info.version` | `1.5.0`（v1:17）→ **已于 2026-09-16 更正为 `1.5.1`** | `2.0.0-candidate`（v2:4） |
| `servers[0].url` | `http://127.0.0.1:8106`（v1:24） | `http://127.0.0.1:8106`（v2:11，描述"实际以部署配置为准"） |
| 路径数 | **14**（v1:42,72,95,130,229,255,299,331,400,418,438,452,472,498） | **10**（v2:28,41,91,115,139,157,177,195,203,213） |
| schema 数 | **36**（更正记录：原文写 30，系笔误——未逐个数 `components.schemas`；实测 36） | 17（v2:257-567） |
| 顶层 `security` | **无**（仅定义 schemes，v1:529-534） | **有**全局要求（v2:13-14） |
| 可复用 `responses` | 无 | 4 个（v2:230-254） |

> **§1.2 更正记录（2026-09-16，TL 授权）**
> ① `schema 数` 原文写 **30** 系**我的算术错误**（未逐个数 `components.schemas`），实测为 **36**；已更正为 36。
> ② `info.version` 已于 2026-09-16 更正为 **`1.5.1`**（更正性补丁）：Contract Owner 追认的对象是
>    **`1.5.0` 的 additive 增量**，而该 artifact 其后被更正两次 ⇒ bump 以保持"被追认对象唯一可指"。
> ③ 经 F1/F3/F4/F5 形状更正 + 错误信封族如实化后，**当前实测**：`version 1.5.1`、
>    `components.schemas` **42**、`paths` **14**（路径数未变）、文件 **63418 字节**（分析时为 38.23 KB）。
> ④ 以上仅为**快照数字修正**，不改变 §1.2 表内其余判读结论与 §3 的归并推荐。

### 1.3 第三份治理产物：内部合同（**不属本次归并范围，但从"权威"视角必须登记**）

- `docs/contracts/internal/openapi/kert-skill-runtime-internal-v1.yaml:1-5` 自述
  "Python Core -> Java Skill Runtime private contract. **Not for external clients**"，`version: 1.0.0-candidate`，
  `security: InternalTokenAuth`（`:9-10`, `:52-56`）。
- 它**不是**对外权威，但其所在目录 `docs/contracts/**` 同时承载"对外 v2 候选"，
  这正是"目录即权威"错觉的来源之一。归并结论须显式说明：**对外面只保留 1 份权威**，
  内部面另立（不并入）。

### 1.4 v1 已被机器消费的事实（决定"选 v1"不能只是文档姿态）

| 消费者 | 绑定的合同文件 | 证据 |
|---|---|---|
| v1.5 路由 API 集成测试 | `specs/kert-openapi-v1.yaml` | `tests/integration/test_routing_api.py:22`（`SPEC = .../kert-openapi-v1.yaml`）、`:55-56`（读 `ActivationPlan.required`）、`:59`（读 `data.plan`）、`:115-116`（读 `data.allowed`） |
| 路由 trace 机械核对 | `specs/kert-openapi-v1.yaml` + `schemas/assembly-trace.schema.json` | `tests/integration/test_skill_routing_trace.py:224-228` |
| SP-15 错误码登记核对 | `specs/kert-openapi-v1.yaml` | `tests/integration/test_sp15_contract_conformance.py:57`（`OPENAPI_SPEC`）、`:109-112`（正则抽取 `KERT_*` 码）、`:459-462` |
| 参考 GITS 客户端 | 端点面 `/v1/skills` 等 | `examples/gits_adapter/python/kert_client.py:199-201` |

> **反向事实（治理缺口）**：`src/kert/infrastructure/release.py:217-224` 的发布清单只哈希
> `docs/contracts/openapi`、`docs/contracts/schemas`、`docs/contracts/internal`、`skills/`——
> **`specs/` 不在其中**。即"运行中权威"当前**不进入发布制品哈希**，而"未批准候选"进入。
> 归并方案必须同时修这条（§3.1 P2）。

---

## 2. 差异矩阵（每项附 `文件:行号` 证据）

### 2.1 路径级差异（14 vs 10）

**A. 双方共有路径（6 条）——但**4 条**的响应形状不一致（见 §2.2）**

| # | 路径 | v1 | v2 | 判定 |
|---|---|---|---|---|
| 1 | `/api/skill/health` | v1:72-93，`operationId: getSkillHealth` | v2:28-40，`operationId: listSkills` | **operationId 冲突**（见下 B-①） |
| 2 | `/api/skill/execute` | v1:130-227 | v2:41-90 | 路径同、状态码集不同（§2.3） |
| 3 | `/v1/jobs/{jobId}` | v1:331-398 | v2:91-114 | 路径同、响应 schema 不同（§2.2-④） |
| 4 | `/api/skill/gates/{customerId}` | v1:255-297，`operationId: getGates` | v2:139-156，`operationId: listGates` | **schema 结构性冲突**（§2.2-②） |
| 5 | `/api/skill/gates/audit` | v1:299-329，`operationId: auditGate` | v2:157-176，`operationId: recordGateAudit` | 响应 schema 不同（§2.2-③） |
| 6 | `/livez` `/readyz` `/metrics` | v1:400-450（`livez`/`readyz`/`getMetrics`） | v2:195-220（`liveness`/`readiness`/`metrics`） | operationId 全不一致（§2.3-D） |

**B. v1 独有（8 条）**

| # | 路径 | v1 行号 | 实现 | 说明 |
|---|---|---|---|---|
| ① | `GET /v1/health` | v1:42-70 | `server.py:448-469` ✅ | GITS 未调用；v2 未声明 |
| ② | `GET /v1/skills` | v1:95-128 | **未实现** | `docs/integration/KERT_GITS_CONTRACT_DIFF.md:14`（"规范要求新增，server.py 尚未实现"）、`:96`（P2 待做）。**v1 自身的"幽灵路径"** |
| ③ | `GET /api/skill/report/{requestId}` | v1:229-253 | `server.py:645-658` ✅ | **GITS 活动调用**（`KERT_GITS_CONTRACT_DIFF.md:16`；GITS `application.yaml:56`；`examples/gits_adapter/README.md:164`）。**v2 完全未声明 → 高危** |
| ④ | `GET /v1/knowledge-maps` | v1:452-470 | `server.py:693-713` ✅ | v1.5 追认增量（§0.1 追认项 ①）；v2 未声明 |
| ⑤ | `GET /v1/knowledge-maps/{mapId}` | v1:472-496 | `server.py:715-727` ✅ | 同上 |
| ⑥ | `POST /v1/routing/plan` | v1:498-526 | `server.py:729-747` ✅ | 同上 |
| ⑦ | （实现有、v1 无）`/v1/extractions`、`/v1/extractions/{job_id}/result`、`/v1/entities/{entity_id}`、`/v1/data/query`、`/v1/search`、`/v1/graph/query`、`/v1/rules/evaluate`、`/v1/evidence/{object_id}`、`/v1/catalog` = **9 条** | **v1 未登记** | `server.py:471-500`、`:510-520`、`:522-528`、`:530-537`、`:539-546`、`:548-559`、`:561-567`、`:569-592`、`:594-605`；服务自述清单 `server.py:4-17` | **已实现但未入 v1**；其中 `/v1/graph/query` 是 v2 **唯一**声明到该域的路径（v2:177-194） |

**C. v2 独有（2 条）**

| # | 路径 | v2 行号 | 实现 | 说明 |
|---|---|---|---|---|
| ① | `POST /v1/graph/query` | v2:177-194 | `server.py:548-559` ✅ | 唯一"v2 有、实现有、v1 无"的路径 → **应并入 v1** |
| ② | `POST /api/v2/jobs/{jobId}/cancel` | v2:115-138 | **未实现**（`src/**` 内 `/api/v2` 零命中） | 与 `docs/contracts/README.md:34`"新增 `/api/v2/*`（候选）"呼应；`KERT_PHASE0_DECISION_RECORD.md:37`（D-06 批准"v1 保留兼容层、新增 `/api/v2` 候选"） |

**D. operationId 命名冲突（机械后果）**

- `listSkills`：v1 用于 `GET /v1/skills`（v1:100），v2 用于 `GET /api/skill/health`（v2:30）。
  两份文件各自的 operationId 内部唯一，但**归并后必然撞名**，且语义不同（一个是"列 Skill 详情含参数"，
  一个是"健康检查 + 能力状态"）。任何"合并成一份"的机械操作都会在此处静默改写语义。
- 另有 4 组同端点不同名：`getSkillHealth`/`listSkills`、`getGates`/`listGates`、`auditGate`/`recordGateAudit`、
  `livez`/`liveness`、`readyz`/`readiness`、`getMetrics`/`metrics`（v1:47,77,100,139,234,262,306,338,405,423,443
  vs v2:30,43,93,117,141,159,179,197,205,215）。

### 2.2 schema 级差异（逐项）

| # | 对象 | v1 | v2 / JSON Schema | 冲突性质 |
|---|---|---|---|---|
| ① | **`SkillHealthResponse`** | v1:551-561，`required: [status, skills]`，**无 `service`** | v2:257-272，`required: [status, service, skills]`，`service` 注 `x-note: 生产版应配置化，不写死 customer-engagement`（v2:266） | **v2 更贴合实现**：实现返回 `{status, service:"customer-engagement", skills}`（`server.py:612-617`）。v1 因未 `additionalProperties:false` 而"恰好不报错"，但 v1 未登记 `service`（撞 C-14 同源问题） |
| ② | **`GateListResponse.gates[]`** | v1:1042-1051 → `GateChecklistItem`（v1:974-994）：`{gate, state, name, checklist:{must[],forbidden[]}}`；示例 v1:277-295 亦为 `gate: G0 / state: PASSED / checklist.must` | v2:458-467 → `GateDefinition`（v2:469-492）：`required [gateId,name,sequence,must,forbidden]` + `assetPath/version/contentHash`；`schemas/gate.schema.json:6-45` 同形且 `additionalProperties:false`（`:45`） | **结构性冲突，且 v2 正确**：实现返回 `{"gateId","name","sequence","must","forbidden","assetPath"}`（`src/kert/application/service_proposal.py:114-117`，经 `skills.py:890-896` → `server.py:660-663`）。**v1 的 `gate`/`state`/`checklist` 三个键在实现中不存在** |
| ③ | **`GateAuditResponse`** | v1:1074-1085：`{recorded, timestamp, auditPath}` | v2:509-519：`{recorded, auditId, recordedAt}` | **两者都与实现不符**：实现返回 `{"recorded":true, customerId, gate, decision, decidedBy, reason, recordedAt}`（`skills.py:907-920`）。v1 的 `timestamp`/`auditPath` 不存在；v2 的 `auditId` 不存在；`recordedAt` 在 v2 ✅ |
| ④ | **Job 状态响应** | v1:1009-1040 `JobStatusResponse`：`required [jobId, status]`，`jobId`/`createdAt`/`startedAt`/`completedAt`，`data.skill_result`（v1:1027-1032，`description: COMPLETED 时包含 skill_result`） | v2:362-374 `JobResponse`：`required [jobId, status]`，**顶层** `skill_result` + `error`；`schemas/job.schema.json:25-27`（`skill_result`）、`:14-24`（status 6 值含 `DEAD`/`CANCELLED`） | **`skill_result` 位置不一致**：v1 在 `data.skill_result`，v2 在顶层。**GITS 现读 `data.skill_result`**（`gits-cbanking/.../DshJobPoller.java:122-126`）→ v2 采用即破坏轮询器（另见 §2.5-G） |
| ⑤ | **错误信封** | v1:1087-1099 `ErrorResponse`：`required [requestId, status]` + `status enum [skill_error, exit_policy_no_new_evidence]`（v1:1095）+ `errors[]` | v2:434-443 `ErrorResponse`：`required [error]`，`{error: ErrorItem, requestId, traceId}`；`ErrorItem`（v2:445-456）`required [code, message]` + `retryable`/`details` | **互斥的两种信封**，见 §2.3 |
| ⑥ | **错误明细字段名** | v1:1101-1127 `ErrorDetail`：`code` / `message` / **`detail`**（v1:1125-1127） | `schemas/error.schema.json:10-22`：`code` / `message` / **`retryable`** / **`details`**；v2:445-456 同名 | **同概念两名**：`detail` vs `details`；v1 无 `retryable`。实现用的是 `retryable`（`server.py:311-313`）→ 与 JSON Schema/v2 一致，与 v1 不一致 |
| ⑦ | **`SkillExecuteResponse` 必填集** | v1:694-725：`required [requestId, status, data]`（`errors`/`assemblyTrace`/`modelCalls` 可选） | `schemas/skill-execute-response.schema.json:6-13`：`required` **6 项全必填**；`:49` `additionalProperties:false` | **严格度冲突**：JSON Schema 比 v1 严。实现必发 6 项中的哪些未在 v1 声明，故按 v1 校验通过、按 schema 校验亦通过（当前实现确实都发），但**契约强度不等价** |
| ⑧ | **`SkillExecuteRequest.required`** | v1:622-644：`required [skillId, requestId, request]` | v2:285-300：`required [skillId]`（`request` 降为可选 `object`）；`schemas/skill-execute-request.schema.json:6-8` 同 v2，且 `:27 additionalProperties:false` | **必填集冲突**：v1 要求 3 项，v2/schema 只要求 1 项。更强的约束在 v1（对 GITS 无影响，GITS 全发，`DshHttpSkillExecutionAdapter.java:29`） |
| ⑨ | **`ContextPackage`** | v1:665-692：`required [schemaVersion, customerId]`，含 `gateState`（v1:679-688）、`proposalContext`（v1:689-692） | v2:302-325 与 `schemas/context-package.schema.json:7-40`：含 `customerName`/`industry`/`enterpriseData`/`interactionContent`/`existingMemories`，`required: []`（schema `:39`），`additionalProperties:true`（`:40`） | **并集关系**：v1 有 `gateState`（v2/schema 无）、v2 有 5 个字段（v1 无）。且 schema 自述"权威 GITS 附录待对齐"（`context-package.schema.json:6`）= 登记在册的缺口（`docs/contracts/README.md:39`） |
| ⑩ | **`ServiceResult`（SP-20）** | v1:753-823：**无** `ruleViolations` | `schemas/sp20.schema.json:60-65`：**有** `ruleViolations`，且 `:67 additionalProperties:false` | v1 把 `ruleViolations` 放在 `SkillExecuteData`（v1:747-751），v2 语义下它在 SP-20 结果内。**位置不同**；`additionalProperties:false` 使该差异成为硬冲突（SP-20 结果带 ruleViolations 时按 sp20.schema 是合规的） |
| ⑪ | **`assemblyTrace` 条目** | v1:709-719：`type: array`（v1.5 由 `object` 修正而来，v1:715-716），元素为 `object` + `additionalProperties:true`，**不 `$ref`**，仅在 prose 指向 canonical schema（v1:711-714） | `schemas/assembly-trace.schema.json`：`required [phase,status,message]`（`:6-10`），含 v1.5 新字段 `mapId`/`mapExpected`/`mapMismatch`/`planHash`/`versions`（`:66-91`），`additionalProperties:true`（`:107`） | **已是"引用式"协同的先例**（READY 模式）：v1 不复写字段，canonical 在 schema。**这正是 D3 推荐的形态** |
| ⑫ | **`nullable` 语法** | v1 使用 `nullable: true` **8 处**：v1:1172,1183,1186,1189,1192,1244,1259,1280（另有 `deprecated: true` v1:662） | v2 无 `nullable`；`schemas/job.schema.json:42-47` 用 `type: ["string","null"]` | **方言冲突**：`nullable` 是 OpenAPI 3.0 关键字，**3.1.0 已移除**（3.1 用 JSON Schema 的 `type` 数组/null）。直接决定 D4 的代价（§3.1 P2） |

### 2.3 错误码 / 状态码级差异

| # | 对象 | v1 | v2 | 判定 |
|---|---|---|---|---|
| A | `/api/skill/execute` 状态码集 | **200 / 202 / 400 / 404 / 500**（v1:175,189,198,210,222） | **200 / 202 / 401 / 403 / 404 / 409 / 413 / 422 / 429**（v2:53,59,65,67,69,75,81,83,89） | **互不包含**：v1 有 400/500 而无 401/403/409/413/429；v2 反之。归并必须取并集并逐条定裁决（`409 幂等冲突`、`413 体积`、`429 限流`在实现中确有对应中间件——`server.py:218-228` 的加固栈描述） |
| B | 错误体结构（同状态码下） | `{requestId, status, errors[{code,message,detail}]}`（v1:1087-1099,1101-1127） | `{error:{code,message,retryable,details}}`（v2:434-456） | **不可兼容的两种结构**。实况是**两者并存**：`/api/skill/execute` 走 v1 式（`server.py:635-643`，来自 `result.as_dict()`），基础设施异常走 v2 式（`server.py:308-316` `_handle()` → `detail={"error":{code,message,retryable}}`） |
| C | 错误码词表 | v1 `ErrorDetail.code` 文档化 **14 个**：`INVALID_PARAMETER`/`SKILL_NOT_FOUND`/`SKILL_EXECUTION_ERROR`/`CONTEXT_VALIDATION_ERROR`/`GATE_CHECK_FAILED`/`JOB_NOT_FOUND`/`INTERNAL_ERROR`/`KERT_PERMISSION_DENIED`/`KERT_CONTEXT_INSUFFICIENT`/`KERT_PRODUCT_KNOWLEDGE_STALE`/`KERT_RULE_VERSION_MISSING`/`KERT_EXECUTION_TIMEOUT`/`KERT_CONTRACT_MISMATCH`/`KERT_EVIDENCE_INCOMPLETE`/`KERT_INTERNAL_ERROR`（v1:1106-1122，注：共列 15 行含 8 个 `KERT_*`） | v2 `ErrorItem.code` 为**自由 string**（v2:449-450），**无词表**、无枚举 | **v2 丢失错误码契约**。而 `KERT_*` 8 码已被测试钉住（`test_sp15_contract_conformance.py:76-79,109-112,459-462`）→ 若以 v2 为权威，这 8 码**失去合同依据**，该测试将引用不存在的规定 |
| D | 探针 operationId | `livez`/`readyz`/`getMetrics`（v1:405,423,443） | `liveness`/`readiness`/`metrics`（v2:197,205,215） | 需择一并登记为 deprecation（无外部消费方，`KERT_GITS_CONTRACT_DIFF.md:21-23` 标"KERT 独有"） |

### 2.4 鉴权级差异

| # | 对象 | v1 | v2 | 实现（第三轴） | 判定 |
|---|---|---|---|---|---|
| A | 顶层 `security` | **无**（v1 只在 v1:529-534 定义 `ApiKeyAuth`，未在任何 operation 或全局启用） | **全局强制** `security: [ApiKeyAuth: []]`（v2:13-14） | `AuthConfig.enabled` 默认 **False**（`src/kert/infrastructure/runtime_config.py:81`） | v1 与实现一致（默认不强制）；v2 是**意图**（生产强制）。差异性质 = "契约声明"vs"当前实况"，须由 Owner 择一表达方式 |
| B | scheme 语义 | `X-API-Key`，描述"**演示环境可省略**"（v1:530-534） | `X-API-Key`，描述"KERT **服务到服务** API Key"（v2:224-228） | 实现：`header_name` 默认 `X-API-Key`，可配 `KERT_AUTH_HEADER`（`runtime_config.py:82`, `:396-404`） | 同名同位置；**描述语义不同**（"可省略" vs "服务到服务"），影响安全评审口径 |
| C | 公共（免鉴权）路径白名单 | **未声明** | `/api/skill/health`（v2:33）、`/livez`（v2:199）、`/readyz`（v2:207）、`/metrics`（v2:217）显式 `security: []` | `DEFAULT_PUBLIC_PATHS = ("/v1/health", "/api/skill/health", "/livez", "/readyz")`（`runtime_config.py:32-33`） | **v2 缺 `/v1/health`**（实现视为公共但目前该路径也不在 v2 路径表内）；v2 的 `/metrics` 公共与实现一致 |
| D | 管理/闸门作用域 | 未声明 | 未声明（v2:157-176 仅要求 `401`） | `/api/skill/gates/audit` 属 `DEFAULT_ADMIN_PATH_PREFIXES`（`runtime_config.py:40`），需 `admin` scope（ADR-013，`server.py:417-423` 同族校验） | **两份都未登记 scope 语义**，而实现已按 scope 拒绝（403）。属共同缺口 |
| E | 限流 / 体积 / 脱敏 | 未声明 | 声明 `429`/`413`（v2:89,81）复用组件（v2:243-254） | 实现有加固栈（限流/并发/体积/脱敏，`server.py:218-228`），可配开关（`runtime_config.py:406-414`） | v2 在"声明"层面更完整；v1 缺声明 |

### 2.5 第三轴：**规范 vs 实现实况**（本次核对的额外发现，超出 v1↔v2 对比但决定归并可行性）

> 说明：任务包要求"路径/schema/错误码/鉴权"四轴 v1↔v2 对比。但归并的**唯一判据是"哪份与运行实况一致"**，
> 故本节单列"规范 vs 实现"。**每项均回源**。

| # | 发现 | 证据 | 影响 |
|---|---|---|---|
| F1 | `/api/skill/gates/{customerId}` 的 v1 形状（`gate`/`state`/`checklist`）**与实现不符**；v2 形状（`gateId`/`sequence`/`must`）**与实现相符** | v1:974-994,277-295 vs `service_proposal.py:114-117` vs v2:469-492 | **v1 有实况失实**（与 `assemblyTrace` 同类，属可修正缺陷） |
| F2 | `/v1/routing/plan` 的 v1 `RoutingPlanResponse` 要求**顶层** `allowed`（`required` 含之，v1:1217），实现把 `allowed` 放在 **`data` 内** | v1:1215-1233 vs `server.py:742-747`（`_response(..., data)`）+ `server.py:206-215`（信封）vs `tests/integration/test_routing_api.py:115-116,151-152`（`["data"]["allowed"]`） | **v1 在 v1.5 新端点上即与实现不符**（测试按 `data.allowed` 断言，故测试绿而合同错）。**这是本次最被低估的缺陷** |
| F3 | `/v1/jobs/{jobId}` 实现返回 `_response("REQ-JOB-...", STATUS.md front matter)`，键为**蛇形** `job_id`/`job_type`/`started_at`/`finished_at`/`progress`…，`skill_result` 位于 `data` 内 | `server.py:502-508`；`jobs.py:236-253`（front matter 键清单）、`:312-333`（`read_job_status`，`:329` 注入 `skill_result`）；测试 `tests/integration/test_service_proposal.py:97,102,118`（读 `["data"]["skill_result"]`） | v1 的 `jobId`（camelCase，`required`）**在实现中不存在**；v2 的顶层 `skill_result` 亦不存在。**两份规范都与实况不符**，且 GITS 读 `data.skill_result`（见 G 行）→ 修合同须避免"按 v1 字面把 `job_id` 改名"（会破坏实现与测试） |
| F4 | `/api/skill/execute` 的 404 响应体**不是** `ErrorResponse`，而是**与 200 同构**的 skill 结果（`status=skill_error` + `errors[0].code=UNKNOWN_SKILL`） | `server.py:635-643`（`status_code=404 if unknown else 200`，同一 `payload`）；GITS 亦按此实现（`DshHttpSkillExecutionAdapter.java:32`："未知 skillId → 404, errors[0].code=UNKNOWN_SKILL"） | v1:210-221 与 v2:69-74 都声明 404 返回 `ErrorResponse` → **两份都失实**（GITS 已按真实行为编码） |
| F5 | `/api/skill/gates/audit` 响应与 v1/v2 均不符 | `skills.py:907-920`（`{recorded, customerId, gate, decision, decidedBy, reason, recordedAt}`）vs v1:1074-1085 / v2:509-519 | 见 §2.2-③ |
| F6 | 错误 `retryable` 字段：实现发 `retryable`（v2/schema 有，v1 无） | `server.py:311-313` vs v1:1101-1127 vs `error.schema.json:17-19` | 支撑 §2.3-B/⑥ |
| F7 | `/api/skill/health` 实现返回 `service`（v2 有，v1 无） | `server.py:612-617` vs v1:551-561 vs v2:257-272 | 支撑 §2.2-①；与 C-14（`service` 写死 `customer-engagement`）同源 |
| F8 | **v1 声明的 `/v1/skills` 未实现**；**实现有 9 条 `/v1/*` 未登记进 v1** | v1:95-128 vs `server.py:4-17`（自述清单）与 `:471-605`（实际路由）；`KERT_GITS_CONTRACT_DIFF.md:14,96` | 双向覆盖缺口；归并须以"实现路由表"为基准做一次全量对账 |
| F9 | **`/api/v2/*` 在实现中零命中** | `src/**` 检索 `/api/v2`、`/v2/` = 0 结果 | v2 的 `/api/v2/jobs/{jobId}/cancel`（v2:115-138）为纯设计；`docs/contracts/README.md:34`、`KERT_PHASE0_DECISION_RECORD.md:37` 只表示"候选/已批准方向" |
| F10 | `x-contract-bundle-hash: PENDING_COMPUTE` 仍留在 v2 头 | v2:9；冲突登记 `C-19`（`KERT_DOCUMENT_CONFLICT_REGISTER.md:38`），状态 `PENDING`；实际 hash 在 manifest（`evidence/phase0/contract-bundle-manifest.json:6` = `72a4d0a9…`） | 归并若保留 v2 任一权威地位，须先关 C-19 |
| F11 | **发布制品哈希不含 `specs/`** | `src/kert/infrastructure/release.py:217-224`（只哈希 `docs/contracts/{openapi,schemas,internal}` 与 `skills/`） | 治理缺口：运行中权威不受版本哈希保护 |

### 2.6 GITS 第三方消费方实况（决定兼容结论）

| GITS 位置 | 事实 | 证据 |
|---|---|---|
| 端点面 | `/api/skill/execute`、`/api/skill/health`、`/api/skill/report`、`/v1/jobs`、`/api/skill/gates/{id}`、`/api/skill/gates/audit` | `gits-cbanking/apps/api/src/main/resources/application.yaml:54-57`；`EngagementConfig.java:156-178`、`:180-194` |
| 执行响应 | 读**顶层** `requestId`/`status`/`data`，并把 `status` 解析为 `ok|skill_error|exit_policy_no_new_evidence` | `DshHttpSkillExecutionAdapter.java:27-33`、`:187-197`、`:205-208` |
| Job 轮询 | 读 **`data.status`** 且**强制非空**；读 **`data.skill_result`** | `DshJobPoller.java:13-16`（文档）、`:71`、`:122-126`、`:128`（"响应缺 data.status" 即抛错） |
| 闸门 | `GET /api/skill/gates/{customerId}`、`POST /api/skill/gates/audit` | `DshHttpSkillGateAdapter.java:20-32` |
| 端口 | GITS 默认 `DSH_BASE_URL=http://127.0.0.1:8107`，与两份合同 `servers` 的 `8106` **不一致** | `gits-cbanking/.../application.yaml:51` vs v1:24 / v2:11（另见 KERT 仓根 `p24_serve_8107.py`） |

> **结论**：`/v1/jobs/{jobId}` 的 `data.status` + `data.skill_result` 是**已投产的跨仓接口形状**。
> 任何把 `skill_result` 移到顶层的方案（= v2 现在的写法）都会使 `DshJobPoller` 在 `:128` 直接抛
> `SkillExecutionException`，走 Fallback。这是本任务认定的**最高级别兼容风险**。

---

## 3. 归并方案（≥2 个，含取舍与否决理由）

### 3.1 方案 A（**推荐**）：v1 = 服务面唯一权威；v2 降级为"非权威设计输入"；schemas 保留为细节 canonical

**内容**

1. **单一权威**：`specs/kert-openapi-v1.yaml`（升级为 `1.6.0`，见 P1）。v1 的 `info.description`
   保留"运行中权威"表述（v1:16），并把"v2 候选未批准"改为"v2 已归档为非权威设计输入"。
2. **路径收敛**：
   - `/api/skill/*` + `/v1/*` **全部落在 v1 之内**（现状即如此，14 条路径不新增前缀）；
   - `/api/v2/*` **不并入 v1**：`/api/v2/jobs/{jobId}/cancel`（v2:115-138）保留为**未实现候选**，
     移至独立文档（如 `specs/kert-openapi-v2-candidate.yaml`）或 `docs/contracts/legacy/`，
     并显式标注 `x-implemented: false`；
   - `POST /v1/graph/query`（v2:177-194，实现有 `server.py:548-559`）→ **并入 v1**。
3. **schema 收敛**：
   - 共 6 条路径中，**v1 正确 1 条、v2 正确 2 条、两者皆错 2 条、需并集 1 条**（据 §2.2 逐项）：
     - 采用 v2：`GateListResponse`/`GateDefinition`（§2.2-②）、`SkillHealthResponse.service`（§2.2-①）；
     - 采用 v1：`JobStatusResponse.data.skill_result` 位置（§2.2-④）、`ErrorResponse` 词表（§2.3-C）、
       `assemblyTrace` 引用形态（§2.2-⑪）、`SkillExecuteRequest.required` 3 项（§2.2-⑧）；
     - 两者皆错，按实现修正：`GateAuditResponse`（§2.2-③/F5）、`/api/skill/execute` 404 体（F4）、
       `RoutingPlanResponse` 信封（F2）、`JobStatusResponse.jobId` vs `data.job_id`（F3）；
     - 并集：`ContextPackage`（§2.2-⑨）、`/api/skill/execute` 状态码集（§2.3-A）。
   - **`docs/contracts/schemas/*.json` 的定位**：保留为"字段级 canonical 细节层"，
     v1 以 **prose 引用 + 可选 `x-canonical-ref`** 指向（`assemblyTrace` 已是既有先例，v1:709-719），
     **不与 v1 并列成为第二权威**；`docs/contracts/README.md:9-13` 需相应改写为
     "v1 = 服务面权威；schemas = 其细节 canonical 层；v2 = 非权威设计输入"。
   - 需修的两处 schema 自述：`context-package.schema.json:6`（"候选 Schema；权威 GITS 附录待对齐"）、
     `docs/contracts/README.md:39`（"GITS 权威 ContextPackage 附录尚未纳入"）→ 归并后仍为**未清单项**（诚实保留）。
4. **`scripts/validate_contract_bundle.py` 校验对象**：
   - 目标态：**校验 v1 + schemas**（bundle = `specs/kert-openapi-v1.yaml` ⊕ `docs/contracts/schemas/*.json`）；
   - 但 `:75-76` 硬要求 `openapi == "3.1.0"`，而 v1 是 `3.0.3`（v1:1）且用了 **8 处 `nullable`**
     （v1:1172,1183,1186,1189,1192,1244,1259,1280）——`nullable` 在 3.1 中**不存在**。
     故 P2 只有两种实现方式：
     - (a) v1 升 3.1.0 + 8 处 `nullable: true` → `type: [T, "null"]`（语义等价改写，须逐处复核）；
     - (b) 校验器改为按 `openapi` 值分支（3.0.x 走 3.0 校验、3.1.x 走 3.1 校验）。
     **推荐 (a)**：把"方言统一"一次做完，避免永久双方言；代价是 v1 历史指纹变化（须重算 bundle hash）。
   - `scripts/contract_bundle_hash.py:20-33` 白名单同步改为 `specs/kert-openapi-v1.yaml` + schemas；
   - `src/kert/infrastructure/release.py:217-224` 增加 `public_contracts_v1 = hash_directory(repo/"specs", patterns=("*.yaml",))`（F11）。

**取舍**

| 维度 | 评价 |
|---|---|
| GITS 兼容 | **零变更**（GITS 只读 `/api/skill/*` + `/v1/jobs`，两处形状均被保留为 v1 形态） |
| 实现改动 | **零**（不改 `src/**`） |
| 合同改动量 | 中等：v1 需 5 处实况修正 + 1 条路径并入 + 8 处 `nullable` 改写；v2 需加非权威标注 |
| 风险 | 主要是"v1 修正"本身要 Contract Owner 批准（属合同修订，不是纯机械）；`nullable` 改写引入方言风险 |
| 治理收益 | 彻底消除双权威：校验对象、发布哈希对象、文档引用对象三者归一 |

### 3.2 方案 B：v2（3.1.0）为唯一权威，v1 降级为有期限兼容层

**内容**：把 v2 补全为包含全部 14 条服务面路径 + 9 条未登记 `/v1/*`，然后把 `specs/kert-openapi-v1.yaml`
标 `deprecated`，设兼容截止期（对齐 `docs/production-evolution-plan.md:67` 的 `/api/v2/*` 演进意图与
`KERT_PHASE0_DECISION_RECORD.md:37` D-06）。

**取舍**

| 维度 | 评价 |
|---|---|
| 与 D-06 决策一致 | ✅（D-06 批准"v1 保留兼容层、新增 `/api/v2` 候选"） |
| GITS 兼容 | ❌ **破坏**：v2 未声明 `/api/skill/report/{requestId}`（§2.1-B③）；`/v1/jobs` 把 `skill_result` 提到顶层（§2.2-④）→ `DshJobPoller.java:122-128` 直接失败 |
| 必须先做的补全 | v2 需补 **6 类**：report 路径、`data.job_id` 与 `jobId` 的关系、`service` 字段确认、错误码词表（§2.3-C）、v1.5 三条路由路径、9 条未登记 `/v1/*` |
| 前提状态 | v2 自述"**未批准**"（v2:7）+ `DESIGNED_AS_CANDIDATE`（`KERT_STATUS_BASELINE_CANDIDATE.yaml:104-106`） |
| 结论 | **否决（本轮）**：采用它等于把未批准候选升格为生产合同，且需 GITS 跨仓改码——与 `Leibniz-KERT/AGENTS.md` 规则 #1（不得修改 GITS 仓库）冲突。可作为 **方案 A 之后的 Phase 3 目标态**（先补全、再批准、再切） |

### 3.3 方案 C：保持双权威，只增加机器可校验的"映射层"

**内容**：新增 `specs/CONTRACT_MAP.yaml`，声明 v1↔v2 的路径/schema 对应与冲突点，加一个校验脚本
断言"两份文件在映射表覆盖内的差异 = 已声明差异"。

**取舍**

| 维度 | 评价 |
|---|---|
| 改动最小 | ✅ 不动两份合同正文 |
| 治本性 | ❌ C-20 的成因是**权威声明与服务实际不符**（`KERT_DOCUMENT_CONFLICT_REGISTER.md:44`），映射层不消除双权威 → 下一次引用仍可分叉 |
| 与 Owner 已批一致 | ⚠ Owner 已批准"**列入**收口"（§0.1:54），映射层等于把收口降级为"长期并存" |
| 结论 | **否决**：可作为方案 A 的**过渡态**（P0→P1 之间），不作为终态 |

### 3.4 方案对比速览

| 判据 | A（v1 权威 + v2 降级） | B（v2 权威） | C（双权威 + 映射） |
|---|---|---|---|
| GITS 是否需改码 | **否** | 是（report + jobs） | 否 |
| 是否消除 C-20 | **是** | 是 | 否 |
| 是否需要 Owner 合同修订 | 是（v1 修正 5 处 + 方言） | 是（v2 补全 + 批准） | 否 |
| 能否本轮完成 | **可（分 4 期）** | 不可（依赖 v2 补全） | 可，但无终局 |
| 与测试/发布链一致性 | 高（4 个测试已绑 v1） | 低（测试全部要改） | 中 |

---

## 4. 兼容与迁移（对现行调用方 GITS 的影响）

### 4.1 影响面判定：方案 A 下 **GITS 零变更**

| GITS 调用 | 依赖的形状 | 方案 A 处置 | 影响 |
|---|---|---|---|
| `POST /api/skill/execute` | 顶层 `requestId`/`status`/`data`/`errors`（`DshHttpSkillExecutionAdapter.java:187-197`） | 保留 v1 信封（v1:694-725） | 无 |
| `POST /api/skill/execute`（async） | 202 `{jobId,status}` | 保留（v1:996-1007；`server.py:631-633`） | 无 |
| `GET /api/skill/health` | `status` + `skills[].skillId` | 保留；**将 `service` 补入 v1**（F7，additive） | 无（GITS 忽略未知字段，`KERT_GITS_CONTRACT_DIFF.md:88`） |
| `GET /api/skill/report/{requestId}` | HTML/JSON | **保留在权威内**（此路径 v2 缺失，采纳 v2 即回归） | 无 |
| `GET /v1/jobs/{jobId}` | `data.status`（非空）、`data.skill_result` | **保留 v1 位置**；`jobId` 与 `data.job_id` 的规范须一次性对齐（见 4.3） | 无（若把 `job_id` 改名反而**有害**） |
| `GET /api/skill/gates/{customerId}` | 未深解（GITS 侧为 raw 透传） | 采用 v2 的 `gateId/sequence/must` 形状（= 实现） | 无（若坚持 v1 形状则**GITS 会拿到与实现不符的合同**） |
| `POST /api/skill/gates/audit` | 未深解 | 按实现修正为 `recorded` + 回显字段（F5） | 无 |
| `/api/v2/*` | 未使用 | 保留为未实现候选 | 无 |

### 4.2 迁移路径（调用方视角）

```text
Phase 0（文档，无代码）：冻结 v2 权威表述；在 v2 头与 docs/contracts/README.md 标注
        "非权威设计输入，服务面权威见 specs/kert-openapi-v1.yaml"
Phase 1（v1 patch）：修正 5 处实况失实 + 并入 /v1/graph/query
Phase 2（工具链）：validate_contract_bundle / contract_bundle_hash / release.py 白名单切 v1
Phase 3（未来 v2）：如需 /api/v2/*，以"补全 → Owner 批准 → 新文档"三步走，不沿用现候选
```

- **GITS 需做**：**无**（方案 A）。
- **GITS 可选做**：把 `DSH_BASE_URL` 默认值与合同 `servers`（8106）对齐，或在合同 `servers` 中
  改为配置占位（当前 v1:24 / v2:11 均写死 8106，而 GITS 默认 8107，冲突 C-04 同源）。
- **KERT 侧不做**：不改 `src/**`、`tests/**`（本任务边界；后续 Loop 另立）。

### 4.3 必须同时裁决的"跨仓字段口径"

`/v1/jobs/{jobId}` 上存在**三方不一致**，且**任何一方单独改都会破**：

| 方 | 期望 | 证据 |
|---|---|---|
| v1 合同 | 顶层 `jobId`（`required`），`data.skill_result` | v1:1009-1032 |
| 实现 | `data.job_id`（蛇形），`data.skill_result` | `server.py:502-508`、`jobs.py:236-253` |
| GITS | `data.status` + `data.skill_result`（不读 `jobId`） | `DshJobPoller.java:122-128` |
| KERT 参考客户端 | 顶层 `jobId` + `data.skill_result` | `examples/gits_adapter/python/kert_client.py:416-434` |

**建议口径（供 Owner 裁决，非本任务结论）**：合同**改为与实现一致**
（`data.job_id` + `data.skill_result`），并**保留** `jobId` 为 `deprecated` 说明；
理由：GITS 现不读 `jobId`（`DshJobPoller` 只读 `data.*`），而实现与 `test_service_proposal.py:97-118`
已按 `data` 断言，**改实现的代价 > 改合同的代价**。**但**若同时要求 KERT 参考客户端可用，
则须同步修 `kert_client.py:425-431`（属 `examples/**`，不在本任务边界内）。

---

## 5. 风险与回滚

### 5.1 风险登记

| # | 风险 | 触发条件 | 等级 | 缓解 |
|---|---|---|---|---|
| R1 | **GITS 轮询静默降级** | 误采 v2 的顶层 `skill_result` | **高** | 方案 A 保留 v1 位置；在合同中显式写"`skill_result` 位于 `data` 内，供 `DshJobPoller` 读取" |
| R2 | **report 路径从权威中消失** | 以 v2 取代 v1 | **高** | 方案 A 不采 |
| R3 | **`KERT_*` 8 错误码失去合同依据** | 采 v2（v2 无码表，§2.3-C） | 中 | 方案 A 保留 v1 码表并考虑补 `retryable` |
| R4 | **契约指纹失效/证据链断裂** | 改校验白名单或改 v1 正文 | 中 | `evidence/phase0/contract-bundle-manifest.json:6` 的 `72a4d0a9…` 将失效 → **保留旧 manifest 不动**，新一期另出 manifest，不覆盖 |
| R5 | **OpenAPI 方言迁移引入语义漂移** | v1 升 3.1.0 后 8 处 `nullable` 改写（v1:1172…1280） | 中 | 逐处 diff 复核 + 用现有测试（`pytest tests/integration`）做回归；不做"批量替换" |
| R6 | **operationId 撞名** | 两份机械合并共享路径（§2.1-D） | 中 | 归并时同时裁决 6 组 operationId，写入 CONTRACT_INDEX 类登记 |
| R7 | **登记册残留矛盾被继续引用** | `KERT_DOCUMENT_CONFLICT_REGISTER.md:28` 未同步 | 中 | 随 P1 一并修正（§1.1 补充偏差） |
| R8 | **`/api/v2/*` 被误当作已实现** | 只读 v2 路径表 | 低 | v2 归档时加 `x-implemented: false`（F9） |
| R9 | 端口 8106/8107 不一致导致联调误判 | 无 `DSH_BASE_URL` 时的默认值 | 低 | 合同 `servers` 改配置占位（与 C-04 处理方式一致） |

### 5.2 回滚

- **全部变更均在文档与脚本层**（`specs/**`、`docs/contracts/**`、`scripts/**`、`evidence/**`），
  **不动 `src/**`、`tests/**`、GITS 仓** ⇒ 回滚 = `git revert` 对应提交；
- 无数据迁移、无不可逆点、无运行时改动 ⇒ **回滚成本低**；
- 唯一需"一次性做对"的是 R4 的 fingerprint 策略：**不覆盖既有 manifest**，用追加方式出新期制品。

### 5.3 分期方案（因非纯 additive）

| 期 | 范围 | 交付 | 前置 | 可独立回滚 |
|---|---|---|---|---|
| **P0** | 权威声明冻结（纯文档，零合同语义变更） | v2 头 + `docs/contracts/README.md:30-40` + `KERT_DOCUMENT_CONFLICT_REGISTER.md:28` 同步为"v2 非权威" | 无 | ✅ |
| **P1** | v1 patch（合同修订，须 Contract Owner 批准） | 修 5 处实况失实（F1/F2/F3/F4/F5）+ 并入 `/v1/graph/query` + 补 `service`/`retryable` + 状态码并集；版本 `1.5.0 → 1.6.0` | P0 | ✅ |
| **P2** | 工具链与制品（不动合同语义） | `validate_contract_bundle.py` 指向 v1（含方言处置，见 §3.1-4）、`contract_bundle_hash.py:20-33` 白名单、`release.py:217-224` 增加 `specs/` | P1 | ✅ |
| **P3** | v2 处置（归档或拆分为独立候选文档） | v2 移出校验白名单并加 `x-implemented:false`；`/api/v2/jobs/{jobId}/cancel` 独立登记为未来项 | P2 | ✅ |
| **P4**（未来，需 GITS 配合） | 真 v2 演进 | 补全 → Owner 批准 → 新合同 | 另行立项 | — |

**分期不得合并的理由**：P1 属合同修订（Contract Owner 权限），P2/P3 属工具链（可实现），
P0 只是消除误引。任意两期合并都会使"合同语义变更"与"工具链切换"混在同一提交，
一旦指纹/校验失败将无法定位是语义问题还是工具问题。

---

## 6. 待 Owner / Contract Owner 裁决点（本任务不自行裁决）

| # | 裁决点 | 选项 | 影响 |
|---|---|---|---|
| O1 | 单一权威归属 | A：v1 / B：v2 | 决定 §3 整章 |
| O2 | v1 的 5 处实况失实是否本轮修正 | 修 / 另行立项 | 不修则 v1 继续"测试绿但合同错"（F2 最典型） |
| O3 | `/v1/jobs/{jobId}` 字段口径（`jobId` vs `data.job_id`） | 改合同（推荐）/ 改实现 | 跨仓字段，须 GITS 知情（§4.3） |
| O4 | 9 条"已实现未登记"的 `/v1/*` 是否补登记 | 全补 / 只补 `/v1/graph/query` / 不补 | 决定 v1 覆盖率与 F8 是否关闭 |
| O5 | v1 是否升 3.1.0（消 8 处 `nullable`） | 升 / 校验器双方言分支 | R5；也是"能否用同一校验器"的前提 |
| O6 | v2 的处置等级 | 归档（推荐）/ 降级保留 / 拆分独立候选 | 决定 P3 内容 |
| O7 | `/api/v2/*` 命名空间是否保留为候选 | 保留 / 移除 | 影响 D-06 决策的一致性表述 |
| O8 | `KERT_*` 8 错误码与 `retryable` 是否并入权威 | 并入 / 只保留 v1 现有码 | 影响 `test_sp15_contract_conformance.py:459-462` 的合同依据 |
| O9 | GITS 侧默认端口 8107 与合同 `servers` 8106 的口径 | 合同改占位 / GITS 改默认 | C-04 同源，需跨仓 |

---

## 7. 非声明（原样保留任务包 §4）

```text
不是 Contract Owner 批准、不构成合同修订、不改变 `PRODUCTION_RELEASE_GATE=BLOCKED`、
不代表 GITS UAT 通过；归并**未执行**。
```

### 附：本任务实际未做之事（边界自证）

- 未修改 `specs/**`、`docs/contracts/**`、`src/**`、`tests/**`、`scripts/**`、GITS 仓任何文件；
  本任务**只新增**本文件 `evidence/m7-3/CANDIDATE-CONTRACT-MERGE-V1-V2.md`；
- 未 push、未提交；未运行任何修改型命令；
- 未声称"归并已完成/已获批准"；未对 `PRODUCTION_RELEASE_GATE`（现 `BLOCKED`，
  `KERT_STATUS_BASELINE_CANDIDATE.yaml:17`）作任何变化暗示；
- 所有差异结论均附 `文件:行号`，无凭记忆断言。
