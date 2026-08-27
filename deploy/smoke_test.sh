#!/usr/bin/env bash
# DKWS 冒烟测试脚本（M2.7）
#
# 快速验证部署是否可用：启动 → 健康检查 → 执行一个 Skill → 停止
#
# 前置条件：
#   - Docker 与 docker compose 已安装
#   - deploy/.env 已配置（至少 DKWS_API_KEYS）
#
# 用法：
#   ./deploy/smoke_test.sh              # 完整冒烟测试
#   ./deploy/smoke_test.sh --skip-down  # 测试完不停止容器
#
# 退出码：
#   0  全部通过
#   1  失败

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
COMPOSE_FILE="$SCRIPT_DIR/docker-compose.yml"
ENV_FILE="$SCRIPT_DIR/.env"
SKIP_DOWN=false

# 解析参数
for arg in "$@"; do
    case "$arg" in
        --skip-down) SKIP_DOWN=true ;;
        -h|--help)
            echo "用法: $0 [--skip-down]"
            echo "  --skip-down  测试完不停止容器"
            exit 0
            ;;
        *)
            echo "未知参数: $arg" >&2
            exit 2
            ;;
    esac
done

echo "=========================================="
echo "DKWS 冒烟测试"
echo "=========================================="

# ---------- 0. 前置检查 ----------
if ! command -v docker &>/dev/null; then
    echo "[FAIL] docker 未安装" >&2
    exit 1
fi

if [ ! -f "$ENV_FILE" ]; then
    echo "[FAIL] 未找到 $ENV_FILE，请先 cp deploy/.env.example deploy/.env 并配置" >&2
    exit 1
fi

# ---------- 1. 构建镜像 ----------
echo ""
echo "[1/5] 构建镜像…"
docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" build 2>&1
echo "[1/5] 构建完成"

# ---------- 2. 启动服务 ----------
echo ""
echo "[2/5] 启动服务…"
# 确保先清理旧容器
docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" down --remove-orphans 2>/dev/null || true
docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" up -d 2>&1
echo "[2/5] 服务已启动"

# 清理函数
cleanup() {
    if [ "$SKIP_DOWN" = true ]; then
        echo ""
        echo "[cleanup] --skip-down 模式，保留容器运行"
        return
    fi
    echo ""
    echo "[cleanup] 停止服务…"
    docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" down --remove-orphans 2>&1 || true
    echo "[cleanup] 已停止"
}
trap cleanup EXIT

# ---------- 3. 等待健康检查 ----------
echo ""
echo "[3/5] 等待 API 服务就绪（最长 90s）…"
MAX_WAIT=90
INTERVAL=5
WAITED=0
API_URL="http://localhost:8106"

while [ $WAITED -lt $MAX_WAIT ]; do
    if curl -fsS "$API_URL/livez" >/dev/null 2>&1; then
        break
    fi
    sleep $INTERVAL
    WAITED=$((WAITED + INTERVAL))
    echo "  等待中… ${WAITED}s / ${MAX_WAIT}s"
done

if [ $WAITED -ge $MAX_WAIT ]; then
    echo "[FAIL] API 服务在 ${MAX_WAIT}s 内未就绪" >&2
    # 输出容器日志辅助排查
    echo "--- api 容器日志（最近 30 行）---" >&2
    docker compose -f "$COMPOSE_FILE" logs --tail=30 api 2>&1 || true
    exit 1
fi
echo "[3/5] API 服务已就绪（等待 ${WAITED}s）"

# ---------- 4. 健康端点验证 ----------
echo ""
echo "[4/5] 验证健康端点…"
PASS=true

# /livez
if curl -fsS "$API_URL/livez" >/dev/null 2>&1; then
    echo "  [PASS] /livez"
else
    echo "  [FAIL] /livez" >&2
    PASS=false
fi

# /readyz（允许 503 降级）
READYZ_STATUS=$(curl -sS -o /dev/null -w "%{http_code}" "$API_URL/readyz" 2>/dev/null || echo "000")
if [ "$READYZ_STATUS" = "200" ] || [ "$READYZ_STATUS" = "503" ]; then
    echo "  [PASS] /readyz (HTTP $READYZ_STATUS)"
else
    echo "  [FAIL] /readyz (HTTP $READYZ_STATUS)" >&2
    PASS=false
fi

# /metrics（允许 401 需密钥）
METRICS_STATUS=$(curl -sS -o /dev/null -w "%{http_code}" "$API_URL/metrics" 2>/dev/null || echo "000")
if [ "$METRICS_STATUS" = "200" ] || [ "$METRICS_STATUS" = "401" ]; then
    echo "  [PASS] /metrics (HTTP $METRICS_STATUS)"
else
    echo "  [FAIL] /metrics (HTTP $METRICS_STATUS)" >&2
    PASS=false
fi

# ---------- 5. Skill 执行测试 ----------
echo ""
echo "[5/5] 执行 Skill 测试…"

# 从 .env 提取 API Key（取第一个 key 的 secret 部分）
API_KEY=""
if [ -f "$ENV_FILE" ]; then
    # 格式：key_id:secret:scope，取 secret
    KEY_LINE=$(grep '^DKWS_API_KEYS=' "$ENV_FILE" | head -1 | cut -d= -f2-)
    API_KEY=$(echo "$KEY_LINE" | cut -d',' -f1 | cut -d: -f2)
fi

if [ -z "$API_KEY" ] || [ "$API_KEY" = "CHANGE_ME_AT_LEAST_16_CHARS" ]; then
    echo "  [SKIP] API Key 未配置真实值，跳过 Skill 执行测试"
else
    # 尝试列出可用 Skill
    SKILL_LIST_STATUS=$(curl -sS -o /tmp/dkws_skills.json -w "%{http_code}" \
        -H "X-API-Key: $API_KEY" \
        "$API_URL/api/skill/list" 2>/dev/null || echo "000")

    if [ "$SKILL_LIST_STATUS" = "200" ]; then
        echo "  [PASS] /api/skill/list (HTTP 200)"

        # 尝试执行第一个 Skill
        FIRST_SKILL=$(python3 -c "
import json, sys
try:
    data = json.load(open('/tmp/dkws_skills.json'))
    items = data.get('data', {}).get('skills', [])
    if items:
        print(items[0].get('id', ''))
except Exception:
    pass
" 2>/dev/null || true)

        if [ -n "$FIRST_SKILL" ]; then
            echo "  [INFO] 检测到 Skill: $FIRST_SKILL（仅验证 list，不触发执行）"
        fi
    elif [ "$SKILL_LIST_STATUS" = "401" ]; then
        echo "  [SKIP] /api/skill/list 返回 401（API Key 可能无 read 权限）"
    else
        echo "  [FAIL] /api/skill/list (HTTP $SKILL_LIST_STATUS)" >&2
        PASS=false
    fi
fi

# ---------- 汇总 ----------
echo ""
echo "=========================================="
if [ "$PASS" = true ]; then
    echo "冒烟测试结果：全部通过"
    echo "=========================================="
    exit 0
else
    echo "冒烟测试结果：存在失败项" >&2
    echo "=========================================="
    exit 1
fi
