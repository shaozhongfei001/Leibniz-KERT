# 任务包：v1 ↔ v2 契约归并**候选方案**（冲突 C-20 收口）

```text
TASK_ID    : M7-CLOSURE-C20-CONTRACT-MERGE-CANDIDATE
派发人     : Tech Lead
授权依据   : Contract Owner 2026-09-15 批准"将 v1↔v2 双权威归并**列入** W8/Phase 0 收口"
             登记：docs/governance/KERT_PENDING_OWNER_DECISION_M7_EVOLUTION_V1.0.md §0.1
            冲突登记：docs/governance/KERT_DOCUMENT_CONFLICT_REGISTER.md **C-20**
性质       : **只读分析 + 候选方案**（decision-ready）
```

## 1. 目标（可验收的产出）

1. `evidence/m7-3/CANDIDATE-CONTRACT-MERGE-V1-V2.md`，须含：
   - **差异矩阵**：`specs/kert-openapi-v1.yaml`（1.5.0，运行中权威）vs
     `docs/contracts/openapi/kert-openapi-v2.yaml`（2.0.0-candidate）的
     **路径级 / schema 级 / 错误码级 / 鉴权级**逐项差异（每项给出证据行号）；
   - **归并原则建议**（≥2 个可选方案 + 取舍），至少回答：
     单一权威选谁？`/api/skill/*` 与 `/v1/*` 与 `/api/v2/*` 如何收敛？
     `docs/contracts/schemas/*.json` 与 v1 内联 schema 的关系？
     `scripts/validate_contract_bundle.py` 应校验哪一份？
   - **兼容与迁移**：对 GITS 调用方（现行调用 `/api/skill/*`）的影响与迁移路径；
   - **风险与回滚**：归并若不是纯 additive，需给出分期方案。
2. 结论必须**可被 Contract Owner 直接裁决**（含明确推荐项与否决理由）。

## 2. 硬性边界（违反即返工）

- **不得修改** `specs/kert-openapi-v1.yaml`、`docs/contracts/**`、任何合同文件；
- 不得修改 `src/**`、`tests/**`；不得 push；不得改 GITS 仓；
- 不得对"归并已完成"作任何暗示；本任务**不产生**合同效力。

## 3. 必须核对的既有事实（勿凭记忆）

| 事实 | 位置 |
|---|---|
v2 自述"Phase 0 候选，不表示生产合同已批准" | `docs/contracts/openapi/kert-openapi-v2.yaml` 头部 |
`docs/contracts/README.md` 原称"唯一权威源"（已于 2026-09-15 修正） | `docs/contracts/README.md` |
状态基线记 v13/v14 = CONFLICTING、v2 候选 = DESIGNED_AS_CANDIDATE | `docs/governance/KERT_STATUS_BASELINE_CANDIDATE.yaml` |
C-20 条目与处理方式 | `docs/governance/KERT_DOCUMENT_CONFLICT_REGISTER.md` |
v1.5 增量与追认范围 | `evidence/m7-3/CONTRACT_CHANGE_PROPOSAL_ROUTING_API.md`、§0.1 追认登记 |
校验工具只校验 v2 bundle | `scripts/validate_contract_bundle.py` |

## 4. 非声明（必须原样写入交付物）

不是 Contract Owner 批准、不构成合同修订、不改变 `PRODUCTION_RELEASE_GATE=BLOCKED`、
不代表 GITS UAT 通过；归并**未执行**。
