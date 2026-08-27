#!/usr/bin/env bash
# list_skills.sh — 列出 DKWS 可用 Skill
#
# 用法：
#   ./list_skills.sh [BASE_URL]
#
# 示例：
#   ./list_skills.sh
#   ./list_skills.sh http://192.168.1.100:8106
#
# 环境变量：
#   DKWS_API_KEY — API Key（可选）

set -euo pipefail

BASE_URL="${1:-http://127.0.0.1:8106}"
API_KEY="${DKWS_API_KEY:-}"

HEADERS=(-H "Accept: application/json")
if [[ -n "$API_KEY" ]]; then
  HEADERS+=(-H "X-API-Key: $API_KEY")
fi

echo ">>> GET ${BASE_URL}/v1/skills"
curl -sS "${BASE_URL}/v1/skills" "${HEADERS[@]}" | python3 -m json.tool 2>/dev/null || echo "(raw output above)"
