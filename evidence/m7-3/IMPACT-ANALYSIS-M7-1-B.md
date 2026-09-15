# 影响面分析：M7.1-B（真实能力适配器 + skills 接线）

```text
DOC_ID      : IMPACT-ANALYSIS-M7-1-B
TASK_ID     : M7-1-B-PREPARATION (前置件；非实施授权)
REPO        : Leibniz-KERT
性质        : 只读分析（**不改任何代码**）；decision-ready，供 Owner 裁决使用
依据        : evidence/m7-3/TL_DECISION_M7-1-FIRST-SLICE.md（第二片-A 授权与边界）
              evidence/m7-3/CANDIDATE-M7-1-KNOWLEDGE-SOURCE.md（§2/§3/§5/§6）
              evidence/m7-3/TL_DECISION_M7-1-B-PREPARATION（本任务授权）
基线提交    : 第二片-A 已入库（`14d3b69`）；本片**不含**任何代码改动
```

**硬性边界（本任务遵守情况）**：只新增本文件；**未**修改 `application/skills.py`、`api/**`、任何合同、`deploy/**`、任何测试；未 commit、未 push。
**测量方式**：所有"受影响用例"结论均来自**实跑测量**（§1），不使用估算；无法实跑的部分（e2e 需活服务）以"文件:用例名 + 判据"枚举并标注"未实跑"。

**行号基准（重要，供复核）**：本文件的 `文件:行号` 引用于 **2026-09-16 工作区快照**上复核。该快照**包含另一个在途工作包（c20 契约归并）的未提交改动**（`src/kert/api/server.py` +29 行、`specs/kert-openapi-v1.yaml`、`tests/integration/test_contract_shape_conformance.py` 等）：

- 涉及 `server.py` 的 `readyz` 行号已按当前工作区**重新取**（`362-429`、`371`、`392-398`）；
- `skill_execute` 的 `error→HTTP` 映射（`648`/`667`/`670`）亦已按当前工作区复核；
- 该在途改动只新增 `@app.exception_handler(Exception)`（仅影响 5xx 兜底路径，其自身 docstring 写明"2xx 与中间件行为不变"）⇒ **不改变**本文件对"业务错误返回 200"的判定，也不改变 §2 的实跑结论；
- 若后续 `server.py` 再被改动，请以"**函数名 + 行号**"复核，勿只信行号。

---

## 0. 结论摘要（6 条）

1. **受影响面可被精确界定，不需要估**：全仓 `tests/unit + tests/integration + tests/contract + tests/recovery`（实收集 **1447** 条）中，执行"将被接线技能"（走 `_route_plan`）的用例共 **44 条**（`_route_plan` 调用 49 次）。分类：**A=29 会行为改变 / B=9 走能力驱动路径 / C=3 不变 / E=3 需在回归中显式确认**。
2. **A 组 29 条不是"测试写错了"，而是今天 `fail-open` 语义的既有断言载体**：它们全部是"**计划放行 + 客户知识库不可用**"的组合，现状断言 `status=ok` 且逐条 `skipped`（证据：`test_outreach_ok_no_library` / `test_meeting_ok_no_library` / `test_kert_skipped_without_customer_knowledge` 等）。按 O-2 的 **(R) 解析失败 ⇒ fail-closed**，这 29 条会从 `ok/skipped` 变为 **`skill_error` + `KERT_PERMISSION_DENIED`**。⇒ **改它们等于改已声明的业务语义，须 Owner 裁决**，不是测试维护。
3. **唯一实质语义变更是"（R）可用性失败不再被吞成 skipped"**（现状 `customer_knowledge.py:35,41-49` + `skills.py:509-521` 双层 fail-open）。数据未命中（(D)）语义**不变**（§6）。
4. **门禁顺序是被实测钉住的硬约束**：能力解析**必须晚于**计划门禁。C 组 3 条用例分别断言 `ROUTE_POLICY_ABSENT`、`ONTOLOGY_REFERENCE_INVALID`、`ROUTE_UNRESOLVED`；若把能力门禁提前，拒绝码会漂移、这 3 条必红（§3.4）。
5. **e2e 存在已核实的"假绿"风险**：`/api/skill/execute` 对**一切业务错误返回 200**（`server.py:667-671` 仅 `UNKNOWN_SKILL` 为 404），而 `tests/e2e/test_all_skills_execution.py:66-74` 只断言 `status_code in (200,201,202)` + 字段存在 ⇒ **接线后若部署工作区未供给声明，该用例仍会绿而技能实际返回 `skill_error`**。必须在 M7.1-B 内一并加强 e2e 断言（属测试改动，需授权）。
6. **部署顺序被编排自动闭合**：`provision` 是 `api`/`worker` 的 `service_completed_successfully` 依赖（`deploy/docker-compose.yml:74-77,144-151`），而声明已随镜像进容器（`deploy/Dockerfile:58`）⇒ 只要用**重建后的镜像**，部署时声明必然先落到卷里，"代码已接线但声明未供给"的危险窗口在正常编排下不会出现（§4.3/§5）。

