# M7.1-B1 最终确认跑 · 证据（2026-09-16）

**授权**：Tech Lead 确认跑信号（含 R-A / R-E / R-G + E-5 + (a)–(h) 与三分类 node id diff 细化判据）
**性质**：本文件是**已完成的确认跑**的证据落盘（**不是重跑**）；原始产物见同目录三份文件。
**结论**：**PASS —— 未触发任何停下条件**（主口径对称差 ∅；双向差集 100% 可归因；红集未变多变少）。

---

## 0. 范围与边界（明写，不做隐含排除）

- **不含 `tests/e2e`**（TL 裁定①）：e2e 需活服务；`tests/e2e/kert_api_validation.py` 非 `test_*.py` 不被 pytest 收集 ⇒ 纳入只会引入环境噪声。e2e 归 **B-2 交付项**。
- B-1 的等价性主张针对 **unit + integration + contract + recovery** 四目录（本轮实跑 4 目录）。
- **第三方在途件未纳入本片改动面**：`src/kert/application/provision.py`、`src/kert/cli/main.py`、`tests/unit/test_provision.py`、`src/kert/domain/activation_contract.py`、`tests/unit/test_activation_contract.py`、`examples/**/activations/**`、`.understandignore`。

> **记录自洽（取代关系）**：本次为**干净窗口**跑（HEAD 前后逐字一致、`status` 前后逐字相同）⇒
> **取代**此前一次"窗口内含 TL docs-only 提交"的跑；后者**作废**，其"docs-only 例外"**不再需要**。
> 本轮记录以**本文件**为准（TL 已核实工具 sha 与全部关键数字，见决策清单 B-1 确认跑行）。

## 1. HEAD / status / golden（开工前·收工后各一次）

```text
开工前 HEAD = 2643382cedafd0fc038b9fe1ca53b2be8348e08b
收工后 HEAD = 2643382cedafd0fc038b9fe1ca53b2be8348e08b     ← 跑数窗口内 HEAD 未变
golden 再核 = skills.py sha256 1677173cd1170fd6552a589d4e22f1d8ca97cfed47d91c9b9a041daa7fe9efc4  ⇒ MATCH
git status --porcelain（前后逐字相同，完整 7 行）:
 M .understandignore
 M src/kert/application/provision.py
 M src/kert/cli/main.py
 M tests/unit/test_provision.py
?? examples/bank-front-knowledge-maps/90_control/schema/activations/
?? src/kert/domain/activation_contract.py
?? tests/unit/test_activation_contract.py
```

## 2. 命令 / 工具 sha / 环境

```text
cd /home/szf/dev/Leibniz-KERT && .venv/bin/python /tmp/m71b_confirm_probe.py
cd /home/szf/dev/Leibniz-KERT && .venv/bin/python /tmp/m71b_baseline_audit.py
探针 sha : 83678c401fbac1e363a6a8ee3380b13ba3487b9054b1269f97bf09c55b342dfe（R-G 合规版：同脚本双计数 + 红集同跑）
审计 sha : f67e0cd4daa11df935e7c3b0f1571991316c6321a933b7a7c0a2631a1842aa6b（基线内联 + 溯源 + 三分类 diff）
基线量具 : /tmp/m71b_impact_probe.py sha256 d73ce3c61f0f61e7a7f3a0379ca694040b2d8e733fd98aa8324e0ee9b776639b（未改动）
环境     : python 3.12.8 / pytest 9.1.1 ；探针内真实 pytest_exit = 1
```

**工具已落盘（本目录，TL 补落；与 `/tmp` 原件**逐字相同**）**

```text
evidence/m7-3/confirm-run-m7-1-b1-probe.py            sha256 83678c40…（== /tmp/m71b_confirm_probe.py）
evidence/m7-3/confirm-run-m7-1-b1-baseline-audit.py   sha256 f67e0cd4…（== /tmp/m71b_baseline_audit.py）
```

> **定位（TL 裁定，据实照录）**：脚本内含 `/tmp` 绝对路径 ⇒ **作为"证据记录"入库，不是可移植工具**；
> **口径权威 = 本文件 §2 / §7**（含基线原文与各组 sha256），**不是脚本本身**。
> 若日后要把它提升为仓内可复用工具（`scripts/`），属**另立议题**。
> （补落 `baseline-audit` 的价值：它正是本轮出过一次**假差异**的解析器（C 组行内注释并入 node id）⇒
> 落盘后该类解析问题**可被后人审计**，而不随 `/tmp` 消失。）

## 3. 四目录原始计数与真实退出码

