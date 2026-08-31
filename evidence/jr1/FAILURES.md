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
| F-1 | 锁定 `ruff==0.16.4` / `mypy==2.3.1` + `pyproject.toml` 显式 `select = ["E4","E7","E9","F"]` + 修清该集下 84 个错误；收紧计划另立 `JR1-LINT-BASELINE` | **已修复** |
| F-2 | 补齐 `write`/`hash`/`relation-write`/`roundtrip` 四处最小阈值 + `Test` job 显式限定作用域 | **已修复** |
| F-3 | 已立任务包 `JR1-E2E-SKIP`，待 PR #4 合入后派工 | 已受控 |

### F-1 修复明细

1. **锁版本**（根因）：`pip install ruff mypy` → `pip install ruff==0.16.4 mypy==2.3.1`。
   不锁版本是本项的真正元凶——ruff 默认规则集随版本扩张，工具升级即可
   凭空引入红灯。
2. **显式规则集**：`pyproject.toml` 新增 `[tool.ruff.lint]`
   `select = ["E4", "E7", "E9", "F"]`，不再依赖 ruff 默认值。
   该集合等价于团队引入 Lint 时的隐含预期强度，**非放宽门禁**。
3. **修清 84 个错误**：62 个由 `ruff --fix` 安全自动修（`F401` 未使用
   import、`F541` 等），22 个人工逐条处理。其中两项为真实缺陷：

   - **`F811` `src/dkws/application/report.py`**：`render_report` 在同文件
     重复定义两次。第 351 行的旧版本被第 502 行完全遮蔽（dead code），
     且旧版**缺少 `SP-20` 服务建议书分支**。已删除旧版，保留含
     `render_proposal_report` 分支的完整实现。
   - **`E402` `src/dkws/application/skills.py`**：两处 import 位于
     `logging.getLogger()` 之后。经确认无循环导入顾虑，已归位到文件头部。

   其余 `F841` 未使用变量逐条判断后移除。注意 `ingest.py:148` 的
   `_write_lineage()` 有写文件副作用，仅移除赋值、保留调用。
   `interaction_memory.py` 移除 `t0` 后 `time` 模块已无引用，同步移除 import。

4. **`PLE1205` 19 处经核实为误报**，不在本次修复范围，理由见
   `evidence/jr1/TASK_PACKAGE_LINT_BASELINE.md` §3：
   `job.logger` 是项目自定义结构化 logger（`info(code, message, **kv)`），
   非标准库 `logging.Logger`，不存在 % 格式化字符串。

   > **更正**：本文档初版及 Tech Lead 初期口头判断曾称这 19 处为
   > "运行时真实缺陷"。经核实签名与实测 `logging` 行为后确认该判断有误——
   > 既非缺陷，且标准库 `logging` 参数不匹配时也只在 stderr 打印内部错误、
   > 不向调用方抛异常。特此更正，避免误导后续修复。

### F-2 修复明细

1. **阈值模型缺陷**（根因，非 runner 抖动）：本地重复运行同样稳定失败，
   `100_rows` 单个用例在多次运行间波动达 24 倍（3.6ms / 24.5ms / 71.6ms /
   87.7ms）。原因是阈值按行数**线性缩放**：
   `HASH_THRESHOLD_MS * (n / 10_000)` 使 100 行的门槛被算成 `3ms`，
   而 pyarrow 调用开销、内存分配与解释器抖动**不随行数缩放**，
   小数据量下由固定开销主导，3ms 物理上不可达。

   作者原本已在 `read` 路径设了 `READ_MIN_THRESHOLD_MS = 50` 保护，
   但 `write` / `hash` 路径漏了——三个失败用例全部落在缺保护的路径上，
   与根因完全吻合。

   已补齐 `WRITE_MIN_THRESHOLD_MS = 50`、`HASH_MIN_THRESHOLD_MS = 100`，
   并将四处阈值统一为 `max(MIN, 线性缩放)` 模式（含此前未失败但存在
   同类隐患的 `write_relation_parquet` 与 `roundtrip`，避免遗留定时炸弹）。
   NFR-005 的真实约束是 10K 行那一档，小数据量不应设不可达门槛。

   验证：`tests/performance/test_parquet_benchmark.py` 15 个用例
   连续两轮全部通过。

2. **作业边界缺陷**：`Test` job 跑无参数 `pytest`，被
   `testpaths = ["tests"]` 带上 `e2e` / `security` / `performance` 全部
   （CI 日志确认该 job 内含 45 个 e2e ERROR 行），与三个专职 job 完全重叠，
   且与 `performance` job 的 `continue-on-error: true` 语义矛盾——
   同一批基准用例在此阻断、在那放行。

   已改为显式限定作用域：
   `tests/unit/ tests/integration/ tests/contract/ tests/recovery/`。

   > **关键修正**：初版计划仅跑 `unit + integration`。核查发现
   > `tests/contract`（**含 JR-1 内部契约测试**）与 `tests/recovery`
   > **没有任何专职 job**，此前仅靠无参数 `pytest` 被间接执行。
   > 若按初版计划，JR-1 的核心交付物将彻底脱离 CI 验证。已纳入作用域。

## 本地验证结果（PR #4 修复后）

| 项 | 结果 |
|---|---|
| `ruff check src/ tests/` | `All checks passed!` |
| `tests/unit + integration + contract + recovery` | `EXIT=0`，覆盖率 **83.92%**（门槛 80%） |
| `tests/performance/test_parquet_benchmark.py` | 15 passed，连续两轮 |
| `tests/security/` | `EXIT=0`（回归对照，未受影响） |
| `ci.yml` YAML 语法 | 合法 |

`tests/e2e` 仍为 24 error（外部服务缺失），由 `JR1-E2E-SKIP` 处理，
本次不在范围内。

## 对合并授权的影响

Owner 已授权合并 PR #4。Tech Lead 在执行前核验发现上述红灯，
**暂缓合并并回报**，理由：

1. PR #4 本身正确且已验证（`develop..HEAD` diff 仅 2 个配置文件，
   与 `PULL_REQUEST_CI_FIX.md` 描述一致），3 项红灯均非其引入；
2. 但合入后 `develop` 将处于红灯状态，PR #1 / #2 随后也无法取得绿灯
   check run，D-4 「先让 CI 转绿再合 #1 → #2」的前提无法达成；
3. 按 AGENTS.md §3 第 10 条，Tech Lead 不自行决定绕过门禁。

**后续（Owner 二次授权）**：Owner 批准按 Tech Lead 建议处理 F-1（方案 C）
与 F-2（方案 A′），并同意并入 PR #4。修复已完成，PR #4 的性质随之从
「纯配置修复」扩展为「配置修复 + 门禁基线确立」。
`tests/e2e` 的 24 error 仍待 `JR1-E2E-SKIP` 解决，届时 CI 方可全绿。

## 非声明

- 本记录不代表 PR #4 有缺陷。
- 本记录不代表 CI 已全绿（`tests/e2e` 24 error 未解决）。
- 本记录不构成 `QA_PASS`。
