#!/usr/bin/env bash
# poll_job.sh — 轮询 DKWS 异步 Job 状态
#
# 用法：
#   ./poll_job.sh JOB_ID [BASE_URL] [INTERVAL_SEC] [TIMEOUT_SEC]
#
# 示例：
#   ./poll_job.sh JOB-SKILL-20260828-001
#   ./poll_job.sh JOB-SKILL-20260828-001 http://192.168.1.100:8106 5 300
#
# 环境变量：
#   DKWS_API_KEY — API Key（可选）

set -euo pipefail

JOB_ID="${1:?Usage: $0 JOB_ID [BASE_URL] [INTERVAL_SEC] [TIMEOUT_SEC]}"
BASE_URL="${2:-http://127.0.0.1:8106}"
INTERVAL="${3:-3}"
TIMEOUT="${4:-180}"
API_KEY="${DKWS_API_KEY:-}"

HEADERS=(-H "Accept: application/json")
if [[ -n "$API_KEY" ]]; then
  HEADERS+=(-H "X-API-Key: $API_KEY")
fi

echo ">>> Polling job ${JOB_ID} (interval=${INTERVAL}s, timeout=${TIMEOUT}s)"

DEADLINE=$(($(date +%s) + TIMEOUT))
LAST_STATUS=""

while true; do
  RESPONSE=$(curl -sS -w "\n%{http_code}" "${BASE_URL}/v1/jobs/${JOB_ID}" "${HEADERS[@]}")
  HTTP_CODE=$(echo "$RESPONSE" | tail -1)
  BODY_ONLY=$(echo "$RESPONSE" | sed '$d')

  if [[ "$HTTP_CODE" == "404" ]]; then
    echo "Job not found: ${JOB_ID}"
    exit 1
  fi

  STATUS=$(echo "$BODY_ONLY" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status','UNKNOWN'))" 2>/dev/null || echo "UNKNOWN")

  NOW=$(date +%H:%M:%S)
  if [[ "$STATUS" != "$LAST_STATUS" ]]; then
    echo "[${NOW}] Status: ${STATUS}"
    LAST_STATUS="$STATUS"
  fi

  if [[ "$STATUS" == "COMPLETED" || "$STATUS" == "FAILED" ]]; then
    echo ""
    echo "Job finished: ${STATUS}"
    echo "$BODY_ONLY" | python3 -m json.tool 2>/dev/null || echo "$BODY_ONLY"
    exit $( [[ "$STATUS" == "COMPLETED" ]] && echo 0 || echo 1 )
  fi

  if [[ $(date +%s) -ge $DEADLINE ]]; then
    echo ""
    echo "Polling timed out after ${TIMEOUT}s (last status: ${STATUS})"
    exit 2
  fi

  sleep "$INTERVAL"
done
