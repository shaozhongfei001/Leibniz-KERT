#!/usr/bin/env bash
# execute_skill_async.sh — 异步提交 DKWS Skill 执行
#
# 用法：
#   ./execute_skill_async.sh SKILL_ID CUSTOMER_ID [REQUEST_ID] [BASE_URL]
#
# 示例：
#   ./execute_skill_async.sh SP-20 CUST-001
#   ./execute_skill_async.sh SP-20 CUST-002 req-002 http://192.168.1.100:8106
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

BODY=$(cat <<EOF
{
  "skillId": "${SKILL_ID}",
  "requestId": "${REQUEST_ID}",
  "async": true,
  "request": {
    "context": {
      "schemaVersion": "1.0.0",
      "customerId": "${CUSTOMER_ID}"
    }
  }
}
EOF
)

echo ">>> POST ${BASE_URL}/api/skill/execute (async)"
echo "    skillId=${SKILL_ID}, customerId=${CUSTOMER_ID}, requestId=${REQUEST_ID}"
RESPONSE=$(curl -sS -w "\n%{http_code}" -X POST "${BASE_URL}/api/skill/execute" "${HEADERS[@]}" -d "$BODY")
HTTP_CODE=$(echo "$RESPONSE" | tail -1)
BODY_ONLY=$(echo "$RESPONSE" | sed '$d')

echo "HTTP_STATUS: ${HTTP_CODE}"
echo "$BODY_ONLY" | python3 -m json.tool 2>/dev/null || echo "$BODY_ONLY"

# 如果返回 202，提取 jobId 并提示轮询
if [[ "$HTTP_CODE" == "202" ]]; then
  JOB_ID=$(echo "$BODY_ONLY" | python3 -c "import sys,json; print(json.load(sys.stdin).get('jobId',''))" 2>/dev/null || echo "")
  if [[ -n "$JOB_ID" ]]; then
    echo ""
    echo "Job submitted: ${JOB_ID}"
    echo "Poll with: ./poll_job.sh ${JOB_ID} ${BASE_URL}"
  fi
fi
