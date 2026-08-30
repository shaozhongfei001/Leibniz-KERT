# JR-1 证据清单：内部契约双端测试

- 任务包：**JR-1**（内部契约双端测试）
- 角色：Feature Pilot
- 分支：`feature/jr1-internal-contract-dual-tests`（基于 `origin/develop`）
- 目标：让 Python Core 与 Java Skill Runtime 对同一份内部契约具备可验证的消费/提供能力
- 契约版本：`1.0.0-candidate`
- 契约 bundle hash：`64b9b432d6ee9fc9e017436171f05e1198ab920121202266c835c471ff2c4550`
- 总体结果：**8/8 项验证通过**

---

## 1. 证据文件

| 文件 | 说明 |
|------|------|
| `README.md` | 本证据清单 |
| `PR_STATUS.md` | PR 创建后状态核实 + **必须修正项（base 指向 `main`）** |
| `PULL_REQUEST.md` | JR-1 PR 正文 + Owner 决策落实明细（第 8 节） |
| `PULL_REQUEST_BASELINE.md` | 基线 PR 正文（两份计划文档合入 `develop`） |
| `internal-contract-hash.txt` | 契约 bundle hash + 7 份受控文件分项 sha256 |
| `e2e-verification-report.md` | 端到端验证报告（8 项检查逐项结论） |
| `python-contract-test.log` | Python 契约测试日志（`tests/contract`，170 passed） |
| `python-contract-internal-verbose.log` | Python 内部契约测试逐条明细（117 passed） |
| `python-full-suite.log` | Python 全量回归（1317 passed，证明无回归） |
| `java-contract-test.log` | Java 契约测试日志（`InternalContract*Test`，73 passed） |
| `java-full-suite.log` | Java 全量测试（74 passed，含既有 1 项） |
| `FAILURES.md` | 失败记录（先记录后修复，2 条） |

## 2. 测试命令（真实可复现）

```bash
cd ~/dev/Leibniz-KERT

# Python 侧契约测试
.venv/bin/python -m pytest tests/contract              # 170 passed
.venv/bin/python -m pytest tests/contract/internal     # 117 passed

# Java 侧契约测试（离线本地仓库）
cd poc/spring-ai-alibaba-skill-runtime
mvn -o -B test                                         # 74 passed

# 契约 hash
.venv/bin/python scripts/internal_contract_hash.py

# 端到端验证（一条命令跑完 8 项检查）
.venv/bin/python scripts/verify_jr1_internal_contract.py \
    --report evidence/jr1/e2e-verification-report.md
```

> 说明：仓库 `pyproject.toml` 的 `addopts` 已含 `-q`，命令行无需重复传 `-q`
> （重复会进入 extra-quiet 模式而隐藏 `N passed` 摘要）。
> Maven 使用 `-o` 离线模式，依赖取自本机 `~/.m2/repository`。

## 3. 测试结果汇总

| 侧 | 范围 | 用例数 | 结果 |
|----|------|--------|------|
| Python | `tests/contract/internal`（JR-1 新增） | 117 | PASS |
| Python | `tests/contract`（含既有 53） | 170 | PASS |
| Python | `tests`（全量回归） | 1317 | PASS |
| Java | `InternalContractSchemaTest` | 27 | PASS |
| Java | `InternalContractConsumerTest` | 24 | PASS |
| Java | `InternalContractProviderTest` | 15 | PASS |
| Java | `InternalContractHashTest` | 7 | PASS |
| Java | 模块全量 | 74 | PASS |

**双端契约用例合计：117（Python）+ 73（Java）= 190。**

## 4. 覆盖矩阵

### 4.1 Python 侧（JR-1 §6.2）

| 要求 | 覆盖位置 |
|------|----------|
| ExecutionPlan 示例通过 Schema | `test_internal_contract_schemas.py::TestExamplesPassSchema` |
| ExecutionResult 示例通过 Schema | 同上 |
| ToolCallReceipt 示例通过 Schema | 同上 |
| ModelCallReceipt 示例通过 Schema | 同上 |
| RuntimeError 示例通过 Schema | 同上 |
| RuntimeCapabilities 示例通过 Schema | 同上 |
| 未知字段策略 | `test_internal_contract_negative.py::TestUnknownFieldPolicy` |
| 必填字段缺失 | `test_internal_contract_negative.py::TestRequiredFieldPolicy` |
| 同 key 不同 payload 幂等冲突语义 | `test_internal_contract_negative.py::TestIdempotencyConflictSemantics` |

