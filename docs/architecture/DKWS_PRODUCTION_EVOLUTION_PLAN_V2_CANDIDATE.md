# DKWS 生产演进计划 V2（候选）

> 状态：CANDIDATE_READY_FOR_OWNER_REVIEW
> 日期：2026-08-26
> 替代关系：替代 V1 候选（`docs/production-evolution-plan.md`），V1 保留为历史。
> 依据：独立评审报告 + Phase 0 受控结论

## 0. 受控状态

```text
PHASE_1_DECISION=MODIFY_THEN_APPROVE
BASELINE_STATE=DRAFT_CANDIDATE
PRODUCTION_READY=NO
GITS_UAT_PASS=NO
```

## 1. Phase 0：基线、产品边界、契约、ADR、NFR

### 目标
收敛冲突文档，明确独立服务端边界，建立机器可验证契约唯一权威源，补齐 ADR/NFR，为 Owner 提供是否批准 Phase 1 的决策依据。

### 交付物
- 状态唯一权威源、冲突登记册、替代关系表
- 独立服务边界设计
- Runtime Control Plane 设计
- OpenAPI 3.1 + JSON Schema
- ADR-012~015
- 生产 NFR 候选
- GITS A+B 交接包
- Phase 1 验收测试计划

### 退出标准
- 所有已知文档矛盾已解决或显式登记
- 契约 hash 可独立重算
- v1→v2 兼容策略明确
- Owner 完成 Phase 0 审批

## 2. Phase 1：单机单租户生产候选

### 范围
- 单机、单实例、单租户
- 文件系统知识权威源
- SQLite Runtime Store
- 独立 Worker
- API Key + TLS 边界
- 限流与大小限制
- 持久化幂等、持久化 Job
- Evidence/Gate 审计
- 最小 Metrics、Tracing、告警
- 备份恢复
- CI/CD 和供应链安全
- 不依赖外部智能体运行平台

### 必须新增/修改
- Secret Provider、密钥轮换、吊销
- SQLite WAL、migration、备份恢复
- 幂等 payload hash、冲突 409
- Job 原子领取/lease/重试/dead-letter
- 认证中间件、限流、body limit、CORS/Host 校验
- 结构化日志、/livez、/readyz、/metrics
- Docker Compose + systemd 模板
- SBOM、依赖锁、SAST/DAST、镜像扫描
- 数据分类、脱敏、审计防篡改
- 最小 SLO/告警/运行手册

### 退出标准
- 安全、重启、并发、断电、备份恢复、升级回滚测试通过
- 独立 QA 签署
- Owner 决定是否进入内网试点

## 3. Phase 2：可靠执行与完整可观测性

- 持久 Worker 全面落地：租约、取消、deadline、人工重放
- LLM Gateway：重试/熔断/限流/成本/预算
- Prompt Registry、Model Policy、Eval Gate
- Guardrails、事实一致性、幻觉检测
- OpenTelemetry Trace 规范
- SLO/告警/仪表盘/成本运营

## 4. Phase 3：知识源、工具与 LLM 治理深化

- KnowledgeSource typed capability + registered query
- KnowledgeMap Registry / RoutePolicy / ActivationPlan
- ToolRegistry：默认拒绝、权限、沙箱、egress、Secret、回执
- 首批只做 Parquet/Kùzu/受控 HTTP
- 插件包签名、版本、停用
- LLM 评测集、回归阈值、红队

## 5. Phase 4：受控多租户和企业集成

- 直接目录级租户命名空间（不做先列级作为正式方案）
- tenant_id 全链路
- 数据分类、脱敏、删除、保留、legal hold
- 共享知识资产授权
- 企业审计与合规集成

## 6. Phase 5：按触发条件扩展

触发条件需由真实容量/性能/HA/SLA 数据驱动，当前不启动：

- PostgreSQL 切换
- 多实例/Worker 横向扩展
- 对象存储/共享文件系统
- 外部消息队列
- active-passive/多活

## 7. 每个 Phase 必须包含

目标、输入、交付物、依赖、退出标准、自动化测试、人工验证、风险、回滚、Owner 决策点、独立 QA Gate。

## 8. 与 V1 的主要差异

| 项目 | V1 | V2 |
|---|---|---|
| 前置 | 无 Phase 0 | 新增 Phase 0 |
| 多租户 | 先列级后目录级 | 正式方案直接目录级；Phase 1 单租户 |
| 数据治理 | 推迟 Phase 4 | 基础治理前移 Phase 1 |
| 工具/知识源 | 自由 statement | typed/registered/capability |
| 供应链安全 | 未详细 | Phase 1 必须 |
| Phase 1 Metrics | 与 Phase 2 冲突 | 最小运行指标，Phase 2 扩展 |
