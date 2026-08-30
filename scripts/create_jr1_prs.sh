#!/usr/bin/env bash
# 创建 JR-1 相关的两个 PR（基线 PR + JR-1 PR），并在必要时修正 base。
#
# 为什么需要本脚本：GitHub 创建 PR 必须走 HTTPS API，SSH 只能推分支。
# 本机 origin 为 SSH-only 且无 GitHub token，故 Feature Pilot 无法创建 PR。
# 一旦提供凭据，执行本脚本即可按正确顺序、用已评审的正文创建两个 PR。
#
# 本脚本硬编码 --base develop。这一点很关键：仓库默认分支是 main，
# GitHub 的「pull/new/<branch>」网页创建入口会默认以 main 为 base，
# 从而把 develop 的存量提交一并带入 main。脚本对已存在的 PR 也会检查
# base 并在不符时改正。
#
# 用法：
#   export GH_TOKEN=<token>            # 需 repo 权限；不要回显该值
#   bash scripts/create_jr1_prs.sh          # 创建（或修正 base）
#   bash scripts/create_jr1_prs.sh --dry-run # 只打印将执行的动作
#
# 顺序：先基线 PR（受控基线先于实现），再 JR-1 PR。

set -euo pipefail

REPO="shaozhongfei001/Leibniz-KERT"
BASE="develop"

BASELINE_BRANCH="feature/dkws-java-runtime-integration"
BASELINE_TITLE="docs(arch): merge Java Runtime integration plan into controlled baseline"
BASELINE_BODY="evidence/jr1/PULL_REQUEST_BASELINE.md"

JR1_BRANCH="feature/jr1-internal-contract-dual-tests"
JR1_TITLE="test(contract): JR-1 internal contract dual-side tests (Python 117 + Java 73)"
JR1_BODY="evidence/jr1/PULL_REQUEST.md"

DRY_RUN=0
[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=1

cd "$(dirname "$0")/.."

fail() { echo "ERROR: $*" >&2; exit 1; }

# --- 前置检查 -------------------------------------------------------------
command -v gh >/dev/null || fail "未找到 gh CLI"

if [[ $DRY_RUN -eq 0 ]]; then
  if [[ -z "${GH_TOKEN:-}" && -z "${GITHUB_TOKEN:-}" ]]; then
    gh auth status >/dev/null 2>&1 \
      || fail "无 GitHub 凭据。请 export GH_TOKEN=<token> 或运行 gh auth login"
  fi
fi

for f in "$BASELINE_BODY" "$JR1_BODY"; do
  [[ -f "$f" ]] || fail "缺少 PR 正文文件: $f"
done

echo "== 拉取远程状态 =="
git fetch origin --prune --quiet

for br in "$BASE" "$BASELINE_BRANCH" "$JR1_BRANCH"; do
  git rev-parse --verify --quiet "origin/$br" >/dev/null \
    || fail "远程分支不存在: origin/$br（请先推送）"
  printf "  %-46s %s\n" "$br" "$(git rev-parse --short "origin/$br")"
done

# 分支若与 base 无差异则无法开 PR，提前拦截给出明确原因
for br in "$BASELINE_BRANCH" "$JR1_BRANCH"; do
  n=$(git rev-list --count "origin/$BASE..origin/$br")
  [[ "$n" -gt 0 ]] || fail "origin/$br 相对 origin/$BASE 无新提交，无法创建 PR"
  printf "  %-46s %s 个新提交\n" "$br" "$n"
done

# --- 创建 PR --------------------------------------------------------------
create_pr() {
  local branch="$1" title="$2" body_file="$3" label="$4"

  echo
  echo "== [$label] $branch -> $BASE =="

  # 先查是否已有开启中的 PR（不限 base）：Owner 可能已手工创建，
  # 且 GitHub 创建页默认以仓库默认分支为 base，容易误指向 main。
  local existing existing_base
  existing=$(gh pr list --repo "$REPO" --head "$branch" --state open \
               --json number --jq '.[0].number' 2>/dev/null || true)

  if [[ -n "$existing" && "$existing" != "null" ]]; then
    existing_base=$(gh pr view "$existing" --repo "$REPO" \
                      --json baseRefName --jq .baseRefName 2>/dev/null || true)
    echo "  已存在开启中的 PR #$existing（base=$existing_base）"

    if [[ "$existing_base" != "$BASE" ]]; then
      echo "  !! base 不是 $BASE，需修正（否则会把 $BASE 的存量提交一并带入 $existing_base）"
      if [[ $DRY_RUN -eq 1 ]]; then
        echo "  [dry-run] gh pr edit $existing --repo $REPO --base $BASE"
      else
        gh pr edit "$existing" --repo "$REPO" --base "$BASE" \
          && echo "  已将 PR #$existing 的 base 改为 $BASE"
      fi
    else
      echo "  base 正确，跳过创建（幂等）"
    fi

    gh pr view "$existing" --repo "$REPO" --json url --jq .url 2>/dev/null || true
    return 0
  fi

  if [[ $DRY_RUN -eq 1 ]]; then
    echo "  [dry-run] gh pr create --repo $REPO --base $BASE --head $branch \\"
    echo "              --title \"$title\" --body-file $body_file"
    return 0
  fi

  gh pr create --repo "$REPO" --base "$BASE" --head "$branch" \
    --title "$title" --body-file "$body_file"
}

# 顺序固定：受控基线先于实现
create_pr "$BASELINE_BRANCH" "$BASELINE_TITLE" "$BASELINE_BODY" "1/2 基线 PR"
create_pr "$JR1_BRANCH"      "$JR1_TITLE"      "$JR1_BODY"      "2/2 JR-1 PR"

echo
if [[ $DRY_RUN -eq 1 ]]; then
  echo "dry-run 结束，未创建任何 PR。"
else
  echo "两个 PR 处理完成。请由 Owner / Tech Lead 审查与 merge。"
  echo "注意：合并顺序应为 基线 PR -> JR-1 PR。"
fi
