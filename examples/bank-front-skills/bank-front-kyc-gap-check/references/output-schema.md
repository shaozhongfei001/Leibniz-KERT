# 输出结构定义（SK-FRONT-006 KYC缺口核验）

输出为 JSON：KYC 缺口卡片列表。

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

## 重点字段说明

| 字段 | 说明 |
| --- | --- |
| `kycGaps[].description` | 缺口描述：精准、具体、可回答，避免泛泛提问（KE-FRONT-005-01） |
| `kycGaps[].trigger` | 触发源：引用事实对账冲突原文，关联规则编号（KE-FRONT-005-02） |
| `kycGaps[].priority` | 优先级：high/medium/general（RUL-FRONT-002：资金安全/合规风险/经营决策） |
| `kycGaps[].verifyScript` | 核实话术三要素：事实依据 + 提问内容 + 核实目标（KE-FRONT-005-03） |
| `kycGaps[].actionPlan` | 核实行动：目标 + 时机 + 路径（KE-FRONT-005-04） |

## 校验约定

- 每条缺口必须含触发源与规则编号（可追溯）。
- 每条缺口必须含核实话术（verifyScript）。
- 无触发源时不强行制造缺口。
