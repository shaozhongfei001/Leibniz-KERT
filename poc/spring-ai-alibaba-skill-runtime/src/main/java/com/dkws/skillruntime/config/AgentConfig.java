package com.dkws.skillruntime.config;

import com.alibaba.cloud.ai.graph.agent.ReactAgent;
import com.alibaba.cloud.ai.graph.agent.hook.skills.SkillsAgentHook;
import com.alibaba.cloud.ai.graph.skills.registry.SkillRegistry;
import com.alibaba.cloud.ai.graph.skills.registry.filesystem.FileSystemSkillRegistry;
import com.dkws.skillruntime.model.SkillManifest;
import com.dkws.skillruntime.security.ShellCommandGuard;
import com.dkws.skillruntime.service.SkillLifecycleService;
import com.dkws.skillruntime.service.SkillToolRegistry;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.ai.tool.ToolCallback;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * Spring AI Alibaba Agent 配置（POC-2：动态 Skill->Tool 绑定）。
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
    public SkillsAgentHook skillsAgentHook(SkillRegistry skillRegistry,
                                           SkillLifecycleService lifecycleService,
                                           SkillToolRegistry toolRegistry) throws Exception {
        Map<String, List<ToolCallback>> groupedTools = new HashMap<>();
        Path skillsRoot = Path.of("user-skills").toAbsolutePath().normalize();
        if (Files.isDirectory(skillsRoot)) {
            try (var dirs = Files.list(skillsRoot)) {
                for (Path skillDir : dirs.toList()) {
                    String skillId = skillDir.getFileName().toString();
                    var manifestOpt = lifecycleService.currentManifest(skillId);
                    if (manifestOpt.isPresent()) {
                        SkillManifest manifest = manifestOpt.get();
                        groupedTools.put(skillId, toolRegistry.resolve(manifest.toolIds()));
                    }
                }
            }
        }

        return SkillsAgentHook.builder()
                .skillRegistry(skillRegistry)
                .autoReload(true)
                .groupedTools(groupedTools)
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
