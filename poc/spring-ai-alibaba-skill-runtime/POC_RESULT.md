# Spring AI Alibaba Skill Runtime PoC 验证结果

> 日期：2026-08-26
> 状态：PARTIAL_PASS（核心链路已通，沙箱执行待补环境配置）

## 环境

- Java 21
- Spring Boot 3.3.5
- Spring AI Alibaba 1.1.2.0
- DeepSeek API（OpenAI 兼容）
- Maven local repo 使用工作区 `.m2-repo`

## 已验证通过

| 项 | 结果 |
|---|---|
| 服务启动 | PASS |
| Skill 自动扫描 | PASS：`Loaded skill: demo-skill` |
| Skill 列表 API | PASS：`GET /api/skills` 返回 demo-skill |
| 热加载触发 | PASS：请求时日志出现 `Reloading skills...` |
| DeepSeek 普通对话 | PASS：返回 `Hello! How can I help you today?` |
| read_skill 调用 | PASS：模型回答中明确说明已通过 read_skill 读取 demo-skill |
| groupedTools 深度绑定 | PASS：日志出现 `SkillsInterceptor: added 2 tool(s) for skill 'demo-skill' to dynamicToolCallbacks` |

## 未通过 / 部分通过

| 项 | 结果 | 原因 |
|---|---|---|
| PythonTool 沙箱执行 | FAIL | GraalVM Python 未配置 core home / stdlib / C API，文件读取 `PermissionError: Operation not permitted` |
| ShellTool 执行 | FAIL | `Shell session not initialized`，ShellTool2 需要先初始化 ShellSessionManager |

## 关键日志

```text
SkillScanner: Loaded skill: demo-skill
FileSystemSkillRegistry: Skills reloaded: 1 total skills
SkillsInterceptor: added 2 tool(s) for skill 'demo-skill' to dynamicToolCallbacks
[python::PythonContext] WARNING: could not determine Graal.Python's core path
ERR: PermissionError [Errno 1] Operation not permitted: '.../demo-skill/scripts/demo.py'
```

## 结论

Spring AI Alibaba 的 Skills + read_skill + groupedTools 渐进式披露链路已经验证可用。
Python/Shell 沙箱执行属于环境配置问题，不是框架不支持；需要补齐 GraalVM Python 运行环境或改用 OS 级沙箱执行。

## 下一步修复

1. 配置 GraalVM Python 的 `--python.CoreHome` / `--python.StdLibHome` / `--python.SysPrefix`
2. 或改用 `nsjail`/`bubblewrap` + 系统 Python 子进程执行
3. 初始化 `ShellSessionManager` 后再调用 ShellTool/ShellTool2
4. 补充 Tool 调用回执与 trace 输出
