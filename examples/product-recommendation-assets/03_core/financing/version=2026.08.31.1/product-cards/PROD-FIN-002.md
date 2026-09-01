---
schema: product_card/v1
product_id: PROD-FIN-002
name: 应收账款质押融资
product_family: FINANCING
product_family_name: 流动资金融资
version: 1.0.0
status: ACTIVE
effective_from: "2026-09-01T00:00:00+08:00"
effective_to: null
owner: 公司金融产品管理部
reviewer: 公司金融产品管理部（产品 Owner，OQ-02 批准）
published_at: "2026-09-01T00:00:00+08:00"
content_hash: "sha256:5980a7c401a963f7e65e8965b961af1b291a1e85788213c57225d306ebcb1a3a"
institutions: [CN-HZ]
prohibited_industries: [REAL_ESTATE, SECURITIES_INVESTMENT]
prohibited_regions: []
prohibited_uses: [EQUITY_INVESTMENT, SECURITIES_INVESTMENT, REAL_ESTATE_INVESTMENT, REPAY_OTHER_BANK_LOAN]
prerequisite_product_ids: [SETTLEMENT_ACCOUNT]
mutex_product_ids: []
required_materials: [TRADE_CONTRACT, INVOICE, DELIVERY_RECEIPT, BUYER_CONFIRMATION, RECEIVABLE_LEDGER, BUSINESS_LICENSE, FINANCIAL_STATEMENT]
admission_criteria:
  customerTypes: [GENERAL_LEGAL_PERSON]
  minScale: SMALL
  minRating: BBB
  requiredAccountRelationship: SETTLEMENT_ACCOUNT
capabilities: [RECEIVABLE_FINANCING, WORKING_CAPITAL]
applicable_scenarios: [RECEIVABLE_HIGH_RATIO, LONG_PAYMENT_TERM]
risk_notes: [RECEIVABLE_AUTHENTICITY, BUYER_CREDIT_RISK]
complementary_products: [SETTLEMENT_ACCOUNT, RECEIVABLE_LEDGER_TOOL]
---

# 产品卡：应收账款质押融资（PROD-FIN-002）

> 状态块：
> - **ACTIVE**
> - **FROZEN=YES**
> - **IMPLEMENTED=NO**
>
> 本卡经 OQ-02 产品 Owner 批准自 CANDIDATE 激活为 ACTIVE（reviewer 已指定、EvidenceRef 已登记），
> 进入生产推荐全集。权威制度/条款号仍待核定补齐；FROZEN=YES 表示版本内容冻结，后续修订须新建版本目录。

## 1. 产品概览与客户价值

以企业真实、合法、可转让的应收账款设定质押/转让为基础提供融资。客户价值：盘活账期长、回款慢的应收账款，改善现金流，降低对传统担保的依赖。

## 2. 适用客户与适用场景

- 适用客户：持有稳定、真实应收账款（买方为核心企业/优质买方）的中型/小型企业。
- 适用场景：应收账款占比高、账期长、回款慢；向优质买方赊销形成应收。

## 3. 产品能力

- 提供应收账款质押/转让融资（有追索/无追索待核定）。
- 解决：应收账款占用营运资金、回款周期长导致的流动性缺口。

## 4. 准入条件

- 应收账款真实、合法、可转让，无权利负担。
- 买方资信良好、有履约能力（核心企业/优质买方优先，待核定）。
- 贸易背景真实，合同/发票/发货单据齐备可核。
- 在本行开立结算账户，回款路径可控。
- 企业主体准入同流动资金贷款基本要求（见 PROD-FIN-001）。

## 5. 排除条件与禁止用途

- 排除条件：虚假贸易、虚构/重复应收账款；买方为无法核实的关联方（待核定）；应收账款已转让/已质押/已用于其他融资。
- 禁止用途：融资资金不得流向与贸易背景无关用途；不得虚构应收套取资金；同一笔应收账款不得重复质押融资。

## 6. 前置、互斥、替代与配套产品

- 前置产品：与买方的真实贸易合同、本行结算账户。
- 互斥产品：同一笔应收账款不得与流动资金贷款（PROD-FIN-001）或其他融资重复融资；不得重复质押。
- 替代产品：订单融资（PROD-FIN-003）可按订单阶段替代（真实订单备货阶段）。
- 配套产品：对公结算账户、应收账款台账/确权工具。

## 7. 流程与材料

- 流程：应收账款确权 → 中登网登记 → 融资审批与放款 → 回款管理 → 核销/结清。
- 材料：贸易合同、发票、发货/验收单据、买方确认函、应收账款台账、营业执照与财报。
- 协同角色：客户经理（受理/确权）、供应链金融岗（登记/回款监控）、风险/授信审批岗、放款岗。
- 办理时效口径：T+N 工作日（具体时效以行内制度为准，待核定）。

## 8. 价格边界

- 融资利率 + 登记费等按《产品定价管理办法》核定（待核定数值）。
- 融资比例（质押率）上限按制度核定（待核定）。

## 9. 风险提示与人工复核

- 风险：应收账款真实性、买方信用风险、回款路径控制风险、重复融资风险。
- 人工复核要求：确权与贸易背景必须人工核实；放款与回款监控必须人工复核。

## 10. 销售边界

- 不得虚构贸易背景、不得承诺「无需核实」放款。
- AI/模型不得直接创建授信/放款/审批动作（INV-09）。
- 推荐仅为候选建议，最终以确权核实与审批为准。

## 11. EvidenceRef（源文件与条款定位）

| ref_id | source_id | source_title | clause（条款定位） | 用途 |
|---|---|---|---|---|
| EV-FIN-002-01 | SRC-FIN-003 | 《供应链金融业务操作规程》（行内） | 应收账款确权/登记/放款流程条款（待核定条款号） | 流程、准入 |
| EV-FIN-002-02 | SRC-FIN-001 | 《流动资金贷款管理办法》（行内） | 用途与融资边界条款（待核定条款号） | 禁止用途 |
| EV-FIN-002-03 | SRC-FIN-002 | 《对公客户准入与评级管理办法》（行内） | 客户/买方资信准入条款（待核定条款号） | 准入条件 |
| EV-FIN-002-04 | SRC-FIN-004 | 《产品定价管理办法》（行内） | 融资利率/费率边界条款（待核定条款号） | 价格边界 |
| EV-FIN-002-05 | SRC-FIN-005 | 《流动资金贷款风险管理指引》（行内） | 应收账款真实性/回款风险条款（待核定条款号） | 风险提示 |

## 12. 不可变版本语义

本卡 `version=1.0.0`、`status=ACTIVE`（OQ-02 批准）。ACTIVE 版本内容不可变（FROZEN=YES），只可退役；内容变更需新建版本目录，本卡文件不改写。
