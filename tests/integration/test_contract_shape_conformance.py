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
    if "oneOf" in schema:  # 析取：至少一支必须匹配（如实记录形态并存的情形）
        _, checked = check_shape_any(spec, schema, value, path)
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


def check_shape_any(spec: dict, schema: dict, value, path: str) -> tuple[int, int]:
    """`oneOf` 析取核对：至少一支通过。

    Returns:
        (命中分支下标, 该分支已核对键数)；全不匹配时抛 AssertionError 并列出各支失败原因。
    """
    failures = []
    for idx, branch in enumerate(schema["oneOf"]):
        try:
            return idx, check_shape(spec, branch, value, path)
        except AssertionError as exc:  # noqa: PERF203 - 分支少，可读性优先
            label = branch.get("$ref", "<inline>") if isinstance(branch, dict) else branch
            failures.append(f"    branch[{idx}] {label}: {exc}")
    raise AssertionError(
        f"{path}: oneOf 无任何分支匹配实际形状：\n" + "\n".join(failures))


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
#    修正依据：实现 `skill_execute() 的 404 段 @ `src/kert/api/server.py:663-671``（复用同步结果体，`status_code=404`）
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
#    修正依据：实现 `job()` @ `src/kert/api/server.py:530-536` + `src/kert/application/jobs.py:236-253`
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
#    修正依据：实现 `_handle()` @ `src/kert/api/server.py:310-318`
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


# --------------------------------------------------------------------------- #
# ⑧ 健康接口（F7）
# --------------------------------------------------------------------------- #

def test_skill_health_shape_matches_contract(spec, client):
    """`/api/skill/health` 必须声明实现真正返回的全部键（`service` 与 `skills[].version`）。

    修正依据：`skill_health()` @ `src/kert/api/server.py:637-645` 返回字典字面量
    `{"status", "service", "skills:[{skillId,name,version}]}`；
    原合同漏声明 `service` 与 `skills[].version`（三条断言方向中的"实现发了合同没声明的"）。
    """
    ref = _ref_of(spec, "/api/skill/health", "get", "200")
    assert ref == "SkillHealthResponse"
    body = client.get("/api/skill/health").json()

    checked = check_shape(spec, _schemas(spec)[ref], body, ref)
    assert checked >= 4, checked
    assert body["service"] == "customer-engagement"  # 写死值，见 C-14
    for item in body["skills"]:
        checked += check_shape(spec, _schemas(spec)["SkillBriefInfo"], item,
                               "SkillBriefInfo")
    assert checked >= 5 + 3 * len(body["skills"]), checked
    assert body["skills"] and all(s["version"] for s in body["skills"])


# --------------------------------------------------------------------------- #
# ⑥ 错误信封族 · Part A（合同如实化）
# --------------------------------------------------------------------------- #

def test_execute_has_no_400_and_422_matches_contract(spec, client):
    """`/api/skill/execute` **没有 400 路径**；参数错误实测为 422 + FastAPI 校验体。

    修正依据：该路由无 `try/except`（`skill_execute()` @ `src/kert/api/server.py:647-671`），
    请求体校验由 Pydantic 直接完成并返回 422。
    """
    responses = spec["paths"]["/api/skill/execute"]["post"]["responses"]
    assert "400" not in responses, "400 实测不可达，不得再声明"
    ref = _ref_of(spec, "/api/skill/execute", "post", "422")
    assert ref == "ValidationErrorResponse"

    r = client.post("/api/skill/execute", json={})
    assert r.status_code == 422
    body = r.json()
    checked = check_shape(spec, _schemas(spec)[ref], body, ref)
    assert checked >= 4, checked
    assert body["detail"][0]["loc"] == ["body", "skillId"]
    # 不得再是旧声明的 ErrorResponse 形状
    assert "errors" not in body and "requestId" not in body


