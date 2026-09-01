# FO-01 执行器规则 ID 对齐（KERT 规则 ID 对齐）

> 状态块：
> - **CANDIDATE**
> - **FROZEN=NO**
> - **IMPLEMENTED=NO**
>
> 本文档是 **FO-01 交付物**，记录 WP2-3 执行器 `eligibility.py` 的 `RULE_CATALOG`
> 与消费规则清单（`skills/product-recommendation/rules/rule-bundle-manifest.md`）之间
> 规则 ID 漂移的消除决策。所有结论均基于对知识工程仓库 `~/dev/Leibniz-KERT` 实际文件的
> 逐文件取证，未臆造。

- 生成日期：2026-08-31
- 取证仓库：`~/dev/Leibniz-KERT`
- 派工编号：FO-01（KERT 规则 ID 对齐）

---

## 1. 问题描述（ID 漂移）

WP2-3 执行器 `src/dkws/application/product_recommendation/eligibility.py` 的
`RULE_CATALOG` 原使用下列 ruleId：

| 原 category | 原 ruleId | 原 ruleVersion |
|---|---|---|
| VALIDITY | `PR-ELIG-001` | `1.3` |
| REGULATORY | `PR-REG-001` | `2.0` |
| ADMISSION | `PR-ADM-004` | `2.0` |
| PREREQUISITE_EXCLUSION | `PR-PRE-001` | `1.0` |
| MATERIAL | `PR-MAT-001` | `1.0` |
| SALES_BOUNDARY | `PR-BND-001` | `1.0` |

其中 `PR-ADM-004` / `PR-PRE-001` / `PR-BND-001` 在消费规则清单
（`rule-bundle-manifest.md` §2）**不存在**；`PR-ELIG-001` 被误标为 VALIDITY
（清单中 `PR-ELIG-001` 是客户准入规则，有效性规则是 `PR-VALID-001`）；
`ruleVersion` 亦与清单候选版本 `1.0.0-candidate` 不一致。

清单（`rule-bundle-manifest.md` §2，6 条种子规则）的真实 ID 与版本：

| README 顺序 | 规则类型 | ruleId | ruleVersion |
|---|---|---|---|
| 2 | 有效性 | `PR-VALID-001` | `1.0.0-candidate` |
| 3 | 监管禁止 | `PR-REG-001` | `1.0.0-candidate` |
| 4 | 客户准入 | `PR-ELIG-001` | `1.0.0-candidate` |
| 5+6 | 前置互斥 | `PR-PRMUTEX-001` | `1.0.0-candidate` |
| 2.2（非硬约束） | 材料 | `PR-MAT-001` | `1.0.0-candidate` |
| 7 | 销售边界 | `PR-SALES-001` | `1.0.0-candidate` |

## 2. 映射决策

按派工语义映射，`RULE_CATALOG` 全部 ruleId 改为消费规则清单真实 ID，
`ruleVersion` 统一为清单候选版本 `1.0.0-candidate`：

| 语义 | 原 ruleId | → 新 ruleId | category（不变） |
|---|---|---|---|
| 有效性 | `PR-ELIG-001`（标 VALIDITY） | → `PR-VALID-001` | VALIDITY |
| 监管禁止 | `PR-REG-001` | → `PR-REG-001`（不变） | REGULATORY |
| 客户准入 | `PR-ADM-004` | → `PR-ELIG-001` | ADMISSION |
| 前置互斥 | `PR-PRE-001` | → `PR-PRMUTEX-001` | PREREQUISITE_EXCLUSION |
| 材料 | `PR-MAT-001` | → `PR-MAT-001`（不变） | MATERIAL |
| 销售边界 | `PR-BND-001` | → `PR-SALES-001` | SALES_BOUNDARY |

不存在的 `PR-ADM-004` / `PR-BND-001` / `PR-PRE-001` 全部**映射**（非删除）到清单真实 ID，
不引入规则删除语义。执行器固定执行顺序（有效性 → 监管禁止 → 客户准入 → 前置互斥 →
材料 → 销售边界）**保持不变**——FO-01 仅消除 ID 漂移，不改变求值顺序与求值语义。

## 3. 交付文件与改动清单

| 文件 | 动作 | 说明 |
|---|---|---|
| `src/dkws/application/product_recommendation/eligibility.py` | 修改 | `RULE_CATALOG` 6 条 ruleId 改为清单真实 ID；`ruleVersion` 全部改 `1.0.0-candidate`；注释补 FO-01 映射说明 |
| `tests/integration/test_product_recommendation_eligibility.py` | 修改 + 新增 | 更新旧 ID 引用（`PR-ADM-004`→`PR-ELIG-001`、`PR-PRE-001`→`PR-PRMUTEX-001`、聚合测试 fixture）；新增 `test_rule_catalog_ids_and_versions_align_with_manifest` 锁定精确映射 |
| `tests/integration/test_golden_cases_consistency.py` | 新增 | 新增 `test_executor_rule_catalog_is_subset_of_manifest`：执行器 `RULE_CATALOG ⊆ 清单` 断言 + 版本对齐 + 完备性（无遗漏/无孤儿） |
| `docs/governance/FO-01_RULE_ID_ALIGNMENT.md` | 新增 | 本文档 |

> 未改动：`rule-bundle-manifest.md`（WP2-2 交付物，其 §5「跨包集成待办」描述了本次
> FO-01 所消除的漂移，现已被本任务闭环；该文件属并发任务基线，本任务不代改）。
> 未改动：`rules/*.md`（6 条规则文件）、`rules/README.md`、`golden-cases.json`。

## 4. 测试自证

命令：

```bash
.venv/bin/python -m pytest \
  tests/integration/test_product_recommendation_eligibility.py \
  tests/integration/test_golden_cases_consistency.py -q
```

结果：见 §5（testEvidence 记录命令与退出码，全绿）。

## 5. 边界与诚实声明

- 本任务为 **CANDIDATE** 交付：`FROZEN=NO`、`IMPLEMENTED=NO`，未接运行时，未做真实 E2E。
- 仅消除 `RULE_CATALOG` 的 ruleId/ruleVersion 漂移；规则求值逻辑、失败码、四态闭集聚合
  均未改动。
- 逐组执行器重放 golden-cases.json 的「期望值一致性」断言**不在** FO-01 范围
  （仍属 WP2-3 后续工作），本任务只新增「执行器 ID ⊆ 清单」静态对齐断言。
- 权威基线（`specs/product-recommendation/`、`specs/openapi/...`、`SP-15.json`、
  `AC-PRODUCT-RECOMMEND-001.json`、`modules/scenario-customer-journey/.../recommendation/`、
  `ProductRecommendationApplicationService.java`、`JdbcProductRecommendationRepository.java`）
  本任务未引用、未改动。
