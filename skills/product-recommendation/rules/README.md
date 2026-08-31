# 产品推荐规则包（RuleBundle）

规则发布必须包含 Owner、版本、生效时间、测试集、影响产品和回滚版本。无证据不得发布硬规则（INV-05）。

## 规则分类（八类）

| 规则类型 | 示例 | 执行方式 |
|---|---|---|
| 有效性规则 | 产品生效/失效、机构范围 | 确定性规则 |
| 监管禁止规则 | 禁止行业/用途/地域 | 确定性规则，FAIL_CLOSED |
| 客户准入规则 | 企业类型/规模/评级/账户关系 | DMN/规则引擎 |
| 前置与互斥规则 | 必须先开户、组合不可并存 | 图关系+规则 |
| 材料规则 | 必须提供合同/订单/报表 | 规则+缺口生成 |
| 场景适配规则 | 跨境/供应链/流动性/司库 | 匹配规则 |
| 排序策略 | 需求匹配/时机/可执行性 | 可配置策略/小模型 |
| 销售边界规则 | 禁止承诺/必须专家介入 | 规则+HumanGate |

## 硬约束执行顺序（第一段，强制）

1. 权限与数据用途 → `FAIL_CLOSED`
2. 产品有效性（ACTIVE + 机构 + asOf）→ `INELIGIBLE`
3. 监管/政策禁止 → `INELIGIBLE`
4. 客户与机构准入 → FAIL=`INELIGIBLE`；缺失=`UNKNOWN`
5. 产品前置条件 → FAIL=排除或转组合依赖
6. 产品互斥与存量冲突 → `INELIGIBLE` 或 `REVIEW_REQUIRED`
7. 销售边界 → 保留边界并强制门禁

## 硬约束不变量

- `INELIGIBLE` 不能通过提高匹配分数重新进入候选；
- `UNKNOWN` 不能转换为"低置信度通过"；
- 每条结论 `ruleId + ruleVersion + inputFactRefs + result + reasonCode`；
- 产品版本过期或规则版本缺失 → 整轮不得产出可批准方案；
- 排除项对客户经理可解释，但敏感内部规则按权限脱敏。

## 排序策略

`FitScore = Σ(wi × mi)` 权重由产品域 Owner 按版本配置，经评审后发布。分数只用于已合格候选内部排序，不代表审批通过概率。

## 规则来源与语义查询

- 语义查询：`SQ-ACTIVE-PRODUCT-VERSIONS`、`SQ-CUSTOMER-NEED-AND-PROJECT`、`SQ-CUSTOMER-RELATIONSHIP`；
- 规则资产落 DKWS 五层工作区（`01_raw → 03_core → 04_serve`），`03_core` 为唯一权威源。
