# DKWS Python Core 运行加固说明（M2-P1）

对应任务包：`M2-P1`（M2.1 认证与安全边界、M2.2 限流与大小限制、M2.3 SQLite Runtime Store）。
依据：`ADR-013`（服务认证）、`ADR-015`（单节点生产 profile）、`ADR-012`（SQLite Runtime Store）。

> 非声明：本文档不代表 DKWS 已生产就绪，不代表安全审计已完成，不代表 GITS UAT 已通过。

## 1. 总览

Python Core 是唯一公共入口。M2-P1 在 HTTP 入口处加入四层中间件，并为可变运行态提供
SQLite 持久化。中间件实际执行顺序（外 → 内）：

```
请求 → 大小限制(413) → 并发限制(429) → 限流(429) → 认证(401/403) → 路由
```

限流置于认证**之前**，使无效密钥的洪水请求同样受限；限流中间件自行识别 API Key 以保持
按 Key 分桶，识别失败退回按客户端 IP 分桶。

## 2. 配置来源与优先级

后者覆盖前者：

1. 代码默认值
2. 配置文件（JSON，路径由 `DKWS_CONFIG_FILE` 指定）
3. 环境变量（`DKWS_*`）
4. 构造参数（`create_app(runtime_config=...)`，供测试注入）

示例配置文件：`examples/config/runtime.prod.example.json`。

## 3. M2.1 认证与安全边界

### 3.1 环境变量

| 变量 | 默认 | 说明 |
|---|---|---|
| `DKWS_PROFILE` | `dev` | `dev` / `prod` |
| `DKWS_BIND_HOST` | `127.0.0.1`（配置层默认） | 监听地址，纳入生产校验 |
| `DKWS_AUTH_ENABLED` | 有密钥时为 `true` | 是否启用认证 |
| `DKWS_AUTH_HEADER` | `X-API-Key` | 认证请求头名称 |
| `DKWS_API_KEYS` | 空 | 逗号分隔的密钥声明 |

> 注意：`scripts/serve_skill_service.py` 的 `--host` 默认为 `0.0.0.0`（沿用既有行为），
> 该值会写入 `DKWS_BIND_HOST` 参与校验。因此生产 profile 下若不启用认证，
> 除认证/限流缺失外还会额外命中"对外监听禁止匿名访问"，启动被拒。

密钥声明格式（三种）：

```
secret
key_id:secret
key_id:secret:scope1|scope2
```

作用域：`read`、`execute`、`admin`。未指定时默认 `read|execute`。

### 3.2 凭据处理

- 密钥仅以 SHA-256 摘要驻留内存，配置文件可直接写 `digest` 从而完全不落明文。
- 摘要比较使用 `hmac.compare_digest`（常量时间），降低时序侧信道风险。
- 密钥长度不足 16 字符直接拒绝启动。
- 错误响应与日志不回显密钥内容，仅使用非机密的 `key_id`。
- `active: false` 表示已吊换/吊销，验证时视为无效。

### 3.3 认证语义

| 情况 | 状态码 | 错误码 |
|---|---|---|
| 认证关闭（dev） | 放行 | — |
| 白名单路径（`/v1/health`、`/api/skill/health`） | 放行 | — |
| 未携带密钥 | 401 | `UNAUTHENTICATED` |
| 密钥无效或已吊销 | 401 | `UNAUTHENTICATED` |
| 密钥有效但作用域不足（如闸门审计需 `admin`） | 403 | `FORBIDDEN` |

401 响应附带 `WWW-Authenticate`，提示所需请求头。同时支持
`Authorization: Bearer <key>` 形式。

### 3.4 生产 profile fail-fast

`DKWS_PROFILE=prod` 时，以下任一不满足即拒绝启动（抛 `ConfigError`）：

- 未启用 API Key 认证
- 启用认证但无任何有效密钥
- 未启用限流
- 未启用请求体大小限制
- 对外监听（非回环地址）却未启用认证

启动脚本 `scripts/serve_skill_service.py` 在 `create_app` 之前完成校验，
校验失败以非零退出码终止；dev 模式未启用认证时打印显式告警。

## 4. M2.2 限流与大小限制

| 变量 | 默认 | 说明 |
|---|---|---|
| `DKWS_RATE_LIMIT_ENABLED` | `false` | 是否启用限流 |
| `DKWS_RATE_LIMIT_RPM` | `600` | 每分钟请求数 |
| `DKWS_RATE_LIMIT_BURST` | `60` | 令牌桶容量（突发额度） |
| `DKWS_SIZE_LIMIT_ENABLED` | `true` | 是否启用大小限制 |
| `DKWS_MAX_REQUEST_BYTES` | `1048576` | 请求体上限 |
| `DKWS_MAX_RESPONSE_BYTES` | `8388608` | 响应体上限 |
| `DKWS_CONCURRENCY_ENABLED` | `false` | 是否启用并发上限 |
| `DKWS_MAX_IN_FLIGHT` | `32` | 在途请求上限 |
| `DKWS_CONCURRENCY_TIMEOUT` | `0` | 许可等待秒数，`0` 表示立即拒绝 |

行为要点：

