#!/usr/bin/env bash
# 一键复跑「六环链路 · 人类走查」（原图 + 故事；Playwright 真人浏览器）。
#
# 它自己做完这些事（**人只需要跑这一条命令**）：
#   ① 在**临时工作区**里 provision 控制面（路由策略 / 知识地图 / 本体引用）；
#   ② 用**独立端口**起本仓 KERT（拒绝复用任何外部实例，避免"证据不是本次改动产生的"）；
#   ③ 等就绪（fail-closed：超时即失败并打印日志尾部，绝不以"跳过"收场）；
#   ④ 跑走查：KERT 侧（Swagger 环1→环3）+ **六环工作台**（/dsh/rings，一键走一遍）；
#      `--with-lightrag` 时再加知识库侧（需外部实例在跑；否则**不**默默跳过）；
#   ⑤ 收尾：杀掉自己起的 KERT（`--keep` 可保留）。
#
# 产出：`evidence/m7-3/human-walkthrough/*.png`（原图）+ 控制台"人看到了什么"。
# 依赖：Playwright（`pip install playwright`）+ 系统 Chrome 或自带 chromium；**不改** pyproject。
#
# ⚠ 非声明：走查是**人侧可见面复核**，不是机械断言；六环断言在 tests/ 与 CI job 里。

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

PY="${PY:-$REPO_ROOT/.venv/bin/python}"
PORT="${PORT:-8123}"
WS="${WS:-/tmp/kert-human-walkthrough-ws}"
OUT="${OUT:-$REPO_ROOT/evidence/m7-3/human-walkthrough}"
CONTROL_PLANE="${CONTROL_PLANE:-$REPO_ROOT/examples/bank-front-knowledge-maps}"
SKILL_PACKAGES="${SKILL_PACKAGES:-$REPO_ROOT/examples/bank-front-skills}"
KERT_LOG="${KERT_LOG:-/tmp/kert-human-walkthrough.log}"
WITH_LIGHTRAG=0
KEEP=0
FULL_CHAIN=0

usage() {
  cat <<'USAGE'
用法：scripts/run_human_walkthrough.sh [选项]
  --full-chain      先造出**完整链**（接入→抽取→审核→发布→按计划物化）⇒ 工作台的环 5/6 能取回链
                    （默认不做：默认走"供给态空工作区"，环 5/6 会如实显示 SERVICE_NOT_READY）
  --with-lightrag   同时走知识库侧（需 LightRAG 实例在跑，默认 9621）
  --port <端口>     KERT 监听端口（默认 8123）
  --ws <目录>       工作区（默认 /tmp/kert-human-walkthrough-ws）
  --out <目录>      PNG 输出目录（默认 evidence/m7-3/human-walkthrough）
  --keep            跑完不杀 KERT（便于人自己接着看）
  -h|--help         本帮助
环境变量：PY（python 解释器）、CONTROL_PLANE、SKILL_PACKAGES、KERT_LOG
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --full-chain) FULL_CHAIN=1; shift ;;
    --with-lightrag) WITH_LIGHTRAG=1; shift ;;
    --port) PORT="$2"; shift 2 ;;
    --ws) WS="$2"; shift 2 ;;
    --out) OUT="$2"; shift 2 ;;
    --keep) KEEP=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "::error::未知参数：$1"; usage; exit 2 ;;
  esac
done

echo "== 一键复跑：六环链路人类走查 =="
echo "   仓库      = $REPO_ROOT"
echo "   解释器    = $PY"
echo "   端口/工作区 = $PORT / $WS"
echo "   原图目录  = $OUT"

# ① 依赖自检（**不**静默降级）
if [[ ! -x "$PY" ]]; then
  echo "::error::找不到 Python 解释器：$PY（可用 PY=... 覆盖；或用 .venv/bin/python）"
  exit 1
fi
if ! "$PY" -c "import playwright" >/dev/null 2>&1; then
  echo "::error::未安装 Playwright（$PY -m pip install playwright；本脚本**不改** pyproject）"
  exit 1
fi

# ② 拒绝复用外部实例（同 CI e2e job 的纪律：非本脚本启动的实例不得作为证据）
if curl -fsS --max-time 2 "http://127.0.0.1:${PORT}/api/skill/health" >/dev/null 2>&1; then
  echo "::error::端口 ${PORT} 上已有实例在监听 —— 拒绝复用外部实例（换个 --port，或先停掉它）"
  exit 1
fi

# ③ 供给控制面（幂等；--init 允许在空目录初始化）
"$PY" -c "
import sys
sys.argv = ['kert', 'provision', '-w', '$WS', '-s', '$CONTROL_PLANE', '--init']
from kert.cli.main import app
app()
" >/dev/null
echo "✓ 控制面已供给：$WS"

