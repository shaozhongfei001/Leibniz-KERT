# DKWS 可观测性说明（M2-P3 / M2.5）

对应任务包：`M2-P3`，范围 `M2.5 可观测性`。
依据：`ADR-015`（单节点生产 profile）、规格 `§9.20`（作业日志契约）、
`DKWS_HYBRID_DEPLOYMENT_AND_OPERATIONS_V1.0_CANDIDATE.md` §6。

> **非声明**：本文档不代表 DKWS 已生产就绪，不代表安全审计已完成，
> 不代表 GITS UAT 已通过，不代表 C′ 受控混合架构已成为正式基线。

## 1. 设计原则

### 1.1 零新增必需依赖

Prometheus 文本格式与 JSON 日志**均自研实现**，未引入 `prometheus_client`
或 `opentelemetry` 作为必需依赖。理由：

- 本项目为单机单实例（ADR-015），指标规模小，自研可完全掌控输出格式；
- 避免为可观测性引入新的供应链面与故障面；
- `pyproject.toml` **未改动**。

`prometheus_client` / `opentelemetry` 若已安装则作为**可选增强**，
缺失时自动降级（与既有 `kuzu` 的 fail-open 风格一致）。
能力状态可从 `app.state.observability_capabilities` 读取。

### 1.2 不改动 §9.20 文件日志

`JobLogger` 的行格式与 `log_sha256` 是受门禁约束的审计契约。
本次**新增** stdout JSON 通道，**不替换**文件通道，二者并存：

| 通道 | 用途 | 格式 | 受 §9.20 约束 |
|---|---|---|---|
| `90_control/jobs/<id>/logs/*.log` | 作业审计留痕 | 空格分隔文本 | **是**（不可改） |
| stdout | 运行时可观测（采集器消费） | 单行 JSON | 否（本次新增） |

## 2. 结构化日志

### 2.1 启用

| 环境变量 | 默认 | 说明 |
|---|---|---|
| `DKWS_STRUCTURED_LOGS` | **prod=true / dev=false** | 是否切为单行 JSON 输出 stdout |
| `DKWS_LOG_LEVEL` | `INFO` | 日志级别 |
| `DKWS_SERVICE_NAME` | `dkws-python-core` | 写入每条日志的服务标识 |

dev 保持人类可读（便于本地调试），prod 默认 JSON（便于采集器解析）。

### 2.2 字段

关键字段按固定顺序排列，便于人工阅读与工具解析：

```json
{
  "timestamp": "2026-08-27T12:00:00Z",
  "level": "INFO",
  "logger": "dkws.access",
  "event_code": "HTTP_ACCESS",
  "message": "GET /v1/catalog -> 200",
  "request_id": "REQ-ea3fa017b29541b6",
  "trace_id": "c94fbdc7153143a4b3c22...",
  "span_id": "e04109e7a4154af1",
  "service": "dkws-python-core",
  "status": 200,
  "duration_ms": 1.612,
  "key_id": "svc",
  "client_ip": "127.0.0.1"
}
```

规格要求的 `requestId` / `traceId` / `tenantId` / `skillId` 均在
`LOG_FIELD_ORDER` 中定义并自动从请求上下文注入。

### 2.3 脱敏（三层）

1. **字段名匹配**：键名含 `password`/`token`/`secret`/`credential`/`api_key` 等
   一律输出 `***`（复用 `logging.SENSITIVE_KEYS`）。
2. **正文内联密钥**：`redact_message()` 处理 `token=xxx`、`Authorization: Bearer xxx`
   等形态。
   > **为何新增**：`_sanitize_message` 仅折叠空白与截断，**不做内容脱敏**；
   > 字段级脱敏也只看键名。M2.5 新增 stdout 通道后，正文中的密钥成为**新的
   > 泄漏面**，故在此收口。
3. **裸密钥字面量**：`sk-`/`ghp_`/`xoxb-` 等常见前缀即使无键名也脱敏。

非敏感数值（`int`/`float`/`bool`）**保留原类型**，便于从日志提取指标。

E2E 已验证：`logs_do_not_leak_api_keys` —— 日志中不出现任何 API Key 明文。

## 3. 探针端点

### 3.1 `/livez`（存活）

