package com.dkws.skillruntime.service;

import com.alibaba.cloud.ai.graph.skills.registry.SkillRegistry;
import com.alibaba.cloud.ai.graph.skills.registry.AbstractSkillRegistry;
import com.dkws.skillruntime.model.SkillUploadResponse;
import com.dkws.skillruntime.security.ZipSafeExtractor;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.web.multipart.MultipartFile;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Comparator;

@Service
public class SkillUploadService {

    private final Path userSkillsDir;
    private final ZipSafeExtractor zipSafeExtractor;
    private final SkillRegistry skillRegistry;

    public SkillUploadService(
            @Value("${skill-runtime.user-skills-dir}") String userSkillsDir,
            @Value("${skill-runtime.max-skill-zip-size:20MB}") String maxZipSize,
            @Value("${skill-runtime.max-skill-files:200}") int maxFiles,
            SkillRegistry skillRegistry) {
        this.userSkillsDir = Path.of(userSkillsDir).toAbsolutePath().normalize();
        this.zipSafeExtractor = new ZipSafeExtractor(parseSize(maxZipSize), maxFiles);
        this.skillRegistry = skillRegistry;
    }

    public SkillUploadResponse upload(MultipartFile file) throws IOException {
        if (file == null || file.isEmpty()) {
            throw new IllegalArgumentException("file is empty");
        }

        Path tempRoot = Files.createTempDirectory("skill-extract-");
        try {
            zipSafeExtractor.extractTo(file, tempRoot);
            Path skillMd = tempRoot.resolve("SKILL.md");
            if (!Files.exists(skillMd)) {
                throw new IllegalArgumentException("SKILL.md not found in zip");
            }

            String skillName = detectSkillName(skillMd);
            Path target = userSkillsDir.resolve(skillName).normalize();
            if (!target.startsWith(userSkillsDir)) {
                throw new SecurityException("invalid skill name");
            }
            Files.createDirectories(userSkillsDir);
            deleteRecursively(target);
            Files.move(tempRoot, target);

            reloadRegistry();

            return new SkillUploadResponse(skillName, "1.0.0", "INSTALLED", true);
        } finally {
            deleteRecursively(tempRoot);
        }
    }

    private String detectSkillName(Path skillMd) throws IOException {
        for (String line : Files.readAllLines(skillMd)) {
            if (line.startsWith("name:")) {
                return line.substring("name:".length()).trim();
            }
        }
        return skillMd.getParent().getFileName().toString();
    }

    private void reloadRegistry() {
        if (skillRegistry instanceof AbstractSkillRegistry abstractRegistry) {
            abstractRegistry.reload();
        }
    }

    private void deleteRecursively(Path root) throws IOException {
        if (!Files.exists(root)) {
            return;
        }
        try (var paths = Files.walk(root)) {
            paths.sorted(Comparator.reverseOrder()).forEach(p -> {
                try {
                    Files.deleteIfExists(p);
                } catch (IOException e) {
                    throw new RuntimeException(e);
                }
            });
        }
    }

    private long parseSize(String raw) {
        String v = raw.trim().toUpperCase();
        if (v.endsWith("MB")) {
            return Long.parseLong(v.replace("MB", "").trim()) * 1024 * 1024;
        }
        if (v.endsWith("KB")) {
            return Long.parseLong(v.replace("KB", "").trim()) * 1024;
        }
        return Long.parseLong(v);
    }
}
