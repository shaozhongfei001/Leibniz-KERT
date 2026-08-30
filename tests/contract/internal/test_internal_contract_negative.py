"""JR-1：内部契约否定路径测试（未知字段 / 必填缺失 / 幂等冲突）。

对应任务包 JR-1 §6.2 后三项。契约的约束力体现在"该拒绝时确实拒绝"，
因此本模块全部为否定用例。
"""

from __future__ import annotations

import copy
import hashlib
import json

import pytest

from .conftest import (
    SCHEMA_FILES,
    assert_invalid,
    assert_valid,
    load_example,
    load_schema,
)

#: Schema → 用于构造否定用例的基准示例。
BASELINE_EXAMPLE: dict[str, str] = {
    "execution-plan.schema.json": "execution-plan.valid.json",
    "execution-result.schema.json": "execution-result.valid.json",
    "tool-call-receipt.schema.json": "tool-call-receipt.valid.json",
    "model-call-receipt.schema.json": "model-call-receipt.valid.json",
    "runtime-error.schema.json": "runtime-error.idempotency-conflict.json",
    "runtime-capabilities.schema.json": "runtime-capabilities.valid.json",
}


def _baseline(schema_name: str) -> dict:
    """返回基准示例的深拷贝，供否定用例修改。"""
    return copy.deepcopy(load_example(BASELINE_EXAMPLE[schema_name]))


class TestUnknownFieldPolicy:
    """未知字段策略：内部契约为封闭对象，未知字段必须被拒绝。"""

    @pytest.mark.parametrize("schema_name", SCHEMA_FILES)
    def test_top_level_unknown_field_rejected(self, schema_name):
        """顶层新增未知字段被拒绝。"""
        instance = _baseline(schema_name)
        instance["dkwsUnexpectedField"] = "should-be-rejected"
        messages = assert_invalid(schema_name, instance)
        assert any("dkwsUnexpectedField" in m for m in messages), messages

    @pytest.mark.parametrize("schema_name", SCHEMA_FILES)
    def test_baseline_without_unknown_field_is_valid(self, schema_name):
        """作为对照：未注入未知字段时基准示例通过。"""
        assert_valid(schema_name, _baseline(schema_name))

    def test_unknown_field_in_nested_tool_receipt_rejected(self):
        """嵌套工具回执中的未知字段同样被拒绝（``$ref`` 传递封闭性）。"""
        result = _baseline("execution-result.schema.json")
        result["toolCallReceipts"][0]["rogueField"] = 1
        messages = assert_invalid("execution-result.schema.json", result)
        assert any("rogueField" in m for m in messages), messages

    def test_unknown_field_in_nested_model_receipt_rejected(self):
        """嵌套模型回执中的未知字段被拒绝。"""
        result = _baseline("execution-result.schema.json")
        result["modelCallReceipts"][0]["rogueField"] = True
        messages = assert_invalid("execution-result.schema.json", result)
        assert any("rogueField" in m for m in messages), messages

    def test_open_payload_containers_still_accept_free_form(self):
        """开放载荷容器（``result`` / ``contextPackage`` / ``details``）允许自由字段。

        封闭性作用于契约信封，不应误伤业务载荷。
        """
        result = _baseline("execution-result.schema.json")
        result["result"]["vendorSpecificPayload"] = {"a": [1, 2, 3]}
        assert_valid("execution-result.schema.json", result)

        plan = _baseline("execution-plan.schema.json")
        plan["contextPackage"]["anyBusinessFact"] = "ok"
        assert_valid("execution-plan.schema.json", plan)

        err = _baseline("runtime-error.schema.json")
        err["details"]["extraDiagnostic"] = "ok"
        assert_valid("runtime-error.schema.json", err)


class TestRequiredFieldPolicy:
    """必填字段缺失必须被拒绝。"""

    @pytest.mark.parametrize("schema_name", SCHEMA_FILES)
    def test_each_required_field_is_enforced(self, schema_name):
        """逐一删除每个必填字段，都应被拒绝。"""
        required = load_schema(schema_name)["required"]
        for field in required:
            instance = _baseline(schema_name)
            instance.pop(field, None)
            messages = assert_invalid(schema_name, instance)
            assert any(field in m for m in messages), (
                f"{schema_name} 删除必填字段 {field} 后未给出对应错误: {messages}"
            )

    @pytest.mark.parametrize("schema_name", SCHEMA_FILES)
    def test_empty_object_rejected(self, schema_name):
        """空对象被拒绝（至少缺失全部必填字段）。"""
        messages = assert_invalid(schema_name, {})
        assert messages

    def test_nested_receipt_missing_required_rejected(self):
        """嵌套回执缺失必填字段被拒绝。"""
        result = _baseline("execution-result.schema.json")
        del result["toolCallReceipts"][0]["toolVersion"]
        messages = assert_invalid("execution-result.schema.json", result)
        assert any("toolVersion" in m for m in messages), messages

    def test_wrong_type_rejected(self):
        """必填字段类型错误被拒绝。"""
        result = _baseline("execution-result.schema.json")
        result["usable"] = "true"
        assert_invalid("execution-result.schema.json", result)

    def test_out_of_enum_status_rejected(self):
        """状态枚举外取值被拒绝。"""
        result = _baseline("execution-result.schema.json")
        result["status"] = "MOSTLY_FINE"
        messages = assert_invalid("execution-result.schema.json", result)
        assert any("MOSTLY_FINE" in m for m in messages), messages

    def test_bad_date_time_rejected(self):
        """非 RFC3339 时间戳被拒绝（``format: date-time`` 生效）。"""
        plan = _baseline("execution-plan.schema.json")
        plan["deadline"] = "2026/08/30 10:15"
        assert_invalid("execution-plan.schema.json", plan)


