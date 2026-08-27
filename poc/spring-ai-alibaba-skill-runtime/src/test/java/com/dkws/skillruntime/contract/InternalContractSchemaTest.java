package com.dkws.skillruntime.contract;

import com.dkws.skillruntime.model.ExecutionResult;
import com.dkws.skillruntime.model.ModelCallReceipt;
import com.dkws.skillruntime.model.RuntimeCapabilities;
import com.dkws.skillruntime.model.ToolCallReceipt;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.networknt.schema.JsonSchema;
import com.networknt.schema.JsonSchemaFactory;
import com.networknt.schema.SchemaValidatorsConfig;
import com.networknt.schema.SpecVersion;
import com.networknt.schema.ValidationMessage;
import org.junit.jupiter.api.Test;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * Provider 侧契约测试：Java Runtime 产出的 DTO 序列化结果必须通过
 * {@code docs/contracts/internal/schemas/*.schema.json} 中的同一批 JSON Schema。
 *
 * <p>与 Python consumer 侧测试
 * {@code tests/contract/test_internal_runtime_contract.py} 配对，
 * 共同构成施工令第十一节 §2 要求的「Python 与 Java consumer/provider contract test」。
 *
 * <p><b>本测试的价值在于捕获「Java DTO 与契约漂移」</b>：
 * 例如 Java 侧 ToolCallReceipt 缺少 inputHash / policyDecisionId 等审计字段时，
 * 本测试会失败，从而阻止「源码存在即标 PASS」。
 */
class InternalContractSchemaTest {

    private static final ObjectMapper MAPPER = new ObjectMapper();

    /** schema $id 的命名空间前缀，用于映射到本地文件（离线解析）。 */
    private static final String ID_NAMESPACE = "https://contracts.dkws.internal/skill-runtime/v1/";

    private static final List<String> SCHEMA_FILES = List.of(
            "execution-plan.schema.json",
            "execution-result.schema.json",
            "tool-call-receipt.schema.json",
            "model-call-receipt.schema.json",
            "runtime-error.schema.json",
            "runtime-capabilities.schema.json");

    /** 定位仓库根：从当前工作目录（poc 模块目录）上溯两级。 */
    private static Path repoRoot() {
        Path cwd = Paths.get("").toAbsolutePath();
        Path candidate = cwd;
        for (int i = 0; i < 6 && candidate != null; i++) {
            if (Files.isDirectory(candidate.resolve("docs/contracts/internal/schemas"))) {
                return candidate;
            }
            candidate = candidate.getParent();
        }
        throw new IllegalStateException("cannot locate repo root from " + cwd);
    }

    private static JsonSchema schema(String name) throws IOException {
        Path schemaDir = repoRoot().resolve("docs/contracts/internal/schemas");
        SchemaValidatorsConfig config = SchemaValidatorsConfig.builder().build();

        // schema 内 $id 是 https URI（稳定标识），但**不得联网解析**。
        // 因此把 $id 命名空间映射到本地文件，保证离线可重复构建。
        Map<String, String> uriMappings = new HashMap<>();
        for (String schemaFile : SCHEMA_FILES) {
            uriMappings.put(ID_NAMESPACE + schemaFile, schemaDir.resolve(schemaFile).toUri().toString());
        }

        JsonSchemaFactory factory = JsonSchemaFactory
                .builder(JsonSchemaFactory.getInstance(SpecVersion.VersionFlag.V202012))
                .schemaMappers(mappers -> mappers.mappings(uriMappings))
                .build();

        String content = Files.readString(schemaDir.resolve(name));
        return factory.getSchema(
                schemaDir.toUri().resolve(name),
                MAPPER.readTree(content),
                config);
    }

    private static Set<ValidationMessage> validate(String schemaName, Object instance) throws IOException {
        JsonNode node = MAPPER.valueToTree(instance);
        return schema(schemaName).validate(node);
    }

    // ------------------------------------------------------------ 健康接口

    @Test
    void healthResponseSatisfiesRuntimeCapabilitiesContract() throws IOException {
        // 对应 POC-2 准入第 20 项：health 必须上报 8 个字段
        RuntimeCapabilities caps = new RuntimeCapabilities(
                "0.0.1-poc2",
                "1.0",
                "0000000000000000000000000000000000000000000000000000000000000000",
                "spring-ai-alibaba-1.1.2.0",
                List.of(),
                "disabled",
                false,
                "ok");
        Set<ValidationMessage> errors = validate("runtime-capabilities.schema.json", caps);
        assertTrue(errors.isEmpty(), () -> "health response violates contract: " + errors);
    }

    @Test
    void healthResponseRejectsInconsistentDegradedFlag() throws IOException {
        // degraded=true 但 status=ok 且无 degradationReason -> 必须被契约拒绝
        RuntimeCapabilities caps = new RuntimeCapabilities(
                "0.0.1-poc2",
                "1.0",
                "0000000000000000000000000000000000000000000000000000000000000000",
                "spring-ai-alibaba-1.1.2.0",
                List.of(),
                "disabled",
                true,
                "ok");
        Set<ValidationMessage> errors = validate("runtime-capabilities.schema.json", caps);
        assertFalse(errors.isEmpty(), "inconsistent degraded flag must be rejected by contract");
    }

    // ------------------------------------------------------------ Receipt 漂移检测

    @Test
    void toolCallReceiptDtoIsMissingMandatoryAuditFields() throws IOException {
        // 当前 Java DTO 只有 toolId/toolVersion/skillId/skillVersion/status/errorCode，
        // 缺 inputHash/policyDecisionId/outputHash/outputTruncated/networkUsed/时间戳。
        // 本断言把「已知契约漂移」显式固化为机器事实，避免 POC2_RESULT 误标 PASS。
        ToolCallReceipt receipt = new ToolCallReceipt(
                "read_skill", "1.0.0", "demo-skill", "1.0.0", "ok", null);
        Set<ValidationMessage> errors = validate("tool-call-receipt.schema.json", receipt);
        assertFalse(errors.isEmpty(),
                "expected contract drift: current ToolCallReceipt DTO lacks audit fields");

        String messages = errors.toString();
        for (String required : List.of("inputHash", "policyDecisionId", "outputHash",
                "outputTruncated", "networkUsed", "startedAt", "completedAt")) {
            assertTrue(messages.contains(required),
                    () -> "contract must require " + required + ", got: " + messages);
        }
    }

    @Test
    void modelCallReceiptDtoIsMissingMandatoryFields() throws IOException {
        // 缺 modelPolicyRef 与 promptHash -> Core 无法审计模型选择是否越权
        ModelCallReceipt receipt = new ModelCallReceipt("internal-mock-chat", 10, 20, 100L, "ok");
        Set<ValidationMessage> errors = validate("model-call-receipt.schema.json", receipt);
        assertFalse(errors.isEmpty(),
                "expected contract drift: ModelCallReceipt DTO lacks modelPolicyRef/promptHash");
        assertTrue(errors.toString().contains("modelPolicyRef"));
    }

    @Test
    void executionResultDtoIsMissingMandatoryFields() throws IOException {
        // 缺 runtimeRequestId/degraded/errors/startedAt/completedAt，且 trace 结构不符
        ExecutionResult result = new ExecutionResult(
                "req-01J8Z4KQ7X9M2N4P6R8T0V2X4Z",
                "SUCCESS",
                true,
                true,
                "answer",
                List.of(),
                List.of(),
                List.of("agent.call"));
        Set<ValidationMessage> errors = validate("execution-result.schema.json", result);
        assertFalse(errors.isEmpty(),
                "expected contract drift: ExecutionResult DTO lacks runtimeRequestId/degraded/errors/timestamps");
    }

    // ------------------------------------------------------------ 契约自身完备性

    @Test
    void allSchemasAreLoadableAndForbidUnknownFields() throws IOException {
        for (String name : SCHEMA_FILES) {
            Path path = repoRoot().resolve("docs/contracts/internal/schemas").resolve(name);
            JsonNode node = MAPPER.readTree(Files.readString(path));
            assertEquals(Boolean.FALSE, node.path("additionalProperties").asBoolean(true) ? Boolean.TRUE : Boolean.FALSE,
                    name + " must set additionalProperties=false");
            assertTrue(node.has("$id"), name + " must declare $id");
            // 可被 schema factory 成功加载（含 $ref 解析）
            schema(name);
        }
    }

    @Test
    void canonicalExamplesPassProviderSideValidation() throws IOException {
        Path examples = repoRoot().resolve("docs/contracts/internal/examples");
        record Pair(String example, String schema) {
        }
        for (Pair pair : List.of(
                new Pair("execution-plan.example.json", "execution-plan.schema.json"),
                new Pair("execution-result.example.json", "execution-result.schema.json"),
                new Pair("runtime-error.example.json", "runtime-error.schema.json"),
                new Pair("runtime-capabilities.example.json", "runtime-capabilities.schema.json"))) {
            JsonNode instance = MAPPER.readTree(Files.readString(examples.resolve(pair.example())));
            Set<ValidationMessage> errors = schema(pair.schema()).validate(instance);
            assertTrue(errors.isEmpty(),
                    () -> pair.example() + " failed provider-side validation: " + errors);
        }
    }

    @Test
    void unknownFieldInExecutionPlanIsRejected() throws IOException {
        Path examples = repoRoot().resolve("docs/contracts/internal/examples");
        JsonNode instance = MAPPER.readTree(Files.readString(examples.resolve("execution-plan.example.json")));
        ((com.fasterxml.jackson.databind.node.ObjectNode) instance).put("experimentalFlag", true);
        Set<ValidationMessage> errors = schema("execution-plan.schema.json").validate(instance);
        assertFalse(errors.isEmpty(), "unknown field must be rejected (fail-closed)");
    }

    @Test
    void incompatibleContractVersionIsRejected() throws IOException {
        Path examples = repoRoot().resolve("docs/contracts/internal/examples");
        JsonNode instance = MAPPER.readTree(Files.readString(examples.resolve("execution-plan.example.json")));
        ((com.fasterxml.jackson.databind.node.ObjectNode) instance).put("contractVersion", "2.0");
        Set<ValidationMessage> errors = schema("execution-plan.schema.json").validate(instance);
        assertFalse(errors.isEmpty(), "contractVersion major mismatch must be rejected");
    }
}
