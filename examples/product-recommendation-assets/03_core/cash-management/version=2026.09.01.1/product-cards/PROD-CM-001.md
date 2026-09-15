---
schema: product_card/v1
product_id: PROD-CM-001
name: 现金池
product_family: CASH_MANAGEMENT
product_family_name: 现金管理
version: 1.0.0
status: ACTIVE
effective_from: "2026-09-01T00:00:00+08:00"
effective_to: null
owner: 公司金融产品管理部
reviewer: 公司金融产品管理部（产品 Owner，OQ-02 批准）
published_at: "2026-09-01T00:00:00+08:00"
content_hash: "sha256:cm001hash"
institutions: [CN-HZ]
prohibited_industries: []
prohibited_regions: []
prohibited_uses: []
prerequisite_product_ids: [SETTLEMENT_ACCOUNT]
mutex_product_ids: []
required_materials: [BUSINESS_LICENSE, GROUP_STRUCTURE_CERTIFICATE, ACCOUNT_AUTHORIZATION_LETTER]
admission_criteria:
  customerTypes: [GENERAL_LEGAL_PERSON]
  minScale: MEDIUM
  minRating: A
  requiredAccountRelationship: SETTLEMENT_ACCOUNT
capabilities: [FUND_POOLING, INTER_COMPANY_TRANSFER, INTEREST_OPTIMIZATION, LIQUIDITY_MANAGEMENT]
applicable_scenarios: [GROUP_FUND_CENTRALIZATION, SUBSIDIARY_CASH_MANAGEMENT, INTEREST_SAVINGS]
risk_notes: [REGULATORY_COMPLIANCE, INTER_COMPANY_TRANSACTION_RISK]
complementary_products: [SETTLEMENT_ACCOUNT, CORPORATE_E_BANK]
---

# 产品卡：现金池（PROD-CM-001）

> 状态：ACTIVE | FROZEN=YES | IMPLEMENTED=NO

## 1. 产品概览与客户价值

现金池是银行为集团客户提供的资金集中管理服务，实现集团内各成员单位资金的归集、下拨、调拨和计价，优化集团整体资金使用效率。客户价值：降低集团整体融资成本，提高闲置资金收益，实现资金可视可控。

## 2. 适用客户与适用场景

- 适用客户：集团型企业（母公司+子公司/分公司），有资金集中管理需求。
- 适用场景：集团资金归集、子公司现金管理、利息节约。

## 3. 产品能力

- 资金归集（日终自动/手动归集）。
- 资金下拨、内部调拨、内部计价。

## 4. 准入条件

- 集团型企业，母公司信用评级 A 及以上。
- 成员单位均在本行开立结算账户。
- 集团内部资金管理权限清晰、授权完整。

## 5. 排除条件与禁止用途

- 无明确集团架构或授权关系的主体。
- 禁止用于规避监管的关联交易。

## 6. 前置、互斥、替代与配套产品

- 前置产品：对公结算账户。
- 配套产品：企业网银。

## 7. 流程与材料

- 流程：需求沟通 → 方案设计 → 协议签署 → 系统配置 → 上线运行。
- 材料：营业执照、集团架构证明、账户授权书。

## 8. 价格边界

- 账户管理费、归集手续费按行内收费标准执行（待核定）。

## 9. 风险提示与人工复核

- 风险：监管合规风险、关联交易风险。
- 人工复核要求：方案设计、协议签署必须人工审核。

## 10. 销售边界

- 不得承诺"保本保息"等误导性表述。
- AI/模型不得直接配置资金归集规则（INV-09）。

## 11. 不可变版本语义

本卡 `version=1.0.0`、`status=ACTIVE`。ACTIVE 版本内容不可变（FROZEN=YES），只可退役。
