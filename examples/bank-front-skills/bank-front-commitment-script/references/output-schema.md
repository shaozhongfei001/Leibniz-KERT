# 输出结构定义（SK-FRONT-005 承诺话术生成）

输出为 JSON：承诺事项卡片列表（按时间线组织）。

```json
{
  "schemaVersion": "1.0",
  "skillId": "SK-FRONT-005",
  "customerId": "<customerId>",
  "generatedAt": "<ISO-8601>",
  "commitments": [
    {
      "commitmentId": "C-001",
      "description": "<承诺描述>",
      "promisor": "client | bank",
      "status": "completed | pending | overdue",
      "promiseDate": "<YYYY-MM-DD>",
      "dueDate": "<YYYY-MM-DD>",
      "factReference": {
        "source": "<沟通时间/渠道>",
        "summary": "<对话摘要>",
        "quote": "<客户原话>",
        "verified": true | false
      },
      "script": {
        "factCitation": "<📌引用的事实出处>",
        "targetRole": "<面向的角色>",
        "text": "<核心话术文本>",
        "goal": "<预期目标>"
      },
      "actionPlan": {
        "owner": "<责任人>",
        "deadline": "<截止时间>",
        "steps": ["<行动路径1>", "<行动路径2>"]
      }
    }
  ],
  "timeline": ["<按时间排序的承诺概要>"],
  "warnings": []
}
```

## 重点字段说明

| 字段 | 说明 |
| --- | --- |
| `commitments[].factReference` | 事实引用：来源标签 + 摘要 + 原话 + `verified`（引用缺失处 `verified: false` 并标注"待核实"） |
| `commitments[].script` | 沟通话术四要素：事实出处（📌）/ 面向角色 / 核心话术 / 预期目标 |
| `commitments[].actionPlan` | 行动计划：责任人 / 截止时间 / 行动路径 |
| `timeline` | 按时间排序的承诺概要 |

## 校验约定

- 每条承诺必须含事实引用；引用缺失处标注"待核实"。
- 话术只引用已核验事实（RUL-FRONT-004）。
- 无历史承诺时输出占位，不虚构。
