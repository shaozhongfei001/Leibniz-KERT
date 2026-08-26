# Spring AI Alibaba Skill 运行态最小落地设计（PoC）

> 状态：CANDIDATE
> 日期：2026-08-26
> 目标：验证 Spring AI Alibaba 能否支撑 DKWS 所需 Skill 运行态闭环
> 版本基线：Spring AI Alibaba 1.1.2.0（以官方文档为准）
> 关联：`DKWS_ADAPTER_FIRST_TECH_STACK_V1.1.md`

## 1. PoC 目标

用一个最小可运行 Spring Boot 服务验证：

1. 运行态导入 Skill：上传 zip / 放入目录即可被识别；
2. 热加载：新增/修改 SKILL.md 或 scripts，无需重启；
3. Tool_call 与 Skill 深度绑定：模型先 read_skill，再按需调用该 Skill 绑定的工具；
4. Python/Shell 沙箱执行：Skill 内脚本可被安全执行。

## 2. 非目标

- 不实现完整生产级管理后台
- 不实现多租户
- 不接入 DKWS 全部知识源
- 不替代 DKWS Python 核心
- 不做生产级审计/权限闭环（PoC 只做最小安全边界）

## 3. 总体架构

```text
┌────────────────────────────────────────────────────┐
│              Spring Boot Skill Runtime             │
│                                                    │
│  REST Controller                                   │
│   ├── POST /api/skills/upload       上传/热加载    │
│   ├── GET  /api/skills              技能列表       │
│   ├── GET  /api/skills/{name}       技能详情       │
│   └── POST /api/agent/chat          执行入口       │
│                                                    │
│  SkillRegistry                                     │
│   ├── FileSystemSkillRegistry（用户技能）          │
│   ├── ClasspathSkillRegistry（系统内置，可选）     │
│   └── CompositeSkillRegistry                       │
│                                                    │
│  SkillsAgentHook (autoReload=true)                 │
│   └── read_skill 渐进式披露                        │
│                                                    │
│  ToolRegistry                                      │
│   ├── groupedTools：Skill -> Tools                 │
│   ├── PythonTool（GraalVM 沙箱）                   │
│   └── ShellTool2（Shell 沙箱）                     │
│                                                    │
│  ChatClient / ReActAgent                           │
│                                                    │
│  Security                                         │
│   ├── zip 解压校验 / 路径穿越防护                  │
│   ├── 文件大小/数量限制                            │
│   ├── 命令白名单 / 工作目录隔离                    │
│   └── 审计日志（PoC 最小）                         │
└────────────────────────────────────────────────────┘
```

## 4. 目录结构

```text
skill-runtime-poc/
├── pom.xml
├── src/main/java/com/example/skillruntime/
│   ├── SkillRuntimeApplication.java
│   ├── controller/
│   │   ├── SkillAdminController.java
│   │   └── AgentChatController.java
│   ├── registry/
│   │   └── CompositeSkillRegistryConfig.java
│   ├── service/
│   │   ├── SkillUploadService.java
│   │   └── SkillExecutionService.java
│   ├── security/
│   │   ├── ZipSafeExtractor.java
│   │   └── ShellCommandGuard.java
│   └── config/
│       └── AgentConfig.java
├── src/main/resources/
│   ├── application.yml
│   └── skills/            # 系统内置技能（可选）
└── user-skills/           # 外部可写技能目录（运行态热加载）
    └── demo-skill/
        ├── SKILL.md
        ├── scripts/
        │   ├── extract.py
        │   └── run.sh
        └── references/
            └── input-schema.json
```

## 5. 核心设计

### 5.1 SkillRegistry

```java
@Configuration
public class CompositeSkillRegistryConfig {

    @Bean
    public FileSystemSkillRegistry userSkillRegistry(
            @Value("${skill-runtime.user-skills-dir}") Path dir) {
        return FileSystemSkillRegistry.builder()
                .rootDirectory(dir)
                .build();
    }

    @Bean
    public CompositeSkillRegistry compositeSkillRegistry(
            FileSystemSkillRegistry userRegistry,
            @Autowired(required = false) ClasspathSkillRegistry classpathRegistry) {
        return new CompositeSkillRegistry(List.of(classpathRegistry, userRegistry));
    }
}
```

- `userSkillsDirectory`：默认 `./user-skills`
- `autoReload(true)`：每次 Agent 执行前重新扫描
- `CompositeSkillRegistry`：系统内置 + 用户上传

### 5.2 热加载

```java
SkillsAgentHook.builder()
        .skillRegistry(compositeRegistry)
        .autoReload(true)
        .build();
```

- 修改 `SKILL.md` 或 `scripts/` 后，下一次 Agent 请求自动生效
- 生产化时建议改为版本目录 + 显式 activate，但 PoC 直接用 autoReload

### 5.3 Tool_call 与 Skill 深度绑定

- 使用 `SkillsAgentHook` 自动注册 `read_skill` 工具
- 使用 `groupedTools` 将工具与 Skill 绑定：

```java
groupedTools(Map.of(
    "pdf-extractor", List.of(pythonTool, shellTool2),
    "data-analyzer", List.of(jdbcTool, parquetTool)
))
```

- 模型先调用 `read_skill("pdf-extractor")`，该 Skill 对应工具才进入本次请求
- 避免一次性暴露全部工具，降低误触和 Token 消耗

### 5.4 Python / Shell 沙箱执行

