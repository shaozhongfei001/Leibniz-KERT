# START HERE — CodeBuddy / Cursor 首次接手入口

> 如果你是 CodeBuddy 或 Cursor，请严格按以下顺序阅读和执行。

## 第一步：拉取最新代码

```bash
cd ~/dev/Leibniz-KERT
git pull origin main
```

## 第二步：必须阅读

1. `AGENTS.md`
2. `docs/development/RULES.md`
3. `docs/development/AGENT_ROLES.md`
4. `docs/development/WORKFLOWS.md`
5. `docs/development/PYTHON_STANDARDS.md`
6. `docs/development/JAVA_STANDARDS.md`
7. `docs/governance/DKWS_TECH_LEAD_DELIVERY_MASTER_PLAN_V1.0.md`
8. `docs/development/DKWS_WORK_BREAKDOWN_STRUCTURE_V1.0.md`

## 第三步：当前第一个任务

当前 Tech Lead 规划中，**CodeBuddy 第一个可执行任务**是：

```text
M2-P1：Python Core 生产加固基础任务包
```

具体任务见：

```text
docs/development/DKWS_WORK_BREAKDOWN_STRUCTURE_V1.0.md
→ M2 Python Core 生产加固
→ M2.1 认证与安全边界
→ M2.2 限流与大小限制
→ M2.3 SQLite Runtime Store
```

## 第四步：开发纪律

- 从 `develop` 分支拉取功能分支
- 每个任务完成后运行相关测试
- 保存原始证据到 `evidence/`
- 提交 PR 到 `develop`
- 不直接 push `main`
- 不修改 GITS 仓库
- 不自行宣称生产就绪或 GITS UAT 通过

## 第五步：遇到不确定事项

- 查看 `docs/governance/DKWS_C_MIXED_ARCH_REMEDIATION_MATRIX.md`
- 查看 `docs/governance/DKWS_DOCUMENT_CONFLICT_REGISTER.md`
- 无法决策时记录为 `PENDING_OWNER_DECISION`