def test_report_404_shape_matches_contract(spec, client):
    """`/api/skill/report/{requestId}` 的 404 实测为 `{"detail": "<字符串>"}`。

    修正依据：`skill_report() 的 404 段 @ `src/kert/api/server.py:681-685`` 用 `HTTPException(detail=str)` 抛出。
    """
    ref = _ref_of(spec, "/api/skill/report/{requestId}", "get", "404")
    assert ref == "StringDetailErrorResponse"
    r = client.get("/api/skill/report/no-such-request-id")
    assert r.status_code == 404
    body = r.json()
    checked = check_shape(spec, _schemas(spec)[ref], body, ref)
    assert checked >= 1, checked
    assert set(body) == {"detail"}, sorted(body)
    assert isinstance(body["detail"], str) and body["detail"]


def _force_map_load_failure(monkeypatch, exc_factory) -> None:
    """让 `KnowledgeMapRegistry.load` 抛出指定异常（只用于测试，不动实现）。"""
    from kert.domain.knowledge_map import KnowledgeMapRegistry

    def _boom(_ws):
        raise exc_factory()

    monkeypatch.setattr(KnowledgeMapRegistry, "load", staticmethod(_boom))


def test_knowledge_maps_error_shapes_match_contract(spec, ws, monkeypatch):
    """`/v1/knowledge-maps` 的 422/500 如实化：领域异常 = `detail` 包装；未捕获 = 信封。

    修正依据：`list_knowledge_maps()` 的 try/except @ `src/kert/api/server.py:728-732`
    给出 `{"detail":{"error":{...}}}`；未捕获异常走 app 级处理器给出 `ErrorResponse` 信封。
    两种 500 形态并存 ⇒ 合同用 `oneOf` 如实声明，本用例**分别命中两支**（防空转）。
    """
    from kert.domain.errors import KERTException, SchemaValidationError

    resp500 = spec["paths"]["/v1/knowledge-maps"]["get"]["responses"]["500"]
    schema500 = resp500["content"]["application/json"]["schema"]
    assert "oneOf" in schema500, (
        "500 实测两种形状并存，合同必须用 oneOf 如实声明（不得只声明一支）")
    assert [b["$ref"].rsplit("/", 1)[1] for b in schema500["oneOf"]] == [
        "InfrastructureErrorResponse", "ErrorResponse"]  # 声明必须两支都在

    app = create_app(ws)
    client = TestClient(app, raise_server_exceptions=False)

    # ① 领域异常（422）⇒ InfrastructureErrorResponse
    ref422 = _ref_of(spec, "/v1/knowledge-maps", "get", "422")
    assert ref422 == "InfrastructureErrorResponse"
    _force_map_load_failure(monkeypatch, lambda: SchemaValidationError("控制面地图定义非法"))
    r = client.get("/v1/knowledge-maps")
    assert r.status_code == 422
    checked = check_shape(spec, _schemas(spec)[ref422], r.json(), ref422)
    assert checked >= 4, checked

    # ② 领域异常（500）⇒ oneOf branch[0]
    _force_map_load_failure(
        monkeypatch, lambda: KERTException("boom", error_code="INTERNAL_ERROR"))
    r = client.get("/v1/knowledge-maps")
    assert r.status_code == 500
    branch, checked = check_shape_any(spec, schema500, r.json(), "knowledge-maps.500")
    assert branch == 0, f"领域异常的 500 应命中 detail 包装分支，实为 branch[{branch}]"
    assert checked >= 4, checked

    # ③ 未捕获异常（500）⇒ oneOf branch[1]
    _force_map_load_failure(monkeypatch, lambda: RuntimeError("boom"))
    r = client.get("/v1/knowledge-maps")
    assert r.status_code == 500
    branch, checked = check_shape_any(spec, schema500, r.json(), "knowledge-maps.500")
    assert branch == 1, branch
    assert checked >= 3, checked


# --------------------------------------------------------------------------- #
# ⑦ 错误信封族 · Part B（实现补齐：未捕获异常 ⇒ 合同声明的 ErrorResponse 信封）
# --------------------------------------------------------------------------- #

