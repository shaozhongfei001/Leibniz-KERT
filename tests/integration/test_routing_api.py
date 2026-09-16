"""v1.5 知识路由 API 集成测试（合同：`specs/kert-openapi-v1.yaml` 的 Routing tag）。

纪律：
- **真实工作区**（`examples/bank-front-knowledge-maps/`，非 mock）；
- 不只测行为，还**机械核对合同与实现一致**（路径存在、预案字段与 `to_dict()` 逐字段相等）；
- fail-closed 路径必须覆盖：未映射、未知 mapId、未知请求字段。
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from kert.api.server import create_app
from kert.domain.workspace import init_workspace

REPO_ROOT = Path(__file__).resolve().parents[2]
EXAMPLE_WS = REPO_ROOT / "examples" / "bank-front-knowledge-maps"
SPEC = REPO_ROOT / "specs" / "kert-openapi-v1.yaml"

ONTOLOGY_VERSION = "CTR-SEM-002@sha256:705578d6324abd0c"


@pytest.fixture
def client() -> TestClient:
    """受控 example 工作区上的 API 客户端（只读；不做数据链路搭建）。"""
    return TestClient(create_app(EXAMPLE_WS))


# --------------------------------------------------------------------------- #
# 合同 ↔ 实现一致性（机械核对，防空转）
# --------------------------------------------------------------------------- #

#: 合同版本钉（**模块常量**：一处维护、多处复用）。
#: 随 Contract Owner 批准的 bump 同步：`1.5.0 → 1.5.1`（形状更正补丁）→ **`1.6.0`**（A-6 九条登记 + A-9 删除）
#: → **`1.6.1`**（D-27：`JobStatusData.status.enum` 4 值 → `JOB_STATES` **九值**，值域更正补丁）。
#: 注意：本用例的**主旨**是"路由三路径与 schema 确已在合同中声明"，版本钉只用于**防意外改版本号**。
EXPECTED_SPEC_VERSION = "1.6.1"


def test_spec_declares_the_three_paths_and_schemas():
    spec = yaml.safe_load(SPEC.read_text(encoding="utf-8"))
    assert spec["info"]["version"] == EXPECTED_SPEC_VERSION
    for path in ("/v1/knowledge-maps", "/v1/knowledge-maps/{mapId}", "/v1/routing/plan"):
        assert path in spec["paths"], path
    schemas = spec["components"]["schemas"]
    for name in ("ActivationPlan", "PlanAsset", "PlanDenial", "RoutingPlanRequest",
                 "RoutingPlanResponse", "KnowledgeMapSummary",
                 "KnowledgeMapListResponse", "KnowledgeMapDetail"):
        assert name in schemas, name


def test_response_envelope_shapes_match_contract(client):
    """合同声明的响应**形状**必须与**实际**响应一致（防"测试绿而合同错"）。

    起因（真实事故，2026-09-16 由 C-20 归并候选发现）：v1.5 的 `RoutingPlanResponse`
    曾把 `allowed` 声明在**顶层**，而实现按标准信封放在 `data` 内，用例按 `data.allowed`
    断言 ⇒ **测试全绿、合同错**。本用例机械核对：合同 `required` ⊆ 实际键集，
    且 `data` 内声明的 `required`/属性名必须真的出现。
    """
    spec = yaml.safe_load(SPEC.read_text(encoding="utf-8"))
    schemas = spec["components"]["schemas"]

    cases = [
        ("KnowledgeMapListResponse", client.get("/v1/knowledge-maps").json()),
        ("KnowledgeMapDetail",
         client.get("/v1/knowledge-maps/KM-CORP-RM-OUTREACH").json()),
        ("RoutingPlanResponse",
         client.post("/v1/routing/plan", json={"taskType": "OUTREACH_PREPARATION"}).json()),
    ]
    for name, body in cases:
        schema = schemas[name]
        assert set(schema["required"]) <= set(body), (name, sorted(body))
        data_schema = (schema.get("properties") or {}).get("data") or {}
        if data_schema:
            assert "data" in body, (name, sorted(body))
            assert set(data_schema.get("required") or ()) <= set(body["data"]), \
                (name, sorted(body["data"]))
            for prop in (data_schema.get("properties") or {}):
                assert prop in body["data"], (name, prop, sorted(body["data"]))


def test_activation_plan_contract_matches_implementation_field_for_field(client):
    """合同 `ActivationPlan.required` 必须与 `to_dict()` 的键集合**逐字段相等**。

    这是"合同先行"的兑现检查：任一侧改了字段而另一侧没跟，本用例变红。
    """
    spec = yaml.safe_load(SPEC.read_text(encoding="utf-8"))
    required = set(spec["components"]["schemas"]["ActivationPlan"]["required"])

    r = client.post("/v1/routing/plan", json={"taskType": "PRE_VISIT_PREPARATION"})
    assert r.status_code == 200
    plan = r.json()["data"]["plan"]
    assert plan is not None

    assert set(plan.keys()) == required, (
        f"实现字段集 {sorted(plan.keys())} 与合同 required {sorted(required)} 不一致")


# --------------------------------------------------------------------------- #
# 知识地图查询
# --------------------------------------------------------------------------- #

def test_list_knowledge_maps(client):
    r = client.get("/v1/knowledge-maps")
    assert r.status_code == 200
    data = r.json()["data"]

    # 反空转：数量与 ID 先断言
    assert data["count"] == 3, data
    ids = {m["mapId"] for m in data["maps"]}
    assert ids == {"KM-CORP-RM-OUTREACH", "KM-CORP-RM-MEETING", "KM-CORP-RM-PREVISIT"}
    for m in data["maps"]:
        assert m["assetCount"] > 0 and m["skillCount"] > 0
        assert m["routePolicyRef"] == "RP-KERT-BANKFRONT-001"

    assert data["policy"]["policyId"] == "RP-KERT-BANKFRONT-001"
    assert data["policy"]["defaultDecision"] == "DENY"


def test_get_knowledge_map_detail(client):
    r = client.get("/v1/knowledge-maps/KM-CORP-RM-MEETING")
    assert r.status_code == 200
    d = r.json()["data"]
    assert d["mapId"] == "KM-CORP-RM-MEETING"
    assert d["tasks"] == ["MEETING_PREPARATION"]
    assert d["assetCount"] == 4


def test_unknown_map_returns_404(client):
    r = client.get("/v1/knowledge-maps/KM-NOT-REGISTERED-0001")
    assert r.status_code == 404
    assert r.json()["detail"]["error"]["code"] == "KNOWLEDGE_MAP_NOT_REGISTERED"


# --------------------------------------------------------------------------- #
# 路由裁决与激活计划
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(("task", "map_id", "map_version"), [
    ("OUTREACH_PREPARATION", "KM-CORP-RM-OUTREACH", "1.0.0"),
    ("MEETING_PREPARATION", "KM-CORP-RM-MEETING", "1.0.0"),
    # 1.0.1：修正 assetRefs（原只列 3 条，属 _run_supply_chain 的读取集）
    ("PRE_VISIT_PREPARATION", "KM-CORP-RM-PREVISIT", "1.0.1"),
])
def test_plan_allowed_for_each_task(client, task, map_id, map_version):
    r = client.post("/v1/routing/plan", json={"taskType": task, "subjectId": "CUST-0001"})
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["allowed"] is True and data["denial"] is None
    plan = data["plan"]
    # 地图键在 versions.knowledgeMap（`to_dict()` 不重复输出 mapKey —— 与合同一致）
    assert "mapKey" not in plan
    assert plan["planId"].startswith("AP-KERT-" + task)
    assert plan["versions"]["knowledgeMap"] == f"{map_id}@{map_version}"
    assert plan["versions"]["routePolicy"] == "RP-KERT-BANKFRONT-001@1.0.0"
    assert plan["versions"]["ontology"] == ONTOLOGY_VERSION
    assert plan["versions"]["activationContract"] is None
    assert plan["routeReason"], "计划必须携带路由理由"


def test_plan_hash_is_replayable_over_http(client):
    """同输入两次调用 ⇒ 同一 planHash 与同一 planId（可重放）。"""
    a = client.post("/v1/routing/plan", json={"taskType": "PRE_VISIT_PREPARATION"})
    b = client.post("/v1/routing/plan", json={"taskType": "PRE_VISIT_PREPARATION"})
    pa, pb = a.json()["data"]["plan"], b.json()["data"]["plan"]
    assert pa["planHash"] == pb["planHash"]
    assert pa["planId"] == pb["planId"]


def test_subject_does_not_affect_plan_hash_over_http(client):
    a = client.post("/v1/routing/plan",
                    json={"taskType": "PRE_VISIT_PREPARATION", "subjectId": "CUST-A"})
    b = client.post("/v1/routing/plan",
                    json={"taskType": "PRE_VISIT_PREPARATION", "subjectId": "CUST-B"})
    pa, pb = a.json()["data"]["plan"], b.json()["data"]["plan"]
    assert pa["planHash"] == pb["planHash"], "主体不得进入 planHash"
    assert pa["subjectId"] != pb["subjectId"]


def test_unmapped_task_is_denied_with_200(client):
    """未映射 ⇒ **200** + allowed=false + denial（拒绝是业务结果，不是协议错误）。"""
    r = client.post("/v1/routing/plan", json={"taskType": "NO_SUCH_TASK"})
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["allowed"] is False
    assert data["plan"] is None
    assert data["denial"]["code"] == "ROUTE_NOT_MAPPED"
    assert "NO_SUCH_TASK" in data["denial"]["reason"]


def test_unknown_request_field_is_rejected(client):
    """合同 `RoutingPlanRequest.additionalProperties: false` ⇒ 未知字段 422。"""
    r = client.post("/v1/routing/plan",
                    json={"taskType": "PRE_VISIT_PREPARATION", "bogus": 1})
    assert r.status_code == 422


def test_missing_task_type_is_rejected(client):
    assert client.post("/v1/routing/plan", json={}).status_code == 422


# --------------------------------------------------------------------------- #
# 未配置控制面的工作区：列表为空 + 默认拒绝
# --------------------------------------------------------------------------- #

def test_unprovisioned_workspace_lists_empty_and_denies(tmp_path: Path):
    ws = tmp_path / "ws"
    init_workspace(ws)
    c = TestClient(create_app(ws))

    listed = c.get("/v1/knowledge-maps")
    assert listed.status_code == 200
    assert listed.json()["data"]["count"] == 0
    assert listed.json()["data"]["policy"] is None

    denied = c.post("/v1/routing/plan", json={"taskType": "PRE_VISIT_PREPARATION"})
    assert denied.status_code == 200
    assert denied.json()["data"]["allowed"] is False
    assert denied.json()["data"]["denial"]["code"] == "ROUTE_POLICY_ABSENT"
