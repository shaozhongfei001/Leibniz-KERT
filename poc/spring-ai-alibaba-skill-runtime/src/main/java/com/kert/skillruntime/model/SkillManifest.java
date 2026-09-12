package com.kert.skillruntime.model;

import java.util.List;

public record SkillManifest(
        String skillId,
        String version,
        String hash,
        List<String> toolIds,
        String policyRef
) {
}
