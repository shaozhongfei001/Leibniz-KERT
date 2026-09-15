---
schema: customer_fact_snapshot/v1
customerId: CUST-CORP-0003
institution: CN-HZ
customerType: GENERAL_LEGAL_PERSON
industry: WHOLESALE_RETAIL
region: CN-310100
scale: LARGE
rating: AA
accountRelationships: [SETTLEMENT_ACCOUNT]
heldProducts: [SETTLEMENT_ACCOUNT, BANK_ACCEPTANCE_DRAFT]
useOfFunds: INTERNATIONAL_TRADE
materials: [BUSINESS_LICENSE, FINANCIAL_STATEMENT, TAX_CERTIFICATE, TRADE_CONTRACT, BANK_STATEMENT, INVOICE, CUSTOMS_DECLARATION, FOREIGN_EXCHANGE_RECEIPT]
needs:
  - needId: NEED-CROSS-BORDER-SETTLEMENT
    needType: CROSS_BORDER
    needStatus: VERIFIED_FACT
    requiredCapabilities: [CROSS_BORDER_PAYMENT, RMB_SETTLEMENT]
    scenario: [IMPORT_EXPORT_SETTLEMENT]
    evidenceRefs: [EV-KI-FRONT-003, EV-KI-FRONT-005]
  - needId: NEED-TRADE-FINANCE
    needType: TRADE_FINANCE
    needStatus: INFERRED_NEED
    requiredCapabilities: [PAYMENT_GUARANTEE, CREDIT_ENHANCEMENT]
    scenario: [TRADE_PAYMENT_GUARANTEE]
    evidenceRefs: [EV-KI-FRONT-004, EV-KI-FRONT-006]
---

# 客户事实快照：鼎信国际贸易集团（CUST-CORP-0003）

> 状态块：
> - **CANDIDATE（OQ-02 演示快照）**
> - **FROZEN=NO**
> - **IMPLEMENTED=NO**

## 事实来源映射

| 事实字段 | 值 | 来源知识条目 |
|---|---|---|
| customerType | GENERAL_LEGAL_PERSON（企业法人） | KI-009 |
| industry | WHOLESALE_RETAIL（批发和零售业） | KI-009 |
| region | CN-310100（上海） | KI-009 |
| scale | LARGE（大型） | KI-009 |
| rating | AA（中风险·战略客户） | KI-009 |
| accountRelationships | SETTLEMENT_ACCOUNT, BANK_ACCEPTANCE_DRAFT | KI-009 |
| useOfFunds | INTERNATIONAL_TRADE（国际贸易） | KI-FRONT-003 / KI-FRONT-005 |
| needs | 跨境结算 + 贸易融资 | KI-FRONT-003 / KI-FRONT-004 / KI-FRONT-006 |
