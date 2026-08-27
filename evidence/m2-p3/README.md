# M2-P3 证据清单

- **任务包**：`M2-P3`
- **范围**：`M2.5 可观测性`（结构化日志 / `/livez` / `/readyz` / `/metrics` / OTel 基础）
- **分支**：`feature/m2-remaining`（基线 `develop` @ `4b28a7d`）
- **生成时间**：2026-08-27

> **非声明**
> - 本次不代表 DKWS 已生产就绪。
> - 本次不代表 GITS UAT 已通过。
> - 本次不代表安全审计已完成。
> - 本次不代表 C′ 受控混合架构已成为正式基线。
> - Tech Lead 自验不代替 Owner 或 Independent QA 签署。

## 1. 验收标准对照

Owner 验收标准：**指标与日志可采集，`/livez`、`/readyz`、`/metrics` 可用且有自动化测试。**

| 标准 | 实现 | 证据 |
|---|---|---|
| 结构化日志 | 单行 JSON + 请求上下文自动注入 + 三层脱敏 | E2E 检查 19-23；`test_observability.py` 日志组 |
| `/livez` | 不检查依赖的存活探针 | E2E 检查 2；`TestLiveness` 6 项 |
| `/readyz` | 工作区/Store 硬性 + 投影/队列 degraded，未就绪 503 | E2E 检查 3；`TestReadiness` 11 项 |
| `/metrics` | Prometheus 文本格式，14 个指标 | E2E 检查 4-11；`TestMetricsEndpoint` 15 项 |
| OpenTelemetry 基础 | W3C Trace Context 贯通 + 可选 OTel 桥接（缺失自动降级） | E2E 检查 12-15；`TestTraceContext` 9 项 |
| 日志与指标可采集 | 自研 Prometheus 解析器实测可消费 | E2E 检查 5「metrics_parseable_by_collector」 |
| 自动化测试 | 103 个测试函数（收集 121 项） | `logs/pytest_*.log` |

## 2. 环境版本

| 项 | 值 |
|---|---|
| Python | 3.12.8（`.venv`） |
| 平台 | Linux |
| **新增第三方依赖** | **无**（Prometheus 格式与 JSON 日志均自研） |
| `pyproject.toml` | **未改动** |
| 可选增强（未安装，已降级） | `prometheus_client`、`opentelemetry` |

> 刻意不引入 `prometheus_client`/`opentelemetry` 作为必需依赖：
> 单机单实例（ADR-015）指标规模小，自研可完全掌控格式，
> 且避免为可观测性引入新的供应链面与故障面。

## 3. 测试命令与结果

| 命令 | 结果 | 退出码 | 日志 |
|---|---|---|---|
| `python -m pytest tests -v` | **602 passed** / 0 failed / 0 skipped | 0 | `logs/pytest_all.log` |
| `python -m pytest tests/unit -v` | 254 passed | 0 | `logs/pytest_unit.log` |
| `python -m pytest tests/integration -v` | 240 passed | 0 | `logs/pytest_integration.log` |
| `python -m pytest tests/security -v` | 36 passed | 0 | `logs/pytest_security.log` |
| `python -m pytest tests/recovery -v` | 18 passed | 0 | `logs/pytest_recovery.log` |
| `python scripts/verify_m2p3_observability.py` | **25/25 → PASS** | 0 | `e2e_observability_report.json` |
| `ruff check <新增/改动文件>` | All checks passed | 0 | — |

### 3.1 门禁未降低

| 项 | M2-P2 基线（`develop` @ `4b28a7d`） | 本次 |
|---|---|---|
| 全量测试通过数 | 481 | **602** |
| 失败 / 跳过 | 0 / 0 | 0 / 0 |
| 新增测试 | — | **121**（103 个函数，含参数化展开） |

### 3.2 新增测试分布

| 文件 | 函数数 | 覆盖内容 |
|---|---|---|
| `tests/unit/test_observability.py` | 60 | ID 生成、traceparent 解析（含 7 种畸形输入）、请求上下文（含线程隔离）、JSON 日志（字段顺序/脱敏/异常）、指标注册表（含并发安全/标签转义/类型冲突）、追踪（采样/上限/降级）、正文脱敏（7 种密钥形态 + 5 种正常内容不误伤） |
| `tests/integration/test_observability_endpoints.py` | 43 | 三端点语义、限流豁免、匿名白名单、指标内容与高基数防护、admin 鉴权、trace 贯通、`/v1/health` 兼容 |

## 4. E2E 验收（真实 uvicorn 进程）

脚本 `scripts/verify_m2p3_observability.py`，**25/25 全部通过**：

