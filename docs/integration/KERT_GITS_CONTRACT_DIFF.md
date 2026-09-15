# KERT-GITS 契约差异报告

> 生成时间：2026-08-28
> 基线：KERT v1.4 契约 vs GITS DshHttpSkillExecutionAdapter / DshHttpSkillGateAdapter / V14KertIntegrationController

---

## 1. 端点对照

| # | KERT 端点 | GITS 调用端点 | 匹配状态 | 备注 |
|---|---|---|---|---|
| 1 | `GET /v1/health` | 无直接调用 | **KERT 独有** | GITS 使用 `/api/skill/health` 做健康检查 |
| 2 | `GET /api/skill/health` | `GET {dsh.base-url}/api/skill/health` | **完全匹配** | GITS `DshHttpSkillGateAdapter` 调用 |
| 3 | `GET /v1/skills` | 无调用 | **KERT 独有** | 规范要求新增，server.py 尚未实现 |
| 4 | `POST /api/skill/execute` | `POST {dsh.base-url}/api/skill/execute` | **完全匹配** | GITS `DshHttpSkillExecutionAdapter` 调用 |
| 5 | `GET /api/skill/report/{requestId}` | `GET {dsh.base-url}/api/skill/report/{requestId}` | **完全匹配** | GITS 报告查看 |
| 6 | `GET /api/skill/gates/{customerId}` | `GET {dsh.base-url}/api/skill/gates/{customerId}` | **完全匹配** | v1.4 新增，V14KertIntegrationController 暴露 |
| 7 | `POST /api/skill/gates/audit` | `POST {dsh.base-url}/api/skill/gates/audit` | **完全匹配** | v1.4 新增，V14KertIntegrationController 暴露 |
| 8 | `POST /v1/jobs` | 无直接调用 | **KERT 独有** | 异步提交端点，GITS 通过 execute + async=true 触发 |
| 9 | `GET /v1/jobs/{jobId}` | `GET {dsh.base-url}/v1/jobs/{jobId}` | **完全匹配** | GITS `DshJobPoller` 轮询 |
| 10 | `GET /livez` | 无调用 | **KERT 独有** | K8s 存活探针 |
| 11 | `GET /readyz` | 无调用 | **KERT 独有** | K8s 就绪探针 |
| 12 | `GET /metrics` | 无调用 | **KERT 独有** | Prometheus 指标 |

## 2. 请求格式差异

### 2.1 Skill Execute 请求

| 字段 | KERT 期望 | GITS 发送 | 差异 |
|---|---|---|---|
| `skillId` | string, required | `command.getSkillId()` | 无差异 |
| `requestId` | string, required | `command.getRequestId()` | 无差异 |
| `async` | boolean, optional (default false) | `command.isAsync()` | 无差异 |
| `request.customerId` | string, 单客户技能 | `Map.of("customerId", command.getCustomerId())` | 无差异 |
| `request.context` | ContextPackage, SP-20/21 | `command.getContext()` (Map) | 无差异 |
| `context` (顶层) | ContextPackage, v1.3 兼容 | 未使用 | GITS 始终通过 request.context 传递 |

**结论**：请求格式完全兼容，无差异。

### 2.2 Gate Audit 请求

| 字段 | KERT 期望 | GITS 发送 | 差异 |
|---|---|---|---|
| `customerId` | string, required | `customerId` | 无差异 |
| `gate` | string, required | `gate` | 无差异 |
| `decision` | enum [PASSED, BLOCKED, WAIVED] | `decision` | 无差异 |
| `decidedBy` | string, required | `decidedBy` | 无差异 |
| `reason` | string, optional | `reason` | 无差异 |

**结论**：完全兼容。

## 3. 响应格式差异

### 3.1 Skill Execute 同步响应 (200)

