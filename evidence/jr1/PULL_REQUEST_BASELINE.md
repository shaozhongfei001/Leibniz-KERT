# PR: 将 Java Runtime 集成计划文档合入受控基线

- **源分支**：`feature/dkws-java-runtime-integration`（`12b5cce`）
- **目标分支**：`develop`
- **性质**：纯文档，受控基线补齐
- **Owner 决策**：2026-08-31「任务书第 10、11 项文档不在 develop —— 先合入作为受控基线」
- **建议合并顺序**：**本 PR 先合**，再合 JR-1 PR

---

## 1. 背景

JR-1 任务书要求阅读的第 10、11 项文档仅存在于本未合并分支，
不在 `develop`，因此 JR-1 执行期间无法从受控基线获取权威依据。
Owner 决策先将其合入 `develop` 作为受控基线。

## 2. 变更内容

| 文件 | 变更 |
|------|------|
| `docs/architecture/DKWS_JAVA_RUNTIME_INTEGRATION_PLAN_V1.0.md` | 新增 |
| `docs/architecture/DKWS_SPRING_AI_ALIBABA_INTEGRATION_STATUS_V1.0.md` | 新增 |

- 提交数：**1**（`12b5cce docs(arch): add Java Runtime integration plan and update C' status`）
- 差异：**+302 行，零代码改动**

## 3. 合入前验证（已完成）

| 检查项 | 结果 |
|--------|------|
| 相对 `develop` 的差异范围 | 仅上述 2 份文档，无代码、无配置 |
| 与 `develop` 合并冲突 | **无冲突**（真实 `git merge --no-commit --no-ff` 试合并通过，随后 abort 并删除临时分支） |
| 是否需更新登记表 | **不需要**。`DKWS_STATUS_BASELINE_CANDIDATE.yaml` 是状态/能力视图，不含受控文档清单；两份文档亦不在 `DKWS_DOCUMENT_CONFLICT_REGISTER.md` 中 |
| 是否与 JR-1 既有事实矛盾 | **不矛盾**，且互相印证（见下） |

> 验证过程修正过一次误判：初次使用 `git merge-tree --write-tree` 报冲突，
> 实为本机 git 2.34.1 不支持该选项（需 ≥2.38）导致的 `fatal: unknown rev`，
> 并非真实冲突。已改用三方 `git merge-tree` + 真实试合并复核。

## 4. 与 JR-1 的关系

`DKWS_JAVA_RUNTIME_INTEGRATION_PLAN_V1.0.md` 中的 **WP1「内部契约双端化」**
即 JR-1 任务包，其要求与 JR-1 PR 交付逐条对应：

| WP1 要求 | JR-1 交付 |
|----------|-----------|
| Python consumer/provider contract tests | `tests/contract/internal/` 117 项 |
| Java consumer/provider contract tests | Java `contract/` 包 73 项 |
| 契约 hash 双端一致 | hash 四方比对（Java 独立重算） |
| 未知字段测试 | 双闸门（反序列化 + Schema） |
| 同 key 不同 payload 测试 | 幂等冲突语义 + `RuntimeStore` 行为对齐 |

**一处差异供 Tech Lead 留意**：`INTEGRATION_STATUS` 文档提到「版本不兼容」测试，
JR-1 **未覆盖**该项 —— 内部契约当前仅 `1.0.0-candidate` 单版本，
无第二版本可比对。JR-1 未编造版本矩阵以凑齐清单；
建议契约出现 `v2` 时以独立任务包补齐。

## 5. 审查要点

1. 两份文档内容是否已获 Owner / Tech Lead 认可为受控基线版本。
2. 文档中「选项 A / C′ 混合架构」表述是否与当前架构决策一致。
3. 是否需要在合入同时将其登记进某个基线索引（当前判断为不需要，请确认）。

## 6. 非声明

- 本 PR 仅为**文档合入**，不引入任何代码、依赖或配置变更。
- 本 PR 不代表 DKWS 已生产就绪、GITS UAT 已通过、安全审计已完成。
- 本 PR 不代表 Java Runtime 已生产可用。
- 本 PR 不代表 C′ 混合架构已成为正式基线（该判定属 Owner / Tech Lead 权限）。
- Feature Pilot 不代替 Owner、Tech Lead 或 Independent QA 签署，且未自行 merge。
