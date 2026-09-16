"""P12/P13/P14 阶段持久化测试（L4-2）。

重点覆盖 §3.3 的关键不变量：
    「P13 调整证据后，旧报告与新证据之间的确认关系失效；
      系统生成新版本，由 P14 对新版本确认。」
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from kert.infrastructure.stage_store import (  # noqa: E402
    StageStore,
    StageTransitionError,
)


@pytest.fixture()
def store(tmp_path):
    return StageStore(tmp_path / "stage.sqlite")


class TestStageProgression:
    def test_opens_at_p12(self, store):
        s = store.open_session("TASK-1", "SIM-C001", purpose="FINANCE_VISIT_PREP",
                               as_of="2026-09-13")
        assert s.current_stage == "P12"
        assert store.get_session(s.session_id).current_stage == "P12"

    def test_forward_transitions_allowed(self, store):
        s = store.open_session("TASK-1", "SIM-C001")
        store.advance(s.session_id, "P13", reason="缺口已确认", actor="rm-001")
        assert store.get_session(s.session_id).current_stage == "P13"
        store.advance(s.session_id, "P14", reason="证据已装配")
        assert store.get_session(s.session_id).current_stage == "P14"

    def test_skipping_stage_is_rejected(self, store):
        """不得从 P12 直接跳到 P14 —— 三阶段必须按序。"""
        s = store.open_session("TASK-1", "SIM-C001")
        with pytest.raises(StageTransitionError):
            store.advance(s.session_id, "P14")

    def test_backward_from_p14_to_p13_allowed(self, store):
        s = store.open_session("TASK-1", "SIM-C001")
        store.advance(s.session_id, "P13")
        store.advance(s.session_id, "P14")
        store.advance(s.session_id, "P13", reason="证据需补充")
        assert store.get_session(s.session_id).current_stage == "P13"


class TestEvidenceInvalidatesConfirmation:
    """§3.3 的承重不变量。"""

    def test_confirmation_requires_bundle_digest(self, store):
        s = store.open_session("TASK-1", "SIM-C001")
        store.advance(s.session_id, "P13")
        with pytest.raises(StageTransitionError):
            store.confirm_package(s.session_id, package_digest="PKG-1",
                                  bundle_digest="", confirmed_by="rm-001")

    def test_valid_confirmation_passes_check(self, store):
        s = store.open_session("TASK-1", "SIM-C001")
        store.advance(s.session_id, "P13")
        c = store.confirm_package(s.session_id, package_digest="PKG-1",
                                  bundle_digest="BND-A", confirmed_by="rm-001")
        ok, why = store.is_confirmation_valid(c.confirmation_id, "BND-A")
        assert ok, why

    def test_evidence_change_invalidates_confirmation(self, store):
        """证据变更后，既有确认必须失效。"""
        s = store.open_session("TASK-1", "SIM-C001")
        store.advance(s.session_id, "P13")
        c = store.confirm_package(s.session_id, package_digest="PKG-1",
                                  bundle_digest="BND-A", confirmed_by="rm-001")
        assert store.is_confirmation_valid(c.confirmation_id, "BND-A")[0]

        invalidated = store.record_evidence_change(s.session_id, "BND-B",
                                                   actor="rm-001")
        assert c.confirmation_id in invalidated
        # 对**新**证据包无效
        ok, why = store.is_confirmation_valid(c.confirmation_id, "BND-B")
        assert not ok
        assert "失效" in why
        # 回到 P13 重新装配
        assert store.get_session(s.session_id).current_stage == "P13"

    def test_digest_mismatch_detected_even_if_not_invalidated(self, store):
        """即便未走失效流程，摘要值不一致也必须被检出。"""
        s = store.open_session("TASK-1", "SIM-C001")
        store.advance(s.session_id, "P13")
        c = store.confirm_package(s.session_id, package_digest="PKG-1",
                                  bundle_digest="BND-A", confirmed_by="rm-001")
        ok, why = store.is_confirmation_valid(c.confirmation_id, "BND-DIFFERENT")
        assert not ok
        assert "不一致" in why

    def test_reconfirmation_after_change(self, store):
        """变更后由 P14 对新版本重新确认。"""
        s = store.open_session("TASK-1", "SIM-C001")
        store.advance(s.session_id, "P13")
        c1 = store.confirm_package(s.session_id, package_digest="PKG-1",
                                   bundle_digest="BND-A", confirmed_by="rm-001")
        store.record_evidence_change(s.session_id, "BND-B")
        store.advance(s.session_id, "P14")
        c2 = store.confirm_package(s.session_id, package_digest="PKG-2",
                                   bundle_digest="BND-B", confirmed_by="rm-001")
        current = store.confirmations(s.session_id, current_only=True)
        assert [c.confirmation_id for c in current] == [c2.confirmation_id]
        assert store.is_confirmation_valid(c2.confirmation_id, "BND-B")[0]
        assert not store.is_confirmation_valid(c1.confirmation_id, "BND-B")[0]

    def test_transitions_are_traceable(self, store):
        s = store.open_session("TASK-1", "SIM-C001")
        store.advance(s.session_id, "P13", reason="缺口确认完成", actor="rm-001")
        store.advance(s.session_id, "P14", reason="预览确认", actor="rm-001")
        store.record_evidence_change(s.session_id, "BND-B", actor="rm-001")
        tr = store.transitions(s.session_id)
        assert len(tr) >= 3
        assert tr[-1]["to_stage"] == "P13"
        assert "失效" in (tr[-1]["reason"] or "")


class TestStatePersistence:
    def test_record_and_read_stage_state(self, store):
        s = store.open_session("TASK-1", "SIM-C001")
        d = store.record_state(s.session_id, "P12",
                               {"gaps": [{"gapId": "G-1"}], "disposition": "ASK_ON_SITE"},
                               actor="rm-001")
        assert d and len(d) == 64
        back = store.latest_state(s.session_id, "P12")
        assert back["gaps"][0]["gapId"] == "G-1"

    def test_digest_is_canonical(self, store):
        """同一内容不同键序应得同一摘要值（可复现要求）。"""
        s = store.open_session("TASK-1", "SIM-C001")
        d1 = store.record_state(s.session_id, "P13", {"a": 1, "b": [2, 3]})
        d2 = store.record_state(s.session_id, "P13", {"b": [2, 3], "a": 1})
        assert d1 == d2

    def test_schema_version(self, store):
        assert store.schema_version() == 1