- **限流**：令牌桶，进程内计数（单机单实例，ADR-015，不引入 Redis）。超限返回 429
  `RATE_LIMITED` 并附 `Retry-After`。健康检查端点豁免，避免探针被拒。
- **请求体大小**：优先按 `Content-Length` 预检；无该头（chunked）时流式累计校验，
  超限即中断，不会把超大请求体读入内存。超限返回 413 `PAYLOAD_TOO_LARGE`。
- **响应体大小**：按 `Content-Length` 或缓冲字节数校验，超限替换为 413。
- **并发**：`asyncio.Semaphore` 限制在途请求数，超限返回 429 `CONCURRENCY_LIMITED`。

所有错误响应与既有领域错误同构：

```json
{"error": {"code": "RATE_LIMITED", "message": "...", "retryable": true}}
```

## 5. M2.3 SQLite Runtime Store

| 变量 | 默认 | 说明 |
|---|---|---|
| `DKWS_RUNTIME_STORE_ENABLED` | `false` | 是否启用运行态持久化 |
| `DKWS_RUNTIME_STORE_PATH` | `<ws>/90_control/runtime/runtime.db` | 数据库路径 |
| `DKWS_RUNTIME_STORE_WAL` | `true` | 是否启用 WAL |
| `DKWS_RUNTIME_STORE_BUSY_TIMEOUT_MS` | `5000` | 忙等超时 |
| `DKWS_IDEMPOTENCY_TTL_SECONDS` | `600` | 幂等记录存活时长 |

### 5.1 权威边界（关键约束）

- **SQLite 不是知识权威源**。知识权威源仍是 `03_core` 下的文件资产。
- Store 仅承载**可变运行态**：幂等记录、Job 状态、Evidence/Gate 审计镜像。
- 数据库文件禁止落入 `01_raw` / `02_work` / `03_core` / `04_serve`，
  违反时构造期抛 `ConflictError`。
- 表结构中不存在任何知识内容表（集成测试对表清单做精确断言以防漂移）。
- Gate 审计的业务权威仍在 GITS；Store 与 JSONL 均为审计镜像。

### 5.2 表结构（schema_version = 1）

| 表 | 用途 |
|---|---|
| `schema_version` | 已应用的 migration 版本 |
| `idempotency_records` | 幂等键 → 响应复放，含 `request_hash` 与 TTL |
| `jobs` | Job 状态、载荷、结果、尝试次数 |
| `evidence_audit` | Evidence 访问/溯源审计（追加式） |
| `gate_audit` | 闸门决策审计镜像（追加式） |

### 5.3 Migration 机制

`MIGRATIONS` 为顺序元组，索引 `i` 对应 `schema_version = i+1`。规则：

- **只能追加，不可修改已发布的 migration**。
- 启动时自动应用未执行的 migration，重复执行幂等。
- 每条 migration 应用后写入 `schema_version` 并提交，中断可续。

### 5.4 可靠性

- WAL + `synchronous=NORMAL` + `busy_timeout`，降低读写竞争。
- 每次操作独立连接，配合进程内写锁，避免跨线程连接复用。
- 幂等记录写入前顺带清理过期行，防止表无界增长。
- 启动时调用 `recover_stale_jobs()`，把上次残留的 `RUNNING` 复位为 `PENDING`。
  （原子领取、lease、dead-letter 属 M2.4 范围，本次未实现。）
- `backup_to()` 使用 SQLite 在线备份 API 生成一致性快照。

### 5.5 幂等复放

启用 Store 后，Skill 执行结果按 `requestId` 持久化，**进程重启后仍可复放**；
内存缓存继续作为一级快路径。未启用时行为与 M1 完全一致（仅内存幂等），
不降低现有能力。

## 6. 健康检查

`GET /v1/health` 的 `data.runtime` 回报加固状态，便于运维核验：

```json
{
  "profile": "prod",
  "auth_enabled": true,
  "rate_limit_enabled": true,
  "size_limit_enabled": true,
  "concurrency_enabled": true,
  "runtime_store_enabled": true,
  "schema_version": 1,
  "warnings": []
}
```

## 7. 启动示例

开发（无认证，显式告警）：

```bash
python scripts/serve_skill_service.py --workspace ./workspace
```

生产 profile（环境变量方式）：

```bash
export DKWS_PROFILE=prod
export DKWS_API_KEYS="gits-caller:<secret-at-least-16-chars>:read|execute"
export DKWS_RATE_LIMIT_ENABLED=true
export DKWS_CONCURRENCY_ENABLED=true
export DKWS_RUNTIME_STORE_ENABLED=true
python scripts/serve_skill_service.py --workspace ./workspace --host 127.0.0.1
```

生产 profile（配置文件方式，推荐——密钥以 digest 保存）：

```bash
export DKWS_CONFIG_FILE=./examples/config/runtime.prod.example.json
python scripts/serve_skill_service.py --workspace ./workspace
```

## 8. 未纳入本次范围

- 分布式限流（需共享状态；当前为单机单实例，见 ADR-015）
- mTLS / TLS 终止（由可信网关负责）
- API Key 自动轮换与密钥管理系统集成
- Job 原子领取 / lease / dead-letter（M2.4）
- `X-Forwarded-For` 信任链（当前有意不信任该头，避免伪造分桶键绕过限流）
