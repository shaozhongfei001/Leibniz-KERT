package com.dkws.skillruntime.model;

import java.util.List;

public record RuntimeCapabilities(
        String runtimeVersion,
        String contractVersion,
        String contractHash,
        String frameworkVersion,
        List<String> activatedSkills,
        String sandboxCapability,
        boolean degraded,
        String status
) {
}
