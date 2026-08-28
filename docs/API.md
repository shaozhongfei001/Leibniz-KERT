# DKWS API 参考文档

> 版本：0.1.0 | 源码：`src/dkws/api/server.py`、`src/dkws/cli/main.py`

本文档列出 DKWS 平台所有 HTTP API 端点和 CLI 命令，按功能分组。

---

## 目录

- [HTTP API](#http-api)
  - [健康检查与服务发现](#健康检查与服务发现)
  - [知识服务](#知识服务)
  - [Skill 执行](#skill-执行)
  - [闸门协作](#闸门协作)
  - [任务控制](#任务控制)
- [CLI 命令](#cli-命令)
  - [工作区管理](#工作区管理)
  - [数据接入](#数据接入)
  - [文档处理](#文档处理)
  - [知识抽取与审核](#知识抽取与审核)
  - [发布与投影](#发布与投影)
  - [服务查询](#服务查询)
  - [任务控制](#任务控制-1)
- [通用约定](#通用约定)

---

## HTTP API

HTTP API 基于 FastAPI 实现，为 CLI 的可选薄层。启动方式：

```bash
.venv/bin/python examples/product_demo/serve_api.py --workspace <工作区路径> --port 8100
```

### 健康检查与服务发现

#### `GET /v1/health`

健康检查端点，匿名可访问。

**响应**：

```json
{
  "status": "ok",
  "version": "0.1.0"
}
```

#### `GET /livez`

存活探针（Kubernetes 兼容），匿名可访问。

**响应**：`200 OK`

#### `GET /readyz`

就绪探针（Kubernetes 兼容），匿名可访问。当 `DKWS_READINESS_REQUIRE_STORE=true`（默认）时，Runtime Store 可连接性作为硬性就绪条件。

**响应**：`200 OK` | `503 Service Unavailable`

#### `GET /metrics`

Prometheus 格式指标（需配置 `DKWS_METRICS_ENABLED=true`）。默认不要求 admin 作用域，生产建议开启 `DKWS_METRICS_REQUIRE_ADMIN=true`。

#### `GET /v1/catalog`

服务目录，列出当前工作区所有可用服务（域 + 服务名 + 版本指针）。

**响应**：

```json
{
  "services": [
    {
      "domain": "product",
      "service": "product_entities",
      "version": "v1"
    }
  ]
}
```

---

### 知识服务

#### `POST /v1/search`

全文/向量/混合检索。

**请求体**：

```json
{
  "service": "<服务名>",
  "query": "<检索词>",
  "mode": "fulltext|vector|hybrid",
  "top_k": 10
}
```

**响应**：

```json
{
  "results": [
    {
      "id": "<片段ID>",
      "score": 0.95,
      "text": "<匹配文本>",
      "evidence_ref": "<证据引用路径>"
    }
  ]
}
```

#### `POST /v1/data/query`

结构化数据查询（Parquet 投影）。

**请求体**：

```json
{
  "service": "<服务名>",
  "filters": {"field": "value"},
  "columns": ["col1", "col2"],
  "limit": 100
}
```

**响应**：

```json
{
  "rows": [{"col1": "val1", "col2": "val2"}],
  "total": 1
}
```

#### `POST /v1/graph/query`

知识图谱查询（Kùzu Cypher 后端，自动回退内存 BFS）。

**请求体**：

```json
{
  "service": "<服务名>",
  "start": "<起始实体ID>",
  "depth": 3,
  "mode": "neighbor|closure|paths"
}
```

**响应**：

```json
{
  "nodes": [{"id": "E-001", "type": "Company", "name": "..."}],
  "edges": [{"from": "E-001", "to": "E-002", "relation": "SUPPLIES"}]
}
```

#### `POST /v1/rules/evaluate`

规则 DSL 评估。

**请求体**：

```json
{
  "service": "<服务名>",
  "rule_id": "<规则ID>",
  "facts": {"field": "value"}
}
```

**响应**：

```json
{
  "matched": true,
  "actions": ["<动作>"],
  "explanation": "<规则说明>"
}
```

#### `GET /v1/entities/{id}`

获取实体详情。

**路径参数**：`id` — 实体标识

**响应**：

```json
{
  "id": "E-001",
  "type": "Company",
  "attributes": {"name": "...", "industry": "..."},
  "evidence_ref": "<证据引用>"
}
```

#### `GET /v1/evidence/{id}`

证据溯源。

**路径参数**：`id` — 证据标识

**响应**：

```json
{
  "id": "<证据ID>",
  "source": "<原始来源>",
  "chain": [{"step": "ingest", "timestamp": "..."}, {"step": "extract", "timestamp": "..."}]
}
```

#### `POST /v1/extractions`

触发知识抽取任务。

**请求体**：

```json
{
  "domain": "product",
  "batch": "<批次ID>",
  "run_id": "<运行ID>"
}
```

**响应**：

```json
{
  "job_id": "JOB-...",
  "status": "queued"
}
```

---

### Skill 执行

#### `POST /api/skill/execute`

执行 Skill（同步或异步）。

**请求体**：

```json
{
  "skillId": "<技能ID>",
  "requestId": "<幂等键>",
  "input": { },
  "context": {
    "customerId": "CUST-CORP-0001",
    "interactionId": "...",
    "interactionContent": "...",
    "existingMemories": []
  },
  "async": false
}
```

**同步响应**（`async: false`）：

```json
{
  "skillId": "<技能ID>",
  "requestId": "<幂等键>",
  "status": "completed",
  "data": {
    "result": { },
    "ruleViolations": [],
    "model": "deterministic|<LLM模型名>",
    "assemblyTrace": [],
    "modelCalls": []
  }
}
```

**异步响应**（`async: true`）：

```json
{
  "job_id": "JOB-...",
  "status": "queued"
}
```

#### `GET /api/skill/health`

Skill 平台健康检查，匿名可访问。返回已注册 Skill 列表。

**响应**：

```json
{
  "status": "ok",
  "skills": [
    {"id": "bank-front-outreach-script", "name": "外联脚本"},
    {"id": "bank-front-meeting-script", "name": "会面脚本"}
  ]
}
```

---

### 闸门协作

#### `GET /api/skill/gates/{customerId}`

获取闸门清单资产。

**路径参数**：`customerId` — 客户标识

**响应**：

```json
{
  "customerId": "CUST-CORP-0001",
  "gates": [
    {"gate": "G0", "status": "PASS", "description": "..."},
    {"gate": "G1", "status": "PENDING", "description": "..."}
  ]
}
```

#### `POST /api/skill/gates/audit`

闸门决策镜像（追加 `90_control/audit/gates.jsonl`）。**要求 admin 作用域**。

**请求体**：

```json
{
  "customerId": "CUST-CORP-0001",
  "gate": "G1",
  "decision": "APPROVE",
  "reason": "..."
}
```

**响应**：

```json
{
  "recorded": true,
  "path": "90_control/audit/gates.jsonl"
}
```

---

### 任务控制

#### `GET /v1/jobs/{job_id}`

查询异步任务状态。

**路径参数**：`job_id` — 任务标识

**响应**：

```json
{
  "job_id": "JOB-...",
  "status": "queued|running|completed|failed",
  "result": { },
  "error": null
}
```

---

## CLI 命令

CLI 为强制接口，通过 `dkws` 命令调用。所有命令均需 `--workspace W` 指定工作区路径。

### 工作区管理

#### `dkws init`

初始化工作区目录结构（五层 + 控制目录）。

```bash
dkws init --workspace W [--force]
```

| 参数 | 说明 |
|------|------|
| `--workspace` | 工作区路径（必填） |
| `--force` | 强制重新初始化（覆盖已有结构） |

#### `dkws inspect`

查看工作区概览（目录、版本指针、过期锁）。

```bash
dkws inspect --workspace W [--output json]
```

| 参数 | 说明 |
|------|------|
| `--output` | 输出格式：`text`（默认）或 `json` |

#### `dkws validate`

工作区一致性校验。

```bash
dkws validate --workspace W --mode full
```

| 参数 | 说明 |
|------|------|
| `--mode` | 校验模式：`full`（全量） |

---

### 数据接入

#### `dkws ingest`

接入原始数据文件到 `01_raw` 层。

```bash
dkws ingest --workspace W --domain product --source f.csv --idempotency-key k
```

| 参数 | 说明 |
|------|------|
| `--domain` | 业务域（如 `product`） |
| `--source` | 源文件路径 |
| `--idempotency-key` | 幂等键（防止重复接入） |

#### `dkws process-data`

结构化数据清洗与 Parquet 投影（`01_raw` → `02_work`）。

```bash
dkws process-data --workspace W --domain product --batch B --schema product \
  --mapping-json '{"key_policy":"product_id","field_mappings":[...]}'
```

| 参数 | 说明 |
|------|------|
| `--domain` | 业务域 |
| `--batch` | 批次标识 |
| `--schema` | 数据 Schema |
| `--mapping-json` | 字段映射 JSON |

---

### 文档处理

#### `dkws parse-doc`

文档登记/规范化/稳定切片（PDF/DOCX/TXT 适配器）。

```bash
dkws parse-doc --workspace W --domain product --batch B
```

| 参数 | 说明 |
|------|------|
| `--domain` | 业务域 |
| `--batch` | 批次标识 |

---

### 知识抽取与审核

#### `dkws extract`

知识候选抽取。

```bash
dkws extract --workspace W --domain product --batch B --run-id R
```

| 参数 | 说明 |
|------|------|
| `--domain` | 业务域 |
| `--batch` | 批次标识 |
| `--run-id` | 运行标识 |

#### `dkws review`

审核消歧（候选 → 确认/拒绝）。

```bash
dkws review --workspace W --domain product --objects <候选路径> \
  --decision APPROVE --reason 说明
```

| 参数 | 说明 |
|------|------|
| `--objects` | 候选对象路径 |
| `--decision` | 审核决定：`APPROVE` / `REJECT` |
| `--reason` | 审核说明 |

---

### 发布与投影

#### `dkws publish`

发布知识到 Core 层（Release + CURRENT 指针）。

```bash
dkws publish --workspace W --domain product --run-id R
```

#### `dkws build-projection`

构建 Serve 层投影（实体/关系/声明/片段/向量/规则/数据集/图谱）。

```bash
dkws build-projection --workspace W --domain product
```

#### `dkws rollback`

回滚到指定版本。

```bash
dkws rollback --workspace W --scope product --to-version V --reason 原因
```

| 参数 | 说明 |
|------|------|
| `--scope` | 回滚范围（域） |
| `--to-version` | 目标版本 |
| `--reason` | 回滚原因 |

---

### 服务查询

#### `dkws query-data`

结构化数据查询。

```bash
dkws query-data --workspace W --service <服务名> --filters-json '{}'
```

#### `dkws search`

全文/向量/混合检索。

```bash
dkws search --workspace W --service <服务名> --query <检索词> --mode fulltext
```

#### `dkws get-entity`

获取实体详情。

```bash
dkws get-entity --workspace W --id <实体ID>
```

#### `dkws graph`

知识图谱查询（Kùzu Cypher 后端）。

```bash
dkws graph --workspace W --start <实体ID> --depth 3 --mode paths
```

| 参数 | 说明 |
|------|------|
| `--start` | 起始实体 ID |
| `--depth` | 遍历深度（上限 10） |
| `--mode` | 查询模式：`neighbor` / `closure` / `paths` |

#### `dkws evaluate-rule`

规则评估。

```bash
dkws evaluate-rule --workspace W --service <服务名> --rule-id <规则ID> --facts-json '{}'
```

#### `dkws trace`

证据溯源。

```bash
dkws trace --workspace W --id <证据ID>
```

---

### 任务控制

#### `dkws job`

查询异步任务状态。

```bash
dkws job --job-id JOB-...
```

---

## 通用约定

### 退出码

| 退出码 | 含义 |
|--------|------|
| `0` | 成功 |
| `2` | 参数/合同错误 |
| `3` | 质量门禁失败 |
| `4` | 冲突/锁 |
| `5` | 内部错误 |

### 认证

生产 profile（`DKWS_PROFILE=prod`）强制启用 API Key 认证：

- 请求头：`X-API-Key: <密钥>`（可通过 `DKWS_AUTH_HEADER` 自定义）
- 匿名白名单：`/v1/health`、`/api/skill/health`、`/livez`、`/readyz`
- Admin 作用域：闸门审计端点（`/api/skill/gates/audit`）要求 `admin` 作用域

### 限流

令牌桶限流（按 API Key 优先、否则按客户端 IP 分桶）：

- 默认：600 请求/分钟，突发 60
- 探针端点不计入限流

### 请求体大小限制

- 请求体：1 MiB（默认）
- 响应体：8 MiB（默认）
