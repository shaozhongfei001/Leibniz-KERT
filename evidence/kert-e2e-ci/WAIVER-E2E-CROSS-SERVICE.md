# 测试豁免登记 WAIVER-E2E-CROSS-SERVICE —— 跨服务 E2E 用例的「未覆盖」登记

```text
STATUS=REGISTERED
AUTHORIZED_BY=Tech Lead（2026-09-14 决策 record：evidence/kert-e2e-ci/TECH_LEAD_DECISION.md §D-5「采纳 c+b」/ §D-10「豁免登记口径」）
TASK_PACKAGE=KERT-E2E-C（evidence/kert-e2e-ci/TASK_PACKAGE_E2E_C_KERT_ONLY.md，AC-8 要求本文件）
SELF_EXPIRING=是（双轨：三条失效触发条件 + 每轮 CI 覆盖账本越界即由下限断言判 job 失败）
RELATED_GAP=F-E2E-01（未解除）
REGISTERED_AT=2026-09-14
GAP_ID_CHECK=本仓检索确认 F-E2E-01 未被占用（全仓仅 TECH_LEAD_DECISION.md / TASK_PACKAGE_E2E_C_KERT_ONLY.md / .github/workflows/ci.yml 引用本编号，无既有登记文件占用）→ 沿用，无需顺延
```

---

## 1. 被豁免对象

| 项 | 值 |
|---|---|
| 豁免范围 | `tests/e2e/` 中**需要 GITS 后端（8082）或 GITS 前端（5173）**的用例 |
| 数量 | **恰好 21 条**（清单见 §2，逐条列出，**不得**用"等"字概括） |
| CI 表现 | 在 `e2e` job 中**显式 skip**，skip reason 含「缺失服务名 + 探活地址」 |
| 判定方式 | 运行时探活（`httpx` 探 `GITS_BASE_URL/actuator/health` 与 `GITS_FRONTEND_URL`），**非**静态标记、**非**无条件 skip |
| 缺口号 | `F-E2E-01` |
| 关联决策 | `TECH_LEAD_DECISION.md` D-5（采纳 `c+b`，即 CI 只起 KERT、跨服务用例显式 skip）、D-9（跨仓凭据未授权，故不走 `a`/`a-lite`）、D-10（登记口径） |
| 规模订正 | 本仓 `evidence/jr1/TASK_PACKAGE_E2E_SKIP.md` 的「34 个用例」与 `gits-cbanking/HANDOFF-2026-09-14-KERT-E2E-CI.md` §2.3 的「1/15/27/4」**均已作废**；基线以 D-5 §0.1 实测 47 条（1 / 25 / 17 / 4）为准，D-6 ① 已裁定该订正属**基线数据订正**，非范围扩大 |

## 2. 豁免清单（21 条逐项）

以下清单由 **CI 实跑产出**（KERT 可用、GITS 双端缺失时的 `E2E 覆盖账本` → `uncovered_by_file`）逐条抄录，按文件分组：

### `tests/e2e/test_cross_service_health.py` —— 3 条

| # | 用例 | 缺失服务 |
|---|---|---|
| 1 | `TestCrossServiceHealth::test_all_services_simultaneously` | 多端/含前端 |
| 2 | `TestCrossServiceHealth::test_gits_backend_health` | 仅 GITS Backend |
| 3 | `TestCrossServiceHealth::test_gits_frontend_reachable` | 多端/含前端 |

### `tests/e2e/test_gits_to_kert_integration.py` —— 2 条

| # | 用例 | 缺失服务 |
|---|---|---|
| 4 | `TestGitsToKertIntegration::test_gits_calls_kert_skill_execute` | 多端/含前端 |
| 5 | `TestGitsToKertIntegration::test_gits_kert_connectivity` | 多端/含前端 |

### `tests/e2e/test_scenario_1_continuous_operation.py` —— 4 条

