package com.dkws.skillruntime.model;

public record ToolCallReceipt(
        String toolId,
        String toolVersion,
        String skillId,
        String skillVersion,
        String status,
        String errorCode
) {
}
