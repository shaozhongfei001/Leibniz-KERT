package com.dkws.skillruntime.service;

import com.dkws.skillruntime.model.SkillManifest;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import java.nio.file.Files;
import java.nio.file.Path;

import static org.junit.jupiter.api.Assertions.*;

class SkillLifecycleServiceTest {

    @TempDir
    Path tempDir;

    @Test
    void installActivateAndRollback() throws Exception {
        Path skillsRoot = tempDir.resolve("skills");
        SkillLifecycleService service = new SkillLifecycleService(skillsRoot.toString());

        Path staged = tempDir.resolve("staged");
        Files.createDirectories(staged);
        Files.writeString(staged.resolve("SKILL.md"), """
                ---
                name: test-skill
                version: 1.0.0
                tools: python
                ---
                """);

        SkillManifest manifest = service.install("test-skill", "1.0.0", staged);
        assertEquals("test-skill", manifest.skillId());
        assertEquals("1.0.0", manifest.version());
        assertFalse(manifest.hash().isBlank());
        assertTrue(manifest.toolIds().contains("python"));

        assertTrue(service.currentVersion("test-skill").isPresent());
        assertEquals("1.0.0", service.currentVersion("test-skill").get());

        service.rollback("test-skill", "1.0.0");
        assertTrue(Files.exists(skillsRoot.resolve("test-skill").resolve("SKILL.md")));
    }
}