命令形态（**E-8 合规，且取其更强形态：根本不经管道**）：
`.venv/bin/python -m pytest tests/<dir> -q -p no:warnings -p no:cacheprovider -o addopts="" --tb=no > /tmp/f 2>&1; echo $?`
—— `$?` 即 pytest 自身退出码（无 `tail`/`grep` 参与）；随后 `grep -E "passed|failed"` 打印**原始结果行**、
`grep -c "^FAILED"` 打印**红测行数**（绿色目录须为 **0**，即 E-8 的"显式 0 failed"检查）。
（E-8 原文要求"管道后必须取 `${PIPESTATUS[0]}`"；本片**不用管道** ⇒ 满足并强于该要求。）

```text
tests/unit        → 3 failed, 976 passed    EXIT=1
tests/integration → 469 passed, 1 xfailed   EXIT=0
tests/contract    → 53 passed               EXIT=0
tests/recovery    → 18 passed               EXIT=0
```

## 4. 主口径（R-G 第 1 条）：`_route_plan` 显式 node id 集合三分类

```text
基线 44 / 当前 63 / SAME 44 / ONLY_IN_BASELINE 0 / ONLY_IN_CURRENT 19
ONLY_IN_BASELINE = 0 条 ⇒ **硬停止条件未触发**
ONLY_IN_CURRENT 19 条来源：**全部为本片两个测试文件**（无其它来源 ⇒ 无 ANOMALY）
  tests/integration/test_skills_capability_swap.py × 11
  tests/unit/test_skills_capability_swap_guards.py × 8
A 组 29 条逐条在场 = True（缺失 0 条）
逐条原始 node id：见 `confirm-run-m7-1-b1-audit.log`（SAME / ONLY_IN_* 三类逐行打印）
```

## 5. 双计数（R-G 第 2 条，同一脚本同一次跑）与归因

```text
_load_ki = 53   _load_ki_from_declaration = 60   supply_chain_unwired = 3
闭合：53 = A29 + D_supply3 + D_other3 + 本片18       60 = A29 + B9 + D_other3 + 本片19
逐组：A(29) 两计数都在  ← 新方法被调 + 回落仍走 _load_ki（符合硬规则 E0）
      B(9)  从 _load_ki 完全移出（0/9）并全部进入新计数（9/9）← **R-G 预期的结构性迁移**
      C(3)/E(3) 两者都不在（路由门禁被拒 / 未路由，与基准一致）
      D_supply(3) 仅 _load_ki（未接线）   D_other(3) 两者都在
双向差集：仅 load_ki 4 条 = D_supply 3 + 本片 1（直调本体用例）
          仅 new   11 条 = B 组 9 条 + 本片 2
⇒ 差异 100% 可归因，无"归因不了"项（否则为停下条件）
```

## 6. 红集（变多/变少都报）

```text
当前 3 条 == 基准 3 条（node id 逐条一致）；变多 = []  变少 = []  ⇒ 未变少到 0
  tests/unit/test_provision_cli.py::test_apply_then_idempotent_rerun
  tests/unit/test_provision_cli.py::test_json_output_follows_standard_envelope
  tests/unit/test_provision_cli.py::test_init_flag_initializes_fresh_volume_then_provisions
归因：红测文件 test_provision_cli.py **未被改**，但其断言的**供给条目数**由第三方在途件
      src/kert/application/provision.py + src/kert/cli/main.py（+ tests/unit/test_provision.py）决定
      ⇒ 归因 = 第三方在途件（本窗口内未变，故红集保持 3 条而非 0 条）
```

## 7. 基线清单（**原文** + 自身 sha256 + 溯源）

溯源：`evidence/m7-3/IMPACT-ANALYSIS-M7-1-B.md` **§2.2 / §2.3 / §2.4 / §2.5 / §2.6**（实跑得出）。
sha256 口径：**排序去重后逐行 join** 的 sha256 ⇒ 与 B-2 复跑时可直接机械核对"基线是否被抄错"。

```text
A(29)            sha256 463e2236378d88b8d3c4fad34d2ec3ed1f7f0bf93a9cfebffe77c6369e0626f8
B(9)             sha256 d5e39592ff0c344ae487a23afd17eef72b201e18c64fa8ccb6a071757d035928
C(3)             sha256 bf03a4f647d29d3b1e925d5c096f73adb7eb0319a7759a4de643e10bdb3d265f
E(3)             sha256 f6a05c5fc8b5dc443b55fb07cbf6b32904f3a1028ef8b684ee097dc44894bc4c
D_supply(3)      sha256 f831b8812660ac2011d8cd7da4829a64c2d423b3b77d09b4b069863bbd9ac002
D_other(3)       sha256 aa4bfe26467e131e85aeab86cedba89d0fccefed66c11ec12977d983bb92fe77
A∪B∪C∪E(44)      sha256 1d473a64c6b7641323d18fec2c865323937e02b98be2b69b5cd1ce1f6f19b100
红集基准(3)      sha256 2c15c15d08f30f53946986a417a024de3a6a659e6b8568cf588e9aa0a8da21a2
```