| # | 用例 | 缺失服务 |
|---|---|---|
| 6 | `TestContinuousOperation::test_full_engagement_loop` | 仅 GITS Backend |
| 7 | `TestContinuousOperation::test_gate_state_via_gits` | 仅 GITS Backend |
| 8 | `TestContinuousOperation::test_operating_view` | 仅 GITS Backend |
| 9 | `TestContinuousOperation::test_start_journey` | 仅 GITS Backend |

### `tests/e2e/test_scenario_2_previsit_report.py` —— 2 条

| # | 用例 | 缺失服务 |
|---|---|---|
| 10 | `TestPrevisitReport::test_full_previsit_flow` | 仅 GITS Backend |
| 11 | `TestPrevisitReport::test_memory_extraction` | 仅 GITS Backend |

### `tests/e2e/test_scenario_3_service_proposal.py` —— 3 条

| # | 用例 | 缺失服务 |
|---|---|---|
| 12 | `TestServiceProposal::test_generate_proposal_via_gits` | 仅 GITS Backend |
| 13 | `TestServiceProposal::test_proposal_different_industry` | 仅 GITS Backend |
| 14 | `TestServiceProposal::test_proposal_fact_labels` | 仅 GITS Backend |

### `tests/e2e/test_scenario_4_knowledge_graph.py` —— 3 条

| # | 用例 | 缺失服务 |
|---|---|---|
| 15 | `TestKnowledgeGraph::test_supply_chain_edges` | 仅 GITS Backend |
| 16 | `TestKnowledgeGraph::test_supply_chain_graph_via_gits` | 仅 GITS Backend |
| 17 | `TestKnowledgeGraph::test_supply_chain_node_types` | 仅 GITS Backend |

### `tests/e2e/test_scenario_5_customer_insight.py` —— 4 条

| # | 用例 | 缺失服务 |
|---|---|---|
| 18 | `TestCustomerInsight::test_customer_operating_view` | 仅 GITS Backend |
| 19 | `TestCustomerInsight::test_full_insight_flow` | 多端/含前端 |
| 20 | `TestCustomerInsight::test_insight_gate_correlation` | 仅 GITS Backend |
| 21 | `TestCustomerInsight::test_kyc_gap_analysis` | 仅 GITS Backend |

**合计 21 条**（覆盖 7 个文件；分文件计数：3 / 2 / 4 / 2 / 3 / 3 / 4）。

> 分组口径说明：D-5 §0.1 把跨服务用例记为「仅 GITS 17 + 三端 4」。实施时按**实测 fixture 依赖**重算为
> 「仅 GITS Backend **16** + 多端/含前端 **5**」——**总数（21）与用例集合完全一致**，差异仅在两处
> 子分组边界：`test_gits_to_kert_integration` 的 2 条与 `test_full_insight_flow` 同时需要 GITS 与 KERT
> （`gits_client` + `kert_client`），归入「多端」更贴合其实测依赖。本差异**不改变**豁免范围、不改变
> 下限断言数字（下限只依赖「无服务 1 + 仅 KERT 25 = 26」）。

---

## 3. 豁免原因

CI 的 `e2e` job **只启动 KERT（本仓代码，dev profile + 确定性适配器）**，不启动 GITS 后端/前端：

1. **不引入跨仓耦合**（D-5 理由 2）：在 KERT 的 CI 中编排 GITS，会让 **KERT 的流水线被另一个仓的提交支配**——任一 GITS 改动都能让本仓 CI 变红。
2. **不引入新的安全面**（D-5 理由 3）：跨仓拉取需要 PAT 或 deploy key，属安全敏感配置；D-9 明确「Tech Lead 只提交需 Owner 授权事项清单并 STOP，禁止自行配置任何凭据」，本循环**未获授权**。
3. **覆盖/成本比**（D-5 理由 1）：本仓 CI 可独立验证的 26 条（无服务 1 + 仅 KERT 25）**已真跑**；跨服务链路的验证留待具备 GITS 的联调/UAT 环境。

因此这 21 条在 CI 中**不变量绿地转变为真跑**，而是**显式 skip 并登记为未覆盖**。

## 4. 不豁免范围（强制）

