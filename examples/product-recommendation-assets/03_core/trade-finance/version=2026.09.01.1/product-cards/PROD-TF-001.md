---
schema: product_card/v1
product_id: PROD-TF-001
name: 银行承兑汇票
product_family: TRADE_FINANCE
product_family_name: 贸易融资
version: 1.0.0
status: ACTIVE
effective_from: "2026-09-01T00:00:00+08:00"
effective_to: null
owner: 公司金融产品管理部
reviewer: 公司金融产品管理部（产品 Owner，OQ-02 批准）
published_at: "2026-09-01T00:00:00+08:00"
content_hash: "sha256:tf001hash"
institutions: [CN-HZ]
prohibited_industries: [REAL_ESTATE]
prohibited_regions: []
prohibited_uses: [EQUITY_INVESTMENT, REAL_ESTATE_INVESTMENT]
prerequisite_product_ids: [SETTLEMENT_ACCOUNT]
mutex_product_ids: []
required_materials: [BUSINESS_LICENSE, TRADE_CONTRACT, INVOICE, GUARANTEE_DEPOSIT]
admission_criteria:
  customerTypes: [GENERAL_LEGAL_PERSON]
  minScale: SMALL
  minRating: BBB
  requiredAccountRelationship: SETTLEMENT_ACCOUNT
capabilities: [PAYMENT_GUARANTEE, CREDIT_ENHANCEMENT, DEFERRED_PAYMENT]
applicable_scenarios: [TRADE_PAYMENT, SUPPLIER_SETTLEMENT, PURCHASE_FINANCING]
risk_notes: [GUARANTEE_RISK, FUND_MISUSE, OVER_ISSUANCE]
complementary_products: [SETTLEMENT_ACCOUNT, DISCOUNT_SERVICE]
---

# 产品卡：银行承兑汇票（PROD-TF-001）

> 状态：ACTIVE | FROZEN=YES | IMPLEMENTED=NO

## 1. 产品概览与客户价值

银行承兑汇票是银行作为承兑人，对出票人签发的商业汇票进行承兑，承诺在汇票到期日无条件支付确定金额给收款人或持票人的票据行为。客户价值：增强商业信用，延期支付，降低融资成本。

## 2. 适用客户与适用场景

- 适用客户：有真实贸易背景、需要延期支付的企业。
- 适用场景：贸易支付、供应商结算、采购融资。

## 3. 产品能力

- 银行信用背书，增强汇票流通性。
- 支持电子/纸质银行承兑汇票。

## 4. 准入条件

- 依法设立并有效存续；证照齐全有效。
- 信用评级 BBB 及以上。
- 有真实贸易背景，购销合同/发票齐全。
- 缴纳保证金或提供担保。

## 5. 排除条件与禁止用途

- 无真实贸易背景的融资性票据。
- 禁止用于股权投资、房地产投资等。

## 6. 前置、互斥、替代与配套产品

- 前置产品：对公结算账户。
- 配套产品：贴现服务。

## 7. 流程与材料

- 流程：申请受理 → 尽职调查 → 额度审批 → 承兑 → 到期付款。
- 材料：营业执照、贸易合同、发票、保证金/担保材料。

## 8. 价格边界

- 承兑手续费按票面金额的 0.5‰（待核定）；保证金比例按风险定价。

## 9. 风险提示与人工复核

- 风险：担保风险、资金挪用、过度开票。
- 人工复核要求：额度审批、承兑必须人工审核。

## 10. 销售边界

- 不得违规开立无真实贸易背景的承兑汇票。
- AI/模型不得直接创建承兑动作（INV-09）。

## 11. 不可变版本语义

本卡 `version=1.0.0`、`status=ACTIVE`。ACTIVE 版本内容不可变（FROZEN=YES），只可退役。
