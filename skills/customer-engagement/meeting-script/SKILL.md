---
name: skill-customer-meeting-script
version: 1.0.0
description: 生成客户经理会面脚本（结构化产物 MeetingScriptResult），输入客户画像/产品候选/敏感点。
intents:
  - 会面脚本
  - 拜访准备
user-invocable: false
---

# 会面脚本 Skill

## 执行契约

- 激活：`POST /api/skill/execute`，`skillId=skill-customer-meeting-script`
- 请求 `request`：`{ customerId, structuredFacts: { profile, productCandidates, sensitivePoints }, knowledgeContext? }`
- 输出 `data`（结构化）：`{ agenda[], talkingPoints[], sensitivePoints[], actionItems[] }`

## 纪律

- 敏感点如实呈现（不回避、不臆造）；
- 模型故障 fail-closed；产物 humanGate 性质，无审批状态。
