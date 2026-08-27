# DKWS 混合部署与运维设计 V1.0（候选）

> 状态：CANDIDATE
> 日期：2026-08-26
> 工作流：DKWS-C-MIXED-ARCH-REMEDIATION-01

## 1. 进程拓扑

```text
DKWS 产品
├── Python Core :8106
├── Java Skill Runtime :18080（内部，仅 loopback/内网）
├── Sandbox Runner（bwrap 子进程）
└── Worker（Python 异步任务）
```

## 2. 网络与 TLS 边界

> 依据：ADR-013、ADR-015；Tech Lead 于 M2-P1 评审确认（2026-08-27）。
> 实现细节见 `DKWS_RUNTIME_HARDENING_M2P1.md`。

### 2.1 TLS 终止位置

**TLS 由外层反向代理（Nginx/网关）终止，DKWS 应用层不实现 TLS。**

```text
外部调用方（GITS 等）
   │  HTTPS
   ▼
Nginx / 网关  ← TLS 终止、证书管理、可选 mTLS
   │  HTTP（回环或内网）
   ▼
Python Core :8106  ← 唯一公共入口；API Key 认证、限流、大小/并发限制
   │  HTTP（仅 loopback/内网）
   ▼
Java Skill Runtime :18080  ← 内部可替换执行器，不对外
```

### 2.2 监听地址要求

| 组件 | 监听地址 | 说明 |
|---|---|---|
| Nginx / 网关 | `0.0.0.0:443` | 唯一对外暴露的端口 |
| Python Core | `127.0.0.1:8106` 或内网地址 | **不得**直接暴露到公网 |
| Java Skill Runtime | `127.0.0.1:18080` | 仅 loopback/内网，不对外 |
| Worker | 无监听端口 | — |

Python Core 的 `DKWS_BIND_HOST` 参与生产 profile 校验：
若绑定非回环地址且未启用 API Key 认证，**启动即被拒绝**（fail-fast）。

> 注意：`scripts/serve_skill_service.py` 的 `--host` 默认为 `0.0.0.0`（沿用既有行为）。
> 生产部署**必须**显式传入 `--host 127.0.0.1`，或确保防火墙/安全组只放通网关来源。

### 2.3 代理头信任策略

**当前默认不信任 `X-Forwarded-For`**，限流分桶键取连接对端 IP。

理由：若无条件信任该头，调用方可伪造其值获得无限分桶，从而绕过限流。
代价：当 DKWS 部署在反向代理之后时，所有请求的对端 IP 均为代理地址，
按 IP 分桶会退化为全局共享配额。

缓解：为已认证请求按 API Key 分桶（优先级高于 IP），故正常调用方不受此退化影响；
仅匿名/未认证流量共享按代理 IP 的配额——这对 DoS 防护而言是可接受的保守行为。

未来如需按真实客户端 IP 分桶，需引入显式配置（如 `DKWS_TRUSTED_PROXY`
或可信代理 IP 列表）后方可信任该头。**此项当前未实现。**

### 2.4 代理侧建议配置

反向代理应承担以下职责，避免与应用层重复或冲突：

- 终止 TLS，仅放通 TLS 1.2+
- 转发至 `127.0.0.1:8106`，保留 `X-API-Key` 请求头
- 代理层大小限制不小于应用层 `DKWS_MAX_REQUEST_BYTES`，避免应用层 413 被代理层提前遮蔽
- 可选 mTLS 校验调用方证书（应用层不实现，属网关职责）
- 不要剥离或改写认证请求头

## 3. 部署顺序

1. 启动 Python Core
2. 启动 Java Skill Runtime
3. Python Core readiness 检查 Java Runtime 可用性
4. 启动 Worker

## 4. 故障降级

| 故障 | 行为 |
|---|---|
| Java Runtime 不可达 | 依赖 Java Runtime 的 Skill fail-closed；知识只读能力继续 |
| Sandbox 不可用 | 工具类 Skill fail-closed |
| 模型不可用 | 按 Skill 策略返回 DEGRADED 或 fail-closed |
| Python Core 不可用 | 全部不可用 |
| 反向代理不可达 | 外部全部不可用；Python Core 仍可经回环自检 |

## 5. 资源预算

- Python Core：建议 1-2 CPU / 2-4GB
- Java Runtime：建议 1-2 CPU / 2-4GB JVM heap
- Sandbox 并发：建议 2-4
- 单机总预算：4-8 CPU / 8-16GB（待 Owner 批准）

## 6. 可观测

> M2.5 已落地，实现细节见 `DKWS_OBSERVABILITY_M2P3.md`。

- 统一 JSON 日志字段：requestId, traceId, tenantId, skillId
  （`DKWS_STRUCTURED_LOGS=true` 启用，生产默认开启）
- W3C Trace Context 贯通（沿用上游 `traceparent`，畸形值拒绝并新建 trace）
- Metrics：HTTP（计数/延迟直方图/4xx/5xx）、Job 队列深度、就绪状态、构建信息
- 告警：Java Runtime down、Sandbox 失败率、磁盘、JVM heap

### 6.1 探针端点

| 端点 | 用途 | 语义 |
|---|---|---|
| `/livez` | 存活 | **不检查依赖**；失败通常触发重启 |
| `/readyz` | 就绪 | 检查工作区与 Runtime Store；未就绪返回 **503**，摘除实例但**不重启** |
| `/metrics` | 指标 | Prometheus `text/plain; version=0.0.4` |
| `/v1/health` | 兼容 | 既有端点，附 `runtime` 加固状态 |

