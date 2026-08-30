package com.dkws.skillruntime.contract;

import static org.assertj.core.api.Assertions.assertThat;

import com.dkws.skillruntime.controller.InternalRuntimeController;
import com.dkws.skillruntime.model.ExecutionResult;
import com.dkws.skillruntime.model.ModelCallReceipt;
import com.dkws.skillruntime.model.RuntimeCapabilities;
import com.dkws.skillruntime.model.RuntimeError;
import com.dkws.skillruntime.model.ToolCallReceipt;
import com.fasterxml.jackson.databind.JsonNode;
import com.networknt.schema.ValidationMessage;
import java.util.List;
import java.util.Map;
import java.util.Set;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * JR-1 §6.3：Java Skill Runtime 作为内部契约 <b>提供方</b> 的能力验证。
 *
 * <p>断言方式为「DTO → JSON → 真实 Schema 校验」，
 * 而非比对手写字符串，确保 Java 产出的 JSON 真的可被 Python Core 消费。
 */
class InternalContractProviderTest {

    private static final String START = "2026-08-30T10:15:20Z";
    private static final String END = "2026-08-30T10:15:27Z";
    private static final String HASH64 =
            "aa11bb22cc33dd44ee55ff6677889900aa11bb22cc33dd44ee55ff6677889900";

    /** 校验并在失败时打印契约错误明细。 */
    private static void assertConformsTo(String schemaFile, Object dto) {
        JsonNode node = InternalContract.toJsonNode(dto);
        Set<ValidationMessage> errors = InternalContract.validate(schemaFile, node);
        assertThat(errors)
                .as("Java 产出的 JSON 不符合 %s:%n%s%n实际=%s",
                        schemaFile, InternalContract.describe(errors), node.toPrettyString())
                .isEmpty();
    }

    private static ToolCallReceipt sampleToolReceipt() {
        return new ToolCallReceipt(
                "tool.customer_profile_reader", "1.2.0",
                "bank-front-precheck", "1.4.0",
                HASH64, "PDP-2026-08-30-77123", HASH64,
                "2026-08-30T10:15:21Z", "2026-08-30T10:15:22Z",
                0, 0.42, 51380224.0, HASH64, Boolean.FALSE, Boolean.FALSE,
                new ToolCallReceipt.SideEffectReceipt("NONE", "pure computation"),
                ToolCallReceipt.STATUS_OK, null
        );
    }

    private static ModelCallReceipt sampleModelReceipt() {
        return ModelCallReceipt.ok("deepseek-chat", HASH64, 1820, 264, 4120.5);
    }

    // ---------- ExecutionResult ----------

    @Test
    @DisplayName("能生成合规 ExecutionResult JSON（成功路径）")
    void generatesValidSuccessExecutionResult() {
        ExecutionResult result = ExecutionResult.success(
                "req-2026-08-30-0001", "rt-7d3f9a1c",
                Map.of("answer", "满足预检条件", "confidence", 0.87),
                START, END,
                List.of(sampleToolReceipt()), List.of(sampleModelReceipt())
        );
        assertConformsTo(InternalContract.EXECUTION_RESULT, result);
    }

    @Test
    @DisplayName("成功结果标记 usable/releaseAllowed 且不降级")
    void successResultCarriesGovernanceFlags() {
        JsonNode node = InternalContract.toJsonNode(ExecutionResult.success(
                "req-1", "rt-1", Map.of("answer", "ok"), START, END, null, null));

        assertThat(node.path("status").asText()).isEqualTo("SUCCESS");
        assertThat(node.path("usable").asBoolean()).isTrue();
        assertThat(node.path("releaseAllowed").asBoolean()).isTrue();
        assertThat(node.path("degraded").asBoolean()).isFalse();
    }

    @Test
    @DisplayName("能生成合规 ExecutionResult JSON（降级路径且禁止放行）")
    void generatesValidDegradedExecutionResult() {
        ExecutionResult result = ExecutionResult.degraded(
                "req-2026-08-30-0003", "rt-9e1c3a7d",
                Map.of("answer", "沙箱不可用"), START, END,
                "SANDBOX_UNAVAILABLE",
                List.of(Map.of("code", "SANDBOX_UNAVAILABLE", "retryable", false))
        );
        assertConformsTo(InternalContract.EXECUTION_RESULT, result);

        JsonNode node = InternalContract.toJsonNode(result);
        assertThat(node.path("status").asText()).isEqualTo("DEGRADED");
        assertThat(node.path("degraded").asBoolean()).isTrue();
        assertThat(node.path("releaseAllowed").asBoolean()).isFalse();
        assertThat(node.path("degradationReason").asText())
                .isEqualTo("SANDBOX_UNAVAILABLE");
    }

