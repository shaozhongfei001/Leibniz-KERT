package com.dkws.skillruntime.controller;

import com.alibaba.cloud.ai.graph.skills.SkillMetadata;
import com.alibaba.cloud.ai.graph.skills.registry.SkillRegistry;
import com.dkws.skillruntime.model.SkillInfo;
import com.dkws.skillruntime.model.SkillUploadResponse;
import com.dkws.skillruntime.service.SkillLifecycleService;
import com.dkws.skillruntime.service.SkillUploadService;
import org.springframework.http.MediaType;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;

import java.io.IOException;
import java.util.List;

@RestController
@RequestMapping("/api/skills")
public class SkillAdminController {

    private final SkillUploadService skillUploadService;
    private final SkillRegistry skillRegistry;
    private final SkillLifecycleService lifecycleService;

    public SkillAdminController(SkillUploadService skillUploadService,
                                SkillRegistry skillRegistry,
                                SkillLifecycleService lifecycleService) {
        this.skillUploadService = skillUploadService;
        this.skillRegistry = skillRegistry;
        this.lifecycleService = lifecycleService;
    }

    @PostMapping(value = "/upload", consumes = MediaType.MULTIPART_FORM_DATA_VALUE)
    public SkillUploadResponse upload(@RequestPart("file") MultipartFile file) throws IOException {
        return skillUploadService.upload(file);
    }

    @GetMapping
    public List<SkillInfo> list() throws IOException {
        return skillRegistry.listAll().stream()
                .map(md -> toInfo(md))
                .toList();
    }

    @GetMapping("/{name}")
    public SkillInfo detail(@PathVariable String name) throws IOException {
        SkillMetadata md = skillRegistry.get(name)
                .orElseThrow(() -> new IllegalArgumentException("skill not found: " + name));
        return toInfo(md);
    }

    private SkillInfo toInfo(SkillMetadata md) {
        try {
            var manifestOpt = lifecycleService.currentManifest(md.getName());
            if (manifestOpt.isPresent()) {
                var m = manifestOpt.get();
                return new SkillInfo(m.skillId(), md.getDescription(), m.version(), m.toolIds());
            }
        } catch (IOException ignored) {
        }
        return new SkillInfo(md.getName(), md.getDescription(), "1.0.0", List.of());
    }
}
