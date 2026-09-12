---
schema: product_card/v1
product_id: PROD-CM-002
name: 资金归集
product_family: CASH_MANAGEMENT
product_family_name: 现金管理
version: 1.0.0
status: ACTIVE
effective_from: "2026-09-01T00:00:00+08:00"
effective_to: null
owner: 公司金融产品管理部
reviewer: 公司金融产品管理部（产品 Owner，OQ-02 批准）
published_at: "2026-09-01T00:00:00+08:00"
content_hash: "sha256:cm002hash"
institutions: [CN-HZ]
prohibited_industries: []
prohibited_regions: []
prohibited_uses: []
prerequisite_product_ids: [SETTLEMENT_ACCOUNT]
mutex_product_ids: []
required_materials: [BUSINESS_LICENSE, ACCOUNT_AUTHORIZATION_LETTER]
admission_criteria:
  customerTypes: [GENERAL_LEGAL_PERSON]
  minScale: SMALL
  minRating: BBB
  requiredAccountRelationship: SETTLEMENT_ACCOUNT
capabilities: [FUND_COLLECTION, AUTOMATIC_SWEEP, BALANCE_MANAGEMENT]
applicable_scenarios: [MULTI_ACCOUNT_MANAGEMENT, DAILY_FUND_COLLECTION, BALANCE_OPTIMIZATION]
risk_notes: [REGULATORY_COMPLIANCE, OPERATION_RISK]
complementary_products: [SETTLEMENT_ACCOUNT, CORPORATE_E_BANK, CASH_POOL]
---

# 产品卡：资金归集（PROD-CM-002）

> 状态：ACTIVE | FROZEN=YES | IMPLEMENTED=NO

## 1. 产品概览与客户价值

资金归集是银行为企业提供的多账户资金自动归集服务，支持定时/实时将下属账户资金归集至主账户。客户价值：实现资金集中管理，减少闲置资金，提高资金使用效率。

## 2. 适用客户与适用场景

- 适用客户：有多账户管理需求的企业或集团。
- 适用场景：多账户管理、日常资金归集、余额优化。

## 3. 产品能力

- 定时/实时资金归集。
- 余额保留、零余额归集等多种归集模式。

## 4. 准入条件

- 依法设立并有效存续；证照齐全有效。
- 信用评级 BBB 及以上。
- 主账户与归集账户均在本行开立。

## 5. 排除条件与禁止用途

- 无明确授权关系的账户归集。
- 禁止用于规避监管的资金划转。

## 6. 前置、互斥、替代与配套产品

- 前置产品：对公结算账户。
- 配套产品：企业网银、现金池。

## 7. 流程与材料

- 流程：需求沟通 → 归集方案设计 → 授权签署 → 系统配置 → 上线运行。
- 材料：营业执照、账户授权书。

## 8. 价格边界

- 归集手续费按行内收费标准执行（待核定）。

## 9. 风险提示与人工复核

- 风险：监管合规风险、操作风险。
- 人工复核要求：归集规则配置必须人工审核。

## 10. 销售边界

- 不得承诺"零风险"等误导性表述。
- AI/模型不得直接配置归集规则（INV-09）。

## 11. 不可变版本语义

本卡 `version=1.0.0`、`status=ACTIVE`。ACTIVE 版本内容不可变（FROZEN=YES），只可退役。
