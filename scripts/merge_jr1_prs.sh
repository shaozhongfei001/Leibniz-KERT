#!/usr/bin/env bash
# 按受控顺序合并 JR-1 相关 PR：先 #1（受控基线），后 #2（JR-1 实现）。
#
# 设计原则（重要）：
#   1. 默认 --dry-run。不传 --confirm 绝不执行任何合并。
#   2. 每一步都**回读实际状态**验证，不以命令退出码当作成功。
#      （教训：gh 2.4.0 的 pr 子命令走 GraphQL，会因 Projects classic 废弃
#       而报错，若只看退出码会误判成功。本脚本统一用 gh api / REST。）
#   3. 合并 #1 后重新检查 #2 的可合并性，因为 #1 会推进 develop。
#   4. 任何一步失败立即停止，不继续合下一个。
#   5. 只合并 #1 / #2。**不动 PR #3（develop -> main）**，那属发布决策。
#
# 用法：
#   bash scripts/merge_jr1_prs.sh              # 预演，只检查不合并（默认）
#   bash scripts/merge_jr1_prs.sh --confirm    # 真正执行合并
#
# 前置：gh 已登录（gh auth status），且对仓库有 write 权限。
# 退出码：0 成功；非 0 表示存在未完成项。

set -uo pipefail

REPO="shaozhongfei001/Leibniz-KERT"
EXPECTED_BASE="develop"
MERGE_METHOD="merge"   # 保留提交历史与 Loop 可追溯性，不用 squash

# 合并顺序固定：受控基线先于实现
PR_BASELINE=1
PR_JR1=2

DRY_RUN=1
[[ "${1:-}" == "--confirm" ]] && DRY_RUN=0

cd "$(dirname "$0")/.."

hr() { printf '%s\n' "----------------------------------------------------------------------"; }
fail() { echo "ERROR: $*" >&2; exit 1; }

command -v gh >/dev/null || fail "未找到 gh CLI"
gh auth status >/dev/null 2>&1 || fail "gh 未登录。请先运行 gh auth login --web"

# 读取 PR 的单个字段（REST，避开旧版 gh 的 GraphQL 缺陷）
pr_field() {
  gh api "repos/$REPO/pulls/$1" --jq "$2" 2>/dev/null || echo ""
}

# 合并前置校验：base 正确、非 draft、mergeable_state 为 clean
preflight() {
  local n="$1" label="$2"
  local base commits state draft merged title

  echo "== 预检 PR #$n（$label）=="

  merged=$(pr_field "$n" .merged)
  if [[ "$merged" == "true" ]]; then
    echo "  已合并，跳过"
    return 2
  fi

  base=$(pr_field "$n" .base.ref)
  commits=$(pr_field "$n" .commits)
  state=$(pr_field "$n" .mergeable_state)
  draft=$(pr_field "$n" .draft)
  title=$(pr_field "$n" .title)

  echo "  标题: ${title:0:70}"
  echo "  base=$base  提交数=$commits  draft=$draft  mergeable_state=$state"

  [[ "$base" == "$EXPECTED_BASE" ]] \
    || { echo "  !! base 应为 $EXPECTED_BASE，实为 $base" >&2
         echo "  !! 修正: bash scripts/create_jr1_prs.sh" >&2; return 1; }

  [[ "$draft" != "true" ]] || { echo "  !! 仍是 draft PR" >&2; return 1; }

  # dirty = 有冲突；blocked = 被保护规则/审查拦住
  case "$state" in
    clean|unstable|has_hooks)
      [[ "$state" == "clean" ]] || echo "  注意: state=$state（非 clean，通常为检查未完成）"
      ;;
    dirty)
      echo "  !! 存在合并冲突，需先解决" >&2; return 1 ;;
    blocked)
      echo "  !! 被分支保护或必需审查拦住，需先满足条件" >&2; return 1 ;;
    *)
      echo "  !! 未知 mergeable_state=$state，保守中止" >&2; return 1 ;;
  esac

  echo "  预检通过"
  return 0
}

# 执行合并并回读验证
do_merge() {
  local n="$1" label="$2"

  if [[ $DRY_RUN -eq 1 ]]; then
    echo "  [dry-run] gh api --method PUT repos/$REPO/pulls/$n/merge -f merge_method=$MERGE_METHOD"
    return 0
  fi

  echo "  正在合并 PR #$n ..."
  gh api --method PUT "repos/$REPO/pulls/$n/merge" \
    -f merge_method="$MERGE_METHOD" >/dev/null 2>&1 || true

  # 不信退出码，回读 merged 状态
  local merged sha
  merged=$(pr_field "$n" .merged)
  if [[ "$merged" == "true" ]]; then
    sha=$(pr_field "$n" .merge_commit_sha)
    echo "  已合并 PR #$n（merge_commit=${sha:0:7}）"
    return 0
  fi

  echo "  ** 合并失败：PR #$n 仍未合并" >&2
  echo "  ** 请打开 https://github.com/$REPO/pull/$n 手动查看原因" >&2
  return 1
}

hr
if [[ $DRY_RUN -eq 1 ]]; then
  echo "模式：DRY-RUN（只检查，不合并）"
  echo "确认无误后执行： bash scripts/merge_jr1_prs.sh --confirm"
else
  echo "模式：CONFIRM（将真正执行合并）"
fi
echo "顺序：#$PR_BASELINE 受控基线  ->  #$PR_JR1 JR-1 实现"
echo "方式：$MERGE_METHOD（保留提交历史，便于 Loop 追溯）"
echo "不触碰：PR #3（develop -> main），属发布决策范围"
hr

# ---- 第 1 步：受控基线 ----
preflight "$PR_BASELINE" "受控基线：Java Runtime 集成计划文档"
rc=$?
if [[ $rc -eq 1 ]]; then fail "PR #$PR_BASELINE 预检失败，未做任何合并"; fi
if [[ $rc -eq 0 ]]; then
  do_merge "$PR_BASELINE" "受控基线" || fail "PR #$PR_BASELINE 合并失败，已停止（未合并 #$PR_JR1）"
fi

hr

# ---- 第 2 步：JR-1 实现 ----
# #1 合并后 develop 已前进，GitHub 需要片刻重算 #2 的可合并性
if [[ $DRY_RUN -eq 0 && $rc -eq 0 ]]; then
  echo "等待 GitHub 重算 PR #$PR_JR1 的可合并性 ..."
  for _ in 1 2 3 4 5 6; do
    sleep 5
    st=$(pr_field "$PR_JR1" .mergeable_state)
    [[ "$st" == "clean" || "$st" == "unstable" ]] && break
    echo "  当前 state=$st，继续等待 ..."
  done
fi

preflight "$PR_JR1" "JR-1：内部契约双端测试"
rc2=$?
if [[ $rc2 -eq 1 ]]; then fail "PR #$PR_JR1 预检失败（#$PR_BASELINE 可能已合并，请检查）"; fi
if [[ $rc2 -eq 0 ]]; then
  do_merge "$PR_JR1" "JR-1 实现" || fail "PR #$PR_JR1 合并失败"
fi

hr
if [[ $DRY_RUN -eq 1 ]]; then
  echo "DRY-RUN 结束，未合并任何 PR。"
  echo "如检查全部通过，执行： bash scripts/merge_jr1_prs.sh --confirm"
else
  echo "合并完成。建议后续："
  echo "  1. git fetch origin --prune && git log --oneline -5 origin/develop"
  echo "  2. 本地复跑验证： .venv/bin/python scripts/verify_jr1_internal_contract.py"
  echo "  3. PR #3（develop -> main）由 Owner 按发布流程决策"
fi
hr
