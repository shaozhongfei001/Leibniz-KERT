package com.dkws.skillruntime.config;

import com.alibaba.cloud.ai.agent.python.tool.PythonTool;
import com.alibaba.cloud.ai.graph.agent.ReactAgent;
import com.alibaba.cloud.ai.graph.agent.hook.skills.SkillsAgentHook;
import com.alibaba.cloud.ai.graph.agent.tools.ShellTool;
import com.alibaba.cloud.ai.graph.skills.registry.SkillRegistry;
import com.alibaba.cloud.ai.graph.skills.registry.filesystem.FileSystemSkillRegistry;
import com.dkws.skillruntime.security.ShellCommandGuard;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.ai.tool.ToolCallback;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

import java.nio.file.Path;
import java.util.List;
import java.util.Map;

/**
 * Spring AI Alibaba Agent 配置。
 */
@Configuration
public class AgentConfig {

    @Bean
    public SkillRegistry fileSystemSkillRegistry(
            @Value("${skill-runtime.user-skills-dir}") String userSkillsDir) {
        return FileSystemSkillRegistry.builder()
                .userSkillsDirectory(Path.of(userSkillsDir).toAbsolutePath().toString())
                .autoLoad(true)
                .build();
    }

    @Bean
    public ShellCommandGuard shellCommandGuard(
            @Value("${skill-runtime.sandbox.allowed-shell-commands:ls,cat,head,tail,python3}") String allowed) {
        return new ShellCommandGuard(List.of(allowed.split(",")));
    }

    @Bean
    public SkillsAgentHook skillsAgentHook(SkillRegistry skillRegistry) {
        ToolCallback python = PythonTool.createPythonToolCallback("python");
        ToolCallback shell = ShellTool.builder("shell")
                .withName("shell")
                .withDescription("Execute shell command")
                .withCommandTimeout(10_000)
                .withMaxOutputLines(200)
                .build();

        return SkillsAgentHook.builder()
                .skillRegistry(skillRegistry)
                .autoReload(true)
                .groupedTools(Map.of(
                        "demo-skill", List.of(python, shell)
                ))
                .build();
    }

    @Bean
    public ReactAgent reactAgent(ChatClient.Builder chatClientBuilder,
                                 SkillsAgentHook skillsAgentHook) {
        ChatClient chatClient = chatClientBuilder.build();
        return ReactAgent.builder()
                .name("dkws-skill-agent")
                .chatClient(chatClient)
                .hooks(skillsAgentHook)
                .build();
    }
}
