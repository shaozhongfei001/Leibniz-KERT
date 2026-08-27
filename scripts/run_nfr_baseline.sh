#!/usr/bin/env bash
# run_nfr_baseline.sh — 一键 NFR 基线测试脚本（M2.10）
#
# 功能：
#   1. 启动本地服务（确定性模式，无需 LLM 密钥）
#   2. 运行基准测试
#   3. 生成报告
#   4. 停止服务
#   5. 全程无人值守
#
# 用法：
#   bash scripts/run_nfr_baseline.sh [--port PORT] [--skip-start] [--skip-stop]
#
# 选项：
#   --port PORT        服务端口（默认 8100）
#   --skip-start       跳过服务启动（假设服务已运行）
#   --skip-stop        跳过服务停止（保留服务运行）
#   --quick            快速模式：减少采样数和持续时间

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
EVIDENCE_DIR="$PROJECT_ROOT/evidence/m2-p6"

# 默认参数
PORT=8106
SKIP_START=0
SKIP_STOP=0
QUICK=0

# 解析参数
while [[ $# -gt 0 ]]; do
    case "$1" in
        --port)     PORT="$2"; shift 2 ;;
        --skip-start) SKIP_START=1; shift ;;
        --skip-stop)  SKIP_STOP=1; shift ;;
        --quick)    QUICK=1; shift ;;
        -h|--help)
            echo "用法: bash scripts/run_nfr_baseline.sh [--port PORT] [--skip-start] [--skip-stop] [--quick]"
            exit 0
            ;;
        *) echo "未知参数: $1"; exit 1 ;;
    esac
done

BASE_URL="http://localhost:$PORT"
SERVER_PID=""
LOG_FILE="$EVIDENCE_DIR/server.log"

echo "=========================================="
echo " M2.10 NFR 基线测试"
echo "=========================================="
echo "项目根: $PROJECT_ROOT"
echo "端口:   $PORT"
echo "URL:    $BASE_URL"
echo "输出:   $EVIDENCE_DIR"
echo "=========================================="

# -------------------------------------------------------
# 1. 创建输出目录
# -------------------------------------------------------
mkdir -p "$EVIDENCE_DIR"

# -------------------------------------------------------
# 2. 启动服务
# -------------------------------------------------------
if [[ $SKIP_START -eq 0 ]]; then
    echo ""
    echo "[1/4] 启动 DKWS 服务（确定性模式）..."

    # 检查端口是否已被占用
    if ss -tlnp "sport = :$PORT" 2>/dev/null | grep -q ":$PORT"; then
        echo "  端口 $PORT 已被占用，假设服务已运行"
        SKIP_START=1
    else
        cd "$PROJECT_ROOT"

        # 启动服务（确定性模式，无需 LLM 密钥）
        python scripts/serve_skill_service.py --port "$PORT" > "$LOG_FILE" 2>&1 &
        SERVER_PID=$!
        echo "  服务 PID: $SERVER_PID"

        # 等待服务就绪
        echo "  等待服务就绪..."
        MAX_WAIT=60
        WAITED=0
        while [[ $WAITED -lt $MAX_WAIT ]]; do
            if curl -sf "$BASE_URL/livez" > /dev/null 2>&1 || curl -sf "$BASE_URL/v1/health" > /dev/null 2>&1; then
                echo "  服务已就绪（等待 ${WAITED}s）"
                break
            fi
            sleep 1
            WAITED=$((WAITED + 1))
        done

        if [[ $WAITED -ge $MAX_WAIT ]]; then
            echo "  错误：服务启动超时（${MAX_WAIT}s）"
            echo "  日志："
            tail -20 "$LOG_FILE" 2>/dev/null || true
            if [[ -n "$SERVER_PID" ]]; then
                kill "$SERVER_PID" 2>/dev/null || true
            fi
            exit 1
        fi
    fi
else
    echo ""
    echo "[1/4] 跳过服务启动（--skip-start）"
fi

# -------------------------------------------------------
# 3. 运行基准测试
# -------------------------------------------------------
echo ""
echo "[2/4] 运行 NFR 基准测试..."

cd "$PROJECT_ROOT"

QUICK_FLAG=""
if [[ $QUICK -eq 1 ]]; then
    QUICK_FLAG="--quick"
    echo "  快速模式：减少采样和持续时间"
fi

python scripts/nfr_benchmark.py \
    --base-url "$BASE_URL" \
    --port "$PORT" \
    --output-dir "$EVIDENCE_DIR"

if [[ $? -ne 0 ]]; then
    echo "  错误：基准测试失败"
    if [[ $SKIP_STOP -eq 0 && -n "$SERVER_PID" ]]; then
        kill "$SERVER_PID" 2>/dev/null || true
    fi
    exit 1
fi

echo "  基准测试完成"

# -------------------------------------------------------
# 4. 生成报告
# -------------------------------------------------------
echo ""
echo "[3/4] 生成 NFR 报告..."

python scripts/nfr_report.py \
    --input "$EVIDENCE_DIR/nfr_benchmark_results.json" \
    --output "$EVIDENCE_DIR/nfr_baseline_report.md"

if [[ $? -ne 0 ]]; then
    echo "  错误：报告生成失败"
    if [[ $SKIP_STOP -eq 0 && -n "$SERVER_PID" ]]; then
        kill "$SERVER_PID" 2>/dev/null || true
    fi
    exit 1
fi

echo "  报告已生成"

# -------------------------------------------------------
# 5. 停止服务
# -------------------------------------------------------
if [[ $SKIP_STOP -eq 0 && -n "$SERVER_PID" ]]; then
    echo ""
    echo "[4/4] 停止 DKWS 服务..."
    kill "$SERVER_PID" 2>/dev/null || true
    # 等待进程退出
    for i in $(seq 1 10); do
        if ! kill -0 "$SERVER_PID" 2>/dev/null; then
            break
        fi
        sleep 1
    done
    # 强制终止
    kill -9 "$SERVER_PID" 2>/dev/null || true
    echo "  服务已停止"
else
    echo ""
    echo "[4/4] 跳过服务停止（--skip-stop 或服务非本脚本启动）"
fi

# -------------------------------------------------------
# 完成
# -------------------------------------------------------
echo ""
echo "=========================================="
echo " NFR 基线测试完成"
echo "=========================================="
echo ""
echo "输出文件："
echo "  - $EVIDENCE_DIR/nfr_benchmark_results.json  (原始数据)"
echo "  - $EVIDENCE_DIR/nfr_baseline_report.md      (Markdown 报告)"
echo "  - $EVIDENCE_DIR/nfr_baseline.md             (基线指标文档)"
if [[ $SKIP_START -eq 0 ]]; then
    echo "  - $LOG_FILE                                  (服务日志)"
fi
echo ""
echo "注意：所有数值为基线值，非 SLA 承诺。"
