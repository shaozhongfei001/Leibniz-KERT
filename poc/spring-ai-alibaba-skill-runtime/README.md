# Spring AI Alibaba Skill Runtime PoC

> 状态：骨架候选，待按官方 1.1.2.0 API 补齐
> 目标：验证 Skill 动态导入、热加载、Tool_call 绑定、Python/Shell 沙箱执行

## 目录

```text
src/main/java/com/dkws/skillruntime/
├── SkillRuntimeApplication.java
├── controller/
│   ├── SkillAdminController.java
│   └── AgentChatController.java
├── service/
│   ├── SkillUploadService.java
│   └── SkillExecutionService.java
├── security/
│   ├── ZipSafeExtractor.java
│   └── ShellCommandGuard.java
├── config/
│   ├── CompositeSkillRegistryConfig.java
│   └── AgentConfig.java
└── model/
    ├── SkillInfo.java
    ├── SkillUploadResponse.java
    ├── ChatRequest.java
    └── ChatResponse.java
```

## 运行

```bash
cd poc/spring-ai-alibaba-skill-runtime
mvn spring-boot:run
```

服务默认端口：`18080`

## API

```bash
# 上传 Skill
curl -F "file=@demo-skill.zip" http://127.0.0.1:18080/api/skills/upload

# 技能列表
curl http://127.0.0.1:18080/api/skills

# Agent 执行（当前为 stub）
curl -X POST http://127.0.0.1:18080/api/agent/chat \
  -H 'Content-Type: application/json' \
  -d '{"message":"使用 demo-skill 处理文件","sessionId":"s1"}'
```

## 待接入 TODO

- [ ] 按官方 1.1.2.0 替换 `Object` 为真实 SkillRegistry / SkillsAgentHook
- [ ] 配置 ChatClient / ReActAgent
- [ ] 实现 `groupedTools` 技能-工具绑定
- [ ] 接入 PythonTool / ShellTool2
- [ ] 实现 Skill 列表/详情从 Registry 读取
- [ ] 增加热更新触发日志与审计
- [ ] 增加单元测试
