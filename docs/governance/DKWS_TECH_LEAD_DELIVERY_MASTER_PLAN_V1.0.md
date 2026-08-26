# DKWS Tech Lead 整体工程交付落地规划 V1.0

> 日期：2026-08-27
> 状态：CANDIDATE
> 工作流：DKWS-C-MIXED-ARCH-REMEDIATION-01
> 目标：将 DKWS 从当前原型/POC 状态推进到“受控单机生产候选 + C′ 混合架构 + GITS A+B 真实联动”的可验收状态。

---

## 1. 当前基线

| 项 | 状态 |
|---|---|
| Python Core | 原型可用，生产加固未完成 |
| Java Skill Runtime | POC-2 PARTIAL_PASS |
| Sandbox | bwrap smoke pass，安全 Gate 未过 |
| 内部契约 | CANDIDATE，双端测试未完成 |
| GITS | UAT_PASS=NO，A+B 未完成 |
| 文档/ADR | Phase 0 与 C′ 候选已建立 |
| Git | 已推送 GitHub `Leibniz-KERT` |

## 2. 目标状态（最终达成）

```text
TARGET=INTERNAL_SINGLE_NODE_PRODUCTION_CANDIDATE
ARCHITECTURE=C_MODIFIED
TENANCY=SINGLE_TENANT
RUNTIME_STORE=SQLITE
JAVA_RUNTIME=INTERNAL_EXECUTOR
GITS_PATH=HTTP_TO_DKWS_PUBLIC_API_ONLY
SANDBOX=OS_LEVEL_NSJAIL_OR_BWRAP
PRODUCTION_READY=NO（直到 Owner + Independent QA 签署）
GITS_UAT_PASS=NO（直到 Owner 签署）
```

## 3. 总体阶段规划

```text
Phase 0A：C′ 架构与内部契约收敛（当前，基本完成，待 Owner 批准）
Phase 1：Python Core 生产加固
并行：GITS B→A 公共 HTTP 联动
Gate C-RUNTIME-01：Java Runtime POC-2 完整准入
Phase 2：Java Runtime 作为 DKWS 内部执行器接入
Gate C-SANDBOX-02：OS Sandbox 独立安全准入
Phase 3：受控启用 Tool、知识源和路由治理
Phase 4：按 Owner 决策扩展企业治理/多租户
Phase 5：按容量和 HA 触发条件扩展
```

## 4. 里程碑与退出标准

### M1：C′ 架构与契约基线（0-2 周）

交付物：

- [x] C′ 架构候选
- [x] ADR-016
- [x] 内部 OpenAPI/Schema
- [x] 内部契约 hash
- [ ] Owner 批准 C′ 架构
- [ ] Python/Java 双端 contract tests
- [ ] 文档冲突清零

退出标准：

- Owner 签署 C′ 架构决策
- 内部契约双端测试通过
- 所有已知冲突有明确处理

### M2：Python Core 生产加固（2-6 周）

交付物：

- [ ] API Key 认证 + TLS 边界
- [ ] 限流、请求体/响应体大小限制
- [ ] SQLite Runtime Store（幂等、Job、审计）
- [ ] 持久化异步 Worker
- [ ] 结构化日志、/livez、/readyz、/metrics
- [ ] 备份恢复与升级回滚
- [ ] Docker Compose / systemd 部署
- [ ] CI/CD、SBOM、依赖扫描
- [ ] 基础数据分类/脱敏

退出标准：

- 安全、重启、并发、断电、备份恢复测试通过
- 独立 QA 复跑
- Owner 批准进入内网试点

### M3：GITS B→A 真实 HTTP 联动（并行 2-6 周）

交付物：

- [ ] GITS 移除 Mock/H2 伪成功
- [ ] fail-closed 空态
- [ ] GITS→DKWS 公共 HTTP Adapter
- [ ] R1、供应链、SP-20、SP-21、Gate E2E
- [ ] 超时/鉴权/契约错误故障注入
- [ ] 两侧 requestId/traceId 证据

退出标准：

- GITS 真实调用 DKWS Python Core
- Owner UAT 签署
- `GITS_UAT_PASS=YES`（仅 Owner 可改）

### M4：Java Runtime POC-2 完整准入（Gate C-RUNTIME-01，4-8 周）

交付物：

