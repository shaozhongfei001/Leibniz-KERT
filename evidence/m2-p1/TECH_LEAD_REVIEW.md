# M2-P1 Tech Lead 评审结论与决策台账

- **任务包**：`M2-P1`（M2.1 认证与安全边界、M2.2 限流与大小限制、M2.3 SQLite Runtime Store）
- **分支**：`feature/m2-p1-python-core-hardening`
- **评审日期**：2026-08-27
- **结论**：**验收通过（有条件）**

> **非声明**
> - 本次不代表 DKWS 已生产就绪。
> - 本次不代表 GITS UAT 已通过。
> - 本次不代表安全审计已完成。
> - 本次不代表 C′ 架构已成为正式基线。
> - Tech Lead 验收不代替 Owner 或 Independent QA 签署。
> - Feature Pilot 不代替 Owner、Tech Lead 或 Independent QA 签署。

## 一、独立核验记录（由 Tech Lead 执行）

| 项 | 方式 | 结果 |
|---|---|---|
| 端到端加固验证 | 本地可写仓库检出分支后运行 `scripts/verify_m2p1_hardening.py` | **20/20 通过 → PASS** |
| 全量测试 | 运行全量 pytest | 全部通过，退出码 0 |
| 代码审查 | `runtime_config.py`、`middleware.py`、`runtime_store.py`、`server.py`、`skills.py`、测试与证据 | 通过 |

### 确认达成的目标

- API Key 认证 + 401/403
- 限流 + 429
- 大小限制 + 413
- SQLite Runtime Store + WAL + migration
- 幂等持久化 + 重启复放
- Gate/Evidence 审计落库
- 生产 profile fail-fast
- 未引入 PostgreSQL / Redis / MQ / K8s
- 未把 SQLite 变成知识权威源
- 未修改 GITS

## 二、四项待决策事项：Tech Lead 结论

| # | 事项 | 结论 | 是否阻塞合并 | 本次代码改动 |
|---|---|---|---|---|
| 1 | `X-Forwarded-For` 信任策略 | **保持现状：默认不信任**，直接使用连接对端 IP，避免伪造分桶键绕过限流 | 不阻塞 | 无 |
| 2 | 多实例部署 | **保持单机单实例设计**，进程内限流，不引入 Redis（符合 ADR-015） | 不阻塞 | 无 |
| 3 | TLS / mTLS 终止位置 | **由可信网关终止 TLS，应用层不实现**；须在部署文档中明确 | 不阻塞 | 仅文档（见第三节） |
| 4 | 密钥下发与轮换流程 | 代码层已支持多密钥 / `active` 吊销 / 作用域；**运维流程列为独立任务**，待 Owner/运维侧确认 | 不阻塞 | 无 |

### 决策 1 展开：`X-Forwarded-For`

Tech Lead 认定当前实现「正确且安全」。后续如部署在可信反向代理之后，
再引入显式配置（如 `DKWS_TRUSTED_PROXY=true` 或可信代理 IP 列表）。
**本次不实现该配置项。**

### 决策 2 展开：多实例

当前进程内令牌桶符合 ADR-015 单机单实例约定。
未来若确需多实例，共享配额方案另行单独设计。

### 决策 3 展开：TLS 边界（**唯一产生本次改动的决策**）

Tech Lead 要求：「需要在部署文档中明确：TLS 由 Nginx/网关负责，DKWS 只监听内网/回环。」

核验发现：`docs/adr/ADR-015-single-node-production-profile.md` 与
`docs/architecture/DKWS_HYBRID_DEPLOYMENT_AND_OPERATIONS_V1.0_CANDIDATE.md`
**此前均无任何 TLS / 反向代理 / 监听地址表述**。

该缺口同时对应 WBS `M2.1` 中明确列出但此前未落地的条目「TLS 反向代理边界」，
属 M2-P1 的真实文档漏项，已于本次补齐。

### 决策 4 展开：密钥流程

代码侧已具备的能力：多密钥并存、`active` 吊销标记、作用域（`read`/`execute`/`admin`）、
仅摘要驻留内存、配置文件可直接写 `digest` 从而不落明文。

