package com.dkws.skillruntime.model;

import java.util.List;

public record ChatResponse(
        String answer,
        List<java.util.Map<String, String>> toolCalls,
        List<String> trace,
        List<ToolCallReceipt> toolCallReceipts,
        List<ModelCallReceipt> modelCallReceipts
) {
}