| # | 检查项 | 观测结果 |
|---|---|---|
| 1 | `server_starts` | 服务就绪，结构化日志已启用 |
| 2 | `livez_available` | `GET /livez` → 200，`status=alive` |
| 3 | `readyz_available` | `GET /readyz` → 200，4 个检查项齐备 |
| 4 | `metrics_available` | `content-type=text/plain; version=0.0.4; charset=utf-8` |
| 5 | `metrics_parseable_by_collector` | **自研解析器成功消费**：10 个指标名、8 个 TYPE 声明 |
| 6 | `metrics_http_requests_labeled` | 含 method/path/status 标签 |
| 7 | `metrics_latency_histogram` | `_bucket`/`_count`/`_sum` 三件套齐备 |
| 8 | `metrics_histogram_type_declared` | `TYPE ... histogram` |
| 9 | `metrics_no_high_cardinality` | **路径标签为 `{object_id}` 模板，未泄漏具体 ID** |
| 10 | `metrics_queue_gauges` | claimable / dead_letter / expired_leases |
| 11 | `metrics_build_info` | 构建信息与运行时长 |
| 12 | `trace_headers_returned` | `X-Request-Id` + `traceparent` 回传 |
| 13 | `trace_request_id_preserved` | 沿用调用方 ID |
| 14 | `trace_continues_upstream` | 沿用上游 trace_id，生成新 span_id |
| 15 | `trace_rejects_malformed` | 畸形 traceparent 被拒并新建 trace |
| 16 | `rejected_requests_observable` | **401 请求同样有指标与日志（无盲区）** |
| 17 | `probes_exempt_from_rate_limit` | burst=3 下连续 6 次 `/livez` 全 200 |
| 18 | `metrics_exempt_from_rate_limit` | 连续 5 次 `/metrics` 全 200 |
| 19 | `logs_are_single_line_json` | 捕获 28 条单行 JSON |
| 20 | `logs_have_access_events` | 事件码 `HTTP_ACCESS` |
| 21 | `logs_have_correlation_fields` | `request_id` + `trace_id` + `duration_ms` |
| 22 | `logs_have_service_field` | `service=dkws-python-core` |
| 23 | `logs_do_not_leak_api_keys` | **日志中无任何 API Key 明文** |
| 24 | `prod_profile_probes_public` | 生产 profile 匿名访问三端点：`{200, 200, 200}` |
| 25 | `prod_profile_business_still_protected` | 业务端点仍 401 |

### 原始日志

| 文件 | 内容 |
|---|---|
| `logs/01_dev_server.log` | dev profile 真实服务 stdout（JSON 日志原始输出） |
| `logs/02_prod_server.log` | prod profile 服务 stdout |
| `logs/pytest_*.log` | 全量 + 四套件测试日志（含命令、时间、Python 版本、退出码） |

## 5. 关键设计决策及其依据

### 5.1 `/livez` 不检查依赖

存活探针失败通常触发**重启**。若把依赖故障计入存活，依赖抖动时会导致
无谓地重启本服务，反而放大故障。依赖健康归 `/readyz`（返回 503 摘除实例，
但不重启进程）。

### 5.2 知识投影不作就绪硬性条件

全新部署尚未发布投影时，若判为未就绪，实例将**永远无法进入服务状态**；
且只读能力（健康、目录）此时仍可用。故降级为 `degraded` 标记。

> 此判断是在 Loop 中修正的：初版把投影列为硬性条件，导致 6 个测试失败；
> 排查后确认 `ws` fixture 只做 `init_workspace`（不含投影），
> 进而认定「空工作区应算就绪」才是正确语义。

### 5.3 路径标签使用路由模板（高基数防护）

若直接用原始路径，每个 `object_id`/`job_id` 都会产生新时间序列，
足以把指标存储打爆。故取 Starlette 的 `route.path` 模板。

### 5.4 dead-letter 之外的新发现：消息正文脱敏缺口

排查测试失败时确认：`_sanitize_message` **仅折叠空白与截断，不做内容脱敏**；
字段级脱敏也只看**键名**。M2.5 新增 stdout 通道后，形如 `token=abc123` 的
正文成为**新的泄漏面**，故新增 `redact_message()` 收口，覆盖：

- `键=值` / `键: 值`（含 `Bearer` 前缀吞并）
- 裸密钥字面量（`sk-`/`ghp_`/`xoxb-` 等）
- 无键名的 `bearer <token>`

同时以 5 种正常内容（`count=42`、`path=/v1/health` 等）验证**不误伤**，
避免脱敏过度损害可诊断性。

### 5.5 身份跨中间件层传递

`BaseHTTPMiddleware` 为**每层**中间件构造独立的 `Request`，
故仅写 `request.state` 无法传到路由函数。改为同时写 **ASGI `scope` 字典**
（整个请求生命周期共享）。

> 此缺陷在 Loop 中发现：`/metrics` 的 admin 鉴权始终返回 403，
> 即使密钥作用域正确。M2-P1 的 `requires_admin` 因在中间件内判定而未暴露此问题。

### 5.6 `/metrics` 鉴权由单一开关决定

