# 任务包 `JR1-LINT-BASELINE` —— 收紧 ruff 规则基线

- **来源**：`evidence/jr1/FAILURES.md` → FAIL-JR1-05 F-1
- **批准角色**：Tech Lead（2026-08-31）
- **状态**：`ready_for_dev`（未派工）
- **建议分支**：`chore/lint-baseline-tighten`（从 `develop` 拉取）
- **前置条件**：PR #4 已合入 `develop`（已确立 `[tool.ruff.lint]` 显式基线）

---

## 1. 背景

PR #4 已完成两件事：

1. **锁定工具版本**：`pip install ruff==0.16.4 mypy==2.3.1`，消除版本漂移。
   此前 CI 用 `pip install ruff`（不锁版本），而 ruff 默认规则集随版本扩张，
   导致工具升级即可凭空引入与代码改动无关的红灯。
2. **显式声明规则集**：`pyproject.toml` 的 `[tool.ruff.lint]`
   `select = ["E4", "E7", "E9", "F"]`，并修清该集下全部 84 个错误。

本任务包负责**在此基线上分批收紧**，引入被暂时排除的规则族。

## 2. 当前被排除规则的实测分布

基于 ruff 0.16.4 默认集（`select` 未限定时）在 PR #4 修复后的代码上实测：

| 规则 | 数量 | 性质 | 建议优先级 |
|---|---|---|---|
| `B008` function-call-in-default-argument | 23 | **真实缺陷风险**：可变默认值/调用在定义时求值 | **高** |
| `BLE001` blind-except | 34 | 代码质量：`except Exception` 掩盖具体异常 | 中 |
| `I001` unsorted-imports | 36 | 风格，可自动修 | 低（可一次性 `--fix`） |
| `UP*` pyupgrade | 若干 | 风格，可自动修 | 低 |
| `PERF*` / `FURB*` | 若干 | 性能/现代化建议 | 低 |
| `S*` flake8-bandit | 若干 | 安全，需逐条甄别（测试中的 `assert` 会误报） | 中 |
| `PLE1205` logging-too-many-args | 19 | **误报，见 §3** | **不引入** |

> 精确数量以任务执行时实测为准，上表用于排定优先级。

## 3. 重要：`PLE1205` 19 处为误报，不得盲目"修复"

Tech Lead 已核实，**这 19 处不是缺陷**：

```text
src/dkws/application/{extract,ingest,jobs,parse_doc,process_data,
                      projection,publish,review,rollback}.py
```

调用形如：

```python
job.logger.info("EXTRACT_START", "知识抽取开始",
                domain=domain, run_id=run_id, segments=len(segment_files))
```

`job.logger` 并非标准库 `logging.Logger`，而是项目自定义的结构化
logger（`src/dkws/infrastructure/logging.py:66`）：

```python
def info(self, code: str, message: str, **kv):
    self.log("INFO", code, message, **kv)
```

`code` 与 `message` 是两个独立语义参数，**不存在 % 格式化字符串**。
ruff 按标准库 `logging` 语义匹配方法名 `info`，因而误判。

**补充事实**：即使确为标准库调用，Python `logging` 也只在 stderr
打印内部错误，**不向调用方抛异常**（已实测验证）。故此项在任何情况下
都不构成"运行时崩溃"级缺陷。

**处置要求**：若引入 `PL` 规则族，必须在
`[tool.ruff.lint.per-file-ignores]` 或 `lint.ignore` 中排除 `PLE1205`，
并注明本节理由。**禁止**为迎合该规则去改动结构化日志调用——
那会破坏日志契约（`code` 字段是可观测性的检索键）。

## 4. 建议执行顺序

| 批次 | 内容 | 预期改动 |
|---|---|---|
| B1 | 引入 `I`（import 排序）+ `UP`，用 `--fix` 自动修 | 纯风格，零行为变更 |
| B2 | 引入 `B`，逐条修 `B008`（23 处真实缺陷风险） | 需人工判断，可能改默认参数语义 |
| B3 | 引入 `BLE`，为 34 处 `except Exception` 收窄异常类型或补 `# noqa` 说明 | 需人工判断 |
| B4 | 引入 `S`，甄别安全告警（测试目录需 `per-file-ignores` 放行 `S101` assert） | 需人工判断 |
| B5 | 视情况引入 `PERF`/`FURB`；**排除 `PLE1205`** | 可选 |

**每批独立 PR**，便于回滚与评审。禁止一次性引入全部规则族。

## 5. 强制约束

1. 每批次必须保持 `ruff check src/ tests/` 零错误后才可提交。
2. **禁止用 `--unsafe-fixes` 批量修改**——必须逐条确认语义。
3. 修改不得降低测试断言强度，不得删除测试用例。
4. 不得改动 `tests/performance` 的阈值模型（PR #4 已修正，见 F-2）。
5. 覆盖率门槛 80% 不得下降（当前 83.92%）。
6. 若某规则与项目既有约定冲突（如 `PLE1205` 与结构化日志），
   应在配置中显式 `ignore` 并注明理由，**而非改代码迎合工具**。

## 6. 关于 mypy

`ci.yml` 中 mypy 仍挂 `|| true`（仅报告，不阻塞）。收紧 mypy 属**独立议题**，
不在本任务包范围。若要收紧，须另立任务包并先评估 `--ignore-missing-imports`
移除后的错误规模。

## 7. 非目标

- 不修改业务逻辑行为。
- 不引入新的第三方 lint 工具。
- 不收紧 mypy（见 §6）。
- 不处理 e2e 外部服务依赖（见 `JR1-E2E-SKIP`）。