- `PythonTool`：基于 GraalVM polyglot，禁用文件 I/O、本地访问、进程创建
- `ShellTool2`：执行 Shell 命令，可指定工作目录
- PoC 安全边界：
  - 每个 Skill 在独立工作目录运行
  - Shell 命令白名单
  - 超时限制
  - 输出大小限制
  - 禁止网络访问（PoC 默认）
  - 禁止绝对路径逃逸

## 6. REST API 最小设计

### 6.1 上传 Skill

```http
POST /api/skills/upload
Content-Type: multipart/form-data
file: skill.zip
```

响应：

```json
{
  "skillName": "pdf-extractor",
  "version": "1.0.0",
  "status": "INSTALLED",
  "reloadTriggered": true
}
```

处理流程：

1. 校验 zip 大小/文件数
2. 安全解压，防 Zip Slip
3. 校验 `SKILL.md` frontmatter
4. 解压到 `user-skills/<skillName>`
5. 触发 registry reload（下次请求自动生效，或显式 refresh）

### 6.2 技能列表

```http
GET /api/skills
```

响应：

```json
{
  "skills": [
    {
      "name": "pdf-extractor",
      "description": "Extract text from PDF",
      "version": "1.0.0",
      "tools": ["python", "shell"]
    }
  ]
}
```

### 6.3 执行 Agent

```http
POST /api/agent/chat
Content-Type: application/json

{
  "message": "使用 pdf-extractor 技能处理 /tmp/input/sample.pdf",
  "sessionId": "sess-001"
}
```

响应：

```json
{
  "answer": "...",
  "toolCalls": [
    {
      "skill": "pdf-extractor",
      "tool": "python",
      "status": "ok"
    }
  ],
  "trace": [
    "read_skill(pdf-extractor)",
    "python(extract.py)"
  ]
}
```

## 7. Skill 包格式

```text
pdf-extractor/
├── SKILL.md
├── scripts/
│   ├── extract.py
│   └── run.sh
└── references/
    └── input-schema.json
```

`SKILL.md` 示例：

```markdown
---
name: pdf-extractor
description: Extract text from PDF files
version: 1.0.0
tools:
  - python
  - shell
---

# PDF Extractor

Use `scripts/extract.py` to extract text from PDF.
```

## 8. application.yml 最小配置

```yaml
server:
  port: 18080

spring:
  application:
    name: dkws-skill-runtime-poc

skill-runtime:
  user-skills-dir: ./user-skills
  max-skill-zip-size: 20MB
  max-skill-files: 200
  sandbox:
    work-dir: ./sandbox-work
    shell-timeout-ms: 10000
    python-timeout-ms: 10000
    max-output-bytes: 1048576
    allow-network: false
    allowed-shell-commands:
      - ls
      - cat
      - head
      - tail
      - python3

spring-ai-alibaba:
  # 按官方 1.1.2.0 文档配置 model / agent / tool-calling starter
```

## 9. 依赖（以官方文档为准）

```xml
<dependency>
    <groupId>com.alibaba.cloud.ai</groupId>
    <artifactId>spring-ai-alibaba-starter-agent</artifactId>
</dependency>

<dependency>
    <groupId>com.alibaba.cloud.ai</groupId>
    <artifactId>spring-ai-alibaba-starter-tool-calling-python</artifactId>
</dependency>

<!-- ShellTool2 若独立 starter 则按官方坐标引入 -->
```

## 10. 安全设计（PoC 最小）

| 风险 | 控制 |
|---|---|
| Zip Slip | 解压前校验路径，禁止 `..` 和绝对路径 |
| 超大文件 | zip 大小、文件数、单文件大小限制 |
| 恶意 SKILL.md | frontmatter 白名单字段校验 |
| Shell 注入 | 命令白名单 + 参数透传限制 |
| Python 逃逸 | GraalVM PythonTool 沙箱默认禁用文件/网络/进程 |
| 资源耗尽 | 超时、输出大小、并发限制 |
| 审计缺失 | PoC 记录上传/执行日志，生产再补审计链 |

## 11. PoC 验收标准

- [ ] 向 `user-skills` 放入新 Skill，无需重启即可被 Agent 发现
- [ ] 修改 SKILL.md 后，下次请求读到新内容
- [ ] 模型先 `read_skill`，再调用该 Skill 绑定工具
- [ ] PythonTool 可执行 Skill 内 Python 脚本
- [ ] ShellTool2 可执行白名单 Shell 命令
- [ ] 上传 zip 可安全解压并热加载
- [ ] Zip Slip/超时/输出超限被拦截
- [ ] 记录每次 Skill/Tool 调用 trace

## 12. 风险与限制

- GraalVM PythonTool 对第三方 Python 库支持有限，复杂 Skill 可能需要 OS 级沙箱
- autoReload 适合开发/小规模；生产建议版本目录 + 显式 activate
- ShellTool2 的安全边界需根据部署环境加固
- 本 PoC 仅验证 Skill 运行态，不替代 DKWS Python 知识/数据服务

## 13. 后续决策点

1. PoC 通过后，是否将 Spring AI Alibaba Skill Runtime 作为独立 Java 服务引入？
2. 若引入，DKWS Python 核心与 Java Skill Runtime 的边界如何划分？
3. 是否由 GITS Java 侧直接内嵌，而不是 DKWS 单独部署？
4. 生产化时是否用版本目录替换 autoReload？
