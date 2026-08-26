# Spring AI Alibaba Runtime POC-2 Plan

> 日期：2026-08-26
> 状态：IN_PROGRESS

## 目标

验证 C′ 混合架构中 Java Runtime 的关键准入项。

## 范围

1. 至少两个 Skill 动态注册
2. Skill→Tool 动态绑定，不硬编码
3. Skill 版本化安装、激活、回滚
4. 内部 API 认证
5. 结构化 Tool/Model Receipt 容器
6. OS Sandbox Runner（bwrap）基础执行

## 非范围

- 不接入生产 Python Core
- 不启用生产 PythonTool/ShellTool
- 不修改 GITS
