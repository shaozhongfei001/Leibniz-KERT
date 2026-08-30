# PR 状态核实与修正记录

- 首次核实：2026-08-31
- 复查更新：2026-08-31（发现新增 PR #3，并修正本文件早前的提交数错误）
- **修正完成：2026-08-31（Owner 提供凭据后，#1/#2 的 base 已改为 `develop`，标题与正文已注入）**

---

## 0. 当前结论（已修正）

`bash scripts/check_pr_base.sh` → **EXIT=0，全部 feature PR base 正确**。

| PR | 源分支 → base | 标题 | 正文 | 提交数 | 判定 |
|----|--------------|------|------|--------|------|
| [#1](https://github.com/shaozhongfei001/Leibniz-KERT/pull/1) | `feature/dkws-java-runtime-integration` → **`develop`** | 已设为 `docs(arch): merge Java Runtime integration plan into controlled baseline` | 2146 字符 | **1** | 就绪待审 |
| [#2](https://github.com/shaozhongfei001/Leibniz-KERT/pull/2) | `feature/jr1-internal-contract-dual-tests` → **`develop`** | 已设为 `test(contract): JR-1 internal contract dual-side tests (Python 117 + Java 73)` | 8083 字符 | **12** | 就绪待审 |
| [#3](https://github.com/shaozhongfei001/Leibniz-KERT/pull/3) | `develop` → `main` | `Develop change` | **0 字符** | 19 | 正常发布 PR，**建议补正文** |

修正手段：`gh api --method PATCH repos/.../pulls/N -f base=develop`。

**为何不用 `gh pr edit`**：本机 `gh` 为 2.4.0，其 `pr` 子命令走 GraphQL 并查询
已被 GitHub 废弃的 Projects classic 字段，报错
`GraphQL: Projects (classic) is being deprecated ... (repository.pullRequest.projectCards)`
而 base 并未改动。REST (`gh api`) 路径不受影响。

---

## 1. 修正前的问题（历史记录，已解决）

| PR | 源分支 → base | 性质 | 判定 |
|----|--------------|------|------|
| #1 | `feature/dkws-java-runtime-integration` → **`main`** | 基线文档 | 需修正 base |
| #2 | `feature/jr1-internal-contract-dual-tests` → **`main`** | JR-1 实现 | 需修正 base |
| #3 | `develop` → `main` | 集成/发布 | 正常，无需修正 |

PR #3（`Develop change`，创建于 2026-08-30T18:34Z）是 `develop → main`
的发布型 PR，属正常集成流程，**不是** base 配错。已核实其范围为
`develop` 领先 `main` 的那 19 个存量提交，**不含任何 JR-1 内容**。

> 校验脚本 `scripts/check_pr_base.sh` 初版曾把 #3 误判为 FAIL，
> 已修正为跳过 `head == develop` 的集成型 PR。

核实命令（无需凭据）：

```bash
bash scripts/check_pr_base.sh                     # 直接给 PASS/FAIL
curl -s "https://api.github.com/repos/shaozhongfei001/Leibniz-KERT/pulls?state=all"
```

## 2. 原问题分析：base 为 `main` 的后果

### 2.1 为什么这是问题

仓库默认分支是 `main`，而 GitHub 的「pull/new/<branch>」创建页默认以
**默认分支**为 base，因此两个 PR 都指向了 `main`。

任务包与角色边界明确要求：**PR 到 `develop`，不得直接动 `main`**。

### 2.2 后果已量化（不是形式问题）

`develop` 领先 `main` **19 个提交**，`main` 不领先 `develop`。因此：

| PR | 若按当前 base 合并，实际带入 `main` 的提交数 | 其中属于本 PR 范围 | 夹带的存量提交 |
|----|------------------------------------------|------------------|--------------|
| #2（JR-1） | **30** | **11** | 19 |
| #1（基线） | **10** | **1** | 9 |

> #1 只夹带 9 个（而非 19 个），因为该分支从较早的 `develop` 提交点分出，
> 未包含 `develop` 后续的 10 个提交。这一差异不改变结论：
> 两者都会把未经本 PR 评审的存量提交推入 `main`。

以 #2 为例，合并会把 **19 个 `develop` 存量提交一并推入 `main`**，
这些提交未经本 PR 评审，包含 `v0.1.0` 发布提交、M2/M3 各阶段成果等：

```text
5e61ac0 feat: v0.1.0 — DKWS-SPEC-001 完整实现 + QA候选包
c608954 feat(m3-p0): complete Phase 0 prerequisites ...
...（共 19 个）
```

等同于在一次「内部契约测试」PR 中夹带一次未声明的发布，
审查范围与实际影响严重不符。

### 2.3 修正方式（二选一，均由 Owner 执行）

**方式 A：网页改 base（推荐，保留现有 PR 编号与讨论）**

对 #1 和 #2 各做一次，每个约 20 秒：

1. 打开 PR 页面
   - #1 https://github.com/shaozhongfei001/Leibniz-KERT/pull/1
   - #2 https://github.com/shaozhongfei001/Leibniz-KERT/pull/2
2. 标题下方有一行分支指示：`shaozhongfei001 wants to merge N commits into
   **main** from <源分支>`
3. 点击其中的 **`main`**（它是下拉按钮，不是纯文本）
4. 在下拉中选择 **`develop`**
5. GitHub 弹出确认框 **Change base branch?** → 点击 **Change base**

改完后页面提交数应收敛：

| PR | 改前（→ main） | 改后（→ develop） |
|----|---------------|------------------|
| #1 | 10 commits | **1 commit** |
| #2 | 30 commits | **11 commits** |

> 若下拉中看不到 `develop`：确认你是仓库 write 权限账号；
> `develop` 确实存在于远程（`git ls-remote --heads origin develop`）。

**方式 B：命令行（需 token，可一次处理两个）**

```bash
export GH_TOKEN=<token>          # 需 repo 权限
bash scripts/create_jr1_prs.sh   # 检测到 base 不符会自动 gh pr edit --base develop
```

或直接用 API（不依赖 gh 版本）：

```bash
for n in 1 2; do
  curl -s -X PATCH \
    -H "Authorization: Bearer $GH_TOKEN" \
    -H "Accept: application/vnd.github+json" \
    "https://api.github.com/repos/shaozhongfei001/Leibniz-KERT/pulls/$n" \
    -d '{"base":"develop"}' >/dev/null && echo "PR #$n base -> develop"
done
```

**方式 C：关闭重建**

关闭 #1、#2，再用 `bash scripts/create_jr1_prs.sh` 重建
（脚本硬编码 `--base develop`，不受仓库默认分支影响）。
缺点是丢失现有 PR 编号与讨论，故列为最后选择。

### 2.4 校验方法

改完后重新校验（一条命令给结论）：

```bash
bash scripts/check_pr_base.sh    # 期望：#1/#2 为 OK，#3 为 SKIP，退出码 0
```

## 3. PR #3 带来的顺序风险（需 Owner 决策）

PR #3（`develop → main`）本身正常，但它与 #1/#2 存在**顺序耦合**：

- 若**先合 #3**：`main` 前进到 `develop`（`5e61ac0`）。此后即使 #1/#2 的
  base 仍是 `main`，夹带问题也会自动消失（#1 剩 1 个提交、#2 剩 11 个）。
- 若**先合 #1/#2 且 base 未改**：19 个存量提交会以「内部契约测试 PR」的
  名义进入 `main`，审查范围与实际影响不符。

**建议顺序**（任一均可，关键是别在 base 未改时先合 #1/#2）：

| 方案 | 顺序 | 说明 |
|------|------|------|
| A（推荐） | 改 #1/#2 base → 合 #1 → 合 #2 → 合 #3 | 各 PR 范围最清晰，`main` 一次性收到已评审内容 |
| B | 合 #3 → 改 #1/#2 base → 合 #1 → 合 #2 | 也可行，但 `main` 会先收到一批未随 PR 正文说明的发布内容 |

无论哪种，**#1 必须早于 #2**（受控基线先于实现）。

## 4. PR 正文与标题（#1/#2 已注入，#3 待补）

修正前，#1/#2 的正文为 GitHub 自动生成的占位（29 / 41 字符），
标题亦为自动生成（如 `Feature/jr1 internal contract dual tests`），
审查者无法据此判断验收依据。

已注入（`gh api --method PATCH ... -F body=@<file>`）：

| PR | 正文来源 | 注入后长度 | 标题 |
|----|----------|-----------|------|
| #1 | `evidence/jr1/PULL_REQUEST_BASELINE.md` | 2146 字符 | `docs(arch): merge Java Runtime integration plan into controlled baseline` |
| #2 | `evidence/jr1/PULL_REQUEST.md` | 8083 字符 | `test(contract): JR-1 internal contract dual-side tests (Python 117 + Java 73)` |

正文含验收依据、测试复现命令、漂移负向验证结论、Owner 决策落实与非声明，
审查者无需翻仓库即可判断。

**待补**：PR #3 正文仍为空（0 字符），却将把 19 个提交
（含 `v0.1.0` 发布）推入 `main`。建议由 Owner / Tech Lead 补充范围与风险说明。
Feature Pilot 未改动 #3，因其属发布决策范围。

## 5. 本文件的自我修正记录

**（a）提交数曾报错。** 首版给出 `#2 → 28/9`、`#1 → 20/1`，实际为
`#2 → 30/11`、`#1 → 10/1`。原因：JR-1 分支在首次统计后又新增了 3 个
PR 文档/脚本提交，复述时未重新计算。已按远程状态重算更正。核对命令：

```bash
git fetch origin --prune
git rev-list --count origin/main..origin/feature/jr1-internal-contract-dual-tests   # 30
git rev-list --count origin/develop..origin/feature/jr1-internal-contract-dual-tests # 11（改 base 后又 +1 = 12）
git rev-list --count origin/main..origin/feature/dkws-java-runtime-integration        # 10
git rev-list --count origin/develop..origin/feature/dkws-java-runtime-integration     # 1
```

**（b）`create_jr1_prs.sh` 曾谎报成功。** 该脚本用 `gh pr edit` 改 base，
遇 GraphQL Projects classic 废弃报错后 **base 实际未变，却仍打印
「两个 PR 处理完成」**。这是最危险的失败模式：看似成功、实则未改。

已修复为：
- 改用 `gh api`（REST）而非 `gh pr view/edit`（GraphQL），绕开旧版 gh 缺陷
- 改完后**回读 `base.ref` 验证**，不以命令退出码判定成功
- 失败时置 `FAILED=1`，脚本以退出码 1 结束并提示改用网页操作
- 幂等复跑已实测：base 已正确时输出「无需改动」，EXIT=0

## 6. 合并顺序

见第 3 节。核心约束：**#1 早于 #2**。
由于 base 已修正，「base 未改前不要先合 #1/#2」的风险已消除。

## 7. Feature Pilot 做了 / 未做的事

已做（Owner 提供凭据后，属修正既有 PR 元数据，不涉及代码与合并）：

- 将 #1 / #2 的 base 由 `main` 改为 `develop`
- 为 #1 / #2 注入已备正文与规范标题
- 修复 `create_jr1_prs.sh` 的谎报缺陷

未做：

- 未修改 PR #3（`develop → main`）的任何内容
- 未 merge 任何 PR
- 未向 `main` 推送任何内容
- 未 approve 或代替他人签署

## 8. 非声明

- 本文件仅为 PR 状态核实记录，不代表 PR 已通过审查或可以合并。
- 不代表 DKWS 已生产就绪、GITS UAT 已通过、安全审计已完成。
- 不代表 Java Runtime 已生产可用、C′ 混合架构已成为正式基线。
- Feature Pilot 不代替 Owner、Tech Lead 或 Independent QA 签署。
