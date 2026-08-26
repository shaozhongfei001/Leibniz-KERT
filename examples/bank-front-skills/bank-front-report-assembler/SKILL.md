---
name: bank-front-report-assembler
display_name: "访前报告组装"
description: "面向银行对公客户经理「智能访前作战单」场景的访前报告组装技能：基于客户全景数据（客户信息、供应链图谱、八维研判、事实对账、承诺话术、KYC缺口、产品组合七模块），按统一版式组装为一页 H5 作战单（移动端）并支持 PDF 导出。当客户经理在访前准备阶段输入 customerId+goal、需要一次拿到完整可执行的 H5 作战单（含风险与待办区、行动项）时触发，输出符合 KI-FRONT-007 渲染模板的完整 H5 作战单 JSON。"
author: yang.yuan@gientech.com
department: "BFSI1_BUSS-BFSI1_BUSS_R&D"
version: v1.0.0
usage_scope: "仅云端使用"
---

# SK-FRONT-001 访前报告组装

## 概述

| 项目 | 内容 |
| --- | --- |
| 技能ID | SK-FRONT-001 |
| 技能名称 | 访前报告组装（H5 作战单生成） |
| 技能类型 | 组合（编排七模块产出 + 统一版式组装） |
| 风险等级 | 高 |
| 关联知识域 | KD-01 / KD-02 / KD-04 / KD-05 / KD-06 / KD-08（全集） |
| 关联提示词模板 | PROMPT-FRONT-001-v1（角色 = 智能访前助手） |
| 关联知识条目 | KI-FLOW-001~007（七个任务流程）、KI-FRONT-007（一页H5作战单输出渲染模板） |
| 关联规则 | RUL-FRONT-001（冲突检测）、RUL-FRONT-002（KYC缺口优先级）、RUL-FRONT-003（产品硬约束）、RUL-FRONT-004（话术事实引用） |
| 关联工具 | T-CRM-001、T-CORE-001、T-EXT-001、T-MARKET-001、T-LLM-001、T-PRODUCT-001、T-AUTH-001 |
| 对应任务 | TASK-FRONT-000（总组装汇总：七个任务节点输出 → 一页H5作战单） |

**服务对象**：对公客户经理（拜访准备者）、分行对公业务支撑岗、陪访的产品经理/分管领导。

**核心价值**：把七个任务节点（TASK-FRONT-001~007）的产出按统一版式组装为「一页 H5 作战单（移动端）+ PDF 导出」，将访前准备时间从数小时缩短至 10 分钟内；自动识别信息缺口、经营断点与潜在需求，突出行动项，让客户经理"拿着就能去拜访"，且每一步结论都可溯源、可复核。

## 适用范围

1. 企业客户首次拜访前的作战单生成（无历史拜访记录）。
2. 存量企业客户定期回访 / 年审前的资料刷新与作战单重建。
3. 重点客户（战略客户、集团客户）专项营销前的全面情报准备。
4. 客户经理交接 / 新接手客户时的快速熟悉与拜访准备。
5. 供应链上下游客户的联动营销（基于供应链图谱定向拜访）。
6. 有明确业务目标（授信营销、存款归集、产品渗透等）的目标导向拜访。
7. 疑难客户（信息缺失、事实冲突、KYC 存疑）的拜访前风险预判与话术准备。
8. 行长 / 分管领导陪访前的作战单预检与质控。

## 何时使用

- 调用方提供 ```customerId```（+调用上下文 ```userId```）并表达访前准备意图时。
- 需要把多源数据（CRM、交易、工商、市场、KYC）汇总为单一交付物（一页 H5 作战单）时。
- 需要一次调用内完成"查数 → 研判 → 对账 → 话术 → 核缺 → 推荐 → 组装"全流程时。

## 何时不要使用

- 只查单一数据源（如仅查客户基本信息）：应直接调用对应专项技能或工具（如 SK-FRONT-002~007 / T-CRM-001），不要走全流程组装。
- 未提供 ```customerId``` 或无法解析出唯一客户实体：必须先补齐客户标识，禁止用空 ID 或模糊名称跑全流程。
- 单点问题排查（如只想看某笔交易异常）：用专项技能，而非组装。
- 无 ```userId``` 鉴权上下文：组装会在首个环节调用 T-AUTH-001，鉴权失败则整体中止，不得绕过。
- 客户已注销 / 退出 / 明确拒绝拜访：中止流程并提示，不产出作战单。

## 默认工作流

组装执行顺序（默认工作流 = TASK-FRONT-001~007 七个模块产出 + 总组装）：

