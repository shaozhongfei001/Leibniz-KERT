# M2-P2 证据清单

- **任务包**：`M2-P2`
- **范围**：`M2.4 持久化异步 Worker`
- **分支**：`feature/m2-p2-persistent-worker`（基线 `develop` @ `8d20235`）
- **生成时间**：2026-08-27

> **非声明**
> - 本次不代表 DKWS 已生产就绪。
> - 本次不代表 GITS UAT 已通过。
> - 本次不代表安全审计已完成。
> - 本次不代表 C′ 受控混合架构已成为正式基线。
> - Feature Pilot 不代替 Owner、Tech Lead 或 Independent QA 签署。

## 1. Owner 决策落实情况

| # | Owner 决策 | 落实方式 |
|---|---|---|
| 1 | **路线 C′**：SQLite 为状态唯一权威，`STATUS.md` 派生只读 | `JobController` 注入 `runtime_store` 后状态经 `sync_job_state()` 先入库、再派生写文件；单向 `SQLite → 文件` |
| 2 | 终态命名统一为 `COMPLETED` | migration 002 含 `UPDATE jobs SET status='COMPLETED' WHERE status='SUCCEEDED'`；M2-P1 的 3 处 `SUCCEEDED` 测试断言同步更新 |
| 3 | 先本地 merge M2-P1 到 `develop`，再从 `develop` 起分支 | `develop` @ `8d20235`（`--no-ff`）已推送；本分支自 `develop` 创建 |

### 关于路线 C′ 的门禁保障

采用字面路线 C（彻底不写 `STATUS.md`）会使 `tests/recovery/test_recovery.py:60-63`
（直接断言 `STATUS.md` 内容）失败，构成门禁下降。C′ 通过**派生写出**规避了此冲突：

```
tests/recovery/test_recovery.py::TestRecovery::test_failed_publish_job_recorded  PASSED
```

既有测试**零修改、零删除**（除 Owner 授权的 3 处 `SUCCEEDED` → `COMPLETED` 命名统一）。

## 2. 环境版本

| 项 | 值 |
|---|---|
| Python | 3.12.8（`.venv`） |
| 平台 | Linux |
| 新增第三方依赖 | **无**（仅 stdlib `sqlite3`/`threading`/`signal`/`socket`/`uuid`） |
| `pyproject.toml` | **未改动**（无新依赖） |

## 3. 测试命令与结果

| 命令 | 结果 | 退出码 | 日志 |
|---|---|---|---|
| `python -m pytest tests -v` | **461 passed** / 0 failed / 0 skipped | 0 | `logs/pytest_all.log` |
| `python -m pytest tests/unit -v` | 177 passed | 0 | `logs/pytest_unit.log` |
| `python -m pytest tests/integration -v` | 176 passed | 0 | `logs/pytest_integration.log` |
| `python -m pytest tests/security -v` | 36 passed | 0 | `logs/pytest_security.log` |
| `python -m pytest tests/recovery -v` | 18 passed | 0 | `logs/pytest_recovery.log` |
| `python scripts/verify_m2p2_worker.py` | **22/22 检查通过 → PASS** | 0 | `e2e_worker_report.json` + `logs/0*.log` |
| `ruff check <本次新增 6 个文件>` | All checks passed | 0 | — |

### 3.1 门禁未降低

| 项 | M2-P1 基线（`develop`） | 本次 |
|---|---|---|
| 全量测试通过数 | 356 | **461** |
| 失败 / 跳过 | 0 / 0 | 0 / 0 |
| 新增测试 | — | **105** |

### 3.2 新增测试分布

