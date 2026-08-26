# DKWS 文档替代关系表（Supersession Map）

> 日期：2026-08-26
> 规则：旧文件保留；通过本表明确谁继续有效、谁被替代、谁是历史。

| 旧/易混淆文件 | 当前有效文件 | 关系 | 说明 |
|---|---|---|---|
| `dkws/docs/architecture.md`（旧版） | `docs/architecture/DKWS_INDEPENDENT_SERVER_BOUNDARY_V1.0.md` + `docs/architecture/DKWS_RUNTIME_CONTROL_PLANE_V1.0.md` | SUPERSEDED_BY_NEW_DESIGN | 旧架构保留为历史，新增独立边界/控制面为 Phase 0 设计 |
| `dkws/README.md` 中状态/能力/测试声明 | `docs/governance/DKWS_STATUS_BASELINE_CANDIDATE.yaml` | SUPERSEDED_FOR_STATUS | README 保留工程说明，状态以 YAML 为准 |
| `dkws/docs/skill-execute-api-contract.md`（v1.3） | `docs/contracts/openapi/dkws-openapi-v2.yaml` + `docs/contracts/schemas/*.json` | SUPERSEDED_AS_MACHINE_CONTRACT | v1.3 保留为兼容/历史；生产合同以 v2 候选为准 |
| `dkws/docs/skill-execute-api-contract-v1.4.md`（v1.4） | 同上 | SUPERSEDED_AS_MACHINE_CONTRACT | v1.4 保留为增量说明 |
| `dkws/docs/production-evolution-plan.md`（V1） | `docs/architecture/DKWS_PRODUCTION_EVOLUTION_PLAN_V2_CANDIDATE.md` | SUPERSEDED_BY_V2_CANDIDATE | V1 保留为历史候选 |
| `dkws/ADR.md`（IMP-ADR-001~011） | `docs/adr/ADR-012*` 等新 ADR | EXTENDED_BY_NEW_ADR | 旧 ADR 仍有效，新 ADR 追加 |
| `dkws/docs/HANDOVER-2026-08-23.*` | `$WS/HANDOVER.md` / `HANDOVER.txt` | SUPERSEDED_FOR_NEW_SESSION | 历史交接保留 |
| `dkws/docs/handover-review-2026-08-26.md` | `docs/governance/*` + `docs/architecture/*` + `docs/contracts/*` | SUPERSEDED_FOR_PHASE0_DETAILS | 评审文档仍为背景材料 |

## 替代原则

1. 不删除历史文件。
2. 新文件在头部声明 `supersedes` 或 `extends`。
3. 冲突以状态基线 YAML、契约 v2、ADR 为准。
4. 任何替代均需在冲突登记册可追溯。

## C′ 混合架构整改新增替代关系（2026-08-26）

| 旧/候选文件 | 新候选文件 | 关系 |
|---|---|---|
| `docs/architecture/DKWS_SPRING_AI_ALIBABA_VS_PYTHON_NATIVE_COMPARISON_V1.0.md` | `docs/architecture/DKWS_CONTROLLED_HYBRID_ARCHITECTURE_V1.0_CANDIDATE.md` | SUPERSEDED_BY_C_PRIME |
| `docs/architecture/DKWS_PRODUCTION_EVOLUTION_PLAN_V2_CANDIDATE.md` | `docs/architecture/DKWS_PRODUCTION_EVOLUTION_PLAN_V2.1_CANDIDATE.md` | SUPERSEDED_BY_V2_1 |
| `docs/integration/GITS_DKWS_A_PLUS_B_HANDOFF.md` | `docs/integration/GITS_DKWS_A_PLUS_B_HANDOFF_V1.1_CANDIDATE.md` | SUPERSEDED_BY_V1_1 |
| `poc/spring-ai-alibaba-skill-runtime/README.md` | `poc/spring-ai-alibaba-skill-runtime/POC2_PLAN.md` / `POC2_RESULT.md` | SUPERSEDED_FOR_POC2_STATUS |
