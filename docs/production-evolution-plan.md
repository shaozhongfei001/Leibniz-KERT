# DKWS 生产级平台演进设计（Production Evolution Plan）

> 2026-08-26 状态更新：本文件为 V1 历史候选，已由
> `docs/architecture/DKWS_PRODUCTION_EVOLUTION_PLAN_V2_CANDIDATE.md` 替代为当前候选。
> 保留本文件用于追溯，不删除。


> 版本：2026-08-26
> 状态：待评审（Owner 离线评审后确认）
> 适用范围：DKWS 从当前原型/联调底座演进为生产级轻量知识工程运行态
> 配套评审：`docs/handover-review-2026-08-26.md`
> 交接入口：`$WS/HANDOVER.md`

---

## 0. 文档目的

本文件回答三个问题：

1. DKWS 当前离生产还差什么？
2. 应该按什么阶段、什么顺序补齐？
3. 每个阶段具体要做什么、做到什么程度、如何验收？

本设计不是推翻现有实现，而是**在保持现有五层工作区、文件权威源、Skill 契约兼容的前提下**，
逐层补齐安全、持久化、可观测、可靠执行、通用知识源/工具框架、多租户与数据治理能力。

---

## 1. 演进目标

### 1.1 目标形态

从“单机原型/联调底座”演进为：

> **单机可生产、可观测、可恢复、可安全接入的轻量知识工程运行态；同时保留未来向多实例/多租户扩展的架构接口。**

### 1.2 非目标

- 不追求互联网级微服务化
- 不引入重型分布式中间件（除非确有必要）
- 不改变 DKWS 的“文件系统为权威源”核心原则
- 不破坏 GITS 已对接的 v1.3/v1.4 契约

### 1.3 设计原则

1. **兼容优先**：现有 `/api/skill/execute`、`/v1/*` 对外契约保持兼容。
2. **可重建不变**：`03_core` 唯一权威，`04_serve` 全部可重建。
3. **演进有 ADR**：每个关键决策必须记录。
4. **先地基后能力**：安全、持久化、可观测优先于工具/多租户。
5. **单机优先**：先保证单机生产可用，再考虑多实例。

---

## 2. 目标架构

```text
┌─────────────────────────────────────────────────────────────┐
│                     接入层 / API Gateway                     │
│  TLS · API Key / JWT · 限流 · CORS · 审计日志                │
└──────────────────────────────┬──────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────┐
│                      DKWS Runtime Core                      │
│  FastAPI Routers                                             │
│  ├── /v1/*         知识服务（兼容）                          │
│  ├── /api/skill/*  Skill 执行服务（兼容）                    │
│  ├── /api/v2/*     新演进 API（多租户/治理/管理）             │
│  └── /livez /readyz /metrics                                 │
├─────────────────────────────────────────────────────────────┤
│  Application Layer                                          │
│  ├── 知识管道：ingest → parse → extract → review → publish   │
│  ├── KnowledgeService：检索 / 图谱 / 规则 / 溯源             │
│  ├── SkillExecutionService：路由 / 执行 / 编排 / 幂等         │
│  ├── ToolExecutionService：工具注册 / 调用 / 审计            │
│  └── Tenant/Policy Service：租户隔离 / 权限 / 数据策略        │
├─────────────────────────────────────────────────────────────┤
│  Infrastructure Layer                                        │
│  ├── LLM Gateway：重试 / 熔断 / 限流 / 结构化输出 / 成本计量  │
│  ├── Knowledge Sources：Parquet / Kùzu / SQL / S3 / 向量库 / HTTP │
│  ├── Tool Providers：内部工具 + 外部 API 适配                 │
│  ├── Runtime Store：SQLite/PostgreSQL（幂等、任务、配置、审计）│
│  ├── Queue/Worker：持久化任务队列 + 独立 Worker 进程          │
│  └── Observability：Metrics / Tracing / Structured Logs      │
└──────────────────────────────┬──────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────┐
│                     Data Plane                               │
│  01_raw / 02_work / 03_core / 04_serve / 90_control          │
│  本地磁盘 / 挂载盘 / S3 兼容对象存储（未来）                  │
└─────────────────────────────────────────────────────────────┘
```

---

## 3. 现状与差距基线

### 3.1 已有能力

