package com.dkws.skillruntime.model;

import java.util.List;

public record ExecutionResult(
        String requestId,
        String status,
        boolean usable,
        boolean releaseAllowed,
        String answer,
        List<ToolCallReceipt> toolCallReceipts,
        List<ModelCallReceipt> modelCallReceipts,
        List<String> trace
) {
}
