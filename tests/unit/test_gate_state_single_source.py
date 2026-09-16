"""D-28a：gate 语义域**单源化**的机械核对（源 ↔ 生产者 ↔ 展示 ↔ 契约 enum）。

判据：**新增 / 改名一个闸门状态时，四处必须同步** ——
① 源（``service_proposal.GATE_STATE_CSS``）、② 生产者（``_gate_recommendations`` 的产出）、
③ 展示（``report.render_proposal_report`` 的 chip）、④ 契约 enum（``specs/kert-openapi-v1.yaml``）；
任一不同步 ⇒ 本文件**变红**（**防复发**断言，取代"靠人记得同步"）。

另钉一条边界：**未知状态必须显式**（``g-unknown`` + 可见标记），**不得**静默渲染为 pending
（原实现的 ``.get(st, "g-pend")`` 会把新增状态静默画成 pending）。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (str(REPO_ROOT / "src"), str(REPO_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from kert.application import report as report_mod  # noqa: E402
from kert.application.service_proposal import (  # noqa: E402
    GATE_STATE_CSS,
    GATE_STATES,
    OVERALL_BLOCKED,
    OVERALL_READY,
    ST_BLOCKED,
    ST_PASSED,
    ST_PENDING,
    ST_READY_FOR_REVIEW,
    ServiceProposalExecutor,
)

SPEC = REPO_ROOT / "specs" / "kert-openapi-v1.yaml"
REPORT_SRC = REPO_ROOT / "src" / "kert" / "application" / "report.py"
PRODUCER_SRC = REPO_ROOT / "src" / "kert" / "application" / "service_proposal.py"


def _spec_gate_states() -> set[str] | None:
    """从契约 YAML 里取闸门状态 enum（取含 PASSED 的那条 enum 数组）。"""
    if not SPEC.is_file():
        return None
    m = re.search(r"enum:\s*\[([^\]]*PASSED[^\]]*)\]", SPEC.read_text(encoding="utf-8"))
    if not m:
        return None
    return {s.strip() for s in m.group(1).split(",") if s.strip()}


def _producer_states(passed, current, unknowns, customer_version):
    """走**真实生产者路径**取 checklist 状态与 overallReadiness。"""
    ex = ServiceProposalExecutor()
    out = ex._gate_recommendations(
        {"proposalContext": {"gateState": {"passed": passed, "current": current}}},
        unknowns, customer_version)
    return [c["state"] for c in out["checklist"]], out["overallReadiness"]


# --------------------------------------------------------------------------- #
# ① 源自身
# --------------------------------------------------------------------------- #

def test_single_source_is_closed_named_and_self_consistent():
    assert GATE_STATES == ("PASSED", "READY_FOR_REVIEW", "BLOCKED", "PENDING")
    assert set(GATE_STATE_CSS) == set(GATE_STATES)
    assert len(set(GATE_STATE_CSS.values())) == len(GATE_STATE_CSS), "CSS 类必须互异"
    assert (ST_PASSED, ST_READY_FOR_REVIEW, ST_BLOCKED, ST_PENDING) == GATE_STATES
    assert (OVERALL_READY, OVERALL_BLOCKED) == ("READY", "BLOCKED")


# --------------------------------------------------------------------------- #
# ② 生产者
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("unknowns, customer_version, expect_overall", [
    (0, {"version": "v1"}, OVERALL_READY),
    (3, {"version": "v1"}, OVERALL_BLOCKED),
    (0, None, OVERALL_BLOCKED),
])
def test_producer_emits_only_single_source_states(unknowns, customer_version, expect_overall):
    states, overall = _producer_states(["G0"], "G1", unknowns, customer_version)
    assert states and set(states) <= set(GATE_STATES), states
    assert overall in (OVERALL_READY, OVERALL_BLOCKED)


def test_producer_covers_every_state_via_real_path():
    """四态都能由真实路径产出（否则"值域"就是空话）。"""
    seen: set[str] = set()
    for passed, current, unknowns, cust in ((["G0"], "G1", 0, {"v": 1}),
                                            (["G0"], "G1", 3, {"v": 1}),
                                            (["G0"], "G1", 0, None),
                                            (["G0"], "G2", 0, {"v": 1})):
        seen |= set(_producer_states(passed, current, unknowns, cust)[0])
    assert seen == set(GATE_STATES), f"未覆盖: {sorted(set(GATE_STATES) - seen)}"


def test_producer_method_has_no_stray_state_literals():
    """**防复发**：生产者方法体内不得再出现状态字面量（只许用单一源具名常量）。"""
    src = PRODUCER_SRC.read_text(encoding="utf-8")
    method = src.split("def _gate_recommendations", 1)[1].split("def _gate_state", 1)[0]
    strays = [st for st in GATE_STATES if f'"{st}"' in method]
    assert strays == [], f"生产者方法体仍有字面量（须改用单一源常量）: {strays}"


# --------------------------------------------------------------------------- #
# ③ 展示侧
# --------------------------------------------------------------------------- #

def test_display_derives_from_single_source():
    for st in GATE_STATES:
        assert report_mod.gate_state_css(st) == GATE_STATE_CSS[st]
    src = REPORT_SRC.read_text(encoding="utf-8")
    assert '"g-pend"' not in src, "展示侧不得自留 CSS 字面量地图（须派生自单一源）"
    strays = [st for st in GATE_STATES if f'"{st}"' in src]
    assert strays == [], f"展示侧仍出现状态字面量: {strays}"


def test_unknown_state_is_explicit_and_never_rendered_as_pending():
    """未知状态 ⇒ **显式** ``g-unknown`` + 可见标记；**不得**静默当 pending。"""
    assert report_mod.gate_state_css("BRAND_NEW") == report_mod.UNKNOWN_STATE_CSS
    assert report_mod.UNKNOWN_STATE_CSS != GATE_STATE_CSS["PENDING"]

    payload = {"data": {"result": {
        "content": {},
        "gateRecommendations": {"currentGate": "G1", "overallReadiness": OVERALL_BLOCKED,
                                "checklist": [{"gate": "G9", "state": "BRAND_NEW"}]},
    }}}
    html = report_mod.render_proposal_report(None, payload)
    assert 'class="gate g-unknown"' in html
    assert 'class="gate g-pend"' not in html, "未知状态被静默渲染成 pending"
    assert "G9:BRAND_NEW（未知状态）" in html


# --------------------------------------------------------------------------- #
# ④ 契约 enum + 防复发（三处必须同步）
# --------------------------------------------------------------------------- #

def test_spec_contract_enum_matches_single_source():
    spec_states = _spec_gate_states()
    assert spec_states is not None, (
        f"未在 {SPEC.name} 找到闸门状态 enum（D-28a 要求契约侧可见；若契约正在改动，请在此处同步）")
    assert spec_states == set(GATE_STATES), f"契约 enum 与单一源不一致: {sorted(spec_states)}"


def test_adding_a_state_forces_syncing_everywhere():
    """**防复发机制**：向单一源临时加一个状态 ⇒ 展示侧**自动**派生（证明无第二份地图），
    而**契约 enum 会立刻不一致**（证明"新增必须四处同步"，不会静默放过）。"""
    injected = "NEW_STATE_FOR_TEST"
    GATE_STATE_CSS[injected] = "g-new"
    try:
        assert report_mod.gate_state_css(injected) == "g-new", "展示侧应自动派生（无第二份地图）"
        spec_states = _spec_gate_states()
        assert spec_states is not None
        assert spec_states != set(GATE_STATE_CSS), "契约 enum 应立刻显现不同步 ⇒ 用例变红"
    finally:
        GATE_STATE_CSS.pop(injected, None)