### 4.2 Java 侧（JR-1 §6.3）

| 要求 | 覆盖位置 |
|------|----------|
| 能解析 ExecutionPlan JSON | `InternalContractConsumerTest#parsesFullExecutionPlan` / `parsesMinimalExecutionPlan` |
| 能生成 ExecutionResult JSON | `InternalContractProviderTest#generatesValidSuccessExecutionResult` / `...Degraded...` |
| 能生成 ToolCallReceipt JSON | `InternalContractProviderTest#generatesValidToolCallReceipt` / `...Minimal...` / `...Blocked...` |
| 能生成 ModelCallReceipt JSON | `InternalContractProviderTest#generatesValidModelCallReceipts` |
| 能处理 RuntimeError JSON | `InternalContractProviderTest#consumesRuntimeErrorJson` / `generatesValidIdempotencyConflictError` |
| 能返回 RuntimeCapabilities JSON | `InternalContractProviderTest#generatesValidRuntimeCapabilities` |
| 未知字段处理 | `InternalContractConsumerTest#unknownFieldRejectedOnDeserialization` / `...BySchema` |
| 必填字段缺失 | `InternalContractConsumerTest#missingRequiredFieldRejected`（参数化覆盖全部必填字段） |

## 5. 双端一致性设计（本任务包的核心）

契约一致性不靠人工核对，而由三处机器闸门守护：

1. **同一份 Schema，双端各自加载**
   - Python：`jsonschema` Draft 2020-12 + `referencing` 解析相对 `$ref`
   - Java：`com.networknt:json-schema-validator`（**仅 test 作用域**）
     直接以 `docs/contracts/internal/schemas/` 的文件 URI 加载
   - 两侧都不复制 Schema 片段到测试代码，契约一改、双端同步失败。

2. **契约 hash 三方比对**
   - Python `scripts/internal_contract_hash.py` 计算值
   - Java `InternalContractHashTest` **独立重算**（同算法：按相对路径排序，
     逐文件 sha256，再对 `"<path>\0<sha256>\0"` 拼接串取 sha256）
   - `evidence/jr1/internal-contract-hash.txt` 记录值
   - 以及 `InternalRuntimeController.CONTRACT_HASH` 内置常量
   - 四者必须相等，否则测试失败。

3. **漂移检测已实测有效（负向验证）**
   在 `runtime-error.schema.json` 注入一个多余属性后实测：
   - Python 端到端验证：`结果 6/7 项通过` → 总体 FAIL，hash 检查报
     `证据/Java 内置 与 当前 漂移`
   - Java `InternalContractHashTest`：`Tests run: 7, Failures: 3` → BUILD FAILURE

   随后已完整还原契约文件（`git status` 干净，hash 回到
   `64b9b432...`）。此验证证明闸门不是形式摆设。

## 6. 变更内容

### 6.1 新增（契约示例，12 份）

`docs/contracts/internal/examples/`：每类对象一份完整示例 + 一份边界示例
（最小必填 / 降级 / 拦截 / 错误）。

> 示例**不计入**契约 hash 范围（示例是测试资产，非契约本体），
> 由 `test_internal_contract_hash.py::test_examples_not_in_hash_scope` 守护。

### 6.2 新增（Python 契约测试，117 项）

`tests/contract/internal/`：`conftest.py`、`test_internal_contract_schemas.py`、
`test_internal_contract_negative.py`、`test_internal_openapi_alignment.py`、
`test_internal_contract_hash.py`。

未新增第三方依赖：`date-time` 格式校验自行实现（仓库未装 `rfc3339-validator`）。

### 6.3 新增（Java 契约测试，73 项）

`poc/spring-ai-alibaba-skill-runtime/src/test/java/com/dkws/skillruntime/contract/`：
`InternalContract.java`（支撑类）、`InternalContractSchemaTest`、
`InternalContractConsumerTest`、`InternalContractProviderTest`、
`InternalContractHashTest`。

### 6.4 修改（Java DTO 对齐契约）

发现 POC2 阶段 DTO 与契约 Schema 存在**静默漂移**（详见 `FAILURES.md`
FAIL-JR1-02），已补齐字段使之可生成合规 JSON：

