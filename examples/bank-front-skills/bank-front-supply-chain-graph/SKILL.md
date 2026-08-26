---
name: bank-front-supply-chain-graph
display_name: "供应链图谱分析"
description: "面向银行智能访前作战单场景的供应链图谱分析能力：整合行内交易数据（T-CORE-001）与外部工商/产业数据（T-EXT-001），生成客户「上游供应商层—本企业层—下游客户层」三段式供应链图谱并输出供应链位置、议价能力、集中度风险与关键变动解读。当客户经理在访前准备阶段需要摸清对公客户的上下游交易结构、判断其产业链位置与议价能力时触发，输出符合 SK-FRONT-002 输出规范的供应链图谱 JSON（nodes + edges + interpretation）。"
author: yang.yuan@gientech.com
department: "BFSI1_BUSS-BFSI1_BUSS_R&D"
version: v1.0.0
usage_scope: "仅云端使用"
---

# SK-FRONT-002 供应链图谱分析

## 1. 概述

| 项 | 内容 |
| --- | --- |
| 技能ID | SK-FRONT-002 |
| 技能名称 | 供应链图谱分析（Supply Chain Graph Analysis） |
| 技能类型 | 组合型（整合行内交易数据 + 外部产业数据） |
| 风险等级 | 中 |
| 关联知识域 | KD-01（客户知识域）、KD-08（数据与智能知识域） |
| 关联工具 | T-CORE-001（行内交易数据，入参 customerId）、T-EXT-001（外部工商/产业/供应链数据，入参 creditCode/industry） |
| 关联知识条目 | KI-FRONT-001（公司供应链图谱：客户自身的上游供应商和下游客户及其业务关系、金额占比、趋势） |
| 对应任务 | TASK-FRONT-002（公司供应链图谱分析） |
| 评测样本 | SMP-EVAL-FRONT-CHAIN-00002（expected：展示至少 3 家供应商、3 家客户及关系解读） |
| 服务对象 | 对公客户经理（访前作战单准备者）、对公授信审查岗（供应链风险初判）、供应链金融产品经理（链上企业识别） |
| 核心价值 | 拜访前把分散在行内流水与外部产业数据中的上下游关系还原为一张三段式供应链图谱，一次回答三个问题：①这家企业处于产业链什么位置（上游/中游/下游）？②它对上下游议价能力如何（集中度、账期、结算方式）？③有哪些集中度风险与关键供应商/客户变动需要访前核实？ |

## 2. 适用范围

1. 对公客户（含潜在客户）首次拜访前，需快速掌握其上下游交易结构的场景。
2. 授信申请初判：需评估客户供应链位置、上下游稳定性与经营依赖时。
3. 供应链金融产品设计：需从核心企业上下游识别链上企业名单时。
4. 贷后/存续期监测：需跟踪关键供应商、客户的新增、流失与占比变化时。
5. 集中度风险分析：需判断客户对单一供应商或客户的依赖程度时。
6. 交叉销售线索挖掘：需从客户交易对手中筛选潜在营销对象时。
7. 客户分层与行业定位：需判断客户处于产业链上游/中游/下游时。
8. 行内交易数据与外部产业数据均可获取、需要组合分析形成完整图谱时。

## 3. 何时使用

- 客户经理在「智能访前作战单」流程中需要生成供应链图谱节点、边与解读时（对应任务 TASK-FRONT-002）。
- 输入包含 ```customerId```，且明确或隐含需要分析客户上下游关系、供应链位置、议价能力或集中度风险时。
- 需要引用知识条目 KI-FRONT-001（公司供应链图谱）内容支撑客户画像或访前必问事项时。
- 已由访前报告组装（SK-FRONT-001 bank-front-report-assembler）派发本任务，或八维研判（SK-FRONT-003）需要本图谱作为输入材料时。

## 4. 何时不要使用

- 无任何行内交易数据或外部数据可核验、仅有客户名称时（应转入第 10 节「信息不足时的处理」，不得凭猜测生成图谱）。
- T-CORE-001 或 T-EXT-001 任一数据源完全不可获取、无法支撑最低图谱构建时。
- 分析对象为个人（零售）客户而非对公客户时。
- 上游访前报告组装（SK-FRONT-001）已完成图谱部分，无需重复生成时。
- 需要出具对外法律效力文件或正式审计结论时（本技能输出仅供行内访前准备与初步判断参考）。

