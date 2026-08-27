# DKWS GITS Adapter 参考实现

> DKWS 独立知识工程服务端与 GITS 集成的适配器参考实现。
> 与 GITS `DshHttpSkillExecutionAdapter` / `DshHttpSkillGateAdapter` 功能对齐。

## 目录结构

```
examples/gits_adapter/
├── README.md                          # 本文件
├── python/
│   └── dkws_client.py                 # Python 客户端（标准库，无第三方依赖）
└── curl/
    ├── list_skills.sh                  # 列出可用 Skill
    ├── execute_skill_sync.sh           # 同步执行 Skill
    ├── execute_skill_async.sh          # 异步提交 Skill
    ├── poll_job.sh                     # 轮询 Job 状态
    └── health_check.sh                 # 健康检查
```

## 快速开始

### curl 脚本

```bash
# 健康检查
./curl/health_check.sh

# 列出 Skill
./curl/list_skills.sh

# 同步执行 R1（对公客户画像）
./curl/execute_skill_sync.sh R1 CUST-001

# 异步执行 SP-20（服务建议书）
./curl/execute_skill_async.sh SP-20 CUST-001

# 轮询 Job
./curl/poll_job.sh JOB-SKILL-20260828-001
```

### Python 客户端

```python
from dkws_client import DkwsClient, execute_skill

client = DkwsClient(base_url="http://127.0.0.1:8106", api_key="your-key")

# 同步执行
result = client.execute_skill_sync("R1", "req-001", customer_id="CUST-001")

# 异步执行 + 自动轮询
result = execute_skill(client, "SP-20", "req-002", context={
    "schemaVersion": "1.0.0",
    "customerId": "CUST-001",
})

# 健康检查
health = client.skill_health()
```

## 错误处理最佳实践

### 1. Fail-Closed 原则

**核心思想**：当 DKWS 不可达或返回异常时，GITS 必须以"最安全"的方式失败，绝不补数或降级为假数据。

GITS 的 `FallbackSkillExecutionAdapter` 明确**禁止本地补数**：

```java
// GITS application.yaml
dsh:
  base-url: "${DSH_BASE_URL:http://127.0.0.1:8106}"
  # 空值时 fail-closed，走 FallbackSkillExecutionAdapter（禁止本地补数）
```

Python 客户端实现：

```python
# 非 ok 状态直接抛异常，不返回部分结果
if status != "ok":
    raise DkwsSkillError(message=err_msg, error_code=err_code, detail=resp)
```

**规则**：
- 5xx 错误 → 重试 → 仍失败 → 抛异常 → GITS 走 Fallback（空结果）
- 4xx 错误 → 不重试 → 直接抛异常
- 网络超时/连接失败 → 重试 → 仍失败 → 抛异常
- **绝不**：用缓存数据、默认值、或本地计算替代 DKWS 结果

### 2. 重试策略（指数退避）

| 参数 | 默认值 | 说明 |
|---|---|---|
| `max_retries` | 3 | 最大重试次数（不含首次） |
| `retry_backoff` | 1.0s | 初始退避时间 |
| `retry_backoff_max` | 30.0s | 最大退避时间 |
| 退避公式 | `min(backoff * 2^attempt, max)` | 指数退避 + 上限 |

退避序列示例：1s → 2s → 4s → 8s → ...

**不重试的场景**：
- HTTP 4xx（客户端错误）：参数错误、Skill 不存在、认证失败
- HTTP 202（异步已接受）
- 业务级错误（`status=skill_error`）

**可重试的场景**：
- HTTP 5xx（服务端错误）
- 连接失败（Connection refused）
- 读取超时

### 3. 超时配置建议

