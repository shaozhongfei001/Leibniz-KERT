# KERT 状态基线**修订候选**（M7.3 达成后）

```text
STATUS   : CANDIDATE_REVISION —— **本文件不改写基线**，供 Owner 签署后由 TL 应用
DATE     : 2026-09-16
AUTHOR   : Tech Lead
目标文件 : docs/governance/KERT_STATUS_BASELINE_CANDIDATE.yaml（2026-08-26 版，未改动）
纪律依据 : docs/governance/KERT_PENDING_OWNER_DECISION_M7_EVOLUTION_V1.0.md
           —— "权威状态文件落后于代码 ⇒ 应由 TL 出修订候选，**不静默改写**"
```

## 0. 为什么出这份候选

M7.3（Skill / Route / ActivationPlan 治理）已于 2026-09-15~16 实施并验证完毕，
但状态基线仍记 `knowledge_map_registry: DESIGNED_NOT_IMPLEMENTED`；另有若干条在更早
巡视中已被指出落后于代码（见下 R-2/R-3/R-4）。按上引纪律，TL **不**直接改写基线，
而是给出**逐条修订候选 + 证据**，交由 Owner 签署。

## 1. 修订候选（逐条，均附证据）

### R-1 `knowledge_map_registry`（**主修订项**，M7.3）

```yaml
  knowledge_map_registry:
-   state: DESIGNED_NOT_IMPLEMENTED
+   state: CURRENT_IMPLEMENTED
+   verification: PARTIAL
+   note: >-
+     控制面注册表 + 路由策略 + 可重放激活计划 + 本体引用（只读消费 gits CTR-SEM-002）
+     + 路由 API（v1.5，已由 Contract Owner 追认）+ 运行时供给 + 技能按计划读资产（fail-closed）
+     均已实现；受控 example 工作区端到端实测通过。verification 仍记 PARTIAL：
+     未经独立 QA、未在生产环境部署验证。
```

证据：

| 证据 | 位置 |
|---|---|
注册表 / 策略 / 计划 / 本体引用 | `121c0c2`、`5a95199`、`559c317` |
路由 API v1.5（合同先行 + 已追认） | `ac441e3`、`4612e08`；`specs/kert-openapi-v1.yaml`（`version 1.5.0`） |
运行时供给 + 编排 | `57e8a25`、`8b5fa99`；`src/kert/application/provision.py`、`deploy/docker-compose.yml` 的 `provision` 任务 |
技能按计划读资产 / 计划被拒即拒绝执行 | `5b9fb0d`；`src/kert/application/skills.py` |
端到端实测 | `evidence/m7-3/EVIDENCE-5B-FULL.md` §6.1（`count=3`；三技能 `assets=3/4/7`） |
**状态基线本文件自身也是证据**：原 `DESIGNED_NOT_IMPLEMENTED` 已被上述实现取代 | —— |

### R-2 `production_security`（更早巡视已指出）

```yaml
  production_security:
-   state: DESIGNED_NOT_IMPLEMENTED
+   state: CURRENT_IMPLEMENTED
+   verification: PARTIAL
+   note: 认证/限流/并发/大小限制/响应脱敏中间件已接线；生产 Key 与 TLS 边界待部署侧落实。
```

证据：`src/kert/api/server.py:218-222`（五类中间件注册）；
`KERT_PENDING_OWNER_DECISION_M7_EVOLUTION_V1.0.md` "另发现一处状态失真"段（该处指出
`production_security: DESIGNED_NOT_IMPLEMENTED` 与 `auth_enabled: false` 均落后于代码）。

### R-3 `production_observability`

```yaml
  production_observability:
-   state: DESIGNED_NOT_IMPLEMENTED
+   state: CURRENT_IMPLEMENTED
+   verification: PARTIAL
+   note: /livez,/readyz,/metrics 与可观测性中间件、结构化日志、OTel 可用性探测已实现；
+         采集链路与告警阈值属部署侧。
```

证据：`src/kert/api/server.py:242`（`ObservabilityMiddleware`）、`:403`（`/metrics`）、
`tests/integration/test_observability_endpoints.py`。

### R-4 `ci_cd`

```yaml
  ci_cd:
-   state: MISSING
+   state: CURRENT_IMPLEMENTED
+   verification: PARTIAL
+   note: CI 已存在（lint/type/test/e2e/覆盖账本等 job）；CD（自动发布）仍未建立，故记 PARTIAL。
```

证据：`.github/workflows/ci.yml`；`evidence/kert-e2e-ci/`。

### R-5 `contracts` 段（新增运行中权威）

```yaml
  openapi_v2_candidate:
    status: DESIGNED_AS_CANDIDATE
    machine_readable: true
+ v15_running_authority:            # 新增：v1.5 为**运行中权威**（服务实际实现）
+   status: CURRENT_AND_RATIFIED
+   machine_readable: true
+   path: specs/kert-openapi-v1.yaml   # version 1.5.0
+   note: >-
+     Contract Owner 于 2026-09-15 追认其 v1.5 additive 增量与 assemblyTrace 类型修正；
+     v1↔v2 双权威归并已**列入** W8/Phase 0 收口（冲突 C-20），归并**未执行**。
```

证据：`4612e08`；`evidence/m7-3/CONTRACT_CHANGE_PROPOSAL_ROUTING_API.md`（STATUS=已追认）；
`docs/governance/KERT_PENDING_OWNER_DECISION_M7_EVOLUTION_V1.0.md` §0.1；
`docs/governance/KERT_DOCUMENT_CONFLICT_REGISTER.md` C-20。

## 2. 明确**不**改动的条目（保持 `DESIGNED_NOT_IMPLEMENTED` / `MISSING`）

| 条目 | 原因 |
|---|---|
`tool_registry`（M7.2） | 未开工（见 WBS §M7.2） |
`multi_knowledge_source_framework`（M7.1） | 未开工；设计候选已派发（`evidence/m7-3/TASK_PACKAGE_M7-1-KNOWLEDGE-SOURCE-DESIGN.md`） |
`multi_tenant_isolation`（M8） | 按 Owner 决策，未开工 |
`backup_recovery_sop` / `sbom_supply_chain` | 未见实施证据，维持原状 |
`project.*` 顶层标志 | `baselined/frozen/production_ready/uat_pass/independent_qa_signed/`
`production_release_gate=BLOCKED` **一律不动** —— M7.3 完成不构成任何上述状态的改变 |

## 3. 应用方式（Owner 签署后由 TL 执行）

1. Owner 在本文件末签署（或逐条裁定 R-1~R-5）；
2. TL 按裁定把变更应用到 `docs/governance/KERT_STATUS_BASELINE_CANDIDATE.yaml`，
   并在该文件头部标注修订日期与依据（本文件路径）；
3. 若 Owner **否决**某条，该条**不进**基线，本文件保留否决记录。

## 4. 非声明

- 本文件是**候选**，**不是**基线、**不是**签署、**不是** ADR；
- **未**修改 `KERT_STATUS_BASELINE_CANDIDATE.yaml` 一个字节（"不静默改写"纪律）；
- R-1~R-5 的 `verification` 一律记 **PARTIAL**：均未经独立 QA、未经生产部署验证；
- 不代表 `PRODUCTION_RELEASE_GATE` 变化（仍 **BLOCKED**）、不代表 GITS UAT 通过。