- 五层工作区（01_raw → 02_work → 03_core → 04_serve + 90_control）
- 知识管道：ingest / parse / extract / review / publish / projection / rollback
- 知识服务：search / data_query / get_entity / graph / evaluate_rule / trace / catalog
- Skill 服务：12 个 Skill、幂等、无新证据策略、assemblyTrace、modelCalls
- 投影：Parquet + Kùzu 图 + fingerprint
- 治理：jobs、gates、audit、locks、日志脱敏
- 测试：集成 137 用例全绿，另有安全/恢复/E2E 测试

### 3.2 生产级差距

| 维度 | 现状 | 差距 |
|---|---|---|
| 安全 | 无鉴权、无 TLS、无限流 | 不能对外生产 |
| 状态 | 幂等/evidence/异步线程全内存 | 重启即丢 |
| 可观测 | 访问日志 + job 文件 | 无 metrics/tracing/告警 |
| 可靠 | daemon thread，无队列/重试 | 任务易丢 |
| LLM | 直接 urllib 调用，无重试/熔断 | 成本与稳定性不可控 |
| 输出 | 正则抓 JSON | 无 schema 强校验 |
| 知识源 | 仅 Parquet/Kùzu/文件 | 无统一 Source 接口 |
| 工具 | 无 ToolRegistry | 未产品化 |
| 租户 | 单租户 | 无隔离 |
| 合规 | 无数据分级/保留策略 | 不满足监管要求 |
| 部署 | systemd 用户服务 | 无容器/CI/CD/备份 SOP |

---

## 4. Phase 1：生产加固地基

> 目标：解决“不能对外生产”的硬伤。
> 完成标准：有鉴权、有持久化幂等、有健康检查、有结构化日志、可容器化部署。

### 4.1 安全与访问控制

#### 4.1.1 API Key 认证

设计 `AuthMiddleware`：

- 请求头：`Authorization: Bearer <api_key>` 或 `X-API-Key: <api_key>`
- 支持配置 `DKWS_AUTH_ENABLED=true/false`，默认生产 `true`
- 未带 Key 返回 `401`
- Key 无效/过期返回 `403`
- Key 绑定：
  - `tenant_id`
  - `allowed_skills`
  - `allowed_api_prefixes`
  - `allowed_customer_prefixes`
  - `rate_limit`

#### 4.1.2 API Key 表结构

```sql
CREATE TABLE api_keys (
    id            TEXT PRIMARY KEY,
    tenant_id     TEXT NOT NULL,
    name          TEXT NOT NULL,
    key_hash      TEXT NOT NULL,
    key_prefix    TEXT NOT NULL,
    allowed_skills TEXT NOT NULL,      -- JSON array
    allowed_apis   TEXT NOT NULL,      -- JSON array
    allowed_customer_prefixes TEXT NOT NULL, -- JSON array
    rate_limit_qps REAL NOT NULL DEFAULT 10,
    enabled       INTEGER NOT NULL DEFAULT 1,
    expires_at    TEXT,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);
```

- 数据库只保存 `key_hash`，不保存明文 Key
- `key_prefix` 用于管理端显示
- 首次生成时一次性返回明文 Key

#### 4.1.3 请求签名（可选，防重放）

- 请求头：
  - `X-Timestamp`
  - `X-Nonce`
  - `X-Signature`
- 签名算法：`HMAC-SHA256(api_secret, method + path + timestamp + nonce + body_sha256)`
- 窗口：`|now - timestamp| <= 300s`
- `nonce` 在 Redis/SQLite 中缓存窗口期，防止重放

#### 4.1.4 限流

实现 `RateLimitMiddleware`：

- 按 API Key / IP 双维度
- 支持 QPS 和并发数限制
- LLM 类 Skill 单独限流：
  - 默认 `SP-20` 每 Key 并发 1
  - 默认其他 Skill 每 Key QPS 5
- 超限返回 `429 {"error":{"code":"RATE_LIMITED"}}`

#### 4.1.5 网络与传输

- 默认监听 `127.0.0.1:8106`
- 对外通过 Nginx/Caddy 暴露 TLS
- 禁止明文跨网调用
- 部署模板提供 `docker/nginx/nginx.conf`

### 4.2 配置外部化

#### 4.2.1 配置模型

新增 `src/dkws/config.py`，使用 Pydantic Settings：

```python
class DkwsSettings(BaseSettings):
    workspace: Path
    listen_host: str = "127.0.0.1"
    listen_port: int = 8106
    auth_enabled: bool = False
    runtime_db_url: str = "sqlite:///data/dkws-runtime.db"
    llm_base_url: str | None = None
    llm_api_key: str | None = None
    llm_model: str = "deepseek-chat"
    llm_timeout_seconds: int = 60
    llm_max_retries: int = 2
    llm_circuit_breaker_threshold: int = 5
    llm_circuit_breaker_reset_seconds: int = 30
    max_async_workers: int = 4
    job_max_retries: int = 3
    log_level: str = "INFO"
    log_json: bool = True
```

