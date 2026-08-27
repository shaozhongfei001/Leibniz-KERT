package com.dkws.skillruntime.service;

import com.dkws.skillruntime.model.SkillManifest;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.Optional;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * Skill 生命周期测试（施工令第十一节 §3）：
 * install / activate / rollback / 重复安装 / hash 不匹配 / 两版本并存 /
 * 激活失败保持旧版本 / 重启后活动版本可恢复。
 *
 * <p>核心不变量：<b>install 绝不切换活动版本</b>，切换只能由显式 activate 完成。
 */
class SkillLifecycleServiceTest {

    @TempDir
    Path tempDir;

    private SkillLifecycleService service() {
        return new SkillLifecycleService(tempDir.resolve("skills").toString());
    }

    private Path stage(String name, String version, String tools) throws IOException {
        Path staged = tempDir.resolve("staged-" + name + "-" + version);
        Files.createDirectories(staged);
        Files.writeString(staged.resolve("SKILL.md"), """
                ---
                name: %s
                version: %s
                tools: %s
                ---
                # %s v%s
                """.formatted(name, version, tools, name, version));
        return staged;
    }

    // ---------------------------------------------------------------- install

    @Test
    void installDoesNotActivate() throws Exception {
        SkillLifecycleService service = service();
        SkillManifest manifest = service.install("test-skill", "1.0.0", stage("test-skill", "1.0.0", "python"));

        assertEquals("test-skill", manifest.skillId());
        assertEquals("1.0.0", manifest.version());
        assertFalse(manifest.hash().isBlank());
        assertTrue(manifest.toolIds().contains("python"));

        // 关键：install 之后不得有活动版本
        assertEquals(Optional.empty(), service.currentVersion("test-skill"),
                "install must not switch the active version");
        assertEquals(Optional.empty(), service.currentManifest("test-skill"));
        assertEquals(List.of("1.0.0"), service.listVersions("test-skill"));
    }

    @Test
    void explicitActivateSwitchesActiveVersion() throws Exception {
        SkillLifecycleService service = service();
        service.install("test-skill", "1.0.0", stage("test-skill", "1.0.0", "python"));
        service.activate("test-skill", "1.0.0");

        assertEquals(Optional.of("1.0.0"), service.currentVersion("test-skill"));
        assertTrue(service.currentManifest("test-skill").isPresent());
    }

    @Test
    void repeatedInstallIsIdempotentAndDoesNotDisturbActive() throws Exception {
        SkillLifecycleService service = service();
        service.install("test-skill", "1.0.0", stage("test-skill", "1.0.0", "python"));
        service.activate("test-skill", "1.0.0");
        service.install("test-skill", "2.0.0", stage("test-skill", "2.0.0", "python"));

        // 重复安装同版本
        SkillManifest again = service.install("test-skill", "1.0.0", stage("test-skill", "1.0.0", "python"));
        assertEquals("1.0.0", again.version());

        // 活动版本仍是 1.0.0，未被 2.0.0 安装动作影响
        assertEquals(Optional.of("1.0.0"), service.currentVersion("test-skill"));
        assertEquals(List.of("2.0.0", "1.0.0"), service.listVersions("test-skill"));
    }

    @Test
    void hashMismatchIsRejectedAndPackageRemoved() throws Exception {
        SkillLifecycleService service = service();
        SecurityException ex = assertThrows(SecurityException.class, () ->
                service.installVerified("test-skill", "1.0.0",
                        stage("test-skill", "1.0.0", "python"), "0".repeat(64)));
        assertTrue(ex.getMessage().contains("SKILL_HASH_MISMATCH"), ex.getMessage());

        // fail-closed：不匹配的包不得残留
        assertEquals(List.of(), service.listVersions("test-skill"));
    }

    @Test
    void hashMatchIsAccepted() throws Exception {
        SkillLifecycleService service = service();
        SkillManifest first = service.install("test-skill", "1.0.0", stage("test-skill", "1.0.0", "python"));

        SkillLifecycleService fresh = new SkillLifecycleService(tempDir.resolve("skills2").toString());
        SkillManifest staged = fresh.install("test-skill", "1.0.0", stage("test-skill", "1.0.0", "python"));
        assertEquals(first.hash(), staged.hash(), "same content must yield same hash");

        // 用正确 hash 安装应通过
        SkillManifest verified = fresh.installVerified("test-skill", "1.0.0",
                stage("test-skill", "1.0.0", "python"), staged.hash());
        assertEquals(staged.hash(), verified.hash());
    }

    // ---------------------------------------------------------------- 多版本

