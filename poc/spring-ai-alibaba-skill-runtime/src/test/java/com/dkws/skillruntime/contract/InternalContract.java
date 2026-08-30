package com.dkws.skillruntime.contract;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.networknt.schema.JsonSchema;
import com.networknt.schema.JsonSchemaFactory;
import com.networknt.schema.SchemaLocation;
import com.networknt.schema.SchemaValidatorsConfig;
import com.networknt.schema.SpecVersion;
import com.networknt.schema.ValidationMessage;
import java.io.IOException;
import java.io.UncheckedIOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.Set;

/**
 * JR-1 内部契约测试支撑：加载 {@code docs/contracts/internal/} 下的真实契约资产。
 *
 * <p>设计要点：Java 侧断言直接针对仓库中的权威 Schema 文件，
 * 不在测试里复制 Schema 片段，从而保证契约一旦变更、双端测试同步失败。
 *
 * <p>Schema 之间以相对文件名互引（如 {@code tool-call-receipt.schema.json}），
 * 因此以 schemas 目录为基准 URI 构建 {@link JsonSchemaFactory}，使 {@code $ref} 可解析。
 */
final class InternalContract {

    /** 内部契约根目录（相对仓库根）。 */
    private static final String CONTRACT_ROOT = "docs/contracts/internal";

    static final String EXECUTION_PLAN = "execution-plan.schema.json";
    static final String EXECUTION_RESULT = "execution-result.schema.json";
    static final String TOOL_CALL_RECEIPT = "tool-call-receipt.schema.json";
    static final String MODEL_CALL_RECEIPT = "model-call-receipt.schema.json";
    static final String RUNTIME_ERROR = "runtime-error.schema.json";
    static final String RUNTIME_CAPABILITIES = "runtime-capabilities.schema.json";

    /** 契约受控 Schema 白名单，与 {@code scripts/internal_contract_hash.py} 一致。 */
    static final String[] ALL_SCHEMAS = {
            EXECUTION_PLAN,
            EXECUTION_RESULT,
            TOOL_CALL_RECEIPT,
            MODEL_CALL_RECEIPT,
            RUNTIME_ERROR,
            RUNTIME_CAPABILITIES,
    };

    private static final ObjectMapper MAPPER = new ObjectMapper();

    private InternalContract() {
    }

    /**
     * 定位仓库根目录。
     *
     * <p>Maven 在模块目录下运行测试，因此向上查找直到发现契约目录，
     * 使测试既可在模块目录运行，也可从仓库根运行。
     *
     * @return 仓库根路径
     * @throws IllegalStateException 未找到契约目录时抛出
     */
    static Path repoRoot() {
        Path current = Paths.get("").toAbsolutePath();
        while (current != null) {
            if (Files.isDirectory(current.resolve(CONTRACT_ROOT))) {
                return current;
            }
            current = current.getParent();
        }
        throw new IllegalStateException("未找到内部契约目录: " + CONTRACT_ROOT);
    }

    /** 返回 schemas 目录。 */
    static Path schemaDir() {
        return repoRoot().resolve(CONTRACT_ROOT).resolve("schemas");
    }

    /** 返回 examples 目录。 */
    static Path exampleDir() {
        return repoRoot().resolve(CONTRACT_ROOT).resolve("examples");
    }

    /** 返回内部 OpenAPI 文件。 */
    static Path openApiFile() {
        return repoRoot()
                .resolve(CONTRACT_ROOT)
                .resolve("openapi")
                .resolve("dkws-skill-runtime-internal-v1.yaml");
    }

    /** 共享 {@link ObjectMapper}，与生产序列化配置保持一致（默认配置）。 */
    static ObjectMapper mapper() {
        return MAPPER;
    }

    /**
     * 加载指定 Schema。
     *
     * @param schemaFileName Schema 文件名，例如 {@link #EXECUTION_RESULT}
     * @return 可执行校验的 {@link JsonSchema}
     */
    static JsonSchema schema(String schemaFileName) {
        // 以文件 URI 作为 retrieval URI，令相对 $ref（同目录文件名）可解析
        JsonSchemaFactory factory =
                JsonSchemaFactory.getInstance(SpecVersion.VersionFlag.V202012);
        SchemaValidatorsConfig config = SchemaValidatorsConfig.builder()
                .formatAssertionsEnabled(true)
                .build();
        SchemaLocation location = SchemaLocation.of(
                schemaDir().resolve(schemaFileName).toUri().toString());
        return factory.getSchema(location, config);
    }

    /**
     * 校验 JSON 节点是否符合指定 Schema。
     *
     * @param schemaFileName Schema 文件名
     * @param node           待校验节点
     * @return 校验错误集合；为空表示通过
     */
    static Set<ValidationMessage> validate(String schemaFileName, JsonNode node) {
        return schema(schemaFileName).validate(node);
    }

    /**
     * 将对象序列化为 JSON 树。
     *
     * @param value 任意 DTO
     * @return JSON 树
     */
    static JsonNode toJsonNode(Object value) {
        return MAPPER.valueToTree(value);
    }

    /**
     * 读取契约示例文件。
     *
     * @param exampleFileName 示例文件名
     * @return JSON 树
     */
    static JsonNode readExample(String exampleFileName) {
        return readJson(exampleDir().resolve(exampleFileName));
    }

    /**
     * 读取任意 JSON 文件。
     *
     * @param path 文件路径
     * @return JSON 树
     */
    static JsonNode readJson(Path path) {
        try {
            return MAPPER.readTree(Files.readString(path));
        } catch (IOException e) {
            throw new UncheckedIOException("读取 JSON 失败: " + path, e);
        }
    }

    /**
     * 把校验错误格式化为可读断言消息。
     *
     * @param messages 校验错误集合
     * @return 多行错误说明
     */
    static String describe(Set<ValidationMessage> messages) {
        StringBuilder sb = new StringBuilder();
        for (ValidationMessage message : messages) {
            sb.append("  - ").append(message.getMessage()).append('\n');
        }
        return sb.toString();
    }
}
