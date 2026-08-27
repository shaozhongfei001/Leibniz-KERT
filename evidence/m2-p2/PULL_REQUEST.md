# PR: feat(m2-p2) 持久化异步 Worker（lease / 重试退避 / dead-letter / 崩溃恢复）

- **源分支**：`feature/m2-p2-persistent-worker`
- **目标分支**：`develop`
- **任务包**：`M2-P2`，范围 `M2.4 持久化异步 Worker`
- **基线**：`develop` @ `8d20235`（M2-P1 已合入）
- **提交**：`42dd56f`（功能）、`e7411c1`（PR 描述）、`+1`（Owner 决策补充）
- **创建链接**：https://github.com/shaozhongfei001/Leibniz-KERT/compare/develop...feature/m2-p2-persistent-worker?expand=1

---

## 一、目标

为 DKWS Python Core 建立**生产级异步任务可靠性**：Job 状态持久化、原子领取、
lease 租约、重试退避、dead-letter，以及**进程崩溃后的完整恢复**。

## 二、Owner 决策落实

| # | Owner 决策 | 落实 |
|---|---|---|
| 1 | **路线 C′**：SQLite 为状态唯一权威，`STATUS.md` 派生只读 | 已实现，见第三节 |
| 2 | 终态命名统一 `COMPLETED` | migration 002 归一 `SUCCEEDED`；同步更新 3 处测试断言 |
| 3 | 先本地 merge M2-P1 到 `develop`，再从 `develop` 起分支 | `develop` @ `8d20235`（`--no-ff`）已推送；本分支自 `develop` 创建 |

### 关于路线 C′ —— 为何不是字面路线 C

评审时我曾提示：字面路线 C（状态迁到 SQLite、**不再写** `STATUS.md`）会使
`tests/recovery/test_recovery.py:60-63`（直接断言 `STATUS.md` 内容）失败，
与「不降低现有测试门禁」冲突。C′ 通过**派生写出**同时满足两者：

- SQLite 成为单一数据源，无双写歧义 —— 路线 C 的实质达成
- `STATUS.md` 内容正确且与库一致 —— 既有测试不破，FR-CTL 审计产物保留

`JobController` 约定「**先同步 SQLite，再派生写文件**」，保证文件内容任何时刻
都不领先于权威表；派生方向单向 `SQLite → 文件`，禁止反向以文件更新状态。

## 三、实现要点

### 3.1 Schema v2（migration 002，只追加不改 001）

- `ALTER TABLE` 加 10 列：lease 三列、重试三列、dead-letter 三列、`idem_key`
- 4 个索引：`idx_jobs_claim` / `idx_jobs_lease` / `idx_jobs_dead_letter` / `idx_jobs_idem`
- 终态归一：`UPDATE jobs SET status='COMPLETED' WHERE status='SUCCEEDED'`
- **未新增任何表**（`CREATE TABLE` 计数 = 0），知识权威源仍是 `03_core` 文件资产

### 3.2 原子领取

`claim_job()` 在 `BEGIN IMMEDIATE` 事务内「选中 + 占用」一次完成，
`UPDATE` 的 `WHERE` 再次校验 `status` 构成 CAS。
**多 Worker 并发下同一 Job 只会被投递一次**（8 线程 30 Job 实测无重复）。

排序 `COALESCE(next_attempt_at, created_at), created_at`，先到先得避免饥饿。

### 3.3 lease 租约与崩溃恢复

- 后台 daemon 线程按 `lease_seconds * 0.4` 续约（单周期内约 2 次机会）
- `kill -9` 后无人续约，lease 到期由 `reclaim_expired_leases()` 回收
- **回收不重置 `attempts`**，崩溃重试同样受 `max_attempts` 约束，不会无限重试
- 只回收 lease **已过期**者，多 Worker 并存时不误抢正常执行中的 Job

**防双写**：`complete_job` / `fail_job` / `heartbeat_job` 均要求 `lease_owner` 匹配。
lease 被回收后原持有者写回一律返回 `None`。
即「至少一次」语义下 **Job 可能执行多次，但结果只写回一次**。

> ⚠️ 因此 **Handler 必须可重入 / 幂等**，已写入文档与 docstring。