**不检查任何外部依赖。** 存活探针失败通常触发重启，若把依赖故障计入存活，
会导致依赖抖动时无谓地重启本服务。依赖健康归 `/readyz`。

```json
{"status": "alive", "service": "dkws-python-core",
 "service_version": "...", "uptime_seconds": 0.373}
```

### 3.2 `/readyz`（就绪）

| 检查项 | 未通过后果 |
|---|---|
| 工作区存在且可写 | **not ready**（无法写审计与产物） |
| Runtime Store 可连接 | 取决于 `DKWS_READINESS_REQUIRE_STORE`（默认 true） |
| 知识投影可读 | 仅 `degraded`，**不阻断** |
| 队列有过期 lease | 仅 `degraded`，不阻断 |

**知识投影为何不作硬性条件**：全新部署尚未发布投影时若判为未就绪，
实例将永远无法进入服务状态；且部分只读能力此时仍可用。
投影缺失通过响应中的 `degraded` 数组与 `/v1/health` 的 `DEGRADED` 暴露。

未就绪返回 **503**，使负载均衡器摘除本实例而**不重启**进程。

```json
{"status": "ready", "degraded": ["knowledge_projection"],
 "checks": {"workspace": {"ok": true, "path": "..."}, ...}}
```

### 3.3 `/metrics`（Prometheus）

返回 `text/plain; version=0.0.4; charset=utf-8`。

| 环境变量 | 默认 | 说明 |
|---|---|---|
| `DKWS_METRICS_ENABLED` | `true` | 关闭后返回 404 |
| `DKWS_METRICS_REQUIRE_ADMIN` | `false` | 是否要求 admin 作用域 |

**访问控制设计**：`/metrics` 的鉴权由 `metrics_require_admin` **单一决定**。
认证中间件对该路径放行（但仍尽力识别身份），因为若按普通端点强制 401，
该开关将永无机会生效（语义矛盾）；且采集器通常无法携带密钥。

> **生产建议**：`metrics_require_admin=true`，或由网络层限制采集来源，
> 二者至少其一。指标含队列深度、DB schema 版本等内部信息。

### 3.4 探针不被限流

`/livez`、`/readyz`、`/metrics`、`/v1/health`、`/api/skill/health` 均在
`DEFAULT_EXEMPT_PATHS` 中，不计入限流——高频周期性访问被限流会导致
误判服务异常。同时 `/livez` 与 `/readyz` 在 `DEFAULT_PUBLIC_PATHS` 中，
生产 profile 下匿名可访问（否则探针会被 401 拦截）。

## 4. 指标清单

| 指标 | 类型 | 标签 | 说明 |
|---|---|---|---|
| `dkws_http_requests_total` | counter | method, path, status | HTTP 请求总数 |
| `dkws_http_request_duration_seconds` | histogram | method, path | 请求耗时（11 个分桶，5ms~10s） |
| `dkws_http_client_errors_total` | counter | method, path, status | 4xx 响应数 |
| `dkws_http_server_errors_total` | counter | method, path, status | 5xx 响应数 |
| `dkws_http_errors_total` | counter | method, path | 未捕获异常数 |
| `dkws_readiness` | gauge | — | 1=就绪，0=未就绪 |
| `dkws_job_queue_claimable` | gauge | — | 可领取 Job 数 |
| `dkws_job_queue_dead_letter` | gauge | — | dead-letter Job 数 |
| `dkws_job_queue_expired_leases` | gauge | — | 待回收 Job 数 |
| `dkws_job_status_count` | gauge | status | 各状态 Job 数 |
| `dkws_process_uptime_seconds` | gauge | — | 进程运行时长 |
| `dkws_build_info` | gauge | version, profile | 构建信息 |
| `dkws_evidence_audit_errors_total` | counter | — | evidence 审计写入失败数 |
| `dkws_metrics_collection_errors_total` | counter | — | 指标采集失败数 |

### 4.1 高基数防护（重要）

路径标签使用**路由模板**而非原始路径：

```
dkws_http_requests_total{method="GET",path="/v1/evidence/{object_id}",status="200"}
```

若直接用原始路径，每个 `object_id` 都会产生一个新时间序列，
足以把指标存储打爆。E2E 已验证 `metrics_no_high_cardinality`。

