"""合同 ↔ 实现 **响应形状** 机械核对（防空转；C-20 归并候选 F1/F3/F4/F5 的防回归闸门）。

背景（真实事故，2026-09-16 由 `evidence/m7-3/CANDIDATE-CONTRACT-MERGE-V1-V2.md` 发现）：
v1 合同曾有多处响应 schema 与服务**实际实现**不符，而既有测试只按"实际"断言 ⇒
**测试全绿、合同错**。本文件把"合同声明的形状"与"真实响应"机械对齐：

对每个被核对的 schema 施加**三段式**判定：

1. `required` 中的键**必须出现** ⇒ 否则"合同要求了实现没有的东西"，报错；
2. 实际出现的键**必须在 `properties` 中被声明** ⇒ 否则"实现发了合同没声明的东西"，报错；
3. 若 `additionalProperties: false`，则 `properties` 中的键**必须全部出现** ⇒
   否则"声明完备性"是假的（此时属性集 = 闭集，声明即承诺）。

判定 2/3 合起来等价于"闭集精确相等"，因此**把合同改回错误形态该用例必红**：
- ① 闸门 `gates[]` 改回 `GateChecklistItem`（`gate`/`state`/`checklist`）⇒ 判定 2 命中；
- ② `JobStatusResponse` 改回扁平对象（顶层 `jobId`）⇒ 判定 1+2 命中；
- ③ `/api/skill/execute` 的 404 改回 `ErrorResponse` ⇒ 判定 2 命中（`data`/`assemblyTrace` 未声明）；
- ④ `GateAuditResponse` 改回 `timestamp`/`auditPath` ⇒ 判定 2 命中；
- ⑤ `/v1/jobs` 的 404 改回 `ErrorResponse` ⇒ 判定 2 命中（`detail` 未声明）。

纪律：本文件**只读**合同与真实响应，不改任何实现；被核对端点的证据行号写在各自用例内。
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from kert.api.server import create_app

REPO_ROOT = Path(__file__).resolve().parents[2]
SPEC = REPO_ROOT / "specs" / "kert-openapi-v1.yaml"
#: 含**已完成** Job（`STATUS.md` + `result.json`）的示例工作区，用于核对 `skill_result` 分支。
COMPLETED_JOB_WS = REPO_ROOT / "examples" / "product-recommendation-assets"
COMPLETED_JOB_ID = "JOB-SKILL-20260901-001"


# --------------------------------------------------------------------------- #
# 核对器
# --------------------------------------------------------------------------- #

def _schemas(spec: dict) -> dict:
    return spec["components"]["schemas"]


def _resolve(spec: dict, schema: dict) -> dict:
    """解析单层 `$ref`（仅本文件用到的 `#/components/schemas/*`）。"""
    while isinstance(schema, dict) and "$ref" in schema:
        ref = schema["$ref"]
        assert ref.startswith("#/components/schemas/"), ref
        schema = _schemas(spec)[ref.rsplit("/", 1)[1]]
    return schema


def check_shape(spec: dict, schema: dict, value, path: str) -> int:
    """三段式核对；返回**已核对的键数**（供防空转断言用）。"""
    checked = 0
    if not isinstance(schema, dict):
        return 0
    if "allOf" in schema:
        for sub in schema["allOf"]:
            checked += check_shape(spec, sub, value, path)
        return checked

    schema = _resolve(spec, schema)
    if "allOf" in schema:  # 解引用后可能仍是合取
        for sub in schema["allOf"]:
            checked += check_shape(spec, sub, value, path)
        return checked

    if isinstance(value, dict):
        props = schema.get("properties") or {}
        required = schema.get("required") or []
        missing = [k for k in required if k not in value]
        assert not missing, (
            f"{path}: 合同 required 却在响应中缺席 {missing}（实际键 {sorted(value)}）")
        undeclared = [k for k in value if props and k not in props]
        assert not undeclared, (
            f"{path}: 响应字段未在合同 properties 中声明 {undeclared}"
            f"（合同已声明 {sorted(props)}）")
        if schema.get("additionalProperties") is False and props:
            absent = [k for k in props if k not in value]
            assert not absent, (
                f"{path}: additionalProperties=false 但合同声明的属性缺席 {absent}"
                f"（实际键 {sorted(value)}）")
        for key, sub in props.items():
            if key in value:
                checked += 1 + check_shape(spec, sub, value[key], f"{path}.{key}")
    elif isinstance(value, list) and "items" in schema:
        for idx, item in enumerate(value):
            checked += check_shape(spec, schema["items"], item, f"{path}[{idx}]")
    return checked


@pytest.fixture(scope="module")
def spec() -> dict:
    return yaml.safe_load(SPEC.read_text(encoding="utf-8"))


@pytest.fixture
def client(ws) -> TestClient:
    return TestClient(create_app(ws))


def _ref_of(spec: dict, path: str, method: str, status: str) -> str:
    """取出某响应声明的 `$ref` 名（路径级接线核对，防"schema 对了但没接上"）。"""
    node = spec["paths"][path][method]["responses"][status]["content"]["application/json"]["schema"]
    ref = node.get("$ref")
    assert ref, f"{path} {status} 未声明 $ref（实为 {node}）"
    return ref.rsplit("/", 1)[1]


# --------------------------------------------------------------------------- #
# ① 闸门清单：GateListResponse / GateDefinition
#    修正依据：实现 `src/kert/application/service_proposal.py:114-117`
#    （`gateId`/`name`/`sequence`/`must`/`forbidden`/`assetPath`）
# --------------------------------------------------------------------------- #

def test_gate_list_shape_matches_contract(spec, client):
    assert _ref_of(spec, "/api/skill/gates/{customerId}", "get", "200") == "GateListResponse"
    body = client.get("/api/skill/gates/CUST-CORP-0001").json()
    checked = check_shape(spec, _schemas(spec)["GateListResponse"], body, "GateListResponse")
    # 反空转：顶 2 键 + 每闸门 6 键 × 6 门 ≥ 38
    assert checked >= 38, checked
    assert [g["gateId"] for g in body["gates"]][:2] == ["GATE-BIZ-G0", "GATE-BIZ-G1"]
    # 原误声明三键必须**不在**真实响应中（钉住 F1 的修正方向）
    for gate in body["gates"]:
        assert "gate" not in gate and "state" not in gate and "checklist" not in gate, gate


def _ref_targets(obj) -> set[str]:
    """递归收集 schema 内的 `$ref` **目标名**（只看引用，不看描述文字）。"""
    found: set[str] = set()
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key == "$ref" and isinstance(value, str):
                found.add(value.rsplit("/", 1)[1])
            else:
                found |= _ref_targets(value)
    elif isinstance(obj, list):
        for item in obj:
            found |= _ref_targets(item)
    return found


def test_gate_checklist_item_still_used_by_gate_recommendations(spec):
    """`GateChecklistItem` 只应从 `GateRecommendations.checklist` 引用（勿被闸门清单误用）。"""
    schemas = _schemas(spec)
    users = sorted(name for name, sch in schemas.items()
                   if "GateChecklistItem" in _ref_targets(sch))
    assert users == ["GateRecommendations"], users
    assert "GateDefinition" in _ref_targets(schemas["GateListResponse"])


# --------------------------------------------------------------------------- #
# ② 闸门审计：GateAuditResponse
#    修正依据：实现 `src/kert/application/skills.py:898-920`（`{"recorded": True, **rec}`）
# --------------------------------------------------------------------------- #

def test_gate_audit_shape_matches_contract(spec, client):
    assert _ref_of(spec, "/api/skill/gates/audit", "post", "200") == "GateAuditResponse"
    r = client.post("/api/skill/gates/audit", json={
        "customerId": "CUST-CORP-0001", "gate": "G1", "decision": "PASSED",
        "decidedBy": "mech-check", "reason": "机械核对"})
    assert r.status_code == 200
    body = r.json()
    checked = check_shape(spec, _schemas(spec)["GateAuditResponse"], body, "GateAuditResponse")
    assert checked >= 7, checked
    assert body["recorded"] is True and body["recordedAt"]
    # 原误声明两键必须缺席
    assert "timestamp" not in body and "auditPath" not in body, sorted(body)


# --------------------------------------------------------------------------- #
# ③ 未知 Skill 的 404：SkillExecuteErrorResponse（**与 200 同构**）
#    修正依据：实现 `src/kert/api/server.py:635-643`（复用同步结果体，`status_code=404`）
# --------------------------------------------------------------------------- #

def test_unknown_skill_404_shape_matches_contract(spec, client):
    ref = _ref_of(spec, "/api/skill/execute", "post", "404")
    assert ref == "SkillExecuteErrorResponse"
    r = client.post("/api/skill/execute", json={
        "skillId": "NO-SUCH-SKILL", "requestId": "mech-check-1",
        "request": {"customerId": "CUST-CORP-0001"}})
    assert r.status_code == 404
    body = r.json()
    checked = check_shape(spec, _schemas(spec)[ref], body, ref)
    assert checked >= 6, checked
    assert body["status"] == "skill_error"
    assert body["errors"][0]["code"] == "UNKNOWN_SKILL"
    # 与 200 同构：错误路径也带装配追踪（这正是 `ErrorResponse` 描述不了的部分）
    assert "assemblyTrace" in body and "data" in body


# --------------------------------------------------------------------------- #
# ④ Job 状态：JobStatusResponse（信封）+ JobStatusData（snake_case 记录）
#    修正依据：实现 `src/kert/api/server.py:502-508` + `src/kert/application/jobs.py:236-253`
#    ⚠ 须通知 GITS：`data.status` / `data.skill_result` 的嵌套位置保持不变
# --------------------------------------------------------------------------- #

def test_job_status_shape_matches_contract(spec):
    assert _ref_of(spec, "/v1/jobs/{jobId}", "get", "200") == "JobStatusResponse"
    client = TestClient(create_app(COMPLETED_JOB_WS))
    r = client.get(f"/v1/jobs/{COMPLETED_JOB_ID}")
    assert r.status_code == 200
    body = r.json()

    checked = check_shape(spec, _schemas(spec)["JobStatusResponse"], body, "JobStatusResponse")
    assert checked >= 5, checked
    # 信封与 Job 业务状态**不同义**：顶层恒 OK，业务状态在 data.status
    assert body["status"] == "OK" and body["data"]["status"] == "COMPLETED"

    data_checked = check_shape(spec, _schemas(spec)["JobStatusData"], body["data"],
                               "JobStatusResponse.data")
    assert data_checked >= 17, data_checked
    # 原误声明的 camelCase 键必须不在响应中（钉住 F3 的修正方向）
    assert "jobId" not in body and "jobId" not in body["data"]
    assert body["data"]["job_id"] == COMPLETED_JOB_ID
    # GITS 口依赖的位置：`data.skill_result`（不是顶层）
    assert "skillResult" not in body and "skill_result" not in body
    assert body["data"]["skill_result"]["status"] == "ok"


def test_job_status_skill_result_is_optional(spec):
    """`skill_result` **不得**进入 `required`：未完成的 Job 不带该键（`jobs.py:324-333`）。"""
    data_schema = _schemas(spec)["JobStatusData"]
    assert "skill_result" not in (data_schema.get("required") or [])
    assert "skill_result" in data_schema["properties"]


# --------------------------------------------------------------------------- #
# ⑤ Job 不存在的 404：InfrastructureErrorResponse（`{"detail":{"error":{...}}}`）
#    修正依据：实现 `src/kert/api/server.py:308-316` 的 `_handle()`
# --------------------------------------------------------------------------- #

def test_job_not_found_404_shape_matches_contract(spec, client):
    ref = _ref_of(spec, "/v1/jobs/{jobId}", "get", "404")
    assert ref == "InfrastructureErrorResponse"
    r = client.get("/v1/jobs/JOB-NOT-EXIST")
    assert r.status_code == 404
    body = r.json()
    checked = check_shape(spec, _schemas(spec)[ref], body, ref)
    assert checked >= 4, checked
    assert body["detail"]["error"]["code"] == "ASSET_NOT_FOUND"
    assert body["detail"]["error"]["retryable"] is False
