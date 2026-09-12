# 会面脚本 · 输出结构

本文件声明 `skill-customer-meeting-script` 的结构化输出契约。

**依据**：`src/kert/application/skills.py` 中 `_run_meeting` 的**实际实现**
（约 653–670 行），该实现明确构造下列字段并对 `agenda` 做类型校验。
**本声明以实现为准，不以推测为准。**

## 输出结构

```json
{
  "agenda": [
    {
      "time": "10:00",
      "topic": "开场与背景"
    }
  ],
  "talkingPoints": [
    {
      "title": "服务介绍",
      "detail": "面向该客户的服务方案要点。"
    }
  ],
  "sensitivePoints": [
    "需谨慎处理的话题（字符串数组）"
  ],
  "actionItems": [
    "会面后待办事项（字符串数组）"
  ],
  "evidenceRefs": [
    {
      "id": "证据引用标识",
      "summary": "证据摘要"
    }
  ]
}
```

## 字段说明

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `agenda` | array | **是** | 会面议程，每项含 `time` 与 `topic`；实现对此做类型校验，非数组即 fail-closed |
| `talkingPoints` | array | 否 | 谈话要点，每项含 `title` 与 `detail`；缺省为空数组 |
| `sensitivePoints` | string[] | 否 | 敏感话题；缺省为空数组 |
| `actionItems` | string[] | 否 | 待办事项；缺省为空数组 |
| `evidenceRefs` | array | 否 | 证据引用（由执行层附加） |

## 与「外联脚本」的区别（**重要**）

会面脚本与外联脚本是**两个不同的技能，输出结构不同**：

| | 外联脚本 | **会面脚本** |
|---|---|---|
| 核心结构 | `scriptTitle` + `sections[]` | **`agenda[]` + `talkingPoints[]`** |
| 特有字段 | `callObjectives[]`、`keyMessages[]` | `sensitivePoints[]`、`actionItems[]` |

**不得把两者视为同一契约**。此前曾误将外联脚本的结构套用于会面脚本，
经实现比对后更正。

## 纪律

- 事实仅来自 `structuredFacts` / `knowledgeContext`，**不得臆造客户事实**；
- 生成内容为 humanGate 性质，**不携带任何审批状态**；
- 模型故障 fail-closed（返回 `skill_error`，不返回残缺半成品）。