| 参数 | 推荐值 | 说明 |
|---|---|---|
| `connect_timeout` | 5s | TCP 连接超时，对齐 GITS `connect-timeout-ms=5000` |
| `read_timeout` | 120s | 响应读取超时，对齐 GITS `read-timeout-ms=120000` |
| `poll_interval` | 3s | Job 轮询间隔，对齐 GITS `async-poll-interval-ms=3000` |
| `poll_timeout` | 180s | Job 轮询总超时，对齐 GITS `async-poll-timeout-ms=180000` |

**特殊场景**：
- SP-21（交互记忆抽取）：同步快任务，≤60s 完成
- SP-20（服务建议书）：**必须异步**，同步超时 120s 不够用

### 4. 错误码映射表

| DKWS 错误码 | HTTP 状态码 | 语义 | GITS 处理 |
|---|---|---|---|
| `INVALID_PARAMETER` | 400 | 请求参数错误 | 不重试，抛 SkillExecutionException |
| `SKILL_NOT_FOUND` | 404 | Skill 未注册 | 不重试，抛 SkillExecutionException |
| `CONTEXT_VALIDATION_ERROR` | 400 | ContextPackage 校验失败 | 不重试，抛 SkillExecutionException |
| `GATE_CHECK_FAILED` | 422 | 闸门检查失败 | 不重试，抛 SkillExecutionException |
| `SKILL_EXECUTION_ERROR` | 500 | Skill 执行内部错误 | 重试，仍失败走 Fallback |
| `INTERNAL_ERROR` | 500 | 系统内部错误 | 重试，仍失败走 Fallback |
| `JOB_NOT_FOUND` | 404 | Job 不存在 | 不重试 |
| `CONNECTION_ERROR` | N/A | 网络连接失败 | 重试，仍失败走 Fallback |
| `TIMEOUT` | N/A | 请求超时 | 重试，仍失败走 Fallback |
| `POLL_TIMEOUT` | N/A | Job 轮询超时 | 不重试，走 Fallback |
| `HTTP_5xx` | 5xx | 服务端错误 | 重试，仍失败走 Fallback |

### 5. 与 GITS Java 适配器对照

| 功能 | GITS Java 适配器 | Python 参考实现 |
|---|---|---|
| 同步执行 | `DshHttpSkillExecutionAdapter.execute()` | `client.execute_skill_sync()` |
| 异步提交 | `DshHttpSkillExecutionAdapter.execute()` + async | `client.execute_skill_async()` |
| Job 轮询 | `DshJobPoller.pollUntilComplete()` | `client.poll_job()` |
| 健康检查 | `DshHttpSkillGateAdapter.checkHealth()` | `client.skill_health()` |
| 闸门查询 | `V14DkwsIntegrationController.getGates()` | `client.get_gates()` |
| 闸门审计 | `V14DkwsIntegrationController.auditGate()` | `client.audit_gate()` |
| Fail-closed | `FallbackSkillExecutionAdapter`（禁止补数） | 抛 `DkwsSkillError` |
| 重试 | Spring RetryTemplate | 手动指数退避 |
| 超时 | RestTemplate connect/read timeout | urllib timeout |
| 认证 | 暂无（演示环境） | `X-API-Key` header |

## API 端点速查

| 端点 | 方法 | 说明 |
|---|---|---|
| `/v1/health` | GET | 服务健康检查 |
| `/api/skill/health` | GET | Skill 子系统健康 |
| `/v1/skills` | GET | 列出可用 Skill |
| `/api/skill/execute` | POST | 执行 Skill（同步/异步） |
| `/api/skill/report/{requestId}` | GET | 获取执行报告 |
| `/api/skill/gates/{customerId}` | GET | 获取闸门清单 |
| `/api/skill/gates/audit` | POST | 闸门决策镜像 |
| `/v1/jobs/{jobId}` | GET | 查询 Job 状态 |
| `/livez` | GET | 存活探针 |
| `/readyz` | GET | 就绪探针 |
| `/metrics` | GET | Prometheus 指标 |

完整规范见 `specs/dkws-openapi-v1.yaml`。
