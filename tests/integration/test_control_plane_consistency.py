"""控制面 ↔ 技能实现一致性（**机械核对**，M7.3 第五步 P1）。

存在理由（真实事故）：`KM-CORP-RM-PREVISIT` 曾只声明 3 条资产，而 `_run_previsit`
实际遍历全部 7 条 `KI_ITEMS`；地图 `notes` 还**自称一致**——该缺陷逃过了当时全部测试，
因为唯一相关用例（`test_activation_plan.py` 的 `REAL_TASKS`）只断言**地图自己**的资产数，
是自证一致，不构成核对。

本文件把"一致"变成**可执行事实**：取**技能自己产出的 trace**（`kiId` 序列）作为
"技能实际读取集"，与地图 `assetRefs` 比对。任一侧改动而另一侧没跟 ⇒ 变红。

范围与口径：
- 仅覆盖"受治理内容"（assets）；`title`/`notes` 等说明性字段不参与版本与核对；
- 地图**受治理内容**变更 ⇒ **必须升版本**（否则两份不同内容共用一个版本号，
  版本合同失效，plan hash 也就失去可追溯性）；
- 资产集相同但仅说明性字段变化 ⇒ 不需要升版本。
"""

from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from kert.application.provision import provision_control_plane  # noqa: E402
from kert.application.skills import SkillExecutionService  # noqa: E402
from kert.domain.knowledge_map import KnowledgeMapRegistry  # noqa: E402
from kert.domain.route_policy import load_route_policy  # noqa: E402
from kert.domain.workspace import init_workspace  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "examples" / "bank-front-knowledge-maps"
SKILL_PKGS = ROOT / "examples" / "bank-front-skills"
CUSTOMER_ID = "CUST-CORP-0001"
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")

#: SP-15 最小合法 context（与 tests/integration/test_sp15_skill_registration.py 同口径）。
SP15_MINIMAL_CONTEXT = {
    "schemaVersion": "1.0.0",
    "customerId": CUSTOMER_ID,
    "needVersionIds": ["NEEDV-001"],
    "recommendationObjective": "补充流动资金与跨境结算方案",
    "asOf": "2026-09-15T09:00:00+08:00",
    "customerFactSnapshotId": "CFS-CUST-CORP-0001",
    "productKnowledgeSnapshotRef": "PKS-20260831-0001",
    "ruleBundleRef": "RB-20260831-0001",
    "permissionDecisionId": "PERM-20260831-0001",
}

#: SP-20 最小合法 context（执行器要求 context.enterpriseData，缺即 fail-closed）。
SP20_MINIMAL_CONTEXT = {
    "customerId": CUSTOMER_ID,
    "customerName": "华东精工装备集团有限公司",
    "industry": "制造业-装备制造",
    "engagementPhase": "ACTIVE_ENGAGEMENT",
    "enterpriseData": {"basicInfo": {}, "financialSummary": {}},
}

#: SP-21 最小合法 context（要求 interactionId + interactionContent）。
SP21_MINIMAL_CONTEXT = {
    "customerId": CUSTOMER_ID,
    "interactionId": "INT-CC-0001",
    "interactionContent": "客户对供应链融资产品表示兴趣，希望了解授信额度和利率",
}

#: skill_id -> (taskType, request)。请求须能让技能执行到产出 trace 那一步。
#: M7 ② 起本表覆盖**全部 7 个受门禁技能**（此前只有 3 个 customer-engagement 技能）。
SKILL_CASES = {
    "skill-customer-outreach-script": ("OUTREACH_PREPARATION", {"customerId": CUSTOMER_ID}),
    "skill-customer-meeting-script": ("MEETING_PREPARATION", {"customerId": CUSTOMER_ID}),
    "skill-customer-previsit-report": (
        "PRE_VISIT_PREPARATION",
        {"customerId": CUSTOMER_ID, "evidenceTimestamp": "2026-08-22T10:00:00Z"},
    ),
    "bank-front-supply-chain-graph": (
        "SUPPLY_CHAIN_GRAPH_ANALYSIS", {"customerId": CUSTOMER_ID}),
    "SP-15": ("PRODUCT_RECOMMENDATION_DECISION", {"context": SP15_MINIMAL_CONTEXT}),
    "SP-20": ("SERVICE_PROPOSAL_PREPARATION", {"context": SP20_MINIMAL_CONTEXT}),
    "SP-21": ("INTERACTION_MEMORY_EXTRACTION", {"context": SP21_MINIMAL_CONTEXT}),
}

#: **按计划读受治理知识资产**的技能：其地图 ``assetRefs`` 必须非空且等于 trace 读到的 kiId 集合。
#: 其余技能的读取集**为空**（来源是技能包目录 / 请求 context，不经控制面）——那也是必须被
#: 机械钉住的事实：一旦它们开始读 KI，本文件会红（地图没跟着改，或该技能没被移入本集合）。
KI_READING_SKILLS = frozenset({
    "skill-customer-outreach-script",
    "skill-customer-meeting-script",
    "skill-customer-previsit-report",
    "bank-front-supply-chain-graph",
})

