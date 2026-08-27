# DKWS 持久化异步 Worker 说明（M2-P2 / M2.4）

对应任务包：`M2-P2`，范围 `M2.4 持久化异步 Worker`。
依据：`ADR-012`（SQLite Runtime Store）、`ADR-015`（单节点生产 profile）、
规格 `§11.1`（任务状态机）、`§9.14/§9.15`（STATUS.md / RUN_REPORT.md 契约）、
`FR-CTL-001/002/005/006`。

> **非声明**：本文档不代表 DKWS 已生产就绪，不代表安全审计已完成，
> 不代表 GITS UAT 已通过，不代表 C′ 受控混合架构已成为正式基线。

## 1. 状态权威：路线 C′（Owner 决策）

Owner 于 2026-08-27 决策采用**路线 C′**：

| 角色 | 载体 | 说明 |
|---|---|---|
| **状态唯一权威** | SQLite `jobs` 表 | 原子领取、lease、重试、dead-letter 全在库内完成 |
| **审计投影（只读）** | `STATUS.md` / `RUN_REPORT.md` | 从 SQLite **派生**写出，保持 §9.14/§9.15 契约与 FR-CTL 审计产物要求 |

**派生方向是单向的**：`SQLite → 文件`。任何组件都不得反向以文件内容更新状态。
`JobController` 内部约定「**先同步 SQLite，再派生写文件**」，
确保任何时刻文件内容都不领先于权威表。

未注入 `runtime_store` 时，`JobController` 保持 M1 的纯文件行为（幂等靠扫描
`STATUS.md`），因此既有调用方与既有测试均不受影响。

## 2. 状态机与命名（§11.1 合规）

终态命名统一为 **`COMPLETED`**（Owner 决策 2），与 `domain/states.py` 对齐。
migration 002 会把 v1 时期可能写入的 `SUCCEEDED` 一次性归一。

```
PENDING ──► RUNNING ──► VALIDATING ──► COMPLETED
   │           │                            
   │           ├──► FAILED ──► RETRYING ──► RUNNING
   │           └──► BLOCKED ──► RUNNING
   └──► CANCELLED
```

### dead-letter 为何不用 `BLOCKED`

`states.py` 规定 `JOB_TRANSITIONS["FAILED"] = {"RETRYING"}`，
即 **`FAILED` 只允许转向 `RETRYING`**。若把 dead-letter 表达为 `BLOCKED`，
就需要 `FAILED → BLOCKED` 这条非法转换，违反 §11.1。

因此 dead-letter 采用 **`status=FAILED` + `dead_letter=1` 标记位**：
既落在合法终态上，又能被 `claim_job` 明确排除、被 `list_dead_letters` 精确检索。

## 3. Schema v2（migration 002）

只追加、不修改 001；用 `ALTER TABLE ADD COLUMN` 保证既有数据平滑升级。

| 列 | 用途 |
|---|---|
| `lease_owner` / `lease_expires_at` / `heartbeat_at` | lease 租约与心跳 |
| `max_attempts` / `next_attempt_at` | 重试额度与退避窗口 |
| `error_code` | 失败原因分类 |
| `dead_letter` / `dead_lettered_at` / `dead_letter_reason` | dead-letter 标记与溯源 |
| `idem_key` | 业务幂等键（同 `job_type` + `idem_key` 只允许一个活跃 Job） |

索引：`idx_jobs_claim`（调度扫描）、`idx_jobs_lease`（回收）、
`idx_jobs_dead_letter`（dead-letter 查询）、`idx_jobs_idem`（幂等查询）。

## 4. 原子领取

`claim_job()` 在 `BEGIN IMMEDIATE` 事务内「选中 + 占用」一次完成，
并在 `UPDATE` 的 `WHERE` 中再次校验 `status`（CAS 语义），
因此多 Worker 并发调用时**同一 Job 只会被一个 Worker 领取**。

领取条件（全部满足）：

- `status` ∈ `{PENDING, RETRYING}`
- `dead_letter = 0`
- `next_attempt_at` 为空或已到期（退避窗口已过）
- `attempts < max_attempts`（仍有尝试余额）

排序为 `COALESCE(next_attempt_at, created_at), created_at`，先到先得，避免饥饿。
并发下拿不到写锁时返回 `None`（属正常竞争），由调用方下一轮重试。

## 5. lease 租约与崩溃恢复

### 5.1 机制

领取时获得带过期时间的 lease；执行期间由后台 daemon 线程按
`lease_seconds * 0.4` 的间隔续约。进程被 `kill -9` 后无人续约，
lease 到期即被 `reclaim_expired_leases()` 回收。

### 5.2 回收语义

| 情况 | 处置 |
|---|---|
| 仍有尝试额度 | 转 `RETRYING`，按指数退避设置 `next_attempt_at`，`error_code=LEASE_EXPIRED` |
| 额度已耗尽 | 转 `FAILED` + `dead_letter=1` |
| lease 未过期 | **不动**（多 Worker 并存时不误抢） |

回收**不重置** `attempts`，因此崩溃重试同样受 `max_attempts` 约束，不会无限重试。

### 5.3 防双写

