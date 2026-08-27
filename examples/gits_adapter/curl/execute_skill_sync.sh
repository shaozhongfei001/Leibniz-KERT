#!/usr/bin/env bash
# execute_skill_sync.sh — 同步执行 DKWS Skill
#
# 用法：
#   ./execute_skill_sync.sh SKILL_ID CUSTOMER_ID [REQUEST_ID] [BASE_URL]
#
# 示例：
#   ./execute_skill_sync.sh R1 CUST-001
#   ./execute_skill_sync.sh SP-21 CUST-002 req-002 http://192.168.1.100:8106
#
# 环境变量：
#   DKWS_API_KEY — API Key（可选）

set -euo pipefail

SKILL_ID="${1:?Usage: $0 SKILL_ID CUSTOMER_ID [REQUEST_ID] [BASE_URL]}"
CUSTOMER_ID="${2:?}"
REQUEST_ID="${3:-req-$(date +%Y%m%d%H%M%S)}"
BASE_URL="${4:-http://127.0.0.1:8106}"
API_KEY="${DKWS_API_KEY:-}"

HEADERS=(-H "Content-Type: application/json" -H "Accept: application/json")
if [[ -n "$API_KEY" ]]; then
  HEADERS+=(-H "X-API-Key: $API_KEY")
fi

# 根据技能类型构建请求体
if [[ "$SKILL_ID" == "SP-20" || "$SKILL_ID" == "SP-21" ]]; then
  # 组合技能：使用 ContextPackage
  BODY=$(cat <<EOF
{
  "skillId": "${SKILL_ID}",
  "requestId": "${REQUEST_ID}",
  "request": {
    "context": {
      "schemaVersion": "1.0.0",
      "customerId": "${CUSTOMER_ID}"
    }
  }
}
EOF
)
else
  # 单客户技能：使用 customerId
  BODY=$(cat <<EOF
{
  "skillId": "${SKILL_ID}",
  "requestId": "${REQUEST_ID}",
  "request": {
    "customerId": "${CUSTOMER_ID}"
  }
}
EOF
)
fi

echo ">>> POST ${BASE_URL}/api/skill/execute (sync)"
echo "    skillId=${SKILL_ID}, customerId=${CUSTOMER_ID}, requestId=${REQUEST_ID}"
curl -sS -w "\nHTTP_STATUS: %{http_code}\n" -X POST "${BASE_URL}/api/skill/execute" "${HEADERS[@]}" -d "$BODY" \
  | python3 -m json.tool 2>/dev/null || echo "(raw output above)"
