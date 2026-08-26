---
name: customer-engagement
version: 1.0.0
description: 客户经理持续经营 Skill 族——外联脚本、会面脚本两个独立 Skill 的运行平台（dsh 即运行平台，HTTP 服务激活）。
intents:
  - 外联脚本生成
  - 会面脚本生成
user-invocable: false
---

# 客户经理持续经营 Skill 族

本族包含两个独立可激活的 Skill，由 dsh（deepseek-harness）作为运行平台注册并通过
`POST /api/skill/execute` 对外服务（当前项目 gits 经 HTTP 调用）：

| skillId | 产物 | 独立激活 |
|---|---|---|
| `skill-customer-outreach-script` | 外联脚本 | 是 |
| `skill-customer-meeting-script` | 会面脚本 | 是 |

> 注：`skill-customer-previsit-report`（R1 拜访报告）已于 2026-08-21 下线移除，
> 相关资产（previsit-report/SKILL.md）与执行器一并删除。

## 使用约束

- 服务默认不可无人值守生成需人工批准的内容（humanGate 产物）；
- 机器事实优先：结构化事实仅作为数据注入，不得臆造客户事实；
- 敏感数据不落盘、日志脱敏。

## 子 Skill

- `outreach-script/SKILL.md` — 外联脚本
- `meeting-script/SKILL.md` — 会面脚本
