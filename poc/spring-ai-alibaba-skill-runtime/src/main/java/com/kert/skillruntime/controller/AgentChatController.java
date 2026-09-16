package com.kert.skillruntime.controller;

import com.kert.skillruntime.model.ChatRequest;
import com.kert.skillruntime.model.ChatResponse;
import com.kert.skillruntime.service.SkillExecutionService;
import jakarta.validation.Valid;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/agent")
public class AgentChatController {

    private final SkillExecutionService skillExecutionService;

    public AgentChatController(SkillExecutionService skillExecutionService) {
        this.skillExecutionService = skillExecutionService;
    }

    @PostMapping("/chat")
    public ChatResponse chat(@Valid @RequestBody ChatRequest request) {
        return skillExecutionService.chat(request);
    }
}
