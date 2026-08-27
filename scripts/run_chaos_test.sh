#!/usr/bin/env bash
# DKWS 故障注入一键测试脚本
# 启动 DKWS 服务 → 逐项执行故障注入 → 记录行为 → 生成报告
# 全程无人值守，安全可控（自动恢复）
#
# 用法：
#   bash scripts/run_chaos_test.sh [--port 8106] [--skip-process-tests]
#
# 环境要求：
#   - Python 3.10+
#   - DKWS 项目在 /home/szf/dev/Leibniz-KERT

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$SCRIPT_DIR/.." && pwd)"
PORT="${DKWS_PORT:-8106}"
SKIP_PROCESS=""
OUT_DIR="${REPO}/evidence/m3-p0"

# 解析参数
while [[ $# -gt 0 ]]; do
    case "$1" in
        --port)
            PORT="$2"
            shift 2
            ;;
        --skip-process-tests)
            SKIP_PROCESS="--skip-process-tests"
            shift
            ;;
        --out)
            OUT_DIR="$2"
            shift 2
            ;;
        --help|-h)
            echo "用法: bash scripts/run_chaos_test.sh [--port 8106] [--skip-process-tests] [--out DIR]"
            exit 0
            ;;
        *)
            echo "未知参数: $1" >&2
            exit 1
            ;;
    esac
done

echo "============================================"
echo "DKWS 故障注入一键测试"
echo "============================================"
echo "端口: $PORT"
echo "输出: $OUT_DIR"
echo "跳过进程测试: ${SKIP_PROCESS:-否}"
echo "时间: $(date '+%Y-%m-%d %H:%M:%S')"
echo ""

# 确保输出目录存在
mkdir -p "$OUT_DIR"

# 清理旧的故障注入状态
echo "[1/4] 清理旧的故障注入状态 ..."
python3 "$SCRIPT_DIR/chaos_injector.py" cleanup 2>/dev/null || true

# 杀掉占用端口的旧进程
echo "[2/4] 清理端口 $PORT 上的旧进程 ..."
PID_ON_PORT=$(lsof -ti :"$PORT" 2>/dev/null || true)
if [[ -n "$PID_ON_PORT" ]]; then
    echo "  发现占用端口的进程: $PID_ON_PORT，正在终止 ..."
    kill -9 $PID_ON_PORT 2>/dev/null || true
    sleep 1
fi

# 运行故障注入测试
echo "[3/4] 运行故障注入测试 ..."
echo "--------------------------------------------"
python3 "$SCRIPT_DIR/chaos_test.py" \
    --dkws-port "$PORT" \
    --out "$OUT_DIR" \
    $SKIP_PROCESS

EXIT_CODE=$?

# 清理
echo ""
echo "[4/4] 最终清理 ..."
python3 "$SCRIPT_DIR/chaos_injector.py" cleanup 2>/dev/null || true

# 杀掉可能残留的 DKWS 进程
PID_ON_PORT=$(lsof -ti :"$PORT" 2>/dev/null || true)
if [[ -n "$PID_ON_PORT" ]]; then
    echo "  清理残留进程: $PID_ON_PORT"
    kill $PID_ON_PORT 2>/dev/null || true
fi

echo ""
echo "============================================"
if [[ $EXIT_CODE -eq 0 ]]; then
    echo "故障注入测试全部通过"
else
    echo "故障注入测试存在失败项"
fi
echo "报告: $OUT_DIR/chaos_test_report.json"
echo "时间: $(date '+%Y-%m-%d %H:%M:%S')"
echo "============================================"

exit $EXIT_CODE
