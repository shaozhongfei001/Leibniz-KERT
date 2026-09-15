"""⑤b-light：技能 trace 反映**解析出的**路由（可观测性接线，M7.3 第五步 b）。

范围声明：本步**不改变**技能读取哪些知识条目（那是 ⑤b-full）；只把"技能进了哪张地图"
从硬编码叙述变成**可核验事实** —— trace 记录解析出的地图 + 版本快照 + planHash，
与 ``/v1/routing/plan`` 同源同值；拒绝或失配时**一律不回落**到硬编码。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import jsonschema
import yaml
from fastapi.testclient import TestClient

SRC = Path(__file__).resolve().parents[2] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from kert.api.server import create_app  # noqa: E402
from kert.application.provision import provision_control_plane  # noqa: E402
from kert.application.skills import SkillExecutionService  # noqa: E402

SOURCE = Path(__file__).resolve().parents[2] / "examples" / "bank-front-knowledge-maps"
CUSTOMER_ID = "CUST-CORP-0001"
OUTREACH_REQ = {"customerId": CUSTOMER_ID}
_ONTOLOGY_VERSION = "CTR-SEM-002@sha256:705578d6324abd0c"


def _route_entry(trace: list[dict]) -> dict:
    """trace 中的路由步骤：成功项带 ``mapId``，被拒项带路由类拒绝码。"""
    for t in trace:
        if "mapId" in t or str(t.get("errorCode", "")).startswith(
                ("ROUTE_", "KNOWLEDGE_MAP_", "ONTOLOGY_REFERENCE_")):
            return t
    raise AssertionError(f"trace 中未找到路由步骤：{trace}")


# --------------------------------------------------------------------------- #
# 未供给：记 blocked，但技能照常完成（本步不改行为）
# --------------------------------------------------------------------------- #

def test_unprovisioned_workspace_records_blocked_but_skill_still_runs(ws):
    svc = SkillExecutionService(ws)
    r = svc.execute("skill-customer-outreach-script", "rt-1", OUTREACH_REQ)

    assert r.status == "ok", (r.status, r.errors)      # 行为不变
    e = _route_entry(r.assembly_trace)
    assert e["status"] == "blocked"
    assert e["errorCode"] == "ROUTE_POLICY_ABSENT"
    # 不回落硬编码：被拒时**不得**出现那张地图的名字
    assert "KM-CORP-RM-OUTREACH" not in json.dumps(e, ensure_ascii=False)


# --------------------------------------------------------------------------- #
# 已供给：trace 反映解析结果
# --------------------------------------------------------------------------- #

def test_provisioned_workspace_records_resolved_plan(ws):
    provision_control_plane(ws, SOURCE)
    svc = SkillExecutionService(ws)
    r = svc.execute("skill-customer-outreach-script", "rt-2", OUTREACH_REQ)

    assert r.status == "ok"
    e = _route_entry(r.assembly_trace)
    assert e["status"] == "ok"
    assert e["mapId"] == "KM-CORP-RM-OUTREACH"
    assert e["versions"]["knowledgeMap"] == "KM-CORP-RM-OUTREACH@1.0.0"
    assert e["versions"]["routePolicy"] == "RP-KERT-BANKFRONT-001@1.0.0"
    assert e["versions"]["ontology"] == _ONTOLOGY_VERSION
    assert len(e["planHash"]) == 16
    assert e["message"].startswith("按计划进入知识地图 KM-CORP-RM-OUTREACH@1.0.0")
    assert "mapMismatch" not in e


def test_trace_plan_hash_equals_routing_plan_api(ws):
    """trace 的 planHash 必须与 ``/v1/routing/plan`` **同源同值**（否则是两套事实）。"""
    provision_control_plane(ws, SOURCE)
    api = TestClient(create_app(ws)).post(
        "/v1/routing/plan", json={"taskType": "OUTREACH_PREPARATION"}).json()

    svc = SkillExecutionService(ws)
    r = svc.execute("skill-customer-outreach-script", "rt-3", OUTREACH_REQ)
    e = _route_entry(r.assembly_trace)

    assert e["planHash"] == api["data"]["plan"]["planHash"]
    assert e["versions"] == api["data"]["plan"]["versions"]


def test_each_skill_reports_its_own_task(ws):
    provision_control_plane(ws, SOURCE)
    svc = SkillExecutionService(ws)
    cases = [
        ("skill-customer-outreach-script", OUTREACH_REQ, "KM-CORP-RM-OUTREACH"),
        ("skill-customer-meeting-script", {"customerId": CUSTOMER_ID}, "KM-CORP-RM-MEETING"),
        # previsit 必须先通过无新证据策略门禁（要求 evidenceTimestamp）才会走到路由步骤
        ("skill-customer-previsit-report",
         {"customerId": CUSTOMER_ID, "evidenceTimestamp": "2026-08-22T10:00:00Z"},
         "KM-CORP-RM-PREVISIT"),
    ]
    for i, (skill_id, req, expected_map) in enumerate(cases):
        r = svc.execute(skill_id, f"rt-4-{i}", req)
        # 未种客户知识时可走既有业务退出策略 exit_policy_no_new_evidence（非错误、非本步引入）
        assert r.status in {"ok", "exit_policy_no_new_evidence"}, (skill_id, r.status, r.errors)
        e = _route_entry(r.assembly_trace)
        assert e["mapId"] == expected_map, (skill_id, e)
        assert e["planHash"], (skill_id, e)


def test_route_trace_absent_when_blocked_before_routing(ws):
    """**边界记录**：技能在"无新证据"门禁处早退时不会有路由条目。

    该门禁位于 ``execute()`` 中、技能分派**之前**（既有业务策略，本步未改动它）。
    本用例把这个边界**钉住**，避免日后误以为"trace 一定含路由条目"。
    """
    provision_control_plane(ws, SOURCE)
    svc = SkillExecutionService(ws)
    r = svc.execute("skill-customer-previsit-report", "rt-4b", OUTREACH_REQ)  # 无 evidenceTimestamp

    assert r.status == "exit_policy_no_new_evidence"
    assert not any("mapId" in t or str(t.get("errorCode", "")).startswith("ROUTE_")
                   for t in r.assembly_trace)


# --------------------------------------------------------------------------- #
# 失配：计划选的地图 ≠ 技能组装知识条目所用的地图 ⇒ 必须显式暴露
# --------------------------------------------------------------------------- #

def test_map_mismatch_is_surfaced_not_hidden(ws):
    """策略把 OUTREACH 交给**另一张也声明该任务**的地图 ⇒ trace 必须显式标记失配。

    注意不能简单把策略指向 KM-CORP-RM-MEETING：那张地图**未声明** OUTREACH_PREPARATION，
    会被路由直接判为错配而拒绝（另一条 path，已由契约的 ROUTE_* 覆盖）。
    真实失配场景是"两张地图都声明同一任务、策略选了另一张"——此时技能仍按自己的 KI 清单
    组装知识，而计划选的却是另一张地图的知识条目，**必须**让这个分歧可见。
    """
    provision_control_plane(ws, SOURCE)
    catalog = ws / "90_control" / "catalog"

    alt = json.loads((catalog / "KM-CORP-RM-OUTREACH.json").read_text(encoding="utf-8"))
    alt["mapId"] = "KM-CORP-RM-OUTREACH-ALT"          # 同样声明 OUTREACH_PREPARATION
    alt["title"] = "外联准备（备选地图）"
    (catalog / "KM-CORP-RM-OUTREACH-ALT.json").write_text(
        json.dumps(alt, ensure_ascii=False, indent=2), encoding="utf-8")

    p = ws / "90_control" / "schema" / "route_policy.json"
    doc = json.loads(p.read_text(encoding="utf-8"))
    for rule in doc["rules"]:
        if rule["taskType"] == "OUTREACH_PREPARATION":
            rule["knowledgeMapId"] = "KM-CORP-RM-OUTREACH-ALT"
    p.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")

    svc = SkillExecutionService(ws)
    r = svc.execute("skill-customer-outreach-script", "rt-5", OUTREACH_REQ)

    assert r.status == "ok", (r.status, r.errors)
    e = _route_entry(r.assembly_trace)
    assert e["status"] == "ok" and e["mapId"] == "KM-CORP-RM-OUTREACH-ALT"
    assert e["mapMismatch"] is True
    assert e["mapExpected"] == "KM-CORP-RM-OUTREACH"
    assert "不一致" in e["message"]


# --------------------------------------------------------------------------- #
# 拒绝码透传（本体引用类）
# --------------------------------------------------------------------------- #

def test_ontology_denial_code_is_passed_through(ws):
    provision_control_plane(ws, SOURCE)
    ref = ws / "90_control" / "schema" / "ontology_reference.json"
    doc = json.loads(ref.read_text(encoding="utf-8"))
    doc["contentSha256"] = "not-a-sha256"
    ref.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")

    svc = SkillExecutionService(ws)
    r = svc.execute("skill-customer-outreach-script", "rt-6", OUTREACH_REQ)

    assert r.status == "ok"
    e = _route_entry(r.assembly_trace)
    assert e["status"] == "blocked"
    assert e["errorCode"] == "ONTOLOGY_REFERENCE_INVALID"


# --------------------------------------------------------------------------- #
# 无工作区
# --------------------------------------------------------------------------- #

def test_no_workspace_records_unresolved():
    svc = SkillExecutionService()
    trace: list[dict] = []
    svc._trace_knowledge_map(trace, "KM-CORP-RM-OUTREACH", "OUTREACH_PREPARATION")

    assert len(trace) == 1
    assert trace[0]["phase"] == "evidence"
    assert trace[0]["status"] == "blocked"
    assert trace[0]["errorCode"] == "ROUTE_UNRESOLVED"
    assert "工作区未配置" in trace[0]["message"]


# --------------------------------------------------------------------------- #
# 合同 ↔ 实现机械核对（Contract Owner 2026-09-15 批准的修正项）
# --------------------------------------------------------------------------- #

ROOT = Path(__file__).resolve().parents[2]
TRACE_SCHEMA = ROOT / "docs" / "contracts" / "schemas" / "assembly-trace.schema.json"
V1_SPEC = ROOT / "specs" / "kert-openapi-v1.yaml"


def test_spec_assembly_trace_is_array_not_object():
    """v1.5 修正：合同须声明 ``assemblyTrace`` 为**数组**（实现返回 list）。

    修正前合同写 ``type: object``，与实现长期不符 —— 本用例把修正钉住，防回归。
    """
    spec = yaml.safe_load(V1_SPEC.read_text(encoding="utf-8"))
    holders = {
        name: schema["properties"]["assemblyTrace"]
        for name, schema in spec["components"]["schemas"].items()
        if isinstance(schema, dict) and "assemblyTrace" in (schema.get("properties") or {})
    }
    assert holders, "合同中未声明 assemblyTrace"
    for name, node in holders.items():
        assert node["type"] == "array", (name, node)
        assert node["items"]["type"] == "object", (name, node)


def test_emitted_trace_entries_conform_to_canonical_schema(ws):
    """实现产出的 trace 条目必须通过 canonical schema（真实校验，非形状近似）。

    覆盖 **ok** 与 **blocked** 两种路由条目：词表（``phase``/``status`` 枚举）、
    必填字段（``message``）与新字段类型（``mapMismatch`` 布尔、``versions`` 值类型）
    任一不符即失败。
    """
    schema = json.loads(TRACE_SCHEMA.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator.check_schema(schema)
    validator = jsonschema.Draft202012Validator(schema)

    provision_control_plane(ws, SOURCE)
    svc = SkillExecutionService(ws)
    ok_entry = _route_entry(svc.execute("skill-customer-outreach-script", "rt-c9a",
                                        OUTREACH_REQ).assembly_trace)
    assert ok_entry["status"] == "ok"
    validator.validate(ok_entry)

    # 撤掉策略 ⇒ 造出 blocked 条目
    (ws / "90_control" / "schema" / "route_policy.json").unlink()
    blocked = _route_entry(SkillExecutionService(ws).execute(
        "skill-customer-outreach-script", "rt-c9b", OUTREACH_REQ).assembly_trace)
    assert blocked["status"] == "blocked"
    validator.validate(blocked)
