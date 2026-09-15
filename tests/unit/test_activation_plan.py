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
from kert.domain.ontology_reference import FILENAME as ONTOLOGY_FILENAME
from kert.domain.route_policy import POLICY_FILENAME, RouteResolver, schema_dir
from kert.domain.workspace import init_workspace

REPO_ROOT = Path(__file__).resolve().parents[2]
REAL_WS = REPO_ROOT / "examples" / "bank-front-knowledge-maps"

REAL_TASKS = {
    # task -> (mapId, mapVersion, assetCount, skillRefs)
    # PREVISIT 为 1.0.1 / 7 条：1.0.0 时误只列 3 条（属 _run_supply_chain 的读取集），
    # 受治理内容变更故升版本；逐技能一致性由 test_control_plane_consistency.py 机械核对。
    "OUTREACH_PREPARATION": ("KM-CORP-RM-OUTREACH", "1.0.0", 3,
                             ["skill-customer-outreach-script"]),
    "MEETING_PREPARATION": ("KM-CORP-RM-MEETING", "1.0.0", 4,
                            ["skill-customer-meeting-script"]),
    "PRE_VISIT_PREPARATION": ("KM-CORP-RM-PREVISIT", "1.0.1", 7,
                              ["skill-customer-previsit-report"]),
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
    for task, (map_id, map_version, asset_count, skills) in REAL_TASKS.items():
        plan = ActivationPlanBuilder.load(REAL_WS).build(task, subject_id="CUST-0001")
        assert isinstance(plan, ActivationPlan), f"{task} 应产出计划，实际 {plan}"
        assert HASH_RE.match(plan.plan_hash), plan.plan_hash
        assert plan.plan_id == plan_id_for(task, plan.plan_hash)
        assert plan.map_key == f"{map_id}@{map_version}"
        assert plan.policy_key == "RP-KERT-BANKFRONT-001@1.0.0"
        assert len(plan.assets) == asset_count, [a.asset_id for a in plan.assets]
        assert list(plan.skills) == skills
        assert plan.route_reason, "计划必须携带路由理由"
        # 预留槽位：不虚构取值
        assert plan.versions["activationContract"] is None
        # 本体引用槽位自 M7.3 第三步起填入**真实声明值**（见本文件"本体引用"一节）
        assert plan.versions["ontology"] == ONTOLOGY_VERSION_A
        assert plan.versions["knowledgeMap"] == f"{map_id}@{map_version}"
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
    # 断言**不变量**而非字面量：sequence 必须 1..N 连续且从 1 起
    # （原写死 [1, 2, 3]，曾把 PREVISIT 只有 3 条资产的缺陷一起"背书"住了）
    seqs = [a["sequence"] for a in d["assets"]]
    assert seqs, "计划必须携带资产"
    assert seqs == list(range(1, len(seqs) + 1)), seqs
    assert d["skills"] == sorted(d["skills"])


# --------------------------------------------------------------------------- #
# M7.3 第三步：本体引用（D-3 入 hash / D-4 fail-closed）
# --------------------------------------------------------------------------- #

ONTOLOGY_SHA_A = "705578d6324abd0c1bd2bd670e6f3c0ffd8e04c358d0134246c89a3acfc38d00"
ONTOLOGY_SHA_B = "1111111122222222333333334444444455555555666666667777777788888888"
ONTOLOGY_VERSION_A = "CTR-SEM-002@sha256:705578d6324abd0c"

ONTOLOGY_TASK = "ONTOLOGY_TEST_TASK"
ONTOLOGY_MAP = "KM-ONTOLOGY-TEST-0001"


def _write_ontology_ws(ws: Path, *, sha256: str = ONTOLOGY_SHA_A,
                       repo: str = "gits-cbanking",
                       source: str = "specs/semantic/gits-core.owl.ttl") -> None:
    """构造最小可放行工作区（地图 + 策略 + 本体引用声明）。"""
    _write_map(ws, ONTOLOGY_MAP, tasks=[ONTOLOGY_TASK],
               assets=[{"assetId": "KI-009", "required": True, "sequence": 1},
                       {"assetId": "KI-010", "required": False, "sequence": 2}],
               skills=["skill-a"])
    _write_policy(ws, [{"priority": 10, "taskType": ONTOLOGY_TASK,
                        "knowledgeMapId": ONTOLOGY_MAP, "reason": "本体相关路由"}])
    d = schema_dir(ws)
    d.mkdir(parents=True, exist_ok=True)
    (d / ONTOLOGY_FILENAME).write_text(json.dumps({
        "schema": "ontology_reference/v1", "contractId": "CTR-SEM-002",
        "authorityRepo": repo, "authoritySource": source, "contentSha256": sha256,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _build(ws: Path):
    return ActivationPlanBuilder.load(ws).build(ONTOLOGY_TASK, subject_id="CUST-0001")


def test_real_workspace_plan_carries_ontology_version_in_versions():
    """受控工作区：`versions.ontology` 取**真实值**（不再是预留 `None`），且格式与 gits 侧一致。"""
    plan = ActivationPlanBuilder.load(REAL_WS).build("PRE_VISIT_PREPARATION")
    assert isinstance(plan, ActivationPlan)
    assert plan.versions["ontology"] == ONTOLOGY_VERSION_A
    assert plan.versions["activationContract"] is None  # 仍为预留槽位
    assert plan.to_dict()["versions"]["ontology"] == ONTOLOGY_VERSION_A


def test_ontology_version_enters_plan_hash(tmp_path: Path):
    """**D-3 主线负例**：只改声明里的哈希 ⇒ plan_hash 必须变；换回 ⇒ 必须回到原值。"""
    ws = tmp_path / "ws"
    init_workspace(ws)
    _write_ontology_ws(ws, sha256=ONTOLOGY_SHA_A)
    before = _build(ws)
    assert isinstance(before, ActivationPlan), before

    # 变异：换一个**合法**哈希
    _write_ontology_ws(ws, sha256=ONTOLOGY_SHA_B)
    after = _build(ws)
    assert isinstance(after, ActivationPlan), after
    assert after.plan_hash != before.plan_hash, "本体版本必须进入 plan hash"
    assert after.plan_id != before.plan_id

    # 反向对照（防空转）：只改来源路径/仓名，不改哈希 ⇒ plan_hash **必须不变**
    _write_ontology_ws(ws, sha256=ONTOLOGY_SHA_A,
                       repo="another-repo", source="docs/ontology/other.ttl")
    path_only = _build(ws)
    assert isinstance(path_only, ActivationPlan), path_only
    assert path_only.plan_hash == before.plan_hash, "来源路径不得进入 plan hash"
    assert path_only.ontology_source == "another-repo:docs/ontology/other.ttl"
    assert path_only.plan_hash != after.plan_hash

    # 换回原哈希 ⇒ 可重放
    _write_ontology_ws(ws, sha256=ONTOLOGY_SHA_A)
    restored = _build(ws)
    assert isinstance(restored, ActivationPlan), restored
    assert replay_matches(before, restored)
    assert restored.plan_hash == before.plan_hash


def test_ontology_version_prefix_is_consistent_with_plan_hash_length():
    """版本中的哈希前缀与 plan hash 取同一长度口径（16 hex）。"""
    plan = ActivationPlanBuilder.load(REAL_WS).build("OUTREACH_PREPARATION")
    assert isinstance(plan, ActivationPlan)
    prefix = plan.versions["ontology"].split("@sha256:")[1]
    assert len(prefix) == len(plan.plan_hash) == 16


def test_ontology_key_participates_in_canonical_content():
    """`canonical_content` 显式包含 ontology 行（防空转：不靠"变量没用到"这种隐性行为）。"""
    base = dict(task_type="T", policy_key="RP-X@1.0.0", map_key="KM-X@1.0.0",
                assets=(PlanAsset("KI-009", True, 1),), skills=("skill-a",))
    with_ont = canonical_content(**base, ontology_key=ONTOLOGY_VERSION_A)
    without_ont = canonical_content(**base)
    assert "ontology=" in with_ont
    assert with_ont != without_ont
    assert canonical_content(**base, ontology_key=ONTOLOGY_VERSION_A) == with_ont


def test_denied_when_ontology_declaration_absent(tmp_path: Path):
    """**D-4 主线负例**：移走/未提供声明文件 ⇒ 计划构建必须 Deny（不是"照常出计划"）。"""
    ws = tmp_path / "ws"
    init_workspace(ws)
    _write_ontology_ws(ws)
    ok = _build(ws)
    assert isinstance(ok, ActivationPlan), ok  # 先证明夹具本身能放行（防夹具缺失导致恒真）

    # 变异：移走声明文件
    (schema_dir(ws) / ONTOLOGY_FILENAME).unlink()
    denied = _build(ws)
    assert isinstance(denied, PlanDenial), "声明缺失时不得照常出计划"
    assert denied.allowed is False
    assert denied.code == "ONTOLOGY_REFERENCE_ABSENT"

    # 恢复 ⇒ 回到可放行且 hash 一致
    _write_ontology_ws(ws)
    restored = _build(ws)
    assert isinstance(restored, ActivationPlan), restored
    assert restored.plan_hash == ok.plan_hash


def test_denied_when_ontology_declaration_invalid(tmp_path: Path):
    """声明非法（大写哈希 / 未知字段 / 绝对路径 / 前缀不符）⇒ `ONTOLOGY_REFERENCE_INVALID`。"""
    for bad in (
        {"contentSha256": ONTOLOGY_SHA_A.upper()},
        {"contractId": "SEM-002"},
        {"authoritySource": "/abs/specs/gits-core.owl.ttl"},
        {"authoritySource": "../other-repo/gits-core.owl.ttl"},
        {"authorityRepo": "gits/repo"},
        {"bogus": 1},
    ):
        ws = tmp_path / "ws"
        init_workspace(ws)
        _write_ontology_ws(ws)
        doc = json.loads((schema_dir(ws) / ONTOLOGY_FILENAME).read_text(encoding="utf-8"))
        doc.update(bad)
        (schema_dir(ws) / ONTOLOGY_FILENAME).write_text(
            json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        denied = _build(ws)
        assert isinstance(denied, PlanDenial), f"{bad} 应导致拒绝"
        assert denied.code == "ONTOLOGY_REFERENCE_INVALID", f"{bad} ⇒ {denied.code}"


def test_ontology_denial_codes_are_distinct_from_route_codes(tmp_path: Path):
    """本体拒绝码**不复用**路由既有码（D-4 明确要求）。"""
    ws = tmp_path / "ws"
    init_workspace(ws)
    _write_ontology_ws(ws)
    (schema_dir(ws) / ONTOLOGY_FILENAME).unlink()
    denied = _build(ws)
    assert isinstance(denied, PlanDenial)
    assert denied.code not in {"ROUTE_POLICY_ABSENT", "ROUTE_NOT_MAPPED", "ROUTE_AMBIGUOUS",
                               "ROUTE_MAP_UNKNOWN", "ROUTE_MAP_POLICY_MISMATCH"}


def test_route_denial_takes_precedence_over_ontology(tmp_path: Path):
    """门禁顺序：路由先裁决 ⇒ 路由被拒时**不**因本体缺失而改变归因（默认拒绝归因正确）。"""
    ws = tmp_path / "ws"
    init_workspace(ws)
    _write_ontology_ws(ws)
    (schema_dir(ws) / ONTOLOGY_FILENAME).unlink()
    denied = ActivationPlanBuilder.load(ws).build("UNMAPPED_TASK")
    assert isinstance(denied, PlanDenial)
    assert denied.code == "ROUTE_NOT_MAPPED", denied.code


def test_denied_when_builder_has_no_workspace():
    """未绑定工作区 ⇒ 读不到声明 ⇒ 拒绝（fail-closed 默认值，不静默放行）。"""
    denied = ActivationPlanBuilder(RouteResolver.load(REAL_WS)).build("PRE_VISIT_PREPARATION")
    assert isinstance(denied, PlanDenial)
    assert denied.code == "ONTOLOGY_REFERENCE_ABSENT"


def test_ontology_source_path_not_in_canonical_content():
    """**逐行**校验：canonical content 不得含来源仓名 / 仓内路径 / 绝对路径。"""
    plan = ActivationPlanBuilder.load(REAL_WS).build("PRE_VISIT_PREPARATION")
    assert isinstance(plan, ActivationPlan)
    content = canonical_content(task_type=plan.task_type, policy_key=plan.policy_key,
                                map_key=plan.map_key, assets=plan.assets, skills=plan.skills,
                                ontology_key=plan.ontology_key)
    assert "specs/semantic" not in content
    assert "gits-cbanking" not in content
    assert str(REPO_ROOT) not in content
    assert str(REAL_WS) not in content
    for line in content.splitlines():
        _, _, value = line.partition("=")
        assert not value.startswith("/"), f"疑似环境路径进入 hash 输入: {line}"


def test_plan_hash_is_sensitive_to_ontology_key():
    """反空转：直接对 `compute_plan_hash` 施加本体版本变化（不依赖文件系统）。"""
    base = dict(task_type="T", policy_key="RP-X@1.0.0", map_key="KM-X@1.0.0",
                assets=(PlanAsset("KI-009", True, 1),), skills=("skill-a",))
    h_a = compute_plan_hash(**base, ontology_key=ONTOLOGY_VERSION_A)
    h_none = compute_plan_hash(**base)
    h_b = compute_plan_hash(**base, ontology_key="CTR-SEM-002@sha256:1111111122222222")
    assert len({h_a, h_none, h_b}) == 3
    assert compute_plan_hash(**base, ontology_key=ONTOLOGY_VERSION_A) == h_a
