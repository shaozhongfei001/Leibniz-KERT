package com.dkws.skillruntime.contract;

import static org.assertj.core.api.Assertions.assertThat;

import com.fasterxml.jackson.databind.JsonNode;
import com.networknt.schema.ValidationMessage;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Set;
import java.util.stream.Stream;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.MethodSource;

/**
 * JR-1 §6.1 / §6.3：Java 侧能加载并解析全部内部契约 Schema，且示例可通过校验。
 *
 * <p>这是 Java 侧成为契约「合格消费者/提供者」的前置条件：
 * 若 Java 无法解析同一份 Schema，双端一致性无从谈起。
 */
class InternalContractSchemaTest {

    /** 提供受控 Schema 白名单，供参数化测试使用。 */
    static Stream<String> allSchemas() {
        return Stream.of(InternalContract.ALL_SCHEMAS);
    }

    /** 提供 Schema 与其示例文件的配对。 */
    static Stream<org.junit.jupiter.params.provider.Arguments> schemaExamplePairs() {
        return Stream.of(
                org.junit.jupiter.params.provider.Arguments.of(
                        InternalContract.EXECUTION_PLAN, "execution-plan.valid.json"),
                org.junit.jupiter.params.provider.Arguments.of(
                        InternalContract.EXECUTION_PLAN, "execution-plan.minimal.json"),
                org.junit.jupiter.params.provider.Arguments.of(
                        InternalContract.EXECUTION_RESULT, "execution-result.valid.json"),
                org.junit.jupiter.params.provider.Arguments.of(
                        InternalContract.EXECUTION_RESULT, "execution-result.degraded.json"),
                org.junit.jupiter.params.provider.Arguments.of(
                        InternalContract.TOOL_CALL_RECEIPT, "tool-call-receipt.valid.json"),
                org.junit.jupiter.params.provider.Arguments.of(
                        InternalContract.TOOL_CALL_RECEIPT, "tool-call-receipt.blocked.json"),
                org.junit.jupiter.params.provider.Arguments.of(
                        InternalContract.MODEL_CALL_RECEIPT, "model-call-receipt.valid.json"),
                org.junit.jupiter.params.provider.Arguments.of(
                        InternalContract.MODEL_CALL_RECEIPT, "model-call-receipt.error.json"),
                org.junit.jupiter.params.provider.Arguments.of(
                        InternalContract.RUNTIME_ERROR,
                        "runtime-error.idempotency-conflict.json"),
                org.junit.jupiter.params.provider.Arguments.of(
                        InternalContract.RUNTIME_ERROR,
                        "runtime-error.deadline-exceeded.json"),
                org.junit.jupiter.params.provider.Arguments.of(
                        InternalContract.RUNTIME_CAPABILITIES,
                        "runtime-capabilities.valid.json"),
                org.junit.jupiter.params.provider.Arguments.of(
                        InternalContract.RUNTIME_CAPABILITIES,
                        "runtime-capabilities.minimal.json")
        );
    }

    @Test
    @DisplayName("契约目录可定位，6 份 Schema 全部存在")
    void allSchemaFilesExist() {
        Path dir = InternalContract.schemaDir();
        assertThat(dir).isDirectory();
        for (String name : InternalContract.ALL_SCHEMAS) {
            assertThat(dir.resolve(name)).as("缺失 Schema %s", name).isRegularFile();
        }
    }

    @Test
    @DisplayName("Schema 目录不含白名单外文件（防止影子契约）")
    void schemaDirHasNoUnregisteredFile() throws Exception {
        try (var stream = Files.list(InternalContract.schemaDir())) {
            var onDisk = stream
                    .map(p -> p.getFileName().toString())
                    .filter(n -> n.endsWith(".json"))
                    .sorted()
                    .toList();
            assertThat(onDisk).containsExactlyInAnyOrder(InternalContract.ALL_SCHEMAS);
        }
    }

    @ParameterizedTest(name = "Java 可加载并解析 {0}")
    @MethodSource("allSchemas")
    @DisplayName("每份 Schema 都能被 Java 校验器加载")
    void schemaIsLoadableByJava(String schemaFileName) {
        assertThat(InternalContract.schema(schemaFileName)).isNotNull();
    }

    @ParameterizedTest(name = "{0} 声明 additionalProperties=false")
    @MethodSource("allSchemas")
    @DisplayName("每份 Schema 为封闭对象（未知字段策略）")
    void schemaClosesUnknownFields(String schemaFileName) {
        JsonNode raw = InternalContract.readJson(
                InternalContract.schemaDir().resolve(schemaFileName));
        assertThat(raw.path("additionalProperties").asBoolean(true)).isFalse();
        assertThat(raw.path("$schema").asText())
                .isEqualTo("https://json-schema.org/draft/2020-12/schema");
        assertThat(raw.path("required").isArray()).isTrue();
        assertThat(raw.path("required")).isNotEmpty();
    }

    @ParameterizedTest(name = "示例 {1} 通过 {0}")
    @MethodSource("schemaExamplePairs")
    @DisplayName("全部契约示例通过 Java 侧 Schema 校验")
    void exampleMatchesSchema(String schemaFileName, String exampleFileName) {
        JsonNode example = InternalContract.readExample(exampleFileName);
        Set<ValidationMessage> errors = InternalContract.validate(schemaFileName, example);
        assertThat(errors)
                .as("示例 %s 未通过 %s:%n%s",
                        exampleFileName, schemaFileName, InternalContract.describe(errors))
                .isEmpty();
    }

    @Test
    @DisplayName("嵌套 $ref 生效：非法子对象被拒绝")
    void nestedRefIsEnforced() {
        var result = (com.fasterxml.jackson.databind.node.ObjectNode)
                InternalContract.readExample("execution-result.valid.json");
        ((com.fasterxml.jackson.databind.node.ObjectNode)
                result.withArray("toolCallReceipts").get(0))
                .put("status", "NOT_A_STATUS");

        Set<ValidationMessage> errors =
                InternalContract.validate(InternalContract.EXECUTION_RESULT, result);
        assertThat(errors)
                .as("嵌套 $ref 未生效：非法回执状态未被拒绝")
                .isNotEmpty();
    }
}
