---
name: skill-customer-outreach-script
version: 1.0.0
description: 生成客户经理外联脚本（结构化产物 OutreachScriptResult），输入客户画像/KYC 摘要/访前目标。
intents:
  - 外联脚本
  - 客户触达
user-invocable: false
---

# 外联脚本 Skill

## 执行契约

- 激活：`POST /api/skill/execute`，`skillId=skill-customer-outreach-script`
- 请求 `request`：`{ customerId, structuredFacts: { profile, kyc, visitGoals }, knowledgeContext? }`
- 输出 `data`（结构化）：`{ scriptTitle, sections[], callObjectives[], keyMessages[] }`

## 纪律

- 事实仅来自 `structuredFacts`/`knowledgeContext`，不得臆造客户事实；
- 模型故障 fail-closed（返回 `skill_error`，不返回残缺半成品）；
- 生成内容为 humanGate 性质，不携带任何审批状态。