| 项 | 处置 |
|---|---|
| 无服务用例 1 条（`test_golden_scenario.py::test_full_pipeline`） | **不豁免**，必须真跑 |
| 仅 KERT 用例 25 条 | **不豁免**，CI 中必须真跑并通过（下限断言 `passed >= 26` 的组成部分） |
| `tests/unit`、`tests/integration`、`tests/contract`、`tests/recovery` | **不豁免**，不受本登记影响；覆盖率门槛 `--cov-fail-under=80` 不变 |
| `tests/e2e/test_*.py` 的**断言语义** | **不豁免**，不得改宽或删除（本循环未改任何用例文件） |
| 缺失服务的 fast-fail 探活超时 | **不豁免**，缺失服务须快速失败（`E2E_PROBE_TIMEOUT`，默认 3s），不复用 `E2E_HEALTH_TIMEOUT`（30s） |
| `E2E_REQUIRE_SERVICES=1` 的既有语义 | **不豁免**，仍必须使三端缺失全部判失败（向后兼容，见 `tests/e2e/conftest.py`） |

## 5. 自我过期机制（三条**并列**失效触发条件）

本豁免为「未覆盖登记」，无 `xfail(strict=True)` 自动过期能力，故采用双轨：**失效触发条件 + 每轮覆盖账本**。以下三条**任一成立即须重新裁决**（重新裁决前不得继续引用本登记作为"已登记"依据）：

| # | 触发条件 | 届时应做 |
|---|---|---|
| **T1** | CI 引入 GITS 服务编排（`a`/`a-lite` 落地） | 本豁免**自动作废**；21 条须转为**真跑**，并同步收紧下限（`passed` 下限升至 47），`e2e` job 增加 GITS 就绪校验 |
| **T2** | 跨服务用例集合发生变化（新增 / 删除 / 移动 / 重命名） | 本登记 §2 清单与实跑账本 `uncovered_by_file` 不一致即失效；须重出登记并复核下限推导 |
| **T3** | 每轮 CI 覆盖账本越界 | 账本出现 `passed < 下限` 或 `skipped > 上限` 或 `errors > 0` 或 `failed > 0` 时，由下限断言**直接判 job 失败**（fail-closed，不得降级为 warning） |

配套：`loops`/评审侧可在任意一轮以「账本 ↔ 本文件 §2 清单逐条比对」的方式验伪 T2 —— 两者不一致即说明本登记已过期。

## 6. 覆盖账本要求（每轮 CI 必须打印）

`e2e` job 每轮必须打印（由 `tests/e2e/conftest.py` 的 session 钩子生成，并落盘 JSON 供独立断言步骤核验）：

```text
E2E 覆盖账本（下限由本次收集结果推导，见 TECH_LEAD_DECISION.md D-8）：
  collected = <n>
  passed  = <n>   (下限 <min> = 无服务 <a> + 仅 KERT <b>)
  skipped = <n>   (上限 <max> = 跨服务 <c>（仅 GITS <d> + 多端/含前端 <e>）)
  failed  = <n>   (必须 0)
  errors  = <n>   (必须 0)
  覆盖口径：<passed>/<collected> 真跑，<skipped>/<collected> 未覆盖
  未覆盖用例清单（按文件分组）：
    <文件>  (<m> 条)
      - <用例>  [<缺失服务名> 不可达 (<探活地址>)]
  require 开关：<生效的开关>
  ✓/✗ 下限断言 …
```

硬约束（D-8）：

1. 下限/上限**必须由当次收集结果推导**（`下限 = 无服务用例 + 仅 KERT 用例`，`上限 = 跨服务用例`），不得写成脱离实际的魔数；用例增删后自动重算。
2. `errors == 0`、`failed == 0`、`passed >= 下限`、`skipped <= 上限` **任一不满足即 job 失败**。
3. 禁止以 `continue-on-error`、`|| true`、吞异常等任何手段绕过该断言。
4. 未覆盖清单必须**逐条**打印（按文件分组），使"未覆盖"在日志中显式可见。

## 7. 边界声明（强制）

