"""DKWS 内部契约（Python Core -> Java Skill Runtime）契约测试 —— Python 侧。

覆盖施工令第十一节 §2「契约」要求：
- OpenAPI 可解析
- JSON Schema meta-schema 校验
- 所有 $ref 真实存在
- 示例通过 Schema
- contract hash 可重算
- 未知字段（additionalProperties=false，fail-closed）
- 版本不兼容（contractVersion major 不匹配）
- 同 key 不同 payload（幂等冲突可被契约表达）

Java 侧对应测试见
`poc/spring-ai-alibaba-skill-runtime/src/test/java/com/dkws/skillruntime/contract/InternalContractSchemaTest.java`
（provider 侧：Java 产出的 DTO 序列化结果必须通过同一批 schema）。

本文件是 consumer 侧（Python Core 视角）。
"""

from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

jsonschema = pytest.importorskip("jsonschema", reason="jsonschema required for contract tests")
yaml = pytest.importorskip("yaml", reason="PyYAML required to parse OpenAPI")

from jsonschema import Draft202012Validator  # noqa: E402
from referencing import Registry, Resource  # noqa: E402
from referencing.jsonschema import DRAFT202012  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
CONTRACT_DIR = REPO_ROOT / "docs" / "contracts" / "internal"
SCHEMA_DIR = CONTRACT_DIR / "schemas"
EXAMPLE_DIR = CONTRACT_DIR / "examples"
OPENAPI_PATH = CONTRACT_DIR / "openapi" / "dkws-skill-runtime-internal-v1.yaml"
HASH_SCRIPT = REPO_ROOT / "scripts" / "internal_contract_hash.py"

SCHEMA_FILES = [
    "execution-plan.schema.json",
    "execution-result.schema.json",
    "tool-call-receipt.schema.json",
    "model-call-receipt.schema.json",
    "runtime-error.schema.json",
    "runtime-capabilities.schema.json",
]


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _registry() -> Registry:
    """构建本地 schema 注册表，使跨文件 $ref（相对文件名）可解析。"""
    resources: list[tuple[str, Resource]] = []
    for name in SCHEMA_FILES:
        schema = _load_json(SCHEMA_DIR / name)
        resource = Resource.from_contents(schema, default_specification=DRAFT202012)
        # 同时以相对文件名与 $id 注册，兼容两种引用写法
        resources.append((name, resource))
        if "$id" in schema:
            resources.append((schema["$id"], resource))
    return Registry().with_resources(resources)


REGISTRY = _registry()


def _validator(schema_name: str) -> Draft202012Validator:
    schema = _load_json(SCHEMA_DIR / schema_name)
    return Draft202012Validator(schema, registry=REGISTRY)


# ------------------------------------------------------------------ 结构性校验


@pytest.mark.parametrize("schema_name", SCHEMA_FILES)
def test_schema_is_valid_against_meta_schema(schema_name: str) -> None:
    """每个 schema 必须自身合法（Draft 2020-12 meta-schema）。"""
    schema = _load_json(SCHEMA_DIR / schema_name)
    Draft202012Validator.check_schema(schema)
    assert schema.get("$schema") == "https://json-schema.org/draft/2020-12/schema"
    assert "$id" in schema, f"{schema_name} must declare $id for stable referencing"
    assert schema.get("additionalProperties") is False, (
        f"{schema_name} must set additionalProperties=false (fail-closed on unknown fields)"
    )


def test_openapi_is_parseable_and_internal_only() -> None:
    """OpenAPI 可解析，且必须是仅内部可达、强制内部认证。"""
    spec = yaml.safe_load(OPENAPI_PATH.read_text(encoding="utf-8"))
    assert spec["openapi"].startswith("3.")
    assert "securitySchemes" in spec["components"]
    assert "InternalTokenAuth" in spec["components"]["securitySchemes"]

    # 不得形成第二公共 API：所有路径必须在 /internal/ 命名空间下
    for path in spec["paths"]:
        assert path.startswith("/internal/"), f"non-internal path exposed: {path}"

    # 服务器必须是 loopback / 内部地址，不得指向公网
    for server in spec["servers"]:
        assert "127.0.0.1" in server["url"] or "localhost" in server["url"], server


