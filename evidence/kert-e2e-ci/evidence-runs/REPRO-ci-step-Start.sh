set -euo pipefail
# 拒绝复用已在 8106 上运行的外部实例（TECH_LEAD_DECISION §0.3：
# 非本仓检出会产出与本次改动无关的假象，不得作为证据）。
if curl -fsS --max-time 2 http://127.0.0.1:8106/api/skill/health > /dev/null 2>&1; then
  echo "::error::8106 上已有实例在监听，拒绝复用外部实例（须由本 job 启动本仓代码）"
  exit 1
fi
# 空 HOME：复现 CI 的「无密钥」环境，强制确定性适配器
mkdir -p "$RUNNER_TEMP/kert-home" "$RUNNER_TEMP/kert-ws"
# 空目录即可作 workspace，无需 `kert init`（scripts/run_nfr_baseline.sh 为既有范式）
nohup env HOME="$RUNNER_TEMP/kert-home" \
  python scripts/serve_skill_service.py \
    --port 8106 --host 127.0.0.1 --workspace "$RUNNER_TEMP/kert-ws" \
  > "$RUNNER_TEMP/kert.log" 2>&1 &
echo $! > "$RUNNER_TEMP/kert.pid"
for i in $(seq 1 60); do
  if curl -fsS --max-time 2 http://127.0.0.1:8106/api/skill/health > /dev/null; then
    echo "KERT 就绪（第 ${i} 秒）：GET /api/skill/health = 200"
    exit 0
  fi
  sleep 1
done
echo "::error::KERT 未能在 60 秒内于 127.0.0.1:8106 就绪，e2e 无法真跑——拒绝以 skip 掩盖"
cat "$RUNNER_TEMP/kert.log"
exit 1