def _payload_hash(payload: dict) -> str:
    """按规范序列化后计算 payload 的 SHA-256。

    与 Runtime Store 的幂等语义一致：以内容摘要判定"同键是否同内容"。
    """
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class TestIdempotencyConflictSemantics:
    """同 key 不同 payload 的幂等冲突语义（JR-1 §6.2 末项）。"""

    def test_same_key_same_payload_yields_same_hash(self):
        """同键同内容 → ``payloadHash`` 相同（可安全复放）。"""
        plan_a = _baseline("execution-plan.schema.json")
        plan_b = _baseline("execution-plan.schema.json")
        assert plan_a["idempotencyKey"] == plan_b["idempotencyKey"]
        assert _payload_hash(plan_a) == _payload_hash(plan_b)

    def test_same_key_different_payload_yields_different_hash(self):
        """同键不同内容 → ``payloadHash`` 必须不同（可检出冲突）。"""
        plan_a = _baseline("execution-plan.schema.json")
        plan_b = _baseline("execution-plan.schema.json")
        plan_b["contextPackage"]["facts"]["customerSegment"] = "RETAIL"

        assert plan_a["idempotencyKey"] == plan_b["idempotencyKey"]
        assert _payload_hash(plan_a) != _payload_hash(plan_b)

    def test_payload_hash_is_field_order_independent(self):
        """``payloadHash`` 不受字段书写顺序影响（避免伪冲突）。"""
        plan = _baseline("execution-plan.schema.json")
        reordered = dict(reversed(list(plan.items())))
        assert _payload_hash(plan) == _payload_hash(reordered)

    def test_conflict_error_example_conforms_to_runtime_error(self):
        """幂等冲突以 ``RuntimeError`` 契约表达，且通过 Schema。"""
        err = load_example("runtime-error.idempotency-conflict.json")
        assert_valid("runtime-error.schema.json", err)
        assert err["code"] == "IDEMPOTENCY_CONFLICT"
        assert err["retryable"] is False, "幂等冲突不可重试"

    def test_conflict_error_carries_both_hashes(self):
        """冲突错误携带期望与实际 ``payloadHash``，可供审计定位。"""
        details = load_example(
            "runtime-error.idempotency-conflict.json"
        )["details"]
        assert details["idempotencyKey"]
        assert details["expectedPayloadHash"] != details["actualPayloadHash"]
        for key in ("expectedPayloadHash", "actualPayloadHash"):
            assert len(details[key]) == 64

    def test_runtime_store_rejects_same_key_different_payload(self, tmp_path):
        """与 Python Core 实际实现对齐：Runtime Store 检出同键不同内容。

        证明契约语义不是纸面约定，而与 :class:`RuntimeStore` 行为一致。
        """
        from dkws.domain.errors import IdempotencyConflictError
        from dkws.infrastructure.runtime_store import RuntimeStore

        plan_a = _baseline("execution-plan.schema.json")
        plan_b = _baseline("execution-plan.schema.json")
        plan_b["contextPackage"]["facts"]["customerSegment"] = "RETAIL"
        key = plan_a["idempotencyKey"]

        store = RuntimeStore(tmp_path / "runtime.db")
        assert store.lookup("skill_execute", key) is None, "初始不应存在记录"

        first = store.remember(
            "skill_execute", key, _payload_hash(plan_a), {"status": "SUCCESS"}
        )
        assert first.request_hash == _payload_hash(plan_a)

        # 同键同内容：复放既有记录，不抛冲突
        replay = store.remember(
            "skill_execute", key, _payload_hash(plan_a), {"status": "SUCCESS"}
        )
        assert replay.request_hash == first.request_hash
        assert replay.created_at == first.created_at, "应复放原记录而非新写入"

        # 同键不同内容：判定为幂等冲突
        with pytest.raises(IdempotencyConflictError):
            store.remember(
                "skill_execute", key, _payload_hash(plan_b), {"status": "SUCCESS"}
            )
