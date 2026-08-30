# Release: develop → main

> 本文件是 **PR #3 正文草案**，供 Owner / Tech Lead 审阅后决定是否注入。
> Feature Pilot 未修改 PR #3 —— `develop → main` 属发布决策范围。
>
> 注入命令（确认内容无误后执行）：
> ```bash
> gh api --method PATCH repos/shaozhongfei001/Leibniz-KERT/pulls/3 \
>   -f title="release: merge develop into main (19 commits, v0.1.0 baseline)" \
>   -F body=@evidence/jr1/PULL_REQUEST_3_RELEASE_DRAFT.md
> ```

---

## 1. 范围

把 `develop` 的 19 个提交合入 `main`。

| 项目 | 数值 |
|------|------|
| 提交数 | **19** |
| 变更文件 | **191** |
| 行数 | **+37723 / −66** |
| 版本号 | `main` 与 `develop` 均为 `0.1.0`（**本 PR 不改版本号**） |

主要内容（`git log --oneline origin/main..origin/develop`）：

```text
5e61ac0 feat: v0.1.0 — DKWS-SPEC-001 完整实现 + QA候选包
c608954 feat(m3-p0): complete Phase 0 prerequisites
...（共 19 个，覆盖 M2 / M3 各阶段成果）
```

复核命令：

```bash
git fetch origin --prune
git log --oneline origin/main..origin/develop
git diff --stat origin/main...origin/develop | tail -3
```

## 2. 风险与注意事项

### 2.1 CI 当前为红（**合并前须知**）

`develop` 最新提交的 CI 结论：

| Job | 结论 |
|-----|------|
| Lint | **failure** |
| Test | **failure** |
| Security Tests | **failure** |
| E2E Tests | **failure** |
| Performance Benchmarks | success |

run: https://github.com/shaozhongfei001/Leibniz-KERT/actions/runs/33328453465

**根因已定位，与代码缺陷无关**：`httpx` 仅声明在 `requirements-lock.txt`，
未列入 `pyproject.toml` 的 `[project.optional-dependencies]`
（当前仅 `api = [fastapi, uvicorn]`、`dev = [pytest]`）。
CI 走 `pip install ".[api,dev]"` 时缺 `httpx`，导致：

```text
ModuleNotFoundError: No module named 'httpx'
RuntimeError: The starlette.testclient module requires the httpx package
```

进而 `tests/e2e`、`tests/integration/*` 收集失败。

**本地对照**：全量 `pytest` 1317 项通过。故这是 **CI 依赖声明缺口**，
不是 `develop` 代码质量问题。

> 建议：**先以独立任务包修复依赖声明、让 CI 转绿，再合并本 PR**。
> 若因发布窗口需先合并，请在此 PR 中显式记录「已知 CI 红、根因为依赖
> 声明缺口」，避免后续误判为 `main` 引入了回归。
> 详见 `evidence/jr1/FAILURES.md` FAIL-JR1-04。

### 2.2 合并规模较大

191 文件 / +37723 行，建议确认：

- 是否所有内容都已通过对应阶段的评审（M2 / M3 各阶段）。
- 是否需要打 tag（当前 `pyproject.toml` 已是 `0.1.0`，但 `main` 上是否已有
  `v0.1.0` tag 需确认，避免版本号与 tag 不一致）。

### 2.3 与 JR-1 相关 PR 的顺序

- PR #1（`feature/dkws-java-runtime-integration` → `develop`）：受控基线文档
- PR #2（`feature/jr1-internal-contract-dual-tests` → `develop`）：JR-1 实现

两者 base 已修正为 `develop`，与本 PR **无文件重叠**。

建议顺序：**#1 → #2 → #3**。这样 `main` 一次性收到包含 JR-1 契约闸门的
完整内容；若先合本 PR，则 JR-1 内容需等下一次 `develop → main` 才进入 `main`。

## 3. 已知覆盖缺口

- **CI 不含 Java**（`java|maven|jdk` 在 `ci.yml` 中匹配 0 行）。
  JR-1 建立的 Java 侧 73 项契约测试与四方哈希闸门**目前只在本地生效**，
  未进入 CI 防线。是否新增 Java job 需 Tech Lead 决策。
- CI `pull_request` 触发分支原仅 `[main]`，导致 feature → develop 的 PR
  不被验证；JR-1 分支中已修为 `[main, develop]`，
  该修复随 PR #2 合入后才生效。

## 4. 非声明

- 本 PR 不代表 DKWS 已生产就绪。
- 本 PR 不代表 GITS UAT 已通过。
- 本 PR 不代表安全审计已完成（Security Tests 当前为 failure）。
- 本 PR 不代表 Java Runtime 已生产可用。
- 本 PR 不代表 C′ 混合架构已成为正式基线。
- 本正文由 Feature Pilot 起草，**发布与合并决策属 Owner / Tech Lead**；
  Feature Pilot 未修改、未合并本 PR。