## 5. 默认工作流

1. 确认输入：校验 ```customerId```（必填）及可选增强字段（customerName / creditCode / industry / analysisPeriodMonths），不满足最低输入要求时按第 10 节处理。
2. 拉取行内交易数据（T-CORE-001）：以 ```customerId``` 为入参，获取近 12 个月收付款流水，识别交易对手、金额、笔数与资金方向（收款=下游客户付款，付款=向上游供应商采购）。
3. 拉取外部产业数据（T-EXT-001）：以 ```creditCode``` / ```industry``` 为入参，获取工商登记（注册资本、成立时间、行业分类）、产业链位置标注、公开上下游关系与行业景气信息。
4. 数据清洗与对手归并：标准化并归并交易对手（同一实体的多账号/多名称合并），剔除同业往来、费用、工资、税费等非经营性交易。
5. 构建图谱节点：生成三段式节点——上游供应商层节点、本企业层节点（唯一 1 个）、下游客户层节点，记录名称、类型、所属层、金额、占比、趋势。
6. 构建图谱边：为每对「本企业—供应商」「本企业—客户」生成有向边，记录方向、年交易额、占采购/销售比、结算方式、趋势与数据来源。
7. 计算指标：计算供应商/客户集中度（Top1、Top3、Top5 占比及 HHI）、上下游集中度对比、交易环比/同比趋势。
8. 业务解读：按第 6 节框架输出供应链位置、议价能力、集中度风险、关键供应商/客户变动四类解读，标注数据来源与置信度。
9. 生成输出：按 references/output-schema.md 组装 nodes + edges + interpretation，输出三段式供应链图谱 JSON。
10. 自检与标注：对照第 11 节交付标准自检；无法核验的内容标注 ```verifyStatus: "PENDING"```，并在 followUpQuestions 中转化为访前核实问句。

## 6. 核心分析框架

### 6.1 图谱三段式结构（对应 KI-FRONT-001）

供应链图谱采用固定三层结构：

```
┌────────────────────────────────────────────────────────────┐
│ 上游供应商层（Supplier Layer）                              │
│   供应商S1 / S2 / S3 ...（本企业向其采购）                   │
│            │  采购边（付款方向：本企业 → 供应商）            │
├────────────────────────────────────────────────────────────┤
│ 本企业层（Enterprise Layer）                                │
│   客户本体（customerId）—— 全图唯一中心节点                  │
│            │  销售边（收款方向：客户 → 本企业）              │
├────────────────────────────────────────────────────────────┤
│ 下游客户层（Customer Layer）                                │
│   客户C1 / C2 / C3 ...（向本企业采购）                      │
└────────────────────────────────────────────────────────────┘
```

- **上游供应商层**：本企业的主要付款对象（采购）。关注采购金额、采购占比、结算账期；边方向为本企业 → 供应商。
- **本企业层**：客户本体，唯一中心节点，承接上下两层的全部边。
- **下游客户层**：本企业的主要收款对象（销售）。关注销售金额、销售占比、账期；边方向为客户端 → 本企业（资金流入）。

### 6.2 议价能力判断维度

| 维度 | 判断逻辑 | 指向 |
| --- | --- | --- |
| 供应商集中度 | Top1 供应商采购占比 ≥ 30% 或 Top3 ≥ 60% | 对上游议价能力弱，采购依赖风险高 |
| 客户集中度 | Top1 客户销售占比 ≥ 30% 或 Top3 ≥ 60% | 对下游议价能力弱，销售依赖风险高 |
| 上下游集中度对比 | 上游分散、下游集中 | 下游强势，本企业处于被动地位 |
| 结算账期 | 对上游账期短（现款/预付）、对下游账期长（赊销） | 上游议价能力强于本企业 |
| 交易稳定性 | 主要交易对手近 6 个月交易额趋势 | 上升=关系稳固；下降=关系松动 |
| 产业链位置 | 上游=原料/部件供应商；中游=制造/组装；下游=渠道/终端 | 位置决定议价空间与行业话语权 |

