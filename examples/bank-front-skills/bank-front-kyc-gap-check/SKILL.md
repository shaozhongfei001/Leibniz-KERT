---
name: bank-front-kyc-gap-check
display_name: "KYC缺口核验"
description: "当银行客户经理在智能访前作战单场景下，已获得事实对账冲突或行业信号，需要识别 KYC 信息缺口、按风险优先级排序并生成核实话术与核实路径时使用本技能。输出 KYC 缺口卡片（含核实话术 + 行动计划），可直接嵌入访前作战单，指导现场核实并留痕。"
author: yang.yuan@gientech.com
department: "BFSI1_BUSS-BFSI1_BUSS_R&D"
version: v1.0.0
usage_scope: "仅云端使用"
---

# SK-FRONT-006 KYC 缺口核验

## 概述

| 项目 | 内容 |
| --- | --- |
| 技能ID | SK-FRONT-006 |
| 技能名称 | KYC 缺口核验 |
| 技能类型 | 生成 |
| 风险等级 | 高 |
| 关联知识域 | KD-01（客户知识域）、KD-06（合规知识域） |
| 关联知识条目 | KI-FRONT-005（KYC信息缺口）、KI-RULE-001（KYC核验制度，源自 SRC-KYC-001 KYC问题库） |
| 关联规则 | RUL-FRONT-002（缺口优先级规则：资金安全/合规风险/经营决策三类） |
| 关联工具 | T-LLM-001（LLM 服务：生成核实话术与缺口描述） |
| 对应任务 | TASK-FRONT-006（KYC信息缺口识别与核实话术） |

**服务对象**：对公客户经理（访前核验准备）、合规岗（KYC 补全督导）。

**核心价值**：基于事实对账冲突与行业信号，自动识别客户 KYC 信息缺口（对应 KI-FRONT-005），按资金安全、合规风险、经营决策三类优先级排序，为每个缺口生成精准、可回答的核实话术与核实路径，让客户经理带着"要核实什么、怎么问、何时核"的清单上门，现场留痕、闭环补全。

## 适用范围

1. 客户经理获得事实对账冲突（如营收与用电量背离）后，需要识别背后 KYC 缺口时。
2. 客户信息不完整（缺关键 KYC 要素）需要补全时。
3. 客户涉及高风险业务（大额授信、跨境、关联交易）需要加强 KYC 核实时。
4. 合规检查要求补充客户身份/受益所有人/风险等级信息时。
5. 存量客户信息过期需要更新核实时。
6. 作为访前作战单"KYC 缺口"模块的输入素材时。

## 何时使用

- 访前作战单编制流程中，TASK-FRONT-006（KYC信息缺口识别与核实话术）被触发时。
- 输入包含 ```customerId``` 与 ```conflicts```（事实对账冲突/异常清单），需要识别 KYC 缺口时。
- 需要为每个缺口生成核实话术与核实路径时。

## 何时不要使用

- 无触发源（无事实对账冲突、无行业信号、无 KYC 要素缺失）时：输出"无缺口"占位，不强行制造缺口。
- 仅需查询客户 KYC 档案（不缺信息）时。
- 需要出具正式 KYC 合规结论时（本技能输出为访前核验准备，最终结论以合规确认为准）。

## 默认工作流

1. **确认输入**：校验 ```customerId```（必填）与 ```conflicts```（事实对账冲突清单，可选但强烈建议）。
2. **对照 KYC 要素清单核验（KI-RULE-001）**：按 KYC 核验制度（客户身份识别、受益所有人、风险等级划分等，源自 SRC-KYC-001 KYC问题库）核验已得数据，识别缺失/存疑要素。
3. **缺口识别（T-LLM-001）**：基于触发源（事实对账冲突原文 / 行业信号）识别信息缺口，生成**缺口描述**（KE-FRONT-005-01）：精准、具体、可回答，避免泛泛提问；如"扩产项目的资金来源是否已通过股东注资解决？"。
4. **优先级排序（RUL-FRONT-002）**：按三类优先级规则标注处理优先级：
   - **资金安全**（高）：涉及资金去向不明、还款来源存疑等；
   - **合规风险**（高/中）：涉及受益所有人、风险等级、制裁名单等；
   - **经营决策**（中/一般）：涉及经营计划、融资安排等。
5. **生成核实话术（T-LLM-001）**：针对每个缺口生成三要素核实话术（KE-FRONT-005-03）：①引用事实依据；②具体提问内容；③核实目标。
6. **生成核实行动计划（KE-FRONT-005-04）**：为每个缺口生成核实行动方案：①核实目标；②核实时机；③核实路径（具体操作步骤）。
7. **生成输出**：按 references/output-schema.md 组装 KYC 缺口卡片列表。
8. **自检与交付**：对照"交付标准"checklist 自检，通过后交付访前报告组装（SK-FRONT-001）或直接交付客户经理。

## 核心分析框架

### 5.1 KYC 缺口要素（KI-FRONT-005）