认证中间件对 `/metrics` 放行（但仍尽力识别身份），鉴权交由
`metrics_require_admin` 决定。理由：若按普通端点强制 401，该开关将
**永无机会生效**（语义矛盾）；且采集器通常无法携带密钥。

## 6. 变更文件清单

### 6.1 新增（源码）

| 文件 | 行数 | 说明 |
|---|---|---|
| `src/dkws/infrastructure/observability.py` | 559 | 请求上下文、JSON 日志、正文脱敏、指标注册表、追踪 |

### 6.2 修改（源码）

| 文件 | 变更 |
|---|---|
| `src/dkws/infrastructure/runtime_config.py` | 新增 `ObservabilityConfig`（10 字段）与 `_env_float`；`DEFAULT_PUBLIC_PATHS` 加入 `/livez`+`/readyz`；新增 `DEFAULT_EXEMPT_PATHS`；采样率范围校验 |
| `src/dkws/api/middleware.py` | 新增 `ObservabilityMiddleware`；`_publish_identity()` 经 ASGI scope 传递身份；限流豁免改用 `DEFAULT_EXEMPT_PATHS`（原为硬编码 2 个路径）；`/metrics` 鉴权交由端点 |
| `src/dkws/api/server.py` | 新增 `/livez`、`/readyz`、`/metrics`；`create_app` 装配日志/注册表/追踪器并暴露 `app.state`；**`recover_stale_jobs` → `reclaim_expired_leases`**（修正 M2.4 遗留）；evidence 审计的静默 `try-pass` 补上日志与指标 |

### 6.3 新增（测试）

- `tests/unit/test_observability.py`（60 函数）
- `tests/integration/test_observability_endpoints.py`（43 函数）

### 6.4 修改（测试）

- `tests/integration/test_runtime_store_api.py`：`test_stale_running_jobs_recovered_on_startup`
  拆为 `test_expired_lease_jobs_reclaimed_on_startup` 与
  `test_live_lease_jobs_not_touched_on_startup`，反映 M2.4 的 lease 感知语义

### 6.5 新增（文档 / 工具）

- `docs/architecture/DKWS_OBSERVABILITY_M2P3.md`
- `scripts/verify_m2p3_observability.py`
- `evidence/m2-p3/**`

### 6.6 修改（文档）

- `docs/architecture/DKWS_HYBRID_DEPLOYMENT_AND_OPERATIONS_V1.0_CANDIDATE.md`
  §6 可观测性落地化（探针语义表、采集侧要求、Worker 无端点说明）

## 7. 顺带修复的既有问题

| 问题 | 位置 | 处置 |
|---|---|---|
| `create_app` 仍调用已 deprecated 的 `recover_stale_jobs`，会误抢 Worker 正在处理的 Job | `server.py` | 改为 `reclaim_expired_leases`，并补 2 个针对性测试 |
| evidence 审计失败静默 `try-pass`（无日志无指标） | `server.py` | 补 `EVIDENCE_AUDIT_FAILED` 日志与错误计数指标 |
| 限流豁免路径硬编码，新增探针不会自动豁免 | `middleware.py` | 抽为 `DEFAULT_EXEMPT_PATHS` 常量 |
| 日志正文中的密钥不脱敏 | `observability.py` | 新增 `redact_message()`（见 5.4） |

## 8. 约束遵守自查

| 约束 | 状态 | 说明 |
|---|---|---|
| 不引入 PostgreSQL / Redis / 外部 MQ / Kubernetes | 遵守 | 且未引入 `prometheus_client`/`opentelemetry` 作必需依赖 |
| 不把 SQLite 变成知识权威源 | 遵守 | 本次未触碰 Store schema |
| 不修改 GITS | 遵守 | 变更全在本仓库 |
| 不修改 Java Runtime 生产边界 | 遵守 | `poc/` 零改动 |
| 不降低现有测试门禁 | 遵守 | 481 → 602 |
| 不改动 §9.20 文件日志契约 | 遵守 | stdout JSON 为**新增**通道，`JobLogger` 未改 |
| 不直接 push main | 遵守 | 工作于 `feature/m2-remaining` |

## 9. 已知限制与遗留项

| 项 | 说明 | 归属 |
|---|---|---|
| 指标为进程内，重启归零 | counter 归零由 Prometheus `rate()` 自然处理 | 设计取舍 |
| 无 OTLP 导出器 | 内置追踪不做网络导出 | 后续 |
| Worker 进程无 `/metrics` | Worker 无 HTTP 端口，跨进程聚合需 textfile collector | 后续 |
| 无日志采样/限流 | 高 QPS 下访问日志量大，依赖采集侧限流 | 后续 |
| `tenant_id` 已定义未接线 | 多租户尚未落地 | M3+ |
| 脱敏为正则启发式 | 无法覆盖全部密钥形态；系统性方案属 M2.9 数据分类与脱敏 | **M2-P4** |
