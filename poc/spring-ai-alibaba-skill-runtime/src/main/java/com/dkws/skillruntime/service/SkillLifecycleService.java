package com.dkws.skillruntime.service;

import com.dkws.skillruntime.model.SkillManifest;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.Comparator;
import java.util.HexFormat;
import java.util.List;
import java.util.Optional;
import java.util.stream.Stream;

/**
 * POC-2 Skill 生命周期：支持 flat active（FileSystemSkillRegistry） + versions 归档。
 *
 * <p><b>权威边界</b>：Skill 包的审核、版本、hash、签名、激活与撤销记录由
 * Python Core 控制面拥有。本 Service 只是 Runtime 侧的执行者，只负责
 * 「安装到 staging」「按指令原子切换」「回滚」，不自行决定该激活哪个版本。
 *
 * <p><b>install 与 activate 严格分离</b>（施工令 R4 第 5~7 项）：
 * {@code install} 只把包写入 {@code .versions/<skillId>/<version>}，
 * <b>绝不</b>触碰活动目录；切换活动版本必须由显式 {@code activate} 完成。
 *
 * <p><b>activate 失败保持旧版本</b>：切换采用「先写 staging 目录 -> 校验 ->
 * 原子替换」，任一步失败都恢复原活动版本，不留下半切换状态。
 */
@Service
public class SkillLifecycleService {

    private final Path skillsRoot;

    public SkillLifecycleService(@Value("${skill-runtime.user-skills-dir}") String userSkillsDir) {
        this.skillsRoot = Path.of(userSkillsDir).toAbsolutePath().normalize();
    }

    /**
     * 安装 Skill 包到 staging（版本归档区），<b>不激活</b>。
     *
     * <p>重复安装同 skillId+version 幂等覆盖该版本目录，但不影响当前活动版本。
     *
     * @return 已安装版本的 manifest（读自版本目录，非活动目录）
     */
    public SkillManifest install(String skillId, String version, Path stagedDir) throws IOException {
        Path versionDir = versionDir(skillId, version);
        Files.createDirectories(versionDir);
        deleteRecursively(versionDir);
        copyTree(stagedDir, versionDir);
        return manifestOf(skillId, versionDir)
                .orElseThrow(() -> new IllegalArgumentException("SKILL.md missing in package: " + skillId));
    }

    /**
     * 安装并校验期望哈希。哈希不匹配时删除已落盘内容并拒绝（fail-closed）。
     */
    public SkillManifest installVerified(String skillId, String version, Path stagedDir, String expectedHash)
            throws IOException {
        SkillManifest manifest = install(skillId, version, stagedDir);
        if (expectedHash != null && !expectedHash.isBlank() && !expectedHash.equals(manifest.hash())) {
            deleteRecursively(versionDir(skillId, version));
            throw new SecurityException("SKILL_HASH_MISMATCH: expected=" + expectedHash
                    + " actual=" + manifest.hash());
        }
        return manifest;
    }

    /**
     * 原子切换活动版本。失败时保持原活动版本可继续服务。
     */
    public void activate(String skillId, String version) throws IOException {
        Path versionDir = versionDir(skillId, version);
        if (!Files.isDirectory(versionDir)) {
            throw new IllegalArgumentException("version not found: " + version);
        }

        Path activeDir = skillsRoot.resolve(skillId).normalize();
        Path stagingDir = skillsRoot.resolve(".staging-" + skillId).normalize();
        Path backupDir = skillsRoot.resolve(".backup-" + skillId).normalize();

        // 1) 先在独立 staging 目录构建完整新版本，避免中途失败破坏活动目录
        deleteRecursively(stagingDir);
        Files.createDirectories(stagingDir);
        copyTree(versionDir, stagingDir);
        Files.writeString(stagingDir.resolve("CURRENT"), version + "\n", StandardCharsets.UTF_8);
        if (!Files.exists(stagingDir.resolve("SKILL.md"))) {
            deleteRecursively(stagingDir);
            throw new IllegalStateException("ACTIVATION_FAILED: SKILL.md missing in version " + version);
        }

        // 2) 备份旧活动版本，再原子替换
        boolean hadPrevious = Files.isDirectory(activeDir);
        deleteRecursively(backupDir);
        if (hadPrevious) {
            Files.move(activeDir, backupDir, StandardCopyOption.ATOMIC_MOVE);
        }
        try {
            Files.move(stagingDir, activeDir, StandardCopyOption.ATOMIC_MOVE);
        } catch (IOException | RuntimeException e) {
            // 切换失败：恢复旧版本，保证服务不中断
            if (hadPrevious && !Files.exists(activeDir)) {
                Files.move(backupDir, activeDir, StandardCopyOption.ATOMIC_MOVE);
            }
            deleteRecursively(stagingDir);
            throw e;
        }
        deleteRecursively(backupDir);
    }

