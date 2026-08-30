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

## 8. Owner 决策与落实（2026-08-31）

Owner 已就 JR-1 上报的 5 项作出决策，逐项落实状态如下。

| # | 事项 | Owner 决策 | 落实状态 |
|---|------|-----------|----------|
| 1 | PR 创建 | 凭据由 Owner 侧提供 | **仍阻塞**：本机无凭据，见下 8.1 |
| 2 | 两份计划文档不在 `develop` | **先合入作为受控基线** | 已完成合入前验证，见 8.2 |
| 3 | `feature/poc2-contract-sandbox` | 仅作测试草稿，**不引入** | 已遵守（本 PR 零引用），见 8.3 |
| 4 | 公共契约 `PENDING_COMPUTE`（C-19） | **不改动** | 已遵守（未触碰），见 8.4 |
| 5 | `--skip-java` 记为 FAIL | **保留严格策略** | 已保留（无需改动），见 8.5 |

### 8.1 PR 创建（决策 1）— 仍需 Owner 执行

本机 `gh` 已安装但未认证，`GH_TOKEN` / `GITHUB_TOKEN` 均为空，
`origin` 为 SSH-only（`git@github.com:...`），无 HTTPS API 凭据。
属「缺凭据」类硬阻塞，Feature Pilot 不绕过。

分支已推送且与远程一致，直接创建即可：

```text
https://github.com/shaozhongfei001/Leibniz-KERT/pull/new/feature/jr1-internal-contract-dual-tests
```

### 8.2 两份计划文档合入 `develop`（决策 2）— 已完成合入前验证

Owner 决策「先合入作为受控基线」。Feature Pilot **不可自行 merge**，
故仅完成合入前验证并给出执行方案。

源分支：`origin/feature/dkws-java-runtime-integration`（`12b5cce`）

验证结论：

| 检查项 | 结果 |
|--------|------|
| 该分支相对 `develop` 的差异 | **仅 2 份文档，+302 行，零代码改动** |
| 独有提交数 | **1 个**（`12b5cce docs(arch): add Java Runtime integration plan and update C' status`） |
| 与 `develop` 合并冲突 | **无冲突**（真实试合并 `--no-commit --no-ff` 通过，随后 abort 复原） |
| 是否需要更新登记表 | **不需要**：`DKWS_STATUS_BASELINE_CANDIDATE.yaml` 是状态/能力视图，不含受控文档清单；两份文档也未在 `DKWS_DOCUMENT_CONFLICT_REGISTER.md` 中 |
| 与 JR-1 事实是否矛盾 | **不矛盾**，且互相印证（见下） |

内容印证：`DKWS_JAVA_RUNTIME_INTEGRATION_PLAN_V1.0.md` 的 **WP1「内部契约双端化」**
正是本任务包 JR-1，其交付要求与本 PR 逐条对应：

| WP1 要求 | 本 PR 对应交付 |
|----------|---------------|
| Python consumer/provider contract tests | `tests/contract/internal/` 117 项 |
| Java consumer/provider contract tests | Java `contract/` 包 73 项 |
| 契约 hash 双端一致 | hash 四方比对（Java 独立重算） |
| 未知字段测试 | 未知字段策略双闸门（反序列化 + Schema） |
| 同 key 不同 payload 测试 | 幂等冲突语义 + `RuntimeStore` 行为对齐 |

> 一处差异供 Tech Lead 留意：WP1 未要求「版本不兼容」测试，
> 而 `INTEGRATION_STATUS` 文档提到该项。本 PR **未覆盖版本不兼容矩阵**
> （契约当前仅 `1.0.0-candidate` 单版本，无第二版本可比对）。
> 建议在契约出现 `v2` 时以独立任务包补齐，避免此刻造出假证据。

**建议执行方式**（保持基线可追溯，与 JR-1 解耦）：
先将 `feature/dkws-java-runtime-integration` 单独 PR 合入 `develop`，
再合 JR-1 PR。两者无文件重叠，顺序不影响，但**先合基线**更符合
「受控基线先于实现」的权威顺序。

```text
https://github.com/shaozhongfei001/Leibniz-KERT/pull/new/feature/dkws-java-runtime-integration
```

Feature Pilot 未自行创建该分支的副本分支，以免产生重复提交与冲突源。

### 8.3 前序契约分支不引入（决策 3）— 已遵守

`feature/poc2-contract-sandbox`（`ef5d5b3`）仅作测试草稿，不引入。
本 PR 严格基于 `origin/develop`，未引用、未 cherry-pick 其任何内容。

### 8.4 公共契约 `PENDING_COMPUTE` 不改动（决策 4）— 已遵守

`docs/contracts/openapi/dkws-openapi-v2.yaml` 的
`x-contract-bundle-hash: PENDING_COMPUTE` 属冲突登记册 C-19（状态 `PENDING`），
位于**对外**契约，不在 JR-1 范围，未触碰。

内部契约侧无占位符残留，由
`test_internal_contract_hash.py::test_no_pending_compute_placeholder` 守护。

### 8.5 `--skip-java` 严格策略保留（决策 5）— 已保留

`scripts/verify_jr1_internal_contract.py` 将 `--skip-java` 显式记为 **FAIL**
并附「跳过即视为未验证，不得据此宣称双端通过」。该行为已是当前实现，
无需改动。CI 若无 Maven，将如实呈现为未验证而非假绿。

## 9. 非声明

- 本次**不**代表 DKWS 已生产就绪。
- 本次**不**代表 GITS UAT 已通过。
- 本次**不**代表安全审计已完成。
- 本次**不**代表 Java Runtime 已生产可用。
- 本次**不**代表 C′ 混合架构已成为正式基线。
- Feature Pilot **不代替** Owner、Tech Lead 或 Independent QA 签署。
- 本任务包仅覆盖**内部契约的双端可验证性**，不含真实网络联调、
  性能压测、沙箱逃逸测试与灰度切换验证。