#### 4.2.2 配置文件示例

```yaml
workspace: /data/dkws/workspace
listen_host: 127.0.0.1
listen_port: 8106
auth_enabled: true
runtime_db_url: sqlite:///data/dkws-runtime/dkws-runtime.db
llm_base_url: https://api.deepseek.com
llm_model: deepseek-chat
llm_timeout_seconds: 60
llm_max_retries: 2
llm_circuit_breaker_threshold: 5
llm_circuit_breaker_reset_seconds: 30
max_async_workers: 4
job_max_retries: 3
log_json: true
```

#### 4.2.3 环境变量覆盖

所有配置项支持环境变量：

- `DKWS_WORKSPACE`
- `DKWS_LISTEN_HOST`
- `DKWS_LISTEN_PORT`
- `DKWS_AUTH_ENABLED`
- `DKWS_RUNTIME_DB_URL`
- `DKWS_LLM_BASE_URL`
- `DKWS_LLM_API_KEY`
- `DKWS_LLM_MODEL`
- `DKWS_LLM_TIMEOUT_SECONDS`
- `DKWS_LLM_MAX_RETRIES`
- `DKWS_LLM_CIRCUIT_BREAKER_THRESHOLD`
- `DKWS_LLM_CIRCUIT_BREAKER_RESET_SECONDS`
- `DKWS_MAX_ASYNC_WORKERS`
- `DKWS_JOB_MAX_RETRIES`
- `DKWS_LOG_LEVEL`
- `DKWS_LOG_JSON`

### 4.3 持久化 Runtime Store

#### 4.3.1 数据库选型

- 单机默认：SQLite
- 多实例/高可用：PostgreSQL
- 通过 SQLAlchemy 或轻量 Repository 抽象隔离

#### 4.3.2 幂等表

```sql
CREATE TABLE idempotency_records (
    request_id   TEXT PRIMARY KEY,
    skill_id     TEXT NOT NULL,
    response_json TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    expires_at   TEXT NOT NULL
);
CREATE INDEX idx_idem_expires ON idempotency_records(expires_at);
```

#### 4.3.3 无新证据状态表

```sql
CREATE TABLE evidence_state (
    customer_id    TEXT PRIMARY KEY,
    latest_timestamp TEXT NOT NULL,
    updated_at     TEXT NOT NULL
);
```

#### 4.3.4 Job 表

```sql
CREATE TABLE jobs (
    job_id       TEXT PRIMARY KEY,
    job_type     TEXT NOT NULL,
    skill_id     TEXT,
    request_id   TEXT,
    payload      TEXT NOT NULL,
    status       TEXT NOT NULL,  -- PENDING/RUNNING/SUCCESS/FAILED/DEAD
    retry_count  INTEGER NOT NULL DEFAULT 0,
    max_retries  INTEGER NOT NULL DEFAULT 3,
    worker_id    TEXT,
    error_code   TEXT,
    error_message TEXT,
    created_at   TEXT NOT NULL,
    started_at   TEXT,
    finished_at  TEXT,
    expires_at   TEXT
);
CREATE INDEX idx_jobs_status ON jobs(status, created_at);
CREATE INDEX idx_jobs_request ON jobs(request_id);
```

#### 4.3.5 审计事件表

```sql
CREATE TABLE audit_events (
    event_id     TEXT PRIMARY KEY,
    event_time   TEXT NOT NULL,
    request_id   TEXT,
    tenant_id    TEXT,
    actor        TEXT,
    action       TEXT NOT NULL,  -- skill.execute / tool.call / api.access / gate.audit
    resource     TEXT,
    detail_json  TEXT NOT NULL,
    ip           TEXT
);
CREATE INDEX idx_audit_time ON audit_events(event_time);
```

### 4.4 结构化日志

#### 4.4.1 日志格式

统一 JSON Lines：

```json
{
  "time": "2026-08-26T01:00:00.000Z",
  "level": "INFO",
  "logger": "dkws.api",
  "requestId": "req-abc",
  "tenantId": "gits",
  "skillId": "SP-20",
  "event": "skill_execute_start",
  "message": "execute started",
  "durationMs": 0,
  "extra": {}
}
```

#### 4.4.2 必须记录的审计点