| 文件 | 变更 |
|------|------|
| `model/ExecutionResult.java` | 补齐 `runtimeRequestId`/`usable`/`releaseAllowed`/`degraded`/`startedAt`/`completedAt` 等契约必填字段；`success()` / `degraded()` 工厂方法 |
| `model/ToolCallReceipt.java` | 补齐 `skillId`/`skillVersion`/`policyDecisionId`/`sandboxProfileHash`/`sideEffectReceipt` 等；`ok()` / `blocked()` 工厂方法 |
| `model/ModelCallReceipt.java` | 补齐 `promptHash`/`paramsHash`/`degraded`/`status`；`latencyMs`/`estimatedCost` 按契约用 `number` |
| `model/RuntimeCapabilities.java` | 补齐 `contractHash`/`frameworkVersion`/`sandboxCapability`/`degraded`/`status` |
| `model/ExecutionPlan.java` | **新增**。`@JsonIgnoreProperties(ignoreUnknown = false)` 使未知字段在反序列化即失败 |
| `model/RuntimeError.java` | **新增**。契约错误码常量 + `idempotencyConflict()` 等工厂方法 |
| `controller/InternalRuntimeController.java` | `health()` 返回契约合规能力声明；公开 `CONTRACT_HASH` 常量供测试守护 |
| `pom.xml` | 新增 `json-schema-validator` 1.5.7（**`<scope>test</scope>`**，不进运行时） |

DTO 补齐仅作用于**内部 Runtime 边界**，未改动任何对外公共 API。

### 6.5 新增（端到端验证脚本）

`scripts/verify_jr1_internal_contract.py`，8 项检查，支持
`--skip-java` / `--no-logs` / `--report`。`--skip-java` 显式记为 FAIL，
避免「跳过 Java 却宣称双端通过」。

## 7. Owner 决策落实（2026-08-31）

| # | 事项 | Owner 决策 | 落实状态 |
|---|------|-----------|----------|
| 1 | PR 创建 | 凭据由 Owner 侧提供 | Owner 已手工创建 PR [#1](https://github.com/shaozhongfei001/Leibniz-KERT/pull/1)、[#2](https://github.com/shaozhongfei001/Leibniz-KERT/pull/2)。**但两者 base 均为 `main` 而非 `develop`，需修正** —— 详见 `PR_STATUS.md` |
| 2 | 两份计划文档合入 `develop` 作受控基线 | 先合入 | 合入前验证完成：仅 2 文档 / +302 行 / 零代码 / 无冲突；Feature Pilot 不自行 merge |
| 3 | `feature/poc2-contract-sandbox` | 仅测试草稿，不引入 | 已遵守（零引用） |
| 4 | 公共契约 `PENDING_COMPUTE`（C-19） | 不改动 | 已遵守（未触碰） |
| 5 | `--skip-java` 记为 FAIL | 保留严格策略 | 已保留（当前实现即如此） |

详见 `PULL_REQUEST.md` 第 8 节（含合入前验证明细与执行建议）。

已知覆盖缺口（如实记录，不造假证据）：**版本不兼容矩阵未覆盖**。
契约当前仅 `1.0.0-candidate` 单版本，无第二版本可比对；
建议契约出现 `v2` 时以独立任务包补齐。

## 8. 合规自检

| 约束 | 状态 |
|------|------|
| 不修改 GITS 仓库 | 遵守（本次改动全在 Leibniz-KERT） |
| 不直接 push main | 遵守（功能分支 → PR 到 develop） |
| 不自行 merge | 遵守 |
| 不引入 PostgreSQL / Redis / 外部 MQ / Kubernetes | 遵守（新增依赖仅 test 作用域的 JSON Schema 校验器） |
| 不把 SQLite 变成知识权威源 | 遵守（`RuntimeStore` 仅用于幂等语义验证，未承载知识） |
| 不修改生产系统配置 | 遵守 |
| 先记录失败再修复 | 遵守（`FAILURES.md` 2 条） |
| Java Runtime 不对外暴露 | 由 `test_internal_openapi_alignment.py` 断言路径限 `/internal/`、服务器限回环 |

## 9. 非声明

- 本次**不**代表 DKWS 已生产就绪。
- 本次**不**代表 GITS UAT 已通过。
- 本次**不**代表安全审计已完成。
- 本次**不**代表 Java Runtime 已生产可用。
- 本次**不**代表 C′ 混合架构已成为正式基线。
- Feature Pilot **不代替** Owner、Tech Lead 或 Independent QA 签署。
- 本任务包仅覆盖**内部契约的双端可验证性**，不含真实网络联调、
  性能压测、沙箱逃逸测试与灰度切换验证。
