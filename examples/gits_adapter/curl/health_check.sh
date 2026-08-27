#!/usr/bin/env bash
# health_check.sh — DKWS 健康检查
#
# 用法：
#   ./health_check.sh [BASE_URL]
#
# 示例：
#   ./health_check.sh
#   ./health_check.sh http://192.168.1.100:8106
#
# 环境变量：
#   DKWS_API_KEY — API Key（可选）
#
# 检查项：
#   1. /v1/health — 服务整体健康
#   2. /api/skill/health — Skill 子系统健康（GITS 适配器使用）
#   3. /livez — 存活探针
#   4. /readyz — 就绪探针

set -euo pipefail

BASE_URL="${1:-http://127.0.0.1:8106}"
API_KEY="${DKWS_API_KEY:-}"

HEADERS=(-H "Accept: application/json")
if [[ -n "$API_KEY" ]]; then
  HEADERS+=(-H "X-API-Key: $API_KEY")
fi

check_endpoint() {
  local name="$1"
  local path="$2"
  local expected_status="${3:-200}"

  RESPONSE=$(curl -sS -o /dev/null -w "%{http_code}" "${BASE_URL}${path}" "${HEADERS[@]}" 2>/dev/null) || RESPONSE="000"

  if [[ "$RESPONSE" == "$expected_status" ]]; then
    echo "  [OK] ${name} (${path}) -> ${RESPONSE}"
  else
    echo "  [FAIL] ${name} (${path}) -> ${RESPONSE} (expected ${expected_status})"
  fi
}

echo "=== DKWS Health Check (${BASE_URL}) ==="
echo ""

check_endpoint "Service Health" "/v1/health"
check_endpoint "Skill Health" "/api/skill/health"
check_endpoint "Liveness Probe" "/livez"
check_endpoint "Readiness Probe" "/readyz"

echo ""
echo "--- Skill Health Detail ---"
curl -sS "${BASE_URL}/api/skill/health" "${HEADERS[@]}" | python3 -m json.tool 2>/dev/null || echo "(unable to parse)"
