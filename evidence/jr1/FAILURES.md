# JR-1 相关失败记录

## `FAIL-JR1-05`：CI 首次在 develop PR 上运行后暴露 3 项既存红灯

- **发现时间**：2026-08-31
- **发现角色**：Tech Lead（执行合并授权前的门禁核验）
- **触发 PR**：#4 `fix/ci-httpx-test-dependency` → `develop`
- **CI 运行**：[33351476195](https://github.com/shaozhongfei001/Leibniz-KERT/actions/runs/33351476195)
- **性质**：**均非本 PR 引入**。PR #4 修好 `httpx` 缺失并让 CI 首次在
  `develop` PR 上运行，于是把此前从未被验证的既存问题一次性暴露出来。

### CI 结果总览

| Job | 结论 | 根因归属 |
|---|---|---|
| Security Tests | ✅ SUCCESS | — |
| Performance Benchmarks | ✅ SUCCESS（`continue-on-error: true`） | — |
| Lint | ❌ FAILURE | 既存 F-1 |
| Test | ❌ FAILURE | 既存 F-2 |
| E2E Tests | ❌ FAILURE | 既存 F-3 |

`mergeStateStatus = UNSTABLE`、`mergeable = MERGEABLE`。

---

### F-1 Lint：ruff 267 个既存错误

```text
Found 267 errors.
[*] 148 fixable with the `--fix` option (26 hidden fixes can be enabled with the `--unsafe-fixes` option)
##[error]Process completed with exit code 1.
```

- 步骤：`ruff check src/ tests/`（`Ruff check` 步骤失败，`Mypy type check` 未执行）
- **仓库中不存在任何 ruff 配置**（`pyproject.toml` 无 `[tool.ruff]`，
  无 `.ruff.toml` / `ruff.toml`），因此 ruff 以**全默认规则集**扫描全库。
- 样本错误为 import 排序（`I001` 类）等风格项，非功能缺陷。
- 归属：既存技术债。此前 CI 从不在 `develop` PR 运行，故从未暴露。

### F-2 Test：3 个性能基准断言超阈值

```text
FAILED tests/performance/test_parquet_benchmark.py::test_parquet_logical_hash_benchmark[100_rows]
  - AssertionError: logical_hash 100 rows: 3.5ms > 3ms threshold
FAILED ...[1000_rows]  - 72.4ms > 30ms threshold
FAILED ...[10000_rows] - 312.1ms > 300ms threshold
```

- **覆盖率达标**：`Required test coverage of 80% reached. Total coverage: 85.36%`
- 根因：`Test` job 跑 `pytest`（无路径参数）→ `testpaths = ["tests"]`
  导致**连 `tests/performance` 一起跑**。而专职的 `Performance Benchmarks`
  job 设了 `continue-on-error: true`（性能波动不应阻断），
  `Test` job 却没有——同一批用例在两个 job 中被赋予**矛盾的阻断语义**。
- 归属：CI 作业边界设计缺陷（既存）。GitHub runner 性能抖动即可触发。

### F-3 E2E：外部服务缺失导致 24 个 error

```text
ERROR ... - AssertionError: 服务未就绪: http://127.0.0.1:8082/actuator/health ([Errno 111] Connection refused)
ERROR ... - AssertionError: 服务未就绪: http://127.0.0.1:8106/api/skill/health ([Errno 111] Connection refused)
```

- 归属：已受控，见 `evidence/jr1/TECH_LEAD_DECISION.md` D-3 →
  任务包 `JR1-E2E-SKIP`（`evidence/jr1/TASK_PACKAGE_E2E_SKIP.md`）。
- **对任务包的重要校正**：CI 日志确认失败**不止 GITS（`:8082`）**，
  `kert_ready`（`:8106`）同样 `Connection refused`。任务包已按 3 个
  fixture（KERT / GITS / GITS Frontend）全覆盖设计，此处得到实证支持。
- 本地此前观测为 21 个 error，CI 为 24 个，差异源于执行环境与选择范围，
  不影响根因判定。

---

## 处置

| 缺陷 | 处置 | 状态 |
|---|---|---|
| F-1 | 需 Owner 决策：新建 ruff 基线任务包（配置 + 分批修复），或临时放宽 Lint 阻断 | **待决策** |
| F-2 | 需 Owner 决策：`Test` job 排除 `tests/performance`（推荐），或对齐 `continue-on-error` | **待决策** |
| F-3 | 已立任务包 `JR1-E2E-SKIP`，待 CI 修复合入后派工 | 已受控 |

## 对合并授权的影响

Owner 已授权合并 PR #4。Tech Lead 在执行前核验发现上述红灯，
**暂缓合并并回报**，理由：

1. PR #4 本身正确且已验证（`develop..HEAD` diff 仅 2 个配置文件，
   与 `PULL_REQUEST_CI_FIX.md` 描述一致），3 项红灯均非其引入；
2. 但合入后 `develop` 将处于红灯状态，PR #1 / #2 随后也无法取得绿灯
   check run，D-4 「先让 CI 转绿再合 #1 → #2」的前提无法达成；
3. 按 AGENTS.md §3 第 10 条，Tech Lead 不自行决定绕过门禁。

## 非声明

- 本记录不代表 PR #4 有缺陷。
- 本记录不代表 CI 已全绿。
- 本记录不构成 `QA_PASS`。