### 3.4 重试与 dead-letter

- 指数退避 `min(base * factor^(n-1), max)`，默认 `2 / 2 / 300`
- `NonRetryableJobError` 与未注册 `job_type` **立即** dead-letter，不消耗额度
- 支持 `--list-dead-letters` 查看、`--requeue` 人工重放

### 3.5 为何 dead-letter 不用 `BLOCKED`（请重点评审）

`domain/states.py` 规定 `JOB_TRANSITIONS["FAILED"] = {"RETRYING"}`，
即 `FAILED` **只允许**转向 `RETRYING`。若用 `BLOCKED` 表达 dead-letter，
需要 `FAILED → BLOCKED` 这条**非法转换**，违反 §11.1。

故采用 `status=FAILED` + `dead_letter=1` 标记位。
`requeue_dead_letter` 走 `FAILED → RETRYING` 合法转换。
测试 `test_dead_letter_never_uses_blocked` 与端到端检查 13 均设立断言防漂移。

### 3.6 Worker 运行时与入口

- Handler 注册、轮询、周期性 reclaim、`SIGTERM`/`SIGINT` 优雅停机
- `scripts/run_worker.py` 含 `--stats` / `--list-dead-letters` / `--requeue` 运维子命令
- `execute_async` 增加**持久化入队模式**（注入 Store 时仅入队，交 Worker 执行）

> 补充说明：原 `execute_async` 用裸 `threading.Thread` 执行，**进程崩溃即丢任务**，
> 正是 M2.4 要解决的问题。现注入 Store 后走持久化路径；未注入时保留线程模式作 M1 兼容。

## 四、测试与验证

| 命令 | 结果 | 退出码 |
|---|---|---|
| `python -m pytest tests -v` | **481 passed** / 0 failed / 0 skipped | 0 |
| `python -m pytest tests/unit -v` | 177 passed | 0 |
| `python -m pytest tests/integration -v` | 196 passed | 0 |
| `python -m pytest tests/security -v` | 36 passed | 0 |
| `python -m pytest tests/recovery -v` | 18 passed | 0 |
| `python scripts/verify_m2p2_worker.py` | **27/27 → PASS** | 0 |
| `ruff check <新增 7 文件>` | All checks passed | 0 |

**门禁未降低**：356（`develop` 基线）→ **481**，新增 125 个测试函数。
既有测试**零修改零删除**，仅按 Owner 决策统一 3 处 `SUCCEEDED` → `COMPLETED` 断言。

`jobs.py` / `skills.py` 的存量 ruff 告警数**改动前后完全一致**（10 / 11 处），
已用 `git stash` 对比确认非本次引入。

### 崩溃恢复端到端（M2.4 验收核心）

真实子进程持有 lease → `kill -9`（退出码 -9）→ lease 未释放 →
到期回收 → 新 Worker 接手 → `COMPLETED`，`attempts=2` 未重置。

另含：SIGTERM 优雅停机（执行中 Job 仍完成、无悬挂 lease）、
额度耗尽 dead-letter、人工重放恢复、退避序列 `[2,4,8]` 与封顶 `[2,4,8,10,10]`、
8 线程并发无重复投递、3 个运维子命令。

**未新增任何第三方依赖**（仅 stdlib `sqlite3`/`threading`/`signal`/`socket`/`uuid`），
`pyproject.toml` 未改动。

## 五、约束遵守自查

| 约束 | 状态 |
|---|---|
| 不引入 PostgreSQL / Redis / 外部 MQ / Kubernetes | 遵守（亦未引入 Celery / RQ，队列语义全由 SQLite 事务实现） |
| 不把 SQLite 变成知识权威源 | 遵守（migration 002 未新增表；`test_store_holds_no_knowledge_tables` 精确断言表清单） |
| 不修改 GITS | 遵守 |
| 不修改 Java Runtime 生产边界 | 遵守（`poc/` 零改动） |
| 不降低现有测试门禁 | 遵守（356 → 461） |
| 不直接 push main / 不自行 merge | 遵守（M2-P1 的本地 merge 系 Owner 显式授权的例外） |

## 六、变更文件

**新增源码**：`src/dkws/infrastructure/worker.py`

