# PR 状态核实与必须修正项（2026-08-31）

Owner 已手工创建两个 PR。Feature Pilot 通过 GitHub 公开 API 核实实际状态
（本机无凭据，只读匿名查询）后发现**一处必须修正的问题**。

---

## 1. 已创建的 PR

| PR | 源分支 | 实际 base | 应为 base | 状态 |
|----|--------|-----------|-----------|------|
| [#1](https://github.com/shaozhongfei001/Leibniz-KERT/pull/1) | `feature/dkws-java-runtime-integration` | **`main`** | `develop` | open |
| [#2](https://github.com/shaozhongfei001/Leibniz-KERT/pull/2) | `feature/jr1-internal-contract-dual-tests` | **`main`** | `develop` | open |

核实命令（无需凭据）：

```bash
curl -s "https://api.github.com/repos/shaozhongfei001/Leibniz-KERT/pulls?state=all"
```

## 2. 必须修正：base 应为 `develop`，当前为 `main`

### 2.1 为什么这是问题

仓库默认分支是 `main`，而 GitHub 的「pull/new/<branch>」创建页默认以
**默认分支**为 base，因此两个 PR 都指向了 `main`。

任务包与角色边界明确要求：**PR 到 `develop`，不得直接动 `main`**。

### 2.2 后果已量化（不是形式问题）

`develop` 领先 `main` **19 个提交**，`main` 不领先 `develop`。因此：

| PR | 若按当前 base 合并，实际带入 `main` 的提交数 | 其中属于本 PR 范围 |
|----|------------------------------------------|------------------|
| #2（JR-1） | **28** | **9** |
| #1（基线） | 20 | 1 |

也就是说，合并 #2 会把 **19 个 develop 存量提交一并推入 `main`**，
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
| #1 | 20 commits | **1 commit** |
| #2 | 28 commits | **9 commits** |

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

改完后重新查询，两个 PR 的 base 应均为 `develop`：

```bash
curl -s "https://api.github.com/repos/shaozhongfei001/Leibniz-KERT/pulls?state=open" \
  | grep -E '"ref"|"number"'
```

## 3. 次要项：PR 正文未使用已备文本

当前正文长度：#1 为 29 字符，#2 为 41 字符；标题为 GitHub 自动生成
（`Feature/jr1 internal contract dual tests`）。

已备好的正文与建议标题：

| PR | 正文文件 | 建议标题 |
|----|----------|----------|
| #1 | `evidence/jr1/PULL_REQUEST_BASELINE.md` | `docs(arch): merge Java Runtime integration plan into controlled baseline` |
| #2 | `evidence/jr1/PULL_REQUEST.md` | `test(contract): JR-1 internal contract dual-side tests (Python 117 + Java 73)` |

正文含验收依据、测试复现命令、漂移负向验证结论、Owner 决策落实与非声明，
建议粘贴以便审查者无需翻仓库即可判断。此项不阻断合并，但影响可审计性。

## 4. 合并顺序（不变）

**先 #1（受控基线），后 #2（JR-1 实现）**，符合「受控基线先于实现」。

## 5. Feature Pilot 未做的事

- 未修改 PR base（无凭据，且改 base 属 Owner 决策范围）。
- 未关闭或重建任何 PR。
- 未 merge 任何 PR。
- 未向 `main` 推送任何内容。

## 6. 非声明

- 本文件仅为 PR 状态核实记录，不代表 PR 已通过审查或可以合并。
- 不代表 DKWS 已生产就绪、GITS UAT 已通过、安全审计已完成。
- 不代表 Java Runtime 已生产可用、C′ 混合架构已成为正式基线。
- Feature Pilot 不代替 Owner、Tech Lead 或 Independent QA 签署。