---

## 1. 测量方法（可复现，不改仓内代码）

### 1.1 做法

**内存仪器 + 全量实跑**：用一个位于 `/tmp` 的一次性脚本，在运行 pytest **之前**把三个方法包上**只读记录包装器**（调用后原样委托原实现，不改变任何行为）：

| 被包装 | 记录什么 |
|---|---|
| `SkillExecutionService._route_plan` | 当前用例 nodeid、`task`、`expectedMapId`、工作区是否含声明、现状结果（`ALLOWED` / `RAISED:<type>:<code>`） |
| `SkillExecutionService._load_ki` | 当前用例 nodeid、`self._ckp.available`、工作区是否有 `04_serve/customer_knowledge/CURRENT.md`、取数命中数 |
| `SkillExecutionService._run_supply_chain` | 未接线读取路径的触达用例（O-6 范围） |

复现命令（脚本与原始记录都**在仓外**，不随交付入库）：

```bash
.venv/bin/python /tmp/m71b_impact_probe.py          # 仪器 + 实跑 + 汇总
# 原始逐调用记录：/tmp/m71b_impact_records.json
```

### 1.2 实跑范围与口径

| 范围 | 是否实跑 | 说明 |
|---|---|---|
| `tests/unit`、`tests/integration`、`tests/contract`、`tests/recovery` | **实跑**（收集 1447 条） | 本文件所有"实跑得出"的清单来自这里 |
| `tests/security`、`tests/performance` | 已核实**零命中** | 二者不含三个已接线技能的调用（grep 无结果） |
| `tests/e2e` | **未实跑**（需外部活服务，`KERT_BASE_URL`） | 收集 47 条；相关项以 §2.3 枚举 |

"当前用例"的归属用 pytest 的 `pytest_runtest_setup` 钩子取 `item.nodeid`；异步/线程路径可能出现"同一用例多次调用"或"计划放行但未观察到取数"，后者单列为 E 组，不并入 A/B。

---

## 2. (a) 受影响既有用例清单

### 2.1 分类定义

| 组 | 判据（实跑得出） | 接线后预期 |
|---|---|---|
| **A（会变）** | 计划**放行** 且 客户知识库**不可用**（`_ckp.available=False`，工作区无 `04_serve/customer_knowledge/CURRENT.md`） | 由 `ok` + 逐条 `skipped` → **拒绝**（`skill_error` / `KERT_PERMISSION_DENIED`）**（须 Owner 裁决）** |
| **B（等价路径）** | 计划**放行** 且 客户知识库**可用** | 读取改由能力驱动；**结果应等价**（需等价性证据，见 §5.3） |
| **C（不变）** | 计划**已被拒**（无工作区 / 无策略 / 本体非法 / 未映射） | 不变（前提：能力门禁晚于计划门禁，§3.4） |
| **E（待确认）** | 计划**放行**但本次未观察到取数调用（多为异步/线程路径） | 视执行是否发生；须在 M7.1-B 回归中显式确认 |
| **D（另一轴）** | 有 KI 读取但**不经过路由**（`_run_supply_chain` 等） | M7.1-B 若不改这条路径 ⇒ 不变；但存在"同一数据两条读取路径"的一致性债（O-6） |

### 2.2 A 组：**会行为改变**的既有用例（29 条，实跑得出）

