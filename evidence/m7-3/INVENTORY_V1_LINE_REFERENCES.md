# 只读清单：全仓 v1:NNN 引用 x 勘误(-5 行) 影响核对

性质：只读分析产物；本文件未修改任何被引用文本。
行号基准：specs @ b586345^ = 1826 行(旧)  /  @ b586345 = 1821 行(新)。
日期：2026-09-16  /  ID：M7-CLOSURE-C20-V1-LINE-REFS

## 0. 口径与计数

- 模式：v1:([0-9]+)(?:-([0-9]+))?   口径 = 出现次数（含行内多次）
- 范围：仓根递归；排除 .git / __pycache__ / .venv / node_modules；跳过含 NUL 的二进制
- 实测总数 = 70 处（TL 消息记为 67 处 ⇒ 对账见 1.1）
- 分布：./evidence/m7-3/CANDIDATE-CONTRACT-MERGE-V1-V2.md = 67；./evidence/m7-3/DECISION_SHEET_M7_CLOSURE.md = 3
- 判定汇总：待人工 = 3；未漂移 = 18；漂移 = 48；跨界 = 1

判定规则（纯机械，不依赖语义）：未漂移 = 区间内每行 new[x]==old[x]；漂移 = 区间内每行 new[x-5]==old[x]；跨界 = 区间跨越勘误点 236；越界 = 引用号超出 1821。

## 1. 结论（先读这一节）

### 1.1 计数对账（70 vs TL 的 67）

- 全仓 **70 处**（出现次数口径）= `CANDIDATE-CONTRACT-MERGE-V1-V2.md` **67 处** + `DECISION_SHEET_M7_CLOSURE.md` **3 处**。
- ⇒ **TL 的"全仓 67 处"实际等于 `CANDIDATE-CONTRACT-MERGE-V1-V2.md` 单个文件的出现次数**；另有 TL 本轮新写的 **D-15 行自身**再引入 3 处（`v1:1009` / `v1:1172` / `v1:17`）⇒ 合计 70。
- ⚠ **D-15 行本身已中招**：该行引用的 `v1:1009`、`v1:1172` **两处已漂移**（候选应为 `1004` / `1167`）。

### 1.2 机械判定汇总

| 判定 | 条数 | 说明 |
|---|---|---|
| **漂移**（整体下移 5 行） | 48 | `new[N-5] == old[N]` 逐条核对为 **True** |
| **未漂移** | 18 | 区间内容新旧逐行相同（**不等于引用正确**，见 1.3-3） |
| **待人工**（区间**跨本批改写区**） | 3 | `:113 v1:331-398`、`:114 v1:255-297`、`:159 v1:753-823` |
| **跨界**（区间**跨越**勘误点 236） | 1 | `:124 v1:229-253` |

### 1.3 ⚠ 禁止盲做 N−5 批量替换（三类反例均已实证）

1. **跨本批改写区 3 处 + 跨界 1 处**：−5 对它们**不成立** —— 该区间同时被本批 F1/F3/F7 形状修正改写过，行数不再守恒（`new[N-5] != old[N]`）。
2. **"勘误前即不准"（机械已确证 4 行）**：这些引用**在新旧两版都不在其引用号上**；做 −5 只是把错挪到另一个错位：
   - `CANDIDATE-CONTRACT-MERGE-V1-V2.md:63` 称 `info.version` 在 `v1:17` ⇒ 实测 `info.version` 在 **`:48`**（新旧同）；`:17` 是 `info.description` 正文 ⇒ **引用错，非漂移**。
   - `:64` / `:209` / `:335` 称 `servers[0].url`（端口）在 `v1:24` ⇒ 实测 `servers:` 在 **`:54`**（新旧同）；`:24` 是 description 正文 ⇒ **引用错，非漂移**。
   - `DECISION_SHEET_M7_CLOSURE.md:94`（D-15 行自身）同样引用 `v1:17`。
