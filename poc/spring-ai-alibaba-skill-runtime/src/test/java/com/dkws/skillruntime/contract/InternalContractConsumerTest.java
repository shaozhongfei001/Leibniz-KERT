package com.dkws.skillruntime.contract;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.dkws.skillruntime.model.ExecutionPlan;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.networknt.schema.ValidationMessage;
import java.util.Set;
import java.util.stream.Stream;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.MethodSource;

/**
 * JR-1 §6.3：Java Skill Runtime 作为内部契约 <b>消费方</b> 的能力验证。
 *
 * <p>覆盖：能解析 ExecutionPlan、未知字段处理、必填字段缺失。
 * Runtime 必须在入口拒绝非法计划，而不是「尽力执行」。
 */
class InternalContractConsumerTest {

    /** 加载完整计划示例。 */
    private static ObjectNode validPlanNode() {
        return (ObjectNode) InternalContract.readExample("execution-plan.valid.json");
    }

    /** 反序列化为 DTO。 */
    private static ExecutionPlan parse(JsonNode node) throws Exception {
        return InternalContract.mapper().treeToValue(node, ExecutionPlan.class);
    }

    // ---------- 解析能力 ----------

    @Test
    @DisplayName("能解析完整 ExecutionPlan JSON 并保留全部控制面字段")
    void parsesFullExecutionPlan() throws Exception {
        ExecutionPlan plan = parse(validPlanNode());

        assertThat(plan.contractVersion()).isEqualTo("1.0.0-candidate");
        assertThat(plan.requestId()).isEqualTo("req-2026-08-30-0001");
        assertThat(plan.tenantId()).isEqualTo("tenant-huaxin");
        assertThat(plan.skillId()).isEqualTo("bank-front-precheck");
        assertThat(plan.skillHash()).hasSize(64);
        assertThat(plan.activationPlanHash()).hasSize(64);
        assertThat(plan.policyId()).isEqualTo("POL-SKILL-EXEC-002");
        assertThat(plan.deadline()).isEqualTo("2026-08-30T10:15:30Z");
        assertThat(plan.idempotencyKey()).isNotBlank();
        assertThat(plan.payloadHash()).hasSize(64);
        assertThat(plan.allowedToolIds()).containsExactly(
                "tool.customer_profile_reader", "tool.credit_limit_calculator");
        assertThat(plan.customerScope()).containsEntry("customerId", "CUST-000123");
        assertThat(plan.contextPackage()).containsKey("facts");
    }

    @Test
    @DisplayName("能解析最小 ExecutionPlan JSON（仅必填字段）")
    void parsesMinimalExecutionPlan() throws Exception {
        ExecutionPlan plan = parse(
                InternalContract.readExample("execution-plan.minimal.json"));

        assertThat(plan.requestId()).isEqualTo("req-2026-08-30-0002");
        assertThat(plan.allowedToolIds()).isEmpty();
        assertThat(plan.traceparent()).as("可选字段缺失时为 null").isNull();
        assertThat(plan.contextPackage()).isNull();
    }

    @Test
    @DisplayName("解析后可回写为合规 JSON（消费-提供往返无损）")
    void roundTripsWithoutContractViolation() throws Exception {
        ExecutionPlan plan = parse(validPlanNode());
        JsonNode reserialized = InternalContract.toJsonNode(plan);

        Set<ValidationMessage> errors =
                InternalContract.validate(InternalContract.EXECUTION_PLAN, reserialized);
        assertThat(errors)
                .as("往返后不符合契约:%n%s", InternalContract.describe(errors))
                .isEmpty();
        assertThat(reserialized).isEqualTo(validPlanNode());
    }

    @Test
    @DisplayName("allowedToolIds 为空数组时拒绝任何工具（零授权语义）")
    void emptyAllowedToolIdsBlocksEveryTool() throws Exception {
        ExecutionPlan plan = parse(
                InternalContract.readExample("execution-plan.minimal.json"));

        assertThat(plan.allowedToolIds()).isEmpty();
        assertThat(plan.allowsTool("tool.customer_profile_reader")).isFalse();
    }

