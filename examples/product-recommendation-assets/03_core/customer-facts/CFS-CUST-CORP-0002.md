---
schema: customer_fact_snapshot/v1
customerId: CUST-CORP-0002
institution: CN-HZ
customerType: GENERAL_LEGAL_PERSON
industry: WHOLESALE_RETAIL
region: CN-440300
scale: MEDIUM
rating: A
accountRelationships: [SETTLEMENT_ACCOUNT]
heldProducts: [SETTLEMENT_ACCOUNT]
useOfFunds: SUPPLY_CHAIN_OPERATIONS
materials: [BUSINESS_LICENSE, FINANCIAL_STATEMENT, TAX_CERTIFICATE, TRADE_CONTRACT, BANK_STATEMENT, INVOICE]
needs:
  - needId: NEED-SUPPLY-CHAIN-SETTLEMENT
    needType: SETTLEMENT
    needStatus: VERIFIED_FACT
    requiredCapabilities: [PAYMENT_SETTLEMENT, FUND_TRANSFER]
    scenario: [SUPPLY_CHAIN_PAYMENT]
    evidenceRefs: [EV-KI-FRONT-003]
  - needId: NEED-CASH-MANAGEMENT
    needType: CASH_MANAGEMENT
    needStatus: INFERRED_NEED
    requiredCapabilities: [FUND_POOLING, INTER_COMPANY_TRANSFER]
    scenario: [GROUP_FUND_CENTRALIZATION]
    evidenceRefs: [EV-KI-FRONT-006]
---

# 客户事实快照：汇通供应链管理公司（CUST-CORP-0002）

> 状态块：
> - **CANDIDATE（OQ-02 演示快照）**
> - **FROZEN=NO**
> - **IMPLEMENTED=NO**

## 事实来源映射

| 事实字段 | 值 | 来源知识条目 |
|---|---|---|
| customerType | GENERAL_LEGAL_PERSON（企业法人） | KI-009 |
| industry | WHOLESALE_RETAIL（批发和零售业） | KI-009 |
| region | CN-440300（深圳） | KI-009 |
| scale | MEDIUM（中型） | KI-009 |
| rating | A（中低风险·重点客户） | KI-009 |
| accountRelationships | SETTLEMENT_ACCOUNT（已开立结算账户） | KI-009 |
| useOfFunds | SUPPLY_CHAIN_OPERATIONS（供应链运营） | KI-FRONT-003 |
| needs | 供应链结算 + 现金管理 | KI-FRONT-003 / KI-FRONT-006 |
