# RuleBundle 清单：产品推荐硬规则包（候选种子）

```text
DOC_STATUS=CANDIDATE
FROZEN=NO
IMPLEMENTED=NO
REAL_E2E_PASS=NO
```

> 目录：`skills/product-recommendation/rules/`
> 上游结构定义：`rules/README.md`（八类规则 + 硬约束执行顺序，已验收、本任务不改动）
> 权威基线：GITS《产品推荐三段式决策详细落地方案 V1.0》§8.2 / §13.1 + `SP-15.md` §2 / §7

## 1. RuleBundle 身份

| 字段 | 值 |
|---|---|
| ruleBundleId | `RB-PR-20260831-0001` |
| version | `1.0.0-candidate` |
| releaseOwner | 公司金融产品管理部（产品域 Owner，OQ-02 裁决后回填） |
| effectiveFrom | `2026-08-31T00:00:00+08:00`（候选；正式生效须 Owner 审核发布） |
| rollbackVersion | `null`（首个候选版本，无历史版本可回滚；回滚仅切换指针、不删除规则文件） |
| status | `CANDIDATE` |
| schemaVersion | `1.0.0` |

## 2. 规则清单（6 条硬规则种子）

> 顺序号沿用 `rules/README.md`「硬约束执行顺序」。顺序 1（权限与数据用途 → `FAIL_CLOSED`）由 `AC-PRODUCT-RECOMMEND-001` 与 SP-15 执行前置覆盖，不在本规则包内。

| 顺序 | 规则类型 | ruleId | ruleVersion | 文件 | 失败策略 |
|---|---|---|---|---|---|
| 2 | 有效性规则 | `PR-VALID-001` | `1.0.0-candidate` | `PR-VALID-001.md` | 产品级 `INELIGIBLE`；无有效版本 → 整轮 `FAIL_CLOSED` |
| 3 | 监管禁止规则 | `PR-REG-001` | `1.0.0-candidate` | `PR-REG-001.md` | `INELIGIBLE`（`FAIL_CLOSED`） |
| 4 | 客户准入规则 | `PR-ELIG-001` | `1.0.0-candidate` | `PR-ELIG-001.md` | FAIL → `INELIGIBLE`；缺失 → `UNKNOWN` |
| 5 | 前置与互斥规则 | `PR-PRMUTEX-001` | `1.0.0-candidate` | `PR-PRMUTEX-001.md` | 排除 / 转组合依赖 / `INELIGIBLE` / `REVIEW_REQUIRED` |
| 6 | 材料规则 | `PR-MAT-001` | `1.0.0-candidate` | `PR-MAT-001.md` | 缺口生成（不硬阻断 `ELIGIBLE`） |
| 7 | 销售边界规则 | `PR-SALES-001` | `1.0.0-candidate` | `PR-SALES-001.md` | 保留边界 + 强制 HumanGate |

## 3. 测试集引用

- 黄金样例：`golden-cases.json`（本目录），8 组正反样例，映射 `TC-PR-001` ~ `TC-PR-008`。
- 必覆盖「硬失败不可绕过」：`TC-PR-002`（监管禁止 → `INELIGIBLE`）、`TC-PR-004`（版本失效 → `FAIL_CLOSED`）、`TC-PR-008`（高分不能覆盖 `INELIGIBLE`）。
- 规则单元/边界值测试：`rules/README.md` §硬约束执行顺序 与 GITS §13.2（材料、销售边界的负分支由各规则文件的结论表承载，未单列 TC-PR 业务用例）。

## 4. 回滚版本

- `rollbackVersion = null`（首个候选版本）。
- 回滚语义：只切换 RuleBundle 指针，不删除规则文件；规则文件按版本目录组织，发布后不可变、只可退役（对齐 `rules/README.md` 与 `product-cards/README.md`「不可变版本语义」）。

## 5. 边界与诚实声明

- 全部规则为 `CANDIDATE`，`FROZEN=NO`，未实现、未接运行时。
- 规则 EvidenceRef 指向的源材料（`SRC-FIN-*` / `REG-FIN-*`）当前为 `PENDING_SOURCE`（材料待上传、条款号待 Owner 核定），故本包**不可作生产发布**（`INV-05` 无证据不得发布硬规则）。
- 产品 ID 与条款号待公司金融产品 Owner（`OQ-02`）裁决后回填。
