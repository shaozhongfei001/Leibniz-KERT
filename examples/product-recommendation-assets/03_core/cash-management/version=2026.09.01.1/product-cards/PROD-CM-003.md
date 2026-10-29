---
schema: product_card/v1
product_id: PROD-CM-003
name: 法人账户透支
product_family: CASH_MANAGEMENT
product_family_name: 现金管理
version: 1.0.0
status: ACTIVE
effective_from: "2026-09-01T00:00:00+08:00"
effective_to: null
owner: 公司金融产品管理部
reviewer: 公司金融产品管理部（产品 Owner，OQ-02 批准）
published_at: "2026-09-01T00:00:00+08:00"
content_hash: "sha256:cm003hash"
institutions: [CN-HZ]
prohibited_industries: [REAL_ESTATE, SECURITIES_INVESTMENT]
prohibited_regions: []
prohibited_uses: [EQUITY_INVESTMENT, SECURITIES_INVESTMENT]
prerequisite_product_ids: [SETTLEMENT_ACCOUNT]
mutex_product_ids: []
required_materials: [BUSINESS_LICENSE, FINANCIAL_STATEMENT, TAX_CERTIFICATE, BANK_STATEMENT]
admission_criteria:
  customerTypes: [GENERAL_LEGAL_PERSON]
  minScale: MEDIUM
  minRating: A
  requiredAccountRelationship: SETTLEMENT_ACCOUNT
capabilities: [OVERDRAFT_FACILITY, SHORT_TERM_LIQUIDITY, AUTOMATIC_REPAYMENT]
applicable_scenarios: [TEMPORARY_LIQUIDITY_GAP, PAYMENT_TIMING_MISMATCH]
risk_notes: [OVERDRAFT_ABUSE, REPAYMENT_CAPACITY_VOLATILITY]
complementary_products: [SETTLEMENT_ACCOUNT, WORKING_CAPITAL_LOAN]
---

# 产品卡：法人账户透支（PROD-CM-003）

> 状态：ACTIVE | FROZEN=YES | IMPLEMENTED=NO

## 1. 产品概览与客户价值

法人账户透支是银行与对公客户签订协议，允许其在结算账户存款不足时在核定额度内透支的融资服务。客户价值：解决临时性资金缺口，无需逐笔审批，随借随还。

<!-- enrich:SRC-CM-002 begin -->
- 制度依据（依据 SRC-CM-002 第二条）：法人账户透支是指本行与法人客户约定，在其结算账户存款余额不足时，在核定额度内由本行提供短期资金融通的安排。
<!-- enrich:SRC-CM-002 end -->

## 2. 适用客户与适用场景

- 适用客户：经营稳定、信用评级较高的中型及以上企业。
- 适用场景：临时性流动性缺口、支付时点错配。

## 3. 产品能力

- 核定透支额度，账户余额不足时自动透支。
- 存入资金自动偿还透支。

## 4. 准入条件

- 依法设立并有效存续；经营年限 ≥3 年（待核定）。
- 在本行开立对公结算账户，结算流水稳定。

<!-- enrich:SRC-CM-002 begin -->
- 准入依据（依据 SRC-CM-002 第十七条）：客户申请法人账户透支，内部评级不低于 A 级；评级低于 A 级的，按《对公客户准入与评级管理办法》（`SRC-XFAM-001`）第八条、第九条处理。
<!-- enrich:SRC-CM-002 end -->

## 5. 排除条件与禁止用途

- 房地产开发、证券投资等禁止用途主体。
- 禁止用于股权投资、证券投资等非经营用途。

## 6. 前置、互斥、替代与配套产品

- 前置产品：对公结算账户。
- 配套产品：流动资金贷款。

## 7. 流程与材料

- 流程：客户申请 → 尽职调查 → 评级与额度核定 → 合同签署 → 系统参数配置 → 放款与贷后管理（依据 SRC-CM-002 第十五条）
- 材料：营业执照、财务报表、纳税证明、银行流水。

## 8. 价格边界

- 透支利率以 LPR 为基准加点，按风险定价（待核定）。

<!-- enrich:SRC-CM-002 begin -->
- 定价政策（依据 SRC-CM-002 第九条）：透支资金按日计息，利率不低于同期贷款市场报价利率加 150 个基点，具体以协议约定为准。
- 定价政策（依据 SRC-CM-002 第十条）：透支服务费按透支额度年化百分之零点五收取，最低每户每年人民币 2000 元。
- 定价政策（依据 SRC-CM-002 第十一条）：逾期未归还透支资金的，自逾期之日起按协议利率上浮百分之五十计收罚息，并暂停新增透支。
<!-- enrich:SRC-CM-002 end -->

## 9. 风险提示与人工复核

- 风险：透支滥用风险、还款能力波动。
- 人工复核要求：额度审批必须人工审核。

## 10. 销售边界

- 不得承诺"无限透支"等误导性表述。
- AI/模型不得直接创建透支额度（INV-09）。

## 11. 不可变版本语义

本卡 `version=1.0.0`、`status=ACTIVE`。ACTIVE 版本内容不可变（FROZEN=YES），只可退役。