- API 请求开始/结束
- Skill 执行开始/结束/失败
- LLM 调用开始/结束/失败
- 工具调用开始/结束/失败
- 异步 Job 创建/完成/失败/重试
- 鉴权成功/失败
- 限流触发
- 数据访问（按客户/文档/实体）

### 4.5 健康检查

#### 4.5.1 端点

| 端点 | 用途 |
|---|---|
| `GET /livez` | 进程存活，永远 200 |
| `GET /readyz` | 工作区可写、活动投影存在、Runtime DB 可连接、LLM 配置状态、队列健康 |
| `GET /metrics` | Prometheus 文本格式 |

#### 4.5.2 readyz 检查项

- 工作区根目录存在且可写
- 当前服务活动投影存在
- `03_core/CURRENT.md` 可读
- Runtime DB 可连接
- 队列 Worker 心跳（若启用）
- LLM 配置：未配置时允许 degraded，不阻塞 ready

### 4.6 容器化部署基线

#### 4.6.1 Dockerfile 要点

- 基于 `python:3.11-slim`
- 安装系统依赖：`libgomp1`（Kùzu/pyarrow 需要）
- 复制 `pyproject.toml`、安装依赖
- 复制 `src`、`scripts`、`skills`、`examples/bank-front-skills`
- 非 root 用户运行
- 挂载 `/data/dkws/workspace` 和 `/data/dkws-runtime`
- 启动命令：`python -m uvicorn dkws.api.app:app --host 0.0.0.0 --port 8106`

#### 4.6.2 docker-compose 服务

```yaml
services:
  dkws:
    build: .
    ports:
      - "127.0.0.1:8106:8106"
    environment:
      DKWS_WORKSPACE: /data/dkws/workspace
      DKWS_RUNTIME_DB_URL: sqlite:////data/dkws-runtime/dkws-runtime.db
      DKWS_AUTH_ENABLED: "true"
    volumes:
      - dkws-workspace:/data/dkws/workspace
      - dkws-runtime:/data/dkws-runtime
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://127.0.0.1:8106/livez"]
      interval: 30s
      timeout: 5s
      retries: 3

  nginx:
    image: nginx:1.27
    ports:
      - "443:443"
    volumes:
      - ./docker/nginx/nginx.conf:/etc/nginx/nginx.conf:ro
      - ./certs:/etc/nginx/certs:ro
    depends_on:
      - dkws
```

### 4.7 Phase 1 验收标准

- [ ] 未带 API Key 返回 401
- [ ] 无权限 Skill 返回 403
- [ ] 超限返回 429
- [ ] 服务重启后同 `requestId` 幂等仍命中
- [ ] 服务重启后 R1 `evidenceTimestamp` 状态仍生效
- [ ] `/livez`、`/readyz`、`/metrics` 可用
- [ ] 日志为 JSON 结构化
- [ ] Docker 镜像可构建、可启动、可恢复
- [ ] 现有 137 集成用例全绿

---

## 5. Phase 2：可靠执行与可观测

> 目标：异步任务不丢、LLM 可控、全链路可观测。

### 5.1 持久化任务队列

#### 5.1.1 Worker 模型

- 独立进程 `python -m dkws.worker`
- 启动时从 `jobs` 表恢复：
  - `PENDING` → 直接消费
  - `RUNNING` 且 `worker_id` 已死 → 重置为 `PENDING`
  - `RUNNING` 且还在运行 → 不重复执行
  - `FAILED` 且 `retry_count < max_retries` → 重试
- 心跳表：

```sql
CREATE TABLE worker_heartbeats (
    worker_id   TEXT PRIMARY KEY,
    last_beat   TEXT NOT NULL,
    host        TEXT NOT NULL,
    pid         INTEGER NOT NULL
);
```

#### 5.1.2 任务状态机

```text
PENDING → RUNNING → SUCCESS
   ↑         ↓
   └── FAILED → DEAD
   retry_count++
```

#### 5.1.3 Job 执行器改造

- `SkillExecutionService.execute_async()` 改为：
  1. 写 `jobs` 表
  2. 返回 `job_id`
  3. Worker 消费并调用 `execute()`
  4. 完成写 `result.json` 并更新状态
- 现有 `GET /v1/jobs/{job_id}` 兼容

### 5.2 LLM Gateway

#### 5.2.1 接口

```python
class LLMGateway:
    def complete(
        self,
        *,
        skill_id: str,
        kind: str,
        system: str,
        user: str,
        response_schema: dict | None = None,
        timeout_seconds: int | None = None,
    ) -> LlmResult:
        ...
```

