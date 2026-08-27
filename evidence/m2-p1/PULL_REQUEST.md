# PR: feat(m2-p1) Python Core 生产加固（认证 / 限流 / SQLite Runtime Store）

- **源分支**：`feature/m2-p1-python-core-hardening`
- **目标分支**：`develop`
- **任务包**：`M2-P1`（M2.1 + M2.2 + M2.3）
- **提交**：`4dbbff3`（功能）、`22bc5e2`（PR 描述）、`3c72edc`（Tech Lead 评审结论与 TLS 边界文档）
- **创建链接**：https://github.com/shaozhongfei001/Leibniz-KERT/compare/develop...feature/m2-p1-python-core-hardening?expand=1

> **Tech Lead 评审状态**：已于 2026-08-27 独立核验并**验收通过（有条件）**。
> 端到端 20/20 PASS、全量测试退出码 0、代码审查通过。
> 四项待决策事项均获结论且**均不阻塞合并**，详见 `evidence/m2-p1/TECH_LEAD_REVIEW.md`。

---

## 一、目标

为 DKWS Python Core（C′ 架构中唯一公共入口）建立生产加固基础能力，覆盖
认证与安全边界、流量与体积控制、运行态持久化三块。

## 二、范围与实现

### M2.1 认证与安全边界（ADR-013 / ADR-015）

- 新增 `src/dkws/infrastructure/runtime_config.py`：集中承载 profile(`dev`/`prod`)、
  认证、限流、大小、并发、Runtime Store 配置。
  来源优先级：**默认值 < 配置文件(`DKWS_CONFIG_FILE`) < 环境变量(`DKWS_*`) < 构造参数**。
- **凭据处理**：API Key 仅以 SHA-256 摘要驻留内存；配置文件可直接写 `digest`
  从而完全不落明文；比较使用 `hmac.compare_digest`（常量时间）；
  密钥短于 16 字符直接拒绝启动；错误响应与日志不回显密钥，仅用非机密 `key_id`。
- 支持 `key_id` / `scopes`(`read`|`execute`|`admin`) / `active` 吊销标记，多密钥并存以便轮换。
- 认证中间件：401 `UNAUTHENTICATED`（附 `WWW-Authenticate`）、403 `FORBIDDEN`；
  健康检查为白名单（探针无需凭据）；兼容 `Authorization: Bearer <key>`。
- **生产 profile fail-fast**：缺认证 / 缺有效密钥 / 缺限流 / 缺请求体限制，
  或对外监听却未启用认证 → 抛 `ConfigError`，启动脚本以非零码退出。
  dev 模式未启用认证时打印显式告警。

### M2.2 限流与大小限制

- 令牌桶限流：按 API Key 优先、否则客户端 IP 分桶；429 `RATE_LIMITED` + `Retry-After`；
  健康检查豁免；进程内计数（单机单实例，ADR-015，**不引入 Redis**）。
- **中间件顺序**：`大小限制 → 并发限制 → 限流 → 认证 → 路由`。
  限流刻意置于认证**之前**，以拦截"用无效密钥反复消耗认证开销"的洪水；
  为仍能按 Key 分桶，限流中间件自行做一次轻量密钥识别（只取 `key_id`，
  不做作用域判定，不代替认证决策）。
- 请求体大小：优先 `Content-Length` 预检；无该头（chunked）时**流式累计校验，
  超限即中断**，不把超大 body 读入内存。响应体同样受限。均返回 413 `PAYLOAD_TOO_LARGE`。
- `asyncio.Semaphore` 并发上限，饱和返回 429 `CONCURRENCY_LIMITED`。
- 所有错误响应与既有领域错误同构：`{"error":{"code","message","retryable"}}`。

### M2.3 SQLite Runtime Store（ADR-012）

- 新增 `src/dkws/infrastructure/runtime_store.py`：
  WAL + `synchronous=NORMAL` + `busy_timeout`；每操作独立连接 + 进程内写锁。
- `schema_version` 表 + 顺序 `MIGRATIONS`（**只可追加，不可修改已发布项**），
  启动自动应用未执行的 migration，重复执行幂等。