```text
tests/integration/test_control_plane_consistency.py::test_map_assets_equal_skill_reads[skill-customer-meeting-script]
tests/integration/test_control_plane_consistency.py::test_map_assets_equal_skill_reads[skill-customer-outreach-script]
tests/integration/test_control_plane_consistency.py::test_map_assets_equal_skill_reads[skill-customer-previsit-report]
tests/integration/test_control_plane_consistency.py::test_plan_drives_reads_not_source_literals
tests/integration/test_persistent_jobs.py::TestPersistentAsyncExecution::test_worker_picks_up_enqueued_job
tests/integration/test_prod_async_guard.py::TestProductionRequiresRuntimeStore::test_default_profile_is_dev
tests/integration/test_prod_async_guard.py::TestProductionRequiresRuntimeStore::test_sync_execute_unaffected_in_prod
tests/integration/test_redaction.py::TestBackwardCompatibility::test_skill_execution_result_keeps_plaintext
tests/integration/test_runtime_store_api.py::test_execute_persists_idempotency_record
tests/integration/test_runtime_store_api.py::test_idempotency_replay_after_restart
tests/integration/test_runtime_store_api.py::test_no_replay_across_restart_without_store
tests/integration/test_runtime_store_api.py::test_no_store_still_works_in_memory
tests/integration/test_runtime_store_api.py::test_repeated_execute_is_idempotent
tests/integration/test_runtime_store_api.py::test_service_level_replay_from_store
tests/integration/test_runtime_store_api.py::test_store_holds_no_knowledge_tables
tests/integration/test_runtime_store_api.py::test_store_stats_after_traffic
tests/integration/test_skill_routing_trace.py::test_each_skill_reports_its_own_task
tests/integration/test_skill_routing_trace.py::test_emitted_trace_entries_conform_to_canonical_schema
tests/integration/test_skill_routing_trace.py::test_map_mismatch_is_surfaced_not_hidden
tests/integration/test_skill_routing_trace.py::test_provisioned_workspace_records_resolved_plan
tests/integration/test_skill_routing_trace.py::test_trace_plan_hash_equals_routing_plan_api
tests/integration/test_skills.py::TestApi::test_execute
tests/integration/test_skills.py::TestApi::test_execute_idempotent
tests/integration/test_skills.py::TestExecute::test_fail_closed
tests/integration/test_skills.py::TestExecute::test_idempotent_replay
tests/integration/test_skills.py::TestExecute::test_meeting_ok_no_library
tests/integration/test_skills.py::TestExecute::test_old_request_fields_ignored
tests/integration/test_skills.py::TestExecute::test_outreach_ok_no_library
tests/integration/test_skills.py::TestKertCollaboration::test_kert_skipped_without_customer_knowledge
```

> **为什么它们"会变"**：这些用例的**受控工作区都含声明**（M7.3 供给：地图 + 策略 + 本体引用 + 声明），因此**计划门禁放行**；但工作区**没有** `customer_knowledge` 活动投影，故 `_ckp.available=False`（`customer_knowledge.py:41-49`）→ `_load_ki` 走 `skills.py:509-521` 的 fail-open 分支，逐条 `_trace_ki(ok=False)` → 用例断言 `ok` + `skipped`。
> 接线后该分支被 `KNOWLEDGE_SOURCE_UNAVAILABLE` 取代 ⇒ **拒绝**。
> 其中 3 条用例名本身即语义标签：`test_meeting_ok_no_library`、`test_outreach_ok_no_library`、`test_kert_skipped_without_customer_knowledge` —— "无库 ⇒ ok/skipped"是**今天被明文断言**的行为。

### 2.3 B 组：**走能力驱动路径**的既有用例（9 条，实跑得出）