- [ ] 两个以上 Skill 动态注册
- [ ] 动态 Skill→Tool 绑定
- [ ] Skill 版本化安装/激活/回滚/并发隔离
- [ ] 真实 ToolCall Receipt + ModelCall Receipt
- [ ] Python Core→Java Runtime 鉴权/幂等/deadline/取消/Trace
- [ ] 故障注入：重启、超时、重复请求、网络中断
- [ ] 自动化单元/契约/集成/安全/恢复测试
- [ ] SBOM、依赖/许可证/漏洞报告
- [ ] 性能与资源基准

退出标准：

- POC-2 十二项准入全部通过
- 独立 QA 复跑签署
- Owner 批准 Java Runtime 作为内部执行器

### M5：Java Runtime 接入 Python Core（Phase 2，8-12 周）

交付物：

- [ ] Python Core 生成 ExecutionPlan
- [ ] Java Runtime 执行并返回 ExecutionResult + Receipts
- [ ] 统一日志/Trace/Metrics
- [ ] Java Runtime 不可用时 Skill 级 fail-closed
- [ ] 统一发布 manifest、升级顺序、回滚矩阵

退出标准：

- Core→Runtime E2E 通过
- 故障降级矩阵验证通过
- 双栈运维文档与演练完成

### M6：OS Sandbox 安全准入（Gate C-SANDBOX-02，8-14 周）

交付物：

- [ ] bwrap/nsjail Runner 生产化
- [ ] 路径穿越、命令注入、网络、资源、超时、输出超限等负向用例
- [ ] 独立安全 QA
- [ ] Sandbox profile hash + ToolCallReceipt

退出标准：

- 安全负向用例全部通过
- 独立 Security QA 签署
- 才允许生产启用 Python/Shell Tool

### M7：受控启用 Tool、知识源和路由治理（Phase 3，12-18 周）

交付物：

- [ ] KnowledgeSource typed capability
- [ ] ToolRegistry 默认拒绝策略
- [ ] Skill/Route/ActivationPlan 治理
- [ ] Prompt/Model/预算治理
- [ ] 可观测闭环

退出标准：

- 工具与知识源调用可审计、可回滚、可配额
- 无未授权 Tool 调用

### M8：企业治理/多租户（Phase 4，按 Owner 决策，18-24 周）

交付物：

- [ ] 目录级租户隔离（如启用）
- [ ] 数据分类、脱敏、保留、删除、legal hold
- [ ] 审计导出与合规

退出标准：

- 按 Owner/合规要求验收

### M9：扩展触发（Phase 5，远期）

- 仅当真实容量/HA/SLA 触发时评估 PostgreSQL、多实例、对象存储、MQ

## 5. 每周 Tech Lead 例行动作

- 更新 `DKWS_C_MIXED_ARCH_REMEDIATION_MATRIX.md`
- 检查未关闭 Blocker/Major
- 跑相关测试并保存证据
- 维护契约 hash 与 supersession map
- 向 Owner 输出周报/决策请求

## 6. 测试与证据要求

每个阶段必须保存：

- 命令、工作目录、时间、版本、退出码
- 原始日志/报告
- PASS/FAIL/NOT_EXECUTED/BLOCKED
- 对应评审发现

## 7. 风险与应对

| 风险 | 应对 |
|---|---|
| 双栈运维复杂 | 统一发布 manifest、统一 OTel、统一告警 |
| Sandbox 未过 Gate | 生产保持 Tool 禁用，继续 Python-only 回退 |
| Java Runtime 准入失败 | 回退方案 B，不阻塞生产 |
| GITS 集成延迟 | A+B 与 Java Runtime 解耦，先走 Python Core |
| 团队技能不足 | 通过 AGENTS.md/开发规范/Codebuddy/Cursor 协作 |

## 8. 最终验收 Gate

```text
C-B01..C-B05 全部关闭或 PENDING_INDEPENDENT_QA
POC-2 十二项准入全部通过
Sandbox 独立安全 QA 通过
GITS UAT Owner 签署
独立 QA 签署
Owner 批准生产试点
```

## 9. 非声明

```text
本规划不表示当前已生产就绪。
本规划不表示 GITS UAT 已通过。
本规划不表示 Java Runtime 已生产可用。
本规划是 Tech Lead 交付路线，最终签署权在 Owner 与 Independent QA。
```