| 文件 | 数量 | 覆盖内容 |
|---|---|---|
| `tests/unit/test_job_queue.py` | 45 | schema v2、v1→v2 升级归一、原子领取（含 8 线程并发无重复投递）、lease 心跳、退避序列、dead-letter、幂等键、取消、队列统计 |
| `tests/unit/test_worker.py` | 27 | Handler 路由、未注册类型、异常重试、不可重试错误、lease 续约保活、lease 失效防双写、`max_jobs`、优雅停机、环境变量配置 |
| `tests/recovery/test_worker_crash_recovery.py` | 14 | lease 回收语义、重启接续、**真实 `kill -9`**、崩溃后 dead-letter、**SIGTERM 优雅停机** |
| `tests/integration/test_persistent_jobs.py` | 19 | 状态权威在 SQLite、`STATUS.md` 派生一致性、`execute_async` 入队、Worker 接续、跨重启存活 |
| **合计** | **105** | — |

### 3.3 静态检查

```
ruff check src/dkws/infrastructure/worker.py src/dkws/infrastructure/runtime_store.py \
           scripts/run_worker.py scripts/verify_m2p2_worker.py \
           tests/unit/test_job_queue.py tests/unit/test_worker.py \
           tests/recovery/test_worker_crash_recovery.py \
           tests/integration/test_persistent_jobs.py
→ All checks passed!
```

`src/dkws/application/jobs.py` 与 `skills.py` 的既有告警数量**改动前后完全一致**
（分别 10 处、11 处，均为存量），已用 `git stash` 对比确认非本次引入。

## 4. 端到端验证（真实进程 + kill -9）

脚本 `scripts/verify_m2p2_worker.py`，报告 `e2e_worker_report.json`，**22/22 通过**：

| # | 检查项 | 观测结果 |
|---|---|---|
| 1 | `schema_version_is_2` | `schema_version=2` |
| 2 | `lease_retry_columns_present` | 新增 10 列齐备 |
| 3 | `scheduling_indexes_present` | 4 个索引已建立 |
| 4 | `crash_worker_claims_job` | 子进程领取 `J-CRASH`，`status=RUNNING owner=w-crash attempts=1` |
| 5 | `worker_killed_with_sigkill` | **`kill -9` 后退出码 = -9** |
| 6 | `lease_not_released_by_crash` | 被强杀进程无机会清理，lease 仍指向已死 Worker |
| 7 | `expired_lease_reclaimed` | 回收过期 lease 数 = 1 |
| 8 | `crashed_job_reprocessed_to_completion` | 新 Worker 接手 → `COMPLETED`，`result={'v': 42}` |
| 9 | `attempt_count_preserved_across_crash` | `attempts=2`（崩溃那次 + 恢复那次，**未重置**） |
| 10 | `first_failure_goes_retrying` | 第 1 次失败 → `RETRYING`，`next_attempt_at` 已设置 |
| 11 | `exhausted_attempts_go_dead_letter` | 额度耗尽 → `FAILED` + `dead_letter=True`，原因「重试次数耗尽（2/2）」 |
| 12 | `dead_letter_not_reclaimable` | dead-letter 不再被领取，避免无限重试 |
| 13 | `dead_letter_avoids_blocked_state` | **未使用 `BLOCKED`**（§11.1 合规，见下） |
| 14 | `dead_letter_requeue_works` | 人工重放后 → `COMPLETED` |
| 15 | `exponential_backoff_applied` | 退避序列 = `[2.0, 4.0, 8.0]` 秒 |
| 16 | `backoff_capped` | 退避序列 = `[2.0, 4.0, 8.0, 10.0, 10.0]`，上限生效 |
| 17 | `sigterm_graceful_shutdown` | 执行中收到 SIGTERM，当前 Job 仍完成 → `COMPLETED` |
| 18 | `no_dangling_lease_after_shutdown` | 优雅停机后无悬挂 lease |
| 19 | `concurrent_claim_no_duplicates` | 8 线程领取 30 个 Job：投递 30 次，去重后 30 个 |
| 20 | `cli_stats_works` | `--stats` 输出合法 JSON 队列概览 |
| 21 | `cli_list_dead_letters_works` | `--list-dead-letters` 退出码 0 |
| 22 | `cli_requeue_rejects_unknown` | 重放不存在的 Job 返回退出码 1 |