**修改源码**：`runtime_store.py`（migration 002 + 13 个新方法）、
`application/jobs.py`（C′ 改造）、`application/skills.py`（持久化入队）

**新增测试**：`tests/unit/test_job_queue.py`(45)、`tests/unit/test_worker.py`(27)、
`tests/recovery/test_worker_crash_recovery.py`(14)、
`tests/integration/test_persistent_jobs.py`(19)

**修改测试**（Owner 授权的命名统一）：`test_runtime_store.py`(2)、
`test_runtime_store_api.py`(1)

**新增文档/工具**：`docs/architecture/DKWS_PERSISTENT_WORKER_M2P2.md`、
`scripts/run_worker.py`、`scripts/verify_m2p2_worker.py`、`evidence/m2-p2/**`

## 七、Owner 审核结论与合并前待办（已全部完成）

Owner 于 2026-08-27 审核：**APPROVE WITH CONDITIONS**，三项合并前待办已全部落实。

| # | Owner 结论 | 落实 |
|---|---|---|
| 1 | Handler 幂等性作为明确边界，**不阻塞** M2-P2；后续接入其余 8 个服务时须逐一声明幂等性并补「重复执行无副作用」测试 | 已在 `register_handlers()` docstring 标注幂等性评审要求；本次仅 `SKILL` 接入 |
| 2 | `recover_stale_jobs` **标记 deprecated 但保留兼容**，不删除、不改行为 | 已加 `.. deprecated:: M2.4` 与误抢风险说明 |
| 3 | 生产 profile **必须强制启用 Runtime Store**，否则拒绝异步执行，禁止回退 threading；须在合并前补充 | 已实现并补测 |

### 决策 3 实现细节（安全/可靠性要求）

`SkillExecutionService` 新增 `profile` 参数。`profile=prod` 且未启用 Store 时：

```
ServiceNotReadyError: 生产 profile 下异步执行必须启用 Runtime Store：
线程模式在进程崩溃时会丢任务。请设置 DKWS_RUNTIME_STORE_ENABLED=true
并启动 Worker（scripts/run_worker.py），或改用同步执行。
```

- HTTP **503 `SERVICE_NOT_READY`**，`retryable=true`（启用 Store 后即恢复）
- `details` 含 `profile` / `runtime_store_enabled` / `remediation`，便于运维定位
- **拒绝时不创建任何 Job**，确认未回退 threading（端到端检查 24 专门验证）
- profile 比较**忽略大小写与空白**，防配置笔误绕过校验
- **同步执行不受约束**（不依赖 Worker，无丢任务风险）
- profile 来源：构造参数优先，缺省读 `DKWS_PROFILE`（默认 `dev`）；
  `create_app()` 自动传入 `cfg.profile`

附带改动：`app.state` 暴露 `skill_service`，用于运维自检与校验链路测试
（对 M2-P3 可观测性亦有价值）。

### 补充后指标

| 项 | 补充前 | 补充后 |
|---|---|---|
| 全量测试 | 461 passed | **481 passed** |
| 端到端检查 | 22/22 | **27/27** |
| 新增测试函数 | 105 | **125** |

## 八、遗留项

| 项 | 归属 |
|---|---|
| 至少一次语义（不提供 exactly-once） | 设计取舍，已文档化 |
| 其余 8 个应用服务接入 Worker（须先过幂等性评审） | 后续，依 Owner 决策 1 |
| 无优先级队列（当前 FIFO） | 后续 |
| 无 cron / 周期调度（`available_at` 仅支持一次性延迟） | 后续 |
| 可观测性（无 `/metrics`，仅进程内 `WorkerStats` 与日志） | **M2-P3 = M2.5**（Owner 已确认，分支 `feature/m2-p3-observability`） |
| 跨主机多实例（需共享同一 SQLite 文件） | 依 ADR-015，暂不支持 |

## 九、非声明

- 本次**不**代表 DKWS 已生产就绪。
- 本次**不**代表 GITS UAT 已通过。
- 本次**不**代表安全审计已完成。
- 本次**不**代表 C′ 受控混合架构已成为正式基线。
- Feature Pilot **不**代替 Owner、Tech Lead 或 Independent QA 签署。
