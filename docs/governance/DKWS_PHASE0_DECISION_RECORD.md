# DKWS Phase 0 Decision Record（候选）

> 状态：CANDIDATE_READY_FOR_OWNER_REVIEW
> 日期：2026-08-26
> 角色：Tech Lead / Architecture Remediation Lead
> 前置依据：`docs/dd/DKWS_independent_architecture_review_2026-08-26_V1.0.md`
> 本文档不替代 Owner 决策，不替代正式基线。

## 1. 本记录目的

记录 Phase 0 整改中需要 Owner 确认的关键决策，以及 Tech Lead 在受控范围内形成的候选方案。

## 2. 受控结论（来自独立评审）

```text
GATE_DECISION=PASS_WITH_REQUIRED_CHANGES
DESIGN_REVIEW=COMPLETE
IMPLEMENTATION_VERIFICATION=PARTIAL
PRODUCTION_RELEASE_GATE=BLOCKED
GITS_UAT_PASS=NO
GITS_NEXT_OPTION=A+B
PHASE_1_DECISION=MODIFY_THEN_APPROVE
BASELINE_STATE=DRAFT_CANDIDATE / NOT_BASELINED
PRODUCTION_READY=NO
FROZEN=NO
```

## 3. Owner 待决策清单

| ID | 决策项 | 候选建议 | 影响 |
|---|---|---|---|
| D-01 | 是否批准 DKWS 定位为“独立服务端软件，不依赖外部智能体运行平台” | 批准 | 影响产品边界、配置命名、部署和 Skill 资产 |
| D-02 | 是否批准新增 Phase 0 | 批准 | 影响演进计划版本和 Gate |
| D-03 | 是否批准 SQLite Runtime Store 并变更“禁止数据库”旧约束 | 批准，通过 ADR-012 | 影响 SPEC 验收口径 |
| D-04 | 是否批准 API Key + TLS 边界作为首期认证 | 批准 | 影响生产安全基线 |
| D-05 | 是否批准首个生产候选为单机、单实例、单租户 | 批准 | 影响多租户路径和 NFR |
| D-06 | 是否批准 v1 保留兼容层、新增 `/api/v2` 候选 | 批准 | 影响契约版本策略 |
| D-07 | 是否批准 GITS 采用 A+B 且 B 先落地 | 批准 | 影响 GITS 交接和 UAT |
| D-08 | 是否批准 Phase 1 修改后范围（含 Secret、CI/CD、备份恢复、供应链安全） | 批准 | 影响 Phase 1 实施范围 |
| D-09 | 生产 SLO/RPO/RTO、数据保留期、成本预算等业务指标 | 待 Owner 提供 | 无法由 Tech Lead 决定 |

## 4. 未决事项

- `ME-01` DKWS 源码受控 commit 锚点缺失
- `ME-03` 原始测试报告缺失
- `ME-06/07` GITS P24/P30 差异与 UAT 原始证据缺失
- `ME-08` GITS 权威 ContextPackage/附录合同缺失
- `ME-10/11` 银行数据制度与生产指标缺失

以上未决事项不因 Phase 0 文档完成而关闭，需 Owner 提供证据或明确 `PENDING_OWNER_DECISION`。

## 5. 状态声明

- 本文档为候选，不视为正式基线。
- Phase 0 输出在 Owner 审批前不得作为生产实施授权。
- Tech Lead 不代替 Owner 或独立 QA 签署。