#: 金丝雀串：若 500 响应体出现它，说明异常内容被回显（安全缺陷）。
LEAK_CANARY = "SECRET-CANARY-2f9c1d"


def test_unhandled_exception_returns_error_envelope(spec, ws, monkeypatch):
    """未捕获异常必须返回合同声明的 `ErrorResponse` 信封，且**不得**回显异常内容。

    修正依据：`/api/skill/execute` 的 `500` 声明为 `ErrorResponse`
    （`requestId`/`status`/`errors[]`）；实现此前落到 FastAPI 默认 500（纯文本）。
    app 级处理器见 `src/kert/api/server.py` 的 `_unhandled_exception`。
    变异自证：移除该处理器 ⇒ 本用例 FAIL（退化为纯文本 500）。
    """
    app = create_app(ws)
    service = app.state.skill_service

    def _boom(*_args, **_kwargs):
        raise RuntimeError(LEAK_CANARY)

    monkeypatch.setattr(service, "execute", _boom)
    client = TestClient(app, raise_server_exceptions=False)

    r = client.post("/api/skill/execute",
                    json={"skillId": "SP-20", "requestId": "boom-1", "request": {}})
    assert r.status_code == 500
    assert "application/json" in r.headers.get("content-type", ""), r.headers
    body = r.json()

    checked = check_shape(spec, _schemas(spec)["ErrorResponse"], body, "ErrorResponse")
    assert checked >= 3, checked
    assert body["status"] == "skill_error"
    assert body["errors"][0]["code"] == "INTERNAL_ERROR"
    assert body["requestId"], "500 必须回传 requestId 以便与日志关联"

    # (b) 安全口径：只给通用文案，不得回显异常类名或异常内容
    assert LEAK_CANARY not in r.text, "500 响应体泄漏了异常内容"
    assert "RuntimeError" not in r.text, "500 响应体泄漏了异常类名"


# --------------------------------------------------------------------------- #
# ⑨ v1.6.0 / A-6：9 条新登记路径的机械核对（三段式 + 防空转下限）
#    合同：`specs/kert-openapi-v1.yaml`（1.6.0）；实现：`src/kert/api/server.py`
#    夹具策略：数据面端点需要**已发布投影**，故复用 `test_api.py` 的全链路形态
#      （ingest → parse → extract → review → publish → projection，**不 mock 实现**）。
#    这些用例的价值：把 A-6 的 9 条"手写登记"变成**可机械证伪**的声明 ——
#    合同里少一个键（实现有、合同无）或多一个键（合同要求、实现没有）都会立刻变红。
# --------------------------------------------------------------------------- #


def _norm_path(path: str) -> str:
    """归一化路径参数**名**（合同 `{jobId}` 与实现 `{job_id}` 属命名风格差异，非集合差异）。"""
    import re as _re

    return _re.sub(r"\{[^}]+\}", "{}", path)


def _contract_v1_paths(spec: dict) -> set[str]:
    return {p for p in spec["paths"] if p.startswith("/v1/")}


#: 合同声明、实现缺失 ⇒ **必须逐条写理由**（v1.6.0 起为**空**：A-9 已把 `/v1/skills` 移除）。
CONTRACT_ONLY_EXEMPT: dict[str, str] = {}

#: 实现有、合同不声明 ⇒ **必须逐条写理由**（v1.6.0 起为**空**）。
IMPLEMENTATION_ONLY_EXEMPT: dict[str, str] = {}


