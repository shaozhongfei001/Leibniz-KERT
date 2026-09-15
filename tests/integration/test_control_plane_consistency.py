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
from kert.domain.workspace import init_workspace  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "examples" / "bank-front-knowledge-maps"
CUSTOMER_ID = "CUST-CORP-0001"
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")

#: skill_id -> (taskType, request)。请求须能让技能走到"逐 KI 记录"那一步。
SKILL_CASES = {
    "skill-customer-outreach-script": ("OUTREACH_PREPARATION", {"customerId": CUSTOMER_ID}),
    "skill-customer-meeting-script": ("MEETING_PREPARATION", {"customerId": CUSTOMER_ID}),
    "skill-customer-previsit-report": (
        "PRE_VISIT_PREPARATION",
        {"customerId": CUSTOMER_ID, "evidenceTimestamp": "2026-08-22T10:00:00Z"},
    ),
}


def _declared_assets(task: str) -> tuple[str, str, set[str]]:
    """受控控制面里唯一声明该任务的地图 → (mapId, version, assetIds)。"""
    registry = KnowledgeMapRegistry.load(SOURCE)
    hits = [m for m in registry.maps if task in m.tasks]
    assert len(hits) == 1, f"任务 {task} 应由**恰好一张**地图声明，实际 {[m.map_id for m in hits]}"
    m = hits[0]
    return m.map_id, m.version, {a.asset_id for a in m.asset_refs}


def _skill_reads(ws: Path, skill_id: str, request: dict) -> set[str]:
    """**技能自己产出的 trace** 里出现过的 kiId 集合 = 技能实际读取集。"""
    svc = SkillExecutionService(ws)
    r = svc.execute(skill_id, f"cc-{skill_id}", request)
    return {t["kiId"] for t in r.assembly_trace if t.get("kiId")}


@pytest.mark.parametrize("skill_id", sorted(SKILL_CASES))
def test_map_assets_equal_skill_reads(ws_provisioned, skill_id):
    """地图 `assetRefs` 必须**逐条等于**技能实际读取集。"""
    task, request = SKILL_CASES[skill_id]
    map_id, version, declared = _declared_assets(task)
    read = _skill_reads(ws_provisioned, skill_id, request)

    # 反空转：trace 机制若失效（不再产出 kiId），本用例必须失败而不是"空集相等"而空过
    assert read, f"{skill_id} 未产出任何 kiId（trace 机制失效？）——核对不可空过"

    assert declared == read, (
        f"{map_id}@{version} 声明的资产集与 {skill_id} 实际读取集不一致\n"
        f"  仅地图声明: {sorted(declared - read)}\n"
        f"  仅技能读取: {sorted(read - declared)}\n"
        f"→ 修的是**地图定义**（或技能实现），不是本测试"
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


def test_all_three_maps_are_covered():
    """三张地图都必须落进本核对（新增地图/技能时不能漏网）。"""
    registry = KnowledgeMapRegistry.load(SOURCE)
    declared_tasks = {t for m in registry.maps for t in m.tasks}
    covered = {task for task, _ in SKILL_CASES.values()}
    assert declared_tasks == covered, (
        f"控制面声明的任务 {sorted(declared_tasks)} 与已核对任务 {sorted(covered)} 不一致"
        "（新增地图/技能须同步加入 SKILL_CASES）"
    )
