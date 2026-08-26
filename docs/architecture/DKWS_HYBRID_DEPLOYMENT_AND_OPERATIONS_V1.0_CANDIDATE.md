# DKWS 混合部署与运维设计 V1.0（候选）

> 状态：CANDIDATE
> 日期：2026-08-26
> 工作流：DKWS-C-MIXED-ARCH-REMEDIATION-01

## 1. 进程拓扑

```text
DKWS 产品
├── Python Core :8106
├── Java Skill Runtime :18080（内部，仅 loopback/内网）
├── Sandbox Runner（bwrap 子进程）
└── Worker（Python 异步任务）
```

## 2. 部署顺序

1. 启动 Python Core
2. 启动 Java Skill Runtime
3. Python Core readiness 检查 Java Runtime 可用性
4. 启动 Worker

## 3. 故障降级

| 故障 | 行为 |
|---|---|
| Java Runtime 不可达 | 依赖 Java Runtime 的 Skill fail-closed；知识只读能力继续 |
| Sandbox 不可用 | 工具类 Skill fail-closed |
| 模型不可用 | 按 Skill 策略返回 DEGRADED 或 fail-closed |
| Python Core 不可用 | 全部不可用 |

## 4. 资源预算

- Python Core：建议 1-2 CPU / 2-4GB
- Java Runtime：建议 1-2 CPU / 2-4GB JVM heap
- Sandbox 并发：建议 2-4
- 单机总预算：4-8 CPU / 8-16GB（待 Owner 批准）

## 5. 可观测

- 统一 JSON 日志字段：requestId, traceId, tenantId, skillId
- W3C Trace Context 贯通
- Metrics：HTTP、Skill、Tool、Model、Sandbox
- 告警：Java Runtime down、Sandbox 失败率、磁盘、JVM heap

## 6. 发布与版本

- 一个发布 manifest，包含 Python/Java/契约/Skill hash
- 两套构建，一个发布 Gate
- 双 SBOM
- 升级顺序：先 Java Runtime，再 Python Core，或按兼容矩阵

## 7. 备份

- 备份 Python Runtime Store、知识资产、受控 Skill 包
- Java Runtime 无状态，不备份

## 8. 回滚

- 保留上一版本发布 manifest
- 回滚顺序：Python Core → Java Runtime → Skill 版本
