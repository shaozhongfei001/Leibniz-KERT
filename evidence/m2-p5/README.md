# M2-P5 证据清单

- **任务包**：`M2-P5`
- **范围**：`M2.6 备份恢复与升级回滚`
- **分支**：`feature/m2-remaining`
- **生成时间**：2026-08-27

> **非声明**
> - 本次不代表 DKWS 已生产就绪。
> - **本次不代表已通过灾备演练验收**——本报告为开发侧自验，
>   生产灾备演练需在真实部署环境由运维执行并由 Owner 签署。
> - **RPO / RTO 目标属 Owner 决策**，本任务包不设定、不宣称满足任何具体指标。
> - 本次不代表安全审计已完成。
> - Tech Lead 自验不代替 Owner 或 Independent QA 签署。

## 1. 验收标准对照

WBS 验收标准：**恢复演练报告**。

| 标准 | 实现 | 证据 |
|---|---|---|
| 备份脚本 | `backup.py` + `scripts/dkws_ops.py backup` | E2E 检查 2-6 |
| 恢复演练 | 真实备份→校验→恢复→一致性校验全链路 | E2E 检查 10-17 |
| **灾难恢复** | 源工作区**完全删除**后从备份恢复 | E2E 检查 19 |
| 回滚流程 | 发布清单 + git 锚点 + 清单比对 | E2E 检查 20-25 |
| 演练报告 | `e2e_backup_restore_report.json` | 25/25 PASS |

## 2. 环境版本

| 项 | 值 |
|---|---|
| Python | 3.12.8（`.venv`） |
| 平台 | Linux 6.8.0 |
| **新增第三方依赖** | **无**（stdlib `tarfile`/`shutil`/`subprocess`/`json`） |
| `pyproject.toml` | **未改动** |

## 3. 测试命令与结果

| 命令 | 结果 | 退出码 | 日志 |
|---|---|---|---|
| `python -m pytest tests -v` | **813 passed** / 0 failed | 0 | `logs/pytest_all.log` |
| `python -m pytest tests/unit -v` | 436 passed | 0 | `logs/pytest_unit.log` |
| `python -m pytest tests/integration -v` | 269 passed | 0 | `logs/pytest_integration.log` |
| `python -m pytest tests/security -v` | 36 passed | 0 | `logs/pytest_security.log` |
| `python -m pytest tests/recovery -v` | 18 passed | 0 | `logs/pytest_recovery.log` |
| `python scripts/verify_m2p5_backup_restore.py` | **25/25 → PASS** | 0 | `e2e_backup_restore_report.json` |
| `ruff check <改动文件>` | All checks passed | 0 | — |

### 3.1 门禁未降低

| 项 | M2-P4 基线 | 本次 |
|---|---|---|
| 全量测试通过数 | 738 | **813** |
| 失败 / 跳过 | 0 / 0 | 0 / 0 |
| 新增测试 | — | **75**（`test_backup.py` 49 + `test_release.py` 26） |

## 4. E2E 演练报告（25/25 PASS）

### 4.1 备份阶段

| # | 检查项 | 观测结果 |
|---|---|---|
| 1 | `backup_rejects_dest_inside_workspace` | 目标落工作区内被拒绝 |
| 2 | `backup_created` | 9 文件 / 608 字节 / **0.018s** |
| 3 | `backup_db_uses_online_api` | `sqlite_online_backup`，schema=2 |
| 4 | `backup_captures_consistency_point` | CURRENT + core 版本 + db schema |
| 5 | `backup_excludes_stale_locks` | 失效锁被排除 |
| 6 | `backup_includes_marker` | `.dkws_workspace` 已备份 |

### 4.2 校验阶段

| # | 检查项 | 观测结果 |
|---|---|---|
| 7 | `verify_passes_on_intact` | 逐文件 sha256 比对通过 |
| 8 | `verify_detects_tampering` | 检出 `哈希不匹配：01_raw/.../part_0.csv` |
| 9 | `verify_detects_missing` | 检出文件缺失 |

### 4.3 恢复阶段

