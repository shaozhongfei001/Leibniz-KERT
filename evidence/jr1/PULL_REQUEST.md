# PR: JR-1 内部契约双端测试

- **源分支**：`feature/jr1-internal-contract-dual-tests`
- **目标分支**：`develop`
- **任务包**：JR-1（内部契约双端测试）
- **角色**：Feature Pilot
- **关联架构决策**：C′ 混合架构（选项 A）
- **契约版本**：`1.0.0-candidate`
- **契约 bundle hash**：`64b9b432d6ee9fc9e017436171f05e1198ab920121202266c835c471ff2c4550`

> 本文件供 Owner / Tech Lead 创建 PR 使用。Feature Pilot 无 GitHub 凭据，
> 无法自行创建 PR（详见「待 Owner 处理」）。

---

## 1. 目标

让 Python Core 与 Java Skill Runtime **对同一份内部契约**具备可验证的
消费/提供能力。契约一致性不依赖人工核对，而由机器闸门守护。

## 2. 变更概览

| 类别 | 内容 |
|------|------|
| 新增 | `docs/contracts/internal/examples/` 12 份契约示例 |
| 新增 | `tests/contract/internal/` Python 契约测试 117 项 |
| 新增 | Java `contract/` 包契约测试 73 项 |
| 新增 | `scripts/verify_jr1_internal_contract.py` 端到端验证（8 项检查） |
| 新增 | `model/ExecutionPlan.java`、`model/RuntimeError.java` |
| 修复 | 4 个 Java DTO 与契约 Schema 的静默漂移 |
| 文档 | `docs/contracts/internal/README.md`、`evidence/jr1/` |

提交（6 个原子提交）：

```text
be9245e contract(internal): add 12 internal contract examples for dual-side tests
a7ae48a test(contract): add Python-side internal contract tests (117 cases)
02476be fix(skill-runtime): align internal DTOs with contract schemas
d815653 test(skill-runtime): add Java-side internal contract tests (73 cases)
31f9a31 chore(contract): add JR-1 end-to-end internal contract verification script
a7e636a docs(evidence): record JR-1 internal contract dual-side test evidence
```

## 3. 关键发现：Java DTO 与契约存在静默漂移

POC2 阶段的 DTO 是裁剪版，字段集**小于**契约 Schema 的 `required` 集合，
直接序列化无法通过契约校验。已记录 `FAIL-JR1-02` 后修复：

| DTO | 缺失的契约必填/关键字段 |
|-----|------------------------|
| `ExecutionResult` | `runtimeRequestId`、`usable`、`releaseAllowed`、`startedAt`、`completedAt` |
| `ToolCallReceipt` | `skillId`、`skillVersion`、`policyDecisionId`、`sandboxProfileHash` |
| `ModelCallReceipt` | `promptHash`、`status`、`degraded` |
| `RuntimeCapabilities` | `contractHash`、`sandboxCapability`、`status` |

根因：POC2 只验证「能跑通」，无双端自动校验闸门，因此契约独立演进后
无人发现漂移。本 PR 建立的闸门可防止此类问题再次发生。

DTO 补齐仅作用于**内部 Runtime 边界**，未改动任何对外公共 API。

## 4. 双端一致性闸门设计

1. **同一份 Schema，双端各自加载**
   - Python：`jsonschema` Draft 2020-12 + `referencing` 解析相对 `$ref`
   - Java：`com.networknt:json-schema-validator`（**test scope**）以文件 URI
     直接加载 `docs/contracts/internal/schemas/`
   - 两侧均不复制 Schema 片段到测试代码。

2. **契约 hash 四方比对**（任一漂移即失败）
   - `scripts/internal_contract_hash.py` 输出
   - Java `InternalContractHashTest` **独立重算**（非读取 Python 输出）
   - `InternalRuntimeController.CONTRACT_HASH` 内置常量
   - `evidence/jr1/internal-contract-hash.txt` 记录值

3. **漂移检测已负向实测**
   向 `runtime-error.schema.json` 注入多余属性后：
   - Python 端到端验证 → 总体 **FAIL**（hash 检查报三方漂移）
   - Java `InternalContractHashTest` → `Tests run: 7, Failures: 3`，BUILD FAILURE

   随后完整还原契约（hash 回到 `64b9b432...`，`git status` 干净）。
   **该验证证明闸门不是形式摆设。**

## 5. 测试结果

