---
schema: product_card/v1
product_id: PROD-CB-002
name: 内保外贷
product_family: CROSS_BORDER
product_family_name: 跨境金融
version: 1.0.0
status: ACTIVE
effective_from: "2026-09-01T00:00:00+08:00"
effective_to: null
owner: 国际业务部
reviewer: 国际业务部（产品 Owner，OQ-02 批准）
published_at: "2026-09-01T00:00:00+08:00"
content_hash: "sha256:cb002hash"
institutions: [CN-HZ]
prohibited_industries: [REAL_ESTATE, SECURITIES_INVESTMENT]
prohibited_regions: [SANCTIONED_REGIONS]
prohibited_uses: [CAPITAL_FLIGHT, EQUITY_INVESTMENT, REAL_ESTATE_INVESTMENT]
prerequisite_product_ids: [SETTLEMENT_ACCOUNT]
mutex_product_ids: []
required_materials: [BUSINESS_LICENSE, GUARANTEE_APPLICATION, OVERSEAS_LOAN_AGREEMENT, BOARD_RESOLUTION]
admission_criteria:
  customerTypes: [GENERAL_LEGAL_PERSON]
  minScale: LARGE
  minRating: A
  requiredAccountRelationship: SETTLEMENT_ACCOUNT
capabilities: [CROSS_BORDER_GUARANTEE, OVERSEAS_FINANCING_SUPPORT]
applicable_scenarios: [OVERSEAS_SUBSIDIARY_FINANCING, CROSS_BORDER_INVESTMENT_SUPPORT]
risk_notes: [REGULATORY_COMPLIANCE, GUARANTEE_RISK, FX_RISK, CAPITAL_CONTROL_RISK]
complementary_products: [SETTLEMENT_ACCOUNT, CROSS_BORDER_RMB_SETTLEMENT]
---

# 产品卡：内保外贷（PROD-CB-002）

> 状态：ACTIVE | FROZEN=YES | IMPLEMENTED=NO

## 1. 产品概览与客户价值

内保外贷是境内银行为境内企业开立备用信用证或保函，由境外银行据此向境外企业发放贷款的跨境担保融资模式。客户价值：支持境外子公司/关联公司融资，优化跨境资金安排。

## 2. 适用客户与适用场景

- 适用客户：大型集团企业，有境外子公司融资需求。
- 适用场景：境外子公司融资、跨境投资支持。

## 3. 产品能力

- 开立备用信用证/保函。
- 支持境外银行据此放款。

## 4. 准入条件

- 依法设立并有效存续；信用评级 A 及以上。
- 境内外主体关联关系清晰。
- 符合外汇管理局内保外贷登记要求。

## 5. 排除条件与禁止用途

- 房地产开发、证券投资等禁止用途。
- 禁止用于资本外逃、股权投资等违规用途。

## 6. 前置、互斥、替代与配套产品

- 前置产品：对公结算账户。
- 配套产品：跨境人民币结算。

## 7. 流程与材料

- 流程：业务申请 → 尽职调查 → 额度审批 → 开立保函/备用信用证 → 境外放款 → 到期还款/履约。
- 材料：营业执照、担保申请书、境外贷款协议、董事会决议。

## 8. 价格边界

- 担保费率按行内定价办法核定（待核定）。

## 9. 风险提示与人工复核

- 风险：监管合规风险、担保履约风险、汇率风险、资本管制风险。
- 人工复核要求：额度审批、保函开立必须人工审核。

## 10. 销售边界

- 不得协助规避外汇管理或资本管制。
- AI/模型不得直接创建担保（INV-09）。

## 11. 不可变版本语义

本卡 `version=1.0.0`、`status=ACTIVE`。ACTIVE 版本内容不可变（FROZEN=YES），只可退役。