`complete_job` / `fail_job` / `heartbeat_job` 均要求 `lease_owner` 匹配。
lease 被回收后，原持有者的写回一律返回 `None`。
Worker 侧据此抛 `LeaseLostError` 并放弃写回，交由回收机制重新调度。

这是「至少一次」语义下的关键保障：**Job 可能被执行多次，但结果只会被写回一次。**

> 因此 **Handler 应设计为可重入 / 幂等**。

### 5.4 与 `recover_stale_jobs` 的区别

| 方法 | 行为 | 适用 |
|---|---|---|
| `recover_stale_jobs()`（M2.3） | **无条件**复位所有 `RUNNING` | 单 Worker 部署的启动清理 |
| `reclaim_expired_leases()`（M2.4，推荐） | 仅回收 lease **已过期**者 | 多 Worker 并存；可在运行期周期性安全调用 |

M2.3 的方法予以保留以维持兼容，但多 Worker 场景应使用后者。

## 6. 重试与退避

退避公式：

```
delay = min(backoff_base * backoff_factor ** (attempts - 1), backoff_max)
```

默认 `base=2.0`、`factor=2.0`、`max=300.0`，即 2s → 4s → 8s → … → 封顶 300s。

不可重试错误（Handler 抛 `NonRetryableJobError`，或未注册 `job_type`）
**立即** dead-letter，不消耗剩余额度，避免无意义重试。

## 7. dead-letter 与人工干预

```bash
# 列出 dead-letter
python scripts/run_worker.py --workspace ./workspace --list-dead-letters

# 人工重放（追加额度并清除标记，状态回到 RETRYING）
python scripts/run_worker.py --workspace ./workspace --requeue JOB-SKILL-20260827-0001
```

`requeue_dead_letter()` 走 `FAILED → RETRYING` 这条 §11.1 合法转换。

## 8. Worker 配置

| 环境变量 | 默认 | 说明 |
|---|---|---|
| `DKWS_WORKER_ID` | 自动生成 | 形如 `主机名-PID-随机后缀`（PID 可能复用，故加随机后缀） |
| `DKWS_WORKER_JOB_TYPES` | 空（不限） | 逗号分隔的业务类型 |
| `DKWS_WORKER_LEASE_SECONDS` | `30` | lease 租约时长 |
| `DKWS_WORKER_POLL_INTERVAL` | `1.0` | 空闲轮询间隔 |
| `DKWS_WORKER_RECLAIM_INTERVAL` | `5.0` | lease 回收扫描间隔 |
| `DKWS_WORKER_MAX_JOBS` | `0`（不限） | 处理指定数量后退出 |
| `DKWS_WORKER_BACKOFF_BASE` | `2.0` | 退避基数 |
| `DKWS_WORKER_BACKOFF_FACTOR` | `2.0` | 退避因子 |
| `DKWS_WORKER_BACKOFF_MAX` | `300.0` | 退避上限 |

命令行参数优先于环境变量。

### lease 时长选择

需大于「单个 Job 的最长执行时间 ÷ 心跳可容忍的连续失败次数」。
过短会导致正常执行被误回收；过长会延后崩溃恢复。
心跳间隔为 lease 的 40%，即单个 lease 周期内有约 2 次续约机会。

## 9. 优雅停机

收到 `SIGTERM` / `SIGINT` 后：**不再领取新 Job**，等待当前 Job 执行完毕后退出。
不会中断正在执行的 Handler，也不会留下悬挂 lease。

## 10. 使用示例

```bash
# 启动 Worker
python scripts/run_worker.py --workspace ./workspace

# 仅处理指定类型，自定义 lease
python scripts/run_worker.py --workspace ./workspace \
    --job-types SKILL,INGEST --lease-seconds 60

# 查看队列概览
python scripts/run_worker.py --workspace ./workspace --stats
```

### 异步 Skill 执行

`SkillExecutionService.execute_async()` 有两种模式：

| 模式 | 触发条件 | 行为 |
|---|---|---|
| **持久化（推荐）** | 注入 `runtime_store` | 仅入队，由独立 Worker 进程领取；**进程崩溃不丢任务** |
| 线程（M1 兼容） | 未注入 Store | 后台线程立即执行；**进程退出即丢任务**，仅适用开发环境 |

## 11. 不引入的依赖

依 ADR-015 单机单实例，**不引入** Celery / RQ / Redis / RabbitMQ / Kafka /
Kubernetes Job。队列语义全部由 SQLite 事务实现。

## 12. 已知限制与遗留项

| 项 | 说明 |
|---|---|
| 单机单实例 | 多实例可并存 Worker（lease 已支持），但 SQLite 需在同一文件系统；跨主机需另行设计 |
| 至少一次语义 | 崩溃可能导致 Job 被执行多次，Handler 须可重入；**不提供 exactly-once** |
| 无优先级队列 | 当前 FIFO；如需优先级需追加 migration 与索引 |
| 无 cron / 定时触发 | `available_at` 支持一次性延迟，但无周期调度 |
| Handler 注册集中在入口脚本 | `register_handlers()` 为唯一注册点，便于审计；业务 Handler 需在此登记 |
| 可观测性 | 仅进程内 `WorkerStats` 与日志；`/metrics` 属 **M2.5（M2-P3）** 范围 |
