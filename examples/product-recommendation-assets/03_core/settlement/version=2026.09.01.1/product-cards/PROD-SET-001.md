---
schema: product_card/v1
product_id: PROD-SET-001
name: 单位结算账户
product_family: SETTLEMENT
product_family_name: 结算服务
version: 1.0.0
status: ACTIVE
effective_from: "2026-09-01T00:00:00+08:00"
effective_to: null
owner: 公司金融产品管理部
reviewer: 公司金融产品管理部（产品 Owner，OQ-02 批准）
published_at: "2026-09-01T00:00:00+08:00"
content_hash: "sha256:set001hash"
institutions: [CN-HZ]
prohibited_industries: []
prohibited_regions: []
prohibited_uses: []
prerequisite_product_ids: []
mutex_product_ids: []
required_materials: [BUSINESS_LICENSE, ORGANIZATION_CODE, TAX_CERTIFICATE, LEGAL_REPRESENTATIVE_ID]
admission_criteria:
  customerTypes: [GENERAL_LEGAL_PERSON]
  minScale: MICRO
  minRating: null
  requiredAccountRelationship: null
capabilities: [PAYMENT_SETTLEMENT, FUND_TRANSFER, SALARY_PAYMENT]
applicable_scenarios: [DAILY_SETTLEMENT, SALARY_DISBURSEMENT, TRADE_PAYMENT]
risk_notes: [ANTI_MONEY_LAUNDERING, ABNORMAL_TRANSACTION_MONITORING]
complementary_products: [CORPORATE_E_BANK, CASH_MANAGEMENT]
---

# 产品卡：单位结算账户（PROD-SET-001）

> 状态：ACTIVE | FROZEN=YES | IMPLEMENTED=NO

## 1. 产品概览与客户价值

对公结算账户是银行为企事业单位开立的基本/一般存款账户，提供日常资金收付、转账结算、代发工资等基础服务。客户价值：满足企业日常经营资金收付需求，是所有对公产品的基础账户载体。

## 2. 适用客户与适用场景

- 适用客户：依法设立的企业法人、非法人组织。
- 适用场景：日常资金收付、工资发放、贸易结算。

## 3. 产品能力

- 提供基本/一般/专用/临时存款账户开立与管理。
- 支持现金存取、转账结算、代收代付。

## 4. 准入条件

- 依法设立并有效存续；证照齐全有效。
- 符合反洗钱客户身份识别要求。

## 5. 排除条件与禁止用途

- 无合法经营主体资格的机构。
- 被列入制裁名单或高风险名单的主体。

## 6. 前置、互斥、替代与配套产品

- 前置产品：无。
- 互斥产品：无。
- 配套产品：企业网银、现金管理。

## 7. 流程与材料

- 流程：申请受理 → 客户身份识别 → 账户开立 → 启用。
- 材料：营业执照、组织机构代码证、税务登记证、法定代表人身份证。

## 8. 价格边界

- 账户管理费、转账手续费按行内收费标准执行（待核定）。

## 9. 风险提示与人工复核

- 风险：洗钱风险、异常交易风险。
- 人工复核要求：开户必须人工审核，KYC 尽职调查不可省略。

## 10. 销售边界

- 不得违规开立匿名账户或假名账户。
- AI/模型不得直接创建账户（INV-09）。

## 11. 不可变版本语义

本卡 `version=1.0.0`、`status=ACTIVE`。ACTIVE 版本内容不可变（FROZEN=YES），只可退役。