### 7.1 A 组（29 条，会行为改变；`IMPACT-ANALYSIS-M7-1-B.md` §2.2）

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

### 7.2 B 组（9 条）· 7.3 C 组（3 条）· 7.4 E 组（3 条）· 7.5 D 组（6 条）

```text
# B 组（§2.3）
tests/integration/test_skills.py::TestAssemblyTraceKi::test_outreach_meeting_evidence_from_library
tests/integration/test_skills.py::TestAssemblyTraceKi::test_previsit_evidence_independent_of_request_fields
tests/integration/test_skills.py::TestAssemblyTraceKi::test_previsit_ki_all_ok_from_library
tests/integration/test_skills.py::TestAssemblyTraceKi::test_previsit_ki_all_skipped_unknown_customer
tests/integration/test_skills.py::TestAssemblyTraceKi::test_previsit_sections_per_ki
tests/integration/test_skills.py::TestNoNewEvidencePolicy::test_other_skills_ignore_policy
tests/integration/test_skills.py::TestNoNewEvidencePolicy::test_r1_newer_timestamp_ok
tests/integration/test_skills.py::TestNoNewEvidencePolicy::test_r1_stale_timestamp_blocked
tests/integration/test_skills.py::TestSecondCustomer::test_r1_ki_all_ok

# C 组（§2.4；行内注释已剥离）
tests/integration/test_skill_routing_trace.py::test_no_workspace_refuses_and_records_unresolved
tests/integration/test_skill_routing_trace.py::test_unprovisioned_workspace_refuses_and_records_why
tests/integration/test_skill_routing_trace.py::test_ontology_denial_code_is_passed_through

# E 组（§2.5）
tests/integration/test_persistent_jobs.py::TestPersistentAsyncExecution::test_thread_mode_without_store
tests/integration/test_prod_async_guard.py::TestProductionRequiresRuntimeStore::test_dev_without_store_still_allowed
tests/integration/test_prod_async_guard.py::TestProductionRequiresRuntimeStore::test_explicit_profile_overrides_env

# D 组（§2.6）：supply 3（未接线路径）+ other 3（计划放行但未走到取数）
tests/integration/test_skills.py::TestSupplyChainFromLibrary::test_graph_complete_from_library
tests/integration/test_skills.py::TestSupplyChainFromLibrary::test_graph_partial_unknown_customer
tests/integration/test_skills.py::TestSecondCustomer::test_graph_complete_from_library
tests/integration/test_persistent_jobs.py::TestPersistentAsyncExecution::test_queue_stats_reflects_enqueued
tests/integration/test_prod_async_guard.py::TestProductionRequiresRuntimeStore::test_profile_is_case_insensitive
tests/integration/test_prod_async_guard.py::TestProductionRequiresRuntimeStore::test_profile_read_from_env
```

> **注**：第 7 节清单与 `IMPACT-ANALYSIS-M7-1-B.md` 现场解析结果的 **sha256 逐组相同**（交叉核对由审计脚本完成，见 `confirm-run-m7-1-b1-audit.log` 首段）。

## 8. 原始产物（同目录）

```text
confirm-run-m7-1-b1-probe.log   sha256 c17a5275a0d357a29e843f274c8572a8393885d5b558d8b39e6b6cc70c367064（233 行）
confirm-run-m7-1-b1-audit.log   sha256 d01be9aa065731ba343c6de3881629076d125f13654734e8b7886a99feb24b88（137 行）
confirm-run-m7-1-b1-sets.json   sha256 fefb082ad00e3679153bc52b8920b4df0314da944e72d1d87736c696dba0f7ae（机器可读集合）
```

## 9. 已知边界与残留风险

1. `tests/e2e` 未跑（TL 裁定①）⇒ B-2 交付项；
2. 三条红测归因第三方在途件（本窗口内未变；**若第三方落定后红集变 0，须按"先报再解读"处理**）；
3. 探针工具**已落盘**于本目录（`confirm-run-m7-1-b1-probe.py` / `confirm-run-m7-1-b1-baseline-audit.py`，与 `/tmp` 原件逐字相同，见 §2）⇒ 不再依赖 `/tmp` 存活；
   但其定位为**证据记录**（含 `/tmp` 绝对路径，非可移植工具）⇒ **口径权威仍是本文件 §2/§7**；提升为 `scripts/` 可复用工具属另立议题；
4. R-G 口径缺口：该系列探针**只包装 `_load_ki` + `_load_ki_from_declaration`**；若 B-2 新增读取点，须同步扩展计数，否则计数会被误读（见方案文档 §6 第 7 项）。
