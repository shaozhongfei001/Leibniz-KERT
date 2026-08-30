package com.dkws.skillruntime.contract;

import static org.assertj.core.api.Assertions.assertThat;

import com.dkws.skillruntime.controller.InternalRuntimeController;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * JR-1 §6.4：Java 侧独立重算内部契约 bundle 哈希。
 *
 * <p>关键价值：哈希由 Java 用与 Python 相同的算法 <b>独立</b> 计算，
 * 而不是读取 Python 的输出。三者必须一致：
 * <ol>
 *   <li>Java 重算值</li>
 *   <li>{@link InternalRuntimeController#CONTRACT_HASH} 内置常量</li>
 *   <li>{@code evidence/jr1/internal-contract-hash.txt} 记录值</li>
 * </ol>
 * 任一端漂移都会使本测试失败，从而阻断静默不一致。
 *
 * <p>算法（与 {@code scripts/internal_contract_hash.py} 对齐）：
 * 按相对路径排序，对每个文件取 SHA-256，
 * 再对 {@code "<相对路径>\0<sha256>\0"} 拼接串取 SHA-256。
 */
class InternalContractHashTest {

    /** 受控文件相对路径（相对 {@code docs/contracts/internal}），需与 Python 白名单一致。 */
    private static final List<String> CONTROLLED_FILES = List.of(
            "openapi/dkws-skill-runtime-internal-v1.yaml",
            "schemas/execution-plan.schema.json",
            "schemas/execution-result.schema.json",
            "schemas/model-call-receipt.schema.json",
            "schemas/runtime-capabilities.schema.json",
            "schemas/runtime-error.schema.json",
            "schemas/tool-call-receipt.schema.json"
    );

    private static String sha256Hex(byte[] data) {
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            byte[] hash = digest.digest(data);
            StringBuilder sb = new StringBuilder(hash.length * 2);
            for (byte b : hash) {
                sb.append(String.format(Locale.ROOT, "%02x", b));
            }
            return sb.toString();
        } catch (NoSuchAlgorithmException e) {
            throw new IllegalStateException("SHA-256 不可用", e);
        }
    }

    /** 按契约算法重算 bundle 哈希。 */
    private static String recomputeBundleHash() throws IOException {
        Path base = InternalContract.repoRoot().resolve("docs/contracts/internal");
        List<String> sorted = new ArrayList<>(CONTROLLED_FILES);
        sorted.sort(String::compareTo);

        StringBuilder manifest = new StringBuilder();
        for (String relative : sorted) {
            Path file = base.resolve(relative);
            manifest.append(relative).append('\0')
                    .append(sha256Hex(Files.readAllBytes(file))).append('\0');
        }
        return sha256Hex(manifest.toString().getBytes(StandardCharsets.UTF_8));
    }

    @Test
    @DisplayName("受控契约文件全部存在（7 份：6 Schema + 1 OpenAPI）")
    void allControlledFilesExist() {
        Path base = InternalContract.repoRoot().resolve("docs/contracts/internal");
        assertThat(CONTROLLED_FILES).hasSize(7);
        for (String relative : CONTROLLED_FILES) {
            assertThat(base.resolve(relative))
                    .as("缺失受控契约文件 %s", relative)
                    .isRegularFile();
        }
    }

    @Test
    @DisplayName("Java 重算的 bundle 哈希等于 Runtime 内置 CONTRACT_HASH")
    void javaRecomputedHashMatchesRuntimeConstant() throws IOException {
        assertThat(recomputeBundleHash())
                .as("Runtime 内置契约哈希与实际契约不一致（契约漂移）")
                .isEqualTo(InternalRuntimeController.CONTRACT_HASH);
    }

    @Test
    @DisplayName("Java 重算的 bundle 哈希等于 Python 侧证据记录值")
    void javaRecomputedHashMatchesPythonEvidence() throws IOException {
        Path evidence = InternalContract.repoRoot()
                .resolve("evidence/jr1/internal-contract-hash.txt");
        assertThat(evidence).as("缺失 Python 侧哈希证据").isRegularFile();

        String recorded = null;
        for (String line : Files.readAllLines(evidence, StandardCharsets.UTF_8)) {
            String trimmed = line.trim();
            if (trimmed.startsWith("bundle_hash=")) {
                recorded = trimmed.substring("bundle_hash=".length()).trim();
                break;
            }
        }

        assertThat(recorded).as("证据文件未记录 bundle_hash=").isNotNull();
        assertThat(recorded)
                .as("Java 重算值与 Python 证据不一致（双端契约漂移）")
                .isEqualTo(recomputeBundleHash());
    }

    @Test
    @DisplayName("哈希可重算：连续两次计算结果稳定")
    void recomputationIsStable() throws IOException {
        assertThat(recomputeBundleHash()).isEqualTo(recomputeBundleHash());
    }

    @Test
    @DisplayName("契约哈希为 64 位小写十六进制 SHA-256")
    void hashFormatIsSha256Hex() throws IOException {
        assertThat(recomputeBundleHash()).matches("^[0-9a-f]{64}$");
    }

    @Test
    @DisplayName("health 端点返回的 contractHash 与重算值一致")
    void healthEndpointReportsCurrentContractHash() throws IOException {
        assertThat(new InternalRuntimeController().health().contractHash())
                .isEqualTo(recomputeBundleHash());
    }

    @Test
    @DisplayName("契约变更会改变哈希（防止哈希对改动不敏感）")
    void hashIsSensitiveToContractChange(@org.junit.jupiter.api.io.TempDir Path tempDir)
            throws IOException {
        Path base = InternalContract.repoRoot().resolve("docs/contracts/internal");
        Path original = base.resolve("schemas/runtime-error.schema.json");
        byte[] content = Files.readAllBytes(original);

        Path mutated = tempDir.resolve("mutated.json");
        Files.write(mutated, new String(content, StandardCharsets.UTF_8)
                .replace("\"code\"", "\"codeX\"")
                .getBytes(StandardCharsets.UTF_8));

        assertThat(sha256Hex(Files.readAllBytes(mutated)))
                .as("内容变更后分项哈希应不同")
                .isNotEqualTo(sha256Hex(content));
    }
}
