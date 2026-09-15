"""激活计划单元测试（M7.3；独立评审 §4.7 的 ActivationPlan）。

重点验证两件事：
1. **可重放**：同一输入 ⇒ 同一 plan_hash / plan_id / 逐字段一致（跨实例、跨进程重建亦然）；
   且主体与权限等**非确定性字段不入 hash**；
2. **fail-closed**：路由被拒 ⇒ 不产出计划，只产出显式拒绝。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from kert.domain.activation_plan import (
    ActivationPlan,
    ActivationPlanBuilder,
    PlanAsset,
    PlanDenial,
    canonical_content,
    compute_plan_hash,
    plan_id_for,
    replay_matches,
)
from kert.domain.knowledge_map import catalog_dir
from kert.domain.route_policy import POLICY_FILENAME, schema_dir
from kert.domain.workspace import init_workspace

REPO_ROOT = Path(__file__).resolve().parents[2]
REAL_WS = REPO_ROOT / "examples" / "bank-front-knowledge-maps"

REAL_TASKS = {
    "OUTREACH_PREPARATION": ("KM-CORP-RM-OUTREACH", 3, ["skill-customer-outreach-script"]),
    "MEETING_PREPARATION": ("KM-CORP-RM-MEETING", 4, ["skill-customer-meeting-script"]),
    "PRE_VISIT_PREPARATION": ("KM-CORP-RM-PREVISIT", 3, ["skill-customer-previsit-report"]),
}

HASH_RE = re.compile(r"^[0-9a-f]{16}$")


def _write_map(ws: Path, map_id: str, *, tasks: list[str], assets: list[dict],
               skills: list[str], route_policy_ref: str = "RP-TEST-0001") -> None:
    d = catalog_dir(ws)
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{map_id}.json").write_text(json.dumps({
        "schema": "knowledge_map/v1", "mapId": map_id, "version": "1.0.0",
        "title": f"地图 {map_id}", "domain": "customer", "tasks": tasks, "priority": 10,
        "assetRefs": assets, "skillRefs": skills, "routePolicyRef": route_policy_ref,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_policy(ws: Path, rules: list[dict]) -> None:
    d = schema_dir(ws)
    d.mkdir(parents=True, exist_ok=True)
    (d / POLICY_FILENAME).write_text(json.dumps({
        "schema": "route_policy/v1", "policyId": "RP-TEST-0001", "version": "1.0.0",
        "title": "测试策略", "defaultDecision": "DENY", "rules": rules,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------- #
# 真实工作区：三张地图各产出一份计划
# --------------------------------------------------------------------------- #

def test_real_workspace_builds_plan_for_each_task():
    for task, (map_id, asset_count, skills) in REAL_TASKS.items():
        plan = ActivationPlanBuilder.load(REAL_WS).build(task, subject_id="CUST-0001")
        assert isinstance(plan, ActivationPlan), f"{task} 应产出计划，实际 {plan}"
        assert HASH_RE.match(plan.plan_hash), plan.plan_hash
        assert plan.plan_id == plan_id_for(task, plan.plan_hash)
        assert plan.map_key == f"{map_id}@1.0.0"
        assert plan.policy_key == "RP-KERT-BANKFRONT-001@1.0.0"
        assert len(plan.assets) == asset_count, [a.asset_id for a in plan.assets]
        assert list(plan.skills) == skills
        assert plan.route_reason, "计划必须携带路由理由"
        # 预留槽位：不虚构取值
        assert plan.versions["activationContract"] is None
        assert plan.versions["ontology"] is None
        assert plan.versions["knowledgeMap"] == f"{map_id}@1.0.0"
        assert plan.versions["routePolicy"] == "RP-KERT-BANKFRONT-001@1.0.0"


def test_real_workspace_plan_is_deterministic_across_builders():
    """跨构建器实例（等价于跨进程重建）逐字段一致 ⇒ 可重放。"""
    a = ActivationPlanBuilder.load(REAL_WS).build("PRE_VISIT_PREPARATION", subject_id="C1")
    b = ActivationPlanBuilder.load(REAL_WS).build("PRE_VISIT_PREPARATION", subject_id="C1")
    assert isinstance(a, ActivationPlan) and isinstance(b, ActivationPlan)
    assert replay_matches(a, b)
    assert a.plan_hash == b.plan_hash
    assert a.to_dict() == b.to_dict()


def test_subject_and_permission_do_not_affect_hash():
    """主体/权限是**非确定性**字段 ⇒ 不得进入 plan_hash 或 plan_id。"""
    a = ActivationPlanBuilder.load(REAL_WS).build(
        "PRE_VISIT_PREPARATION", subject_id="CUST-A", permission_decision_id="PD-1")
    b = ActivationPlanBuilder.load(REAL_WS).build(
        "PRE_VISIT_PREPARATION", subject_id="CUST-B", permission_decision_id="PD-2")
    assert isinstance(a, ActivationPlan) and isinstance(b, ActivationPlan)
    assert a.plan_hash == b.plan_hash
    assert a.plan_id == b.plan_id
    assert a.subject_id != b.subject_id  # 但字段本身如实记录
    assert a.to_dict() != b.to_dict()


# --------------------------------------------------------------------------- #
# 哈希敏感性（防止"hash 恒定"这类空转）
# --------------------------------------------------------------------------- #

def _hash(assets: tuple[PlanAsset, ...], skills: tuple[str, ...]) -> str:
    return compute_plan_hash(task_type="T", policy_key="RP-X@1.0.0", map_key="KM-X@1.0.0",
                             assets=assets, skills=skills)


def test_plan_hash_is_sensitive_to_every_deterministic_field():
    base_assets = (PlanAsset("KI-009", True, 1),)
    base = _hash(base_assets, ("skill-a",))

    # 资产集合变
    assert _hash((PlanAsset("KI-009", True, 1), PlanAsset("KI-010", False, 2)), ("skill-a",)) != base
    # sequence 变
    assert _hash((PlanAsset("KI-009", True, 2),), ("skill-a",)) != base
    # required 变
    assert _hash((PlanAsset("KI-009", False, 1),), ("skill-a",)) != base
    # skill 变
    assert _hash(base_assets, ("skill-b",)) != base
    # skill **顺序**不变（排序后入 hash）⇒ 同集合同 hash
    assert _hash(base_assets, ("skill-b", "skill-a")) == _hash(base_assets, ("skill-a", "skill-b"))
    # 同输入可重放
    assert _hash(base_assets, ("skill-a",)) == base


def test_canonical_content_excludes_environment_fields():
    """hash 输入不得含环境/非确定性内容（路径、主体、时刻、计划 ID）。"""
    plan = ActivationPlanBuilder.load(REAL_WS).build("PRE_VISIT_PREPARATION", subject_id="CUST-A")
    assert isinstance(plan, ActivationPlan)

    content = canonical_content(task_type=plan.task_type, policy_key=plan.policy_key,
                                map_key=plan.map_key, assets=plan.assets, skills=plan.skills)

    # 绝对路径不得出现（含仓库根与实际工作区路径）
    assert str(REPO_ROOT) not in content
    assert str(REAL_WS) not in content
    # 非确定性字段不得出现
    for forbidden in ("createdAt", "planId", "timestamp", "CUST-A"):
        assert forbidden not in content, f"canonical content 不得含 {forbidden}"
    # 每行必须是 key=value，且值不得是以 / 开头的绝对路径
    for line in content.splitlines():
        _, _, value = line.partition("=")
        assert not value.startswith("/"), f"疑似环境路径进入 hash 输入: {line}"


# --------------------------------------------------------------------------- #
# fail-closed：路由被拒 ⇒ 不产出计划
# --------------------------------------------------------------------------- #

def test_denied_when_policy_absent(tmp_path: Path):
    ws = tmp_path / "ws"
    init_workspace(ws)
    _write_map(ws, "KM-TEST-0001", tasks=["TASK_A"],
               assets=[{"assetId": "KI-009", "required": True, "sequence": 1}],
               skills=["skill-a"])
    decision = ActivationPlanBuilder.load(ws).build("TASK_A")
    assert isinstance(decision, PlanDenial)
    assert decision.allowed is False
    assert decision.code == "ROUTE_POLICY_ABSENT"


def test_denied_for_unmapped_task(tmp_path: Path):
    ws = tmp_path / "ws"
    init_workspace(ws)
    _write_map(ws, "KM-TEST-0001", tasks=["TASK_A"],
               assets=[{"assetId": "KI-009", "required": True, "sequence": 1}],
               skills=["skill-a"])
    _write_policy(ws, [{"priority": 10, "taskType": "TASK_A",
                        "knowledgeMapId": "KM-TEST-0001", "reason": "r"}])
    decision = ActivationPlanBuilder.load(ws).build("NOPE")
    assert isinstance(decision, PlanDenial)
    assert decision.code == "ROUTE_NOT_MAPPED"


def test_denied_for_ambiguous_task(tmp_path: Path):
    ws = tmp_path / "ws"
    init_workspace(ws)
    for mid in ("KM-TEST-0001", "KM-TEST-0002"):
        _write_map(ws, mid, tasks=["TASK_A"],
                   assets=[{"assetId": "KI-009", "required": True, "sequence": 1}],
                   skills=["skill-a"])
    _write_policy(ws, [
        {"priority": 10, "taskType": "TASK_A", "knowledgeMapId": "KM-TEST-0001", "reason": "r1"},
        {"priority": 10, "taskType": "TASK_A", "knowledgeMapId": "KM-TEST-0002", "reason": "r2"},
    ])
    decision = ActivationPlanBuilder.load(ws).build("TASK_A")
    assert isinstance(decision, PlanDenial)
    assert decision.code == "ROUTE_AMBIGUOUS"
    assert "歧义" in decision.reason


def test_plan_to_dict_shape_is_stable():
    """落盘形状固定：键集合与排序稳定（跨仓对照依赖此形状）。"""
    plan = ActivationPlanBuilder.load(REAL_WS).build("PRE_VISIT_PREPARATION")
    assert isinstance(plan, ActivationPlan)
    d = plan.to_dict()
    assert list(d.keys()) == ["schema", "planId", "taskType", "subjectId", "routeReason",
                              "versions", "assets", "skills", "planHash"]
    assert d["schema"] == "activation_plan/v1"
    assert [a["sequence"] for a in d["assets"]] == [1, 2, 3]
    assert d["skills"] == sorted(d["skills"])