| 要素 | 内容 | 类型 |
| --- | --- | --- |
| KE-FRONT-005-01 | 缺口描述：精准、具体、可回答的待核实问题清单 | 规则（K-Type-R） |
| KE-FRONT-005-02 | 触发源：引用事实对账冲突/异常项原文，关联规则编号（RUL-FRONT-001-xxx） | 事实（K-Type-F） |
| KE-FRONT-005-03 | 核实话术：引用事实依据 + 具体提问内容 + 核实目标 | 流程（K-Type-P） |
| KE-FRONT-005-04 | 核实目标及行动计划：核实目标 + 核实时机 + 核实路径 | 流程（K-Type-P） |

### 5.2 优先级规则（RUL-FRONT-002）

| 优先级 | 场景 | 处理 |
| --- | --- | --- |
| 高 | 资金安全（资金去向不明、还款来源存疑）、合规风险（受益所有人/制裁名单） | 立即核实，现场必问 |
| 中 | 合规风险（风险等级划分）、经营决策（融资安排） | 拜访中核实 |
| 一般 | 经营决策（经营计划） | 可后续跟进核实 |

### 5.3 核验制度引用（KI-RULE-001）

- 客户身份识别：核对工商登记、实际控制人、受益所有人；
- 风险等级划分：按行内 KYC 风险等级规则；
- 制度来源：SRC-KYC-001 KYC 问题库（行内规范）。

## 输入要求

输入遵循 ```references/input-schema.md```，最低可用输入为 ```customerId```；```conflicts```（事实对账冲突清单）为建议输入，提供后可显著提升缺口识别的针对性。示例见 ```assets/example-input.json```，模拟输入见 ```references/mock-input-data.json```。

## 输出要求

输出遵循 ```references/output-schema.md```：KYC 缺口卡片列表（每条含缺口描述、触发源、优先级、核实话术、核实行动计划）。

输出模板：

```json
{
  "schemaVersion": "1.0",
  "skillId": "SK-FRONT-006",
  "customerId": "<customerId>",
  "generatedAt": "<ISO-8601>",
  "kycGaps": [
    {
      "gapId": "KG-001",
      "description": "<精准、可回答的缺口描述>",
      "trigger": "<触发源原文，关联 RUL-FRONT-001-xxx>",
      "priority": "high | medium | general",
      "priorityCategory": "资金安全 | 合规风险 | 经营决策",
      "verifyScript": {
        "factBasis": "<引用的事实依据>",
        "question": "<具体提问内容>",
        "goal": "<核实目标>"
      },
      "actionPlan": {
        "verifyGoal": "<核实目标>",
        "timing": "<核实时机>",
        "path": ["<核实路径步骤1>", "<核实路径步骤2>"]
      }
    }
  ],
  "warnings": []
}
```

## 风险与边界

- **免责声明**：本技能输出为访前 KYC 核验准备，不构成正式 KYC 合规结论；最终以行内合规确认为准。
- **禁止行为**：禁止无触发源强行制造缺口；禁止生成泛泛、不可回答的缺口描述；禁止删除优先级标注。
- **待核验标注**：触发源引用必须关联规则编号（RUL-FRONT-001-xxx）便于审计追溯；未经确认信息标注"待核验"。
- **合规边界**：KYC 信息处理须遵守反洗钱与客户信息保护规定。

## 信息不足时的处理

- 无 ```customerId```：请求补充客户编号或客户名称；无法提供则终止。
- 无 ```conflicts``` 触发源：按行业信号 / KYC 要素缺失识别缺口；仍无触发源则输出"无缺口"占位。
- KYC 要素无法核验：缺口标注"待核验"，核实路径给出补数动作。
- 数据不足无法识别缺口：输出说明 + 建议补充数据源。

## 交付标准

- [ ] 每个缺口含精准、可回答的缺口描述（非泛泛提问）。
- [ ] 每个缺口含触发源引用（关联规则编号 RUL-FRONT-001-xxx，可追溯）。
- [ ] 每个缺口按 RUL-FRONT-002 标注优先级（高/中/一般）与优先级类别（资金安全/合规风险/经营决策）。
- [ ] 每个缺口含核实话术（事实依据 + 提问内容 + 核实目标）。
- [ ] 每个缺口含核实行动计划（目标 + 时机 + 路径）。
- [ ] 无触发源时不强行制造缺口。
- [ ] 输出符合 references/output-schema.md 结构。

## 参考资料与模板

- 输入结构说明：[references/input-schema.md](references/input-schema.md)
- 输出结构说明：[references/output-schema.md](references/output-schema.md)
- 示例输入数据：[assets/example-input.json](assets/example-input.json)
- 模拟输入数据：[references/mock-input-data.json](references/mock-input-data.json)
- 关联知识条目：KI-FRONT-005（KYC信息缺口）、KI-RULE-001（KYC核验制度）
- 关联规则：RUL-FRONT-002（缺口优先级规则）
- 同级相关技能：
  - [../bank-front-report-assembler/SKILL.md](../bank-front-report-assembler/SKILL.md)（SK-FRONT-001 访前报告组装）
  - [../bank-front-fact-reconciliation/SKILL.md](../bank-front-fact-reconciliation/SKILL.md)（SK-FRONT-004 事实对账）
  - [../bank-front-commitment-script/SKILL.md](../bank-front-commitment-script/SKILL.md)（SK-FRONT-005 承诺话术）