### 6.3 集中度风险与关键变动

- **集中度风险**：单一供应商/客户占比 ≥ 30%，或 Top5 合计 ≥ 70% 时触发 high 关注，需在解读中提示并建议访前核实替代来源/流失预案。
- **关键供应商/客户变动**：对比近 6 个月与更早周期，识别新增、退出或占比显著变化的 Top 交易对手，作为访前必问事项。

## 7. 输入要求

本技能最低可用输入为 ```customerId```（T-CORE-001 主入参）。可选增强字段（customerName / creditCode / industry / analysisPeriodMonths）可显著提升外部数据匹配精度与趋势分析能力，建议尽量提供。

> 完整 JSON 结构、最低可用输入与字段说明见 [references/input-schema.md](references/input-schema.md)。

## 8. 输出要求

输出为符合 references/output-schema.md 的供应链图谱 JSON：```nodes```（三段式节点列表）+ ```edges```（有向关系边列表）+ ```interpretation```（供应链位置、议价能力、集中度风险、关键变动四类结构化解读）。每条解读须标注 ```dataSource``` 与置信度。

> 完整字段说明与校验约定见 [references/output-schema.md](references/output-schema.md)。

输出模板：

```json
{
  "schemaVersion": "1.0",
  "skillId": "SK-FRONT-002",
  "customerId": "<customerId>",
  "generatedAt": "<ISO-8601 时间戳>",
  "buildStatus": "complete | partial",
  "nodes": [
    {
      "id": "<节点ID>",
      "name": "<企业名称>",
      "layer": "supplier | enterprise | customer",
      "type": "supplier | enterprise | customer",
      "creditCode": "<统一社会信用代码，可空>",
      "industry": "<行业>",
      "annualAmount": 0,
      "share": 0,
      "trend": "up | flat | down | unknown",
      "dataSource": "T-CORE-001 | T-EXT-001 | MERGED",
      "verifyStatus": "VERIFIED | PENDING"
    }
  ],
  "edges": [
    {
      "source": "<本企业节点ID>",
      "target": "<对手节点ID>",
      "relation": "purchase | sale",
      "direction": "out | in",
      "annualAmount": 0,
      "share": 0,
      "settlement": "<结算方式/账期>",
      "trend": "up | flat | down | unknown",
      "dataSource": "T-CORE-001 | T-EXT-001",
      "verifyStatus": "VERIFIED | PENDING"
    }
  ],
  "interpretation": {
    "supplyChainPosition": "<上游/中游/下游 + 一句依据>",
    "bargainingPower": {
      "upstream": "<对上游议价能力评级（强/中/弱）+ 依据>",
      "downstream": "<对下游议价能力评级（强/中/弱）+ 依据>"
    },
    "concentrationRisk": [
      {
        "type": "supplier | customer",
        "name": "<对手名称>",
        "share": 0,
        "level": "high | medium | low",
        "reason": "<触发原因>",
        "dataSource": "<数据来源>"
      }
    ],
    "keyChanges": [
      {
        "type": "added | removed | shareChanged",
        "name": "<对手名称>",
        "detail": "<变动描述>",
        "period": "<对比周期>",
        "dataSource": "<数据来源>"
      }
    ],
    "overallAssessment": "<一段话综合判断>",
    "followUpQuestions": ["<访前需向客户核实的问句>"],
    "confidence": {
      "position": "high | medium | low",
      "bargainingPower": "high | medium | low",
      "concentration": "high | medium | low",
      "changes": "high | medium | low"
    }
  }
}
```

## 9. 风险与边界

- **免责声明**：本技能输出仅为行内访前准备与初步判断参考，不构成授信结论、法律意见或对外披露材料；最终授信决策须以尽职调查与审批流程为准。
- **数据时效与口径**：T-CORE-001 交易数据仅反映行内可观测流水，可能存在体外交易未纳入；T-EXT-001 外部数据可能存在滞后或口径差异。所有金额、占比、关系均须注明数据来源与统计口径。
- **禁止行为**：
  - 禁止在数据缺失时凭猜测虚构供应商/客户节点或交易金额；
  - 禁止将图谱结果直接作为授信审批依据或对外提供；
  - 禁止将待核验（PENDING）内容当作已核实事实陈述；
  - 禁止泄露客户与交易对手的商业敏感信息，输出仅限行内授权范围使用。