> **子技能加载规则（重要）**：本技能在 DSH 环境中通过 ```skill``` 工具执行专项任务。每个节点开始前，**必须先调用 ```skill``` 工具加载对应子技能**（技能名见步骤内标注，例如 ```bank-front-supply-chain-graph```），再按其 SKILL 指令执行并产出该节点交付物，最后写入组装素材区（assemblyMaterials）。禁止跳过加载直接内联"脑补"执行；若 ```skill``` 工具返回 ```unknown or no longer available```，将该节点标记为"子技能不可用"，按降级规则处理并记入 assemblyMaterials.warnings。
> **工具说明**：T-AUTH-001 / T-CRM-001 / T-EXT-001 / T-MARKET-001 / T-CORE-001 / T-LLM-001 / T-PRODUCT-001 为业务平台侧的约定接口（REST / MCP / SDK）；在 DSH 运行时环境中这些工具**不存在**，其数据获取与处理职责由对应子技能承担，鉴权由宿主会话上下文保证。本技能不依赖任何 T-* 工具的存在。

1. **鉴权与入口校验**：接收 ```{customerId, goal}``` 与调用上下文 ```userId```；校验 userId 对 customerId 的访问权限（DSH 环境由宿主会话上下文保证，对应业务平台 T-AUTH-001）。校验失败立即中止并返回原因；通过后初始化组装素材区（assemblyMaterials）与七模块清单。
2. **① 客户信息装配（TASK-FRONT-001 / KI-FLOW-001）**：按 KI-FLOW-001 流程步骤执行——①CRM/核心系统拉取客户基本信息 → ②标注数据时点与来源 → ③按 KI-009 八要素（客户全称/编号/所属行业/企业规模/年营收/注册地址/主要产品/合作年限）装配为客户信息摘要卡片。作为后续分析的事实锚点，写入 assemblyMaterials.customerBasic。
3. **② 供应链图谱（TASK-FRONT-002）**：调用 ```skill``` 工具加载 ```bank-front-supply-chain-graph```（SK-FRONT-002，对应 T-CORE-001 + T-EXT-001 数据源），按其指令构建公司供应链图谱（KI-FRONT-001：上游供应商层—本企业层—下游客户层三段式 + 位置/议价能力/集中度风险/关键变动解读），输入依赖步骤 2 的客户实体信息，写入 assemblyMaterials.supplyChainGraph。
4. **③ 八维研判（TASK-FRONT-003）**：调用 ```skill``` 工具加载 ```bank-front-eight-dimension```（SK-FRONT-003，对应 T-MARKET-001 数据源），按其指令按政策/市场/技术/供应链/区域/风险/指数/竞争力八维框架研判产业与客户态势（KI-FRONT-002），输入依赖步骤 3 的供应链图谱，写入 assemblyMaterials.eightDimension。
5. **④ 事实对账 / 冲突检测（TASK-FRONT-004）**：调用 ```skill``` 工具加载 ```bank-front-fact-reconciliation```（SK-FRONT-004，对应 T-CORE-001 数据源），按其指令汇总行内关键变动指标（营收、授信使用率、用电量、代发薪、结算量等，KI-FRONT-003），按 RUL-FRONT-001 冲突检测规则交叉校验外部数据，产出指标列表与冲突清单，写入 assemblyMaterials.factReconciliation。
6. **⑤ 承诺话术（TASK-FRONT-005）**：调用 ```skill``` 工具加载 ```bank-front-commitment-script```（SK-FRONT-005，对应 T-LLM-001 生成），按其指令从历史沟通记录提取事实承诺事项（KI-FRONT-004）并按时间线生成有依据的提问话术与行动计划；遵守 RUL-FRONT-004（话术事实引用规则：只引用已核验事实）；输入依赖步骤 5 的冲突清单——冲突项不得回避，必须给出处理口径，写入 assemblyMaterials.commitmentScript。
7. **⑥ KYC 缺口核验（TASK-FRONT-006）**：调用 ```skill``` 工具加载 ```bank-front-kyc-gap-check```（SK-FRONT-006），按其指令对照 KI-RULE-001（KYC核验制度）核验已得数据，产出 KYC 信息缺口清单（KI-FRONT-005），按 RUL-FRONT-002 缺口优先级规则排序，每条缺口含核实话术与核实路径，写入 assemblyMaterials.kycGapList。
8. **⑦ 产品组合推荐（TASK-FRONT-007）**：调用 ```skill``` 工具加载 ```bank-front-product-recommendation```（SK-FRONT-007，对应 T-PRODUCT-001 匹配引擎），按其指令综合 KYC 痛点、沟通记录与市场信号生成候选产品组合（KI-FRONT-006），应用 KI-RULE-002（产品准入与互斥制度）/ RUL-FRONT-003 产品硬约束规则过滤，写入 assemblyMaterials.productPortfolio。
9. **⑧ 总组装 H5 作战单（KI-FRONT-007 渲染）**：按 references/output-schema.md 模板将七模块组装为完整 H5 作战单 JSON；将冲突清单、KYC 缺口、产品硬约束结果置于作战单显著区域（"风险与待办"区置顶）；校验七模块齐全度与输出 schema 完整性。
10. **质控与交付**：对照"交付标准"checklist 自检；输出完整 H5 作战单 JSON（移动端一页版式，可 PDF 导出）。