#### 5.2.2 重试策略

- 网络错误/5xx：指数退避重试，默认 2 次
- 4xx：不重试
- 超时：重试 1 次，然后失败
- 结构化输出校验失败：重试 1 次，再失败返回 `skill_error`

#### 5.2.3 熔断器

- 连续失败阈值：默认 5 次
- 熔断时间：默认 30 秒
- 熔断期间直接返回 `skill_error`，不调用 LLM
- 支持半开探测

#### 5.2.4 限流

- 按 Skill 类型限流
- 按租户/API Key 限流
- 全局并发上限

#### 5.2.5 成本计量

每次调用记录：

```json
{
  "model": "deepseek-chat",
  "inputTokens": 100,
  "outputTokens": 200,
  "latencyMs": 3200,
  "estimatedCost": 0.001,
  "skillId": "SP-20",
  "requestId": "req-abc"
}
```

### 5.3 结构化输出校验

#### 5.3.1 Schema 定义

为每个 Skill 定义 Pydantic 输出模型：

- `OutreachScriptOutput`
- `MeetingScriptOutput`
- `PrevisitReportOutput`
- `SupplyChainGraphOutput`
- `ServiceProposalOutput`
- `InteractionMemoryOutput`
- 外部 bank-front 包输出 schema

#### 5.3.2 校验流程

```text
LLM 返回文本
  → 提取 JSON
  → Pydantic model_validate
  → 失败则带错误信息重试一次
  → 再次失败则 fail-closed 返回 skill_error
```

#### 5.3.3 现有解析替换点

- `SkillExecutionService._parse_json()`
- `ServiceProposalExecutor._parse_json()`
- `InteractionMemoryExecutor._parse_json()`

统一替换为 `StructuredOutputValidator`.

### 5.4 Metrics

#### 5.4.1 HTTP 指标

```text
dkws_http_requests_total{method,path,status}
dkws_http_request_duration_seconds{method,path}
dkws_http_inflight_requests{path}
```

#### 5.4.2 Skill 指标

```text
dkws_skill_executions_total{skill_id,status}
dkws_skill_execution_duration_seconds{skill_id}
dkws_skill_llm_calls_total{skill_id,model,result}
dkws_skill_llm_tokens_total{skill_id,model,type}
dkws_skill_llm_estimated_cost_total{skill_id,model}
```

#### 5.4.3 队列指标

```text
dkws_jobs_total{status}
dkws_jobs_duration_seconds{job_type}
dkws_jobs_retries_total{job_type}
dkws_worker_heartbeat_age_seconds{worker_id}
```

#### 5.4.4 知识源指标

```text
dkws_source_calls_total{source,operation,result}
dkws_source_duration_seconds{source,operation}
```

### 5.5 Tracing

- 引入 OpenTelemetry
- `requestId` 作为 `trace_id`
- Span 示例：
  - `POST /api/skill/execute`
  - `SkillExecutionService.execute`
  - `CustomerKnowledgeProvider.ki_map`
  - `KnowledgeService.search`
  - `KuzuGraphBuilder.query`
  - `LLMGateway.complete`
  - `ToolRegistry.call`
- 现有 `assemblyTrace` 保留，作为业务可读轨迹；Span 作为系统可观测轨迹

### 5.6 Phase 2 验收标准

- [ ] 异步任务重启后不丢失，可恢复执行
- [ ] 异步任务失败自动重试，超过重试进入 DEAD
- [ ] LLM 网络失败自动重试
- [ ] LLM 连续失败触发熔断
- [ ] 所有 Skill 输出经过 schema 校验
- [ ] `/metrics` 能看到 HTTP、Skill、LLM、队列、知识源指标
- [ ] OpenTelemetry trace 可导出
- [ ] 现有 137 集成用例全绿

---

## 6. Phase 3：通用知识源与工具调用框架

> 目标：让“读取知识地图、SKILL 路由、Skill 运行、工具调用、多种知识源适配访问”真正产品化。

### 6.1 KnowledgeSource 统一接口

```python
class KnowledgeSource(Protocol):
    name: str
    source_type: str
    health() -> SourceHealth
    search(query: str, *, tenant_id: str | None = None, **kwargs) -> SourceResult
    query(statement: str, *, tenant_id: str | None = None, **kwargs) -> SourceResult
    get(object_id: str, *, tenant_id: str | None = None, **kwargs) -> SourceResult
    graph(start_entity_ids: list[str], *, tenant_id: str | None = None, **kwargs) -> SourceResult
```

