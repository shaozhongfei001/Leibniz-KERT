package com.dkws.skillruntime.model;

import java.util.List;
import java.util.Map;

public record ChatResponse(
        String answer,
        List<Map<String, String>> toolCalls,
        List<String> trace
) {
}