@pytest.fixture(scope="module")
def chain(tmp_path_factory):
    """全链路夹具 ⇒ `(client, ws)`。9 条数据面端点的机械核对都在此工作区上进行。"""
    import pyarrow as pa
    import pyarrow.parquet as pq

    from kert.application.extract import KnowledgeExtractor
    from kert.application.ingest import Ingestor
    from kert.application.parse_doc import DocumentParserService
    from kert.application.projection import ProjectionBuilder
    from kert.application.publish import Publisher
    from kert.application.review import ReviewService
    from kert.domain import workspace as ws_mod

    ws = tmp_path_factory.mktemp("v16-chain")
    ws_mod.init_workspace(ws)
    md = ws / "p.md"
    md.write_text("# 政策\n\n产品A利率为3.5%。\n\n产品A需要材料M1。\n\n规则：利率不超过10。\n",
                  encoding="utf-8")
    r = Ingestor(ws).ingest("product", [md], "batch-v16-1")
    pr = DocumentParserService(ws).parse("product", r.batch_id)
    ex = KnowledgeExtractor(ws).extract("product", r.batch_id, run_id=pr.run_id)
    ReviewService(ws).review("product", run_id=pr.run_id,
                             object_refs=[c["path"] for c in ex.candidates],
                             decision="APPROVE", reason="ok", decided_by="r")
    Publisher(ws).publish("product", run_id=pr.run_id)
    ProjectionBuilder(ws).build("product")
    # `/v1/data/query` 读 `datasets/<name>.parquet`，而投影默认不建 `datasets/`
    # ⇒ 夹具补一张最小数据集（属**夹具构造**：不改实现、不改合同）。
    vdir = _version_dir(ws)
    (vdir / "datasets").mkdir(exist_ok=True)
    pq.write_table(pa.table({"entity_id": ["E-V16-1", "E-V16-2"], "name": ["甲", "乙"]}),
                   vdir / "datasets" / "entities.parquet")
    return TestClient(create_app(ws)), ws


def _version_dir(ws):
    return next((ws / "04_serve" / "product_knowledge").glob("version=*"))


def _first_cell(ws, filename: str, column: str):
    """取活动投影某列首个值（供构造真实路径参数，避免硬编码 UUID）。"""
    import pyarrow.parquet as pq

    table = pq.read_table(_version_dir(ws) / filename)
    return table.column(column).to_pylist()[0]


# ── ① `POST /v1/extractions`（202，**手写信封**，status=ACCEPTED）──

def test_extractions_202_shape_matches_contract(spec, chain):
    """⚠ 该端点 `status` 为 `ACCEPTED`，与其余 `/v1/*` 的 `OK` **不同义**（F8-①）。"""
    client, ws = chain
    assert _ref_of(spec, "/v1/extractions", "post", "202") == "ExtractionsAcceptedResponse"
    batch_dir = next((ws / "01_raw" / "product").glob("batch=*"))
    doc = next(batch_dir.glob("*.md"))
    r = client.post("/v1/extractions", json={
        "request_id": "REQ-V16-1", "idempotency_key": "k-v16-1", "domain": "product",
        "input": {"type": "workspace_file",
                  "path": f"01_raw/product/{batch_dir.name}/{doc.name}"},
        "extraction_types": ["ENTITY", "STATEMENT"]})
    assert r.status_code == 202, r.text
    body = r.json()
    checked = check_shape(spec, _schemas(spec)["ExtractionsAcceptedResponse"], body,
                          "ExtractionsAcceptedResponse")
    assert checked >= 8, checked  # 反空转下限：信封 5 键 + data 3 键
    assert body["status"] == "ACCEPTED"
    assert body["data"]["result_status"] == "CANDIDATE"
    assert body["data"]["publish_status"] == "NOT_PUBLISHED"


# ── ② `GET /v1/extractions/{job_id}/result` ──

def test_extraction_result_shape_matches_contract(spec):
    assert _ref_of(spec, "/v1/extractions/{job_id}/result", "get", "200") == "ExtractionResultResponse"
    client = TestClient(create_app(COMPLETED_JOB_WS))
    r = client.get(f"/v1/extractions/{COMPLETED_JOB_ID}/result")
    assert r.status_code == 200, r.text
    body = r.json()
    checked = check_shape(spec, _schemas(spec)["ExtractionResultResponse"], body,
                          "ExtractionResultResponse")
    assert checked >= 9, checked
    assert body["data"]["job_id"] == COMPLETED_JOB_ID


