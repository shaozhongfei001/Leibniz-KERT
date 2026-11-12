---
schema: product_card/v1
product_id: PROD-FIN-001
name: 流动资金贷款
product_family: FINANCING
product_family_name: 流动资金融资
version: 1.0.0
status: ACTIVE
effective_from: "2026-09-01T00:00:00+08:00"
effective_to: null
owner: 公司金融产品管理部
reviewer: 公司金融产品管理部（产品 Owner，OQ-02 批准）
published_at: "2026-09-01T00:00:00+08:00"
content_hash: "sha256:b9ffc0b4227902f4481002386816ce93ea167cf2ce80e5f5405a04b50fc0b240"
institutions: [CN-HZ]
prohibited_industries: [REAL_ESTATE, SECURITIES_INVESTMENT]
prohibited_regions: []
prohibited_uses: [EQUITY_INVESTMENT, SECURITIES_INVESTMENT, REAL_ESTATE_INVESTMENT, REPAY_OTHER_BANK_LOAN]
prerequisite_product_ids: [SETTLEMENT_ACCOUNT]
mutex_product_ids: []
required_materials: [BUSINESS_LICENSE, FINANCIAL_STATEMENT, TAX_CERTIFICATE, TRADE_CONTRACT, BANK_STATEMENT, GUARANTEE_MATERIAL]
admission_criteria:
  customerTypes: [GENERAL_LEGAL_PERSON]
  minScale: SMALL
  minRating: BB
  requiredAccountRelationship: SETTLEMENT_ACCOUNT
capabilities: [WORKING_CAPITAL, SHORT_TERM_LIQUIDITY, REVOLVING_CREDIT]
applicable_scenarios: [WORKING_CAPITAL_TURNOVER, SEASONAL_STOCKING]
risk_notes: [REPAYMENT_CAPACITY_VOLATILITY, FUND_MISUSE]
complementary_products: [SETTLEMENT_ACCOUNT, CORPORATE_E_BANK, CASH_MANAGEMENT]
---

# 产品卡：流动资金贷款（PROD-FIN-001）

> 状态块：
> - **ACTIVE**
> - **FROZEN=YES**
> - **IMPLEMENTED=NO**
>
> 本卡经 OQ-02 产品 Owner 批准自 CANDIDATE 激活为 ACTIVE（reviewer 已指定、EvidenceRef 已登记），
> 进入生产推荐全集。权威制度/条款号仍待核定补齐；FROZEN=YES 表示版本内容冻结，后续修订须新建版本目录。

## 1. 产品概览与客户价值

短期流动资金贷款，用于企业日常生产经营周转（采购原材料、季节性备货、营运资金周转等），期限 ≤1 年（循环/非循环额度待核定）。客户价值：以授信额度平滑日常营运资金缺口，随借随还、按实际占用计息，避免一次性中长期负债。

<!-- enrich:SRC-FIN-001 begin -->
- 制度依据（依据 SRC-FIN-001 第四条）：本办法所称借款人应为依法登记并存续的法人或非法人组织；按照国家有关规定不得办理银行贷款的主体除外。
<!-- enrich:SRC-FIN-001 end -->

## 2. 适用客户与适用场景

- 适用客户：依法设立、正常经营满 2 年（待核定）、信用评级达标、有稳定经营流水与真实经营背景的中型/小型企业。
- 适用场景：原材料采购、季节性备货、订单备货、日常营运资金周转、短期流动性补充。

## 3. 产品能力

- 提供短期流动资金授信额度，支持循环/非循环使用（待核定）。
- 解决：日常生产经营中的短期营运资金缺口，匹配真实购销/经营周期。

## 4. 准入条件

- 依法设立并有效存续；证照齐全有效。
- 经营年限 ≥2 年（待核定）；具有真实、持续的经营与还款能力。

- 无重大不良信用记录、无失信被执行等负面信息。
- 在本行开立对公结算账户，结算流水可核实。
- 资金用途合法合规、与经营背景匹配。
- 提供足额合法有效担保或经信用审批通过。

