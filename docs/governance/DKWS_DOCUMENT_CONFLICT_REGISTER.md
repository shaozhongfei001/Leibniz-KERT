# DKWS 文档冲突登记册（Phase 0 候选）

> 日期：2026-08-26
> 原则：不静默覆盖历史；每项冲突标记状态、证据、处理方式。
> 状态：OPEN / RESOLVED_CANDIDATE / PENDING_OWNER_DECISION

| ID | 冲突 | 证据位置 | 当前判定（候选） | 处理方式 | 状态 |
|---|---|---|---|---|---|
| C-01 | 项目状态：SPEC/REQUIREMENTS_MATRIX 说 IMPLEMENTED=NO/DRAFT_CANDIDATE，README 说 IMPLEMENTED_PENDING_QA，交接说能力完成 | SPEC.md、REQUIREMENTS_MATRIX.md、README.md、HANDOVER.md | 未基线、未独立 QA、实现声明为 PENDING_EVIDENCE | 以 `DKWS_STATUS_BASELINE_CANDIDATE.yaml` 为唯一权威源；保留旧文件并标记 superseded | RESOLVED_CANDIDATE |
| C-02 | Skill 数量：README/architecture 写 10，健康接口/HANDOVER 写 12 | README.md、architecture.md、health API | 当前运行态为 12 Skill；旧文档标记 superseded | 状态基线记录 12；旧文档加入替代关系 | RESOLVED_CANDIDATE |
| C-03 | R1 状态：代码注释/SKILL.md 说下线移除，注册表/健康接口/HANDOVER 说已恢复 | src/dkws/application/skills.py、skills/customer-engagement/SKILL.md、health API | 当前实现注册并返回 R1；历史注释为旧状态 | 状态基线记录 CURRENT_IMPLEMENTED；旧注释待后续代码清理但不在 Phase 0 改实现 | RESOLVED_CANDIDATE |
| C-04 | 端口：v1.3 契约默认 8100，交接/运行 8106 | skill-execute-api-contract.md、HANDOVER.md、serve_skill_service.py | 当前运行 8106；端口应为配置项而非合同固定值 | 契约 v2 使用配置占位符；v1 文档标记 superseded | RESOLVED_CANDIDATE |
| C-05 | 地址：172.22.90.134 旧地址仍出现在部分文档；当前 127.0.0.1/192.168.31.220 | 多文档 | 生产配置禁用环境固定 IP；同机用 127.0.0.1 | 新契约/部署文档使用占位符；旧文档标记 superseded | RESOLVED_CANDIDATE |
| C-06 | 测试数量：137 / 192 / 197+ 并存 | README、HANDOVER、architecture | 无原始报告前不可作为独立证据；以复跑生成的报告为准 | 状态基线记录 DOCUMENTED_BUT_NOT_VERIFIED；后续复跑 | RESOLVED_CANDIDATE |
| C-07 | v1.3 数据所有权：正文说 structuredFacts/knowledgeContext 忽略，但输入表/示例仍传旧字段 | skill-execute-api-contract.md | 生产合同前必须消除；当前按“旧字段不参与判定”理解 | 契约 v2 严格 schema；v1 兼容层记录 deprecated | RESOLVED_CANDIDATE |
| C-08 | 原始规格禁止数据库 vs 生产演进引入 SQLite | SPEC/详细需求、production-evolution-plan | 方向合理但需 Owner ADR/基线变更 | ADR-012 记录并请求 Owner 批准 | PENDING_OWNER_DECISION |
| C-09 | 图谱深度：原 API 最大 3，ADR-011/实现放宽到 10 | 原始需求、ADR.md、services.py | 实现为 10；合同 v2 需统一 | 契约 v2 明确 max_depth=10；旧合同标记 superseded | RESOLVED_CANDIDATE |
| C-10 | Phase 1 Metrics 与 Phase 2 冲突：Phase 1 验收要 /metrics，Phase 2 才实现指标 | production-evolution-plan.md | Phase 1 只提供最小运行/安全指标，Phase 2 扩展业务/LLM 指标 | 演进 V2 明确拆分 | RESOLVED_CANDIDATE |
| C-11 | SP-20 落库：集成设计建议知识化入 Core，最新交接明确当前不落库 | 设计文档 vs HANDOVER | 当前不落权威库；是否落库由 Owner 决策 | 状态基线按“不落库”记录 | PENDING_OWNER_DECISION |
| C-12 | P05/P38 是否 DKWS：早期说明称本地能力，GITS Owner UAT 纠正称必须走 DKWS Skill | HANDOVER、GITS OWNER_UAT_W9A_FAIL | 以 GITS Owner UAT 纠正为准：P05/P38 须走 DKWS Skill | 在 A+B 交接中列入 DKWS 范围；本冲突不自行裁决 | PENDING_OWNER_DECISION |
| C-13 | GITS 适配器存在性：UAT 文档称 P30 缺少 adapter/base-url；GITS 工作区存在未提交 adapter 和 base-url | GITS docs/governance、GITS application.yaml、git status | 已提交基线可能缺少；工作区未提交改动已补充；证据不充分 | 标记 PLAUSIBLE_BUT_NOT_INDEPENDENTLY_VERIFIED；需 GITS commit/diff/log | PENDING_EVIDENCE |
| C-14 | `service` 名称：health 写死 customer-engagement；产品独立边界需产品中性 | server.py、HANDOVER | 后续 v2 改为配置化/产品中性 | 新契约 v2 标注 | RESOLVED_CANDIDATE |

## 替代关系汇总

- 状态/能力/证据以 `DKWS_STATUS_BASELINE_CANDIDATE.yaml` 为准。
- 文档替代关系见 `DKWS_SUPERSESSION_MAP.md`。
- 契约 v1/v2 替代关系以 OpenAPI/JSON Schema 候选为唯一权威源，v1 保留兼容层。

## C′ 混合架构整改新增冲突（2026-08-26）

| ID | 冲突 | 当前判定 | 处理方式 | 状态 |
|---|---|---|---|---|
| C-15 | POC README 称骨架待补齐，POC_RESULT 称部分 PASS，源码实现部分完成 | 以 POC2_RESULT 为当前状态，旧 README 标记 superseded | 新 POC2_PLAN/RESULT | RESOLVED_CANDIDATE |
| C-16 | 生产演进 V2 无 Java Runtime，对比文档另建 Phase 0-5 | 以 V2.1 为主，Java Runtime 独立 Gate | 新 V2.1 | RESOLVED_CANDIDATE |
| C-17 | GITS A+B 被推迟到 Java Runtime 之后 | 以独立评审为准：A+B 不等 Java Runtime | GITS V1.1 | RESOLVED_CANDIDATE |
| C-18 | 独立服务边界仍把 Skill 执行全放 Python dkws-server | C′ 将 Java Runtime 作为内部执行器 | 新 C′ 架构 | RESOLVED_CANDIDATE |
| C-19 | OpenAPI `x-contract-bundle-hash: PENDING_COMPUTE` 与 manifest hash 关系不清 | 以 manifest 为实际 hash，OpenAPI 中改为引用 manifest | 后续修正 | PENDING |
