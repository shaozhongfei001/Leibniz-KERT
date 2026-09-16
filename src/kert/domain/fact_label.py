"""断言事实标签值域（F/C/B/H/P/A）：合同 `enum` 的**单一命名源**（D-28 层 2 第五片）。

**为什么这处该立源**（自问"是不是外部结论 / 推模式入参的如实镜像"）：**不是**。
标签虽由上游断言携带，但 **KERT 自己定义闭集并据此放行/过滤/上色** ——
`proposal_rules.evaluate` 用 `FACT_LABELS` 做**必填校验**（未知标签 ⇒ `FACT_LABEL_MANDATORY` 违规）、
`_filter_customer` 用 `CUSTOMER_SAFE_LABELS` 决定**哪些段落进对客版**、
`report` 用它上色/译名 ⇒ 实现侧**拥有**该词汇且**按名比较**（改名会静默改变放行行为）。

立源前实测**重复源三份 + 按名比较五处**：`proposal_rules.VALID_LABELS`（集合）、
`report.LABEL_CN` / `report.LABEL_COLOR`（两张六键映射）、`service_proposal` 的
`("F","A")` / `("C","B")` / `"P"` 与 `proposal_rules` 的同形比较。

三处分工：源（本模块）↔ 生产者/消费者（上述模块）↔ 合同（OpenAPI `Citation.factLabel`，
登记在 `tests/unit/test_contract_enum_single_source.py` 的 ``MAPPINGS``）。

⚠ **边界（不得合并）**：`product_recommendation/eligibility._RATING_ORDER`
（`BBB/A/AA/AAA`，信用评级域）与本域**仅值 `A` 重叠、语义域不同**（清单的"部分重叠"是假阳性）。
"""

from __future__ import annotations

#: 断言事实标签值域（顺序 = 合同 `enum` 顺序）。合同侧必须与本元组**等值**。
FACT_LABELS: tuple[str, ...] = ("F", "C", "B", "H", "P", "A")
#: 具名常量：生产者/消费者**不得**再散落单标签字面量（改名只动上面这一处）。
(
    LABEL_FACT,          # F 事实
    LABEL_INFERENCE,     # C 推论
    LABEL_BELIEF,        # B 信念
    LABEL_HYPOTHESIS,    # H 假设
    LABEL_PREDICTION,    # P 预测
    LABEL_ASSERTION,     # A 断言
) = FACT_LABELS

#: 可进**对客版**的标签（原实现写作字面量 `("F", "A")`，多处重复）。
CUSTOMER_SAFE_LABELS: tuple[str, ...] = (LABEL_FACT, LABEL_ASSERTION)
#: `CUSTOMER_SAFE_LABELS` 的补集（**保序**派生：`("C","B","H","P")`，与既有输出的字节一致）。
NON_CUSTOMER_SAFE_LABELS: tuple[str, ...] = tuple(
    lb for lb in FACT_LABELS if lb not in CUSTOMER_SAFE_LABELS)
#: 内部风险红旗（原实现写作字面量 `("C", "B")`）。
RISK_LABELS: tuple[str, ...] = (LABEL_INFERENCE, LABEL_BELIEF)
#: G3 前不得承诺的**预测**标签（原实现写作字面量 `== "P"`）。
PENDING_LABEL: str = LABEL_PREDICTION