- **待核验标注**：凡无法通过行内交易数据与外部数据双重确认的节点、边与解读，必须标注 ```verifyStatus: "PENDING"```，并在 ```followUpQuestions``` 中转化为访前核实问句。
- **合规边界**：处理客户与交易对手信息须遵守行内数据安全与客户信息保护规定，最小化采集、按需使用。

## 10. 信息不足时的处理

- **无 customerId**：请求用户补充客户编号或客户名称 + 统一社会信用代码；若均无法提供，终止生成并说明原因。
- **行内交易数据不足**（近 12 个月可识别经营交易对手 < 3 家或流水明显不完整）：仅输出可核验部分，将图谱标记为「部分构建」，并在解读中说明覆盖局限。
- **外部数据不可用**：以行内数据为准生成图谱，外部相关字段（行业、产业链位置）标注 ```PENDING```，建议后续人工补录。
- **交易对手无法归并/识别**：将无法归并的经营性交易汇总为「其他交易」节点并标注，不强行猜测对手身份。
- **无法达到最低输出要求**（无法识别至少 3 家供应商或 3 家客户）：输出部分图谱 + 缺口说明，不得为凑数虚构节点；**必须将顶层 ```buildStatus``` 置为 ```partial```**，并在 interpretation / followUpQuestions 中说明覆盖局限。

## 11. 交付标准（Checklist）

- [ ] 输出包含三段式结构：至少 3 个上游供应商节点、1 个本企业节点、至少 3 个下游客户节点；**任一不足时顶层 ```buildStatus``` 必须为 ```partial``` 并附覆盖局限说明，禁止无标注输出不完整图谱**。
- [ ] 每条边包含方向、金额、占比、趋势，且与两端节点金额勾稽一致（同侧边 share 合计 ≤ 1）。
- [ ] 解读覆盖四要素：供应链位置、议价能力、集中度风险、关键供应商/客户变动。
- [ ] 集中度风险按明确阈值触发（单一占比 ≥ 30% 或 Top5 ≥ 70% 触发 high 标注），并给出触发原因。
- [ ] 所有节点、边、解读标注 ```dataSource```（T-CORE-001 / T-EXT-001 / MERGED）与 ```verifyStatus``` / 置信度。
- [ ] 不可核验内容均标注 PENDING 且转化为访前核实问句（followUpQuestions 至少 2 条）。
- [ ] JSON 符合 references/output-schema.md 结构，可通过 schema 校验。
- [ ] 输出仅限行内使用，无对外表述。

## 12. 参考资料与模板

- 输入结构说明：[references/input-schema.md](references/input-schema.md)
- 输出结构说明：[references/output-schema.md](references/output-schema.md)
- 示例输入数据：[assets/example-input.json](assets/example-input.json)
- 模拟输入数据：[references/mock-input-data.json](references/mock-input-data.json)（T-CORE-001 / T-EXT-001 返回的模拟原始数据，供开发调试、离线调用与评测注入）
- 关联知识条目：KI-FRONT-001（公司供应链图谱）
- 关联任务：TASK-FRONT-002（公司供应链图谱分析）
- 同级相关技能（相对路径）：
  - [../bank-front-report-assembler/SKILL.md](../bank-front-report-assembler/SKILL.md)（SK-FRONT-001 访前报告组装）
  - [../bank-front-eight-dimension/SKILL.md](../bank-front-eight-dimension/SKILL.md)（SK-FRONT-003 八维研判）
  - [../bank-front-fact-reconciliation/SKILL.md](../bank-front-fact-reconciliation/SKILL.md)（SK-FRONT-004 事实对账）
  - [../bank-front-commitment-script/SKILL.md](../bank-front-commitment-script/SKILL.md)（SK-FRONT-005 承诺话术）
  - [../bank-front-kyc-gap-check/SKILL.md](../bank-front-kyc-gap-check/SKILL.md)（SK-FRONT-006 KYC 缺口核验）
  - [../bank-front-product-recommendation/SKILL.md](../bank-front-product-recommendation/SKILL.md)（SK-FRONT-007 产品组合推荐）
