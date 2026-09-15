# 外联脚本 · 输出结构

本文件声明 `skill-customer-outreach-script` 的结构化输出契约。
来源为 `SKILL.md` 的「执行契约」段，此处展开为可校验的 JSON 结构。

## 输出结构

```json
{
  "scriptTitle": "外联脚本标题（字符串，面向客户经理）",
  "sections": [
    {
      "heading": "段落标题",
      "content": "段落正文"
    }
  ],
  "callObjectives": [
    "本次外联要达成的目标（字符串数组）"
  ],
  "keyMessages": [
    "必须传达的关键信息（字符串数组）"
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
| `scriptTitle` | string | 是 | 脚本标题 |
| `sections` | array | 是 | 正文段落，每项含 `heading` 与 `content` |
| `callObjectives` | string[] | 是 | 外联目标清单 |
| `keyMessages` | string[] | 是 | 关键信息清单 |
| `evidenceRefs` | array | 是 | 证据引用；**无依据处应如实标注，不得臆造** |

## 纪律

- 事实仅来自 `structuredFacts` / `knowledgeContext`，**不得臆造客户事实**；
- 生成内容为 humanGate 性质，**不携带任何审批状态**；
- 模型故障 fail-closed（返回 `skill_error`，不返回残缺半成品）。