```text
tests/integration/test_skills.py::TestAssemblyTraceKi::test_outreach_meeting_evidence_from_library
tests/integration/test_skills.py::TestAssemblyTraceKi::test_previsit_evidence_independent_of_request_fields
tests/integration/test_skills.py::TestAssemblyTraceKi::test_previsit_ki_all_ok_from_library
tests/integration/test_skills.py::TestAssemblyTraceKi::test_previsit_ki_all_skipped_unknown_customer
tests/integration/test_skills.py::TestAssemblyTraceKi::test_previsit_sections_per_ki
tests/integration/test_skills.py::TestNoNewEvidencePolicy::test_other_skills_ignore_policy
tests/integration/test_skills.py::TestNoNewEvidencePolicy::test_r1_newer_timestamp_ok
tests/integration/test_skills.py::TestNoNewEvidencePolicy::test_r1_stale_timestamp_blocked
tests/integration/test_skills.py::TestSecondCustomer::test_r1_ki_all_ok
```

这些用例的客户知识库**可用**（有 `04_serve/customer_knowledge/CURRENT.md`），读取结果非空。接线后底层读取改由能力驱动 ⇒ **必须逐条保持结果等价**（含 `kiId` 序列、`content` 原文、`ok/skipped` 判定、`sections` 切分）。注意 `test_previsit_ki_all_skipped_unknown_customer` 是 (D) 类"数据未命中"的载体，接线后**必须仍然 skipped**。

### 2.4 C 组：**不变**的既有用例（3 条，实跑得出）

```text
tests/integration/test_skill_routing_trace.py::test_no_workspace_refuses_and_records_unresolved   # 断言 ROUTE_UNRESOLVED
tests/integration/test_skill_routing_trace.py::test_unprovisioned_workspace_refuses_and_records_why # 断言 ROUTE_POLICY_ABSENT
tests/integration/test_skill_routing_trace.py::test_ontology_denial_code_is_passed_through       # 断言 ONTOLOGY_REFERENCE_INVALID
```

前提是 §3.4 的门禁顺序。这 3 条是"能力门禁不得提前"的**实测证据**。

### 2.5 E 组：**需在回归中显式确认**（3 条，实跑得出）

```text
tests/integration/test_persistent_jobs.py::TestPersistentAsyncExecution::test_thread_mode_without_store
tests/integration/test_prod_async_guard.py::TestProductionRequiresRuntimeStore::test_dev_without_store_still_allowed
tests/integration/test_prod_async_guard.py::TestProductionRequiresRuntimeStore::test_explicit_profile_overrides_env
```

三条均为"计划放行但本次未观察到 `_load_ki` 调用"（多为异步/线程路径或未执行完）。**不作为"不受影响"处理**：M7.1-B 回归必须显式复跑并确认状态，不得默认它们不变。

### 2.6 D 组：有 KI 读取但**不经过路由**（6 条；其中 3 条属 O-6 范围）

```text
# 未接线读取路径 _run_supply_chain（技能包 bank-front-supply-chain-graph）
tests/integration/test_skills.py::TestSupplyChainFromLibrary::test_graph_complete_from_library
tests/integration/test_skills.py::TestSupplyChainFromLibrary::test_graph_partial_unknown_customer
tests/integration/test_skills.py::TestSecondCustomer::test_graph_complete_from_library
# 计划放行但本次未走到取数（异步/环境类）
tests/integration/test_persistent_jobs.py::TestPersistentAsyncExecution::test_queue_stats_reflects_enqueued
tests/integration/test_prod_async_guard.py::TestProductionRequiresRuntimeStore::test_profile_is_case_insensitive
tests/integration/test_prod_async_guard.py::TestProductionRequiresRuntimeStore::test_profile_read_from_env
```

> **一致性债（须登记，不在 M7.1-B 范围）**：`_run_supply_chain`（`skills.py:818-823`）读取 `KI-FRONT-001/002/003` **既不经过计划、也不经过能力**，且 id 为源码字面量；其技能 `bank-front-supply-chain-graph` 来自仓内技能包（`skills.py:555-558`）⇒ 属 O-6"仓内技能包资源不纳入"的范围。其后果是：**同一份客户知识数据将存在"能力驱动"与"字面量驱动"两条读取路径**，接线后必须显式登记该缺口，避免被误读为"已全部接线"。

### 2.7 e2e 面（**未实跑**，按文件:用例名枚举；需活服务）

