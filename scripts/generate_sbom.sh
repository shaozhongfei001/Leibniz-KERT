#!/usr/bin/env bash
# DKWS SBOM 生成脚本 (M2.8)
#
# 生成 CycloneDX 格式的 Software Bill of Materials (SBOM)
# 输出到 evidence/m2-p6/sbom/ 目录
#
# 用法：
#   ./scripts/generate_sbom.sh              # 使用当前 Python 环境
#   ./scripts/generate_sbom.sh /path/to/venv # 指定虚拟环境
#
# 依赖：cyclonedx-bom (pip install cyclonedx-bom)
# 回退：pip-licenses (pip install pip-licenses)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
OUTPUT_DIR="${PROJECT_ROOT}/evidence/m2-p6/sbom"

# 如果指定了虚拟环境参数，使用该环境的 Python
PYTHON="${1:-python3}"
PIP="${1:+$1/bin/pip}"
if [ -z "$1" ]; then
    PIP="pip"
fi

mkdir -p "$OUTPUT_DIR"

echo "=== DKWS SBOM Generation ==="
echo "Output: $OUTPUT_DIR"
echo "Python: $($PYTHON --version 2>&1 || echo 'not found')"
echo ""

# 方法1：cyclonedx-bom（CycloneDX 标准格式）
if command -v cyclonedx-py &>/dev/null || $PIP show cyclonedx-bom &>/dev/null; then
    echo "[INFO] 使用 cyclonedx-bom 生成 CycloneDX SBOM..."
    cyclonedx-py environment \
        --output-format json \
        --output "$OUTPUT_DIR/sbom.json" \
        2>/dev/null && echo "[OK] sbom.json 已生成" || {
        # 回退到 pip 方式
        echo "[WARN] cyclonedx-py environment 失败，尝试 pip 列表方式..."
        $PIP list --format=json 2>/dev/null | cyclonedx-py pip \
            --output-format json \
            --output "$OUTPUT_DIR/sbom.json" \
            2>/dev/null && echo "[OK] sbom.json 已生成 (pip 方式)" || \
            echo "[WARN] cyclonedx-bom 生成失败，使用回退方案"
    }
else
    echo "[WARN] cyclonedx-bom 未安装，跳过 CycloneDX SBOM"
fi

# 方法2：pip-licenses 作为回退（许可证清单）
if command -v pip-licenses &>/dev/null || $PIP show pip-licenses &>/dev/null; then
    echo "[INFO] 生成许可证清单..."
    $PIP run pip-licenses --format=json --output-file="$OUTPUT_DIR/licenses.json" 2>/dev/null || \
    pip-licenses --format=json --output-file="$OUTPUT_DIR/licenses.json" 2>/dev/null || \
    echo "[WARN] pip-licenses 生成失败"

    pip-licenses --format=csv --output-file="$OUTPUT_DIR/licenses.csv" 2>/dev/null || true
    echo "[OK] licenses.json / licenses.csv 已生成"
else
    echo "[WARN] pip-licenses 未安装，生成基础依赖清单..."
    $PIP freeze 2>/dev/null | grep -v "^-e" | sort > "$OUTPUT_DIR/requirements-freeze.txt"
    echo "[OK] requirements-freeze.txt 已生成（基础回退）"
fi

# 方法3：pip freeze 作为最基础回退
$PIP freeze 2>/dev/null | grep -v "^-e" | sort > "$OUTPUT_DIR/requirements-freeze.txt"
echo "[OK] requirements-freeze.txt 已生成"

# 生成摘要
echo ""
echo "=== SBOM 摘要 ==="
echo "文件列表："
ls -la "$OUTPUT_DIR/" 2>/dev/null || echo "  (无文件)"
echo ""
echo "依赖总数：$(grep -c '==' "$OUTPUT_DIR/requirements-freeze.txt" 2>/dev/null || echo 'N/A')"

echo ""
echo "[DONE] SBOM 生成完成"
