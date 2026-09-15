---
schema: product_card/v1
product_id: PROD-FIN-003
name: 订单融资
product_family: FINANCING
product_family_name: 流动资金融资
version: 1.0.0
status: ACTIVE
effective_from: "2026-09-01T00:00:00+08:00"
effective_to: null
owner: 公司金融产品管理部
reviewer: 公司金融产品管理部（产品 Owner，OQ-02 批准）
published_at: "2026-09-01T00:00:00+08:00"
content_hash: "sha256:d511fc4c629fd99c56d377ad24778b528987fc6bbf4d65ca6a7570b3afb70241"
institutions: [CN-HZ]
prohibited_industries: [REAL_ESTATE, SECURITIES_INVESTMENT]
prohibited_regions: []
prohibited_uses: [EQUITY_INVESTMENT, SECURITIES_INVESTMENT, REAL_ESTATE_INVESTMENT, REPAY_OTHER_BANK_LOAN]
prerequisite_product_ids: [SETTLEMENT_ACCOUNT]
mutex_product_ids: []
required_materials: [ORDER_CONTRACT, BUYER_CREDIT_MATERIAL, PROCUREMENT_PLAN, BUSINESS_LICENSE, FINANCIAL_STATEMENT]
admission_criteria:
  customerTypes: [GENERAL_LEGAL_PERSON]
  minScale: SMALL
  minRating: BBB
  requiredAccountRelationship: SETTLEMENT_ACCOUNT
capabilities: [ORDER_FINANCING, WORKING_CAPITAL]
applicable_scenarios: [LARGE_ORDER_FULFILLMENT]
risk_notes: [ORDER_AUTHENTICITY, BUYER_REJECTION]
complementary_products: [SETTLEMENT_ACCOUNT, ORDER_RECEIVABLE_CLOSED_ACCOUNT]
---

# 产品卡：订单融资（PROD-FIN-003）

> 状态块：
> - **ACTIVE**
> - **FROZEN=YES**
> - **IMPLEMENTED=NO**
>
> 本卡经 OQ-02 产品 Owner 批准自 CANDIDATE 激活为 ACTIVE（reviewer 已指定、EvidenceRef 已登记），
> 进入生产推荐全集。权威制度/条款号仍待核定补齐；FROZEN=YES 表示版本内容冻结，后续修订须新建版本目录。

## 1. 产品概览与客户价值

基于真实采购订单、以订单项下未来回款/货物为保障的融资，用于订单项下备货/生产资金。客户价值：承接优质买方大额订单时，缓解备货/生产资金压力，锁定订单履约能力。

## 2. 适用客户与适用场景

- 适用客户：承接优质买方真实订单、具备稳定履约能力的中型/小型企业。
- 适用场景：接到大额采购订单但缺备货/生产资金；订单回款有账期。

## 3. 产品能力

- 提供订单项下融资（备货/生产资金），订单回款封闭管理。
- 解决：订单备货/生产阶段的前置资金缺口，匹配订单履约周期。

## 4. 准入条件

- 采购订单真实、合法、有效，买方资信良好。
- 企业具备订单履约能力（生产/交付能力可核实）。
- 贸易背景真实，合同齐备可核。
- 在本行开立结算账户，订单回款路径封闭可控。
- 企业主体准入同流动资金贷款基本要求（见 PROD-FIN-001）。

## 5. 排除条件与禁止用途

- 排除条件：虚假/倒签订单；无履约能力的空壳；订单项下未来应收账款已用于其他融资。
- 禁止用途：融资资金不得用于与订单无关用途；不得虚构订单套取资金；同一订单项下不得重复融资。

## 6. 前置、互斥、替代与配套产品

- 前置产品：与买方的真实订单合同、本行结算账户。
- 互斥产品：同一订单项下不得与应收账款质押融资（PROD-FIN-002）对同一未来应收重复融资；不得与其他融资多头重复。
- 替代产品：应收账款质押融资（PROD-FIN-002）可在应收形成阶段衔接。
- 配套产品：对公结算账户、订单回款封闭账户。

## 7. 流程与材料

- 流程：订单审核 → 买方资信核查 → 融资审批与放款 → 订单回款封闭管理 → 结清。
- 材料：订单合同、买方资信材料、采购计划、生产/履约能力证明、营业执照与财报。
- 协同角色：客户经理（受理/订单核实）、供应链金融岗（买方资信/回款封闭）、风险/授信审批岗、放款岗。
- 办理时效口径：T+N 工作日（具体时效以行内制度为准，待核定）。

## 8. 价格边界

- 融资利率与费率按《产品定价管理办法》核定（待核定数值）；融资比例（按订单金额）上限待核定。

## 9. 风险提示与人工复核

- 风险：订单真实性、买方拒付/退货、履约风险、回款路径控制风险。
- 人工复核要求：订单与买方资信必须人工核实；放款与回款监控必须人工复核。

## 10. 销售边界

- 不得虚构订单背景、不得承诺「按订单全额放款」。
- AI/模型不得直接创建授信/放款/审批动作（INV-09）。
- 推荐仅为候选建议，最终以订单核实与审批为准。

## 11. EvidenceRef（源文件与条款定位）

| ref_id | source_id | source_title | clause（条款定位） | 用途 |
|---|---|---|---|---|
| EV-FIN-003-01 | SRC-FIN-003 | 《供应链金融业务操作规程》（行内） | 订单融资审核/放款/回款封闭条款（待核定条款号） | 流程、准入 |
| EV-FIN-003-02 | SRC-FIN-001 | 《流动资金贷款管理办法》（行内） | 用途与融资边界条款（待核定条款号） | 禁止用途 |
| EV-FIN-003-03 | SRC-FIN-002 | 《对公客户准入与评级管理办法》（行内） | 客户/买方资信准入条款（待核定条款号） | 准入条件 |
| EV-FIN-003-04 | SRC-FIN-004 | 《产品定价管理办法》（行内） | 融资利率/费率边界条款（待核定条款号） | 价格边界 |
| EV-FIN-003-05 | REG-FIN-001 | 《流动资金贷款管理暂行办法》（监管） | 用途限制与受托支付标准（待对齐条款号） | 禁止用途 |

## 12. 不可变版本语义

本卡 `version=1.0.0`、`status=ACTIVE`（OQ-02 批准）。ACTIVE 版本内容不可变（FROZEN=YES），只可退役；内容变更需新建版本目录，本卡文件不改写。