3. **"未漂移" 18 行中仍混有"本就错位"的引用**（机械只能证明"该行内容没变"，不能证明"引用号对"）。当前 `specs` 结构实测：`paths:` @ `:72`、`/v1/health` @ `:73-102`、`/api/skill/health` @ `:103-129`、`/v1/skills` @ `:130-164` ⇒ 下列引用号**与当前结构不符**（疑为 `info.description` 扩写前写就），**须人工核**：
   `:65 v1:42`、`:111 v1:72-93`、`:112 v1:130-227`、`:122 v1:42-70`、`:123 v1:95-128`、`:139 v1:100`、`:196 v1:130-227`、`:57`… （**未逐条裁定**；我只给出结构性反证，不做超出证据的结论）。

### 1.4 建议（供 TL 定夺，不含任何执行）

- 本轮若做批量修，**只能对 48 条"漂移"应用 −5**；其余 **22 条**（18 未漂移 + 3 待人工 + 1 跨界）**必须逐条人工定位**，其中至少 4 条属"引用本身就错"。
- 更稳的做法：与 **1.6.0 轮**一并处理 —— 1.6.0 会再插入行，届时**一次重算全部 70 条的真值**，避免"修完又漂"。

## 2. 逐条清单

| # | 文件:行 | 引用号 | 旧内容(b586345^) | 新内容(HEAD) | 判定 | N-5候选 | new[N-5]==old[N] | 引用行节选 |
|---|---|---|---|---|---|---|---|---|
| 1 | ./evidence/m7-3/CANDIDATE-CONTRACT-MERGE-V1-V2.md:29 | v1:709-719 | content: | description: 地图未注册（协议级资源不存在） | 漂移 | 704-714 | True | \| D3 \| `docs/contracts/schemas/*.json` 与 v1 内联 schema 的关系 \| 保留为**细节 canonical 层* |
| 2 | ./evidence/m7-3/CANDIDATE-CONTRACT-MERGE-V1-V2.md:62 | v1:1 | openapi: 3.0.3 | openapi: 3.0.3 | 未漂移 | - | - | \| OpenAPI 方言 \| `3.0.3`（v1:1） \| `3.1.0`（v2:1） \| |
| 3 | ./evidence/m7-3/CANDIDATE-CONTRACT-MERGE-V1-V2.md:63 | v1:17 | ⑤ `/v1/jobs/{jobId}` 的 `404`：`ErrorResponse` → 新增 `Infra | ⑤ `/v1/jobs/{jobId}` 的 `404`：`ErrorResponse` → 新增 `Infra | 未漂移 | - | - | \| `info.version` \| `1.5.0`（v1:17）→ **已于 2026-09-16 更正为 `1.5.1`** \| `2.0.0-candid |
| 4 | ./evidence/m7-3/CANDIDATE-CONTRACT-MERGE-V1-V2.md:64 | v1:24 | 另记一条**观察（不在本合同范围、本批不修）**：`_handle()` 对**非** `KERTExcepti | 另记一条**观察（不在本合同范围、本批不修）**：`_handle()` 对**非** `KERTExcepti | 未漂移 | - | - | \| `servers[0].url` \| `http://127.0.0.1:8106`（v1:24） \| `http://127.0.0.1:8106`（v2 |
| 5 | ./evidence/m7-3/CANDIDATE-CONTRACT-MERGE-V1-V2.md:65 | v1:42 |  |  | 未漂移 | - | - | \| 路径数 \| **14**（v1:42,72,95,130,229,255,299,331,400,418,438,452,472,498） \| **10** |
| 6 | ./evidence/m7-3/CANDIDATE-CONTRACT-MERGE-V1-V2.md:67 | v1:529-534 | finished_at: "2026-09-01T18:02:29Z" | version: "1.0" | 漂移 | 524-529 | True | \| 顶层 `security` \| **无**（仅定义 schemes，v1:529-534） \| **有**全局要求（v2:13-14） \| |
| 7 | ./evidence/m7-3/CANDIDATE-CONTRACT-MERGE-V1-V2.md:111 | v1:72-93 | paths: | paths: | 未漂移 | - | - | \| 1 \| `/api/skill/health` \| v1:72-93，`operationId: getSkillHealth` \| v2:28-40，`o |
| 8 | ./evidence/m7-3/CANDIDATE-CONTRACT-MERGE-V1-V2.md:112 | v1:130-227 | /v1/skills: | /v1/skills: | 未漂移 | - | - | \| 2 \| `/api/skill/execute` \| v1:130-227 \| v2:41-90 \| 路径同、状态码集不同（§2.3） \| |
| 9 | ./evidence/m7-3/CANDIDATE-CONTRACT-MERGE-V1-V2.md:113 | v1:331-398 | "404": |  | 待人工 | - | - | \| 3 \| `/v1/jobs/{jobId}` \| v1:331-398 \| v2:91-114 \| 路径同、响应 schema 不同（§2.2-④） \| |
| 10 | ./evidence/m7-3/CANDIDATE-CONTRACT-MERGE-V1-V2.md:114 | v1:255-297 | msg: "Field required" | `errors[0].code=UNKNOWN_SKILL`），而**不是** `ErrorResponse`。 | 待人工 | - | - | \| 4 \| `/api/skill/gates/{customerId}` \| v1:255-297，`operationId: getGates` \| v2: |
| 11 | ./evidence/m7-3/CANDIDATE-CONTRACT-MERGE-V1-V2.md:115 | v1:299-329 | schema: | errors: | 漂移 | 294-324 | True | \| 5 \| `/api/skill/gates/audit` \| v1:299-329，`operationId: auditGate` \| v2:157-17 |
| 12 | ./evidence/m7-3/CANDIDATE-CONTRACT-MERGE-V1-V2.md:116 | v1:400-450 | application/json: | gate: G1 | 漂移 | 395-445 | True | \| 6 \| `/livez` `/readyz` `/metrics` \| v1:400-450（`livez`/`readyz`/`getMetrics`）  |
| 13 | ./evidence/m7-3/CANDIDATE-CONTRACT-MERGE-V1-V2.md:122 | v1:42-70 |  |  | 未漂移 | - | - | \| ① \| `GET /v1/health` \| v1:42-70 \| `server.py:448-469` ✅ \| GITS 未调用；v2 未声明 \| |
| 14 | ./evidence/m7-3/CANDIDATE-CONTRACT-MERGE-V1-V2.md:123 | v1:95-128 | version: "1.0.0" | version: "1.0.0" | 未漂移 | - | - | \| ② \| `GET /v1/skills` \| v1:95-128 \| **未实现** \| `docs/integration/KERT_GITS_CONTR |
| 15 | ./evidence/m7-3/CANDIDATE-CONTRACT-MERGE-V1-V2.md:124 | v1:229-253 | $ref: "#/components/schemas/AsyncAcceptedResponse" | $ref: "#/components/schemas/AsyncAcceptedResponse" | 跨界 | - | - | \| ③ \| `GET /api/skill/report/{requestId}` \| v1:229-253 \| `server.py:645-658` ✅ \| |
| 16 | ./evidence/m7-3/CANDIDATE-CONTRACT-MERGE-V1-V2.md:125 | v1:452-470 | "200": | $ref: "#/components/schemas/JobStatusResponse" | 漂移 | 447-465 | True | \| ④ \| `GET /v1/knowledge-maps` \| v1:452-470 \| `server.py:693-713` ✅ \| v1.5 追认增量（ |
| 17 | ./evidence/m7-3/CANDIDATE-CONTRACT-MERGE-V1-V2.md:126 | v1:472-496 | output_refs: [] | error_code: null | 漂移 | 467-491 | True | \| ⑤ \| `GET /v1/knowledge-maps/{mapId}` \| v1:472-496 \| `server.py:715-727` ✅ \| 同上 |
| 18 | ./evidence/m7-3/CANDIDATE-CONTRACT-MERGE-V1-V2.md:127 | v1:498-526 | input_refs: [] | progress: 40 | 漂移 | 493-521 | True | \| ⑥ \| `POST /v1/routing/plan` \| v1:498-526 \| `server.py:729-747` ✅ \| 同上 \| |
| 19 | ./evidence/m7-3/CANDIDATE-CONTRACT-MERGE-V1-V2.md:139 | v1:100 | name: 产品适配与综合方案 | name: 产品适配与综合方案 | 未漂移 | - | - | - `listSkills`：v1 用于 `GET /v1/skills`（v1:100），v2 用于 `GET /api/skill/health`（v2:3 |
| 20 | ./evidence/m7-3/CANDIDATE-CONTRACT-MERGE-V1-V2.md:143 | v1:47 | 本文档为**运行中权威**（服务实际实现）；v2 候选未批准，归并列 W8/Phase 0 收口（冲突 C-20 | 本文档为**运行中权威**（服务实际实现）；v2 候选未批准，归并列 W8/Phase 0 收口（冲突 C-20 | 未漂移 | - | - | `livez`/`liveness`、`readyz`/`readiness`、`getMetrics`/`metrics`（v1:47,77,100,139, |
| 21 | ./evidence/m7-3/CANDIDATE-CONTRACT-MERGE-V1-V2.md:150 | v1:551-561 | data: | requested_by: api | 漂移 | 546-556 | True | \| ① \| **`SkillHealthResponse`** \| v1:551-561，`required: [status, skills]`，**无 `s |
| 22 | ./evidence/m7-3/CANDIDATE-CONTRACT-MERGE-V1-V2.md:151 | v1:1042-1051 | type: string | excludes: | 漂移 | 1037-1046 | True | \| ② \| **`GateListResponse.gates[]`** \| v1:1042-1051 → `GateChecklistItem`（v1:974 |
| 23 | ./evidence/m7-3/CANDIDATE-CONTRACT-MERGE-V1-V2.md:151 | v1:974-994 | SkillExecuteData: | type: string | 漂移 | 969-989 | True | \| ② \| **`GateListResponse.gates[]`** \| v1:1042-1051 → `GateChecklistItem`（v1:974 |
| 24 | ./evidence/m7-3/CANDIDATE-CONTRACT-MERGE-V1-V2.md:151 | v1:277-295 | message: "未知 skillId: UNKNOWN" | - phase: resolve | 漂移 | 272-290 | True | \| ② \| **`GateListResponse.gates[]`** \| v1:1042-1051 → `GateChecklistItem`（v1:974 |
| 25 | ./evidence/m7-3/CANDIDATE-CONTRACT-MERGE-V1-V2.md:152 | v1:1074-1085 | description: SP-21 交互记忆抽取结果 | skillId: | 漂移 | 1069-1080 | True | \| ③ \| **`GateAuditResponse`** \| v1:1074-1085：`{recorded, timestamp, auditPath}`  |
| 26 | ./evidence/m7-3/CANDIDATE-CONTRACT-MERGE-V1-V2.md:153 | v1:1009-1040 | example: SP-20 | type: string | 漂移 | 1004-1035 | True | \| ④ \| **Job 状态响应** \| v1:1009-1040 `JobStatusResponse`：`required [jobId, status]` |
| 27 | ./evidence/m7-3/CANDIDATE-CONTRACT-MERGE-V1-V2.md:153 | v1:1027-1032 | properties: | additionalProperties: | 漂移 | 1022-1027 | True | \| ④ \| **Job 状态响应** \| v1:1009-1040 `JobStatusResponse`：`required [jobId, status]` |
| 28 | ./evidence/m7-3/CANDIDATE-CONTRACT-MERGE-V1-V2.md:154 | v1:1087-1099 | candidateMemories: | type: array | 漂移 | 1082-1094 | True | \| ⑤ \| **错误信封** \| v1:1087-1099 `ErrorResponse`：`required [requestId, status]` + ` |
| 29 | ./evidence/m7-3/CANDIDATE-CONTRACT-MERGE-V1-V2.md:154 | v1:1095 | memorySupersessions: | type: array | 漂移 | 1090-1090 | True | \| ⑤ \| **错误信封** \| v1:1087-1099 `ErrorResponse`：`required [requestId, status]` + ` |
| 30 | ./evidence/m7-3/CANDIDATE-CONTRACT-MERGE-V1-V2.md:155 | v1:1101-1127 | items: | properties: | 漂移 | 1096-1122 | True | \| ⑥ \| **错误明细字段名** \| v1:1101-1127 `ErrorDetail`：`code` / `message` / **`detail`** |
| 31 | ./evidence/m7-3/CANDIDATE-CONTRACT-MERGE-V1-V2.md:155 | v1:1125-1127 | Unknown: | example: UNK-0001 | 漂移 | 1120-1122 | True | \| ⑥ \| **错误明细字段名** \| v1:1101-1127 `ErrorDetail`：`code` / `message` / **`detail`** |
| 32 | ./evidence/m7-3/CANDIDATE-CONTRACT-MERGE-V1-V2.md:156 | v1:694-725 | /v1/knowledge-maps/{mapId}: | parameters: | 漂移 | 689-720 | True | \| ⑦ \| **`SkillExecuteResponse` 必填集** \| v1:694-725：`required [requestId, status,  |
| 33 | ./evidence/m7-3/CANDIDATE-CONTRACT-MERGE-V1-V2.md:157 | v1:622-644 | properties: | description: 服务未就绪 | 漂移 | 617-639 | True | \| ⑧ \| **`SkillExecuteRequest.required`** \| v1:622-644：`required [skillId, reques |
| 34 | ./evidence/m7-3/CANDIDATE-CONTRACT-MERGE-V1-V2.md:158 | v1:665-692 | application/json: | error: | 漂移 | 660-687 | True | \| ⑨ \| **`ContextPackage`** \| v1:665-692：`required [schemaVersion, customerId]`，含 |
| 35 | ./evidence/m7-3/CANDIDATE-CONTRACT-MERGE-V1-V2.md:158 | v1:679-688 |  | oneOf: | 漂移 | 674-683 | True | \| ⑨ \| **`ContextPackage`** \| v1:665-692：`required [schemaVersion, customerId]`，含 |
| 36 | ./evidence/m7-3/CANDIDATE-CONTRACT-MERGE-V1-V2.md:158 | v1:689-692 | error: | /v1/knowledge-maps/{mapId}: | 漂移 | 684-687 | True | \| ⑨ \| **`ContextPackage`** \| v1:665-692：`required [schemaVersion, customerId]`，含 |
| 37 | ./evidence/m7-3/CANDIDATE-CONTRACT-MERGE-V1-V2.md:159 | v1:753-823 | type: apiKey | HealthResponse: | 待人工 | - | - | \| ⑩ \| **`ServiceResult`（SP-20）** \| v1:753-823：**无** `ruleViolations` \| `schemas/ |
| 38 | ./evidence/m7-3/CANDIDATE-CONTRACT-MERGE-V1-V2.md:159 | v1:747-751 | "500": | ApiKeyAuth: | 漂移 | 742-746 | True | \| ⑩ \| **`ServiceResult`（SP-20）** \| v1:753-823：**无** `ruleViolations` \| `schemas/ |
| 39 | ./evidence/m7-3/CANDIDATE-CONTRACT-MERGE-V1-V2.md:160 | v1:709-719 | content: | description: 地图未注册（协议级资源不存在） | 漂移 | 704-714 | True | \| ⑪ \| **`assemblyTrace` 条目** \| v1:709-719：`type: array`（v1.5 由 `object` 修正而来，v1: |
| 40 | ./evidence/m7-3/CANDIDATE-CONTRACT-MERGE-V1-V2.md:160 | v1:715-716 | "422": | /v1/routing/plan: | 漂移 | 710-711 | True | \| ⑪ \| **`assemblyTrace` 条目** \| v1:709-719：`type: array`（v1.5 由 `object` 修正而来，v1: |
| 41 | ./evidence/m7-3/CANDIDATE-CONTRACT-MERGE-V1-V2.md:160 | v1:711-714 | schema: | description: 地图定义非法 | 漂移 | 706-709 | True | \| ⑪ \| **`assemblyTrace` 条目** \| v1:709-719：`type: array`（v1.5 由 `object` 修正而来，v1: |
| 42 | ./evidence/m7-3/CANDIDATE-CONTRACT-MERGE-V1-V2.md:161 | v1:1172 |  | type: string | 漂移 | 1167-1167 | True | \| ⑫ \| **`nullable` 语法** \| v1 使用 `nullable: true` **8 处**：v1:1172,1183,1186,1189, |
| 43 | ./evidence/m7-3/CANDIDATE-CONTRACT-MERGE-V1-V2.md:161 | v1:662 |  | $ref: "#/components/schemas/InfrastructureErrorResponse" | 漂移 | 657-657 | True | \| ⑫ \| **`nullable` 语法** \| v1 使用 `nullable: true` **8 处**：v1:1172,1183,1186,1189, |
| 44 | ./evidence/m7-3/CANDIDATE-CONTRACT-MERGE-V1-V2.md:167 | v1:175 | requestBody: | requestBody: | 未漂移 | - | - | \| A \| `/api/skill/execute` 状态码集 \| **200 / 202 / 400 / 404 / 500**（v1:175,189,198 |
| 45 | ./evidence/m7-3/CANDIDATE-CONTRACT-MERGE-V1-V2.md:168 | v1:1087-1099 | candidateMemories: | type: array | 漂移 | 1082-1094 | True | \| B \| 错误体结构（同状态码下） \| `{requestId, status, errors[{code,message,detail}]}`（v1:108 |
| 46 | ./evidence/m7-3/CANDIDATE-CONTRACT-MERGE-V1-V2.md:169 | v1:1106-1122 | properties: | type: string | 漂移 | 1101-1117 | True | \| C \| 错误码词表 \| v1 `ErrorDetail.code` 文档化 **14 个**：`INVALID_PARAMETER`/`SKILL_NOT_ |
| 47 | ./evidence/m7-3/CANDIDATE-CONTRACT-MERGE-V1-V2.md:170 | v1:405 | gate: G1 | "200": | 漂移 | 400-400 | True | \| D \| 探针 operationId \| `livez`/`readyz`/`getMetrics`（v1:405,423,443） \| `liveness |
| 48 | ./evidence/m7-3/CANDIDATE-CONTRACT-MERGE-V1-V2.md:176 | v1:529-534 | finished_at: "2026-09-01T18:02:29Z" | version: "1.0" | 漂移 | 524-529 | True | \| A \| 顶层 `security` \| **无**（v1 只在 v1:529-534 定义 `ApiKeyAuth`，未在任何 operation 或全局启 |
| 49 | ./evidence/m7-3/CANDIDATE-CONTRACT-MERGE-V1-V2.md:177 | v1:530-534 | progress: 100 | skill_result: | 漂移 | 525-529 | True | \| B \| scheme 语义 \| `X-API-Key`，描述"**演示环境可省略**"（v1:530-534） \| `X-API-Key`，描述"KERT  |
| 50 | ./evidence/m7-3/CANDIDATE-CONTRACT-MERGE-V1-V2.md:189 | v1:974-994 | SkillExecuteData: | type: string | 漂移 | 969-989 | True | \| F1 \| `/api/skill/gates/{customerId}` 的 v1 形状（`gate`/`state`/`checklist`）**与实现不 |
| 51 | ./evidence/m7-3/CANDIDATE-CONTRACT-MERGE-V1-V2.md:190 | v1:1217 | type: array | type: object | 漂移 | 1212-1212 | True | \| F2 \| `/v1/routing/plan` 的 v1 `RoutingPlanResponse` 要求**顶层** `allowed`（`require |
| 52 | ./evidence/m7-3/CANDIDATE-CONTRACT-MERGE-V1-V2.md:190 | v1:1215-1233 | $ref: "#/components/schemas/GateChecklistItem" |  | 漂移 | 1210-1228 | True | \| F2 \| `/v1/routing/plan` 的 v1 `RoutingPlanResponse` 要求**顶层** `allowed`（`require |
| 53 | ./evidence/m7-3/CANDIDATE-CONTRACT-MERGE-V1-V2.md:192 | v1:210-221 | "200": | "200": | 未漂移 | - | - | \| F4 \| `/api/skill/execute` 的 404 响应体**不是** `ErrorResponse`，而是**与 200 同构**的 skil |
| 54 | ./evidence/m7-3/CANDIDATE-CONTRACT-MERGE-V1-V2.md:193 | v1:1074-1085 | description: SP-21 交互记忆抽取结果 | skillId: | 漂移 | 1069-1080 | True | \| F5 \| `/api/skill/gates/audit` 响应与 v1/v2 均不符 \| `skills.py:907-920`（`{recorded,  |
| 55 | ./evidence/m7-3/CANDIDATE-CONTRACT-MERGE-V1-V2.md:194 | v1:1101-1127 | items: | properties: | 漂移 | 1096-1122 | True | \| F6 \| 错误 `retryable` 字段：实现发 `retryable`（v2/schema 有，v1 无） \| `server.py:311-313` |
| 56 | ./evidence/m7-3/CANDIDATE-CONTRACT-MERGE-V1-V2.md:195 | v1:551-561 | data: | requested_by: api | 漂移 | 546-556 | True | \| F7 \| `/api/skill/health` 实现返回 `service`（v2 有，v1 无） \| `server.py:612-617` vs v1 |
| 57 | ./evidence/m7-3/CANDIDATE-CONTRACT-MERGE-V1-V2.md:196 | v1:95-128 | version: "1.0.0" | version: "1.0.0" | 未漂移 | - | - | \| F8 \| **v1 声明的 `/v1/skills` 未实现**；**实现有 9 条 `/v1/*` 未登记进 v1** \| v1:95-128 vs `s |
| 58 | ./evidence/m7-3/CANDIDATE-CONTRACT-MERGE-V1-V2.md:209 | v1:24 | 另记一条**观察（不在本合同范围、本批不修）**：`_handle()` 对**非** `KERTExcepti | 另记一条**观察（不在本合同范围、本批不修）**：`_handle()` 对**非** `KERTExcepti | 未漂移 | - | - | \| 端口 \| GITS 默认 `DSH_BASE_URL=http://127.0.0.1:8107`，与两份合同 `servers` 的 `8106` **不 |
| 59 | ./evidence/m7-3/CANDIDATE-CONTRACT-MERGE-V1-V2.md:224 | v1:16 | ④ `/api/skill/execute` 的 `404`：`ErrorResponse` → 新增 `Ski | ④ `/api/skill/execute` 的 `404`：`ErrorResponse` → 新增 `Ski | 未漂移 | - | - | 保留"运行中权威"表述（v1:16），并把"v2 候选未批准"改为"v2 已归档为非权威设计输入"。 |
| 60 | ./evidence/m7-3/CANDIDATE-CONTRACT-MERGE-V1-V2.md:240 | v1:709-719 | content: | description: 地图未注册（协议级资源不存在） | 漂移 | 704-714 | True | v1 以 **prose 引用 + 可选 `x-canonical-ref`** 指向（`assemblyTrace` 已是既有先例，v1:709-719）， |
| 61 | ./evidence/m7-3/CANDIDATE-CONTRACT-MERGE-V1-V2.md:247 | v1:1 | openapi: 3.0.3 | openapi: 3.0.3 | 未漂移 | - | - | - 但 `:75-76` 硬要求 `openapi == "3.1.0"`，而 v1 是 `3.0.3`（v1:1）且用了 **8 处 `nullable`** |
| 62 | ./evidence/m7-3/CANDIDATE-CONTRACT-MERGE-V1-V2.md:248 | v1:1172 |  | type: string | 漂移 | 1167-1167 | True | （v1:1172,1183,1186,1189,1192,1244,1259,1280）——`nullable` 在 3.1 中**不存在**。 |
| 63 | ./evidence/m7-3/CANDIDATE-CONTRACT-MERGE-V1-V2.md:314 | v1:694-725 | /v1/knowledge-maps/{mapId}: | parameters: | 漂移 | 689-720 | True | \| `POST /api/skill/execute` \| 顶层 `requestId`/`status`/`data`/`errors`（`DshHttpSk |
| 64 | ./evidence/m7-3/CANDIDATE-CONTRACT-MERGE-V1-V2.md:315 | v1:996-1007 | description: 规则校验违规（v1.4 新增） | type: object | 漂移 | 991-1002 | True | \| `POST /api/skill/execute`（async） \| 202 `{jobId,status}` \| 保留（v1:996-1007；`serv |
| 65 | ./evidence/m7-3/CANDIDATE-CONTRACT-MERGE-V1-V2.md:335 | v1:24 | 另记一条**观察（不在本合同范围、本批不修）**：`_handle()` 对**非** `KERTExcepti | 另记一条**观察（不在本合同范围、本批不修）**：`_handle()` 对**非** `KERTExcepti | 未漂移 | - | - | 改为配置占位（当前 v1:24 / v2:11 均写死 8106，而 GITS 默认 8107，冲突 C-04 同源）。 |
| 66 | ./evidence/m7-3/CANDIDATE-CONTRACT-MERGE-V1-V2.md:344 | v1:1009-1032 | example: SP-20 | type: string | 漂移 | 1004-1027 | True | \| v1 合同 \| 顶层 `jobId`（`required`），`data.skill_result` \| v1:1009-1032 \| |
| 67 | ./evidence/m7-3/CANDIDATE-CONTRACT-MERGE-V1-V2.md:367 | v1:1172 |  | type: string | 漂移 | 1167-1167 | True | \| R5 \| **OpenAPI 方言迁移引入语义漂移** \| v1 升 3.1.0 后 8 处 `nullable` 改写（v1:1172…1280） \| 中 |
| 68 | ./evidence/m7-3/DECISION_SHEET_M7_CLOSURE.md:94 | v1:1009 | example: SP-20 | type: string | 漂移 | 1004-1004 | True | \| **D-15** \| **`v1:NNN` 引用漂移（TL 本轮机械核对发现，全仓 67 处）**：`b586345` 的勘误在 `specs:236` 删 |
| 69 | ./evidence/m7-3/DECISION_SHEET_M7_CLOSURE.md:94 | v1:1172 |  | type: string | 漂移 | 1167-1167 | True | \| **D-15** \| **`v1:NNN` 引用漂移（TL 本轮机械核对发现，全仓 67 处）**：`b586345` 的勘误在 `specs:236` 删 |
| 70 | ./evidence/m7-3/DECISION_SHEET_M7_CLOSURE.md:94 | v1:17 | ⑤ `/v1/jobs/{jobId}` 的 `404`：`ErrorResponse` → 新增 `Infra | ⑤ `/v1/jobs/{jobId}` 的 `404`：`ErrorResponse` → 新增 `Infra | 未漂移 | - | - | \| **D-15** \| **`v1:NNN` 引用漂移（TL 本轮机械核对发现，全仓 67 处）**：`b586345` 的勘误在 `specs:236` 删 |

