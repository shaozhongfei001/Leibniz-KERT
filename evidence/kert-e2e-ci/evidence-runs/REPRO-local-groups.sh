#!/usr/bin/env bash
# 复现 EVIDENCE.md 的 6 组实跑证据（KERT 在线/离线两批）。
#
# 用法：
#   # 批 1（需先自行在 KERT_PORT 上启动本仓 KERT，dev + 确定性适配器）
#   bash REPRO-local-groups.sh up
#   # 关闭该 KERT 后
#   bash REPRO-local-groups.sh down
#
# 环境变量：
#   KERT_PORT（默认 8199）  KERT 监听的端口（本地取证用空闲端口，避开常被占用的 8106）
#   DEAD_PORT（默认 8931）  「无服务」场景所指向的空闲端口
#   OUT（默认 /tmp/kert-e2e-c-repro）  日志与账本输出目录
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../../.." && pwd)"
PY="$REPO/.venv/bin/python"
OUT="${OUT:-/tmp/kert-e2e-c-repro}"
KERT_PORT="${KERT_PORT:-8199}"
DEAD_PORT="${DEAD_PORT:-8931}"
export PATH="$REPO/.venv/bin:$PATH"
mkdir -p "$OUT"
cd "$REPO"

run() {  # run <组名> <KERT 基址> [env...]
  local name="$1" base="$2"; shift 2
  echo "=== $name（KERT_BASE_URL=$base） ==="
  env KERT_BASE_URL="$base" KERT_PROFILE=dev E2E_LEDGER_PATH="$OUT/$name-ledger.json" "$@" \
    timeout 900 "$PY" -m pytest tests/e2e/ -p no:cacheprovider > "$OUT/$name.log" 2>&1
  echo "exit=$?"
  grep -E "passed|failed|error" "$OUT/$name.log" | tail -1
}

case "${1:-all}" in
  up)   # 需要 KERT 在线
    run g2_kert_only                    "http://127.0.0.1:$KERT_PORT"
    run g3_kert_only_require_kert       "http://127.0.0.1:$KERT_PORT" E2E_REQUIRE_KERT=1
    run g5_require_gits_without_gits    "http://127.0.0.1:$KERT_PORT" E2E_REQUIRE_GITS=1
    ;;
  down) # 需要 KERT 离线
    run g1_no_service                   "http://127.0.0.1:$DEAD_PORT"
    run g4_kert_down_require_kert       "http://127.0.0.1:$DEAD_PORT" E2E_REQUIRE_KERT=1
    run g6_no_service_require_all       "http://127.0.0.1:$DEAD_PORT" E2E_REQUIRE_SERVICES=1
    ;;
  *)
    echo "用法：REPRO-local-groups.sh {up|down}" >&2
    exit 2
    ;;
esac
