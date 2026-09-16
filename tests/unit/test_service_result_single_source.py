"""D-28 层 2 第五片：**服务结果状态域**（`SUCCESS`/`PARTIAL`）单源核对。

分工：

- **源** = ``kert.domain.service_result``（`SERVICE_RESULT_STATES` + 具名常量）—— 本文件 ①；
- **产生点** = `service_proposal._run_service_proposal`（SP-20）、
  `interaction_memory._run_interaction_memory`（SP-21）—— 本文件 ②（**两条真实路径**）；
- **合同** = **两个** enum（`ServiceResult.status` / `InteractionMemoryResult.status`）——
  由 `test_contract_enum_single_source.py` 的 `MAPPINGS` 核对（**一个源、两行**）。

⚠ **跨域映射（本片重点）**：两处产生点把域值映射到**轨迹条目域**（`ok`/`failed`）作 compose 留痕。
本文件的 ② 把「域值 + 映射结果」**成对**钉住 ⇒ 域值改一个字母即红；而映射的**目标端**属轨迹域，
与本域相交不等、**不得合并**（禁止把 `failed`/`blocked`/`skipped` 塞进本域）。

⚠ 边界：`infrastructure/adapters/sim_bank_front.py` 的 `status_map`（`SUCCESS/PARTIAL/NOT_RUN`，
**coverageStatus 域**，模拟上游判定表）值重叠、域不同 ⇒ 不得合并（本文件 ④）。
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (str(REPO_ROOT / "src"), str(REPO_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from kert.application.skills import SkillExecutionService  # noqa: E402
from kert.domain.service_result import (  # noqa: E402
    SERVICE_PARTIAL,
    SERVICE_RESULT_STATES,
    SERVICE_SUCCESS,
)

PRODUCER_SRCS = {
    "service_proposal.py": REPO_ROOT / "src" / "kert" / "application" / "service_proposal.py",
    "interaction_memory.py": REPO_ROOT / "src" / "kert" / "application" / "interaction_memory.py",
}
ADAPTER_SRC = (REPO_ROOT / "src" / "kert" / "infrastructure" / "adapters"
               / "sim_bank_front.py")

SP20_CTX = {
    "schemaVersion": "1.0.0", "customerId": "CUST-CORP-0001",
    "customerName": "华东精工装备集团有限公司", "industry": "制造业-装备制造",
    "engagementPhase": "FIRST_CONTACT", "journeyId": "J-1", "operatingCaseId": "OC-1",
    "roundNumber": 1,
    "proposalContext": {"proposalType": "INITIAL",
                        "gateState": {"passed": ["G0"], "current": "G1"}},
}
SP21_CTX = {
    "interactionId": "INT-20260823-001",
    "interactionContent": (
        "今日拜访华东精工财务总监与 CFO，对方表示 Q4 有采购计划，预算约 5000 万，"
        "偏好面对面沟通，正在考虑更换主办行；CFO 表示新授信方案需董事会审批。"),
    "existingMemories": [
        {"memoryId": "MEM-OLD-001", "category": "BUSINESS_SIGNAL",
         "content": "客户Q4有采购计划，预算约5000万", "confidence": 0.6},
        {"memoryId": "MEM-OLD-002", "category": "PREFERENCE",
         "content": "CFO 是关键决策人", "confidence": 0.9},
    ],
}


def _compose_entry(trace: list[dict]) -> dict:
    """取**规则校验**那条 compose 留痕（文件内存在同名 phase 的其它留痕 ⇒ 必须按 message 定位）。"""
    hits = [t for t in trace
            if t.get("phase") == "compose" and str(t.get("message", "")).startswith("规则校验")]
    assert len(hits) == 1, hits
    return hits[0]


# --------------------------------------------------------------------------- #
# ① 源自身
# --------------------------------------------------------------------------- #

def test_source_is_closed_ordered_and_named():
    assert SERVICE_RESULT_STATES == ("SUCCESS", "PARTIAL")
    assert (SERVICE_SUCCESS, SERVICE_PARTIAL) == SERVICE_RESULT_STATES
    assert len(set(SERVICE_RESULT_STATES)) == len(SERVICE_RESULT_STATES)


# --------------------------------------------------------------------------- #
# ② 两条真实路径：域值 + 跨域映射结果**成对**钉住
# --------------------------------------------------------------------------- #

def test_sp21_real_path_is_success_and_maps_to_trace_ok(ws_provisioned):
    r = SkillExecutionService(ws_provisioned).execute("SP-21", "srs-sp21-1", {"context": SP21_CTX})
    assert r.status == "ok", r.errors
    res = r.data["result"]
    # 域值：字面量 + 常量**双钉**（只钉常量的话，源与产出会一起变 ⇒ 变异不可见）
    assert res["status"] == "SUCCESS" == SERVICE_SUCCESS, res["status"]
    # 映射结果（**轨迹条目域**的字面量）：本域与轨迹域不得合并
    assert _compose_entry(r.assembly_trace)["status"] == "ok"


def test_sp20_real_path_is_partial_and_maps_to_trace_failed(ws_provisioned):
    r = SkillExecutionService(ws_provisioned).execute("SP-20", "srs-sp20-1", {"context": SP20_CTX})
    assert r.status == "ok", r.errors
    res = r.data["result"]
    assert res["status"] == "PARTIAL" == SERVICE_PARTIAL, res["status"]
    assert _compose_entry(r.assembly_trace)["status"] == "failed"


def test_domain_value_and_mapping_are_consistent_on_real_paths(ws_provisioned):
    """不变量：映射恰由**源常量比较**决定（`ok` ⟺ 域值 == `SERVICE_SUCCESS`）。

    两件事都在本用例里钉：①两条真实路径的「域值 → 映射结果」自洽；
    ②映射的**判据端**必须**引用单一源常量**（写死字面量 ⇒ 本用例红，不必等到行为跑偏）。
    """
    for name, path in PRODUCER_SRCS.items():
        text = path.read_text(encoding="utf-8")
        assert "status == SERVICE_SUCCESS" in text, (
            f"{name} 的跨域映射未引用命名源常量（写死 ⇒ 改名会静默把留痕变成 failed）")

    svc = SkillExecutionService(ws_provisioned)
    for sid, rid, ctx in (("SP-20", "srs-inv-20", SP20_CTX), ("SP-21", "srs-inv-21", SP21_CTX)):
        r = svc.execute(sid, rid, {"context": ctx})
        res = r.data["result"]
        expected = "ok" if res["status"] == SERVICE_SUCCESS else "failed"
        assert _compose_entry(r.assembly_trace)["status"] == expected, (sid, res["status"])
        assert res["status"] in SERVICE_RESULT_STATES, res["status"]


# --------------------------------------------------------------------------- #
# ③ 防复发：产生点不得再散落域字面量
# --------------------------------------------------------------------------- #

def test_producers_have_no_stray_status_literals():
    patterns = ('status = "SUCCESS"', 'status = "PARTIAL"', '"SUCCESS" if',
                '== "SUCCESS"', 'else "PARTIAL"')
    for name, path in PRODUCER_SRCS.items():
        text = path.read_text(encoding="utf-8")
        hits = [p for p in patterns if p in text]
        assert hits == [], f"{name} 仍有域字面量：{hits}"
        assert "SERVICE_SUCCESS" in text and "SERVICE_PARTIAL" in text, (
            f"{name} 未引用命名源常量")


# --------------------------------------------------------------------------- #
# ④ 相邻域边界（禁止合并）
# --------------------------------------------------------------------------- #

def test_coverage_status_domain_is_not_merged():
    """模拟上游的 `coverageStatus` 域（`SUCCESS/PARTIAL/NOT_RUN`）与本域**值重叠、域不同**。"""
    assert "NOT_RUN" not in SERVICE_RESULT_STATES
    src = ADAPTER_SRC.read_text(encoding="utf-8")
    assert "service_result" not in src, "coverageStatus 域不得依赖本域（防误合并）"
