---
schema: product_card/v1
product_id: PROD-SET-002
name: 国内保理
product_family: SETTLEMENT
product_family_name: 结算服务
version: 1.0.0
status: ACTIVE
effective_from: "2026-09-01T00:00:00+08:00"
effective_to: null
owner: 公司金融产品管理部
reviewer: 公司金融产品管理部（产品 Owner，OQ-02 批准）
published_at: "2026-09-01T00:00:00+08:00"
content_hash: "sha256:set002hash"
institutions: [CN-HZ]
prohibited_industries: [REAL_ESTATE]
prohibited_regions: []
prohibited_uses: [EQUITY_INVESTMENT]
prerequisite_product_ids: [SETTLEMENT_ACCOUNT]
mutex_product_ids: []
required_materials: [BUSINESS_LICENSE, TRADE_CONTRACT, INVOICE, RECEIVABLE_CONFIRMATION]
admission_criteria:
  customerTypes: [GENERAL_LEGAL_PERSON]
  minScale: SMALL
  minRating: BBB
  requiredAccountRelationship: SETTLEMENT_ACCOUNT
capabilities: [RECEIVABLE_FINANCING, CREDIT_RISK_TRANSFER, COLLECTION_SERVICE]
applicable_scenarios: [ACCOUNT_RECEIVABLE_TURNOVER, SUPPLY_CHAIN_FINANCING]
risk_notes: [BUYER_CREDIT_RISK, DISPUTE_RISK, FRAUD_RISK]
complementary_products: [SETTLEMENT_ACCOUNT, CORPORATE_E_BANK]
---

# 产品卡：国内保理（PROD-SET-002）

> 状态：ACTIVE | FROZEN=YES | IMPLEMENTED=NO

## 1. 产品概览与客户价值

国内保理是银行基于国内贸易中卖方（债权人）的应收账款，提供应收账款融资、账款管理、催收及坏账担保等综合服务。客户价值：加速应收账款周转，改善现金流，转移买方信用风险。

## 2. 适用客户与适用场景

- 适用客户：有稳定下游客户、应收账款账期较长的大中型企业。
- 适用场景：应收账款周转、供应链融资。

## 3. 产品能力

- 提供应收账款融资（有追索/无追索）。
- 账款管理、催收、坏账担保。

## 4. 准入条件

- 依法设立并有效存续；证照齐全有效。
- 经营年限 ≥2 年（待核定）；信用评级 BBB 及以上。
- 应收账款真实、有效、无争议。
- 买方信用良好。

## 5. 排除条件与禁止用途

- 关联交易应收账款；已质押或存在权利瑕疵的应收账款。
- 禁止用于股权投资等非经营用途。

## 6. 前置、互斥、替代与配套产品

- 前置产品：对公结算账户。
- 配套产品：企业网银。

## 7. 流程与材料

- 流程：申请受理 → 尽职调查 → 额度审批 → 签订保理合同 → 融资发放 → 账款催收。
- 材料：营业执照、贸易合同、发票、应收账款确认函。

## 8. 价格边界

- 融资利率以 LPR 为基准加点；保理费率按行内定价办法核定（待核定）。

## 9. 风险提示与人工复核

- 风险：买方信用风险、贸易纠纷风险、欺诈风险。
- 人工复核要求：额度审批、融资发放必须人工审核。

## 10. 销售边界

- 不得承诺"无追索"误导客户（须明确有追索/无追索条款）。
- AI/模型不得直接创建融资或审批动作（INV-09）。

## 11. 不可变版本语义

本卡 `version=1.0.0`、`status=ACTIVE`。ACTIVE 版本内容不可变（FROZEN=YES），只可退役。