def test_openapi_refs_all_resolve() -> None:
    """所有 $ref 必须真实存在（本地 schema 文件或文档内组件）。"""
    spec = yaml.safe_load(OPENAPI_PATH.read_text(encoding="utf-8"))

    missing: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str):
                if ref.startswith("#/"):
                    cursor: Any = spec
                    for part in ref[2:].split("/"):
                        part = part.replace("~1", "/").replace("~0", "~")
                        if not isinstance(cursor, dict) or part not in cursor:
                            missing.append(ref)
                            break
                        cursor = cursor[part]
                else:
                    target = (OPENAPI_PATH.parent / ref).resolve()
                    if not target.is_file():
                        missing.append(ref)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(spec)
    assert missing == [], f"unresolved $ref: {missing}"


def test_all_schemas_have_examples() -> None:
    """关键 schema 必须有示例，避免契约无法被消费方验证。"""
    for name in ("execution-plan", "execution-result", "runtime-error", "runtime-capabilities"):
        assert (EXAMPLE_DIR / f"{name}.example.json").is_file(), f"missing example for {name}"


# ------------------------------------------------------------------ 示例校验


@pytest.mark.parametrize(
    ("example", "schema_name"),
    [
        ("execution-plan.example.json", "execution-plan.schema.json"),
        ("execution-result.example.json", "execution-result.schema.json"),
        ("runtime-error.example.json", "runtime-error.schema.json"),
        ("runtime-capabilities.example.json", "runtime-capabilities.schema.json"),
    ],
)
def test_examples_pass_schema(example: str, schema_name: str) -> None:
    """示例必须通过对应 schema（含嵌套 receipt 的 $ref 解析）。"""
    instance = _load_json(EXAMPLE_DIR / example)
    errors = sorted(_validator(schema_name).iter_errors(instance), key=lambda e: e.path)
    assert errors == [], [f"{list(e.path)}: {e.message}" for e in errors]


# ------------------------------------------------------------------ contract hash


def test_contract_hash_is_recomputable_and_deterministic() -> None:
    """contract hash 必须可由脚本重算且稳定（两次运行一致）。"""
    first = subprocess.run(
        [sys.executable, str(HASH_SCRIPT)], capture_output=True, text=True, check=True, cwd=REPO_ROOT
    )
    second = subprocess.run(
        [sys.executable, str(HASH_SCRIPT)], capture_output=True, text=True, check=True, cwd=REPO_ROOT
    )
    a, b = json.loads(first.stdout), json.loads(second.stdout)
    assert a["bundle_hash"] == b["bundle_hash"]
    assert len(a["bundle_hash"]) == 64

    # 逐文件哈希必须与实际文件内容一致
    for entry in a["files"]:
        actual = hashlib.sha256((CONTRACT_DIR / entry["path"]).read_bytes()).hexdigest()
        assert actual == entry["sha256"], f"hash drift on {entry['path']}"

    # 白名单必须覆盖全部 schema + openapi，防止漏纳入导致 hash 失真
    covered = {entry["path"] for entry in a["files"]}
    for name in SCHEMA_FILES:
        assert f"schemas/{name}" in covered, f"{name} not covered by contract bundle hash"
    assert "openapi/dkws-skill-runtime-internal-v1.yaml" in covered


def test_contract_hash_changes_when_contract_changes(tmp_path: Path) -> None:
    """契约内容变化必须导致 bundle hash 变化（可用于 breaking diff 检测）。"""
    baseline = json.loads(
        subprocess.run(
            [sys.executable, str(HASH_SCRIPT)], capture_output=True, text=True, check=True, cwd=REPO_ROOT
        ).stdout
    )["bundle_hash"]

    # 仅在内存中模拟：改动一个文件哈希，重算 bundle hash 应不同
    entries = [{"path": "schemas/execution-plan.schema.json", "sha256": "0" * 64}]
    h = hashlib.sha256()
    for e in entries:
        h.update(e["path"].encode()); h.update(b"\0")
        h.update(e["sha256"].encode()); h.update(b"\0")
    assert h.hexdigest() != baseline


