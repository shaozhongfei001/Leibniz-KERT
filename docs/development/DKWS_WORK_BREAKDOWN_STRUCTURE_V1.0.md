# DKWS 工程交付 WBS 详细拆分 V1.0

> 日期：2026-08-27
> 用途：供 CodeBuddy/Cursor/Tech Lead 按任务执行
> 对应主计划：`docs/governance/DKWS_TECH_LEAD_DELIVERY_MASTER_PLAN_V1.0.md`

---

## M1：C′ 架构与内部契约基线

### M1.1 Owner 决策记录

- 输出：Owner 批准 C′ 架构、Java Runtime 内部执行器、GITS 仅公共 HTTP、bwrap/nsjail 沙箱
- 验收：决策记录文档 + Owner 签署
- 责任：Tech Lead / Owner

### M1.2 Python/Java 双端契约测试

- 输出：Python consumer/provider + Java consumer/provider contract tests
- 验收：内部契约 hash 一致，测试通过
- 责任：Contract Owner / CodeBuddy

### M1.3 文档冲突清零

- 输出：更新冲突登记册、supersession map
- 验收：无未说明冲突
- 责任：Tech Lead

---

## M2：Python Core 生产加固

### M2.1 认证与安全边界

- API Key 认证
- TLS 反向代理边界
- 生产 profile 未启用 auth 时拒绝启动
- 验收：401/403/413/429 测试通过

### M2.2 限流与大小限制

- 按 API Key/IP 限流
- 请求体/响应体大小限制
- 并发限制
- 验收：限流与超限测试通过

### M2.3 SQLite Runtime Store

- 幂等表
- Job 表
- Evidence/Gate 审计表
- WAL、migration、备份
- 验收：重启幂等保留、Job 恢复测试通过

### M2.4 持久化异步 Worker

- 原子领取、lease、重试、dead-letter
- 验收：崩溃恢复测试通过

### M2.5 可观测性

- 结构化日志
- /livez、/readyz、/metrics
- OpenTelemetry 基础
- 验收：指标与日志可采集

### M2.6 备份恢复与升级回滚

- 备份脚本
- 恢复演练
- 升级顺序与回滚
- 验收：恢复演练报告

### M2.7 部署

- Docker Compose
- systemd 模板
- 验收：干净环境可启动

### M2.8 CI/CD 与供应链安全

- GitHub Actions
- 依赖锁、SBOM、漏洞扫描
- 验收：CI 全绿，SBOM 生成

### M2.9 数据分类与脱敏

- 字段敏感标记
- 日志/响应脱敏
- 验收：脱敏测试

### M2.10 性能与 NFR 基线

- 延迟、吞吐、并发、资源占用
- 验收：生成 baseline，不宣称达标

---

## M3：GITS B→A 公共 HTTP 联动（需 GITS 仓库授权）

### M3.1 GITS 移除 Mock/H2 伪成功

### M3.2 fail-closed 空态

### M3.3 GITS→DKWS HTTP Adapter

### M3.4 R1/供应链/SP-20/SP-21/Gate E2E

### M3.5 故障注入与证据

### M3.6 Owner UAT

---

## M4：Java Runtime POC-2 完整准入

### M4.1 两个以上 Skill 动态注册

### M4.2 动态 Skill→Tool 绑定

### M4.3 Skill 版本化安装/激活/回滚/并发隔离

### M4.4 真实 ToolCall/ModelCall Receipt

### M4.5 Python Core→Java Runtime 内部 API

### M4.6 故障注入

### M4.7 自动化测试

### M4.8 SBOM/依赖/漏洞

### M4.9 性能与资源基准

### M4.10 十二项准入评审

---

## M5：Java Runtime 接入 Python Core

### M5.1 ExecutionPlan 生成

### M5.2 ExecutionResult + Receipts 持久化

### M5.3 统一日志/Trace/Metrics

### M5.4 Java Runtime 故障降级

### M5.5 统一发布/升级/回滚

---

## M6：OS Sandbox 安全准入

### M6.1 bwrap/nsjail Runner 生产化

### M6.2 安全负向用例

### M6.3 资源限制

### M6.4 独立 Security QA

### M6.5 Sandbox profile hash + ToolCallReceipt

---

## M7：受控启用 Tool、知识源和路由治理

### M7.1 KnowledgeSource typed capability

### M7.2 ToolRegistry 默认拒绝

### M7.3 Skill/Route/ActivationPlan 治理

### M7.4 Prompt/Model/预算治理

### M7.5 可观测闭环

---

## M8：企业治理/多租户（按 Owner 决策）

### M8.1 目录级租户隔离

### M8.2 数据分类/脱敏/保留/删除/legal hold

### M8.3 审计导出与合规

---

## M9：扩展触发（远期）

### M9.1 容量/HA/SLA 触发评估

### M9.2 PostgreSQL/多实例/对象存储/MQ 评估

---

## CodeBuddy 首次任务包

```text
任务包：M2-P1
范围：M2.1、M2.2、M2.3
分支：feature/m2-p1-python-core-hardening
验收：安全、限流、SQLite Runtime Store 基础测试通过
证据：evidence/m2-p1/
```

## 任务执行模板

每个任务必须包含：

```text
任务ID
目标
依赖
交付物
验收标准
测试命令
证据路径
风险
```
