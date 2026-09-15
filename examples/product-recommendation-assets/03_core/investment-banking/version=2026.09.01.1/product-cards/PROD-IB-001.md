---
schema: product_card/v1
product_id: PROD-IB-001
name: 并购贷款
product_family: INVESTMENT_BANKING
product_family_name: 投资银行
version: 1.0.0
status: ACTIVE
effective_from: "2026-09-01T00:00:00+08:00"
effective_to: null
owner: 投资银行部
reviewer: 投资银行部（产品 Owner，OQ-02 批准）
published_at: "2026-09-01T00:00:00+08:00"
content_hash: "sha256:ib001hash"
institutions: [CN-HZ]
prohibited_industries: [REAL_ESTATE, HIGH_POLLUTION, OVERCAPACITY]
prohibited_regions: []
prohibited_uses: [EQUITY_INVESTMENT_EXCEEDING_LIMIT, REPAY_SHAREHOLDER_LOAN]
prerequisite_product_ids: [SETTLEMENT_ACCOUNT]
mutex_product_ids: []
required_materials: [BUSINESS_LICENSE, MERGER_AGREEMENT, DUE_DILIGENCE_REPORT, VALUATION_REPORT, BOARD_RESOLUTION]
admission_criteria:
  customerTypes: [GENERAL_LEGAL_PERSON]
  minScale: LARGE
  minRating: AA
  requiredAccountRelationship: SETTLEMENT_ACCOUNT
capabilities: [MERGER_FINANCING, ACQUISITION_SUPPORT, STRATEGIC_RESTRUCTURING]
applicable_scenarios: [MERGER_AND_ACQUISITION, STRATEGIC_RESTRUCTURING, INDUSTRY_CONSOLIDATION]
risk_notes: [INTEGRATION_RISK, VALUATION_RISK, REGULATORY_RISK, LEVERAGE_RISK]
complementary_products: [SETTLEMENT_ACCOUNT, FINANCIAL_ADVISORY]
---

# 产品卡：并购贷款（PROD-IB-001）

> 状态：ACTIVE | FROZEN=YES | IMPLEMENTED=NO

## 1. 产品概览与客户价值

并购贷款是银行向并购方发放的、用于支付并购交易价款的贷款。客户价值：支持企业战略并购与产业整合，降低并购资金压力。

## 2. 适用客户与适用场景

- 适用客户：大型企业，有战略并购或产业整合需求。
- 适用场景：并购与收购、战略重组、产业整合。

## 3. 产品能力

- 提供并购交易价款融资。
- 支持同一控制下/非同一控制下并购。

## 4. 准入条件

- 依法设立并有效存续；信用评级 AA 及以上。
- 并购交易合法合规，符合国家产业政策。
- 并购方与目标企业有产业协同。
- 并购贷款占比不超过交易价款的 60%（监管要求）。

## 5. 排除条件与禁止用途

- 房地产开发、高污染、产能过剩行业并购。
- 禁止用于超出监管比例的股权投资、偿还股东借款等。

## 6. 前置、互斥、替代与配套产品

- 前置产品：对公结算账户。
- 配套产品：财务顾问。

## 7. 流程与材料

- 流程：业务申请 → 尽职调查 → 并购方案评估 → 审批 → 签订合同 → 放款 → 贷后管理。
- 材料：营业执照、并购协议、尽职调查报告、估值报告、董事会决议。

## 8. 价格边界

- 利率以 LPR 为基准加点，按风险定价（待核定）。

## 9. 风险提示与人工复核

- 风险：整合风险、估值风险、监管风险、杠杆风险。
- 人工复核要求：尽职调查、审批、放款必须人工审核。

## 10. 销售边界

- 不得承诺"必批"等误导性表述。
- AI/模型不得直接创建贷款或审批动作（INV-09）。

## 11. 不可变版本语义

本卡 `version=1.0.0`、`status=ACTIVE`。ACTIVE 版本内容不可变（FROZEN=YES），只可退役。
