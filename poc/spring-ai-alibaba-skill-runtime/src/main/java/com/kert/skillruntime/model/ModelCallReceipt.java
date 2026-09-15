package com.kert.skillruntime.model;

public record ModelCallReceipt(
        String model,
        int inputTokens,
        int outputTokens,
        long latencyMs,
        String status
) {
}
