---
schema: product_card/v1
product_id: PROD-TF-002
name: 国内信用证
product_family: TRADE_FINANCE
product_family_name: 贸易融资
version: 1.0.0
status: ACTIVE
effective_from: "2026-09-01T00:00:00+08:00"
effective_to: null
owner: 公司金融产品管理部
reviewer: 公司金融产品管理部（产品 Owner，OQ-02 批准）
published_at: "2026-09-01T00:00:00+08:00"
content_hash: "sha256:tf002hash"
institutions: [CN-HZ]
prohibited_industries: [REAL_ESTATE]
prohibited_regions: []
prohibited_uses: [EQUITY_INVESTMENT]
prerequisite_product_ids: [SETTLEMENT_ACCOUNT]
mutex_product_ids: []
required_materials: [BUSINESS_LICENSE, TRADE_CONTRACT, LETTER_OF_CREDIT_APPLICATION]
admission_criteria:
  customerTypes: [GENERAL_LEGAL_PERSON]
  minScale: SMALL
  minRating: BBB
  requiredAccountRelationship: SETTLEMENT_ACCOUNT
capabilities: [PAYMENT_GUARANTEE, CREDIT_ENHANCEMENT, DOCUMENTARY_COLLECTION]
applicable_scenarios: [TRADE_PAYMENT, RISK_MITIGATION, SUPPLIER_CREDIT_SUPPORT]
risk_notes: [FRAUD_RISK, DOCUMENT_DISCREPANCY, COMPLIANCE_RISK]
complementary_products: [SETTLEMENT_ACCOUNT, BANK_ACCEPTANCE_DRAFT]
---

# 产品卡：国内信用证（PROD-TF-002）

> 状态：ACTIVE | FROZEN=YES | IMPLEMENTED=NO

## 1. 产品概览与客户价值

国内信用证是银行依照申请人申请开立的、对符合信用证条款的单据进行付款的承诺。客户价值：为买卖双方提供银行信用保障，降低交易风险，支持远期付款。

## 2. 适用客户与适用场景

- 适用客户：有国内贸易结算需求、需要银行信用保障的企业。
- 适用场景：贸易支付、风险缓释、供应商信用支持。

## 3. 产品能力

- 开立/通知/议付/付款全流程服务。
- 支持即期/远期信用证。

## 4. 准入条件

- 依法设立并有效存续；证照齐全有效。
- 有真实贸易背景。

<!-- enrich:SRC-TF-002 begin -->
- 准入依据（依据 SRC-TF-002 第四条）：申请开证的客户应满足：一、依法登记并在本行开立结算账户；二、内部评级不低于本行国内信用证业务准入线（见 `SRC-XFAM-001`）；三、已核定**开证额度**；四、基础交易真实、可核验（按 `SRC-TF-003`）。
- 准入依据（依据 SRC-TF-002 第七条）：下列情形不得受理开证：一、基础交易不真实或材料无法核验；二、未落实开证额度或担保；三、客户处于本行名单类管控；四、申请内容与基础交易明显不符。
- 准入依据（依据 SRC-TF-002 第十八条）：本行国内信用证业务准入线为内部评级 BBB 级；评级低于该线的，按《对公客户准入与评级管理办法》（`SRC-XFAM-001`）第八条、第九条处理。
<!-- enrich:SRC-TF-002 end -->

## 5. 排除条件与禁止用途

- 无真实贸易背景的信用证。
- 禁止用于股权投资等非贸易用途。

## 6. 前置、互斥、替代与配套产品

- 前置产品：对公结算账户。
- 配套产品：银行承兑汇票。

## 7. 流程与材料

- 流程：申请开证 → 审核开证 → 通知受益人 → 交单议付 → 付款/承兑。
- 材料：营业执照、贸易合同、信用证开证申请书。

## 8. 价格边界

- 开证手续费、议付利率按行内收费标准执行（待核定）。

<!-- enrich:SRC-TF-002 begin -->
- 定价政策（依据 SRC-TF-002 第六条）：**保证金比例**应在审批意见中明确。**（演示参考值：保证金比例原则上不低于开证金额的 20%；对优质客户可按内部授权下调）** 上述数值为演示参考值，实际执行以本行风险政策与授权为准。
<!-- enrich:SRC-TF-002 end -->

## 9. 风险提示与人工复核

- 风险：欺诈风险、单据不符点风险、合规风险。
- 人工复核要求：开证、付款必须人工审核。

## 10. 销售边界

- 不得违规开立无真实贸易背景的信用证。
- AI/模型不得直接创建信用证（INV-09）。

## 11. 不可变版本语义

本卡 `version=1.0.0`、`status=ACTIVE`。ACTIVE 版本内容不可变（FROZEN=YES），只可退役。
