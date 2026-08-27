#!/usr/bin/env bash
# DKWS CI 环境初始化脚本 (M2.8)
#
# 在 CI 环境中安装依赖、配置缓存、确保无密钥环境可运行
# 本地开发也可使用：./scripts/ci_setup.sh
#
# 用法：
#   ./scripts/ci_setup.sh                    # 默认安装
#   ./scripts/ci_setup.sh --with-security    # 额外安装安全扫描工具
#   ./scripts/ci_setup.sh --with-lint        # 额外安装 lint 工具
#   ./scripts/ci_setup.sh --full             # 安装全部 CI 工具
#
# 环境变量：
#   DKWS_PROFILE=dev    # CI 默认使用 dev profile（无需 API Key）
#   PYTHON_VERSION      # 可选，指定 Python 版本（本地忽略）

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# 解析参数
INSTALL_SECURITY=false
INSTALL_LINT=false
INSTALL_ALL=false

for arg in "$@"; do
    case "$arg" in
        --with-security) INSTALL_SECURITY=true ;;
        --with-lint)     INSTALL_LINT=true ;;
        --full)          INSTALL_ALL=true ;;
        --help|-h)
            echo "用法: $0 [--with-security] [--with-lint] [--full]"
            echo ""
            echo "选项:"
            echo "  --with-security  安装 pip-audit, bandit, cyclonedx-bom"
            echo "  --with-lint      安装 ruff, mypy"
            echo "  --full           安装全部 CI 工具"
            exit 0
            ;;
    esac
done

if [ "$INSTALL_ALL" = true ]; then
    INSTALL_SECURITY=true
    INSTALL_LINT=true
fi

echo "=== DKWS CI Setup ==="
echo "Project: $PROJECT_ROOT"
echo "Python:  $(python3 --version 2>&1 || echo 'not found')"
echo "Profile: ${DKWS_PROFILE:-dev}"
echo ""

# ──────────────────────────────────────────────
# 1. 确保 dev profile（无密钥环境）
# ──────────────────────────────────────────────
export DKWS_PROFILE="${DKWS_PROFILE:-dev}"
echo "[INFO] DKWS_PROFILE=$DKWS_PROFILE (dev profile 无需 API Key)"

# ──────────────────────────────────────────────
# 2. 升级 pip
# ──────────────────────────────────────────────
echo "[INFO] 升级 pip..."
pip install --upgrade pip setuptools wheel 2>/dev/null || \
    python3 -m pip install --upgrade pip setuptools wheel 2>/dev/null || \
    echo "[WARN] pip 升级失败，继续使用当前版本"

# ──────────────────────────────────────────────
# 3. 安装项目依赖（使用锁文件约束版本）
# ──────────────────────────────────────────────
echo "[INFO] 安装项目依赖..."
LOCK_FILE="${PROJECT_ROOT}/requirements-lock.txt"

if [ -f "$LOCK_FILE" ]; then
    echo "[INFO] 使用 requirements-lock.txt 约束版本"
    pip install -c "$LOCK_FILE" ".[api,dev]" 2>/dev/null || \
        pip install ".[api,dev]"
else
    echo "[WARN] requirements-lock.txt 不存在，直接安装"
    pip install ".[api,dev]"
fi

# ──────────────────────────────────────────────
# 4. 安装测试依赖
# ──────────────────────────────────────────────
echo "[INFO] 安装测试工具 (pytest-cov)..."
pip install pytest-cov 2>/dev/null || echo "[WARN] pytest-cov 安装失败"

# ──────────────────────────────────────────────
# 5. 可选：安装安全扫描工具
# ──────────────────────────────────────────────
if [ "$INSTALL_SECURITY" = true ]; then
    echo "[INFO] 安装安全扫描工具 (pip-audit, bandit, cyclonedx-bom)..."
    pip install pip-audit bandit cyclonedx-bom 2>/dev/null || \
        echo "[WARN] 部分安全工具安装失败"
fi

# ──────────────────────────────────────────────
# 6. 可选：安装 lint 工具
# ──────────────────────────────────────────────
if [ "$INSTALL_LINT" = true ]; then
    echo "[INFO] 安装 lint 工具 (ruff, mypy)..."
    pip install ruff mypy 2>/dev/null || \
        echo "[WARN] 部分 lint 工具安装失败"
fi

# ──────────────────────────────────────────────
# 7. 验证环境
# ──────────────────────────────────────────────
echo ""
echo "=== 环境验证 ==="

# 检查关键包
CHECK_PASSES=true
for pkg in dkws pytest fastapi uvicorn; do
    if python3 -c "import $pkg" 2>/dev/null; then
        echo "[OK] $pkg 可导入"
    else
        echo "[FAIL] $pkg 不可导入"
        CHECK_PASSES=false
    fi
done

# 检查 DKWS_PROFILE
if [ "$DKWS_PROFILE" = "dev" ]; then
    echo "[OK] DKWS_PROFILE=dev (无密钥环境)"
elif [ "$DKWS_PROFILE" = "prod" ]; then
    echo "[WARN] DKWS_PROFILE=prod (需要 API Key，CI 不应使用)"
else
    echo "[WARN] DKWS_PROFILE=$DKWS_PROFILE (非标准 profile)"
fi

echo ""
if [ "$CHECK_PASSES" = true ]; then
    echo "[DONE] CI 环境初始化成功"
else
    echo "[FAIL] CI 环境初始化存在问题，请检查上方输出"
    exit 1
fi
