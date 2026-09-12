package com.kert.skillruntime.model;

import jakarta.validation.constraints.NotBlank;

public record ChatRequest(
        @NotBlank String message,
        String sessionId
) {
}