- 5 张运行态表：`schema_version` / `idempotency_records` / `jobs` /
  `evidence_audit` / `gate_audit`。
- 幂等记录含 `request_hash` 冲突检测（同键不同内容 → `IdempotencyConflictError`）
  与 TTL，写入时顺带清理过期行防止无界增长。
- Skill 执行幂等改为**内存快路径 + 持久层**，进程重启后可按 `requestId` 复放。
- 闸门审计双写（JSONL + Store）；evidence 端点记录访问溯源。
- 启动时 `recover_stale_jobs()` 将残留 `RUNNING` 复位 `PENDING`。
- `backup_to()` 使用 SQLite 在线备份 API 生成一致性快照。

## 三、权威边界（关键，请重点评审）

| 约束 | 落实方式 |
|---|---|
| SQLite **不是**知识权威源 | 仅 5 张运行态表；知识权威源仍是 `03_core` 文件资产 |
| 不保存知识内容本体 | 集成测试对表清单做**精确相等断言**，防止后续漂移 |
| 不落入知识数据目录 | 路径命中 `01_raw`/`02_work`/`03_core`/`04_serve` 时**构造期抛 `ConflictError`** |
| Gate 业务权威在 GITS | Store 与 JSONL 均标注为审计镜像，非业务权威 |

## 四、向后兼容

默认值经刻意选择，**dev 环境行为与 M1 完全一致**：

| 能力 | dev 默认 | 说明 |
|---|---|---|
| 认证 | 关闭（配置密钥后自动开启） | 现有本地流程零改动 |
| 限流 | 关闭 | 不影响本地压测 |
| 并发限制 | 关闭 | — |
| 请求体大小限制 | **开启（1MB）** | 唯一默认开启项，属基础防护 |
| Runtime Store | 关闭 | 未启用时幂等行为与 M1 相同（纯内存） |

`create_app()` 新增的 `runtime_config` 参数为可选，缺省从环境装载；既有调用点无需改动。

## 五、测试与验证

| 命令 | 结果 | 退出码 |
|---|---|---|
| `python -m pytest tests -q` | 356 项全绿 | 0 |
| `python -m pytest tests/unit -q` | 105 项通过 | 0 |
| `python -m pytest tests/integration -q` | 157 项通过 | 0 |
| `python -m pytest tests/security -q` | 36 项通过 | 0 |
| `python scripts/verify_m2p1_hardening.py` | **20/20** 检查通过 | 0 |
| `ruff check <本次新增文件>` | All checks passed | 0 |

- **门禁未降低**：全量 246（基线 `main`）→ 356，失败/跳过均为 0，**既有测试零修改零删除**。
- 新增 107 个测试函数（收集 110 项）。
- 端到端验证启动**真实 uvicorn 进程**发起**真实 HTTP 请求**，逐项确认
  fail-fast、401、403、413、429（含 `Retry-After`）、WAL、`schema_version`、
  幂等落库、审计落库、**重启后幂等复放**。
- 证据（含原始日志、退出码、环境版本、变更清单）：`evidence/m2-p1/`。

开发环境说明：系统默认 Python 3.10 低于 `pyproject.toml` 要求的 `>=3.11`，
本地使用 3.12.8 虚拟环境（`.venv` 已 gitignore）。
**未新增任何第三方依赖**（仅用 stdlib `sqlite3`/`hashlib`/`hmac`/`asyncio`
与已有 FastAPI/Starlette），故 `pyproject.toml` 无需改动。

## 六、约束遵守自查

| 约束 | 状态 |
|---|---|
| 不引入 PostgreSQL / Redis / 外部 MQ / Kubernetes | 遵守 |
| 不把 SQLite 变成知识权威源 | 遵守（见第三节） |
| 不修改 GITS | 遵守（变更全在本仓库） |
| 不修改 Java Runtime 生产边界 | 遵守（`poc/` 零改动） |
| 不降低现有测试门禁 | 遵守（246 → 356） |
| 不直接 push main / 不自行 merge | 遵守（feature 分支 + PR 待评审） |

## 七、变更文件

**新增源码**：`infrastructure/runtime_config.py`、`api/middleware.py`、
`infrastructure/runtime_store.py`

