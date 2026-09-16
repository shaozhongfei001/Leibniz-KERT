"""D-28 层 2 第四片：**技能执行状态域**的单源核对（源 ↔ 生产者 ↔ 合同 ↔ 域边界）。

三处分工（**不重复钉同一条**）：

- **源** = ``kert.domain.skill_status.SKILL_EXECUTION_STATES`` —— 本文件 ①；
- **生产者（真实路径）** = `SkillExecutionService.execute` 的三个分支 + `api/server.py` 的
  **按名比较**分支（决定 404/200）—— 本文件 ②③；
- **合同** = `SkillExecuteResponse.status`（等值）/ `SkillExecuteErrorResponse.status`、
  `ErrorResponse.status`（具名登记子集）—— 由
  `tests/unit/test_contract_enum_single_source.py` 的 ``MAPPINGS`` + ``SUBSET_DECLARATIONS`` 核对；
  内部 JSON 合同（`docs/contracts/schemas/skill-execute-response.schema.json`，受
  `scripts/contract_bundle_hash.py` 哈希闸门保护 ⇒ **只读**）—— 本文件 ④。

⚠ 边界：`assemblyTrace` **条目**状态域（`ok/failed/blocked/skipped/degraded`）**不是**本域 ⇒ 本文件 ⑤。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (str(REPO_ROOT / "src"), str(REPO_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from kert.application.skills import SkillExecutionService  # noqa: E402
from kert.domain.skill_status import (  # noqa: E402
    EXIT_POLICY_NO_NEW_EVIDENCE,
    SKILL_ERROR,
    SKILL_EXECUTION_STATES,
    SKILL_OK,
)

SKILLS_SRC = REPO_ROOT / "src" / "kert" / "application" / "skills.py"
SP15_SRC = REPO_ROOT / "src" / "kert" / "application" / "product_recommendation" / "sp15_skill.py"
SERVER_SRC = REPO_ROOT / "src" / "kert" / "api" / "server.py"
TRACE_SCHEMA = REPO_ROOT / "docs" / "contracts" / "schemas" / "assembly-trace.schema.json"
INTERNAL_SCHEMA = REPO_ROOT / "docs" / "contracts" / "schemas" / "skill-execute-response.schema.json"

CUSTOMER_ID = "CUST-CORP-0001"


# --------------------------------------------------------------------------- #
# ① 源自身
# --------------------------------------------------------------------------- #

def test_source_is_closed_ordered_and_named():
    assert SKILL_EXECUTION_STATES == ("ok", "skill_error", "exit_policy_no_new_evidence")
    assert (SKILL_OK, SKILL_ERROR, EXIT_POLICY_NO_NEW_EVIDENCE) == SKILL_EXECUTION_STATES
    assert len(set(SKILL_EXECUTION_STATES)) == len(SKILL_EXECUTION_STATES), "值域必须互异"


# --------------------------------------------------------------------------- #
# ② 三态的真实产生路径（每态一个字节钉子）
# --------------------------------------------------------------------------- #

def test_state_ok_via_real_execution(ws_provisioned):
    r = SkillExecutionService(ws_provisioned).execute(
        "skill-customer-outreach-script", "ss-ok-1", {"customerId": CUSTOMER_ID})
    assert r.status == SKILL_OK, (r.status, r.errors)
    assert r.as_dict()["status"] == "ok", "立源是零行为变化：产出字节必须不变"


def test_state_skill_error_via_unknown_skill(ws_provisioned):
    r = SkillExecutionService(ws_provisioned).execute("NO-SUCH-SKILL", "ss-err-1", {})
    assert r.status == SKILL_ERROR, r.status
    assert r.status == "skill_error", "立源是零行为变化：产出字节必须不变"
    assert r.errors[0]["code"] == "UNKNOWN_SKILL", r.errors


def test_state_exit_policy_via_missing_evidence_timestamp(ws_provisioned):
    """R1 缺 `evidenceTimestamp` ⇒ 在**取数之前**被无新证据策略拦截（该值唯一产生点）。"""
    r = SkillExecutionService(ws_provisioned).execute(
        "skill-customer-previsit-report", "ss-pol-1", {"customerId": CUSTOMER_ID})
    assert r.status == EXIT_POLICY_NO_NEW_EVIDENCE, (r.status, r.errors)
    assert r.status == "exit_policy_no_new_evidence", "立源是零行为变化：产出字节必须不变"


def test_every_state_is_reachable_through_the_public_entry(ws_provisioned):
    """三态**都**能由真实入口产出（否则"值域"就是空话；防空转）。"""
    svc = SkillExecutionService(ws_provisioned)
    seen = {
        svc.execute("skill-customer-outreach-script", "ss-all-1",
                    {"customerId": CUSTOMER_ID}).status,
        svc.execute("NO-SUCH-SKILL", "ss-all-2", {}).status,
        svc.execute("skill-customer-previsit-report", "ss-all-3",
                    {"customerId": CUSTOMER_ID}).status,
    }
    assert seen == set(SKILL_EXECUTION_STATES), f"未覆盖: {sorted(set(SKILL_EXECUTION_STATES) - seen)}"


# --------------------------------------------------------------------------- #
# ③ `api/server.py` 的**按名比较**分支（取值集合一字未变的证据面）
# --------------------------------------------------------------------------- #

def test_api_branch_still_fires_on_the_named_value(ws_provisioned):
    """未知技能 ⇒ **404**（该状态码由 `result.status == SKILL_ERROR` 分支决定）；
    正常 ⇒ 200 且 `status` 落在源内。分支的**比较取值集合**由 ① 的字节钉子（`SKILL_ERROR ==
    "skill_error"`）机械固定 ⇒ 本用例证明"改了常量、行为未变"。"""
    from kert.api.server import create_app

    client = TestClient(create_app(ws_provisioned, service_id="product_knowledge"))
    bad = client.post("/api/skill/execute", json={
        "skillId": "NO-SUCH-SKILL", "requestId": "ss-api-404", "request": {}})
    assert bad.status_code == 404, bad.text[:200]
    assert bad.json()["status"] == SKILL_ERROR

    good = client.post("/api/skill/execute", json={
        "skillId": "skill-customer-outreach-script", "requestId": "ss-api-200",
        "request": {"customerId": CUSTOMER_ID}})
    assert good.status_code == 200, good.text[:200]
    assert good.json()["status"] in SKILL_EXECUTION_STATES


# --------------------------------------------------------------------------- #
# ④ 内部 JSON 合同（只读核对；该文件受哈希闸门保护，**不改**）
# --------------------------------------------------------------------------- #

def test_internal_contract_schema_matches_the_source():
    spec = json.loads(INTERNAL_SCHEMA.read_text(encoding="utf-8"))
    assert spec["properties"]["status"]["enum"] == list(SKILL_EXECUTION_STATES), (
        "内部合同 schema 的 status 值域与命名源不一致（该文件受 contract_bundle_hash 保护："
        "改它需同步哈希，属另一动作）")


# --------------------------------------------------------------------------- #
# ⑤ 域边界 + 防复发
# --------------------------------------------------------------------------- #

def test_trace_status_domain_is_not_merged():
    """轨迹条目状态域与技能执行状态域取值集合**不相等** ⇒ 禁止合并（两处都有 `"ok"`）。"""
    trace_statuses = set(json.loads(TRACE_SCHEMA.read_text(encoding="utf-8"))
                         ["properties"]["status"]["enum"])
    assert trace_statuses != set(SKILL_EXECUTION_STATES), "两域取值集合相同 ⇒ 请重新裁定归属"
    assert not (set(SKILL_EXECUTION_STATES) & {"failed", "blocked", "skipped", "degraded"}), (
        "技能执行状态域不得吞并轨迹条目域取值")


def _stray_in_construction(src: str, marker: str, window: int = 200) -> list[str]:
    """在 ``marker(...)`` 的**构造窗口**内查技能状态域字面量（`status="…"`）。

    ⚠ 为什么不能全文件查 `status="ok"`：**轨迹条目域**用的是同一 kwarg 形态
    （``self._source_entry(..., status="ok")``，`skills.py:698`）⇒ 全文件查会**误伤异域**。
    按"构造目标"定位才是本域的判据。
    """
    strays: set[str] = set()
    for chunk in src.split(marker)[1:]:
        snippet = chunk[:window]
        strays |= {st for st in SKILL_EXECUTION_STATES if f'status="{st}"' in snippet}
    return sorted(strays)


def test_producers_have_no_stray_status_literals():
    """**防复发**：三处生产者不得再出现**技能状态域**的字面量（只许用命名源常量）。"""
    skills_src = SKILLS_SRC.read_text(encoding="utf-8")
    assert "SkillExecuteResult(" in skills_src, "构造点改名 ⇒ 请同步本用例"
    strays = _stray_in_construction(skills_src, "SkillExecuteResult(")
    assert strays == [], f"skills.py 的 SkillExecuteResult 构造仍有字面量：{strays}"

    sp15_src = SP15_SRC.read_text(encoding="utf-8")
    assert "Sp15ExecutionResult(" in sp15_src, "构造点改名 ⇒ 请同步本用例"
    strays15 = _stray_in_construction(sp15_src, "Sp15ExecutionResult(")
    assert strays15 == [], f"sp15_skill.py 的 Sp15ExecutionResult 构造仍有字面量：{strays15}"

    server_src = SERVER_SRC.read_text(encoding="utf-8")
    api_hits = [p for p in ('"status": "skill_error"',
                            '"status": "exit_policy_no_new_evidence"',
                            '== "skill_error"',
                            '== "exit_policy_no_new_evidence"')
                if p in server_src]
    assert api_hits == [], f"server.py 仍有技能状态域字面量（含按名比较分支）：{api_hits}"