# ── ③ `GET /v1/entities/{entity_id}`（含查询参数 `as_of`）──

def test_entity_shape_matches_contract(spec, chain):
    client, ws = chain
    assert _ref_of(spec, "/v1/entities/{entity_id}", "get", "200") == "EntityResponse"
    assert "as_of" in {p["name"] for p in spec["paths"]["/v1/entities/{entity_id}"]["get"]["parameters"]}
    eid = _first_cell(ws, "entities.parquet", "entity_id")
    r = client.get(f"/v1/entities/{eid}")
    assert r.status_code == 200, r.text
    body = r.json()
    checked = check_shape(spec, _schemas(spec)["EntityResponse"], body, "EntityResponse")
    assert checked >= 8, checked  # 反空转下限：信封 5 键 + data 3 键
    assert body["data"]["entity"]["entity_id"] == eid
    assert body["data"]["statement_count"] == len(body["data"]["statements"])


# ── ④ `POST /v1/data/query` ──

def test_data_query_shape_matches_contract(spec, chain):
    client, _ws = chain
    assert _ref_of(spec, "/v1/data/query", "post", "200") == "DataQueryResponse"
    r = client.post("/v1/data/query", json={"request_id": "REQ-V16-DQ", "dataset": "entities"})
    assert r.status_code == 200, r.text
    body = r.json()
    checked = check_shape(spec, _schemas(spec)["DataQueryResponse"], body, "DataQueryResponse")
    assert checked >= 8, checked  # 反空转下限：信封 5 键 + data 3 键
    assert body["data"]["dataset"] == "entities"
    assert body["data"]["count"] == len(body["data"]["records"]) >= 2


# ── ⑤ `POST /v1/search` ──

def test_search_shape_matches_contract(spec, chain):
    client, _ws = chain
    assert _ref_of(spec, "/v1/search", "post", "200") == "SearchResponse"
    r = client.post("/v1/search", json={"request_id": "REQ-V16-S", "query": "利率",
                                        "mode": "FULLTEXT", "top_k": 5})
    assert r.status_code == 200, r.text
    body = r.json()
    checked = check_shape(spec, _schemas(spec)["SearchResponse"], body, "SearchResponse")
    # 信封 5 键 + data 5 键 + 至少 1 个 hit 的 9 键
    assert checked >= 19, checked
    assert body["data"]["hit_count"] == len(body["data"]["hits"]) >= 1


# ── ⑥ `POST /v1/graph/query`（`paths` 为**条件键**）──

def test_graph_query_shape_matches_contract(spec, chain):
    client, ws = chain
    assert _ref_of(spec, "/v1/graph/query", "post", "200") == "GraphQueryResponse"
    eid = _first_cell(ws, "entities.parquet", "entity_id")
    r = client.post("/v1/graph/query", json={"request_id": "REQ-V16-G",
                                             "start_entity_ids": [eid], "max_depth": 1})
    assert r.status_code == 200, r.text
    body = r.json()
    checked = check_shape(spec, _schemas(spec)["GraphQueryResponse"], body, "GraphQueryResponse")
    assert checked >= 14, checked
    data_schema = _schemas(spec)["GraphQueryResponse"]["properties"]["data"]
    # `paths` 只在 `mode=paths` 出现 ⇒ **不得**进 `required`（否则默认 neighbor 会误判缺键）
    assert "paths" not in (data_schema.get("required") or [])
    assert "paths" in data_schema["properties"]
    assert "paths" not in body["data"]
    assert body["data"]["node_count"] == len(body["data"]["nodes"])


# ── ⑦ `POST /v1/rules/evaluate` ──