| 字段 | KERT 返回 | GITS 解析 | 差异 |
|---|---|---|---|
| `requestId` | string | 未显式解析 | GITS 使用本地 requestId |
| `status` | enum [ok, skill_error, exit_policy_no_new_evidence] | `status.equals("ok")` | 无差异 |
| `data.skillId` | string | `data.getString("skillId")` | 无差异 |
| `data.reportUrl` | string | `data.getString("reportUrl")` | 无差异 |
| `data.result` | object (自由结构 / ServiceResult) | `data.get("result")` (Object) | 无差异 |
| `data.ruleViolations` | array (v1.4 新增) | 未解析（忽略未知字段） | **兼容** |
| `errors` | array | `json.getJSONArray("errors")` | 无差异 |
| `assemblyTrace` | object | 未解析 | **兼容** |
| `modelCalls` | array | 未解析 | **兼容** |

### 3.2 异步响应 (202)

| 字段 | KERT 返回 | GITS 解析 | 差异 |
|---|---|---|---|
| `jobId` | string | `json.getString("jobId")` | 无差异 |
| `status` | "PENDING" | `json.getString("status")` | 无差异 |

### 3.3 Job 状态响应

| 字段 | KERT 返回 | GITS 解析 | 差异 |
|---|---|---|---|
| `jobId` | string | `json.getString("jobId")` | 无差异 |
| `status` | enum [PENDING, RUNNING, COMPLETED, FAILED] | `SkillExecutionStatus.valueOf(status)` | **需注意**：GITS 枚举为 `PENDING/RUNNING/COMPLETED/FAILED`，与 KERT 一致 |
| `data.skill_result` | SkillExecuteResponse | 递归解析为 SkillExecutionResult | 无差异 |

### 3.4 Health 响应

| 字段 | KERT 返回 | GITS 解析 | 差异 |
|---|---|---|---|
| `status` | "ok" / "degraded" | `json.getString("status")` | 无差异 |
| `skills` | array of {skillId, name} | `skills.toList().map { it.getString("skillId") }` | 无差异 |

## 4. 需要协调的变更

### 4.1 KERT 侧待实现

| # | 变更 | 优先级 | 说明 |
|---|---|---|---|
| 1 | `GET /v1/skills` 端点 | P2 | OpenAPI 规范已定义，server.py 尚未实现。GITS 当前未调用，但未来 Skill 发现需要 |
| 2 | `POST /v1/jobs` 独立端点 | P3 | 当前通过 `POST /api/skill/execute?async=true` 触发，独立端点为规范预留 |
| 3 | API Key 认证 | P2 | 当前演示环境无认证，生产需实现 `X-API-Key` header 校验 |
| 4 | `/metrics` Prometheus 端点 | P2 | 生产可观测性必需 |
| 5 | `/livez` + `/readyz` 探针 | P1 | K8s 部署必需 |

### 4.2 GITS 侧待调整

| # | 变更 | 优先级 | 说明 |
|---|---|---|---|
| 1 | 处理 `data.ruleViolations` | P2 | v1.4 新增字段，GITS 应解析并在 UI 展示 BLOCKING 违规 |
| 2 | SP-20 `customerVersion.releaseBlockedUntil` 逻辑 | P1 | GITS 需实现闸门放行检查，`releaseBlockedUntil` 为空时才允许展示对客版 |
| 3 | SP-21 候选记忆持久化 | P1 | KERT 不存记忆，GITS 需通过 `InteractionMemoryPort` 持久化 |
| 4 | `data.result` 类型路由 | P2 | 根据 `skillId` 区分 ServiceResult / InteractionMemoryResult / 自由结构 |

### 4.3 配置差异

| 配置项 | GITS application.yaml | KERT 默认 | 差异 |
|---|---|---|---|
| `dsh.base-url` | `http://127.0.0.1:8106` | `0.0.0.0:8106` | 无差异（同机访问） |
| `dsh.connect-timeout-ms` | 5000 | FastAPI 默认 | 无差异 |
| `dsh.read-timeout-ms` | 120000 (2min) | 无显式超时 | **需注意**：SP-20 异步模式下 KERT 应在 120s 内返回 202 |
| `dsh.skill-execute-path` | `/api/skill/execute` | `/api/skill/execute` | 无差异 |
| `dsh.health-path` | `/api/skill/health` | `/api/skill/health` | 无差异 |
| `dsh.report-path-prefix` | `/api/skill/report` | `/api/skill/report` | 无差异 |
| `dsh.job-path-prefix` | `/v1/jobs` | `/v1/jobs` | 无差异 |
| `dsh.async-poll-interval-ms` | 3000 (3s) | N/A | GITS 侧配置 |
| `dsh.async-poll-timeout-ms` | 180000 (3min) | N/A | GITS 侧配置 |

