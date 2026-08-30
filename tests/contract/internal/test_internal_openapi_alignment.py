"""JR-1：内部 OpenAPI 契约与 JSON Schema 一致性测试。

内部契约由两部分组成：``openapi/dkws-skill-runtime-internal-v1.yaml``（传输面）
与 ``schemas/*.json``（数据面）。OpenAPI 以相对 ``$ref`` 直接引用 Schema 文件，
因此必须保证：引用目标真实存在、全部引用落在受控 Schema 白名单内、
且传输面声明的错误语义与数据面 ``RuntimeError`` 契约可对齐。
"""

from __future__ import annotations

from typing import Any

import pytest
import yaml

from .conftest import OPENAPI_FILE, SCHEMA_DIR, SCHEMA_FILES


@pytest.fixture(scope="module")
def openapi() -> dict:
    """加载内部 OpenAPI 文档。"""
    return yaml.safe_load(OPENAPI_FILE.read_text(encoding="utf-8"))


def _collect_refs(node: Any) -> list[str]:
    """递归收集文档中所有 ``$ref`` 字符串。"""
    found: list[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "$ref" and isinstance(value, str):
                found.append(value)
            else:
                found.extend(_collect_refs(value))
    elif isinstance(node, list):
        for item in node:
            found.extend(_collect_refs(item))
    return found


class TestOpenApiParseable:
    """OpenAPI 文档可解析且结构完整（JR-1 §6.1）。"""

    def test_file_exists(self):
        """内部 OpenAPI 文件存在。"""
        assert OPENAPI_FILE.is_file(), f"缺失 {OPENAPI_FILE}"

    def test_is_openapi_3(self, openapi):
        """声明为 OpenAPI 3.x。"""
        assert str(openapi["openapi"]).startswith("3.")

    def test_has_info_and_paths(self, openapi):
        """含 info 与非空 paths。"""
        assert openapi["info"]["title"]
        assert openapi["info"]["version"]
        assert openapi["paths"], "OpenAPI 未定义任何路径"

    def test_contract_version_matches_schema_examples(self, openapi):
        """OpenAPI 版本与契约候选版本一致。"""
        assert openapi["info"]["version"] == "1.0.0-candidate"

    def test_all_paths_are_internal_only(self, openapi):
        """所有路径都在 ``/internal/`` 前缀下（内部契约不对外暴露）。"""
        offenders = [p for p in openapi["paths"] if not p.startswith("/internal/")]
        assert not offenders, f"内部契约出现非 /internal 路径: {offenders}"

    def test_servers_are_loopback_only(self, openapi):
        """服务器地址限定回环，Java Runtime 不对外监听。"""
        for server in openapi.get("servers", []):
            url = server["url"]
            assert "127.0.0.1" in url or "localhost" in url, (
                f"内部 Runtime 不应对外暴露: {url}"
            )

    def test_execute_endpoint_requires_auth(self, openapi):
        """执行端点受安全方案保护。"""
        execute = openapi["paths"]["/internal/v1/runtime/execute"]["post"]
        # 未局部覆盖时继承全局 security
        effective = execute.get("security", openapi.get("security"))
        assert effective, "执行端点缺少安全声明"


class TestOpenApiRefsResolveToSchemas:
    """OpenAPI 的 ``$ref`` 全部指向受控 Schema 文件。"""

    def test_refs_present(self, openapi):
        """OpenAPI 确实通过 ``$ref`` 复用 Schema，而非内联重复定义。"""
        assert _collect_refs(openapi["paths"]), "paths 中未发现任何 $ref"

    def test_every_schema_ref_target_exists(self, openapi):
        """每个指向 schemas 目录的 ``$ref`` 目标文件真实存在。"""
        missing = []
        for ref in _collect_refs(openapi):
            if ref.startswith("#") or "schemas/" not in ref:
                continue
            target = (OPENAPI_FILE.parent / ref).resolve()
            if not target.is_file():
                missing.append(ref)
        assert not missing, f"OpenAPI 引用了不存在的 Schema: {missing}"

    def test_every_schema_ref_is_whitelisted(self, openapi):
        """所有被引用的 Schema 都在受控白名单内（无影子契约）。"""
        outside = []
        for ref in _collect_refs(openapi):
            if ref.startswith("#") or "schemas/" not in ref:
                continue
            target = (OPENAPI_FILE.parent / ref).resolve()
            if target.parent != SCHEMA_DIR.resolve() or target.name not in SCHEMA_FILES:
                outside.append(ref)
        assert not outside, f"OpenAPI 引用了白名单外的 Schema: {outside}"

    def test_execute_uses_plan_and_result(self, openapi):
        """执行端点请求体用 ExecutionPlan，200 响应用 ExecutionResult。"""
        execute = openapi["paths"]["/internal/v1/runtime/execute"]["post"]
        request_ref = execute["requestBody"]["content"]["application/json"]["schema"][
            "$ref"
        ]
        response_ref = execute["responses"]["200"]["content"]["application/json"][
            "schema"
        ]["$ref"]
        assert request_ref.endswith("execution-plan.schema.json")
        assert response_ref.endswith("execution-result.schema.json")

    def test_health_uses_runtime_capabilities(self, openapi):
        """健康端点 200 响应用 RuntimeCapabilities。"""
        health = openapi["paths"]["/internal/v1/runtime/health"]["get"]
        ref = health["responses"]["200"]["content"]["application/json"]["schema"][
            "$ref"
        ]
        assert ref.endswith("runtime-capabilities.schema.json")


class TestOpenApiErrorSemantics:
    """传输面错误码与数据面 ``RuntimeError`` 语义对齐。"""

    def test_execute_declares_governance_status_codes(self, openapi):
        """执行端点声明治理必需的错误状态码。"""
        responses = openapi["paths"]["/internal/v1/runtime/execute"]["post"][
            "responses"
        ]
        for code in ("401", "408", "409", "422", "503"):
            assert code in responses, f"执行端点缺少 {code} 响应声明"

    def test_idempotency_conflict_is_409(self, openapi):
        """幂等冲突映射到 409，与 ``IDEMPOTENCY_CONFLICT`` 语义一致。"""
        responses = openapi["paths"]["/internal/v1/runtime/execute"]["post"][
            "responses"
        ]
        assert "idempotency" in responses["409"]["description"].lower()

    def test_deadline_exceeded_is_408(self, openapi):
        """超时映射到 408，与 ``DEADLINE_EXCEEDED`` 语义一致。"""
        responses = openapi["paths"]["/internal/v1/runtime/execute"]["post"][
            "responses"
        ]
        assert "deadline" in responses["408"]["description"].lower()
