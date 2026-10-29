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

<!-- enrich:SRC-TF-001 begin -->
- 制度依据（依据 SRC-TF-001 第二条）：本办法所称**银行承兑汇票业务**，是指本行作为承兑人，在客户（出票人）签发汇票后予以承兑，并承诺在汇票到期日无条件付款的业务行为。
- 制度依据（依据 SRC-TF-001 第三条）：本行业务范围包括：承兑、贴现（含转贴现）、以及与本业务相关的查询查复与到期提示付款服务。
<!-- enrich:SRC-TF-001 end -->

## 2. 适用客户与适用场景

- 适用客户：有真实贸易背景、需要延期支付的企业。
- 适用场景：贸易支付、供应商结算、采购融资。

## 3. 产品能力

- 银行信用背书，增强汇票流通性。
- 支持电子/纸质银行承兑汇票。

## 4. 准入条件

- 依法设立并有效存续；证照齐全有效。
- 有真实贸易背景，购销合同/发票齐全。
- 缴纳保证金或提供担保。

<!-- enrich:SRC-TF-001 begin -->
- 准入依据（依据 SRC-TF-001 第五条）：申请承兑的客户应同时满足：一、依法登记且在本行开立结算账户；二、内部评级不低于本行对公承兑业务准入线（见 `SRC-XFAM-001`）；三、与交易对手存在**真实交易背景**（核验按 `SRC-TF-003`）；四、无重大票据违约或不良信用记录。
- 准入依据（依据 SRC-TF-001 第十五条）：查询查复应按票据系统的既定流程办理，查询结果与回复内容应留档；对查询结果异常未澄清前不得办理贴现。
- 准入依据（依据 SRC-TF-001 第二十条）：本行对公承兑业务准入线为内部评级 BBB 级；评级低于该线的，按《对公客户准入与评级管理办法》（`SRC-XFAM-001`）第八条、第九条处理。
<!-- enrich:SRC-TF-001 end -->

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

<!-- enrich:SRC-TF-001 begin -->
- 定价政策（依据 SRC-TF-001 第八条）：**保证金比例**与**担保方式**应在审批意见中明确。**（演示参考值：保证金比例原则上不低于票面金额的 30%；对优质客户可按内部授权下调，但不得低于本行风险下限）** 上述数值为演示参考值，实际执行以本行风险政策与授权为准。
<!-- enrich:SRC-TF-001 end -->

## 9. 风险提示与人工复核

- 风险：担保风险、资金挪用、过度开票。
- 人工复核要求：额度审批、承兑必须人工审核。

## 10. 销售边界

- 不得违规开立无真实贸易背景的承兑汇票。
- AI/模型不得直接创建承兑动作（INV-09）。

## 11. 不可变版本语义

本卡 `version=1.0.0`、`status=ACTIVE`。ACTIVE 版本内容不可变（FROZEN=YES），只可退役。