## 5. 错误码映射

| KERT 错误码 | HTTP 状态码 | GITS 处理 | 说明 |
|---|---|---|---|
| `INVALID_PARAMETER` | 400 | `SkillExecutionException` | 参数校验失败 |
| `SKILL_NOT_FOUND` | 404 | `SkillExecutionException` | Skill 未注册 |
| `SKILL_EXECUTION_ERROR` | 500 | `SkillExecutionException` | 执行内部错误 |
| `CONTEXT_VALIDATION_ERROR` | 400 | `SkillExecutionException` | ContextPackage 校验失败 |
| `GATE_CHECK_FAILED` | 422 | `SkillExecutionException` | 闸门检查失败 |
| `JOB_NOT_FOUND` | 404 | `SkillExecutionException` | Job 不存在 |
| `INTERNAL_ERROR` | 500 | `SkillExecutionException` | 系统内部错误 |

GITS 适配器对非 200 响应统一抛 `SkillExecutionException`，fail-closed 走 `FallbackSkillExecutionAdapter`。

## 6. 总结

**兼容性评估：高度兼容**

- 所有 GITS 已调用的端点与 KERT 实际实现完全匹配
- v1.4 新增字段（`data.ruleViolations`、`data.result`）GITS 忽略未知字段即可，向后兼容
- 唯一功能差异：`GET /v1/skills` 端点 KERT 尚未实现，但 GITS 当前未调用
- 配置路径完全对齐，无需修改

**风险点**：
1. SP-20 异步模式下，KERT 需确保在 GITS `read-timeout-ms`（120s）内返回 202
2. 生产部署前需实现 API Key 认证和 K8s 探针
3. GITS 需实现 `releaseBlockedUntil` 闸门放行逻辑和 SP-21 记忆持久化

---

## 7. KERT 侧合同更正通知（2026-09-16；`v1.5.0` → `v1.5.1`）

> **性质**：本节由 KERT 侧编写，作为**通知渠道备料**；**是否送达 GITS 由 Owner 决定**。
> **未修改 GITS 仓任何文件**（本节全部 GITS 侧引用均为只读核对）。
> 触发：冲突 **C-20** 的归并候选分析（`evidence/m7-3/CANDIDATE-CONTRACT-MERGE-V1-V2.md` §2.5）
> 发现合同与实现存在多处失实，已按实现逐处更正（commit `62b967a`、`f7749af` 及 2026-09-16 补丁）。
> 合同 `info.version`：**`1.5.0` → `1.5.1`**（更正性补丁；Contract Owner 追认的对象是 `1.5.0` 的
> additive 增量，bump 以保持"被追认对象唯一可指"）。

### 7.1 影响调用方口径的更正项（逐项给出结论）