| # | 检查项 | 观测结果 |
|---|---|---|
| 10 | `restore_completed` | 10 文件 / **0.004s** |
| 11 | `restore_workspace_usable` | `is_workspace=True`，**BLOCKER=0** |
| 12 | `restore_structure_check_clean` | `check_workspace(full)` **无问题** |
| 13 | `restore_consistency_matched` | 一致性匹配，无不匹配项 |
| 14 | `restore_clears_residual_locks` | 清理残留锁 1 个 |
| 15 | `restore_preserves_m24_semantics` | COMPLETED / dead_letter / PENDING 全保持，`attempts=1` **未重置** |
| 16 | `restore_dead_letter_not_reclaimed` | dead-letter 不被误领取 |
| 17 | `restore_data_byte_identical` | 原始数据逐字节一致 |
| 18 | `restore_refuses_corrupted_backup` | 损坏备份被拒绝，避免覆盖现场 |

### 4.4 灾难恢复

| # | 检查项 | 观测结果 |
|---|---|---|
| 19 | `disaster_recovery_from_scratch` | **源工作区完全删除**后恢复：10 文件 / **0.004s**，结构与运行态均完整 |

### 4.5 升级回滚支撑

| # | 检查项 | 观测结果 |
|---|---|---|
| 20 | `release_manifest_has_git_anchor` | **git 锚点已补齐**：`commit=636b2147ac19` `branch=feature/m2-remaining` `dirty=True` |
| 21 | `release_manifest_components` | 6 组件哈希齐备 |
| 22 | `release_manifest_records_version_spread` | 如实记录 4 套版本号 |
| 23 | `release_manifest_compare_detects_diff` | 识别组件与版本差异 |
| 24 | `release_manifest_compare_identical` | 同一清单无差异 |
| 25 | `release_fingerprint_stable` | 指纹稳定 |

### 4.6 耗时观测（仅记录，不宣称达标）

| 阶段 | 实测 |
|---|---|
| 备份 | 0.018s |
| 恢复 | 0.004s |
| 灾难恢复 | 0.004s |

> 上述为**本机小规模**演练实测值。生产规模下的 RTO 需在真实数据量与
> 真实存储介质上重新测量。RPO/RTO 目标属 Owner 决策。

## 5. 关键设计决策及其依据

### 5.1 备份产物必须落工作区外（硬约束）

`check_workspace` 对工作区内的非规范文件名（`.db-wal`、含连字符的时间戳命名）
报 `WS_BAD_FILENAME`。备份写进工作区会**污染一致性检查并打破既有门禁**，
故构造期即拒绝。

### 5.2 Runtime DB 必须用在线备份 API

WAL 模式下直接拷贝 `.db` 会与 `-wal`/`-shm` **不一致**，恢复后可能丢失
最近提交或损坏。故一律走 `RuntimeStore.backup_to()`（SQLite 在线备份 API），
并把 `90_control/runtime` 加入文件拷贝排除清单。

### 5.3 一致性点（评审明确指出的缺口）

单独备份「知识资产」或「运行态」任一侧，都无法保证恢复后语义一致。
故备份时同时捕获：

- `04_serve/*/CURRENT.md` 的 `target_version`
- `03_core/*/version=*` 目录清单
- Runtime DB schema 版本与队列统计

恢复后 `verify_consistency()` 比对，不匹配则**显式报告**（不静默忽略）。

### 5.4 锁必须排除且清理

锁文件内含 `pid`/`host`，恢复到新主机后必然失效。若不处理会导致后续写操作
被**无主锁永久阻塞**。故：备份时排除、恢复后清理。

### 5.5 恢复后补齐空目录

`rglob` 不会捕获空目录，而 `init_workspace` 创建的目录结构是
`check_workspace` 的检查依据。故恢复后显式补齐 `TOP_LEVEL_DIRS` 与
`CONTROL_SUBDIRS`。

### 5.6 默认拒绝恢复损坏备份

`restore_backup(verify_first=True)` 为默认值。用损坏备份覆盖现场会造成
**二次灾难**，故必须先校验。保留 `--skip-verify` 但文档标注不建议。

### 5.7 版本号只记录不统一