    @Test
    @DisplayName("仅授权列表内的工具被允许")
    void onlyWhitelistedToolAllowed() throws Exception {
        ExecutionPlan plan = parse(validPlanNode());

        assertThat(plan.allowsTool("tool.customer_profile_reader")).isTrue();
        assertThat(plan.allowsTool("tool.shell_exec")).isFalse();
    }

    // ---------- 未知字段处理 ----------

    @Test
    @DisplayName("未知字段在反序列化阶段即失败，不被静默丢弃")
    void unknownFieldRejectedOnDeserialization() {
        ObjectNode polluted = validPlanNode();
        polluted.put("dkwsUnexpectedField", "should-be-rejected");

        assertThatThrownBy(() -> parse(polluted))
                .hasMessageContaining("dkwsUnexpectedField");
    }

    @Test
    @DisplayName("未知字段同样被 Schema 拒绝（双闸门）")
    void unknownFieldRejectedBySchema() {
        ObjectNode polluted = validPlanNode();
        polluted.put("dkwsUnexpectedField", "should-be-rejected");

        Set<ValidationMessage> errors =
                InternalContract.validate(InternalContract.EXECUTION_PLAN, polluted);
        assertThat(errors).isNotEmpty();
        assertThat(InternalContract.describe(errors))
                .contains("dkwsUnexpectedField");
    }

    @Test
    @DisplayName("开放载荷容器内的自由字段不受影响")
    void openContainersAcceptFreeFormFields() throws Exception {
        ObjectNode plan = validPlanNode();
        ((ObjectNode) plan.path("contextPackage")).put("anyBusinessFact", "ok");

        ExecutionPlan parsed = parse(plan);
        assertThat(parsed.contextPackage()).containsEntry("anyBusinessFact", "ok");

        Set<ValidationMessage> errors =
                InternalContract.validate(InternalContract.EXECUTION_PLAN, plan);
        assertThat(errors)
                .as("开放容器内的业务字段被误拒:%n%s", InternalContract.describe(errors))
                .isEmpty();
    }

    // ---------- 必填字段缺失 ----------

    /** 契约声明的全部必填字段。 */
    static Stream<String> requiredFields() {
        JsonNode schema = InternalContract.readJson(
                InternalContract.schemaDir().resolve(InternalContract.EXECUTION_PLAN));
        return Stream.iterate(0, i -> i + 1)
                .limit(schema.path("required").size())
                .map(i -> schema.path("required").get(i).asText());
    }

    @ParameterizedTest(name = "缺失必填字段 {0} 被拒绝")
    @MethodSource("requiredFields")
    @DisplayName("逐一删除必填字段，Schema 均判定非法")
    void missingRequiredFieldRejected(String field) {
        ObjectNode plan = validPlanNode();
        plan.remove(field);

        Set<ValidationMessage> errors =
                InternalContract.validate(InternalContract.EXECUTION_PLAN, plan);
        assertThat(errors)
                .as("删除必填字段 %s 后仍通过校验", field)
                .isNotEmpty();
        assertThat(InternalContract.describe(errors)).contains(field);
    }

    @Test
    @DisplayName("空对象被拒绝")
    void emptyObjectRejected() {
        Set<ValidationMessage> errors = InternalContract.validate(
                InternalContract.EXECUTION_PLAN,
                InternalContract.mapper().createObjectNode());
        assertThat(errors).isNotEmpty();
    }

    @Test
    @DisplayName("字段类型错误被拒绝")
    void wrongTypeRejected() {
        ObjectNode plan = validPlanNode();
        plan.put("allowedToolIds", "not-an-array");

        assertThat(InternalContract.validate(InternalContract.EXECUTION_PLAN, plan))
                .isNotEmpty();
    }

    @Test
    @DisplayName("非 RFC3339 deadline 被拒绝（format 断言开启）")
    void badDateTimeRejected() {
        ObjectNode plan = validPlanNode();
        plan.put("deadline", "2026/08/30 10:15");

        assertThat(InternalContract.validate(InternalContract.EXECUTION_PLAN, plan))
                .as("format: date-time 断言未生效")
                .isNotEmpty();
    }
}
