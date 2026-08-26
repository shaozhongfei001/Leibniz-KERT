package com.dkws.skillruntime.service;

import com.alibaba.cloud.ai.graph.skills.registry.SkillRegistry;
import com.alibaba.cloud.ai.graph.skills.registry.AbstractSkillRegistry;
import com.dkws.skillruntime.model.SkillManifest;
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
    private final SkillLifecycleService lifecycleService;

    public SkillUploadService(
            @Value("${skill-runtime.user-skills-dir}") String userSkillsDir,
            @Value("${skill-runtime.max-skill-zip-size:20MB}") String maxZipSize,
            @Value("${skill-runtime.max-skill-files:200}") int maxFiles,
            SkillRegistry skillRegistry,
            SkillLifecycleService lifecycleService) {
        this.userSkillsDir = Path.of(userSkillsDir).toAbsolutePath().normalize();
        this.zipSafeExtractor = new ZipSafeExtractor(parseSize(maxZipSize), maxFiles);
        this.skillRegistry = skillRegistry;
        this.lifecycleService = lifecycleService;
    }

    public SkillUploadResponse upload(MultipartFile file) throws IOException {
        if (file == null || file.isEmpty()) {
            throw new IllegalArgumentException("file is empty");
        }

        Path tempRoot = Files.createTempDirectory("skill-staging-");
        try {
            zipSafeExtractor.extractTo(file, tempRoot);
            Path skillMd = tempRoot.resolve("SKILL.md");
            if (!Files.exists(skillMd)) {
                throw new IllegalArgumentException("SKILL.md not found in zip");
            }

            String skillId = detectSkillName(skillMd);
            String version = detectVersion(skillMd);
            SkillManifest manifest = lifecycleService.install(skillId, version, tempRoot);
            lifecycleService.activate(skillId, version);

            reloadRegistry();

            return new SkillUploadResponse(skillId, manifest.version(), "INSTALLED_AND_ACTIVATED", true);
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

    private String detectVersion(Path skillMd) throws IOException {
        for (String line : Files.readAllLines(skillMd)) {
            if (line.startsWith("version:")) {
                return line.substring("version:".length()).trim();
            }
        }
        return "1.0.0";
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
