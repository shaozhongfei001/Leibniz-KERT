# DKWS 生产 NFR 基线 V1.0（候选）

> 状态：CANDIDATE
> 日期：2026-08-26
> 说明：所有未由 Owner/银行制度给出的数值标记 `PENDING_OWNER_DECISION`，不得视为正式承诺。

## 1. 范围

首个生产候选限定为：单机、单实例、单租户、文件系统知识权威源、SQLite Runtime Store。

## 2. 可用性

| 项 | 候选值 | 状态 |
|---|---|---|
| 服务可用性目标 | 99.5%（月度） | PENDING_OWNER_DECISION |
| 维护窗口 | 允许计划内重启 | PENDING_OWNER_DECISION |
| 故障降级 | 知识只读可用；写/异步任务不可用时明确失败 | CANDIDATE |

## 3. 性能

| 项 | 候选值 | 状态 |
|---|---|---|
| API 读请求 P95 延迟 | ≤ 300ms（不含 LLM） | PENDING_OWNER_DECISION |
| 同步 Skill（非 LLM 重）P95 | ≤ 2s | PENDING_OWNER_DECISION |
| SP-20 异步创建响应 | ≤ 1s 返回 202 | CANDIDATE |
| SP-20 总完成时间 | 目标 ≤ 60s，允许 3min | CANDIDATE |
| 最大并发请求 | 50（API 层） | PENDING_OWNER_DECISION |
| 最大并发 SP-20 | 2 | CANDIDATE |
| 最大图谱结果 | nodes ≤ 1000，edges ≤ 5000，响应 ≤ 5MB | CANDIDATE |
| 请求体上限 | 10MB | PENDING_OWNER_DECISION |
| 响应体上限 | 20MB | PENDING_OWNER_DECISION |

## 4. 恢复

| 项 | 候选值 | 状态 |
|---|---|---|
| Job 恢复时间（进程重启） | ≤ 2min 自动重新入队 | CANDIDATE |
| RPO | 24h | PENDING_OWNER_DECISION |
| RTO | 4h | PENDING_OWNER_DECISION |
| Core 备份频率 | 每日 | PENDING_OWNER_DECISION |
| Runtime DB 备份频率 | 每日 | PENDING_OWNER_DECISION |
| 恢复演练频率 | 季度 | PENDING_OWNER_DECISION |

## 5. 容量与保留

| 项 | 候选值 | 状态 |
|---|---|---|
| 知识资产规模 | ≤ 100GB 单盘 | PENDING_OWNER_DECISION |
| Skill 数量 | 50 以内 | CANDIDATE |
| 单次 LLM 成本预算 | 按 Skill/租户月度预算 | PENDING_OWNER_DECISION |
| Token 预算 | 月度总 Token 上限 | PENDING_OWNER_DECISION |
| 日志保留 | 30 天 | PENDING_OWNER_DECISION |
| 审计保留 | 180 天 | PENDING_OWNER_DECISION |
| 数据删除时限 | 按监管要求 | PENDING_OWNER_DECISION |

## 6. 安全补丁

| 项 | 候选值 | 状态 |
|---|---|---|
| 高危漏洞修复时限 | ≤ 7 天 | PENDING_OWNER_DECISION |
| 中危漏洞修复时限 | ≤ 30 天 | PENDING_OWNER_DECISION |
| 依赖扫描频率 | 每次构建 + 每周 | CANDIDATE |

## 7. 告警

| 告警 | 触发 |
|---|---|
| 服务 down | `/readyz` 连续失败 3 次 |
| 磁盘使用率 | > 80% warning，> 90% critical |
| SQLite WAL 大小 | 超过 1GB |
| LLM 失败率 | 连续 5 次失败或 5% 错误率 |
| Job 失败/DEAD | 1 分钟内出现 |
| 备份失败 | 任何失败 |
| 成本预算 | 超过 80% 告警，100% 阻断 |

## 8. 未决项

所有 `PENDING_OWNER_DECISION` 项必须由 Owner/业务/合规提供后才能作为 Phase 1 验收基线。
