"""JR-1：内部契约 Schema 与示例一致性测试（Python consumer 侧）。

对应任务包 JR-1 §6.2。验证 Python Core 作为内部契约消费者，
对 ``docs/contracts/internal/`` 的 6 份 Schema 具备可验证的消费能力。
"""

from __future__ import annotations

import json

import pytest
from jsonschema import Draft202012Validator

from .conftest import (
    EXAMPLE_DIR,
    SCHEMA_DIR,
    SCHEMA_FILES,
    assert_valid,
    build_validator,
    load_example,
    load_schema,
)

#: Schema 文件 → 该 Schema 下所有应通过的示例文件。
SCHEMA_EXAMPLES: dict[str, tuple[str, ...]] = {
    "execution-plan.schema.json": (
        "execution-plan.valid.json",
        "execution-plan.minimal.json",
    ),
    "execution-result.schema.json": (
        "execution-result.valid.json",
        "execution-result.degraded.json",
    ),
    "tool-call-receipt.schema.json": (
        "tool-call-receipt.valid.json",
        "tool-call-receipt.blocked.json",
    ),
    "model-call-receipt.schema.json": (
        "model-call-receipt.valid.json",
        "model-call-receipt.error.json",
    ),
    "runtime-error.schema.json": (
        "runtime-error.idempotency-conflict.json",
        "runtime-error.deadline-exceeded.json",
    ),
    "runtime-capabilities.schema.json": (
        "runtime-capabilities.valid.json",
        "runtime-capabilities.minimal.json",
    ),
}

_ALL_PAIRS = [
    (schema, example)
    for schema, examples in SCHEMA_EXAMPLES.items()
    for example in examples
]


class TestSchemaFilesSelfConsistency:
    """Schema 文件本身可解析、合法且约定一致（JR-1 §6.1）。"""

    def test_all_six_schemas_exist(self):
        """6 份内部契约 Schema 全部存在。"""
        missing = [n for n in SCHEMA_FILES if not (SCHEMA_DIR / n).is_file()]
        assert not missing, f"缺失 Schema: {missing}"

    def test_schema_dir_has_no_unregistered_file(self):
        """Schema 目录不含未登记文件（防止契约漂移）。"""
        on_disk = {p.name for p in SCHEMA_DIR.glob("*.json")}
        assert on_disk == set(SCHEMA_FILES), (
            f"Schema 目录与白名单不一致: 多余={on_disk - set(SCHEMA_FILES)}, "
            f"缺失={set(SCHEMA_FILES) - on_disk}"
        )

    @pytest.mark.parametrize("name", SCHEMA_FILES)
    def test_schema_is_parseable_json(self, name):
        """每份 Schema 都是合法 JSON。"""
        raw = (SCHEMA_DIR / name).read_text(encoding="utf-8")
        assert isinstance(json.loads(raw), dict)

    @pytest.mark.parametrize("name", SCHEMA_FILES)
    def test_schema_is_valid_draft_2020_12(self, name):
        """每份 Schema 自身符合 Draft 2020-12 元 Schema。"""
        schema = load_schema(name)
        assert schema.get("$schema") == (
            "https://json-schema.org/draft/2020-12/schema"
        )
        Draft202012Validator.check_schema(schema)

    @pytest.mark.parametrize("name", SCHEMA_FILES)
    def test_schema_closes_unknown_fields(self, name):
        """每份 Schema 都声明 ``additionalProperties: false``（未知字段策略）。"""
        assert load_schema(name).get("additionalProperties") is False

    @pytest.mark.parametrize("name", SCHEMA_FILES)
    def test_schema_declares_required(self, name):
        """每份 Schema 都声明非空 ``required``。"""
        required = load_schema(name).get("required")
        assert isinstance(required, list) and required


class TestExamplesPassSchema:
    """全部示例通过对应 Schema（JR-1 §6.2 / §7）。"""

    def test_example_dir_fully_covered(self):
        """examples 目录中每个文件都被测试登记，无遗漏。"""
        on_disk = {p.name for p in EXAMPLE_DIR.glob("*.json")}
        registered = {ex for exs in SCHEMA_EXAMPLES.values() for ex in exs}
        assert on_disk == registered, (
            f"示例登记不一致: 未登记={on_disk - registered}, "
            f"缺文件={registered - on_disk}"
        )

    @pytest.mark.parametrize(("schema", "example"), _ALL_PAIRS)
    def test_example_matches_schema(self, schema, example):
        """示例通过其 Schema 校验。"""
        assert_valid(schema, load_example(example))