## 核心分析框架

- **依赖驱动排序**：步骤 3（图谱）是步骤 4（八维研判）的输入；步骤 2/3 参与步骤 5（事实对账）；步骤 5 约束步骤 6（冲突清单约束话术口径）；步骤 7、8 并行依赖步骤 2~4 的数据；步骤 9 汇聚全部模块产出。
- **前置鉴权闸门**：每个环节执行前均校验 ```userId + customerId``` 权限（DSH 环境由宿主会话上下文保证，对应业务平台 T-AUTH-001），任何环节鉴权失败即中止，杜绝越权读取。
- **规则生效点**：RUL-FRONT-001（冲突检测）在步骤 5；RUL-FRONT-002（缺口优先级）在步骤 7；RUL-FRONT-003（产品硬约束）在步骤 8；RUL-FRONT-004（话术事实引用）在步骤 6。
- **显性呈现原则**：冲突、缺口、硬约束结果不得静默吞掉，必须写入作战单"风险与待办"显著区域，并逐条给出行动项。
- **可追溯性**：每条结论记录来源（工具、任务、知识条目、规则），支撑七模块齐全、轨迹可追溯的评测要求。

## 输入要求

输入结构严格遵循 references/input-schema.md（inputSchema = ```{customerId, goal}```）：

- **最低可用输入**：```{"customerId": "<客户ID>", "userId": "<发起人ID>"}```，其中 ```userId``` 为调用上下文注入的鉴权标识。
- ```goal``` 可缺省，缺省时按"全面拜访准备"处理。
- 缺 ```userId``` 或鉴权失败时，流程在鉴权环节中止并提示补充，不产出任何客户数据。

## 输出要求

输出结构严格遵循 references/output-schema.md，交付**完整 H5 作战单 JSON**（一页移动端版式，可 PDF 导出，对应 KI-FRONT-007 渲染模板）。

可直接复用的输出模板（```{{...}}``` 为占位符，需替换为实际值；字段级说明见 references/output-schema.md）：

```json
{
  "schemaVersion": "1.0",
  "skillId": "SK-FRONT-001",
  "requestId": "{{requestId}}",
  "battleOrder": {
    "meta": {
      "id": "BO-{{YYYYMMDD}}-{{customerId}}",
      "customerId": "{{customerId}}",
      "customerName": "{{客户名称}}",
      "goal": "{{拜访目标}}",
      "generatedAt": "{{ISO时间}}",
      "generatedBy": "{{userId}}",
      "version": "1.0"
    },
    "summary": {
      "visitPurpose": "{{一句话拜访目的}}",
      "keyFindings": ["{{关键发现1}}", "{{关键发现2}}"],
      "recommendedActions": ["{{建议行动1}}", "{{建议行动2}}"]
    },
    "sections": {
      "customerBasic": {"{{字段}}": "{{值}}"},
      "supplyChainGraph": {"{{字段}}": "{{值}}"},
      "eightDimension": {"{{维度}}": "{{研判结论}}"},
      "factReconciliation": {"{{字段}}": "{{值}}"},
      "commitmentScript": "{{承诺话术文本}}",
      "kycGapList": ["{{缺口项1}}", "{{缺口项2}}"],
      "productPortfolio": [{"productId": "{{产品ID}}", "reason": "{{推荐理由}}"}]
    },
    "riskAndAction": {
      "conflicts": [{"issue": "{{冲突描述}}", "action": "{{建议处理动作}}"}],
      "kycGaps": [{"item": "{{缺口要素}}", "priority": "{{高/中/低}}", "action": "{{补全动作}}"}],
      "hardConstraints": [{"productId": "{{产品ID}}", "constraint": "{{不满足的硬约束}}"}]
    },
    "assemblyMaterials": {
      "steps": [
        {
          "taskId": "TASK-FRONT-001",
          "taskName": "客户信息装配",
          "status": "success",
          "skillName": "bank-front-report-assembler(内部流程)",
          "outputKeys": ["customerBasic"],
          "knowledgeItems": ["KI-009"],
          "warnings": []
        }
      ],
      "warnings": []
    },
    "disclaimer": "本作战单仅用于拜访准备，不构成授信承诺或投资建议；最终业务决策须经行内合规与风险审查。"
  }
}
```