### 4.2 队列指标采集时机

队列 gauge 在**每次 `/metrics` 被采集时**刷新，不额外起后台线程——
避免为指标引入额外的并发与生命周期管理复杂度。

## 5. 分布式追踪

### 5.1 W3C Trace Context

| 环境变量 | 默认 | 说明 |
|---|---|---|
| `DKWS_TRACING_ENABLED` | `true` | 是否记录 span |
| `DKWS_TRACE_SAMPLE_RATIO` | `1.0` | 采样率 0.0~1.0 |
| `DKWS_OTEL_ENABLED` | `false` | 是否尝试桥接 OpenTelemetry SDK |

行为：

- 解析上游 `traceparent`，**沿用其 trace_id**，生成**新的 span_id**；
- 上游头畸形或全零时**拒绝并新建 trace**，避免伪造值污染链路；
- 响应头回传 `traceparent` 与 `X-Request-Id`；
- 调用方提供的 `X-Request-Id` 被沿用，便于跨系统关联。

### 5.2 内置实现不做网络导出

内置 `Tracer` 仅在进程内保留最近 `max_spans`（默认 256）个 span
供自检与测试断言，**不做网络导出**，因此不引入外部依赖与故障面。
需要真实导出时设 `DKWS_OTEL_ENABLED=true` 并安装 OTel SDK；
未安装时 `attach_otel()` 返回 `False` 并保持内置实现。

## 6. 中间件顺序

```
可观测性 → 大小限制 → 并发限制 → 限流 → 认证 → 路由
```

可观测性置于**最外层**，因此被限流/认证拦截的请求同样产生指标与日志，
使可观测性**不留盲区**（4xx 拒绝也可观测）。E2E 已验证
`rejected_requests_observable`。

### 6.1 身份跨层传递（实现要点）

`BaseHTTPMiddleware` 为**每一层**中间件构造独立的 `Request` 对象，
故仅写 `request.state` 无法传递到路由处理函数。认证中间件通过
`_publish_identity()` 同时写入 `request.state` 与 **ASGI `scope` 字典**
（后者在整个请求生命周期共享），`/metrics` 端点据此读取作用域。

## 7. 启动示例

```bash
# 开发（人类可读日志）
python scripts/serve_skill_service.py --workspace ./workspace

# 生产（JSON 日志 + 指标要求 admin + 启用 Store）
export DKWS_PROFILE=prod
export DKWS_API_KEYS="svc:<secret>:read|execute,ops:<secret>:read|execute|admin"
export DKWS_RATE_LIMIT_ENABLED=true
export DKWS_RUNTIME_STORE_ENABLED=true
export DKWS_METRICS_REQUIRE_ADMIN=true
python scripts/serve_skill_service.py --workspace ./workspace --host 127.0.0.1
```

### 7.1 Prometheus 抓取配置示例

```yaml
scrape_configs:
  - job_name: dkws-python-core
    metrics_path: /metrics
    static_configs:
      - targets: ["127.0.0.1:8106"]
    # metrics_require_admin=true 时需携带密钥
    authorization:
      credentials_file: /etc/prometheus/dkws-admin-key
```

## 8. 已知限制与遗留项

| 项 | 说明 | 归属 |
|---|---|---|
| 指标为进程内，重启归零 | 单机单实例（ADR-015）；counter 重启归零由 Prometheus 的 `rate()` 自然处理 | 设计取舍 |
| 无 OTLP 导出器配置 | 内置追踪不做网络导出；需真实导出时装 OTel SDK 并设 `DKWS_OTEL_ENABLED=true` | 后续 |
| Worker 进程无 `/metrics` | Worker 无 HTTP 端口；其 `WorkerStats` 仅进程内。跨进程指标聚合需 textfile collector 或 pushgateway | 后续 |
| 无日志采样/限流 | 高 QPS 下访问日志可能量大；当前依赖采集侧限流 | 后续 |
| 响应体大小限制对流式响应会缓冲 | 与 M2-P1 相同的既有限制 | 后续 |
| `tenant_id` 字段已定义但未接线 | 多租户尚未落地，字段预留 | M3+ |
