# DKWS-GITS 契约差异报告

> 生成时间：2026-08-28
> 基线：DKWS v1.4 契约 vs GITS DshHttpSkillExecutionAdapter / DshHttpSkillGateAdapter / V14DkwsIntegrationController

---

## 1. 端点对照

| # | DKWS 端点 | GITS 调用端点 | 匹配状态 | 备注 |
|---|---|---|---|---|
| 1 | `GET /v1/health` | 无直接调用 | **DKWS 独有** | GITS 使用 `/api/skill/health` 做健康检查 |
| 2 | `GET /api/skill/health` | `GET {dsh.base-url}/api/skill/health` | **完全匹配** | GITS `DshHttpSkillGateAdapter` 调用 |
| 3 | `GET /v1/skills` | 无调用 | **DKWS 独有** | 规范要求新增，server.py 尚未实现 |
| 4 | `POST /api/skill/execute` | `POST {dsh.base-url}/api/skill/execute` | **完全匹配** | GITS `DshHttpSkillExecutionAdapter` 调用 |
| 5 | `GET /api/skill/report/{requestId}` | `GET {dsh.base-url}/api/skill/report/{requestId}` | **完全匹配** | GITS 报告查看 |
| 6 | `GET /api/skill/gates/{customerId}` | `GET {dsh.base-url}/api/skill/gates/{customerId}` | **完全匹配** | v1.4 新增，V14DkwsIntegrationController 暴露 |
| 7 | `POST /api/skill/gates/audit` | `POST {dsh.base-url}/api/skill/gates/audit` | **完全匹配** | v1.4 新增，V14DkwsIntegrationController 暴露 |
| 8 | `POST /v1/jobs` | 无直接调用 | **DKWS 独有** | 异步提交端点，GITS 通过 execute + async=true 触发 |
| 9 | `GET /v1/jobs/{jobId}` | `GET {dsh.base-url}/v1/jobs/{jobId}` | **完全匹配** | GITS `DshJobPoller` 轮询 |
| 10 | `GET /livez` | 无调用 | **DKWS 独有** | K8s 存活探针 |
| 11 | `GET /readyz` | 无调用 | **DKWS 独有** | K8s 就绪探针 |
| 12 | `GET /metrics` | 无调用 | **DKWS 独有** | Prometheus 指标 |

## 2. 请求格式差异

### 2.1 Skill Execute 请求

| 字段 | DKWS 期望 | GITS 发送 | 差异 |
|---|---|---|---|
| `skillId` | string, required | `command.getSkillId()` | 无差异 |
| `requestId` | string, required | `command.getRequestId()` | 无差异 |
| `async` | boolean, optional (default false) | `command.isAsync()` | 无差异 |
| `request.customerId` | string, 单客户技能 | `Map.of("customerId", command.getCustomerId())` | 无差异 |
| `request.context` | ContextPackage, SP-20/21 | `command.getContext()` (Map) | 无差异 |
| `context` (顶层) | ContextPackage, v1.3 兼容 | 未使用 | GITS 始终通过 request.context 传递 |

**结论**：请求格式完全兼容，无差异。

### 2.2 Gate Audit 请求

| 字段 | DKWS 期望 | GITS 发送 | 差异 |
|---|---|---|---|
| `customerId` | string, required | `customerId` | 无差异 |
| `gate` | string, required | `gate` | 无差异 |
| `decision` | enum [PASSED, BLOCKED, WAIVED] | `decision` | 无差异 |
| `decidedBy` | string, required | `decidedBy` | 无差异 |
| `reason` | string, optional | `reason` | 无差异 |

**结论**：完全兼容。

## 3. 响应格式差异

### 3.1 Skill Execute 同步响应 (200)

| 字段 | DKWS 返回 | GITS 解析 | 差异 |
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

| 字段 | DKWS 返回 | GITS 解析 | 差异 |
|---|---|---|---|
| `jobId` | string | `json.getString("jobId")` | 无差异 |
| `status` | "PENDING" | `json.getString("status")` | 无差异 |

### 3.3 Job 状态响应

| 字段 | DKWS 返回 | GITS 解析 | 差异 |
|---|---|---|---|
| `jobId` | string | `json.getString("jobId")` | 无差异 |
| `status` | enum [PENDING, RUNNING, COMPLETED, FAILED] | `SkillExecutionStatus.valueOf(status)` | **需注意**：GITS 枚举为 `PENDING/RUNNING/COMPLETED/FAILED`，与 DKWS 一致 |
| `data.skill_result` | SkillExecuteResponse | 递归解析为 SkillExecutionResult | 无差异 |

### 3.4 Health 响应

| 字段 | DKWS 返回 | GITS 解析 | 差异 |
|---|---|---|---|
| `status` | "ok" / "degraded" | `json.getString("status")` | 无差异 |
| `skills` | array of {skillId, name} | `skills.toList().map { it.getString("skillId") }` | 无差异 |

## 4. 需要协调的变更

### 4.1 DKWS 侧待实现

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
| 3 | SP-21 候选记忆持久化 | P1 | DKWS 不存记忆，GITS 需通过 `InteractionMemoryPort` 持久化 |
| 4 | `data.result` 类型路由 | P2 | 根据 `skillId` 区分 ServiceResult / InteractionMemoryResult / 自由结构 |

### 4.3 配置差异

| 配置项 | GITS application.yaml | DKWS 默认 | 差异 |
|---|---|---|---|
| `dsh.base-url` | `http://127.0.0.1:8106` | `0.0.0.0:8106` | 无差异（同机访问） |
| `dsh.connect-timeout-ms` | 5000 | FastAPI 默认 | 无差异 |
| `dsh.read-timeout-ms` | 120000 (2min) | 无显式超时 | **需注意**：SP-20 异步模式下 DKWS 应在 120s 内返回 202 |
| `dsh.skill-execute-path` | `/api/skill/execute` | `/api/skill/execute` | 无差异 |
| `dsh.health-path` | `/api/skill/health` | `/api/skill/health` | 无差异 |
| `dsh.report-path-prefix` | `/api/skill/report` | `/api/skill/report` | 无差异 |
| `dsh.job-path-prefix` | `/v1/jobs` | `/v1/jobs` | 无差异 |
| `dsh.async-poll-interval-ms` | 3000 (3s) | N/A | GITS 侧配置 |
| `dsh.async-poll-timeout-ms` | 180000 (3min) | N/A | GITS 侧配置 |

## 5. 错误码映射

| DKWS 错误码 | HTTP 状态码 | GITS 处理 | 说明 |
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

- 所有 GITS 已调用的端点与 DKWS 实际实现完全匹配
- v1.4 新增字段（`data.ruleViolations`、`data.result`）GITS 忽略未知字段即可，向后兼容
- 唯一功能差异：`GET /v1/skills` 端点 DKWS 尚未实现，但 GITS 当前未调用
- 配置路径完全对齐，无需修改

**风险点**：
1. SP-20 异步模式下，DKWS 需确保在 GITS `read-timeout-ms`（120s）内返回 202
2. 生产部署前需实现 API Key 认证和 K8s 探针
3. GITS 需实现 `releaseBlockedUntil` 闸门放行逻辑和 SP-21 记忆持久化
