package com.dkws.skillruntime.security;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.mock.web.MockMultipartFile;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.zip.ZipEntry;
import java.util.zip.ZipOutputStream;

import static org.junit.jupiter.api.Assertions.assertDoesNotThrow;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * Skill 包解压安全测试（Java 侧，对应 R5 安全用例中的 Zip Slip / 数量与大小超限）。
 *
 * <p>注意：本测试属 Tech Lead 自测，不构成 C-B03 的独立安全 QA。
 */
class ZipSafeExtractorTest {

    @TempDir
    Path tempDir;

    private static byte[] zipOf(String... nameContentPairs) throws IOException {
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        try (ZipOutputStream zos = new ZipOutputStream(out)) {
            for (int i = 0; i < nameContentPairs.length; i += 2) {
                zos.putNextEntry(new ZipEntry(nameContentPairs[i]));
                zos.write(nameContentPairs[i + 1].getBytes(StandardCharsets.UTF_8));
                zos.closeEntry();
            }
        }
        return out.toByteArray();
    }

    @Test
    void extractsNormalPackage() throws IOException {
        Path target = Files.createDirectories(tempDir.resolve("ok"));
        MockMultipartFile file = new MockMultipartFile("f", "s.zip", "application/zip",
                zipOf("SKILL.md", "---\nname: demo\nversion: 1.0.0\n---\n"));
        ZipSafeExtractor extractor = new ZipSafeExtractor(1024 * 1024, 32);

        assertDoesNotThrow(() -> extractor.extractTo(file, target));
        assertTrue(Files.exists(target.resolve("SKILL.md")));
    }

    @Test
    void rejectsZipSlipViaParentTraversal() throws IOException {
        Path target = Files.createDirectories(tempDir.resolve("slip"));
        MockMultipartFile file = new MockMultipartFile("f", "evil.zip", "application/zip",
                zipOf("../../evil.txt", "pwned"));
        ZipSafeExtractor extractor = new ZipSafeExtractor(1024 * 1024, 32);

        assertThrows(SecurityException.class, () -> extractor.extractTo(file, target));
        // 逃逸目标不得被创建
        assertFalse(Files.exists(tempDir.resolve("evil.txt")));
        assertFalse(Files.exists(tempDir.getParent().resolve("evil.txt")));
    }

    @Test
    void rejectsTooManyFiles() throws IOException {
        Path target = Files.createDirectories(tempDir.resolve("many"));
        String[] pairs = new String[20];
        for (int i = 0; i < 10; i++) {
            pairs[i * 2] = "f" + i + ".txt";
            pairs[i * 2 + 1] = "x";
        }
        MockMultipartFile file = new MockMultipartFile("f", "many.zip", "application/zip", zipOf(pairs));
        ZipSafeExtractor extractor = new ZipSafeExtractor(1024 * 1024, 3);

        assertThrows(IllegalArgumentException.class, () -> extractor.extractTo(file, target));
    }

    @Test
    void rejectsOversizedArchive() throws IOException {
        Path target = Files.createDirectories(tempDir.resolve("big"));
        MockMultipartFile file = new MockMultipartFile("f", "big.zip", "application/zip",
                zipOf("a.txt", "0123456789".repeat(500)));
        ZipSafeExtractor extractor = new ZipSafeExtractor(64, 32);

        assertThrows(IllegalArgumentException.class, () -> extractor.extractTo(file, target));
    }
}