| 用例 | 判据 | 接线后风险 |
|---|---|---|
| `tests/e2e/test_all_skills_execution.py::TestAllSkillsExecution::test_skill_execute[skill-customer-previsit-report]` | `SKILL_IDS:13` | **假绿**：只断言 HTTP 200 + 字段存在；`skill_error` 也是 200（`server.py:667-671`） |
| 同上 `[...-meeting-script]` | `SKILL_IDS:14` | 同上 |
| 同上 `[...-outreach-script]` | `SKILL_IDS:15` | 同上 |
| `tests/e2e/kert_api_validation.py:220,287,304,311` | 4 处同技能调用 | **不被 pytest 收集**（文件名非 `test_*.py`），属人工验证脚本；同样只查 HTTP |
| `tests/e2e/test_scenario_2_previsit_report.py` / `test_scenario_4_knowledge_graph.py` | 需逐条复核（未实跑） | 需在 M7.1-B 回归中逐条确认 |

⇒ **M7.1-B 应把"e2e 断言必须能区分 `ok` 与 `skill_error`"列为交付项之一**（否则部署侧"绿"不证明可用）。

### 2.8 已核实**不受影响**的范围

| 范围 | 判据 |
|---|---|
| `tests/unit`（918 条） | 实跑：零 `_route_plan` 调用（单元层不驱动技能） |
| `tests/contract`（合同形状/内契约） | 实跑：零调用 |
| `tests/security`、`tests/performance` | grep：无三个已接线技能调用 |
| 其余技能（SP-15/SP-20/SP-21、`bank-front-*` 其余 6 个） | 不经过 `_route_plan`（`skills.py:624-628,555-558`）⇒ 除 M7.1-B 另行扩大范围，否则不受影响 |

---

## 3. (b) 行为差异矩阵

### 3.1 主矩阵

| # | 场景 | 现状（未接线） | M7.1-B 接线后（严格按 O-2） | 变化？ | 严重度 |
|---|---|---|---|---|---|
| 1 | 计划放行 + 声明存在 + 能力可用 + heading 命中 | 读 `04_serve/customer_knowledge/segments.parquet`（`customer_knowledge.ki_map`） | 同一份数据，经 `KS-CUSTOMER-KI-PARQUET` 能力读取 | **应无**（等价性须证，§5.3） | — |
| 2 | 计划放行 + **声明缺失** | 照常读取（`ok` + `skipped`） | `KNOWLEDGE_SOURCE_DECLARATION_ABSENT` ⇒ 拒绝 | **是** | 高（配置错误被暴露） |
| 3 | 计划放行 + **声明非法** | 照常读取 | `KNOWLEDGE_SOURCE_DECLARATION_INVALID` ⇒ 拒绝 | **是** | 高 |
| 4 | 计划放行 + **assetRefId 未绑定** | 该条 `skipped`，其余照常 | `KNOWLEDGE_SOURCE_UNBOUND` ⇒ 拒绝 | **是** | 中（与 §3.3 的 `required` 口径耦合） |
| 5 | 计划放行 + 能力**不可用**（投影缺失） | `_load_ki` 返回 `{}` ⇒ 全 `skipped`，技能仍 `ok` | `KNOWLEDGE_SOURCE_UNAVAILABLE` ⇒ 拒绝 | **是（核心变更）** | 高（fail-open → fail-closed） |
| 6 | 计划放行 + 能力**被停用** | 照常读取 | `KNOWLEDGE_SOURCE_DISABLED` ⇒ 拒绝 | 是 | 低（当前无人停用） |
| 7 | 计划放行 + **数据未命中**（库在、该客户无该 KI） | `skipped` | **仍 `skipped`** | **否** | — |
| 8 | 计划**被拒**（无策略/未映射/歧义/地图未注册/本体缺失或非法/无工作区） | 拒绝，码为 `ROUTE_*` / `KNOWLEDGE_MAP_*` / `ONTOLOGY_REFERENCE_*` | **同上，码不变** | **否（前提 §3.4）** | — |
| 9 | heading 与请求的 assetRefId 不一致 | 静默按 heading 解析出的 KI 归类 | `KNOWLEDGE_SOURCE_ASSET_REF_UNMATCHED` ⇒ 拒绝 | 是 | 中（防"读错条目"） |

### 3.2 唯一实质语义变更

**现状是 fail-open，接线后是 fail-closed**，证据链：

