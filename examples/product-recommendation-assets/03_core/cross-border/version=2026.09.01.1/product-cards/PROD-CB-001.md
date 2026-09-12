---
schema: product_card/v1
product_id: PROD-CB-001
name: 跨境人民币结算
product_family: CROSS_BORDER
product_family_name: 跨境金融
version: 1.0.0
status: ACTIVE
effective_from: "2026-09-01T00:00:00+08:00"
effective_to: null
owner: 国际业务部
reviewer: 国际业务部（产品 Owner，OQ-02 批准）
published_at: "2026-09-01T00:00:00+08:00"
content_hash: "sha256:cb001hash"
institutions: [CN-HZ]
prohibited_industries: []
prohibited_regions: [SANCTIONED_REGIONS]
prohibited_uses: [CAPITAL_FLIGHT, SANCTIONED_TRADE]
prerequisite_product_ids: [SETTLEMENT_ACCOUNT]
mutex_product_ids: []
required_materials: [BUSINESS_LICENSE, CROSS_BORDER_TRADE_CONTRACT, CUSTOMS_DECLARATION, FOREIGN_EXCHANGE_RECEIPT]
admission_criteria:
  customerTypes: [GENERAL_LEGAL_PERSON]
  minScale: SMALL
  minRating: BBB
  requiredAccountRelationship: SETTLEMENT_ACCOUNT
capabilities: [CROSS_BORDER_PAYMENT, RMB_SETTLEMENT, FX_CONVERSION]
applicable_scenarios: [IMPORT_SETTLEMENT, EXPORT_SETTLEMENT, SERVICE_TRADE_SETTLEMENT]
risk_notes: [REGULATORY_COMPLIANCE, FX_RISK, SANCTION_RISK]
complementary_products: [SETTLEMENT_ACCOUNT, FX_FORWARD]
---

# 产品卡：跨境人民币结算（PROD-CB-001）

> 状态：ACTIVE | FROZEN=YES | IMPLEMENTED=NO

## 1. 产品概览与客户价值

跨境人民币结算是银行为企业提供的以人民币为结算货币的跨境收付款服务。客户价值：规避汇率风险，降低汇兑成本，简化跨境结算流程。

## 2. 适用客户与适用场景

- 适用客户：有进出口贸易或服务贸易跨境结算需求的企业。
- 适用场景：进口结算、出口结算、服务贸易结算。

## 3. 产品能力

- 跨境人民币汇款/收款。
- 人民币购售汇。
- 跨境人民币账户管理。

## 4. 准入条件

- 依法设立并有效存续；具备进出口经营资格。
- 信用评级 BBB 及以上。
- 真实跨境贸易背景，外汇合规。

## 5. 排除条件与禁止用途

- 制裁地区交易。
- 禁止用于资本外逃、制裁贸易等违规用途。

## 6. 前置、互斥、替代与配套产品

- 前置产品：对公结算账户。
- 配套产品：远期结售汇。

## 7. 流程与材料

- 流程：业务申请 → 贸易背景审核 → 汇款/收款 → 申报。
- 材料：营业执照、跨境贸易合同、海关报关单、外汇收汇凭证。

## 8. 价格边界

- 汇款手续费、汇兑点差按行内收费标准执行（待核定）。

## 9. 风险提示与人工复核

- 风险：监管合规风险、汇率风险、制裁风险。
- 人工复核要求：大额/敏感交易必须人工审核。

## 10. 销售边界

- 不得协助规避外汇监管。
- AI/模型不得直接执行跨境汇款（INV-09）。

## 11. 不可变版本语义

本卡 `version=1.0.0`、`status=ACTIVE`。ACTIVE 版本内容不可变（FROZEN=YES），只可退役。
