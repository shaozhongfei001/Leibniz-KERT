package com.dkws.skillruntime.controller;

import com.alibaba.cloud.ai.graph.skills.SkillMetadata;
import com.alibaba.cloud.ai.graph.skills.registry.SkillRegistry;
import com.dkws.skillruntime.model.SkillInfo;
import com.dkws.skillruntime.model.SkillUploadResponse;
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

    public SkillAdminController(SkillUploadService skillUploadService,
                                SkillRegistry skillRegistry) {
        this.skillUploadService = skillUploadService;
        this.skillRegistry = skillRegistry;
    }

    @PostMapping(value = "/upload", consumes = MediaType.MULTIPART_FORM_DATA_VALUE)
    public SkillUploadResponse upload(@RequestPart("file") MultipartFile file) throws IOException {
        return skillUploadService.upload(file);
    }

    @GetMapping
    public List<SkillInfo> list() {
        return skillRegistry.listAll().stream()
                .map(this::toInfo)
                .toList();
    }

    @GetMapping("/{name}")
    public SkillInfo detail(@PathVariable String name) {
        return skillRegistry.get(name)
                .map(this::toInfo)
                .orElseThrow(() -> new IllegalArgumentException("skill not found: " + name));
    }

    private SkillInfo toInfo(SkillMetadata md) {
        return new SkillInfo(
                md.getName(),
                md.getDescription(),
                "1.0.0",
                List.of()
        );
    }
}