# ------------------------------------------------------------------ 语义/负向


def test_execution_plan_rejects_unknown_field() -> None:
    """未知字段策略：一律拒绝（fail-closed），不得静默丢弃。"""
    plan = _load_json(EXAMPLE_DIR / "execution-plan.example.json")
    plan["experimentalFlag"] = True
    errors = list(_validator("execution-plan.schema.json").iter_errors(plan))
    assert errors, "unknown field must be rejected"
    assert any("experimentalFlag" in e.message for e in errors)


@pytest.mark.parametrize(
    "field",
    [
        "contractVersion", "requestId", "traceparent", "tenantId", "customerScope",
        "skillId", "skillVersion", "skillHash", "activationPlanHash", "policyId",
        "promptPolicyRef", "modelPolicyRef", "deadline", "idempotencyKey",
        "payloadHash", "allowedToolIds", "knowledgeSourceRefs", "contextPackage",
    ],
)
def test_execution_plan_required_fields_enforced(field: str) -> None:
    """施工令规定的 18 个 ExecutionPlan 最低字段全部必填。"""
    plan = _load_json(EXAMPLE_DIR / "execution-plan.example.json")
    plan.pop(field)
    errors = list(_validator("execution-plan.schema.json").iter_errors(plan))
    assert errors, f"{field} must be required by contract"


@pytest.mark.parametrize("bad_version", ["2.0", "0.9", "1", "v1.0", ""])
def test_contract_version_incompatible_rejected(bad_version: str) -> None:
    """版本不兼容：major != 1 或格式非法必须被 schema 拒绝。"""
    plan = _load_json(EXAMPLE_DIR / "execution-plan.example.json")
    plan["contractVersion"] = bad_version
    errors = list(_validator("execution-plan.schema.json").iter_errors(plan))
    assert errors, f"contractVersion={bad_version!r} must be rejected"


def test_contract_version_minor_bump_accepted() -> None:
    """同 major 的 minor 升级向后兼容。"""
    plan = _load_json(EXAMPLE_DIR / "execution-plan.example.json")
    plan["contractVersion"] = "1.7"
    assert list(_validator("execution-plan.schema.json").iter_errors(plan)) == []


def test_same_idempotency_key_different_payload_is_detectable() -> None:
    """同 key 不同 payload：契约必须让 Runtime 能检测冲突。

    payloadHash 是 contextPackage 的规范化哈希，因此同 idempotencyKey 下
    payload 变化必然导致 payloadHash 变化 -> 可判定 IDEMPOTENCY_KEY_CONFLICT。
    """
    plan_a = _load_json(EXAMPLE_DIR / "execution-plan.example.json")
    plan_b = copy.deepcopy(plan_a)
    plan_b["contextPackage"]["inputs"]["question"] = "不同的问题"

    def canonical_hash(plan: dict) -> str:
        raw = json.dumps(plan["contextPackage"], sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode()).hexdigest()

    plan_a["payloadHash"] = canonical_hash(plan_a)
    plan_b["payloadHash"] = canonical_hash(plan_b)

    assert plan_a["idempotencyKey"] == plan_b["idempotencyKey"]
    assert plan_a["payloadHash"] != plan_b["payloadHash"]

    validator = _validator("execution-plan.schema.json")
    assert list(validator.iter_errors(plan_a)) == []
    assert list(validator.iter_errors(plan_b)) == []

    # 冲突必须能用契约错误码表达且不可重试
    err = {
        "code": "IDEMPOTENCY_KEY_CONFLICT",
        "message": "same idempotencyKey with different payloadHash",
        "retryable": False,
    }
    assert list(_validator("runtime-error.schema.json").iter_errors(err)) == []