    @Test
    @DisplayName("空集合序列化为 [] 而非 null")
    void emptyCollectionsAreArrays() {
        JsonNode node = InternalContract.toJsonNode(ExecutionResult.success(
                "req-1", "rt-1", Map.of("answer", "ok"), START, END, null, null));

        assertThat(node.path("toolCallReceipts").isArray()).isTrue();
        assertThat(node.path("toolCallReceipts")).isEmpty();
        assertThat(node.path("modelCallReceipts").isArray()).isTrue();
        assertThat(node.path("errors").isArray()).isTrue();
    }

    @Test
    @DisplayName("业务字段必须置于 result 开放对象内，不得提升到顶层")
    void businessPayloadStaysInsideResult() {
        JsonNode node = InternalContract.toJsonNode(ExecutionResult.success(
                "req-1", "rt-1", Map.of("vendorField", "x"), START, END, null, null));

        assertThat(node.has("vendorField")).isFalse();
        assertThat(node.path("result").path("vendorField").asText()).isEqualTo("x");
        assertConformsTo(InternalContract.EXECUTION_RESULT, ExecutionResult.success(
                "req-1", "rt-1", Map.of("vendorField", "x"), START, END, null, null));
    }

    // ---------- 回执 ----------

    @Test
    @DisplayName("能生成合规 ToolCallReceipt JSON（完整证据）")
    void generatesValidToolCallReceipt() {
        assertConformsTo(InternalContract.TOOL_CALL_RECEIPT, sampleToolReceipt());
    }

    @Test
    @DisplayName("能生成合规 ToolCallReceipt JSON（最小 ok 形态）")
    void generatesValidMinimalToolCallReceipt() {
        ToolCallReceipt receipt = ToolCallReceipt.ok(
                "tool.x", "1.0.0", "skill.y", "1.0.0", START, END);
        assertConformsTo(InternalContract.TOOL_CALL_RECEIPT, receipt);

        JsonNode node = InternalContract.toJsonNode(receipt);
        assertThat(node.has("errorCode")).as("null 字段不应序列化").isFalse();
    }

    @Test
    @DisplayName("能生成合规 ToolCallReceipt JSON（被策略拦截）")
    void generatesValidBlockedToolCallReceipt() {
        ToolCallReceipt receipt = ToolCallReceipt.blocked(
                "tool.shell_exec", "0.9.0", "skill.y", "1.0.0",
                START, END, RuntimeError.CODE_TOOL_NOT_ALLOWED);
        assertConformsTo(InternalContract.TOOL_CALL_RECEIPT, receipt);

        JsonNode node = InternalContract.toJsonNode(receipt);
        assertThat(node.path("status").asText()).isEqualTo("blocked");
        assertThat(node.path("errorCode").asText()).isEqualTo("TOOL_NOT_ALLOWED");
        assertThat(node.has("outputHash")).isFalse();
    }

    @Test
    @DisplayName("能生成合规 ModelCallReceipt JSON（成功与降级）")
    void generatesValidModelCallReceipts() {
        assertConformsTo(InternalContract.MODEL_CALL_RECEIPT, sampleModelReceipt());

        ModelCallReceipt degraded = ModelCallReceipt.degraded(
                "deepseek-chat", HASH64, 512, 0, 30000.0, "MODEL_TIMEOUT");
        assertConformsTo(InternalContract.MODEL_CALL_RECEIPT, degraded);

        JsonNode node = InternalContract.toJsonNode(degraded);
        assertThat(node.path("status").asText()).isEqualTo("degraded");
        assertThat(node.path("degraded").asBoolean()).isTrue();
        assertThat(node.path("degradationReason").asText()).isEqualTo("MODEL_TIMEOUT");
    }

