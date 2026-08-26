# M2-P1 证据清单

任务包：`M2-P1`（M2.1 认证与安全边界、M2.2 限流与大小限制、M2.3 SQLite Runtime Store）
分支：`feature/m2-p1-python-core-hardening`
生成时间：2026-08-27

> **非声明**
> - 本次不代表 DKWS 已生产就绪。
> - 本次不代表 GITS UAT 已通过。
> - 本次不代表安全审计已完成。
> - 本次不代表 C′ 架构已成为正式基线。
> - Feature Pilot 不代替 Owner、Tech Lead 或 Independent QA 签署。

## 1. 环境版本

| 项 | 值 |
|---|---|
| Python | 3.12.8（`.venv`，由 `install_binary` 安装于 `~/.workbuddy/binaries/python/versions/3.12.8`） |
| 平台 | Linux |
| 依赖安装 | `pip install -e ".[api,dev]"` + `httpx>=0.27`（TestClient 依赖） |
| 新增第三方依赖 | **无**（仅使用 stdlib `sqlite3`/`hashlib`/`hmac`/`asyncio` 与已有 FastAPI/Starlette） |

> 说明：系统默认 Python 为 3.10，低于 `pyproject.toml` 要求的 `>=3.11`，
> 故本地创建 3.12.8 虚拟环境。`.venv` 已在 `.gitignore` 中，不进入提交。

## 2. 测试命令与结果

| 命令 | 结果 | 退出码 | 日志 |
|---|---|---|---|
| `python -m pytest tests -q` | 全部通过 | 0 | `logs/10_pytest_all.log` |
| `python -m pytest tests/unit -q` | 105 项通过 | 0 | `logs/11_pytest_unit.log` |
| `python -m pytest tests/integration -q` | 157 项通过 | 0 | `logs/11_pytest_integration.log` |
| `python -m pytest tests/security -q` | 36 项通过 | 0 | `logs/11_pytest_security.log` |
| `python scripts/verify_m2p1_hardening.py` | 20/20 检查通过 | 0 | `e2e_hardening_report.json` + `logs/0*.log` |

### 2.1 门禁未降低

| 项 | 基线（`main`） | 本次（feature 分支） |
|---|---|---|
| 全量测试通过数 | 246 | 356 |
| 失败/跳过 | 0 / 0 | 0 / 0 |
| 新增测试 | — | **110**（107 个测试函数，其中 1 个参数化展开为 4 项） |

基线数据取自本分支创建前在 `main` 上执行的同一命令。既有测试**零修改、零删除**。

### 2.2 新增测试分布

| 文件 | 测试函数 | 收集项 | 覆盖内容 |
|---|---|---|---|
| `tests/unit/test_runtime_config.py` | 22 | 22 | 配置装载优先级、密钥摘要化、弱密钥拒绝、生产 fail-fast、作用域解析 |
| `tests/unit/test_runtime_store.py` | 36 | 39 | migration 幂等、WAL、目录边界（参数化 4 项）、幂等记录 TTL/冲突、Job 生命周期、审计、备份、并发写 |
| `tests/security/test_api_hardening.py` | 30 | 30 | 401/403/413/429 全路径、白名单、Bearer、密钥不回显、限流分桶与补充、并发饱和 |
| `tests/integration/test_runtime_store_api.py` | 19 | 19 | Store 装配、幂等跨重启复放、审计双写、Job 恢复、表清单边界断言 |
| **合计** | **107** | **110** | — |

### 2.3 静态检查

```
ruff check src/dkws/api/middleware.py src/dkws/infrastructure/runtime_config.py \
           src/dkws/infrastructure/runtime_store.py \
           tests/unit/test_runtime_config.py tests/unit/test_runtime_store.py \
           tests/security/test_api_hardening.py tests/integration/test_runtime_store_api.py
→ All checks passed!
```

范围限定为本次新增文件；仓库存量文件的 ruff 告警未在本任务包范围内处理。

## 3. 端到端验证（真实 uvicorn 进程 + 真实 HTTP）

脚本：`scripts/verify_m2p1_hardening.py`，报告：`e2e_hardening_report.json`。
20/20 全部通过：

| # | 检查项 | 观测结果 |
|---|---|---|
| 1 | `prod_profile_fail_fast` | 退出码 1，输出"拒绝启动"并列明缺失项 |
| 2 | `prod_profile_starts_with_full_config` | 配置齐备时正常就绪 |
| 3 | `health_public_without_key` | `GET /v1/health` → 200（匿名探针可用） |
| 4 | `missing_key_401` | 401 `UNAUTHENTICATED`，`WWW-Authenticate: ApiKey realm="dkws", header="X-API-Key"` |
| 5 | `wrong_key_401` | 401，响应体不回显密钥 |
| 6 | `valid_key_accepted` | 通过认证（非 401/403） |
| 7 | `non_admin_scope_403` | 普通密钥访问闸门审计 → 403 `FORBIDDEN` |
| 8 | `admin_scope_allowed` | admin 密钥 → 200 |
| 9 | `oversize_request_413` | 4KB 请求体（上限 2048）→ 413 `PAYLOAD_TOO_LARGE` |
| 10 | `rate_limit_429` | burst=3 时第 3 次 → 429，`Retry-After: 1` |
| 11 | `skill_execute_succeeds` | `POST /api/skill/execute` → 200 |
| 12 | `health_reports_hardening` | 五项开关均 true，`schema_version=1`，`warnings=[]` |
| 13 | `store_under_control_dir` | 数据库落在 `90_control/runtime/runtime.db` |
| 14 | `wal_enabled` | `journal_mode=wal` |
| 15 | `schema_version_recorded` | `schema_version=1` |
| 16 | `no_knowledge_tables` | 表清单恰为 5 张运行态表，无任何知识内容表 |
| 17 | `idempotency_persisted` | 幂等记录落库，`scope=skill_execute` |
| 18 | `gate_audit_persisted` | 闸门审计落库，`decision=APPROVED` |
| 19 | `gate_audit_jsonl_kept` | JSONL 审计留痕仍在写入 |
| 20 | `restart_idempotency_replay` | **重启后**同 `requestId` → 200 且 trace 含 `idempotency` 阶段 |

