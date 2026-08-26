package com.dkws.skillruntime.model;

public record SkillUploadResponse(
        String skillName,
        String version,
        String status,
        boolean reloadTriggered
) {
}
