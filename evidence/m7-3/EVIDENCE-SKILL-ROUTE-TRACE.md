# 证据：技能 trace 反映解析路由（M7.3 第五步 b-light）

```text
PACKAGE   : M7-3-5b-LIGHT-SKILL-ROUTE-TRACE（用户批准："同意执行你的建议"）
AUTHORITY : docs/governance/KERT_PENDING_OWNER_DECISION_M7_EVOLUTION_V1.0.md §0（D1-A）
BRANCH    : feature/m7-3-knowledge-map-route（base 57e8a25）
DATE      : 2026-09-15
ENV       : python3 3.10.12；ruff 0.16.4（= ci.yml:49）
```

## 1. 范围（**只做可观测性**，不改知识读取）

把 `skills.py` 三个技能里"进入知识地图"的**硬编码叙述**改为**按计划如实记录**：

| 结果 | trace 条目 | 说明 |
|---|---|---|
| 解析成功 | `status=ok` + `mapId` / `planHash` / `versions` | 与 `/v1/routing/plan` **同源同值** |
| 解析成功但地图 ≠ 技能自身 KI 清单对应地图 | 追加 `mapMismatch=True` + `mapExpected` | 分歧**必须可见**，不静默 |
| 计划被拒 | `status=blocked` + 拒绝码（`ROUTE_*` / `KNOWLEDGE_MAP_*` / `ONTOLOGY_REFERENCE_*`） | **一律不回落**硬编码 |
| 工作区未配置 / 解析异常 | `status=blocked` + `ROUTE_UNRESOLVED` | 同上 |

`status` 沿用 trace 既有词表（`ok/skipped/blocked/failed`），**不新增枚举值**；
`assemblyTrace` 在合同中是 `additionalProperties: true`（不透明）⇒ **无需改合同**。

## 2. 交付

| 文件 | sha256（前 16） | 说明 |
|---|---|---|
| `src/kert/application/skills.py` | `fd1914cc6d8fb3bf` | `_trace_knowledge_map` 改为解析驱动（3 处调用点不变） |
| `tests/integration/test_skill_routing_trace.py` | — | **8 例** |

## 3. 命令与结果（原始退出码）

| 命令 | 退出码 | 结果 |
|---|---|---|
| `pytest tests/integration/test_skill_routing_trace.py` | **0** | 8 passed |
| `pytest tests/integration/test_skills.py`（行为未变的既有面） | **0** | 全通过 |
| `pytest tests/unit tests/integration` | **0** | **1282 passed, 1 skipped, 1 xfailed**（无回归） |
| `ruff check src/ tests/` | **0** | `All checks passed!` |

## 4. 变异自证（四项，基线 PASS → 变异 FAIL → 恢复 PASS）

日志：`evidence/m7-3/skill-route-trace-mutation-*.log`；恢复后 `skills.py=fd1914cc6d8fb3bf`。

| 变异 | 施加方式 | 变异后 FAIL 的用例 |
|---|---|---|
| **M1** 被拒时回落硬编码地图 | 拒绝分支改为写 `status=ok` + `expected_map_id` | `test_unprovisioned_workspace_records_blocked_but_skill_still_runs`、`test_ontology_denial_code_is_passed_through` |
| **M2** 失配静默 | `if resolved_id != expected_map_id:` → `if False:` | `test_map_mismatch_is_surfaced_not_hidden` |
| **M3** 任务类型硬编码（三技能都用 OUTREACH） | `.build(task)` → `.build("OUTREACH_PREPARATION")` | `test_each_skill_reports_its_own_task` |
| **M4** trace 不带 planHash | 删 `"planHash": decision.plan_hash` | `test_provisioned_workspace_records_resolved_plan`、`test_trace_plan_hash_equals_routing_plan_api`、`test_each_skill_reports_its_own_task` |

## 5. 测试期发现的两个**真实行为**（不是猜测，均据实调整用例）

1. **本体引用非法 ⇒ 返回拒绝码，不抛错**：`PlanDenial(code=ONTOLOGY_REFERENCE_INVALID)`
   （先用探针实测确认，再写断言；未凭猜测定契约）。
2. **`previsit` 的"无新证据"门禁在路由之前**：该门禁位于 `execute()` 中、技能分派**之前**
   （既有业务策略，本步**未改动**）。故 previsit 缺 `evidenceTimestamp` 时早退、
   trace 中**没有**路由条目。
   - 已加用例 `test_route_trace_absent_when_blocked_before_routing` 把该**边界钉住**，
     避免日后误以为"trace 一定含路由条目"；
   - ⚠ **遗留缺口**：早退场景下无法从 trace 回答"本技能本该用哪张地图"。
     若要补齐，需把路由 trace 提到门禁之前 —— 属**独立议题**，本步未做。

## 6. 附带发现：合同对 `assemblyTrace` 的类型**失实**（**已获批准并修正**）

`specs/kert-openapi-v1.yaml` 原声明 `assemblyTrace: type: object`，但实现
（`SkillExecuteResult.assembly_trace`）返回**数组**。Contract Owner 于 **2026-09-15 批准修正**，
已落地：

- 合同改为 `type: array` + `items`（并按 `$ref` 语义指向 canonical schema，不复写字段）；
- canonical schema `docs/contracts/schemas/assembly-trace.schema.json` 补入 v1.5 新字段
  （`mapId`/`mapExpected`/`mapMismatch`/`planHash`/`versions`）；
- 实现字段名由自造的 `code` **对齐到 canonical 的 `errorCode`**（避免同义重复字段）；
- 新增**机械核对**用例：实现产出的 ok/blocked 两类 trace 条目须通过 canonical schema 校验
  （`test_emitted_trace_entries_conform_to_canonical_schema`），并用例钉住合同为数组
  （`test_spec_assembly_trace_is_array_not_object`）。

## 7. 非声明

- 本证据**不是** `QA_PASS`、**不是** Contract Owner 批准；**不**声明生产就绪、**不**声明 GITS UAT 通过；
- **不**声明第五步完成：**⑤b-full（技能按计划读资产，计划拒绝即拒绝执行）未做**；
- **不**改变技能读取哪些知识条目（本步仅可观测性）；未改 `03_core`、未改 GITS 仓；
- 未 push（`AGENTS.md` 规则 #10）。
