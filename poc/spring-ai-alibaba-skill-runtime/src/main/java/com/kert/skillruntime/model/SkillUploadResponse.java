package com.kert.skillruntime.model;

public record SkillUploadResponse(
        String skillName,
        String version,
        String status,
        boolean reloadTriggered
) {
}