    @Test
    @DisplayName("模型回执必须携带 promptHash（可审计复现）")
    void modelReceiptRequiresPromptHash() {
        ModelCallReceipt missing = new ModelCallReceipt(
                "deepseek-chat", null, null, 10, 5, null, 100.0, null, null,
                ModelCallReceipt.STATUS_OK);

        Set<ValidationMessage> errors = InternalContract.validate(
                InternalContract.MODEL_CALL_RECEIPT,
                InternalContract.toJsonNode(missing));
        assertThat(errors).as("缺少 promptHash 应被契约拒绝").isNotEmpty();
    }

    // ---------- RuntimeError ----------

    @Test
    @DisplayName("能生成合规 RuntimeError JSON（幂等冲突）")
    void generatesValidIdempotencyConflictError() {
        RuntimeError error = RuntimeError.idempotencyConflict(
                "idem-1", HASH64,
                "99887766554433221100ffeeddccbbaa99887766554433221100ffeeddccbbaa");
        assertConformsTo(InternalContract.RUNTIME_ERROR, error);

        JsonNode node = InternalContract.toJsonNode(error);
        assertThat(node.path("code").asText()).isEqualTo("IDEMPOTENCY_CONFLICT");
        assertThat(node.path("retryable").asBoolean())
                .as("幂等冲突不可重试").isFalse();
        assertThat(node.path("details").path("expectedPayloadHash").asText())
                .isNotEqualTo(node.path("details").path("actualPayloadHash").asText());
    }

    @Test
    @DisplayName("能生成合规 RuntimeError JSON（可重试 / 不可重试）")
    void generatesValidRetryabilityErrors() {
        RuntimeError retryable = RuntimeError.retryable(
                RuntimeError.CODE_DEADLINE_EXCEEDED, "deadline exceeded");
        RuntimeError permanent = RuntimeError.permanent(
                RuntimeError.CODE_INVALID_PLAN, "plan violates contract");

        assertConformsTo(InternalContract.RUNTIME_ERROR, retryable);
        assertConformsTo(InternalContract.RUNTIME_ERROR, permanent);

        assertThat(InternalContract.toJsonNode(retryable).path("retryable").asBoolean())
                .isTrue();
        assertThat(InternalContract.toJsonNode(permanent).path("retryable").asBoolean())
                .isFalse();
    }

    @Test
    @DisplayName("能处理外部 RuntimeError JSON（反序列化后仍合规）")
    void consumesRuntimeErrorJson() throws Exception {
        JsonNode source =
                InternalContract.readExample("runtime-error.idempotency-conflict.json");
        RuntimeError parsed = InternalContract.mapper()
                .treeToValue(source, RuntimeError.class);

        assertThat(parsed.code()).isEqualTo(RuntimeError.CODE_IDEMPOTENCY_CONFLICT);
        assertThat(parsed.retryable()).isFalse();
        assertThat(parsed.details()).containsKey("idempotencyKey");
        assertConformsTo(InternalContract.RUNTIME_ERROR, parsed);
    }

    // ---------- RuntimeCapabilities ----------

    @Test
    @DisplayName("能返回合规 RuntimeCapabilities JSON（health 端点真实产物）")
    void generatesValidRuntimeCapabilities() {
        RuntimeCapabilities caps = new InternalRuntimeController().health();
        assertConformsTo(InternalContract.RUNTIME_CAPABILITIES, caps);

        JsonNode node = InternalContract.toJsonNode(caps);
        assertThat(node.path("status").asText()).isEqualTo("ok");
        assertThat(node.path("sandboxCapability").asText()).isEqualTo("disabled");
        assertThat(node.path("contractVersion").asText()).isEqualTo("1.0.0-candidate");
    }

    @Test
    @DisplayName("最小 RuntimeCapabilities 仅含必填字段亦合规")
    void generatesValidMinimalRuntimeCapabilities() {
        RuntimeCapabilities caps = new RuntimeCapabilities(
                "0.0.1-poc2", "1.0.0-candidate", null, null, null, null, null,
                RuntimeCapabilities.STATUS_OK);
        assertConformsTo(InternalContract.RUNTIME_CAPABILITIES, caps);

        JsonNode node = InternalContract.toJsonNode(caps);
        assertThat(node.has("contractHash")).isFalse();
        assertThat(node.size()).isEqualTo(3);
    }
}
