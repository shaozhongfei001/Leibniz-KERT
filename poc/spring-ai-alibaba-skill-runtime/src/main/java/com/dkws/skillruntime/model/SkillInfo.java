package com.dkws.skillruntime.model;

import java.util.List;

public record SkillInfo(
        String name,
        String description,
        String version,
        List<String> tools
) {
}