#: **独立腿（不可省）**：各 KI 读取型技能**应有**的资产声明。
#:
#: 为什么需要它（实测教训）：M7 ② 把供应链技能也改成"按计划读资产"之后，
#: 「``declared == trace``」变成**结构必然**——技能读的就是地图给的那些，地图少声明时
#: trace 会**跟着少**，相等断言照样绿（变异实测：删掉供应链地图的 ``KI-FRONT-003``
#: 声明，本文件依然全绿）。故必须有一条**独立于地图与 trace**的人名级期望：
#: 「地图少声明 ⇒ 技能真的少拿资产」这件事，只能由它发现。
#:
#: 出处在各技能实现与其读取的知识条目：
#: - 三个 customer-engagement 技能：``skills.py`` 的 ``_run_*`` + 客户知识库取数；
#: - 供应链：``_run_supply_chain`` 的三条 trace + ``customer_knowledge.interpretation()``
#:   （``supplyChainPosition`` 取 KI-FRONT-002、``keyChanges`` 取 KI-FRONT-003）。
KI_EXPECTED_ASSETS: dict[str, set[str]] = {
    "skill-customer-outreach-script": {"KI-009", "KI-FRONT-004", "KI-FRONT-006"},
    "skill-customer-meeting-script": {"KI-009", "KI-FRONT-004", "KI-FRONT-005", "KI-FRONT-006"},
    "skill-customer-previsit-report": {
        "KI-009", "KI-FRONT-001", "KI-FRONT-002", "KI-FRONT-003",
        "KI-FRONT-004", "KI-FRONT-005", "KI-FRONT-006"},
    "bank-front-supply-chain-graph": {"KI-FRONT-001", "KI-FRONT-002", "KI-FRONT-003"},
}


def _declared_assets(task: str) -> tuple[str, str, set[str]]:
    """受控控制面里唯一声明该任务的地图 → (mapId, version, assetIds)。"""
    registry = KnowledgeMapRegistry.load(SOURCE)
    hits = [m for m in registry.maps if task in m.tasks]
    assert len(hits) == 1, f"任务 {task} 应由**恰好一张**地图声明，实际 {[m.map_id for m in hits]}"
    m = hits[0]
    return m.map_id, m.version, {a.asset_id for a in m.asset_refs}


def _skill_reads(ws: Path, skill_id: str, request: dict) -> set[str]:
    """**技能自己产出的 trace** 里出现过的 kiId 集合 = 技能实际读取集。

    技能包目录**显式注入**（不依赖 ``KERT_SKILL_PACKAGES`` 环境变量）：外部技能包未加载时
    ``bank-front-supply-chain-graph`` 会是 ``UNKNOWN_SKILL``，核对会**空过**——
    那是"测试环境没装技能"而不是"技能不读知识"，必须排除。
    """
    svc = SkillExecutionService(ws, skill_packages=SKILL_PKGS)
    r = svc.execute(skill_id, f"cc-{skill_id}", request)
    assert r.status == "ok", f"{skill_id} 执行未成功：{r.status} {r.errors}"
    return {t["kiId"] for t in r.assembly_trace if t.get("kiId")}


@pytest.mark.parametrize("skill_id", sorted(SKILL_CASES))
def test_map_assets_equal_skill_reads(ws_provisioned, skill_id):
    """地图 `assetRefs` 必须**逐条等于**技能实际读取集。"""
    task, request = SKILL_CASES[skill_id]
    map_id, version, declared = _declared_assets(task)
    read = _skill_reads(ws_provisioned, skill_id, request)

    if skill_id in KI_READING_SKILLS:
        # 反空转：trace 机制若失效（不再产出 kiId），本用例必须失败而不是"空集相等"而空过
        assert read, f"{skill_id} 未产出任何 kiId（trace 机制失效？）——核对不可空过"
    else:
        # 非 KI 读取型：空是**有意**的，且必须两向都空（下一条 declared == read 再兜一次）
        assert not read, (
            f"{skill_id} 竟然读到了控制面知识资产 {sorted(read)}——"
            "要么同步地图 assetRefs，要么把它移入 KI_READING_SKILLS（不得静默）")

    assert declared == read, (
        f"{map_id}@{version} 声明的资产集与 {skill_id} 实际读取集不一致\n"
        f"  仅地图声明: {sorted(declared - read)}\n"
        f"  仅技能读取: {sorted(read - declared)}\n"
        f"→ 修的是**地图定义**（或技能实现），不是本测试"
    )


