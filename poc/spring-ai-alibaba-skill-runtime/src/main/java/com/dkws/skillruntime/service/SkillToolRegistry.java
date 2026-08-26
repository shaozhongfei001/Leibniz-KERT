package com.dkws.skillruntime.service;

import com.alibaba.cloud.ai.agent.python.tool.PythonTool;
import com.alibaba.cloud.ai.graph.agent.tools.ShellTool;
import org.springframework.ai.tool.ToolCallback;
import org.springframework.stereotype.Service;

import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * POC-2：根据 Skill manifest 中 toolIds 动态构建 ToolCallback 集合。
 * 当前支持 python、shell；后续可扩展。
 */
@Service
public class SkillToolRegistry {

    private final Map<String, ToolCallback> tools = new HashMap<>();

    public SkillToolRegistry() {
        tools.put("python", PythonTool.createPythonToolCallback("python"));
        tools.put("shell", ShellTool.builder("shell")
                .withName("shell")
                .withDescription("Execute shell command")
                .withCommandTimeout(10_000)
                .withMaxOutputLines(200)
                .build());
    }

    public List<ToolCallback> resolve(List<String> toolIds) {
        return toolIds.stream()
                .map(tools::get)
                .filter(java.util.Objects::nonNull)
                .toList();
    }
}