```text
customer_knowledge.py:35    """…服务不可用时返回空（fail-open）。"""
customer_knowledge.py:41-49 try: KnowledgeService(…) / _active_version() → except: available=False
skills.py:509-521           if not self._ckp.available → trace skipped + return {}
                            except Exception → trace skipped + return {}
```

⇒ 今天"知识源不可用"与"客户没有这条知识"**在可观测面上不可区分**（都只是 `skipped`）。M7.1-B 的价值正是把前者变成可失败、可归因的拒绝；代价是 **A 组 29 条用例的断言要改**，且这属**业务语义变更**（不是测试维护）。

### 3.3 与 `required` 子决策的耦合（不得顺手实施）

场景 4（未绑定 ⇒ 拒绝）会**顺带改变** `required: false` 资产的现状语义。今天 `required` **不参与运行时判定**（`skills.py:645-646` 明文，且地图 notes 同载）。若 M7.1-B 把"未绑定"一律判为拒绝，则 `required: false` 的实际效果等价于 `true`。

⇒ 必须在 M7.1-B 中明确二选一并登记：**(i) 未绑定 ⇒ 无条件拒绝**（等价于提升 `required`，需 Owner 一并批准）；**(ii) 未绑定 ⇒ 仅在 `required: true` 时拒绝，`required: false` 记 `skipped` + 具名原因**（保持既有口径，不升格）。**建议 (ii)**：把 `required` 升级留作独立决策，避免一次接线改两件语义。

### 3.4 门禁顺序约束（实测钉住）

能力解析**必须晚于**计划门禁（路由 → 本体引用 → 能力），与设计候选 §3.4 一致。理由：

1. **归因正确**（沿用 `activation_plan.py:174-180` 的既有理由）：配置问题不应被误报成另一种配置问题；
2. **实测**：C 组 3 条用例分别断言 `ROUTE_UNRESOLVED` / `ROUTE_POLICY_ABSENT` / `ONTOLOGY_REFERENCE_INVALID`；把能力门禁提前会使拒绝码漂移、这 3 条必红；
3. **A 组 2 条"无声明"用例**（`test_no_workspace_*`、`test_unprovisioned_*`）今天已在计划门禁被拒 ⇒ 能力门禁后置时它们**行为不变**，是"最小爆炸半径"的正确形态。

---

## 4. (c) 回滚方案

### 4.1 回滚动作

**单 commit revert**（M7.1-B 应做成**独立 commit**，且只改 `application/skills.py` 及其直接测试）：`git revert <M7.1-B-commit>`。

### 4.2 回滚后的行为

| 项 | 回滚后 |
|---|---|
| 三个技能 `skill-customer-*` 的读取 | 回到 `CustomerKnowledgeProvider` 直接读投影（`_load_ki` 原路径） |
| 拒绝语义 | 回到 fail-open（库不可用 ⇒ `skipped`，技能仍 `ok`） |
| A 组 29 条用例 | 回到本文件记录前的断言（须与代码同 revert，保持"代码与断言同源"） |
| 声明（`knowledge_sources.json`） | 仍在工作区里，但**无运行时消费方** ⇒ **完全惰性、无副作用**（实测：44 条用例中无任何代码路径消费它，仅 `provision.validate_source` 校验其合法性）；**不需要**从卷里删除 |

### 4.3 中间态说明（三种，逐一给结论）

| 中间态 | 结果 | 依据 |
|---|---|---|
| **声明已供给 + 代码已回滚** | **安全**：声明无人消费；`provision` 复跑显示"未变 6"（幂等） | `provision.py` 只写不删；声明唯一消费者是 `validate_source` |
| **代码已接线 + 声明未供给** | **危险**：三个技能全部拒绝（`DECLARATION_ABSENT`） | 场景 2 |
| **镜像比卷新/旧不一致** | **正常编排下不出现**：`provision` 是 `api`/`worker` 的前置依赖（`docker-compose.yml:74-77,144-151`），且声明随镜像进容器（`Dockerfile:58`）⇒ 每次 `up -d` 都会先供给 | 见 §5.1 |

> ⇒ **部署顺序被强制且已被编排满足**：**先让声明可供给（已完成：第二片-A，`14d3b69`）→ 再接线（M7.1-B）**。回滚则相反方向天然安全（代码回滚不要求撤声明）。