| 侧 | 范围 | 用例数 | 结果 |
|----|------|--------|------|
| Python | `tests/contract/internal`（新增） | 117 | PASS |
| Python | `tests/contract` | 170 | PASS |
| Python | `tests` 全量回归 | **1317** | PASS |
| Java | 4 个契约测试类 | 73 | PASS |
| Java | 模块全量 | 74 | PASS |
| 端到端 | `verify_jr1_internal_contract.py` | 8 项检查 | **8/8 PASS** |

**双端契约用例合计 190。** 全量回归 1317 通过，证明 DTO 改动无回归。

复现命令：

```bash
cd ~/dev/Leibniz-KERT
.venv/bin/python -m pytest tests/contract/internal          # 117 passed
cd poc/spring-ai-alibaba-skill-runtime && mvn -o -B test    # 74 passed
cd ~/dev/Leibniz-KERT
.venv/bin/python scripts/verify_jr1_internal_contract.py    # 8/8 PASS
```

## 6. 自检清单

- [x] Python 与 Java 双端契约测试全部通过
- [x] 所有示例通过 JSON Schema（12/12）
- [x] 契约 hash 可重算，四方一致
- [x] 测试命令真实可复现（含离线 Maven `-o`）
- [x] 证据保存到 `evidence/jr1/`
- [x] 先记录失败再修复（`FAILURES.md` 2 条）
- [x] 显式 `git add`，未使用 `git add .`
- [x] 新增文件 `ruff check` 全部通过
- [x] **未修改 GITS 仓库**
- [x] **未 push main**，未自行 merge
- [x] **未引入 PostgreSQL / Redis / 外部 MQ / Kubernetes**
      （唯一新增依赖为 `json-schema-validator`，`<scope>test</scope>`）
- [x] **未把 SQLite 变成知识权威源**（`RuntimeStore` 仅用于幂等语义验证）
- [x] 未修改生产系统配置

## 7. 审查要点建议

1. `poc/.../model/*.java` 的字段补齐是否与 Schema 完全对应（可直接跑测试验证）。
2. `InternalContractHashTest` 的哈希算法是否与 Python 脚本严格一致
   （分隔符为 `\0`，非 `\n`）。
3. `ExecutionPlan` 使用 `ignoreUnknown = false` 是否符合治理预期
   （未知字段在反序列化阶段即失败，而非静默丢弃）。
4. 示例文件不计入契约 hash 的决策是否认可
   （由 `test_examples_not_in_hash_scope` 守护）。

## 8. 待 Owner / Tech Lead 处理

1. **PR 需人工创建**：本机 `gh` 未认证（无 `GH_TOKEN` / `GITHUB_TOKEN`），
   Feature Pilot 无法创建 PR。分支已推送，可直接访问：
   https://github.com/shaozhongfei001/Leibniz-KERT/pull/new/feature/jr1-internal-contract-dual-tests

2. **两份任务书引用的文档不在 `develop`**：
   `docs/architecture/DKWS_JAVA_RUNTIME_INTEGRATION_PLAN_V1.0.md` 与
   `DKWS_SPRING_AI_ALIBABA_INTEGRATION_STATUS_V1.0.md` 仅存在于未合并分支
   `origin/feature/dkws-java-runtime-integration`。本次已从该分支读取参考，
   但请确认这两份文档是否应先合入 `develop` 作为受控基线。

3. **存在未合并的前序契约分支** `feature/poc2-contract-sandbox`（`ef5d5b3`），
   其中含另一套内部契约与测试草稿。本 PR 严格基于 `origin/develop` 实现，
   未引入该分支内容。**请 Tech Lead 决策该分支的取舍**，避免后续冲突。

4. **公共契约仍有 `PENDING_COMPUTE`**：
   `docs/contracts/openapi/dkws-openapi-v2.yaml` 的
   `x-contract-bundle-hash: PENDING_COMPUTE` 属已登记冲突 C-19，
   位于**对外**契约，不在 JR-1 内部契约范围内，未擅自改动。

5. **`--skip-java` 语义**：脚本将其显式记为 FAIL，防止「跳过 Java 却宣称
   双端通过」。若 CI 环境无 Maven，请确认此严格策略是否保留。

## 9. 非声明

- 本次**不**代表 DKWS 已生产就绪。
- 本次**不**代表 GITS UAT 已通过。
- 本次**不**代表安全审计已完成。
- 本次**不**代表 Java Runtime 已生产可用。
- 本次**不**代表 C′ 混合架构已成为正式基线。
- Feature Pilot **不代替** Owner、Tech Lead 或 Independent QA 签署。
- 本任务包仅覆盖**内部契约的双端可验证性**，不含真实网络联调、
  性能压测、沙箱逃逸测试与灰度切换验证。