    public Optional<String> currentVersion(String skillId) throws IOException {
        Path current = skillsRoot.resolve(skillId).resolve("CURRENT");
        if (!Files.exists(current)) {
            return Optional.empty();
        }
        return Optional.of(Files.readString(current).trim());
    }

    public Optional<SkillManifest> currentManifest(String skillId) throws IOException {
        return manifestOf(skillId, skillsRoot.resolve(skillId));
    }

    /** 读取指定目录下的 Skill manifest（可用于活动目录或版本目录）。 */
    public Optional<SkillManifest> manifestOf(String skillId, Path dir) throws IOException {
        Path skillMd = dir.resolve("SKILL.md");
        if (!Files.exists(skillMd)) {
            return Optional.empty();
        }
        String version = detectVersion(skillMd);
        String hash = sha256Dir(dir);
        List<String> toolIds = readToolIds(skillMd);
        return Optional.of(new SkillManifest(skillId, version, hash, toolIds, "policy-default"));
    }

    public void rollback(String skillId, String version) throws IOException {
        activate(skillId, version);
    }

    public List<String> listVersions(String skillId) throws IOException {
        Path versions = skillsRoot.resolve(".versions").resolve(skillId);
        if (!Files.isDirectory(versions)) {
            return List.of();
        }
        try (Stream<Path> stream = Files.list(versions)) {
            return stream.map(p -> p.getFileName().toString()).sorted(Comparator.reverseOrder()).toList();
        }
    }

    private Path versionDir(String skillId, String version) {
        Path dir = skillsRoot.resolve(".versions").resolve(skillId).resolve(version).normalize();
        if (!dir.startsWith(skillsRoot)) {
            throw new SecurityException("invalid skill path");
        }
        return dir;
    }

    private List<String> readToolIds(Path skillMd) throws IOException {
        if (!Files.exists(skillMd)) {
            return List.of();
        }
        var lines = Files.readAllLines(skillMd);
        for (int i = 0; i < lines.size(); i++) {
            String line = lines.get(i);
            if (line.startsWith("tools:")) {
                String value = line.substring("tools:".length()).trim();
                if (!value.isEmpty()) {
                    return java.util.Arrays.stream(value.split(","))
                            .map(String::trim)
                            .filter(s -> !s.isEmpty())
                            .toList();
                }
                java.util.ArrayList<String> ids = new java.util.ArrayList<>();
                for (int j = i + 1; j < lines.size(); j++) {
                    String next = lines.get(j).trim();
                    if (next.startsWith("- ")) {
                        ids.add(next.substring(2).trim());
                    } else if (next.isEmpty() || next.startsWith("---")) {
                        break;
                    }
                }
                return ids;
            }
        }
        return List.of();
    }

    private String detectVersion(Path skillMd) throws IOException {
        for (String line : Files.readAllLines(skillMd)) {
            if (line.startsWith("version:")) {
                return line.substring("version:".length()).trim();
            }
        }
        return "1.0.0";
    }

    private void copyTree(Path src, Path dst) throws IOException {
        try (Stream<Path> stream = Files.walk(src)) {
            for (Path p : stream.sorted().toList()) {
                Path target = dst.resolve(src.relativize(p).toString()).normalize();
                if (!target.startsWith(dst)) {
                    throw new SecurityException("path escape");
                }
                if (Files.isDirectory(p)) {
                    Files.createDirectories(target);
                } else {
                    Files.createDirectories(target.getParent());
                    Files.copy(p, target, StandardCopyOption.REPLACE_EXISTING);
                }
            }
        }
    }

    private String sha256Dir(Path dir) throws IOException {
        MessageDigest md;
        try {
            md = MessageDigest.getInstance("SHA-256");
        } catch (NoSuchAlgorithmException e) {
            throw new IllegalStateException(e);
        }
        try (Stream<Path> stream = Files.walk(dir)) {
            for (Path p : stream.sorted().toList()) {
                if (Files.isRegularFile(p)) {
                    md.update(dir.relativize(p).toString().getBytes(StandardCharsets.UTF_8));
                    md.update(Files.readAllBytes(p));
                }
            }
        }
        return HexFormat.of().formatHex(md.digest());
    }

    private void deleteRecursively(Path root) throws IOException {
        if (!Files.exists(root)) {
            return;
        }
        try (Stream<Path> stream = Files.walk(root)) {
            stream.sorted(Comparator.reverseOrder()).forEach(p -> {
                try {
                    Files.deleteIfExists(p);
                } catch (IOException e) {
                    throw new RuntimeException(e);
                }
            });
        }
    }
}