class TestExecutionPlanConsumption:
    """ExecutionPlan 请求示例的消费语义。"""

    def test_full_plan_carries_all_control_fields(self):
        """完整 Plan 携带控制面必需字段。"""
        plan = load_example("execution-plan.valid.json")
        for field in (
            "contractVersion",
            "requestId",
            "tenantId",
            "skillHash",
            "activationPlanHash",
            "policyId",
            "deadline",
            "idempotencyKey",
            "payloadHash",
            "allowedToolIds",
        ):
            assert field in plan, f"ExecutionPlan 缺少控制字段 {field}"

    def test_minimal_plan_only_required_fields(self):
        """最小 Plan 仅含 required 字段，仍然通过校验。"""
        schema = load_schema("execution-plan.schema.json")
        plan = load_example("execution-plan.minimal.json")
        assert set(plan) == set(schema["required"])
        assert_valid("execution-plan.schema.json", plan)

    def test_empty_allowed_tool_ids_is_valid(self):
        """``allowedToolIds`` 允许空数组（零工具授权）。"""
        plan = load_example("execution-plan.minimal.json")
        assert plan["allowedToolIds"] == []
        assert_valid("execution-plan.schema.json", plan)


class TestExecutionResultConsumption:
    """ExecutionResult 响应示例的消费语义。"""

    def test_success_result_is_usable_and_releasable(self):
        """SUCCESS 结果可用且允许放行。"""
        result = load_example("execution-result.valid.json")
        assert result["status"] == "SUCCESS"
        assert result["usable"] is True
        assert result["releaseAllowed"] is True
        assert result["degraded"] is False

    def test_degraded_result_blocks_release(self):
        """DEGRADED 结果必须携带降级原因且不允许放行。"""
        result = load_example("execution-result.degraded.json")
        assert result["status"] == "DEGRADED"
        assert result["degraded"] is True
        assert result["releaseAllowed"] is False
        assert result["degradationReason"]

    def test_nested_receipts_resolved_via_ref(self):
        """嵌套回执通过相对 ``$ref`` 解析并被实际校验。"""
        result = load_example("execution-result.valid.json")
        assert result["toolCallReceipts"], "示例应含至少一条工具回执"
        assert result["modelCallReceipts"], "示例应含至少一条模型回执"

        broken = json.loads(json.dumps(result))
        # 破坏嵌套回执的枚举值，若 $ref 未生效则不会报错
        broken["toolCallReceipts"][0]["status"] = "NOT_A_STATUS"
        validator = build_validator("execution-result.schema.json")
        errors = list(validator.iter_errors(broken))
        assert errors, "嵌套 $ref 未生效：非法子对象未被拒绝"
        assert any("toolCallReceipts" in list(e.absolute_path) for e in errors)

    def test_empty_collections_are_arrays_not_null(self):
        """空集合返回 ``[]`` 而非 ``null``。"""
        result = load_example("execution-result.degraded.json")
        assert result["toolCallReceipts"] == []
        assert result["errors"], "降级结果应携带错误明细"


class TestReceiptConsumption:
    """工具/模型回执消费语义。"""

    def test_tool_receipt_success_carries_evidence(self):
        """成功工具回执携带可审计证据字段。"""
        receipt = load_example("tool-call-receipt.valid.json")
        assert receipt["status"] == "ok"
        assert receipt["exitCode"] == 0
        for field in ("inputHash", "outputHash", "policyDecisionId"):
            assert receipt[field]

    def test_tool_receipt_blocked_carries_error_code(self):
        """被拦截工具回执携带错误码，且不产生输出哈希。"""
        receipt = load_example("tool-call-receipt.blocked.json")
        assert receipt["status"] == "blocked"
        assert receipt["errorCode"] == "TOOL_NOT_ALLOWED"
        assert "outputHash" not in receipt

    def test_model_receipt_records_tokens_and_latency(self):
        """模型回执记录 token 与时延。"""
        receipt = load_example("model-call-receipt.valid.json")
        assert receipt["inputTokens"] >= 0
        assert receipt["outputTokens"] >= 0
        assert receipt["latencyMs"] >= 0
        assert receipt["status"] == "ok"

    def test_model_receipt_error_is_degraded(self):
        """模型错误回执标记降级并带原因。"""
        receipt = load_example("model-call-receipt.error.json")
        assert receipt["status"] == "error"
        assert receipt["degraded"] is True
        assert receipt["degradationReason"] == "MODEL_TIMEOUT"


class TestRuntimeCapabilitiesConsumption:
    """RuntimeCapabilities 消费语义。"""

    def test_capabilities_declare_contract_identity(self):
        """能力声明携带契约版本与契约哈希。"""
        caps = load_example("runtime-capabilities.valid.json")
        assert caps["contractVersion"] == "1.0.0-candidate"
        assert len(caps["contractHash"]) == 64
        assert caps["status"] == "ok"

    def test_sandbox_capability_within_enum(self):
        """``sandboxCapability`` 取值在契约枚举内。"""
        caps = load_example("runtime-capabilities.valid.json")
        assert caps["sandboxCapability"] in {
            "available",
            "unavailable",
            "disabled",
        }

    def test_minimal_capabilities_valid(self):
        """最小能力响应仅含 required 字段。"""
        schema = load_schema("runtime-capabilities.schema.json")
        caps = load_example("runtime-capabilities.minimal.json")
        assert set(caps) == set(schema["required"])