# ③b 可选：把"完整链"造出来（接入 → 抽取 → 审核 → 发布 → **按计划物化**）
#    为什么默认不做：默认走"供给态空工作区"更能暴露"没走到物化时链取不回来"的真实形态
#    （工作台会如实显示 SERVICE_NOT_READY）。要看完整链就加 --full-chain。
if [[ "$FULL_CHAIN" == "1" ]]; then
  env WS="$WS" "$PY" - <<'PY'
import json
import os
from pathlib import Path

from kert.application.extract import KnowledgeExtractor
from kert.application.ingest import Ingestor
from kert.application.parse_doc import DocumentParserService
from kert.application.publish import Publisher
from kert.application.review import ReviewService
from kert.application.services import KnowledgeService

ws = Path(os.environ["WS"])
src = Path("/tmp/kert-walkthrough-demo-source.md")
src.write_text(
    "# 政策\n\n## 产品\n\n产品A利率为3.5%。\n\n产品B利率为4.2%。\n\n"
    "产品A需要材料M1。\n\n规则：利率不超过10。\n", encoding="utf-8")

r = Ingestor(ws).ingest("product", [src], "batch-walkthrough-demo")
pr = DocumentParserService(ws).parse("product", r.batch_id)
ex = KnowledgeExtractor(ws).extract("product", r.batch_id, run_id=pr.run_id)
ReviewService(ws).review("product", run_id=pr.run_id,
                         object_refs=[c["path"] for c in ex.candidates],
                         decision="APPROVE", reason="walkthrough demo", decided_by="walkthrough")
pub = Publisher(ws).publish("product", run_id=pr.run_id)
out = KnowledgeService(ws, service_id="product_knowledge").materialize_from_plan(
    "OUTREACH_PREPARATION", domain="product", subject_id="CUST-CORP-0001")
print("  链已造好：core 版本 =", pub.release_version,
      "| 投影版本 =", out["projection_version"], "| planId =", out["planId"])
print("  血缘：", json.dumps({k: out[k] for k in ("planId", "planHash")}, ensure_ascii=False))
PY
  echo "✓ 完整链已就绪（工作台的环 5/6 现在能取回链）"
fi

# ④ 起 KERT（独立端口；本仓代码）
KERT_PID=""
cleanup() {
  if [[ -n "$KERT_PID" ]] && kill -0 "$KERT_PID" 2>/dev/null; then
    if [[ "$KEEP" == "1" ]]; then
      echo "（--keep：KERT 仍在运行，pid=$KERT_PID，日志 $KERT_LOG）"
    else
      kill "$KERT_PID" 2>/dev/null || true
      echo "✓ 已停止本次启动的 KERT（pid=$KERT_PID）"
    fi
  fi
}
trap cleanup EXIT

env KERT_PROFILE=dev KERT_REPO_ROOT="$REPO_ROOT" KERT_SKILL_PACKAGES="$SKILL_PACKAGES" \
  nohup "$PY" scripts/serve_skill_service.py --port "$PORT" --host 127.0.0.1 \
  --workspace "$WS" > "$KERT_LOG" 2>&1 &
KERT_PID=$!

for i in $(seq 1 60); do
  if curl -fsS --max-time 2 "http://127.0.0.1:${PORT}/api/skill/health" >/dev/null 2>&1; then
    echo "✓ KERT 就绪（第 ${i} 秒）：http://127.0.0.1:${PORT}/dsh/rings"
    break
  fi
  if ! kill -0 "$KERT_PID" 2>/dev/null; then
    echo "::error::KERT 进程已退出，日志尾部："
    tail -30 "$KERT_LOG"
    exit 1
  fi
  sleep 1
  if [[ "$i" == "60" ]]; then
    echo "::error::KERT 未能在 60 秒内就绪（端口 $PORT），日志尾部："
    tail -30 "$KERT_LOG"
    exit 1
  fi
done

# ⑤ 跑走查（KERT 侧 + 工作台；--with-lightrag 时加知识库侧）
WALK_ARGS=(--kert-url "http://127.0.0.1:${PORT}" --out "$OUT")
if [[ "$WITH_LIGHTRAG" == "1" ]]; then
  WALK_ARGS+=(--with-lightrag)
fi
"$PY" evidence/m7-3/human-walkthrough/run_walkthrough.py "${WALK_ARGS[@]}"

echo
echo "== 完成 =="
echo "原图（未裁剪未美化）："
ls -1 "$OUT"/*.png 2>/dev/null | sed 's/^/  /' || true
echo "故事与判据表：$OUT/STORY_human_walkthrough.md"
if [[ "$WITH_LIGHTRAG" != "1" ]]; then
  echo "（知识库侧**未**跑：如需，加 --with-lightrag 且确保外部实例在跑）"
fi
