"""M7 ②：**新纳入计划门禁的 4 个技能** —— 正例（有合法声明 ⇒ 放行且跑通）
+ 反例（声明缺失 / 非法 ⇒ **具名拒绝**）。

被核技能（此前由 ``defaultDecision: DENY`` 绕过门禁，直连可执行）：

===============================  ======================================  ========================
skill                          taskType                                 地图
===============================  ======================================  ========================
``bank-front-supply-chain-graph``  ``SUPPLY_CHAIN_GRAPH_ANALYSIS``       ``KM-CORP-RM-SUPPLYCHAIN``
``SP-15``                      ``PRODUCT_RECOMMENDATION_DECISION``     ``KM-CORP-RM-PRODUCT``
``SP-20``                      ``SERVICE_PROPOSAL_PREPARATION``        ``KM-CORP-RM-PROPOSAL``
``SP-21``                      ``INTERACTION_MEMORY_EXTRACTION``       ``KM-CORP-RM-MEMORY``
===============================  ======================================  ========================

口径与既有 3 个 customer-engagement 技能**完全一致**（``SkillExecutionService._route_plan``，
fail-closed，**不回落**任何字面量清单）：工作区未配置 / 策略缺失 / 任务未映射 / 地图未注册 /
地图非法 / 本体引用缺失 ⇒ ``SkillError``（合同既有码 ``KERT_PERMISSION_DENIED``，
具体路由码在 ``detail.routeCode``），**执行器不会被调用、不产出业务结果**。

反例覆盖四档：① 无工作区 ② 无控制面（策略缺失）③ 任务规则被删 ④ 地图声明非法（未知字段）。
每档都对 4 个技能逐一无遗漏（parametrize），任一新技能漏接门禁 ⇒ 变红。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from kert.application.provision import provision_control_plane  # noqa: E402
from kert.application.skills import SkillExecutionService  # noqa: E402
from kert.domain.workspace import init_workspace  # noqa: E402

SOURCE = ROOT / "examples" / "bank-front-knowledge-maps"
SKILL_PKGS = ROOT / "examples" / "bank-front-skills"
CUSTOMER_ID = "CUST-CORP-0001"

#: skill_id -> (taskType, mapId, request)。请求取各技能的最小合法输入。
CASES: dict[str, tuple[str, str, dict]] = {
    "bank-front-supply-chain-graph": (
        "SUPPLY_CHAIN_GRAPH_ANALYSIS", "KM-CORP-RM-SUPPLYCHAIN", {"customerId": CUSTOMER_ID}),
    "SP-15": (
        "PRODUCT_RECOMMENDATION_DECISION", "KM-CORP-RM-PRODUCT",
        {"context": {
            "schemaVersion": "1.0.0", "customerId": CUSTOMER_ID,
            "needVersionIds": ["NEEDV-001"], "recommendationObjective": "补充流动资金",
            "asOf": "2026-09-15T09:00:00+08:00",
            "customerFactSnapshotId": "CFS-CUST-CORP-0001",
            "productKnowledgeSnapshotRef": "PKS-20260831-0001",
            "ruleBundleRef": "RB-20260831-0001",
            "permissionDecisionId": "PERM-20260831-0001",
        }}),
    "SP-20": (
        "SERVICE_PROPOSAL_PREPARATION", "KM-CORP-RM-PROPOSAL",
        {"context": {
            "customerId": CUSTOMER_ID, "customerName": "华东精工装备集团有限公司",
            "industry": "制造业-装备制造", "engagementPhase": "ACTIVE_ENGAGEMENT",
            "enterpriseData": {"basicInfo": {}, "financialSummary": {}},
        }}),
    "SP-21": (
        "INTERACTION_MEMORY_EXTRACTION", "KM-CORP-RM-MEMORY",
        {"context": {
            "customerId": CUSTOMER_ID, "interactionId": "INT-GATE-0001",
            "interactionContent": "客户对供应链融资产品表示兴趣，希望了解授信额度和利率",
        }}),
}

#: 允许出现的路由拒绝码（全部来自既有受控件：``route_policy`` 的 ``ROUTE_*``；
#: ``ROUTE_UNRESOLVED`` 是 ``_route_plan`` 对"解析期即失败"（无工作区 / 地图非法）的归类码）。
NAMED_ROUTE_CODES = frozenset({
    "ROUTE_UNRESOLVED", "ROUTE_POLICY_ABSENT", "ROUTE_NOT_MAPPED",
    "ROUTE_AMBIGUOUS", "ROUTE_MAP_UNKNOWN", "ROUTE_MAP_POLICY_MISMATCH",
})


def _svc(ws: Path | None) -> SkillExecutionService:
    """显式注入技能包目录（不依赖 ``KERT_SKILL_PACKAGES`` 环境变量）。"""
    return SkillExecutionService(ws, skill_packages=SKILL_PKGS)


@pytest.fixture
def ws_ready(tmp_path: Path) -> Path:
    """已供给控制面的工作区（门禁可放行的前置）。"""
    init_workspace(tmp_path)
    provision_control_plane(tmp_path, SOURCE)
    return tmp_path


def _plan_entry(trace: list[dict]) -> dict:
    entries = [t for t in trace if t.get("phase") == "evidence" and t.get("mapId")]
    assert len(entries) == 1, f"计划留痕应恰好 1 条，实际 {len(entries)}"
    return entries[0]


# --------------------------------------------------------------------------- #
# 正例：有合法声明 ⇒ 放行且跑通
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("skill_id", sorted(CASES))
def test_positive_allow_and_run(ws_ready, skill_id):
    """有声明 ⇒ 放行：执行成功，且 trace 里留下**计划留痕**（地图 + planHash）。"""
    task, map_id, request = CASES[skill_id]
    r = _svc(ws_ready).execute(skill_id, f"gate-ok-{skill_id}", request)

    assert r.status == "ok", f"{skill_id} 应放行并跑通，实际 {r.status}: {r.errors}"
    assert not r.errors
    e = _plan_entry(r.assembly_trace)
    assert e["status"] == "ok"
    assert e["mapId"] == map_id
    assert e["versions"]["routePolicy"] == "RP-KERT-BANKFRONT-001@1.1.0"
    assert len(e["planHash"]) == 16
    assert "mapMismatch" not in e, "计划所选地图必须与本技能的期望地图一致"


# --------------------------------------------------------------------------- #
# 反例：声明缺失 / 非法 ⇒ 具名拒绝（执行器不被调用）
# --------------------------------------------------------------------------- #

def _assert_named_refusal(r, *, task: str, expected_code: str) -> None:
    """被拒的**机械判据**：合同既有错误码 + trace 里恰好一条 blocked 具名码 + 无计划留痕 + 无业务结果。

    ``SkillExecutionService.execute`` **不抛异常**（与 API 信封一致）：拒绝以
    ``status == "skill_error"`` + ``errors[].code == KERT_PERMISSION_DENIED`` 表达，
    具体路由码落在 trace 的 blocked 条目 ``errorCode`` —— 与既有 3 个技能同口径
    （见 ``tests/integration/test_skill_routing_trace.py``）。
    """
    assert r.status == "skill_error", f"应被拒绝，实际 status={r.status}（{r.errors}）"
    assert "KERT_PERMISSION_DENIED" in {e.get("code") for e in r.errors}, r.errors

    blocked = [t for t in r.assembly_trace
               if t.get("phase") == "evidence" and t.get("status") == "blocked"]
    assert len(blocked) == 1, f"应恰好一条 blocked 留痕，实际 {blocked}"
    assert blocked[0].get("errorCode") == expected_code, blocked[0]
    assert blocked[0].get("errorCode") in NAMED_ROUTE_CODES, blocked[0]
    assert task in json.dumps(r.errors, ensure_ascii=False), r.errors

    assert not [t for t in r.assembly_trace if t.get("mapId")], "被拒时不得留下计划放行留痕"
    assert not (r.data or {}).get("result"), "被拒时不得产出业务结果"


#: 无工作区时**仍已注册**的技能（SP-15 不在此列，见下一条用例）。
NO_WS_REGISTERED = tuple(sorted(set(CASES) - {"SP-15"}))


@pytest.mark.parametrize("skill_id", NO_WS_REGISTERED)
def test_negative_no_workspace_is_named_refusal(skill_id):
    """① 无工作区 ⇒ ``ROUTE_UNRESOLVED``（不得因"没有工作区"而放过）。"""
    task, _map_id, request = CASES[skill_id]
    r = _svc(None).execute(skill_id, f"gate-nws-{skill_id}", request)
    _assert_named_refusal(r, task=task, expected_code="ROUTE_UNRESOLVED")


def test_negative_no_workspace_sp15_is_refused_even_earlier():
    """SP-15 的特殊性（**既有**注册口径，非本次接线引入）：它只在**有工作区**时注册
    （见 ``skills.py`` 的 WP6-2 分支）⇒ 无工作区时在**更早一层**就被具名拒绝
    （``UNKNOWN_SKILL``），根本走不到路由门禁。

    此处如实钉住该事实：仍然是具名拒绝 + 无业务结果，**不是**静默放过。
    """
    _task, _map_id, request = CASES["SP-15"]
    r = _svc(None).execute("SP-15", "gate-nws-sp15", request)
    assert r.status == "skill_error", r.status
    assert {e.get("code") for e in r.errors} == {"UNKNOWN_SKILL"}, r.errors
    assert not (r.data or {}).get("result")


@pytest.mark.parametrize("skill_id", sorted(CASES))
def test_negative_control_plane_absent_is_named_refusal(tmp_path, skill_id):
    """② 有工作区但**未供给控制面**（策略缺失）⇒ ``ROUTE_POLICY_ABSENT``。"""
    task, _map_id, request = CASES[skill_id]
    init_workspace(tmp_path)
    r = _svc(tmp_path).execute(skill_id, f"gate-nocp-{skill_id}", request)
    _assert_named_refusal(r, task=task, expected_code="ROUTE_POLICY_ABSENT")


@pytest.mark.parametrize("skill_id", sorted(CASES))
def test_negative_task_rule_removed_is_named_refusal(ws_ready, skill_id):
    """③ 供给后把该任务的**规则删掉** ⇒ ``ROUTE_NOT_MAPPED``（默认拒绝，不回落）。"""
    task, _map_id, request = CASES[skill_id]
    p = ws_ready / "90_control" / "schema" / "route_policy.json"
    doc = json.loads(p.read_text(encoding="utf-8"))
    kept = [r for r in doc["rules"] if r["taskType"] != task]
    assert len(kept) == len(doc["rules"]) - 1, f"夹具失效：策略里没有 {task} 的规则"
    doc["rules"] = kept
    p.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    r = _svc(ws_ready).execute(skill_id, f"gate-norule-{skill_id}", request)
    _assert_named_refusal(r, task=task, expected_code="ROUTE_NOT_MAPPED")


@pytest.mark.parametrize("skill_id", sorted(CASES))
def test_negative_illegal_map_declaration_is_named_refusal(ws_ready, skill_id):
    """④ 地图声明**非法**（未知字段，契约拒绝静默忽略）⇒ 具名拒绝，不静默放过。"""
    task, map_id, request = CASES[skill_id]
    p = ws_ready / "90_control" / "catalog" / f"{map_id}.json"
    doc = json.loads(p.read_text(encoding="utf-8"))
    doc["unknownField"] = 1
    p.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    r = _svc(ws_ready).execute(skill_id, f"gate-badmap-{skill_id}", request)
    _assert_named_refusal(r, task=task, expected_code="ROUTE_UNRESOLVED")