### 4.4 回滚不需要动的东西

- **不需要合同回滚**（M7.1-B 不应改合同；若需新增 trace 字段，见 §5.4 的枚举约束）。
- **不需要数据迁移/回滚**（不新增表、不写运行态；`ADR-012` 边界不变）。
- **不需要重新供给**（声明与接线解耦）。

---

## 5. (d) 部署侧前置核验清单

### 5.1 可核验判据（现状即可执行）

| # | 判据 | 命令/接口 | 期望 |
|---|---|---|---|
| D1 | 供给容器成功 | `docker inspect kert-provision --format '{{.State.ExitCode}}'` | `0` |
| D2 | 供给计数含第 4 类 | 供给日志 | 首次 `新建 6 / 覆盖 0 / 未变 0`；复跑 `新建 0 / 覆盖 0 / 未变 6` |
| D3 | 卷内确实有声明 | `docker run --rm -v <stack>_workspace:/data/workspace --entrypoint sh kert-python-core:local -c 'ls /data/workspace/90_control/schema/'` | 必含 `knowledge_sources.json` |
| D4 | 地图已供给（既有判据） | `GET /v1/knowledge-maps` | `count > 0`（=0 说明供给未生效，路由将默认拒绝） |
| D5 | 镜像内交付物一致（TL 新规） | `sha256sum` 工作区声明 vs `docker run --rm --entrypoint sh <image> -c 'sha256sum /app/examples/bank-front-knowledge-maps/90_control/schema/knowledge_sources.json'` | 两者**相等**且 = `abf65061c50c8a8fb350a4508efb224648f9aecd18a87be8693c1c54eba49d26` |
| D6 | 先提交再 build | `git log -1 --format=%H` 与镜像构建时间 | 提交**先于**构建；镜像 sha256 与镜像内文件 sha256 同时入证据 |

### 5.2 **不能**作为判据的东西（防误判）

| 不可用的判据 | 原因（行号） |
|---|---|
| `/readyz` 绿灯 | 它只查"工作区可写 + `knowledge_projection`（**非阻断**）+ runtime_store"；**不查** `90_control/schema/**`（`server.py:362-429`；其中 `:371` 表格明写"知识投影可读 → 仅 degraded，**不阻断**"，`:392-398` 即该分支实现） |
| e2e 全绿 | `skill_error` 也是 HTTP 200（`server.py:667-671`）⇒ 绿不证明可用（§2.7） |
| `kert inspect` 输出 | 只列一级目录与 `CURRENT.md` 指针，**不列** `90_control/schema/` 下的文件（`workspace.py:99-138`） |
| 镜像"已存在" | e2e 侧实测：镜像可能"存在但内容陈旧"（层缓存按内容算）；必须重建并用 D5 校验 |

### 5.3 M7.1-B 必须自带的等价性证据

对 B 组 9 条 + 真实工作区（含 `customer_knowledge` 投影的用例）：
1. 接线前后**逐条**比对：`kiId` 序列、`content` 原文、`sections` 切分、`ok/skipped` 判定、`data` 主体结构；
2. 至少 1 条"同一输入前后 `assembly_trace` 除新增留痕外**逐字段相同**"的机械断言；
3. 反空转：若适配器在投影缺失时返回 `[]` 而非拒绝/具名原因，等价性用例**必须变红**（对应第一片 M3/M9' 的同构变异）。

### 5.4 若要在 trace 中新增留痕字段（`capabilityId` / `bindingSha256`）

- **允许加字段**：canonical schema 为 `additionalProperties: true`（`docs/contracts/schemas/assembly-trace.schema.json:107`）⇒ 不破 `test_emitted_trace_entries_conform_to_canonical_schema`；
- **必须复用既有枚举**：新条目/新字段所在条目的 `phase` 只能取 `resolve|idempotency|validate|kert|evidence|model|parse|compose|tool`（`:18-31`），`status` 只能取 `ok|failed|blocked|skipped|degraded`（`:35-44`）；
- **不得**据此改 `docs/contracts/**`（本任务边界；且该 schema 是 v1.5 追认后的 canonical 文件）。