三者均在限流豁免与匿名白名单中（`/metrics` 除外，其鉴权由
`DKWS_METRICS_REQUIRE_ADMIN` 单一决定）。

### 6.2 采集侧要求

- **`/metrics` 需保护**：指标含队列深度、DB schema 版本等内部信息。
  生产须设 `DKWS_METRICS_REQUIRE_ADMIN=true`，或由网络层限制采集来源。
- **路径标签为路由模板**（如 `/v1/evidence/{object_id}`），已内建高基数防护。
- **Worker 进程无 HTTP 端口**，其统计不经 `/metrics` 暴露；
  跨进程聚合需 textfile collector 或 pushgateway（当前未实现）。

## 7. 发布与版本

- 一个发布 manifest，包含 Python/Java/契约/Skill hash
- 两套构建，一个发布 Gate
- 双 SBOM
- 升级顺序：先 Java Runtime，再 Python Core，或按兼容矩阵

## 8. 备份

> M2.6 已落地，实现见 `src/dkws/infrastructure/backup.py`，
> 运维入口 `scripts/dkws_ops.py`。演练报告见 `evidence/m2-p5/`。

- 备份 Python Runtime Store、知识资产、受控 Skill 包
- Java Runtime 无状态，不备份

### 8.1 备份范围

| 目录 | 是否必备 | 理由 |
|---|---|---|
| `01_raw` | **必备** | 原始批次不可重建 |
| `03_core` | **必备** | 唯一知识权威源（ADR-012） |
| `90_control` | **必备** | 治理与审计不可重建 |
| `02_work` | 默认纳入 | 看似可重建，但 `04_serve` 数据集重建依赖其 parquet 中间产物 |
| `04_serve` | 默认纳入 | 重建耗时计入 RTO |
| `90_control/locks` | **排除** | 锁含 pid/host，恢复后必然失效 |
| `90_control/runtime` | **排除文件拷贝** | DB 单独走 SQLite 在线备份 API |

### 8.2 硬性约束

1. **备份产物必须落工作区外**：落入会触发 `WS_BAD_FILENAME`，
   破坏 `check_workspace` 一致性检查。工具会在构造期拒绝。
2. **Runtime DB 必须用在线备份 API**：WAL 模式下直接拷贝 `.db` 会与
   `-wal`/`-shm` 不一致。
3. **必须捕获一致性点**：同时记录 `CURRENT.md` 指针、`03_core` 版本清单、
   DB schema 版本，使恢复后可验证「知识版本 ↔ 运行态」是否匹配。

### 8.3 操作

```bash
# 备份（目标必须在工作区之外）
python scripts/dkws_ops.py backup --workspace ./workspace --dest /var/backups/dkws

# 校验完整性（逐文件 sha256）
python scripts/dkws_ops.py verify --backup /var/backups/dkws/backup-<ts>
```

### 8.4 待 Owner 决策

**RPO / RTO 目标、备份频率、保留策略、演练频率均未设定**——
工具不内置业务默认值。需运维侧在调度层（cron / systemd timer）配置。

## 9. 恢复

```bash
# 恢复（演练建议恢复到新目录，勿直接覆盖生产）
python scripts/dkws_ops.py restore \
    --backup /var/backups/dkws/backup-<ts> --target /srv/dkws-restored
```

恢复流程内建以下动作：

1. **先校验后恢复**（默认）：损坏备份被拒绝，避免用坏备份覆盖现场造成二次灾难；
2. **清理残留锁**：否则后续写操作会被无主锁永久阻塞；
3. **补齐空目录**：`rglob` 不捕获空目录，而目录结构是 `check_workspace` 的依据；
4. **一致性校验**：比对恢复后与备份时的一致性点，不匹配则显式报告；
5. **结构检查**：运行 `check_workspace(full)`，存在 BLOCKER 时返回非零退出码。

恢复**不会**重置 Job 的 `attempts`、不会清除 `dead_letter` 标记——
这些是 M2.4 语义，受 `tests/recovery` 锁定。

## 10. 回滚

- 保留上一版本发布 manifest
- 回滚顺序：Python Core → Java Runtime → Skill 版本

### 10.1 发布清单

```bash
# 生成（含 git commit 锚点、4 套版本号汇总、6 个组件哈希）
python scripts/dkws_ops.py manifest --out /srv/releases/RELEASE_MANIFEST.json

# 升级/回滚前比对差异
python scripts/dkws_ops.py compare --left old.json --right new.json
```

清单含 `fingerprint`（由 git commit 与组件哈希派生），
可判断「两次部署是否为同一份代码 + 同一份契约」。

**工作区脏状态会被检出**：存在未提交变更时清单标注「不应用于生产」，
命令返回退出码 2（可用 `--allow-dirty` 放行）。

### 10.2 已知限制

| 项 | 说明 |
|---|---|
| 回滚动作仍需人工 | 工具提供差异识别，不自动执行回滚 |
| 版本号未统一 | 代码中并存 4 套版本，清单只记录不统一 |
| 无异地/加密备份 | 备份为本地明文 |
| 无增量备份 | 全量拷贝，大数据量下窗口与成本待评估 |