| # | 端点 / 项 | 合同侧更正 | GITS 现行读取（只读核对） | GITS 是否需改码 |
|---|---|---|---|---|
| 1 | `GET /v1/jobs/{jobId}`（200） | 原声明为**扁平** `{jobId, status, createdAt, completedAt, data.skill_result}`；现更正为**标准信封** + `data.job_id`（snake_case） | `DshJobPoller.java:122-128` 读 **`data.status`**（强制非空）与 **`data.skill_result`** | **否**。⚠ 明确：`data.status` / `data.skill_result` 的**嵌套位置不变**，既有读取不受影响 |
| 2 | `GET /v1/jobs/{jobId}`（404） | 原声明为 `ErrorResponse`；现更正为 `{"detail":{"error":{code,message,retryable}}}`（实测） | `DshJobPoller.java:107-112` 对非 2xx 统一抛 `SkillExecutionException` → Fallback | **否** |
| 3 | `POST /api/skill/execute`（404） | 原声明为 `ErrorResponse`（含 `SKILL_NOT_FOUND` 示例）；现更正为**与 200 同构**：`{requestId, status:"skill_error", data:{reportUrl}, errors:[{code:"UNKNOWN_SKILL"}], assemblyTrace, modelCalls}` | `DshHttpSkillExecutionAdapter.java:27-33` 已按"404 + `errors[0].code=UNKNOWN_SKILL`"实现；`:187-197` 按顶层 `requestId`/`status`/`data` 解析 | **否**（口径本就一致）。附注：本文件 §5 表格第 130 行的 `SKILL_NOT_FOUND` 为旧写法，实践返回 **`UNKNOWN_SKILL`** |
| 4 | `POST /api/skill/execute`（**422 新增**） | 原声明 **`400`**，实测**不可达**（路由无 `try/except`，Pydantic 直接 422）；现更正为 `422` + FastAPI 校验体 `{"detail":[{type,loc,msg,input}]}` | 对非 2xx 统一抛异常（`:139-144`） | **否**（除非 GITS 侧有 `400` 特判，建议自查一次） |
| 5 | `POST /api/skill/execute`（500） | 原声明为 `ErrorResponse` 但实现落到 **FastAPI 默认 500 纯文本**；已在**实现侧**补齐 app 级处理器（`src/kert/api/server.py` 的 `_unhandled_exception`），现实际返回 JSON 信封：`{requestId, status:"skill_error", errors:[{code:"INTERNAL_ERROR", message:"内部错误"}]}` | `parse()` 仅在 2xx 路径解析 | **否**；对 GITS 为**增强**（此前非 JSON、无法解析；异常细节不回显） |
| 6 | `GET /api/skill/gates/{customerId}` | `gates[]` 原误写为 `{gate, state, checklist:{must,forbidden}}`；现更正为资产形状 `{gateId, name, sequence, must, forbidden, assetPath}`（**无 `data` 包装**，顶层 `{customerId, gates}`） | `DshHttpSkillGateAdapter.java:80-82`（已知无 `data` 包装）、`:88-96`（读 `criteria`，缺失则回落 **`must`**）、`:99`（回落 **`assetPath`**）、`:102-103`（读 **`gateId`/`name`**） | **否**（GITS 读的键与更正后形状一致；仅请顺带确认闸门页渲染键名） |
| 7 | `GET /api/skill/report/{requestId}`（404） | 原未声明响应体；现更正为 `{"detail":"<字符串>"}`（实现 `HTTPException(detail=str)`） | 报告查看路径（本文件 §1 第 5 行） | **建议自查**：若 GITS 把 404 体当 JSON **对象**解析，需改为兼容字符串 |

### 7.2 结论

- **无需 GITS 改码即可继续联调**：第 1/2/3/5 项是被动兼容（或增强），第 1 项的嵌套位置**不变**。
- **建议 GITS 侧自查两项**：第 6 项（闸门渲染键名）、第 7 项（报告 404 体解析）。
- **合同未变的调用面**（本文件 §1/§2/§3 的结论仍然有效）：
  `/api/skill/health`、`/api/skill/execute` 的 200/202 请求与响应形状、
  `/api/skill/gates/audit` 的请求体与其 `recorded` 读取（`DshHttpSkillGateAdapter.java:143-144`）、
  `/v1/jobs` 的 `data.status` / `data.skill_result` 位置。

### 7.3 遗留（本节**未**处理，另行立项）

1. **端口口径**：合同 `servers[0].url` 为 `127.0.0.1:8106`，而 GITS `application.yaml:51` 默认
   `DSH_BASE_URL=http://127.0.0.1:8107`（与冲突 C-04 同源）——需 Owner 统一为配置占位或对齐默认值。
2. KERT 侧 `DshHttpSkillGateAdapter` 读取的 `schemaVersion` / `flowName` 两键**不在 KERT 响应中**
   （GITS 使用默认值）——是否补入合同由 Contract Owner 决定。
3. 本文件 §4/§5 的历史段（2026-08-28 基线）中 `GET /v1/skills 尚未实现` 等条目**保留不改**；
   其中已过时的错误码写法见 §7.1 第 3 项附注。

### 7.4 非声明

本节**不是** Contract Owner 批准、**不构成**合同修订或 GITS UAT 通过；
**未修改 GITS 仓任何文件**，**不代表** GITS 已收到/接受本通知；
归并（v1↔v2）仍**未执行**（冲突 C-20 保持 `OPEN`）。