---

## 6. (e) 与 v1.3 "evidence ok/skipped 不阻塞执行" 的关系

| 部分 | 接线后 | 依据 |
|---|---|---|
| **不变**：`ok/skipped` 的**判定语义**（库里取到/取不到） | 逐条 KI 仍按"是否命中"记 `ok`/`skipped` | `skills.py:699-711` 不动 |
| **不变**：`skipped` **不阻塞**技能完成 | 只要能力可用，未命中的 KI 仍只是 `skipped`，技能照常 `ok` | 同上 |
| **不变**：`_ki_context` 只拼计划 `assets` 命中的 KI | 拼接与 `only=` 过滤逻辑不变 | `skills.py:523-532` |
| **变化**：`ok/skipped` 的**判定输入** | 由 `_ckp.available` 改为 capability 的可用性判定（探针） | `skills.py:509-521` 被替换为新判定 |
| **变化**：不再存在"知识源不可用 ⇒ 全 skipped 且 `ok` 输出"的通道 | 该情形变为拒绝（场景 5） | O-2 的 (R)/(D) 分野 |
| **未变**：`required` 不参与判定 | 除非按 §3.3 一并批准，否则保持 | `skills.py:645-646` |

一句话：**v1.3 的 (D) 类语义（数据未命中不阻塞）完整保留；(R) 类（源不可用）从"被吞成 skipped"改为"显式拒绝"**。这正是 M7.1-B 需要 Owner 裁决的原因——它把一个**已上线可观测行为**（`ok` + `skipped`）改为拒绝。

---

## 7. 风险登记与待裁决

| ID | 风险/待决 | 建议 | 需谁 |
|---|---|---|---|
| R-1 | A 组 29 条断言需改：属业务语义变更，不得由开发自行改测试对齐实现 | 与"失败分野"同批登记；改动须附"变更前后行为"逐条对照 | **Owner** |
| R-2 | 场景 4 与 `required` 口径耦合 | 采用 §3.3 的 (ii)，把 `required` 升级留作独立决策 | **Owner** |
| R-3 | e2e 假绿（`skill_error` 也是 200） | M7.1-B 交付项内加入"e2e 断言须区分 `ok`/`skill_error`"（需测试改动授权） | TL |
| R-4 | `_run_supply_chain` 未接线（O-6） | 登记为已知缺口，**不得**在报告中表述为"全部读取已接线" | TL |
| R-5 | "代码已接线 + 声明未供给"会导致三技能全拒绝 | 由 compose 前置依赖闭合；回滚方向天然安全（§4.3）；部署须用 D1-D3 核验 | TL/运维 |
| R-6 | 分期：一次接线会同时造成 A 组 29 条变化 | 可拆 **B-1（等价替换：仅成功路径切能力驱动，源不可用仍 `skipped` + 具名原因）**→ **B-2（严格 fail-closed）**；B-1 预期 **0 条**既有用例变化，B-2 才是 R-1 | **Owner** |

---

## 8. (f) 本任务边界（遵守情况）

| 边界 | 落实 |
|---|---|
| 只写本文件 | 仅新增 `evidence/m7-3/IMPACT-ANALYSIS-M7-1-B.md` |
| 不改 `application/skills.py`、`api/**`、合同、`deploy/**` | **未改**（实测仪器只在内存中包装，脚本与原始记录都在 `/tmp`，未入库） |
| 不改任何测试 | **未改** |
| 不 commit、不 push | **未做** |

---

## 9. 非声明

- 本文件**不是**实施授权、**不是** Owner 裁决、**不是** ADR、**不是**合同修订；不代表 `PRODUCTION_RELEASE_GATE` 变化。
- 本文件**不**声称 M7.1-B 已完成、**不**声称任何能力生产就绪；`PRODUCTION_RELEASE_GATE=BLOCKED` 不变。
- 所有"受影响用例"结论均来自 §1 的实跑测量；e2e 面**未实跑**并已显式标注，不得被读作"e2e 已核"。
- 本文的 `/tmp` 脚本与原始记录是**过程材料**，不属受控交付物；结论已完整写入本文（自包含）。
- 未修改 GITS 仓；未 push。