代码中并存 4 套版本（`package=0.1.0`、`service_http=1.0.0`、
`runtime_db_schema=2`、`projection_builder=1.0.0`）。统一涉及多处契约与测试，
属**独立变更**，不在本任务包范围。本次只汇总记录使其可见。

### 5.8 git 锚点补齐（治理文档登记的缺失项）

`DKWS_STATUS_BASELINE_CANDIDATE.yaml` 原登记 `dkws_git_commit_anchor: null`。
现由 `git_anchor()` 采集 commit / branch / tag / dirty 状态。
**dirty 工作区会明确警示「不应用于生产」**，`dkws_ops.py manifest` 返回退出码 2
（可用 `--allow-dirty` 放行）。

## 6. Loop Engineering 记录

### 6.1 自测脚本误用 API（非产品缺陷）

首次自测显示恢复后 dead-letter 丢失。排查确认：`claim_job` 按 FIFO 领到
`JOB-BK-1`，而我对 `JOB-BK-2` 调 `fail_job` 因**非 lease 持有者**返回 `None`。
`backup_to()` 本身正确。修正自测脚本顺序后通过。

### 6.2 `Finding` 字段名错误（产品缺陷）

`_check_structure` 读 `finding.severity`，实际字段为 `level`，
导致 `ok` 判定失效（有 BLOCKER 仍返回 `True`）。已修正并新增 `blockers` 属性。

### 6.3 测试 fixture 数据不规范（非产品缺陷）

`CURRENT.md` 指向的版本目录未在 `04_serve` 下创建，触发
`WS_DANGLING_CURRENT`（BLOCKER）。此为 fixture 问题，已补齐目录。

## 7. 变更文件清单

### 7.1 新增（源码）

| 文件 | 行数 | 说明 |
|---|---|---|
| `src/dkws/infrastructure/backup.py` | 529 | 备份范围、一致性点、在线 DB 快照、完整性校验、恢复与一致性验证 |
| `src/dkws/infrastructure/release.py` | ~330 | git 锚点、版本汇总、组件哈希、发布清单、清单比对 |

### 7.2 新增（测试）

- `tests/unit/test_backup.py`（49 项）
- `tests/unit/test_release.py`（26 项）

### 7.3 新增（工具 / 文档）

- `scripts/dkws_ops.py`（运维 CLI：backup / verify / restore / manifest / compare）
- `scripts/verify_m2p5_backup_restore.py`（E2E 演练）
- `evidence/m2-p5/**`

## 8. 约束遵守自查

| 约束 | 状态 |
|---|---|
| 不引入 PostgreSQL / Redis / 外部 MQ / Kubernetes | 遵守（纯 stdlib） |
| 不把 SQLite 变成知识权威源 | 遵守（未触碰 schema） |
| 不修改 GITS | 遵守 |
| 不修改 Java Runtime 生产边界 | 遵守（`poc/` 零改动） |
| 不降低现有测试门禁 | 遵守（738 → 813） |
| 不破坏 `tests/recovery` 锁定的 M2.4 语义 | 遵守（E2E 检查 15-16 专项验证） |
| 不自行设定 RPO/RTO | 遵守（manifest 中明确标注属 Owner 决策） |

## 9. 已知限制与遗留项

| 项 | 说明 | 归属 |
|---|---|---|
| **RPO/RTO 未设定** | 备份频率、保留策略、演练频率均需 Owner 决策 | **需 Owner 决策** |
| 无调度集成 | 未提供 cron/systemd timer 配置；备份需运维侧接入调度 | M2-P6（部署） |
| 无异地/加密备份 | 备份为本地明文；异地复制与静态加密未实现 | 后续 |
| 无增量备份 | 全量拷贝；大数据量下备份窗口与存储成本待评估 | 后续 |
| 版本号未统一 | 4 套版本并存，本次只记录 | 独立变更 |
| 无自动回滚执行 | 提供清单比对与差异识别，但回滚动作仍需人工执行 | 后续 |
| 生产灾备演练未执行 | 本次为开发侧自验；生产演练需真实环境与 Owner 签署 | **需 Owner 安排** |