统一结果：

```python
@dataclass
class SourceResult:
    records: list[dict]
    meta: dict
    truncated: bool
    latency_ms: float
    source: str
```

统一错误：

```python
@dataclass
class SourceError(Exception):
    source: str
    code: str
    message: str
    retryable: bool
```

### 6.2 首批 KnowledgeSource 适配器

| Source | 操作 | 说明 |
|---|---|---|
| `WorkspaceParquetSource` | search/query/get/graph | 04_serve Parquet 投影 |
| `KuzuGraphSource` | graph/query | Kùzu 图投影 |
| `FileSystemSource` | get | 01_raw/03_core 文件读取 |
| `SqlSource` | query | 只读 SQL 数据源（白名单 SQL） |
| `ObjectStorageSource` | get/search | S3/MinIO 文档/资产 |
| `VectorDbSource` | search | 生产向量库（如 Qdrant/pgvector） |
| `HttpSource` | query/get | 外部业务 API，受白名单和超时约束 |

### 6.3 KnowledgeSource Registry

```python
class KnowledgeSourceRegistry:
    def register(source: KnowledgeSource) -> None
    def get(name: str) -> KnowledgeSource
    def list() -> list[SourceInfo]
    def health() -> dict[str, SourceHealth]
```

- 启动时注册内置 Source
- 支持通过配置启用/停用
- 每个 Source 有独立健康检查

### 6.4 ToolRegistry 统一工具调用

#### 6.4.1 ToolSpec

```python
@dataclass
class ToolSpec:
    name: str
    description: str
    input_schema: dict
    output_schema: dict
    permission: str            # e.g. "knowledge.read", "customer.read"
    timeout_seconds: int = 10
    audit: bool = True
    enabled: bool = True
```

#### 6.4.2 Tool 执行上下文

```python
@dataclass
class ToolContext:
    request_id: str
    tenant_id: str
    actor: str
    customer_ids: list[str]
    skill_id: str | None
```

#### 6.4.3 Tool 执行结果

```python
@dataclass
class ToolResult:
    tool_call_id: str
    name: str
    status: str          # ok / error / blocked
    data: dict
    error: dict | None
    latency_ms: float
    trace: list[dict]
```

#### 6.4.4 首批内置工具

| 工具名 | 权限 | 说明 |
|---|---|---|
| `knowledge.search` | knowledge.read | 检索知识片段 |
| `knowledge.get_entity` | knowledge.read | 获取实体 |
| `knowledge.graph` | knowledge.read | 图谱查询 |
| `knowledge.evaluate_rule` | knowledge.read | 规则评估 |
| `customer.supply_chain` | customer.read | 客户供应链图谱 |
| `customer.ki_map` | customer.read | 客户 KI 片段 |
| `proposal.merge` | proposal.write | 建议书装配 |
| `memory.compare` | memory.read | 记忆比对 |
| `http.get` | http.read | 白名单外部 HTTP GET |

### 6.5 Skill 声明工具依赖

在 SKILL.md front matter 增加：

```yaml
tools:
  - name: knowledge.search
    required: true
  - name: customer.supply_chain
    required: true
```

执行时：

1. 检查工具权限
2. 加载工具
3. 调用工具
4. 记录 `tool_call_id` 到 `assemblyTrace`
5. 工具失败按 Skill 策略 fail-open 或 fail-closed

### 6.6 与现有代码映射

| 现有代码 | 演进后 |
|---|---|
| `CustomerKnowledgeProvider.ki_map()` | `customer.ki_map` Tool 或 `WorkspaceParquetSource` |
| `CustomerKnowledgeProvider.supply_chain()` | `customer.supply_chain` Tool |
| `KnowledgeService.search()` | `knowledge.search` Tool 底层实现 |
| `KnowledgeService.graph()` | `knowledge.graph` Tool 底层实现 |
| `SkillExecutionService._load_packages()` | `SkillRegistry + ToolRegistry` |
| `SkillExecutionService._executor()` | `SkillExecutor + ToolExecutor` |

### 6.7 Phase 3 验收标准

- [ ] 所有现有知识服务可通过统一 Source 接口调用
- [ ] 新增 SQL、S3、向量库 Source 可插拔
- [ ] ToolRegistry 支持注册/查询/执行/审计
- [ ] Skill 可通过声明依赖调用工具
- [ ] 工具调用进入 `assemblyTrace`
- [ ] 现有 `/api/skill/execute` 行为不变
- [ ] 137 集成用例全绿

---

