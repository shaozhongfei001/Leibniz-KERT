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
 */
@Service
public class SkillLifecycleService {

    private final Path skillsRoot;

    public SkillLifecycleService(@Value("${skill-runtime.user-skills-dir}") String userSkillsDir) {
        this.skillsRoot = Path.of(userSkillsDir).toAbsolutePath().normalize();
    }

    public SkillManifest install(String skillId, String version, Path stagedDir) throws IOException {
        Path versionDir = skillsRoot.resolve(".versions").resolve(skillId).resolve(version).normalize();
        if (!versionDir.startsWith(skillsRoot)) {
            throw new SecurityException("invalid skill path");
        }
        Files.createDirectories(versionDir);
        deleteRecursively(versionDir);
        copyTree(stagedDir, versionDir);
        activate(skillId, version);
        return currentManifest(skillId).orElseThrow();
    }

    public void activate(String skillId, String version) throws IOException {
        Path versionDir = skillsRoot.resolve(".versions").resolve(skillId).resolve(version).normalize();
        if (!Files.isDirectory(versionDir)) {
            throw new IllegalArgumentException("version not found: " + version);
        }
        Path activeDir = skillsRoot.resolve(skillId).normalize();
        deleteRecursively(activeDir);
        Files.createDirectories(activeDir);
        copyTree(versionDir, activeDir);
        Files.writeString(skillsRoot.resolve(skillId).resolve("CURRENT"), version + "\n", StandardCharsets.UTF_8);
    }

    public Optional<String> currentVersion(String skillId) throws IOException {
        Path current = skillsRoot.resolve(skillId).resolve("CURRENT");
        if (!Files.exists(current)) {
            return Optional.empty();
        }
        return Optional.of(Files.readString(current).trim());
    }

    public Optional<SkillManifest> currentManifest(String skillId) throws IOException {
        Path activeDir = skillsRoot.resolve(skillId);
        Path skillMd = activeDir.resolve("SKILL.md");
        if (!Files.exists(skillMd)) {
            return Optional.empty();
        }
        String version = detectVersion(skillMd);
        String hash = sha256Dir(activeDir);
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