def test_rules_evaluate_shape_matches_contract(spec, chain):
    client, _ws = chain
    assert _ref_of(spec, "/v1/rules/evaluate", "post", "200") == "RuleEvaluateResponse"
    r = client.post("/v1/rules/evaluate", json={"request_id": "REQ-V16-R", "facts": {"rate": 5}})
    assert r.status_code == 200, r.text
    body = r.json()
    checked = check_shape(spec, _schemas(spec)["RuleEvaluateResponse"], body, "RuleEvaluateResponse")
    assert checked >= 13, checked
    assert body["data"]["matched_rules"], body["data"]


# ── ⑧ `GET /v1/evidence/{object_id}`（`blocker` 为**条件键**）──

def test_evidence_shape_matches_contract(spec, chain):
    client, ws = chain
    assert _ref_of(spec, "/v1/evidence/{object_id}", "get", "200") == "EvidenceResponse"
    sid = _first_cell(ws, "statements.parquet", "statement_id")
    r = client.get(f"/v1/evidence/{sid}")
    assert r.status_code == 200, r.text
    body = r.json()
    checked = check_shape(spec, _schemas(spec)["EvidenceResponse"], body, "EvidenceResponse")
    assert checked >= 8, checked
    data_schema = _schemas(spec)["EvidenceResponse"]["properties"]["data"]
    assert "blocker" not in (data_schema.get("required") or [])
    assert "blocker" in data_schema["properties"]
    assert body["data"]["object_id"] == sid
    assert body["data"]["chain"]


# ── ⑨ `GET /v1/catalog` ──

def test_catalog_shape_matches_contract(spec, chain):
    client, _ws = chain
    assert _ref_of(spec, "/v1/catalog", "get", "200") == "CatalogResponse"
    body = client.get("/v1/catalog").json()
    checked = check_shape(spec, _schemas(spec)["CatalogResponse"], body, "CatalogResponse")
    assert checked >= 7, checked
    assert body["data"]["projections"], body["data"]


# --------------------------------------------------------------------------- #
# ⑩ §6 集合级防复发断言（A-6 的交付条件 ③）
# --------------------------------------------------------------------------- #

def test_contract_v1_paths_equal_implemented_routes(spec, ws):
    """**集合级**断言：合同 `/v1/*` 路径集合 == 实现 `app.routes` 的 `/v1/*` 集合（± 显式豁免）。

    为什么必须有这一条：**逐用例形状核对永远发现不了"实现有、合同无"** ——
    没有用例就没有核对对象（这正是 F8 的成因）。只有集合级断言能在
    "新增路由却忘记登记" 或 "删了实现却留着声明" 时**立刻变红**。

    豁免纪律：两边豁免清单**都**必须是 `路径 -> 非空理由`；空串豁免视为违规
    （不得以"豁免"为名绕过断言）。
    """
    app = create_app(ws)
    impl = {_norm_path(getattr(route, "path", "") or "") for route in app.routes}
    impl = {p for p in impl if p.startswith("/v1/")}
    contract = {_norm_path(p) for p in _contract_v1_paths(spec)}

    for name, reason in {**CONTRACT_ONLY_EXEMPT, **IMPLEMENTATION_ONLY_EXEMPT}.items():
        assert reason.strip(), f"豁免 {name} 必须逐条写明理由（不得空串豁免）"

    only_contract = sorted(contract - impl - set(CONTRACT_ONLY_EXEMPT))
    only_impl = sorted(impl - contract - set(IMPLEMENTATION_ONLY_EXEMPT))
    assert not only_contract, f"合同声明但实现缺失（反向缺口族，见 A-9）：{only_contract}"
    assert not only_impl, f"实现有但合同未声明（F8 正向缺口族，见 A-6）：{only_impl}"
    # 防空转：本断言不得在"两边都空"的退化情形下通过
    assert len(contract) >= 14, f"防空转：合同 /v1/* 路径集合异常（{sorted(contract)}）"
    assert len(impl) >= 14, f"防空转：实现 /v1/* 路由集合异常（{sorted(impl)}）"