## 7. Phase 4：多租户与数据治理

### 7.1 租户模型

```text
tenant_id
├── workspace_namespace
├── api_keys
├── allowed_customer_ids
├── allowed_skills
└── data_policy
```

#### 7.1.1 租户表

```sql
CREATE TABLE tenants (
    tenant_id   TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    namespace   TEXT NOT NULL,
    enabled     INTEGER NOT NULL DEFAULT 1,
    data_policy TEXT NOT NULL,   -- JSON
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
```

#### 7.1.2 租户数据隔离

- 方式一（当前单工作区）：所有表/投影增加 `tenant_id` 列，查询强制过滤
- 方式二（未来）：每租户独立工作区目录
- 推荐先做方式一，因为改动最小

### 7.2 数据分级与脱敏

#### 7.2.1 敏感级别

| 级别 | 示例 | 默认可见范围 |
|---|---|---|
| PUBLIC | 企业名称、行业 | 所有内部用户 |
| PII | 手机号、身份证、地址 | 客户经理 + 合规 |
| CONFIDENTIAL | 财务、授信、往来流水 | 客户经理 + 审批 |
| INTERNAL | 行内判断、内部报告 | 内部仅限授权 |

#### 7.2.2 脱敏策略

- 手机号：`138****8000`
- 身份证：`3301**********1234`
- 地址：保留到市/区
- 金额：可按权限决定是否显示
- 对客版：沿用 SP-20 的段落级 F/A 过滤

#### 7.2.3 字段标记

在投影 schema 增加 `x_sensitivity` 字段，或维护独立敏感字段清单。

### 7.3 审计与合规

- 所有访问/执行/工具调用写入 `audit_events`
- 支持按租户、客户、时间范围导出
- 支持数据保留策略：
  - `audit_events` 保留 180 天
  - job 保留 30 天
  - 幂等记录保留 10 分钟（可配置）
  - 日志保留 30 天
- 支持数据删除接口（按租户/客户）
- 支持“被遗忘权”类请求流程

### 7.4 Phase 4 验收标准

- [ ] API Key 绑定租户，查询强制租户过滤
- [ ] 同一 `customerId` 在不同租户下不可互读
- [ ] 输出按权限脱敏
- [ ] 审计事件可查询、可导出
- [ ] 数据保留策略可配置
- [ ] 137 集成用例全绿（新增租户用例）

---

## 8. Phase 5：高可用与规模化（远期）

### 8.1 多实例扩展

如果未来需要多实例：

- Runtime Store 从 SQLite 迁移 PostgreSQL
- 工作区放到共享存储（NFS）或对象存储
- 任务队列改用 PostgreSQL/Redis
- 文件锁改为分布式锁（如 Redis/PostgreSQL advisory lock）
- Kùzu 图保持可重建投影，不承担跨实例强一致
- 只读副本可指向同一 04_serve 快照

### 8.2 单机生产高可用

- 03_core 每日备份 + 异地副本
- 90_control 审计日志每日备份
- active-passive 冷备
- 磁盘使用率监控
- 恢复演练至少每季度一次

### 8.3 容量规划

- 工作区大小、投影版本数、job 数量、日志大小
- LLM 成本预算按租户/技能
- Kùzu 图规模上限
- API 并发上限

---

## 9. 与现有代码的改造映射

### 9.1 新增模块

```text
src/dkws/config.py                  # Pydantic Settings
src/dkws/api/middleware/auth.py     # API Key / JWT
src/dkws/api/middleware/rate_limit.py
src/dkws/api/middleware/audit.py
src/dkws/api/health.py              # /livez /readyz /metrics
src/dkws/runtime/store.py           # SQLite/Postgres 仓储
src/dkws/runtime/idempotency.py
src/dkws/runtime/evidence.py
src/dkws/runtime/jobs.py
src/dkws/runtime/audit.py
src/dkws/worker/main.py             # 独立 Worker 进程
src/dkws/llm/gateway.py
src/dkws/llm/retry.py
src/dkws/llm/circuit_breaker.py
src/dkws/llm/cost.py
src/dkws/schema/output.py            # Skill 输出模型
src/dkws/source/base.py
src/dkws/source/registry.py
src/dkws/source/parquet_source.py
src/dkws/source/kuzu_source.py
src/dkws/source/sql_source.py
src/dkws/source/object_storage_source.py
src/dkws/source/vector_source.py
src/dkws/source/http_source.py
src/dkws/tools/registry.py
src/dkws/tools/base.py
src/dkws/tools/knowledge.py
src/dkws/tools/customer.py
src/dkws/tools/proposal.py
src/dkws/tools/memory.py
src/dkws/tenant/model.py
src/dkws/tenant/policy.py
src/dkws/observability/logging.py
src/dkws/observability/metrics.py
src/dkws/observability/tracing.py
```