- 本登记是**「未覆盖」的显式登记，不是「通过」**。
- 任何报告、PR 描述、发布说明**不得**把「CI 绿」表述为「跨服务链路已验证」/「GITS↔KERT 联调通过」。
- CI 绿只证明：①②26 条本仓可跑用例真的跑了且通过；③KERT 起不来时 job 会失败（防假绿生效）。
- 本登记**不构成** Independent QA 的 `QA_PASS`，也**不表示** KERT `PRODUCTION_READY=YES` 或 `GITS_UAT_PASS=YES`。

## 8. 移除步骤（T1 成立时）

1. 在 `e2e` job 中增加 GITS 后端/前端服务编排（含就绪校验，失败即 `exit 1`），并按 D-9 先取得 Owner 对跨仓凭据的书面授权。
2. 移除 `E2E_REQUIRE_KERT=1` 的单服务口径，改为 `E2E_REQUIRE_SERVICES=1`（三端全要求），使 21 条缺失时 fail 而非 skip。
3. 将下限断言的 `min_passed` 由 26 收紧为 `collected`（即全部真跑）——注意该项由收集结果自动推导，**无需改代码**，但必须在评审中确认覆盖口径已变为 47/47。
4. 更新本文件为 `STATUS=SUPERSEDED_BY_T1` 并在 `TECH_LEAD_DECISION.md` / 相关任务包中登记 `F-E2E-01` 状态变化。

## 9. 附带说明（不属本豁免范围）

- `Performance Benchmarks`（`tests/performance/`）的计时不稳定（`22.36ms > 20.0ms`）与本豁免无关，D-5 非目标已明确排除。
- `evidence/jr1/TASK_PACKAGE_E2E_SKIP.md`（`JR1-E2E-SKIP`）按 D-6 应标注 `superseded_by=KERT-E2E-C`；**本次未执行该标注**——本循环被授权的文件范围仅 `tests/e2e/conftest.py`、`.github/workflows/ci.yml`（`e2e` job 内）与新增 `evidence/kert-e2e-ci/**`，不含 `evidence/jr1/**`。该项留待 Tech Lead / Owner 执行，`JR1-E2E-SKIP` 文件保持原样、不删除。

---

## 10. T3 触发后的重新裁决（2026-09-14）

**背景**：真实 CI run `34845070952`（sha `c865365`）的账本出现 `failed=10` 且
`passed=16 < 下限 26` ⇒ §5 的 **T3 触发**，按规定须重新裁决。

**裁决结果：豁免维持不变**（本文件继续有效，§1~§8 全部不变）。

**依据**：

1. **T3 的触发根因不在本豁免范围内**，而是一个独立的产品缺陷：`bank-front-*` 等外部技能
   因「Skill 包解析静默降级」而未被注册（缺口 **`F-E2E-02`**，修复见
   `TASK_PACKAGE_D-E2E-01.md`）。该修复**未**改用例、**未**改断言语义、
   **未**触碰本豁免的 21 条清单。
2. **T2 未触发**：新账本（run `34858121012`）的 `uncovered_by_file` 与本文件 §2 清单
   **逐文件计数完全一致** —— `test_cross_service_health` 3 /
   `test_gits_to_kert_integration` 2 / `test_scenario_1_continuous_operation` 4 /
   `test_scenario_2_previsit_report` 2 / `test_scenario_3_service_proposal` 3 /
   `test_scenario_4_knowledge_graph` 3 / `test_scenario_5_customer_insight` 4 = **21**。
3. **T3 不再成立**：新账本 `failed=0`、`passed=26 >= 下限 26`、`errors=0`、
   `skipped=21 <= 上限 21`。
4. **T1 未触发**：CI 仍未编排 GITS 服务。

**结论**：本豁免的登记口径、21 条清单与下限/上限推导**全部不变**，
继续按 §7 边界声明引用；相关解除记录见 `ADMISSION-E2E-EVIDENCE.md` §6。

**不构成**：`QA_PASS`、`PRODUCTION_READY`，也不表示跨服务链路已验证。
`F-E2E-01` **未解除**。