    @Test
    void twoVersionsCoexistAndOnlyOneIsActive() throws Exception {
        SkillLifecycleService service = service();
        SkillManifest v1 = service.install("test-skill", "1.0.0", stage("test-skill", "1.0.0", "python"));
        SkillManifest v2 = service.install("test-skill", "2.0.0", stage("test-skill", "2.0.0", "python,shell"));

        assertNotEquals(v1.hash(), v2.hash(), "different content must yield different hash");
        assertEquals(List.of("2.0.0", "1.0.0"), service.listVersions("test-skill"));

        service.activate("test-skill", "1.0.0");
        assertEquals(Optional.of("1.0.0"), service.currentVersion("test-skill"));
        assertEquals(List.of("python"), service.currentManifest("test-skill").orElseThrow().toolIds());

        service.activate("test-skill", "2.0.0");
        assertEquals(Optional.of("2.0.0"), service.currentVersion("test-skill"));
        assertEquals(List.of("python", "shell"), service.currentManifest("test-skill").orElseThrow().toolIds());

        // 两个版本目录都仍然存在（旧版本未被销毁，可回滚）
        assertEquals(List.of("2.0.0", "1.0.0"), service.listVersions("test-skill"));
    }

    @Test
    void rollbackRestoresPreviousVersion() throws Exception {
        SkillLifecycleService service = service();
        service.install("test-skill", "1.0.0", stage("test-skill", "1.0.0", "python"));
        service.install("test-skill", "2.0.0", stage("test-skill", "2.0.0", "python,shell"));
        service.activate("test-skill", "1.0.0");
        service.activate("test-skill", "2.0.0");
        assertEquals(Optional.of("2.0.0"), service.currentVersion("test-skill"));

        service.rollback("test-skill", "1.0.0");
        assertEquals(Optional.of("1.0.0"), service.currentVersion("test-skill"));
        assertEquals(List.of("python"), service.currentManifest("test-skill").orElseThrow().toolIds());
    }

    // ---------------------------------------------------------------- 失败保持

    @Test
    void activateUnknownVersionKeepsCurrentActive() throws Exception {
        SkillLifecycleService service = service();
        service.install("test-skill", "1.0.0", stage("test-skill", "1.0.0", "python"));
        service.activate("test-skill", "1.0.0");

        assertThrows(IllegalArgumentException.class, () -> service.activate("test-skill", "9.9.9"));

        // 激活失败必须保持旧版本可服务
        assertEquals(Optional.of("1.0.0"), service.currentVersion("test-skill"));
        assertTrue(service.currentManifest("test-skill").isPresent());
    }

    @Test
    void activateBrokenPackageKeepsCurrentActive() throws Exception {
        SkillLifecycleService service = service();
        service.install("test-skill", "1.0.0", stage("test-skill", "1.0.0", "python"));
        service.activate("test-skill", "1.0.0");

        // 构造一个缺 SKILL.md 的坏版本（模拟安装后被破坏）
        Path broken = tempDir.resolve("skills").resolve(".versions").resolve("test-skill").resolve("3.0.0");
        Files.createDirectories(broken);
        Files.writeString(broken.resolve("README.md"), "no manifest here");

        assertThrows(IllegalStateException.class, () -> service.activate("test-skill", "3.0.0"));

        // 旧版本仍然活动且完好
        assertEquals(Optional.of("1.0.0"), service.currentVersion("test-skill"));
        assertTrue(Files.exists(tempDir.resolve("skills").resolve("test-skill").resolve("SKILL.md")));
    }

    @Test
    void pathTraversalInSkillIdIsRejected() {
        SkillLifecycleService service = service();
        assertThrows(SecurityException.class, () ->
                service.install("../../etc", "1.0.0", stage("evil", "1.0.0", "python")));
    }

    // ---------------------------------------------------------------- 重启恢复

    @Test
    void activeVersionSurvivesRuntimeRestart() throws Exception {
        Path skillsRoot = tempDir.resolve("skills");
        SkillLifecycleService before = new SkillLifecycleService(skillsRoot.toString());
        before.install("test-skill", "1.0.0", stage("test-skill", "1.0.0", "python"));
        before.install("test-skill", "2.0.0", stage("test-skill", "2.0.0", "python,shell"));
        before.activate("test-skill", "2.0.0");

        // 模拟进程重启：新建 Service 实例读取同一目录（Runtime 无状态，状态在文件系统）
        SkillLifecycleService after = new SkillLifecycleService(skillsRoot.toString());
        assertEquals(Optional.of("2.0.0"), after.currentVersion("test-skill"));
        assertEquals(List.of("2.0.0", "1.0.0"), after.listVersions("test-skill"));
        assertEquals(List.of("python", "shell"), after.currentManifest("test-skill").orElseThrow().toolIds());
    }

    @Test
    void noLeftoverStagingOrBackupDirsAfterActivation() throws Exception {
        Path skillsRoot = tempDir.resolve("skills");
        SkillLifecycleService service = new SkillLifecycleService(skillsRoot.toString());
        service.install("test-skill", "1.0.0", stage("test-skill", "1.0.0", "python"));
        service.activate("test-skill", "1.0.0");
        service.install("test-skill", "2.0.0", stage("test-skill", "2.0.0", "python"));
        service.activate("test-skill", "2.0.0");

        assertFalse(Files.exists(skillsRoot.resolve(".staging-test-skill")), "staging dir must be cleaned up");
        assertFalse(Files.exists(skillsRoot.resolve(".backup-test-skill")), "backup dir must be cleaned up");
    }
}
