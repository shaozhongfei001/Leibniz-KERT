"""合同**形状级**核对：`/v1/health`（D-42 → 合同 v1.6.2）。

存在理由（实测缺陷，2026-09-17）：`HealthResponse` 长期声明为**扁平**对象
（`required: [status, timestamp, skills]`、`status` 小写 `[ok, degraded]`），而实现返回的是
**标准信封**（`request_id`/`status`/`data`/`errors`/`meta`）+ `data = {status: OK|DEGRADED,
service_version, data_version, runtime{8 键}}` ⇒ **形状不同**。此前**值域**核对
（`tests/unit/test_contract_enum_single_source.py`）只能发现 enum 漂移，**形状级**漂移无判据。

本用例两向都判（这是重点）：
① **实现 == 声明**：顶层 / `data` / `data.runtime` 三层的键集合逐层相等，且**实际取值 ⊆ 声明 enum**；
② **判据本身有牙**：把"多一个键 / 少一个必填键 / 取值越界"的合成响应喂给同一个比对函数，
   **必须报出**（否则本用例只是装饰）。

非声明：本用例只覆盖 `/v1/health` 一处（形状级核对的**试点**）；其余端点仍只有值域核对。
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from fastapi.testclient import TestClient

SPEC = Path(__file__).resolve().parents[2] / "specs" / "kert-openapi-v1.yaml"


def _health_schema() -> dict:
    doc = yaml.safe_load(SPEC.read_text(encoding="utf-8"))
    return doc["components"]["schemas"]["HealthResponse"]


def compare_shape(actual: dict, declared: dict) -> list[str]:
    """把实测响应与合同声明逐项比对；返回问题清单（空 = 一致）。

    **两向**：实现多出未声明的键、实现缺少声明必填的键、取值不在声明 enum 内 —— 都报。
    """
    problems: list[str] = []
    props = set((declared.get("properties") or {}).keys())
    required = set(declared.get("required") or [])
    got = set(actual.keys())
    extra = got - props
    missing = required - got
    if extra:
        problems.append("实现多出未声明键: %s" % sorted(extra))
    if missing:
        problems.append("实现缺少声明必填键: %s" % sorted(missing))
    for key, sub in (declared.get("properties") or {}).items():
        if key in actual and isinstance(sub, dict):
            enum = sub.get("enum")
            if enum is not None and actual[key] not in enum:
                problems.append("键 %s 取值 %r 不在声明 enum %s 内" % (key, actual[key], enum))
    return problems


@pytest.fixture
def health_body(ws) -> dict:
    """真建 app 打一发 `/v1/health`（不 mock 实现，避免"自己跟自己比"）。"""
    from kert.api.server import create_app

    client = TestClient(create_app(ws, service_id="contract_shape_probe"))
    resp = client.get("/v1/health")
    assert resp.status_code == 200, resp.text
    return resp.json()


# ── ① 实现 == 声明 ──


def test_envelope_shape_matches_contract(health_body: dict) -> None:
    """顶层信封：键集合与声明一致，且信封 `status` 的取值**已被合同登记**。"""
    schema = _health_schema()
    assert compare_shape(health_body, schema) == []
    # 信封 status 实现恒为 "OK"；v1.6.2 前它**不在任何 enum 内**（客户端会收到未声明的值）⇒ 钉住。
    assert health_body["status"] == "OK"
    assert schema["properties"]["status"]["enum"] == ["OK"]


def test_data_shape_matches_contract(health_body: dict) -> None:
    """`data`：四键、闭集，`status` 取值 ∈ 声明 enum。"""
    schema = _health_schema()["properties"]["data"]
    data = health_body["data"]
    assert compare_shape(data, schema) == []
    assert data["status"] in schema["properties"]["status"]["enum"]


def test_runtime_shape_matches_contract(health_body: dict) -> None:
    """`data.runtime`：实现是**字面量字典** ⇒ 与声明逐键相等（八键）。"""
    declared = _health_schema()["properties"]["data"]["properties"]["runtime"]
    runtime = health_body["data"]["runtime"]
    assert set(runtime) == set(declared["properties"])
    assert set(declared["required"]) == set(runtime)
    assert compare_shape(runtime, declared) == []


def test_data_version_may_be_null_but_is_declared_nullable(health_body: dict) -> None:
    """`data_version` 未就绪时为 null ⇒ 合同必须声明 nullable（否则形状核对会误判）。"""
    declared = _health_schema()["properties"]["data"]["properties"]["data_version"]
    assert declared.get("nullable") is True
    assert health_body["data"]["data_version"] is None or isinstance(
        health_body["data"]["data_version"], str
    )


# ── ② 判据有牙（合成响应必须被报出）──


def test_detector_flags_undeclared_extra_key(health_body: dict) -> None:
    problems = compare_shape({**health_body, "unexpected_key": 1}, _health_schema())
    assert problems and any("多出未声明键" in p for p in problems), problems


def test_detector_flags_missing_required_key(health_body: dict) -> None:
    schema = _health_schema()
    body = {k: v for k, v in health_body.items() if k != "meta"}
    problems = compare_shape(body, schema)
    assert problems and any("缺少声明必填键" in p for p in problems), problems


def test_detector_flags_enum_violation(health_body: dict) -> None:
    """**这条正是原始缺陷的形态**：实现若把信封 status 写成小写 `ok`，必须被判据逮住。"""
    problems = compare_shape({**health_body, "status": "ok"}, _health_schema())
    assert problems and any("不在声明 enum" in p for p in problems), problems


def test_detector_would_have_caught_the_original_defect(health_body: dict) -> None:
    """回归钉子：旧声明（扁平 `status/timestamp/skills`）喂进来必须报"多键 + 缺键"。"""
    old_declared = {
        "required": ["status", "timestamp", "skills"],
        "properties": {
            "status": {"enum": ["ok", "degraded"]},
            "timestamp": {"type": "string"},
            "skills": {"type": "array"},
        },
    }
    problems = compare_shape(health_body, old_declared)
    assert any("多出未声明键" in p for p in problems), problems
    assert any("缺少声明必填键" in p for p in problems), problems