## 风险与边界

- **金融场景免责**：本技能产出仅为拜访准备材料，不构成授信承诺、投资建议或任何形式的法律 / 合规意见；涉及授信、承诺、产品准入的结论须经行内合规与风险审查后方可对外使用。
- **禁止行为**：
  - 禁止绕过 T-AUTH-001 读取或汇总客户数据；
  - 禁止将未核验数据写入话术或作战单正文；
  - 禁止删除、隐藏、弱化冲突、KYC 缺口、产品硬约束结果；
  - 禁止把行外来源（工商 / 产业 / 供应链等）数据当作行内已核验事实呈现。
- **待核验标注规则**：凡未经行内权威源（CRM / 交易系统）确认、或跨源不一致的数据，必须标注"待核验"；话术中的事实引用必须带来源标签；冲突项必须附建议处理动作；任何标注不得在最终输出中被移除。

## 信息不足时的处理

按信息完备度分级降级输出，所有降级都必须写入 assemblyMaterials.warnings：

- **完整度 A**（customerId + goal 全备，七模块数据齐全）：输出完整作战单。
- **完整度 B**（缺 goal）：goal 默认"全面拜访准备"，输出完整作战单并在 meta 中标注默认目标来源。
- **完整度 C**（某子技能数据缺失 / 超时）：该模块输出"数据不可得"占位 + 原因，其余模块照常执行；作战单对应区块标记"待补"，并在 riskAndAction 中给出补数动作。
- **完整度 D**（鉴权失败 / 无 userId / 无法解析 customerId）：中止流程，不产出作战单，返回明确原因与补全指引。

## 交付标准

质量验收 checklist（交付前逐项自检）：

- [ ] **鉴权**：每个环节均有 T-AUTH-001 校验记录，无任何绕过路径。
- [ ] **七模块齐全**：客户信息、供应链图谱、八维研判、事实对账、承诺话术、KYC 缺口、产品组合均存在且非空占位。
- [ ] **轨迹可追溯**：assemblyMaterials.steps 完整记录任务顺序、来源工具 / 任务 / 知识条目 / 规则。
- [ ] **显性呈现**：冲突、KYC 缺口、产品硬约束均出现在作战单"风险与待办"显著区域，且逐条含行动项。
- [ ] **话术合规**：话术事实引用全部来自已核验事实；冲突项有处理口径；无未核验数据冒充事实。
- [ ] **Schema 校验**：输出通过 references/output-schema.md 校验，无缺失必填字段。
- [ ] **组装层校验（各模块交付标准核对）**：
  - 供应链图谱：节点 ≥3 供应商 + ≥3 客户，否则必须携带 ```buildStatus: "partial"``` 与覆盖局限说明；
  - 八维研判：```eightDimension``` 必须含逐维 1-5 分评分与依据，禁止仅定性描述；
  - KYC 缺口：每个缺口卡片必须含核实话术（verifyScript）；
  - 客户信息：```customerBasic``` 按 KI-009 八要素输出并携带 ```missingFields```；
  - 事实对账：指标列表必须显式列出缺失指标的数据缺口清单，不得仅列可得指标。

## 参考资料与模板

- 输入结构定义：references/input-schema.md
- 输出结构定义：references/output-schema.md
- 示例输入数据：assets/example-input.json
- 模拟输入数据（开发调试 / 离线调用 / 评测注入）：references/mock-input-data.json
- 子技能（节点实现，**执行顺序 = 默认工作流；每个节点执行前必须先调用 ```skill``` 工具加载对应技能，再按其 SKILL 指令执行**）：
  - SK-FRONT-002 供应链图谱 → ```skill``` 加载 ```bank-front-supply-chain-graph```（../bank-front-supply-chain-graph/SKILL.md）
  - SK-FRONT-003 八维研判 → ```skill``` 加载 ```bank-front-eight-dimension```（../bank-front-eight-dimension/SKILL.md）
  - SK-FRONT-004 事实对账 / 冲突检测 → ```skill``` 加载 ```bank-front-fact-reconciliation```（../bank-front-fact-reconciliation/SKILL.md）
  - SK-FRONT-005 承诺话术 → ```skill``` 加载 ```bank-front-commitment-script```（../bank-front-commitment-script/SKILL.md）
  - SK-FRONT-006 KYC 缺口核验 → ```skill``` 加载 ```bank-front-kyc-gap-check```（../bank-front-kyc-gap-check/SKILL.md）
  - SK-FRONT-007 产品组合推荐 → ```skill``` 加载 ```bank-front-product-recommendation```（../bank-front-product-recommendation/SKILL.md）
