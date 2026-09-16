# 只读差异清单：`/v1/jobs/{jobId}` 合同声明 × 实现实测（D-24）

```text
ID       : M7-CLOSURE-C20-D24-JOBS-DIFF
性质     : **只读差异清单** —— 本文件**不回改合同、不改码**（`specs/**`、`src/**` 一字未动）
裁决依据 : D-24（`evidence/m7-3/DECISION_SHEET_M7_CLOSURE.md`）：TL 派工"只读核对合同声明与实现口径，
           产出差异清单；若发现'实现有、合同未声明'⇒ 按 A-6 的机械核对口径登记"
作者     : c20（契约/实现面）
DATE     : 2026-09-16
行号基准 : 合同 `specs/kert-openapi-v1.yaml` 路径块 `:664-724`、schema `:1477-1597`；
           实现 `src/kert/api/server.py`：`_response()` `:208-217`、`job()` `:530-536`、
           `skill_execute()` 异步分支 `:656-661`；`src/kert/application/jobs.py`：`fm` `:236-253`、
           `read_job_status()` `:312-333`；值域权威 `src/kert/domain/states.py:11-14`（`JOB_STATES`，9 值）／`:15`（`JOB_TERMINAL`）（HEAD 时点；TL 入库时对齐：原文写作 `:11-15`，把两个符号并入同一跨度，与正文第 5 行的 `:11-14` 不自洽）
```

## 1. 口径与实测证据（活栈，专用端口 **8151**）

命令（原文，`.venv/bin/python` = **Python 3.12.8**；服务以 `KERT_PROFILE=dev` +
`KERT_SKILL_PACKAGES=examples/bank-front-skills` + `provision --init` 后的临时工作区启动；结束复核
`ss -ltn` 8151 已释放、只 kill 本进程）：

```text
POST /api/skill/execute  {"skillId":"SP-20","requestId":"d24-1","request":{"context":{...}},"async":true}
GET  /v1/jobs/{jobId}    （提交后立即 / 轮询至终态）
GET  /v1/jobs/NONEXISTENT-JOB
GET  /v1/jobs/JOB-SKILL-20260916-D24   （由真实 STATUS.md 复制并**仅将 status 改为 BLOCKED**）
```

| 观测 | 实测（原文摘录） |
|---|---|
| **A** 202 提交 | `202 {"jobId": "JOB-SKILL-20260916-001", "status": "PENDING"}` |
| **B** 首次 GET（运行中） | `200 {"request_id":"REQ-JOB-JOB-SKILL-20260916-001","status":"OK","data":{…16 键…, "status":"RUNNING","progress":0,"finished_at":null,…},"errors":[],"meta":{…}}` |
| **C** 终态 GET | `data.status = "COMPLETED"`、`progress = 100`、`finished_at` 有值、**`data.skill_result` 出现**（形状 = 完整 execute 响应：`{"requestId":…,"status":"ok","data":{…}}`） |
| **D** 不存在 | `404 {"detail":{"error":{"code":"ASSET_NOT_FOUND","message":"任务不存在: NONEXISTENT-JOB","retryable":false}}}` |
| **E** **`BLOCKED`**（合同 enum 外的值） | **`200`** + `data.status = "BLOCKED"`（信封其余键不变） |

> E 的构造方式：复制真实 `STATUS.md`，**只**把 front matter 的 `status:` 改为 `BLOCKED`
> （该值通过实现侧文件契约校验：`BLOCKED` ∈ `states.JOB_STATES` 且 ∈ `JOB_TERMINAL`，
> 终态已带 `finished_at`）⇒ 端点**如实投影**为 `200 + data.status="BLOCKED"`。

## 2. 逐条差异清单

| # | 项 | 合同怎么写（`specs/kert-openapi-v1.yaml`） | 实现怎么给（实测/回源） | 是否一致 | 建议 |
|---|---|---|---|---|---|
| 1 | 202 受理体 | `/api/skill/execute` 202 → `AsyncAcceptedResponse`（`required:[jobId,status]`、`status.enum:[PENDING]`，`:1477-1488`） | `{jobId, status:"PENDING"}`（A） | ✅ | — |
| 2 | 200 信封 | `JobStatusResponse`：`required:[request_id,status,data]`、`additionalProperties:false`、props `{request_id,status,data,errors,meta}`（`:1490-1521`） | 实测 5 键齐全、**无额外键**（B/C） | ✅ | — |
| 3 | 信封 `status` | `string`，描述"实现恒为 `OK`，与 `data.status` 不同义"（`:1509-1511`） | 实测 `"OK"`（B/C/E） | ✅ | — |
| 4 | `data` 键集 | `JobStatusData` 16 属性 + 条件 `skill_result`；`additionalProperties:false`（`:1523-1597`） | 实测 16 键**逐字段对应**（B/C/E）；键名 snake_case ✓ | ✅ | — |
| 5 | **`data.status` 值域（enum）** | `enum: [PENDING, RUNNING, COMPLETED, FAILED]` —— **4 值**（`:1546-1549`） | 实现侧权威 `JOB_STATES` = **9 值**（`PENDING, RUNNING, VALIDATING, COMPLETED, FAILED, CANCEL_REQUESTED, CANCELLED, RETRYING, BLOCKED`；`states.py:11-14`，且 `job_status/v1` 的 enum 直接取 `list(JOB_STATES)`，`contracts/specs.py:585`）；**实测 E：`BLOCKED` 返回 `200`** | ❌ **不一致（合同 enum 不完备）** | 扩为 9 值；或显式声明"合同仅覆盖 API 可达子集"并给出依据 —— 二者取一，**不得**留 4 值 |
| 6 | `data.skill_result` | 仅 **COMPLETED** 时附加、位置 `data` 内、形状同 execute；不得进 `required`（`:1591-1597`） | 实测：终态出现（C）、非终态**不出现**（B）✓ 位置与形状 ✓ | ✅ | — |
| 7 | `data.progress` | `integer`，`minimum 0`、`maximum 100`（`:1574-1577`） | 运行中 `0`、终态 `100`（B/C） | ✅ | — |
| 8 | `data.finished_at` | `string` `format: date-time`、`nullable: true`（`:1570-1573`） | 运行中 `null`、终态时间戳（B/C） | ✅ | — |
| 9 | 404 体 | `InfrastructureErrorResponse` `{detail:{error:{code,message,retryable}}}`（`:1713-1725`） | 实测同形（D） | ✅ | — |
| 10 | 路径参数名 | `/v1/jobs/{jobId}`（占位符 **camelCase**） | 路由 `/v1/jobs/{job_id}`（`server.py:530`） | ⚠ **命名差异，不影响行为**（占位符名不进 wire format） | 可不改；若要一致可对齐占位符名 |
| 11 | 契约面覆盖 | 该路径**已在合同声明**（`get` + 200/404 接线，`:664-696`） | 实现有该路由（`server.py:530`） | ✅ | **非**"实现有、合同未声明"⇒ **无需** A-6 式登记 |

## 3. 归纳与建议

- **唯一实质不符 = 第 5 行**：合同 `data.status.enum`（4 值）**窄于**实现可达域（9 值）；
  **已用实验证明**：端点会**如实返回**合同 enum 外的 `BLOCKED`（`200`）。
  ⇒ 影响：任何**按合同生成类型/校验响应**的调用方，遇到 `BLOCKED`/`CANCELLED`/`VALIDATING`/`RETRYING`/
  `CANCEL_REQUESTED` 时会**把合法响应判为非法**（GITS `DshJobPoller` 只读字符串故不受影响，但严格校验方会）。
- **既有机械核对用例的覆盖盲区**：`tests/integration/test_contract_shape_conformance.py:224-244` 已核对
  `/v1/jobs/{jobId}` 的信封、键集、404、`skill_result` 位置，但**只观测 `data.status == "COMPLETED"`
  一个取值**（`:234`）⇒ **对 enum 的可达域无覆盖**，因此本条差异**不被现有断言捕获**。
- **建议（属 1.6.0 家族，不在本轮执行）**：把该值域做成**机械核对**——
  「合同 `JobStatusData.status.enum` == 实现 `states.JOB_STATES`（或合同显式声明子集 + 理由）」
  ⇒ 与 **A-6** 的"合同路径集合 == 实现路由集合 ± 显式豁免清单"**同一手法**（集合级、防复发）。
- 其余 10 项**全部一致**（含 202 受理体、信封、键集、条件 `skill_result`、404 体）；
  唯一非行为差异是第 10 行的占位符命名。

## 4. 一处自我更正（c20 此前对 TL 的口述）

我在 Step 2 落地轮报告中曾写"该端点实测 **200 + `data.status = OK`**" —— **表述不准确**：
实测到的 `OK` 是**信封** `status`（`:1509-1511` 所述"恒为 `OK`"），而 **`data.status` 是 Job 业务状态**
（实测取值 `RUNNING` → `COMPLETED`，并可为 `BLOCKED` 等）。本次以 A–E 五条**原始报文**更正之。

## 5. 非声明

本文件为**只读分析产物**：**未回改合同**、**未改任何代码/测试**、**未 commit**；
**不代表** D-24 已关闭；**不主张** `BLOCKED`（或其它值）已穷尽实现可达域（本清单仅以**实测的 `BLOCKED`**
与**权威值域 `JOB_STATES`** 为据；`CANCELLED` 由 `runtime_store.cancel_job()` 产生且被
`tests/unit/test_job_queue.py:425-430` 覆盖，但其**经本端点的可见性**本文**未逐条证明**）。
行号均为 **HEAD 时点**行号，后续改动须按 E-2 重新对齐。
