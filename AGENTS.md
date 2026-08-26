# AGENTS.md — Leibniz-KERT / DKWS 开发代理指引

> 本文件是 Codebuddy、Cursor、DeepSeek-Harness 等 AI 代理在本仓库工作时的最高优先级开发规则入口。

## 1. 项目定位

DKWS 是独立知识工程服务端，目标架构为 C′ 混合架构：

- Python Core：唯一公共入口、控制面、知识/数据权威源
- Java Skill Runtime：内部可替换执行器，不对外
- GITS：仅通过 Python Core 公共 HTTP 调用

## 2. 代理角色

- Owner：最终决策人
- Tech Lead / Architecture Lead：架构、评审、复杂设计
- Feature Pilot：日常功能开发
- Independent QA：独立验证
- Security QA：安全验证
- Contract Owner：契约维护

## 3. 强制 Rules

1. 不得修改 GITS 仓库
2. 不得让 GITS 直连 Java Runtime
3. 不得把 Java Runtime 嵌入 GITS
4. 生产禁用 `autoReload` 扫描可写目录
5. 未通过安全 Gate 前，PythonTool/ShellTool 生产默认关闭
6. 不自行宣布 `PRODUCTION_READY=YES` 或 `GITS_UAT_PASS=YES`
7. 不删除历史文档/ADR/评审记录
8. 文档冲突时保留旧文件并登记 superseded
9. 所有修改必须可追溯
10. 没有 Owner 授权不得自动 push/merge

## 4. 开发流程

1. 从 `develop` 拉取 `feature/<id>`
2. 本地开发
3. 运行相关测试
4. 更新文档/契约
5. 提交 PR 到 `develop`
6. 等待评审

## 5. 规范文件

- Agent 角色：`docs/development/AGENT_ROLES.md`
- 流程：`docs/development/WORKFLOWS.md`
- 通用规则：`docs/development/RULES.md`
- Python 规范：`docs/development/PYTHON_STANDARDS.md`
- Java 规范：`docs/development/JAVA_STANDARDS.md`