### 原始日志

| 文件 | 内容 |
|---|---|
| `logs/01_crash_worker.log` | 被 `kill -9` 的子进程输出 |
| `logs/02_graceful_worker.log` | SIGTERM 优雅停机子进程输出 |
| `logs/03_cli_stats.log` | `--stats` 输出与退出码 |
| `logs/04_cli_dead_letters.log` | `--list-dead-letters` 输出与退出码 |
| `logs/pytest_*.log` | 全量 + 四套件测试日志（含命令、时间、Python 版本、退出码） |

## 5. 关键设计决策及其依据

### 5.1 dead-letter 不使用 `BLOCKED`

`domain/states.py` 规定 `JOB_TRANSITIONS["FAILED"] = {"RETRYING"}`，
即 `FAILED` **只允许**转向 `RETRYING`。若把 dead-letter 表达为 `BLOCKED`，
需要 `FAILED → BLOCKED` 这条**非法转换**，违反 §11.1。

故采用 `status=FAILED` + `dead_letter=1` 标记位：落在合法终态上，
且能被 `claim_job` 排除、被 `list_dead_letters` 精确检索。
测试 `test_dead_letter_never_uses_blocked` 与端到端检查 13 均对此设立断言。

### 5.2 限流之外的防双写

「至少一次」语义下 Job 可能被执行多次，但**结果只会被写回一次**：
`complete_job` / `fail_job` / `heartbeat_job` 均要求 `lease_owner` 匹配，
lease 被回收后原持有者写回一律返回 `None`。

因此 **Handler 必须可重入 / 幂等**，此约束已写入文档与代码 docstring。

### 5.3 `reclaim_expired_leases` 取代 `recover_stale_jobs`

M2.3 的 `recover_stale_jobs()` **无条件**复位所有 `RUNNING`，
多 Worker 并存时会误抢正在被其它 Worker 正常处理的 Job。
M2.4 新增的 `reclaim_expired_leases()` 只回收 lease **已过期**者，
可在运行期周期性安全调用。前者保留以维持 M2.3 兼容。

## 6. 变更文件清单

### 6.1 新增（源码）

| 文件 | 说明 |
|---|---|
| `src/dkws/infrastructure/worker.py` | Worker 运行时：Handler 注册、轮询、lease 续约线程、退避重试、优雅停机、环境变量配置 |

### 6.2 修改（源码）

| 文件 | 变更 |
|---|---|
| `src/dkws/infrastructure/runtime_store.py` | migration 002；`JobRecord` 扩展 10 字段 + 2 辅助方法；新增 `claim_job` / `heartbeat_job` / `complete_job` / `fail_job` / `reclaim_expired_leases` / `list_dead_letters` / `requeue_dead_letter` / `cancel_job` / `queue_stats` / `find_job_by_idem` / `max_job_seq` / `sync_job_state` / `set_job_payload`；`create_job` 支持 `max_attempts`/`idem_key`/`available_at` |
| `src/dkws/application/jobs.py` | `JobController` 接受 `runtime_store`；幂等判定改走 SQLite（保留文件回落）；各状态变更先同步库再派生写文件 |
| `src/dkws/application/skills.py` | `execute_async` 增加持久化入队模式（注入 Store 时仅入队，交 Worker 执行）；保留线程模式 |

### 6.3 新增（测试）

- `tests/unit/test_job_queue.py`
- `tests/unit/test_worker.py`
- `tests/recovery/test_worker_crash_recovery.py`
- `tests/integration/test_persistent_jobs.py`

### 6.4 修改（测试，Owner 授权的命名统一）

- `tests/unit/test_runtime_store.py`（2 处 `SUCCEEDED` → `COMPLETED`）
- `tests/integration/test_runtime_store_api.py`（1 处同上）

### 6.5 新增（文档 / 工具）