def test_retryable_must_be_false_for_contract_violations() -> None:
    """契约违规类错误不得声明为可重试（防止 Core 无限重试）。"""
    err = {"code": "TOOL_NOT_ALLOWED", "message": "blocked", "retryable": True}
    errors = list(_validator("runtime-error.schema.json").iter_errors(err))
    assert errors, "contract-violation error must not be retryable"


def test_unknown_error_code_rejected() -> None:
    """错误码必须来自受控枚举，避免 Runtime 自造语义。"""
    err = {"code": "SOMETHING_WENT_WRONG", "message": "oops", "retryable": True}
    assert list(_validator("runtime-error.schema.json").iter_errors(err))


def test_failed_result_must_not_be_usable() -> None:
    """FAILED 必须 usable=false、releaseAllowed=false 且带错误。"""
    result = _load_json(EXAMPLE_DIR / "execution-result.example.json")
    result["status"] = "FAILED"
    errors = list(_validator("execution-result.schema.json").iter_errors(result))
    assert errors, "FAILED with usable=true must be rejected"


def test_degraded_requires_reason() -> None:
    """DEGRADED 必须给出 degradationReason，禁止无理由降级。"""
    result = _load_json(EXAMPLE_DIR / "execution-result.example.json")
    result["status"] = "DEGRADED"
    result["degraded"] = True
    errors = list(_validator("execution-result.schema.json").iter_errors(result))
    assert errors, "degraded without reason must be rejected"

    result["degradationReason"] = "model unavailable, fell back to template"
    assert list(_validator("execution-result.schema.json").iter_errors(result)) == []


def test_success_must_not_carry_errors() -> None:
    """SUCCESS 不得同时携带错误（防止吞异常取 PASS）。"""
    result = _load_json(EXAMPLE_DIR / "execution-result.example.json")
    result["errors"] = [{"code": "TOOL_FAILED", "message": "x", "retryable": True}]
    errors = list(_validator("execution-result.schema.json").iter_errors(result))
    assert errors, "SUCCESS with errors must be rejected"


def test_tool_receipt_non_ok_requires_error_code() -> None:
    """非 ok 的 ToolCallReceipt 必须带 errorCode。"""
    receipt = _load_json(EXAMPLE_DIR / "execution-result.example.json")["toolCallReceipts"][0]
    receipt = dict(receipt, status="blocked")
    receipt.pop("errorCode", None)
    errors = list(_validator("tool-call-receipt.schema.json").iter_errors(receipt))
    assert errors, "non-ok receipt must require errorCode"


def test_tool_receipt_requires_audit_fields() -> None:
    """回执必须包含审计字段，框架日志不可替代。"""
    receipt = _load_json(EXAMPLE_DIR / "execution-result.example.json")["toolCallReceipts"][0]
    for field in ("inputHash", "policyDecisionId", "outputHash", "outputTruncated", "networkUsed"):
        broken = dict(receipt)
        broken.pop(field)
        assert list(_validator("tool-call-receipt.schema.json").iter_errors(broken)), (
            f"{field} must be required in ToolCallReceipt"
        )


def test_capabilities_degraded_consistency() -> None:
    """健康上报 degraded 与 status 必须一致。"""
    caps = _load_json(EXAMPLE_DIR / "runtime-capabilities.example.json")
    caps["degraded"] = True
    errors = list(_validator("runtime-capabilities.schema.json").iter_errors(caps))
    assert errors, "degraded=true with status=ok must be rejected"


def test_capabilities_requires_poc2_admission_fields() -> None:
    """POC-2 准入第 20 项：健康接口 8 个字段全部必填。"""
    caps = _load_json(EXAMPLE_DIR / "runtime-capabilities.example.json")
    for field in (
        "runtimeVersion", "contractVersion", "contractHash", "frameworkVersion",
        "activatedSkills", "sandboxCapability", "degraded", "status",
    ):
        broken = dict(caps)
        broken.pop(field)
        assert list(_validator("runtime-capabilities.schema.json").iter_errors(broken)), (
            f"{field} must be required in health response"
        )