def test_expected_assets_table_covers_exactly_the_ki_reading_skills():
    """防空转：期望表必须**恰好**覆盖 KI 读取型技能集合（新增读取型技能须同步登记）。"""
    assert set(KI_EXPECTED_ASSETS) == set(KI_READING_SKILLS), (
        f"期望表 {sorted(KI_EXPECTED_ASSETS)} 与 KI 读取型技能集合 "
        f"{sorted(KI_READING_SKILLS)} 不一致")
    assert all(KI_EXPECTED_ASSETS[s] for s in KI_EXPECTED_ASSETS), "期望表不得有空集"


@pytest.mark.parametrize("skill_id", sorted(KI_READING_SKILLS))
def test_ki_reading_maps_declare_the_expected_assets(skill_id):
    """**独立腿**：地图必须声明"该技能真正需要"的资产集（人名级期望，见表中出处）。

    这条与 ``declared == trace`` **互补**：后者在计划驱动之后是结构必然，发现不了
    "地图少声明 ⇒ 技能少拿资产"；本条独立钉住期望值，少一份即红。
    """
    task, _ = SKILL_CASES[skill_id]
    map_id, version, declared = _declared_assets(task)
    expected = KI_EXPECTED_ASSETS[skill_id]
    assert declared == expected, (
        f"{map_id}@{version} 的 assetRefs 与期望不一致\n"
        f"  地图多出（技能并不需要）: {sorted(declared - expected)}\n"
        f"  地图缺少（技能真的会少拿）: {sorted(expected - declared)}\n"
        f"→ 修的是**地图定义**（或同步更新本表并写明出处），不是放松断言"
    )


@pytest.mark.parametrize("skill_id", sorted(SKILL_CASES))
def test_declared_map_version_is_semver(skill_id):
    """版本号须为 semver 形态（保证 planHash 的版本可追溯性）。"""
    task, _ = SKILL_CASES[skill_id]
    _, version, _ = _declared_assets(task)
    assert SEMVER_RE.match(version), version


def test_plan_drives_reads_not_source_literals(tmp_path: Path):
    """**(A) 的核心证明**：改地图的 ``assetRefs`` ⇒ 技能读取集**随之改变**。

    ⑤b-full 之后，"地图 == 技能读取"在受控工作区上是**结构必然**（技能读的就是计划给的
    资产），故单靠相等断言**无法证明"读取来源是计划"**。必须**改动地图**并观察技能跟随：
    若实现里仍残留源码字面量（例如又加回一句硬编码 ``_trace_ki``），本用例变红。

    这也是 M1 缺陷（地图少声明资产）在 ⑤b-full 之后的**新防线**：那时"少声明"不再意味
    技能多读，而是意味**控制面真的少给资产**——那属于控制面治理，由本用例保证它会被如实执行。
    """
    src = tmp_path / "src"
    shutil.copytree(SOURCE, src)
    p = src / "90_control" / "catalog" / "KM-CORP-RM-OUTREACH.json"
    doc = json.loads(p.read_text(encoding="utf-8"))
    doc["assetRefs"] = [
        {"assetId": "KI-FRONT-002", "required": True, "sequence": 1},  # 原声明集**之外**的资产
        {"assetId": "KI-009", "required": True, "sequence": 2},
    ]
    p.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")

    ws = tmp_path / "ws"
    init_workspace(ws)
    provision_control_plane(ws, src)

    read = _skill_reads(ws, "skill-customer-outreach-script", {"customerId": CUSTOMER_ID})
    assert read == {"KI-FRONT-002", "KI-009"}, (
        f"技能读取集未跟随地图变化 ⇒ 仍存在源码字面量来源：{sorted(read)}")


def test_all_declared_maps_are_covered():
    """**三侧同源**：地图声明 / 策略规则 / 已核对技能，三者的任务集合必须完全一致。

    任一新增（地图、规则或纳入门禁的技能）而另两侧没跟上 ⇒ 变红，防止漏网。
    """
    registry = KnowledgeMapRegistry.load(SOURCE)
    policy = load_route_policy(SOURCE)
    assert policy is not None, "受控源必须存在路由策略（本一致性核对的共同前提）"

    declared_tasks = {t for m in registry.maps for t in m.tasks}
    rule_tasks = {r.task_type for r in policy.rules}
    covered = {task for task, _ in SKILL_CASES.values()}

    assert declared_tasks == covered, (
        f"地图声明的任务 {sorted(declared_tasks)} 与已核对任务 {sorted(covered)} 不一致"
        "（新增地图/技能须同步加入 SKILL_CASES）"
    )
    assert rule_tasks == covered, (
        f"策略规则的任务 {sorted(rule_tasks)} 与已核对任务 {sorted(covered)} 不一致"
        "（新增规则/技能须同步加入 SKILL_CASES；漏掉的技能会绕过门禁）"
    )
    assert len(covered) == 7, f"受门禁技能应为 7 个，实际 {len(covered)}"
