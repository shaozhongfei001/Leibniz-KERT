"""路由策略单元测试（M7.3；独立评审 §4.7 的 RoutePolicy）。

覆盖：真实工作区命中 / 默认拒绝（无策略、任务未映射）/ 同优先级歧义拒绝（且**爆炸半径最小**）/
跨引用校验（规则指向未注册地图、地图与策略错配）/ 契约拒绝（未知字段、非法默认决策等）。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from kert.domain.errors import SchemaValidationError
from kert.domain.knowledge_map import KnowledgeMapRegistry, catalog_dir
from kert.domain.route_policy import (
    CODE_AMBIGUOUS,
    CODE_MAP_POLICY_MISMATCH,
    CODE_MAP_UNKNOWN,
    CODE_NO_POLICY,
    CODE_NOT_MAPPED,
    CODE_OK,
    POLICY_FILENAME,
    RouteResolver,
    load_route_policy,
    parse_route_policy,
    policy_path,
    schema_dir,
)
from kert.domain.workspace import init_workspace

REPO_ROOT = Path(__file__).resolve().parents[2]
REAL_WS = REPO_ROOT / "examples" / "bank-front-knowledge-maps"

REAL_ROUTES = {
    "OUTREACH_PREPARATION": "KM-CORP-RM-OUTREACH",
    "MEETING_PREPARATION": "KM-CORP-RM-MEETING",
    "PRE_VISIT_PREPARATION": "KM-CORP-RM-PREVISIT",
}


def _policy_doc(**overrides) -> dict:
    doc = {
        "schema": "route_policy/v1",
        "policyId": "RP-TEST-0001",
        "version": "1.0.0",
        "title": "测试策略",
        "defaultDecision": "DENY",
        "rules": [
            {"priority": 10, "taskType": "TEST_TASK",
             "knowledgeMapId": "KM-TEST-0001", "reason": "测试路由"},
        ],
    }
    doc.update(overrides)
    return doc


def _write_policy(ws: Path, doc: dict) -> Path:
    d = schema_dir(ws)
    d.mkdir(parents=True, exist_ok=True)
    p = d / POLICY_FILENAME
    p.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return p


def _write_map(ws: Path, map_id: str, *, tasks: list[str], route_policy_ref: str | None = None) -> None:
    d = catalog_dir(ws)
    d.mkdir(parents=True, exist_ok=True)
    doc = {
        "schema": "knowledge_map/v1",
        "mapId": map_id,
        "version": "1.0.0",
        "title": f"地图 {map_id}",
        "domain": "customer",
        "tasks": tasks,
        "priority": 10,
        "assetRefs": [{"assetId": "KI-009", "required": True, "sequence": 1}],
        "skillRefs": ["skill-customer-outreach-script"],
    }
    if route_policy_ref:
        doc["routePolicyRef"] = route_policy_ref
    (d / f"{map_id}.json").write_text(
        json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------- #
# 真实工作区
# --------------------------------------------------------------------------- #

def test_real_workspace_policy_routes_three_tasks():
    resolver = RouteResolver.load(REAL_WS)
    policy = resolver.policy

    assert policy is not None, f"{policy_path(REAL_WS)} 必须存在"
    assert policy.policy_id == "RP-KERT-BANKFRONT-001"
    assert policy.version == "1.0.0"
    assert policy.default_decision == "DENY"
    assert len(policy.rules) == 3, [r.task_type for r in policy.rules]
    assert policy.ambiguous_task_types == ()

    for task, expected_map in REAL_ROUTES.items():
        res = resolver.resolve(task)
        assert res.allowed, f"{task} 应被放行，实际 {res.code}: {res.reason}"
        assert res.map is not None and res.map.map_id == expected_map
        assert res.rule is not None and res.rule.reason, "路由必须可解释（reason 非空）"
        assert res.policy_key == "RP-KERT-BANKFRONT-001@1.0.0"
        # 地图与策略双侧一致：地图也声明了该策略引用
        assert res.map.route_policy_ref == policy.policy_id


def test_real_workspace_maps_reference_the_policy():
    """跨引用一致性：三张地图的 routePolicyRef 必须等于真实策略 ID。"""
    reg = KnowledgeMapRegistry.load(REAL_WS)
    policy = load_route_policy(REAL_WS)
    assert policy is not None
    refs = {m.route_policy_ref for m in reg.maps}
    assert refs == {policy.policy_id}, refs


# --------------------------------------------------------------------------- #
# fail-closed：默认拒绝 / 歧义拒绝
# --------------------------------------------------------------------------- #

def test_default_deny_when_policy_absent(tmp_path: Path):
    ws = tmp_path / "ws"
    init_workspace(ws)
    _write_map(ws, "KM-TEST-0001", tasks=["TEST_TASK"])  # 有地图、无策略

    resolver = RouteResolver.load(ws)
    assert resolver.policy is None
    res = resolver.resolve("TEST_TASK")
    assert not res.allowed and res.code == CODE_NO_POLICY
    # 注册表本身仍能解析（用于诊断），但路由**不放行**
    assert resolver.resolve_via_registry_only("TEST_TASK").allowed


def test_default_deny_for_unmapped_task(tmp_path: Path):
    ws = tmp_path / "ws"
    init_workspace(ws)
    _write_map(ws, "KM-TEST-0001", tasks=["TEST_TASK"])
    _write_policy(ws, _policy_doc())

    res = RouteResolver.load(ws).resolve("OTHER_TASK")
    assert not res.allowed and res.code == CODE_NOT_MAPPED
    assert "TEST_TASK" in res.reason


def test_same_priority_ambiguity_denied_with_small_blast_radius(tmp_path: Path):
    """同优先级歧义 ⇒ 该任务拒绝；**其余任务不受影响**（爆炸半径最小化）。"""
    ws = tmp_path / "ws"
    init_workspace(ws)
    _write_map(ws, "KM-TEST-0001", tasks=["TASK_A"], route_policy_ref="RP-TEST-0001")
    _write_map(ws, "KM-TEST-0002", tasks=["TASK_A"])
    _write_map(ws, "KM-TEST-0003", tasks=["TASK_B"], route_policy_ref="RP-TEST-0001")
    _write_policy(ws, _policy_doc(rules=[
        {"priority": 10, "taskType": "TASK_A", "knowledgeMapId": "KM-TEST-0001", "reason": "r1"},
        {"priority": 10, "taskType": "TASK_A", "knowledgeMapId": "KM-TEST-0002", "reason": "r2"},
        {"priority": 10, "taskType": "TASK_B", "knowledgeMapId": "KM-TEST-0003", "reason": "r3"},
    ]))

    resolver = RouteResolver.load(ws)
    assert resolver.policy is not None
    assert resolver.policy.ambiguous_task_types == ("TASK_A",)  # 诊断可见

    denied = resolver.resolve("TASK_A")
    assert not denied.allowed and denied.code == CODE_AMBIGUOUS
    assert denied.candidates == ("KM-TEST-0001", "KM-TEST-0002")

    ok = resolver.resolve("TASK_B")
    assert ok.allowed and ok.map is not None and ok.map.map_id == "KM-TEST-0003"


def test_lower_priority_wins(tmp_path: Path):
    ws = tmp_path / "ws"
    init_workspace(ws)
    _write_map(ws, "KM-TEST-0001", tasks=["TASK_A"])
    _write_map(ws, "KM-TEST-0002", tasks=["TASK_A"])
    _write_policy(ws, _policy_doc(rules=[
        {"priority": 30, "taskType": "TASK_A", "knowledgeMapId": "KM-TEST-0001", "reason": "low"},
        {"priority": 10, "taskType": "TASK_A", "knowledgeMapId": "KM-TEST-0002", "reason": "high"},
    ]))
    res = RouteResolver.load(ws).resolve("TASK_A")
    assert res.allowed and res.map is not None and res.map.map_id == "KM-TEST-0002"
    assert res.reason == "high"


def test_map_declaring_other_policy_is_denied(tmp_path: Path):
    """地图声明了**别的**策略 ⇒ 拒绝（防错配）。"""
    ws = tmp_path / "ws"
    init_workspace(ws)
    _write_map(ws, "KM-TEST-0001", tasks=["TASK_A"], route_policy_ref="RP-OTHER-999")
    _write_policy(ws, _policy_doc(rules=[
        {"priority": 10, "taskType": "TASK_A", "knowledgeMapId": "KM-TEST-0001", "reason": "r"},
    ]))
    # 构造期即拒绝（策略与地图错配是**定义**问题）
    with pytest.raises(SchemaValidationError, match="不一致"):
        RouteResolver.load(ws)


def test_rule_pointing_to_unregistered_map_is_rejected(tmp_path: Path):
    ws = tmp_path / "ws"
    init_workspace(ws)
    _write_policy(ws, _policy_doc(rules=[
        {"priority": 10, "taskType": "TASK_A", "knowledgeMapId": "KM-ABSENT-0001", "reason": "r"},
    ]))
    with pytest.raises(SchemaValidationError, match="未注册的知识地图"):
        RouteResolver.load(ws)


def test_policy_vs_map_task_mismatch_is_denied(tmp_path: Path):
    """策略把任务路由到某地图，但该地图未声明此任务 ⇒ 拒绝（双侧一致性）。"""
    ws = tmp_path / "ws"
    init_workspace(ws)
    _write_map(ws, "KM-TEST-0001", tasks=["OTHER_TASK"], route_policy_ref="RP-TEST-0001")
    _write_policy(ws, _policy_doc(rules=[
        {"priority": 10, "taskType": "TASK_A", "knowledgeMapId": "KM-TEST-0001", "reason": "r"},
    ]))
    res = RouteResolver.load(ws).resolve("TASK_A")
    assert not res.allowed and res.code == CODE_NOT_MAPPED
    assert "未声明此任务" in res.reason


@pytest.mark.parametrize("task", ["", "   ", None, 5])
def test_resolve_rejects_blank_task(tmp_path: Path, task):
    ws = tmp_path / "ws"
    init_workspace(ws)
    with pytest.raises(SchemaValidationError):
        RouteResolver.load(ws).resolve(task)


def test_expected_codes_are_stable():
    """拒绝码是对外契约的一部分，改动需显式（防止静默改名）。"""
    assert (CODE_OK, CODE_NO_POLICY, CODE_NOT_MAPPED, CODE_AMBIGUOUS,
            CODE_MAP_UNKNOWN, CODE_MAP_POLICY_MISMATCH) == (
        "OK", "ROUTE_POLICY_ABSENT", "ROUTE_NOT_MAPPED", "ROUTE_AMBIGUOUS",
        "ROUTE_MAP_UNKNOWN", "ROUTE_MAP_POLICY_MISMATCH")


# --------------------------------------------------------------------------- #
# 契约拒绝
# --------------------------------------------------------------------------- #

def test_unknown_top_level_field_rejected():
    with pytest.raises(SchemaValidationError, match="未声明字段"):
        parse_route_policy(_policy_doc(extra=1), source="t.json")


def test_unknown_rule_field_rejected():
    doc = _policy_doc(rules=[{"priority": 10, "taskType": "T", "knowledgeMapId": "KM-TEST-0001",
                              "reason": "r", "bogus": True}])
    with pytest.raises(SchemaValidationError, match="规则含未声明字段"):
        parse_route_policy(doc, source="t.json")


@pytest.mark.parametrize(("override", "match"), [
    ({"schema": "route_policy/v2"}, "schema 不支持"),
    ({"policyId": "XX-TEST-0001"}, "必须以 'RP-' 开头"),
    ({"policyId": "rp-lower"}, "非法路由策略 ID"),
    ({"version": "1.0"}, "非法version"),
    ({"defaultDecision": "ALLOW"}, "只允许 'DENY'"),
    ({"rules": []}, "rules 必须是非空数组"),
    ({"title": " "}, "title"),
])
def test_policy_contract_violations(override: dict, match: str):
    with pytest.raises(SchemaValidationError, match=match):
        parse_route_policy(_policy_doc(**override), source="t.json")


def test_rule_field_violations():
    base = {"priority": 10, "taskType": "T", "knowledgeMapId": "KM-TEST-0001", "reason": "r"}
    for override, match in (
        ({"priority": -1}, "priority 必须是非负整数"),
        ({"taskType": ""}, "taskType 必须是非空字符串"),
        ({"knowledgeMapId": "lower"}, "非法知识地图 ID"),
        ({"reason": "  "}, "reason 必须是非空字符串"),
    ):
        doc = _policy_doc(rules=[{**base, **override}])
        with pytest.raises(SchemaValidationError, match=match):
            parse_route_policy(doc, source="t.json")


def test_bad_json_policy_is_rejected(tmp_path: Path):
    ws = tmp_path / "ws"
    init_workspace(ws)
    d = schema_dir(ws)
    (d / POLICY_FILENAME).write_text("{oops", encoding="utf-8")
    with pytest.raises(SchemaValidationError, match="无法解析"):
        load_route_policy(ws)


def test_policy_file_absent_returns_none(tmp_path: Path):
    ws = tmp_path / "ws"
    init_workspace(ws)
    assert load_route_policy(ws) is None
    assert not policy_path(ws).exists()