仍需运维侧补充（**不属本任务包**）：密钥生成规范、下发渠道、轮换周期、吊销流程、审计要求。

## 三、依据评审结论所做的改动

严格限定在决策 3 明确要求的文档范围，**未改动任何源码、测试或既有行为**。

| 文件 | 变更 |
|---|---|
| `docs/architecture/DKWS_HYBRID_DEPLOYMENT_AND_OPERATIONS_V1.0_CANDIDATE.md` | 新增「2. 网络与 TLS 边界」章节；后续章节编号顺延（原 2~8 → 3~9）；故障降级表补充「反向代理不可达」一行 |
| `evidence/m2-p1/TECH_LEAD_REVIEW.md` | 本文件（决策台账） |

新增章节内容要点：

- **2.1 TLS 终止位置**：明确 TLS 由 Nginx/网关终止，应用层不实现；给出调用链拓扑图
- **2.2 监听地址要求**：逐组件列出监听地址；指出 `serve_skill_service.py` 的 `--host`
  默认为 `0.0.0.0`，生产部署必须显式传 `127.0.0.1` 或以防火墙约束来源
- **2.3 代理头信任策略**：记录决策 1 的结论、理由、代价与缓解方式，
  并明确「未来如需信任该头，须引入显式配置，当前未实现」
- **2.4 代理侧建议配置**：代理层大小限制不小于应用层上限（避免 413 被提前遮蔽）、
  保留 `X-API-Key` 头、可选 mTLS 属网关职责

### 回归确认

文档改动不涉及代码路径，全量测试与端到端验证结论继续有效：

| 项 | 结果 |
|---|---|
| 全量 pytest | 356 passed / 0 failed / 0 skipped，退出码 0 |
| 端到端验证 | 20/20 → PASS，退出码 0 |

## 四、当前阻塞项

| 阻塞项 | 原因 | 处置 |
|---|---|---|
| PR 尚未在 GitHub 创建 | `gh` CLI 未认证；已复核 `GITHUB_TOKEN` / `GH_TOKEN` / `GITHUB_PAT` 均未设置，且无 `~/.config/gh` 配置 | GitHub 凭据属仓库外凭据，Feature Pilot 不自行获取或配置，留待人工一步完成 |

**人工创建 PR**：

- 链接：https://github.com/shaozhongfei001/Leibniz-KERT/compare/develop...feature/m2-p1-python-core-hardening?expand=1
- 描述：直接使用 `evidence/m2-p1/PULL_REQUEST.md`
- 目标分支 `develop` 已存在于远程，可用

## 五、后续步骤（按 Tech Lead 建议）

| # | 步骤 | 责任方 | 状态 |
|---|---|---|---|
| 1 | 确认上述 4 项决策 | Owner / Tech Lead | Tech Lead 已给出建议，待 Owner 确认 |
| 2 | 人工创建 PR 并合并到 `develop` | 人工 | 待执行（Feature Pilot 不自行 merge） |
| 3 | 合并后标记 M2-P1 完成 | Tech Lead | 待执行 |
| 4 | 领取下一任务包 M2-P2 | Feature Pilot | 待授权（范围候选见下） |

### M2-P2 范围候选（依 WBS）

| 编号 | 名称 | WBS 要求 | 验收标准 |
|---|---|---|---|
| M2.4 | 持久化异步 Worker | 原子领取、lease、重试、dead-letter | 崩溃恢复测试通过 |
| M2.5 | 可观测性 | 结构化日志；`/livez`、`/readyz`、`/metrics`；OpenTelemetry 基础 | 指标与日志可采集 |

M2-P1 已为 M2.4 铺好基础：`jobs` 表（含 `attempts`、`status`、`payload`、`result`）、
migration 机制（只追加）、`recover_stale_jobs()` 状态复位。
M2.4 需在此之上补齐原子领取、lease 租约、重试退避与 dead-letter。

**等待 Owner/Tech Lead 明确 M2-P2 范围后再启动，不自行开工。**
