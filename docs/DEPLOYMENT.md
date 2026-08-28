# DKWS 部署指南

> 版本：0.1.0 | 适用平台：Linux / macOS

---

## 目录

- [环境要求](#环境要求)
- [安装](#安装)
- [配置](#配置)
  - [环境变量](#环境变量)
  - [配置文件](#配置文件)
- [启动服务](#启动服务)
- [Docker 部署](#docker-部署)
- [Systemd 部署](#systemd-部署)
- [生产安全清单](#生产安全清单)
- [常见问题排查](#常见问题排查)

---

## 环境要求

| 项目 | 要求 |
|------|------|
| Python | >= 3.11（已验证 3.11.7） |
| 操作系统 | Linux / macOS |
| 磁盘 | 工作区目录需可写（五层目录结构） |

### 核心依赖

| 包 | 版本 | 用途 |
|----|------|------|
| typer | >= 0.12 | CLI 框架 |
| PyYAML | >= 6.0 | YAML 解析 |
| pyarrow | >= 15.0 | Parquet 读写 |
| pypdf | >= 5.0 | PDF 解析 |
| python-docx | >= 1.1 | DOCX 解析 |
| kuzu | >= 0.11 | 嵌入式图数据库 |

### 可选依赖（HTTP API）

| 包 | 版本 | 用途 |
|----|------|------|
| fastapi | >= 0.110 | HTTP API 框架 |
| uvicorn | >= 0.29 | ASGI 服务器 |

---

## 安装

### 1. 克隆仓库

```bash
git clone <仓库地址> && cd Leibniz-KERT
```

### 2. 创建虚拟环境并安装

```bash
python3 -m venv --system-site-packages .venv
.venv/bin/pip install -e ".[dev]"
```

如需 HTTP API 功能：

```bash
.venv/bin/pip install -e ".[api]"
```

或同时安装：

```bash
.venv/bin/pip install -e ".[api,dev]"
```

### 3. 验证安装

```bash
.venv/bin/dkws --help
```

---

## 配置

DKWS 配置来源优先级（后者覆盖前者）：

1. 代码内默认值
2. 配置文件（JSON，路径由 `DKWS_CONFIG_FILE` 指定）
3. 环境变量（`DKWS_*`）
4. 构造参数（显式覆盖，供测试使用）

### 环境变量

#### 基础配置

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| `DKWS_PROFILE` | `dev` | 运行 profile：`dev` 或 `prod` |
| `DKWS_BIND_HOST` | `127.0.0.1` | API 监听地址 |
| `DKWS_CONFIG_FILE` | — | JSON 配置文件路径 |

#### 认证配置

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| `DKWS_AUTH_ENABLED` | `false`（dev）/ 强制 `true`（prod） | 是否启用 API Key 认证 |
| `DKWS_AUTH_HEADER` | `X-API-Key` | 认证请求头名称 |
| `DKWS_API_KEY` | — | 单个 API Key（格式：`secret` 或 `key_id:secret` 或 `key_id:secret:scope1\|scope2`） |
| `DKWS_API_KEYS` | — | 多个 API Key，逗号分隔 |

#### 限流配置

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| `DKWS_RATE_LIMIT_ENABLED` | `false`（dev）/ 强制 `true`（prod） | 是否启用限流 |
| `DKWS_RATE_LIMIT_RPM` | `600` | 每分钟请求上限 |
| `DKWS_RATE_LIMIT_BURST` | `60` | 突发额度 |

#### 请求大小限制

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| `DKWS_SIZE_LIMIT_ENABLED` | `true` | 是否启用大小限制 |
| `DKWS_MAX_REQUEST_BYTES` | `1048576`（1 MiB） | 请求体最大字节数 |
| `DKWS_MAX_RESPONSE_BYTES` | `8388608`（8 MiB） | 响应体最大字节数 |

#### 并发控制

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| `DKWS_CONCURRENCY_ENABLED` | `false` | 是否启用并发限制 |
| `DKWS_MAX_IN_FLIGHT` | `32` | 最大在途请求数 |
| `DKWS_CONCURRENCY_TIMEOUT` | `0.0` | 获取并发槽超时（秒） |

#### Runtime Store（SQLite）

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| `DKWS_RUNTIME_STORE_ENABLED` | `false` | 是否启用运行态持久化 |
| `DKWS_RUNTIME_STORE_PATH` | `<工作区>/90_control/runtime/runtime.db` | 数据库文件路径 |
| `DKWS_RUNTIME_STORE_WAL` | `true` | 是否启用 WAL 模式 |
| `DKWS_RUNTIME_STORE_BUSY_TIMEOUT_MS` | `5000` | SQLite 忙等超时（毫秒） |
| `DKWS_IDEMPOTENCY_TTL_SECONDS` | `600` | 幂等记录保留时长（秒） |

#### 可观测性

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| `DKWS_STRUCTURED_LOGS` | `false`（dev）/ `true`（prod） | 结构化 JSON 日志 |
| `DKWS_LOG_LEVEL` | `INFO` | 日志级别 |
| `DKWS_SERVICE_NAME` | `dkws-python-core` | 服务标识 |
| `DKWS_METRICS_ENABLED` | `true` | 是否暴露 `/metrics` |
| `DKWS_METRICS_REQUIRE_ADMIN` | `false` | `/metrics` 是否要求 admin 作用域 |
| `DKWS_TRACING_ENABLED` | `true` | 是否启用追踪 |
| `DKWS_TRACE_SAMPLE_RATIO` | `1.0` | 追踪采样率（0.0~1.0） |
| `DKWS_OTEL_ENABLED` | `false` | 是否桥接 OpenTelemetry SDK |
| `DKWS_READINESS_REQUIRE_STORE` | `true` | `/readyz` 是否检查 Store 连接 |

#### 数据脱敏

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| `DKWS_REDACT_RESPONSE` | `false` | 是否脱敏 API 响应 |
| `DKWS_REDACT_RESPONSE_TEXT` | `false` | 是否掩码响应中的自由文本 |
| `DKWS_REDACT_THRESHOLD` | `RESTRICTED` | 响应脱敏分类阈值 |
| `DKWS_LLM_REDACTION` | `true` | 是否在 LLM 提示词出站前脱敏 |
| `DKWS_REDACT_LOGS` | `true` | 是否对结构化日志字段脱敏 |

#### LLM 适配器（Skill 平台）

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| `DKWS_LLM_BASE_URL` | — | OpenAI 兼容 API 地址 |
| `DKWS_LLM_API_KEY` | — | API 密钥 |
| `DKWS_LLM_MODEL` | — | 模型名称（如 `deepseek-chat`） |

### 配置文件

通过 `DKWS_CONFIG_FILE` 指定 JSON 配置文件路径。示例：

```json
{
  "profile": "prod",
  "bind_host": "0.0.0.0",
  "auth": {
    "enabled": true,
    "keys": [
      {"key_id": "admin-key", "secret": "<16位以上密钥>", "scopes": ["admin", "read", "execute"]},
      {"key_id": "read-only", "digest": "<SHA-256摘要>", "scopes": ["read"], "active": true}
    ]
  },
  "rate_limit": {"enabled": true, "requests_per_minute": 600, "burst": 60},
  "size_limit": {"enabled": true, "max_request_bytes": 1048576, "max_response_bytes": 8388608},
  "concurrency": {"enabled": true, "max_in_flight": 32},
  "runtime_store": {"enabled": true, "wal": true},
  "observability": {
    "structured_logs": true,
    "log_level": "INFO",
    "metrics_enabled": true,
    "metrics_require_admin": true,
    "tracing_enabled": true
  },
  "redaction": {
    "response_enabled": true,
    "llm_enabled": true,
    "log_enabled": true
  }
}
```

> 安全提示：配置文件中的 `secret` 字段为明文，生产建议使用 `digest`（SHA-256 摘要）代替，或仅通过环境变量注入。

---

## 启动服务

### CLI 模式（强制接口）

```bash
# 初始化工作区
.venv/bin/dkws init --workspace /path/to/workspace --force

# 校验工作区
.venv/bin/dkws validate --workspace /path/to/workspace --mode full
```

### HTTP API 模式（可选薄层）

```bash
.venv/bin/python examples/product_demo/serve_api.py \
  --workspace /path/to/workspace --port 8100
```

### 生产启动示例

```bash
export DKWS_PROFILE=prod
export DKWS_AUTH_ENABLED=true
export DKWS_API_KEYS="admin:your-secure-key-at-least-16-chars:admin|read|execute"
export DKWS_RATE_LIMIT_ENABLED=true
export DKWS_RUNTIME_STORE_ENABLED=true
export DKWS_STRUCTURED_LOGS=true

.venv/bin/python examples/product_demo/serve_api.py \
  --workspace /path/to/workspace --port 8100
```

---

## Docker 部署

项目提供 `deploy/Dockerfile` 和 `deploy/docker-compose.yml`。

### 构建镜像

```bash
docker build -f deploy/Dockerfile -t dkws:latest .
```

### Docker Compose

```bash
cd deploy
cp .env.example .env
# 编辑 .env 配置工作区路径和密钥
docker compose up -d
```

---

## Systemd 部署

项目提供 `deploy/dkws.service` 模板：

```bash
sudo cp deploy/dkws.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable dkws
sudo systemctl start dkws
```

编辑 service 文件中的 `WorkingDirectory`、`ExecStart`、环境变量等参数。

---

## 生产安全清单

生产 profile（`DKWS_PROFILE=prod`）强制以下安全控制，缺失则 fail-fast：

- [x] API Key 认证已启用（`DKWS_AUTH_ENABLED=true`）
- [x] 至少配置一个有效 API Key（>= 16 字符）
- [x] 限流已启用（`DKWS_RATE_LIMIT_ENABLED=true`）
- [x] 请求体大小限制已启用
- [x] 对外监听时（非 127.0.0.1）禁止匿名访问
- [x] LLM 提示词出站脱敏已启用（默认开启）
- [x] 密钥仅在内存中以 SHA-256 摘要保存，不落盘、不进日志

---

## 常见问题排查

### 1. `ConfigError: 生产 profile 必须启用 API Key 认证`

**原因**：`DKWS_PROFILE=prod` 但未配置认证。

**解决**：

```bash
export DKWS_AUTH_ENABLED=true
export DKWS_API_KEYS="your-secure-key-at-least-16-chars"
```

### 2. `ConfigError: API Key 'xxx' 长度不足 16 字符`

**原因**：API Key 最少 16 字符。

**解决**：使用更长的密钥。

### 3. 健康探针返回 401

**原因**：生产 profile 下探针被认证拦截。

**解决**：`/v1/health`、`/livez`、`/readyz` 已在匿名白名单中，不应被拦截。检查是否自定义了 `public_paths` 覆盖了默认值。

### 4. LLM 调用失败

**原因**：未配置 LLM 环境变量。

**解决**：Skill 平台未配置 LLM 时自动回退到确定性适配器。如需 LLM 能力：

```bash
export DKWS_LLM_BASE_URL=https://api.deepseek.com
export DKWS_LLM_API_KEY=your-api-key
export DKWS_LLM_MODEL=deepseek-chat
```

### 5. Kùzu 图查询失败

**原因**：Kùzu 不可用或图未构建。

**解决**：运行 `dkws build-projection` 构建图谱投影。Kùzu 不可用时自动回退内存 BFS（fail-open）。

### 6. 工作区校验失败

**原因**：目录结构不完整或合同文件损坏。

**解决**：

```bash
.venv/bin/dkws validate --workspace W --mode full
```

查看具体错误信息，必要时用 `dkws init --force` 重建目录结构。

### 7. SQLite Runtime Store 锁定

**原因**：并发写入或前次进程异常退出。

**解决**：检查 `DKWS_RUNTIME_STORE_BUSY_TIMEOUT_MS` 设置（默认 5000ms），或删除 WAL/SHM 文件后重启。