**修改源码**：`domain/errors.py`（新增 5 异常 + 4 错误码，既有码未动）、
`api/server.py`、`application/skills.py`、`scripts/serve_skill_service.py`

**新增测试**：`tests/unit/test_runtime_config.py`、`tests/unit/test_runtime_store.py`、
`tests/security/test_api_hardening.py`、`tests/integration/test_runtime_store_api.py`

**新增文档/工具**：`docs/architecture/DKWS_RUNTIME_HARDENING_M2P1.md`、
`examples/config/runtime.prod.example.json`、`scripts/verify_m2p1_hardening.py`、
`evidence/m2-p1/**`（含 `TECH_LEAD_REVIEW.md` 决策台账）

**修改文档**：`docs/architecture/DKWS_HYBRID_DEPLOYMENT_AND_OPERATIONS_V1.0_CANDIDATE.md`
（新增「2. 网络与 TLS 边界」，落实 Tech Lead 决策 3）

**其他**：`.gitignore` 增加 `!evidence/**/*.log` 例外（证据日志需入库，
原 `*.log` 规则会将其排除）

## 八、四项决策事项（Tech Lead 已给出结论）

以下四项经 Tech Lead 评审确认，**均不阻塞本 PR 合并**：

| # | 事项 | 结论 | 本 PR 代码改动 |
|---|---|---|---|
| 1 | `X-Forwarded-For` 信任策略 | 保持现状：默认不信任，用连接对端 IP，避免伪造分桶键绕过限流（认定为「正确且安全」） | 无 |
| 2 | 多实例部署 | 维持单机单实例，进程内限流，不引入 Redis（符合 ADR-015） | 无 |
| 3 | TLS / mTLS 终止位置 | 由可信网关终止，应用层不实现；**须在部署文档中明确** | 仅文档，见下 |
| 4 | 密钥下发与轮换流程 | 代码层已支持多密钥/`active` 吊销/作用域；运维流程列为**独立任务** | 无 |

决策 3 落地（提交 `3c72edc`）：核验发现 ADR-015 与混合部署运维文档此前
**均无任何 TLS/反向代理/监听地址表述**，该缺口同时对应 WBS `M2.1` 中
已列但未落地的条目「TLS 反向代理边界」，属真实漏项，本次补齐：

- `docs/architecture/DKWS_HYBRID_DEPLOYMENT_AND_OPERATIONS_V1.0_CANDIDATE.md`
  新增「2. 网络与 TLS 边界」（TLS 终止位置与调用链拓扑、逐组件监听地址要求、
  代理头信任策略的结论与理由、代理侧建议配置），后续章节编号顺延（2~8 → 3~9）
- `evidence/m2-p1/TECH_LEAD_REVIEW.md` 新增，记录核验结果与四项决策台账

其中特别提示两点运维风险：

1. `serve_skill_service.py` 的 `--host` 默认为 `0.0.0.0`（沿用既有行为），
   生产部署**必须**显式传 `--host 127.0.0.1`，或以防火墙/安全组约束来源。
2. 反向代理层的大小限制**不应小于**应用层 `DKWS_MAX_REQUEST_BYTES`，
   否则应用层 413 会被代理层提前遮蔽。

## 九、遗留项（非本任务包范围）

- Job 原子领取 / lease / dead-letter → **M2.4**（本次仅实现状态复位）
- 分布式限流 → 依决策 2，暂不实施
- `DKWS_TRUSTED_PROXY` 等可信代理配置 → 依决策 1，当前未实现
- 密钥生成规范 / 下发渠道 / 轮换周期 / 吊销流程 / 审计要求 → 依决策 4，独立运维任务
- 响应体大小限制对流式响应会先缓冲；当前无流式端点，后续引入需改造

## 十、非声明

- 本次**不**代表 DKWS 已生产就绪。
- 本次**不**代表 GITS UAT 已通过。
- 本次**不**代表安全审计已完成。
- 本次**不**代表 C′ 架构已成为正式基线。
- Tech Lead 验收**不**代替 Owner 或 Independent QA 签署。
- Feature Pilot **不**代替 Owner、Tech Lead 或 Independent QA 签署。
