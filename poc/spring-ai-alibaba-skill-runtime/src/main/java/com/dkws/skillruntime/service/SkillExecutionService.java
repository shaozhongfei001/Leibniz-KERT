package com.dkws.skillruntime.service;

import com.alibaba.cloud.ai.graph.agent.ReactAgent;
import com.dkws.skillruntime.model.ChatRequest;
import com.dkws.skillruntime.model.ChatResponse;
import org.springframework.stereotype.Service;

import java.util.List;
import java.util.Map;

/**
 * Skill 执行服务：通过 Spring AI Alibaba ReactAgent 执行。
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
            // PoC 暂不解析内部 toolCalls；真实 trace 可在后续通过 Hook/Interceptor 输出
            return new ChatResponse(
                    answer,
                    List.of(),
                    List.of("agent.call")
            );
        } catch (Exception e) {
            return new ChatResponse(
                    "SKILL_RUNTIME_ERROR: " + e.getMessage(),
                    List.of(Map.of("status", "error")),
                    List.of("agent.call.failed")
            );
        }
    }
}
