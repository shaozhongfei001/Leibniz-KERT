package com.dkws.skillruntime.service;

import com.alibaba.cloud.ai.graph.agent.ReactAgent;
import com.dkws.skillruntime.model.ChatRequest;
import com.dkws.skillruntime.model.ChatResponse;
import com.dkws.skillruntime.model.ModelCallReceipt;
import com.dkws.skillruntime.model.ToolCallReceipt;
import org.springframework.stereotype.Service;

import java.util.List;
import java.util.Map;

/**
 * Skill 执行服务：通过 Spring AI Alibaba ReactAgent 执行。
 * POC-2 先返回结构化 receipt 容器；真实 tool/model 回执由后续 Interceptor 填充。
 */
@Service
public class SkillExecutionService {

    private final ReactAgent reactAgent;

    public SkillExecutionService(ReactAgent reactAgent) {
        this.reactAgent = reactAgent;
    }

    public ChatResponse chat(ChatRequest request) {
        try {
            var message = reactAgent.call(request.message());
            String answer = message.getText();
            return new ChatResponse(
                    answer,
                    List.of(),
                    List.of("agent.call"),
                    List.of(),
                    List.of()
            );
        } catch (Exception e) {
            return new ChatResponse(
                    "SKILL_RUNTIME_ERROR: " + e.getMessage(),
                    List.of(Map.of("status", "error")),
                    List.of("agent.call.failed"),
                    List.of(),
                    List.of()
            );
        }
    }
}