- `docs/architecture/DKWS_PERSISTENT_WORKER_M2P2.md`
- `scripts/run_worker.py`（Worker 入口 + `--stats`/`--list-dead-letters`/`--requeue` 运维子命令）
- `scripts/verify_m2p2_worker.py`（端到端验证）
- `evidence/m2-p2/**`

## 7. 验收标准对照

| Owner 验收标准 | 实现 | 证据 |
|---|---|---|
| 原子领取 Job | `claim_job()`：`BEGIN IMMEDIATE` + CAS `WHERE status=?` | 端到端检查 19（8 线程 30 Job 无重复）；`test_concurrent_claim_no_duplicates` |
| lease 租约与心跳 | `lease_owner`/`lease_expires_at`/`heartbeat_at` + 后台续约线程 | 端到端检查 4/6/7；`test_heartbeat_keeps_lease_alive` |
| 重试退避 | 指数退避 `min(base*factor^(n-1), max)` | 端到端检查 15/16；`test_backoff_grows_exponentially` |
| dead-letter | `FAILED` + `dead_letter=1`，支持列出与人工重放 | 端到端检查 11-14；`test_dead_letter_*` |
| **崩溃恢复测试通过** | `reclaim_expired_leases()` | **端到端检查 5-9（真实 `kill -9`）**；`tests/recovery/test_worker_crash_recovery.py` 14 项 |

## 8. 约束遵守自查

| 约束 | 状态 | 说明 |
|---|---|---|
| 不引入 PostgreSQL / Redis / 外部 MQ / Kubernetes | 遵守 | 队列语义全由 SQLite 事务实现；未引入 Celery/RQ |
| 不把 SQLite 变成知识权威源 | 遵守 | migration 002 **未新增任何表**，仅为 `jobs` 加列；知识权威源仍是 `03_core` 文件资产；`test_store_holds_no_knowledge_tables` 精确断言表清单 |
| 不修改 GITS | 遵守 | 变更全在本仓库 |
| 不修改 Java Runtime 生产边界 | 遵守 | `poc/` 零改动 |
| 不降低现有测试门禁 | 遵守 | 356 → 461 |
| 不直接 push main | 遵守 | 工作于 `feature/m2-p2-persistent-worker` |
| 不自行 merge | 遵守 | 待 PR 评审（M2-P1 的本地 merge 系 Owner 显式授权的例外） |

## 9. 已知限制与遗留项

| 项 | 说明 | 归属 |
|---|---|---|
| 至少一次语义 | 崩溃可能导致 Job 执行多次，Handler 须可重入；不提供 exactly-once | 设计取舍，已文档化 |
| 单机单实例 | 多 Worker 可并存（lease 已支持），但需共享同一 SQLite 文件；跨主机需另设计 | 依 ADR-015 |
| 无优先级队列 | 当前 FIFO；如需优先级需追加 migration 与索引 | 后续 |
| 无 cron / 周期调度 | `available_at` 支持一次性延迟，无周期触发 | 后续 |
| 可观测性 | 仅进程内 `WorkerStats` 与日志，无 `/metrics` | **M2.5（M2-P3）** |
| Handler 注册点 | `scripts/run_worker.py::register_handlers()` 为唯一注册入口，当前仅接线 `SKILL` | 后续业务按需登记 |

## 10. 需 Owner / Tech Lead 确认

1. **Handler 幂等性责任边界**：至少一次语义要求业务 Handler 可重入。
   现有 9 个应用服务（ingest/extract/publish 等）若要接入 Worker，
   需逐一确认其幂等性。本次仅接线 `SKILL`，其余未接入。
2. **`recover_stale_jobs` 是否弃用**：M2.4 已提供更安全的 `reclaim_expired_leases`。
   前者保留中，是否在后续版本标记 deprecated 待定。
3. **`execute_async` 默认模式**：当前未注入 Store 时仍走线程模式（M1 兼容）。
   是否在生产 profile 下强制要求启用 Store（否则拒绝异步执行）待定。
