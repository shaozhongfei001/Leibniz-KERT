#!/usr/bin/env bash
# 在独立 user+net 命名空间内，逐条复现 .github/workflows/ci.yml 的 e2e job 的 run 步骤。
#
# 为什么需要 netns：CI 的 e2e job 用**真值端口 8106**；而开发机上 8106 常被外部实例
# 占用（TECH_LEAD_DECISION §0.3 警示"非本仓检出不得作为证据"）。`unshare -rn` 提供的
# 网络命名空间里 127.0.0.1 是独立的，可得到干净的 8106，且**不干扰**宿主机上的实例。
#
# 用法：
#   unshare -rn bash -c 'ip link set lo up; bash REPRO-ci-job-locally.sh happy'
#   unshare -rn bash -c 'ip link set lo up; bash REPRO-ci-job-locally.sh kert-down'
#   unshare -rn bash -c 'ip link set lo up; bash REPRO-ci-job-locally.sh port-occupied'
#
# 环境变量：
#   OUT（默认 /tmp/kert-e2e-c-repro）  日志与账本输出目录
#   RUNNER_TEMP（默认 $OUT/runner）    复现 GitHub Actions 的 ${{ runner.temp }}
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../../.." && pwd)"
MODE="${1:-happy}"
export OUT="${OUT:-/tmp/kert-e2e-c-repro}"
export RUNNER_TEMP="${RUNNER_TEMP:-$OUT/runner}"
export PATH="$REPO/.venv/bin:$PATH"   # CI 中由 actions/setup-python + pip install 提供

rm -rf "$RUNNER_TEMP"
mkdir -p "$RUNNER_TEMP"
cd "$REPO"

echo "########## 环境预检（netns 内） ##########"
ip -o addr show lo | head -2
for port in 8106 8082 5173; do
  echo "$port 预检: $(curl -s -o /dev/null -w '%{http_code}' --max-time 2 "http://127.0.0.1:$port" || true)"
done

run_step() {  # run_step <标签> <脚本> [env...]
  local label="$1" script="$2"; shift 2
  echo
  echo "########## STEP: $label ##########"
  env "$@" bash "$script"
  echo "########## $label exit=$? ##########"
}

case "$MODE" in
  happy)
    run_step "Start KERT (dev profile, deterministic adapters)" \
      "$HERE/REPRO-ci-step-Start.sh" KERT_PROFILE=dev
    run_step "Run E2E tests" "$HERE/REPRO-ci-step-Run.sh" \
      KERT_PROFILE=dev E2E_REQUIRE_KERT=1 \
      E2E_LEDGER_PATH="$RUNNER_TEMP/e2e-coverage-ledger.json"
    run_step "Assert E2E coverage ledger" "$HERE/REPRO-ci-step-Assert.sh"
    ;;
  kert-down)
    echo
    echo "########## 说明：本模式不执行 Start KERT，模拟「KERT 起不来」 ##########"
    run_step "Run E2E tests（KERT 未起）" "$HERE/REPRO-ci-step-Run.sh" \
      KERT_PROFILE=dev E2E_REQUIRE_KERT=1 \
      E2E_LEDGER_PATH="$RUNNER_TEMP/e2e-coverage-ledger.json"
    run_step "Assert E2E coverage ledger（CI 中因上一步失败不会执行，此处为独立取证）" \
      "$HERE/REPRO-ci-step-Assert.sh"
    ;;
  port-occupied)
    echo
    echo "########## 说明：本模式先在 netns 内占用 8106，再执行 Start KERT ##########"
    mkdir -p "$OUT/home"
    env -u KERT_LLM_BASE_URL -u KERT_LLM_API_KEY -u KERT_LLM_MODEL \
      KERT_PROFILE=dev HOME="$OUT/home" \
      nohup "$REPO/.venv/bin/python" "$REPO/scripts/serve_skill_service.py" \
        --port 8106 --host 127.0.0.1 --workspace "$RUNNER_TEMP/ws0" \
        > "$RUNNER_TEMP/pre.log" 2>&1 &
    for _ in $(seq 1 20); do
      curl -fsS --max-time 2 http://127.0.0.1:8106/api/skill/health > /dev/null 2>&1 && break
      sleep 1
    done
    echo "预占实例健康检查: $(curl -s -o /dev/null -w '%{http_code}' --max-time 2 http://127.0.0.1:8106/api/skill/health)"
    run_step "Start KERT（8106 已被占用）" "$HERE/REPRO-ci-step-Start.sh" KERT_PROFILE=dev
    ;;
  *)
    echo "未知模式：$MODE（可选 happy / kert-down / port-occupied）" >&2
    exit 2
    ;;
esac
