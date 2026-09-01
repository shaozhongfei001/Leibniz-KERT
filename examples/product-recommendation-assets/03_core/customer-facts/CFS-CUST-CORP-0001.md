---
schema: customer_fact_snapshot/v1
customerId: CUST-CORP-0001
institution: CN-HZ
customerType: GENERAL_LEGAL_PERSON
industry: MANUFACTURING
region: CN-330100
scale: LARGE
rating: AA
accountRelationships: [SETTLEMENT_ACCOUNT]
heldProducts: [SETTLEMENT_ACCOUNT]
useOfFunds: WORKING_CAPITAL
materials: [BUSINESS_LICENSE, FINANCIAL_STATEMENT, TAX_CERTIFICATE, TRADE_CONTRACT, BANK_STATEMENT, INVOICE, RECEIVABLE_LEDGER, BUYER_CONFIRMATION, ORDER_CONTRACT, GUARANTEE_MATERIAL, DELIVERY_RECEIPT, BUYER_CREDIT_MATERIAL, PROCUREMENT_PLAN]
needs:
  - needId: NEED-WORKING-CAPITAL
    needType: FINANCING
    needStatus: VERIFIED_FACT
    requiredCapabilities: [WORKING_CAPITAL, SHORT_TERM_LIQUIDITY]
    scenario: [WORKING_CAPITAL_TURNOVER]
    evidenceRefs: [EV-KI-FRONT-003, EV-KI-FRONT-006]
  - needId: NEED-RECEIVABLE-FINANCING
    needType: FINANCING
    needStatus: INFERRED_NEED
    requiredCapabilities: [RECEIVABLE_FINANCING]
    scenario: [RECEIVABLE_HIGH_RATIO, LONG_PAYMENT_TERM]
    evidenceRefs: [EV-KI-FRONT-001, EV-KI-FRONT-004]
---

# 客户事实快照：华东精工装备集团（CUST-CORP-0001）

> 状态块：
> - **CANDIDATE（OQ-02 演示快照）**
> - **FROZEN=NO**
> - **IMPLEMENTED=NO**
>
> 本快照为 OQ-02 演示注入的最小结构化事实，从 DKWS 知识条目投影而来
> （KI-009 企业客户基本信息、KI-FRONT-001 供应链图谱、KI-FRONT-003 行内变动、
> KI-FRONT-004 事实承诺、KI-FRONT-006 产品候选组合），非生产级权威事实，
> 仅供 C2 降级 shell 演示三段式硬约束/匹配/组合链路。生产化需由事实 Owner 依据
> 正式 Need 版本与 KYC 系统回填，并替换为权威证据引用。

## 事实来源映射

| 事实字段 | 值 | 来源知识条目 |
|---|---|---|
| customerType | GENERAL_LEGAL_PERSON（企业法人） | KI-009 |
| industry | MANUFACTURING（制造业） | KI-009 / KI-FRONT-002 |
| region | CN-330100（杭州） | KI-009 |
| scale | LARGE（大型） | KI-009 |
| rating | AA（中风险·战略客户） | KI-009 |
| accountRelationships | SETTLEMENT_ACCOUNT（已开立结算账户） | KI-009 |
| useOfFunds | WORKING_CAPITAL（营运资金周转） | KI-FRONT-003 / KI-FRONT-006 |
| needs | 流动资金 + 应收账款融资 | KI-FRONT-003 / KI-FRONT-004 / KI-FRONT-006 |
