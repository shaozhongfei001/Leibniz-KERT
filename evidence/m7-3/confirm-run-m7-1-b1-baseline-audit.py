#!/usr/bin/env python3
"""M7.1-B1 确认跑｜**基线审计 + 三分类 node id diff**（临时脚本，/tmp，不入库）。

满足 TL 本轮细化要求：
1. **基线内联 + 溯源**：A/B/C/D/E 清单内联于本文件（来源见各清单头注释），并打印
   **基线列表自身的 sha256**（排序后）⇒ "内联基线 == 文档记录基线"可机械核对；
2. 额外做**机械交叉核对**：把内联清单与 `IMPACT-ANALYSIS-M7-1-B.md` 现场解析结果比对
   ⇒ **杜绝"基线抄错"成为新的静默失败点**（比要求更强，方向一致）；
3. **三分类 diff**：`SAME` / `ONLY_IN_BASELINE` / `ONLY_IN_CURRENT`，**打印原始 node id**；
4. **A 组 29 条逐条在场**检查；`ONLY_IN_CURRENT` 逐条标注**来源文件**，
   非本片两个测试文件者标 `⚠ ANOMALY`；
5. 打印**红集**（变多/变少/不变）+ **已知边界：本轮不含 e2e**。

用法：先跑探针产出 `/tmp/m71b_confirm_sets.json`，再执行本脚本。
    cd /home/szf/dev/Leibniz-KERT && .venv/bin/python /tmp/m71b_confirm_probe.py
    cd /home/szf/dev/Leibniz-KERT && .venv/bin/python /tmp/m71b_baseline_audit.py
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

REPO = Path("/home/szf/dev/Leibniz-KERT")
DOC = REPO / "evidence" / "m7-3" / "IMPACT-ANALYSIS-M7-1-B.md"
SETS = Path("/tmp/m71b_confirm_sets.json")
MY_FILES = ("tests/unit/test_skills_capability_swap_guards.py",
            "tests/integration/test_skills_capability_swap.py")

# ---------------------------------------------------------------- 内联基线（内联 + 溯源）
# 来源：evidence/m7-3/IMPACT-ANALYSIS-M7-1-B.md §2.2（A 组，29 条，实跑得出）
BASE_A = [
    "tests/integration/test_control_plane_consistency.py::test_map_assets_equal_skill_reads[skill-customer-meeting-script]",
    "tests/integration/test_control_plane_consistency.py::test_map_assets_equal_skill_reads[skill-customer-outreach-script]",
    "tests/integration/test_control_plane_consistency.py::test_map_assets_equal_skill_reads[skill-customer-previsit-report]",
    "tests/integration/test_control_plane_consistency.py::test_plan_drives_reads_not_source_literals",
    "tests/integration/test_persistent_jobs.py::TestPersistentAsyncExecution::test_worker_picks_up_enqueued_job",
    "tests/integration/test_prod_async_guard.py::TestProductionRequiresRuntimeStore::test_default_profile_is_dev",
    "tests/integration/test_prod_async_guard.py::TestProductionRequiresRuntimeStore::test_sync_execute_unaffected_in_prod",
    "tests/integration/test_redaction.py::TestBackwardCompatibility::test_skill_execution_result_keeps_plaintext",
    "tests/integration/test_runtime_store_api.py::test_execute_persists_idempotency_record",
    "tests/integration/test_runtime_store_api.py::test_idempotency_replay_after_restart",
    "tests/integration/test_runtime_store_api.py::test_no_replay_across_restart_without_store",
    "tests/integration/test_runtime_store_api.py::test_no_store_still_works_in_memory",
    "tests/integration/test_runtime_store_api.py::test_repeated_execute_is_idempotent",
    "tests/integration/test_runtime_store_api.py::test_service_level_replay_from_store",
    "tests/integration/test_runtime_store_api.py::test_store_holds_no_knowledge_tables",
    "tests/integration/test_runtime_store_api.py::test_store_stats_after_traffic",
    "tests/integration/test_skill_routing_trace.py::test_each_skill_reports_its_own_task",
    "tests/integration/test_skill_routing_trace.py::test_emitted_trace_entries_conform_to_canonical_schema",
    "tests/integration/test_skill_routing_trace.py::test_map_mismatch_is_surfaced_not_hidden",
    "tests/integration/test_skill_routing_trace.py::test_provisioned_workspace_records_resolved_plan",
    "tests/integration/test_skill_routing_trace.py::test_trace_plan_hash_equals_routing_plan_api",
    "tests/integration/test_skills.py::TestApi::test_execute",
    "tests/integration/test_skills.py::TestApi::test_execute_idempotent",
    "tests/integration/test_skills.py::TestExecute::test_fail_closed",
    "tests/integration/test_skills.py::TestExecute::test_idempotent_replay",
    "tests/integration/test_skills.py::TestExecute::test_meeting_ok_no_library",
    "tests/integration/test_skills.py::TestExecute::test_old_request_fields_ignored",
    "tests/integration/test_skills.py::TestExecute::test_outreach_ok_no_library",
    "tests/integration/test_skills.py::TestKertCollaboration::test_kert_skipped_without_customer_knowledge",
]

# 来源：同上 §2.3（B 组，9 条）
BASE_B = [
    "tests/integration/test_skills.py::TestAssemblyTraceKi::test_outreach_meeting_evidence_from_library",
    "tests/integration/test_skills.py::TestAssemblyTraceKi::test_previsit_evidence_independent_of_request_fields",
    "tests/integration/test_skills.py::TestAssemblyTraceKi::test_previsit_ki_all_ok_from_library",
    "tests/integration/test_skills.py::TestAssemblyTraceKi::test_previsit_ki_all_skipped_unknown_customer",
    "tests/integration/test_skills.py::TestAssemblyTraceKi::test_previsit_sections_per_ki",
    "tests/integration/test_skills.py::TestNoNewEvidencePolicy::test_other_skills_ignore_policy",
    "tests/integration/test_skills.py::TestNoNewEvidencePolicy::test_r1_newer_timestamp_ok",
    "tests/integration/test_skills.py::TestNoNewEvidencePolicy::test_r1_stale_timestamp_blocked",
    "tests/integration/test_skills.py::TestSecondCustomer::test_r1_ki_all_ok",
]

# 来源：同上 §2.4（C 组，3 条；行内注释已剥离）
BASE_C = [
    "tests/integration/test_skill_routing_trace.py::test_no_workspace_refuses_and_records_unresolved",
    "tests/integration/test_skill_routing_trace.py::test_unprovisioned_workspace_refuses_and_records_why",
    "tests/integration/test_skill_routing_trace.py::test_ontology_denial_code_is_passed_through",
]

# 来源：同上 §2.5（E 组，3 条）
BASE_E = [
    "tests/integration/test_persistent_jobs.py::TestPersistentAsyncExecution::test_thread_mode_without_store",
    "tests/integration/test_prod_async_guard.py::TestProductionRequiresRuntimeStore::test_dev_without_store_still_allowed",
    "tests/integration/test_prod_async_guard.py::TestProductionRequiresRuntimeStore::test_explicit_profile_overrides_env",
]

# 来源：同上 §2.6（D 组，6 条 = supply 3 + async/环境 3）
BASE_D_SUPPLY = [
    "tests/integration/test_skills.py::TestSupplyChainFromLibrary::test_graph_complete_from_library",
    "tests/integration/test_skills.py::TestSupplyChainFromLibrary::test_graph_partial_unknown_customer",
    "tests/integration/test_skills.py::TestSecondCustomer::test_graph_complete_from_library",
]
BASE_D_OTHER = [
    "tests/integration/test_persistent_jobs.py::TestPersistentAsyncExecution::test_queue_stats_reflects_enqueued",
    "tests/integration/test_prod_async_guard.py::TestProductionRequiresRuntimeStore::test_profile_is_case_insensitive",
    "tests/integration/test_prod_async_guard.py::TestProductionRequiresRuntimeStore::test_profile_read_from_env",
]

#: 红集基准（第三方在途所致，非本片；该文件未被改）
BASE_RED = [
    "tests/unit/test_provision_cli.py::test_apply_then_idempotent_rerun",
    "tests/unit/test_provision_cli.py::test_json_output_follows_standard_envelope",
    "tests/unit/test_provision_cli.py::test_init_flag_initializes_fresh_volume_then_provisions",
]


def sha_of(ids) -> str:
    """基线列表自身的 sha256（排序后逐行 join）⇒ 单调、可机械核对。"""
    blob = "\n".join(sorted(set(ids)))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def doc_block(title: str, nxt: str) -> list[str]:
    """从文档现场解析同一清单（用于与内联清单交叉核对）。"""
    text = DOC.read_text(encoding="utf-8")
    m = re.search(re.escape(title) + r"(.*?)" + re.escape(nxt), text, re.S)
    c = re.search(r"```text\n(.*?)```", m.group(1), re.S)
    out = []
    for line in c.group(1).splitlines():
        line = line.split("#")[0].strip()      # 剥离任意位置行内注释
        if line:
            out.append(line)
    return out


def source_of(nodeid: str) -> str:
    for f in MY_FILES:
        if nodeid.startswith(f):
            return f
    return "⚠ ANOMALY（非本片来源）"


def tri_class(base, current, label):
    b, c = set(base), set(current)
    same, only_b, only_c = sorted(b & c), sorted(b - c), sorted(c - b)
    print(f"\n--- [{label}] 三分类（原始 node id）---")
    print(f"  基线 {len(b)} / 当前 {len(c)} / SAME {len(same)} / ONLY_IN_BASELINE {len(only_b)} / ONLY_IN_CURRENT {len(only_c)}")
    print(f"  [SAME] {len(same)} 条（逐条）:")
    for n in same:
        print(f"    SAME            {n}")
    print(f"  [ONLY_IN_BASELINE] {len(only_b)} 条（逐条；**非空 ⇒ 硬停止条件**）:")
    for n in only_b:
        print(f"    ONLY_IN_BASELINE {n}")
    print(f"  [ONLY_IN_CURRENT] {len(only_c)} 条（逐条 + 来源文件）:")
    anomaly = []
    for n in only_c:
        src = source_of(n)
        if src.startswith("⚠"):
            anomaly.append(n)
        print(f"    ONLY_IN_CURRENT  {n}   ← {src}")
    return same, only_b, only_c, anomaly


def main() -> int:
    s = json.loads(SETS.read_text(encoding="utf-8"))
    route = set(s["route_plan_set"])
    old = set(s["load_ki_set"])
    new = set(s["load_ki_from_declaration_set"])
    supply = set(s["supply_chain_unwired_set"])
    reds = set(s["reds"])
    base44 = set(BASE_A) | set(BASE_B) | set(BASE_C) | set(BASE_E)

    print("=" * 78)
    print("M7.1-B1 确认跑｜基线审计 + 三分类 node id diff")
    print("=" * 78)
    print(f"[env] python={s['env']['python']}  pytest={s['env']['pytest']}  "
          f"探针内 pytest_exit={s['env']['pytest_exit']}")
    print("[cmd] cd /home/szf/dev/Leibniz-KERT && .venv/bin/python /tmp/m71b_confirm_probe.py")
    print("\n[已知边界] 本轮确认跑**不含 tests/e2e**（TL 裁定①）：e2e 需活服务、"
          "`kert_api_validation.py` 非 `test_*.py` 不被收集 ⇒ 不隐含排除，明写在此。")

    print("\n" + "[ 基线清单：内联 sha256 与文档解析 sha256 交叉核对 ]".center(78, "="))
    for label, inline, t, n in (("A", BASE_A, "### 2.2 A 组", "### 2.3"),
                                ("B", BASE_B, "### 2.3 B 组", "### 2.4"),
                                ("C", BASE_C, "### 2.4 C 组", "### 2.5"),
                                ("E", BASE_E, "### 2.5 E 组", "### 2.6"),
                                ("D_supply", BASE_D_SUPPLY, "### 2.6 D 组", "### 2.7"),
                                ("D_other", BASE_D_OTHER, "### 2.6 D 组", "### 2.7")):
        from_doc = doc_block(t, n)
        if label == "D_supply":
            from_doc = [x for x in from_doc if "test_graph_" in x]
        if label == "D_other":
            from_doc = [x for x in from_doc if "test_graph_" not in x]
        ok = set(inline) == set(from_doc)
        print(f"  {label:9s} 内联 {len(inline):2d} 条 sha256={sha_of(inline)}")
        print(f"  {'':9s} 文档 {len(from_doc):2d} 条 sha256={sha_of(from_doc)}  一致={ok}")
        if not ok:
            print(f"  {'':9s} ⚠ 差异: 仅内联={sorted(set(inline) - set(from_doc))} "
                  f"仅文档={sorted(set(from_doc) - set(inline))}")
    print(f"  A∪B∪C∪E 内联 sha256 = {sha_of(base44)}（44 条）")
    print("  红集基准内联 sha256 = " + sha_of(
        ["tests/unit/test_provision_cli.py::test_apply_then_idempotent_rerun",
         "tests/unit/test_provision_cli.py::test_json_output_follows_standard_envelope",
         "tests/unit/test_provision_cli.py::test_init_flag_initializes_fresh_volume_then_provisions"]))

    print("\n" + "[ 主口径：`_route_plan` 显式 node id 集合（R-G 硬证据）]".center(78, "="))
    _same44, only_b44, only_c44, anom = tri_class(base44, route, "A∪B∪C∪E(44) vs route_plan")
    print("\n  [A 组 29 条逐条在场]" )
    missing_a = sorted(set(BASE_A) - route)
    print(f"    A 组全部在场 = {not missing_a}（缺失 {len(missing_a)} 条）")
    for n in missing_a:
        print(f"      ONLY_IN_BASELINE {n}")

    print("\n" + "[ 双计数：同一脚本同一次跑 ]".center(78, "="))
    print(f"  _load_ki={len(old)}  _load_ki_from_declaration={len(new)}  supply_unwired={len(supply)}")
    for label, grp in (("A", BASE_A), ("B", BASE_B), ("C", BASE_C), ("E", BASE_E),
                       ("D_supply", BASE_D_SUPPLY), ("D_other", BASE_D_OTHER)):
        g = set(grp)
        print(f"  {label:9s} ⊆load_ki={str(g <= old):5s} ⊆new={str(g <= new):5s} | "
              f"load_ki∩={len(g & old):2d} new∩={len(g & new):2d}")
    print(f"  双向差集: 仅 load_ki（新计数未命中）={len(s['diff_only_load_ki'])} 条")
    for x in s["diff_only_load_ki"]:
        print(f"     ONLY_LOAD_KI        {x}")
    print(f"  双向差集: 仅 new（load_ki 未命中）={len(s['diff_only_new'])} 条")
    for x in s["diff_only_new"]:
        print(f"     ONLY_NEW            {x}   ← {source_of(x)}")

    print("\n" + "[ 红集（变多/变少都要报；变少到 0 先报 TL，不自行解读） ]".center(78, "="))
    base_red = set(BASE_RED)
    print(f"  当前红集 {len(reds)} 条；基准 {len(base_red)} 条")
    for n in sorted(reds):
        print(f"    RED       {n}")
    print(f"  变多（新增红）= {sorted(reds - base_red)}")
    print(f"  变少（消失红）= {sorted(base_red - reds)}")
    print(f"  红集 == 基准 3 条 ? {reds == base_red}")

    hard_stop = bool(only_b44) or bool(missing_a) or bool(anom)
    print("\n" + "=" * 78)
    print(f"[判据] 硬停止条件：A 组逐条差异={bool(only_b44) or bool(missing_a)}；"
          f"ONLY_IN_CURRENT 出现非本片来源={bool(anom)}")
    print(f"[结论] {'⛔ 触发停下条件 —— 立即报 TL，不自行解释' if hard_stop else '✅ 未触发停下条件'}")
    print("[边界] 本轮不含 tests/e2e（TL 裁定①）；第三方在途件未纳入我的改动面。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