### 9.2 修改现有模块

| 文件 | 改动 |
|---|---|
| `src/dkws/api/server.py` | 注入中间件、配置、依赖 |
| `src/dkws/application/skills.py` | 幂等/evidence 改 Runtime Store；LLM 走 Gateway；输出走 Validator |
| `src/dkws/application/service_proposal.py` | LLM 走 Gateway；输出走 Validator；异步由 Worker 调度 |
| `src/dkws/application/interaction_memory.py` | 同上 |
| `src/dkws/application/customer_knowledge.py` | 实现 KnowledgeSource 接口 |
| `src/dkws/application/services.py` | 保留 API，底层可接入 Source Registry |
| `src/dkws/infrastructure/adapters/llm.py` | 保留适配器，由 Gateway 封装 |
| `scripts/serve_skill_service.py` | 改为读取配置，可选启动 Worker |

### 9.3 兼容性保证

- `/api/skill/execute` 请求/响应结构不变
- `/v1/*` 请求/响应结构不变
- 错误码新增不破坏旧错误码
- 配置默认值保持当前行为：
  - `auth_enabled=false`
  - `runtime_db_url=sqlite:///...`
  - `log_json=true`（可关闭）

---

## 10. 建议 ADR

| ADR | 内容 |
|---|---|
| `IMP-ADR-012` | 引入 Runtime Store（SQLite 起步，PostgreSQL 可迁移） |
| `IMP-ADR-013` | API Key 认证模型与租户绑定 |
| `IMP-ADR-014` | 统一 KnowledgeSource 接口与 Registry |
| `IMP-ADR-015` | ToolRegistry 与工具调用审计 |
| `IMP-ADR-016` | LLM Gateway（重试/熔断/限流/成本） |
| `IMP-ADR-017` | 异步任务从线程改为持久化 Worker |
| `IMP-ADR-018` | 数据分级与脱敏策略 |
| `IMP-ADR-019` | 租户隔离模型（先列级，后目录级） |

---

## 11. 评审决策点

评审时需要 Owner 明确：

1. 生产部署形态：
   - A. 单机 Docker Compose
   - B. systemd + 裸机
   - C. 多实例容器编排
2. Runtime DB：
   - A. SQLite（先单机）
   - B. PostgreSQL（一步到位）
3. 认证方式：
   - A. API Key 足够
   - B. 需要 JWT/SSO
4. 租户范围：
   - A. 单租户先上生产
   - B. 一开始就多租户
5. 知识源范围：
   - A. 先只做 Parquet/Kùzu/HTTP
   - B. 直接纳入 SQL/向量库/S3
6. 工具调用：
   - A. 先只做内部工具
   - B. 同时支持外部 API 工具
7. 合规要求：
   - A. 内部生产，审计 180 天
   - B. 监管级，需要完整数据删除/导出流程

---

## 12. 里程碑建议

| 里程碑 | 内容 | 预计 |
|---|---|---|
| M1 | Phase 1 完成，可内网生产试用 | 2-3 周 |
| M2 | Phase 2 完成，异步/LLM/可观测稳定 | 4-6 周 |
| M3 | Phase 3 完成，知识源/工具框架落地 | 6-10 周 |
| M4 | Phase 4 完成，多租户/治理 | 10-14 周 |
| M5 | Phase 5 按需启动 | 远期 |

---

## 13. 风险与缓解

| 风险 | 缓解 |
|---|---|
| 改造破坏现有契约 | 所有阶段保留兼容层，跑全量回归 |
| SQLite 并发写瓶颈 | 单机内仍可控；多实例切 PostgreSQL |
| 文件工作区并发冲突 | 保留文件锁；多实例需共享锁升级 |
| LLM 成本失控 | 限流 + 预算 + 成本计量 |
| 多租户过滤遗漏 | 强制 Repository 层注入 tenant_id，禁止裸查询 |
| Kùzu 版本/兼容风险 | 保持可重建投影，必要时回退内存 BFS |

---

## 14. 下一步

1. Owner 离线评审本文档与 `docs/handover-review-2026-08-26.md`
2. 确认第 11 节评审决策点
3. 立项 Phase 1
4. 补充 ADR-012/013
5. 开始代码改造
