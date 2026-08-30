#!/usr/bin/env bash
# 校验 JR-1 相关 PR 的 base 是否为 develop（而非 main）。
#
# 背景：仓库默认分支是 main，GitHub 的 pull/new/<branch> 网页入口会以默认
# 分支为 base。若 base 误为 main，合并会把 develop 的存量提交一并推入 main
# （develop 领先 main 19 个提交，含 v0.1.0 发布提交）。
#
# 本脚本只读、匿名，无需任何凭据。
#
# 用法：
#   bash scripts/check_pr_base.sh
#
# 退出码：0 = 两个 PR 的 base 均为 develop；1 = 存在需修正项。

set -uo pipefail

REPO="shaozhongfei001/Leibniz-KERT"
EXPECTED_BASE="develop"
API="https://api.github.com/repos/${REPO}/pulls?state=open&per_page=50"

cd "$(dirname "$0")/.."

command -v curl >/dev/null || { echo "ERROR: 未找到 curl" >&2; exit 1; }

PY=".venv/bin/python"
[[ -x "$PY" ]] || PY="python3"

echo "== 查询 ${REPO} 的开启中 PR（匿名只读）=="

PR_PAYLOAD=$(curl -s --max-time 30 "$API") || {
  echo "ERROR: 查询 GitHub API 失败（网络不可达？）" >&2
  exit 1
}
export PR_PAYLOAD EXPECTED_BASE

# 说明：payload 通过环境变量传入，避免与 heredoc 争用 stdin。
"$PY" <<'PYEOF'
import json
import os
import sys

expected = os.environ["EXPECTED_BASE"]
raw = os.environ["PR_PAYLOAD"]

try:
    data = json.loads(raw)
except json.JSONDecodeError:
    print("ERROR: API 返回非 JSON（可能被限流）", file=sys.stderr)
    raise SystemExit(1)

if isinstance(data, dict):
    print(f"ERROR: API 返回错误: {data.get('message')}", file=sys.stderr)
    raise SystemExit(1)

if not data:
    print("未发现开启中的 PR。")
    raise SystemExit(1)

wrong = []
for pr in sorted(data, key=lambda p: p["number"]):
    base = pr["base"]["ref"]
    ok = base == expected
    print(f"[{'OK  ' if ok else 'FAIL'}] PR #{pr['number']}  {pr['head']['ref']}")
    print(f"         base={base}  (期望 {expected})")
    print(f"         {pr['html_url']}")
    if not ok:
        wrong.append((pr["number"], base))

print("-" * 68)
if wrong:
    print(f"需修正: {len(wrong)} 个 PR 的 base 不是 {expected}")
    for number, base in wrong:
        print(f"  - PR #{number}: {base} -> {expected}")
    print()
    print("修正方式见 evidence/jr1/PR_STATUS.md 第 2.3 节。")
    print("网页最快: 打开 PR -> 点标题下方的 base 分支名 'main' -> 选 'develop'")
    print("         -> 确认 'Change base'")
    raise SystemExit(1)

print(f"全部 PR 的 base 均为 {expected}，可继续审查。")
print("合并顺序: 先基线 PR，后 JR-1 PR。")
PYEOF
