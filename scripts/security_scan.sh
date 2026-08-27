#!/usr/bin/env bash
# DKWS 安全扫描脚本 (M2.8)
#
# 运行 pip-audit（依赖漏洞扫描）+ bandit（代码安全扫描）
# 输出报告到 evidence/m2-p6/security/ 目录
#
# 用法：
#   ./scripts/security_scan.sh              # 使用当前 Python 环境
#   ./scripts/security_scan.sh /path/to/venv # 指定虚拟环境
#
# 依赖：pip-audit, bandit (pip install pip-audit bandit)
# CI 集成：此脚本不阻塞 CI，仅生成报告供人工审查

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
OUTPUT_DIR="${PROJECT_ROOT}/evidence/m2-p6/security"
SRC_DIR="${PROJECT_ROOT}/src"

# 如果指定了虚拟环境参数，使用该环境的 Python
PYTHON="${1:-python3}"
PIP="${1:+$1/bin/pip}"
if [ -z "$1" ]; then
    PIP="pip"
fi

mkdir -p "$OUTPUT_DIR"

echo "=== DKWS Security Scan ==="
echo "Output: $OUTPUT_DIR"
echo "Python: $($PYTHON --version 2>&1 || echo 'not found')"
echo "Source: $SRC_DIR"
echo ""

EXIT_CODE=0

# ──────────────────────────────────────────────
# 1. pip-audit：依赖漏洞扫描
# ──────────────────────────────────────────────
echo "--- pip-audit: 依赖漏洞扫描 ---"
if command -v pip-audit &>/dev/null || $PIP show pip-audit &>/dev/null; then
    # JSON 报告（机器可读）
    pip-audit --format=json --output="$OUTPUT_DIR/pip-audit.json" 2>/dev/null || true

    # Markdown 报告（人可读）
    pip-audit --format=markdown --output="$OUTPUT_DIR/pip-audit.md" 2>/dev/null || true

    # 纯文本摘要（终端输出）
    pip-audit --format=columns 2>/dev/null | tee "$OUTPUT_DIR/pip-audit.txt" || true

    # 检查是否有漏洞
    VULN_COUNT=$(python3 -c "
import json, sys
try:
    data = json.load(open('$OUTPUT_DIR/pip-audit.json'))
    deps = data.get('dependencies', [])
    count = sum(len(d.get('vulns', [])) for d in deps)
    print(count)
except Exception:
    print(0)
" 2>/dev/null || echo "0")

    echo "[OK] pip-audit 报告已生成"
    if [ "$VULN_COUNT" -gt 0 ]; then
        echo "[WARN] 发现 ${VULN_COUNT} 个已知漏洞，详见 $OUTPUT_DIR/pip-audit.json"
    else
        echo "[OK] 未发现已知依赖漏洞"
    fi
else
    echo "[SKIP] pip-audit 未安装，跳过依赖漏洞扫描"
    echo "       安装方式: pip install pip-audit"
fi

echo ""

# ──────────────────────────────────────────────
# 2. bandit：代码安全扫描
# ──────────────────────────────────────────────
echo "--- bandit: 代码安全扫描 ---"
if command -v bandit &>/dev/null || $PIP show bandit &>/dev/null; then
    # JSON 报告（机器可读）
    bandit -r "$SRC_DIR" -f json -o "$OUTPUT_DIR/bandit.json" 2>/dev/null || true

    # 纯文本报告（人可读）
    bandit -r "$SRC_DIR" -f txt -o "$OUTPUT_DIR/bandit.txt" 2>/dev/null || true

    # 终端输出摘要
    bandit -r "$SRC_DIR" -f custom \
        --msg-template "{relpath}:{lineno}: {test_id} {severity} {msg}" \
        2>/dev/null | tee "$OUTPUT_DIR/bandit-summary.txt" || true

    # 统计问题数量
    HIGH_COUNT=$(python3 -c "
import json, sys
try:
    data = json.load(open('$OUTPUT_DIR/bandit.json'))
    results = data.get('results', [])
    high = sum(1 for r in results if r.get('issue_severity') == 'HIGH')
    print(high)
except Exception:
    print(0)
" 2>/dev/null || echo "0")

    MEDIUM_COUNT=$(python3 -c "
import json, sys
try:
    data = json.load(open('$OUTPUT_DIR/bandit.json'))
    results = data.get('results', [])
    medium = sum(1 for r in results if r.get('issue_severity') == 'MEDIUM')
    print(medium)
except Exception:
    print(0)
" 2>/dev/null || echo "0")

    echo "[OK] bandit 报告已生成"
    echo "     HIGH: ${HIGH_COUNT}, MEDIUM: ${MEDIUM_COUNT}"

    if [ "$HIGH_COUNT" -gt 0 ]; then
        echo "[WARN] 发现 ${HIGH_COUNT} 个 HIGH 级别安全问题，详见 $OUTPUT_DIR/bandit.json"
    fi
else
    echo "[SKIP] bandit 未安装，跳过代码安全扫描"
    echo "       安装方式: pip install bandit"
fi

echo ""

# ──────────────────────────────────────────────
# 3. 生成安全扫描摘要
# ──────────────────────────────────────────────
echo "--- 生成安全扫描摘要 ---"
cat > "$OUTPUT_DIR/scan-summary.md" << 'SUMMARY_HEADER'
# DKWS 安全扫描摘要

> 自动生成，请勿手动编辑

## 扫描时间

SUMMARY_HEADER

echo "$(date -Iseconds)" >> "$OUTPUT_DIR/scan-summary.md"

cat >> "$OUTPUT_DIR/scan-summary.md" << 'SUMMARY_BODY'

## 扫描工具

| 工具 | 用途 | 报告文件 |
|------|------|----------|
| pip-audit | 依赖漏洞扫描 | pip-audit.json, pip-audit.md |
| bandit | 代码安全扫描 | bandit.json, bandit.txt |

## 注意事项

- 安全扫描报告仅供参考，不阻塞 CI
- HIGH 级别问题应优先处理
- 依赖漏洞需评估实际影响范围后再决定是否升级
SUMMARY_BODY

echo "[OK] scan-summary.md 已生成"

echo ""
echo "=== Security Scan Complete ==="
echo "报告目录: $OUTPUT_DIR"
ls -la "$OUTPUT_DIR/" 2>/dev/null

exit $EXIT_CODE