<!-- enrich:SRC-FIN-001 begin -->
- 准入依据（依据 SRC-FIN-001 第四条）：本办法所称借款人应为依法登记并存续的法人或非法人组织；按照国家有关规定不得办理银行贷款的主体除外。
- 准入依据（依据 SRC-FIN-001 第五条）：借款人应同时满足下列基本条件：一、依法经市场监督管理部门或主管部门核准登记；二、借款用途明确、合法；三、具有持续经营能力与合法还款来源；四、信用状况良好、近十二个月无重大结算违规记录；五、内部评级不低于本办法第六条要求。
- 准入依据（依据 SRC-FIN-001 第六条）：内部评级与受理档位统一按《对公客户准入与评级管理办法》（`SRC-XFAM-001`）第八条（档位矩阵）、第九条（双签审批）执行；本办法不再另行规定评级档位，避免与统一办法出现两套口径。
- 准入依据（依据 SRC-FIN-001 第七条）：下列情形不得受理：一、借款用途属本办法第九条禁止用途；二、被列入本行制裁或限制名单；三、近十二个月发生贷款资金挪用且未整改完毕。
- 准入依据（依据 SRC-FIN-001 第二十条）：本行流动资金贷款业务准入线为内部评级 BB 级；评级低于该线的，按《对公客户准入与评级管理办法》（`SRC-XFAM-001`）第八条、第九条处理。品种适用范围（**非准入门槛**）：内部评级 AA 级（含）以上的客户可申请全部流动资金贷款品种，BB 级至 A 级客户限申请标准流动资金贷款品种。
<!-- enrich:SRC-FIN-001 end -->

## 5. 排除条件与禁止用途

- 排除条件：房地产开发、股票/债券/理财等投资性用途主体；无真实贸易背景；产能过剩/淘汰类行业；空壳或无实际经营企业；失信被执行人。
- 禁止用途：不得用于股权投资、证券投资、固定资产投资（长期）、偿还其他金融机构贷款、以贷收贷、流向房地产/股市/理财、向关系人利益输送等。

## 6. 前置、互斥、替代与配套产品

- 前置产品：对公结算账户。
- 互斥产品：同一授信额度下与部分专项/中长期贷款互斥；不得用于「以贷还贷」与其他流动资金贷款形成多头重复授信。
- 替代产品：应收账款质押融资（PROD-FIN-002）、订单融资（PROD-FIN-003）可部分替代（按真实贸易背景选择）。
- 配套产品：对公结算账户、企业网银/现金管理。

## 7. 流程与材料

- 流程：申请受理 → 尽职调查 → 评级授信审批 → 合同签订（含担保）→ 放款（受托支付/自主支付）→ 贷后管理。
- 材料：营业执照、公司章程、财务报表、纳税证明、购销/经营合同、银行流水、担保材料（如抵押/质押/保证）。
- 协同角色：客户经理（受理/尽调）、风险/授信审批岗、放款与贷后管理岗、产品经理（方案）。
- 办理时效口径：T+N 工作日（具体时效以行内制度为准，待核定）。

## 8. 价格边界

- 利率以 LPR 为基准加点，按风险定价；具体区间与审批权限由《产品定价管理办法》核定（待核定数值）。
- 费率/违约金等按合同约定，边界以《流动资金贷款管理办法》为准（待核定）。

<!-- enrich:SRC-FIN-001 begin -->
- 定价政策（依据 SRC-FIN-001 第十一条）：贷款利率按照本行定价管理有关规定确定，并在借款合同中明确约定；涉及利率调整的，应当约定调整条件与生效方式。
<!-- enrich:SRC-FIN-001 end -->

## 9. 风险提示与人工复核

- 风险：还款能力波动、资金挪用、担保物价值波动、行业/政策变化。
- 人工复核要求：授信审批、放款与贷后必须人工复核；资金用途须受托支付或经核实的自主支付。

## 10. 销售边界

- 不得承诺「必批」「固定利率」「无抵押放款」等无依据承诺。
- AI/模型不得直接创建授信、定价、审批或写回动作（INV-09）。
- 推荐仅为候选建议，最终以准入审批与合同为准。

## 11. EvidenceRef（源文件与条款定位）

| ref_id | source_id | source_title | clause（条款定位） | 用途 |
|---|---|---|---|---|
| EV-FIN-001-01 | SRC-FIN-001 | 《流动资金贷款管理办法》（行内） | 准入/用途/期限/受托支付条款（待核定条款号） | 准入条件、禁止用途、流程 |
| EV-FIN-001-02 | SRC-FIN-002 | 《对公客户准入与评级管理办法》（行内） | 客户类型/规模/评级准入条款（待核定条款号） | 准入条件 |
| EV-FIN-001-03 | SRC-FIN-004 | 《产品定价管理办法》（行内） | 利率/费率定价区间与审批权限（待核定条款号） | 价格边界 |
| EV-FIN-001-04 | SRC-FIN-005 | 《流动资金贷款风险管理指引》（行内） | 风险提示/贷后/资金挪用防范条款（待核定条款号） | 风险提示 |
| EV-FIN-001-05 | REG-FIN-001 | 《流动资金贷款管理暂行办法》（监管） | 用途限制与受托支付标准（待对齐条款号） | 禁止用途 |

## 12. 不可变版本语义

本卡 `version=1.0.0`、`status=ACTIVE`（OQ-02 批准）。ACTIVE 版本内容不可变（FROZEN=YES），只可退役；内容变更需新建版本目录，本卡文件不改写。