### 3.1 原始日志

| 文件 | 内容 |
|---|---|
| `logs/01_fail_fast.log` | 生产 profile 拒绝启动的完整输出与退出码 |
| `logs/02_service.log` | 服务进程 stdout/stderr（含 uvicorn 访问日志） |
| `logs/03_store_dump.json` | SQLite 表清单、schema 版本、journal 模式、行数 |
| `logs/04_restart.log` | 重启进程日志（验证幂等复放） |

## 4. 变更文件清单

### 4.1 新增（源码）

| 文件 | 说明 |
|---|---|
| `src/dkws/infrastructure/runtime_config.py` | 运行时配置：profile、认证、限流、大小、并发、Store；含生产 fail-fast 校验 |
| `src/dkws/api/middleware.py` | 四个中间件：大小限制、并发限制、限流、API Key 认证 |
| `src/dkws/infrastructure/runtime_store.py` | SQLite Runtime Store：migration、WAL、幂等、Job、审计、备份 |

### 4.2 修改（源码）

| 文件 | 变更 |
|---|---|
| `src/dkws/domain/errors.py` | 新增 5 个异常与 4 个错误码（401/403/429/413），既有码未改动 |
| `src/dkws/api/server.py` | `create_app` 接受 `runtime_config`、装配中间件与 Store、health 回报加固状态、evidence 端点写审计 |
| `src/dkws/application/skills.py` | `SkillExecutionService` 接受 `runtime_store`，幂等双层（内存 + 持久化）、闸门审计双写 |
| `scripts/serve_skill_service.py` | 启动前配置校验、生产 fail-fast、dev 模式显式告警 |

### 4.3 新增（测试）

- `tests/unit/test_runtime_config.py`
- `tests/unit/test_runtime_store.py`
- `tests/security/test_api_hardening.py`
- `tests/integration/test_runtime_store_api.py`

### 4.4 新增（文档/配置/工具）

- `docs/architecture/DKWS_RUNTIME_HARDENING_M2P1.md` —— 运行加固说明
- `examples/config/runtime.prod.example.json` —— 生产 profile 配置示例（密钥用 digest）
- `scripts/verify_m2p1_hardening.py` —— 端到端加固验证脚本
- `evidence/m2-p1/**` —— 本证据集

## 5. 约束遵守自查

| 约束 | 状态 | 说明 |
|---|---|---|
| 不引入 PostgreSQL | 遵守 | 仅 stdlib `sqlite3` |
| 不引入 Redis | 遵守 | 限流为进程内令牌桶（ADR-015 单机单实例） |
| 不引入外部 MQ | 遵守 | 无消息中间件 |
| 不引入 Kubernetes | 遵守 | 无编排配置变更 |
| 不把 SQLite 变成知识权威源 | 遵守 | 仅 5 张运行态表；集成测试对表清单做精确断言；路径落 `01_raw`/`02_work`/`03_core`/`04_serve` 时构造期抛错 |
| 不修改 GITS | 遵守 | 变更全部位于本仓库 |
| 不修改 Java Runtime 生产边界 | 遵守 | `poc/` 下 Java 代码零改动 |
| 不降低现有测试门禁 | 遵守 | 246 → 356，既有测试零修改 |
| 不直接 push main | 遵守 | 工作于 `feature/m2-p1-python-core-hardening` |
| 不自行 merge | 遵守 | 提交 PR 至 `develop`，待评审 |

## 6. 默认值与兼容性

所有加固能力默认状态经过刻意选择，保证 **dev 环境行为与 M1 完全一致**：

| 能力 | dev 默认 | 说明 |
|---|---|---|
| 认证 | 关闭（配置密钥后自动开启） | 现有本地流程无需改动 |
| 限流 | 关闭 | 避免影响本地压测 |
| 并发限制 | 关闭 | — |
| 请求体大小限制 | **开启**（1MB） | 唯一默认开启项，属基础防护 |
| Runtime Store | 关闭 | 未启用时幂等行为与 M1 相同（纯内存） |

## 7. 已知限制与遗留项

| 项 | 说明 | 归属 |
|---|---|---|
| Job 原子领取 / lease / dead-letter | 本次仅实现状态复位（`recover_stale_jobs`） | M2.4 |
| 分布式限流 | 当前进程内计数，多实例不共享 | 需 Owner 明确是否多实例 |
| TLS / mTLS | 由可信网关负责，未在应用层实现 | 待 Tech Lead 定部署形态 |
| API Key 轮换自动化 | 支持 `active` 标记与多密钥并存，但无自动轮换 | 后续 |
| `X-Forwarded-For` 信任链 | **有意不信任**该头，避免伪造分桶键绕过限流；若部署在反向代理后需 Owner 确认可信代理配置 | 需 Owner 决策 |
| 响应体大小限制的流式响应 | 会缓冲后校验，超大流式响应存在内存占用 | 当前无流式端点，后续如引入需改造 |
