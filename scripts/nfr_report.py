#!/usr/bin/env python3
"""NFR 报告生成器（M2.10 性能与 NFR 基线）。

读取基准测试结果 JSON，生成 Markdown 格式报告。

用法：
  python scripts/nfr_report.py \
    --input evidence/m2-p6/nfr_benchmark_results.json \
    --output evidence/m2-p6/nfr_baseline_report.md
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from datetime import datetime


def _md_table(headers: list[str], rows: list[list[str]]) -> str:
    """生成 Markdown 表格。"""
    lines = []
    lines.append("| " + " | ".join(headers) + " |")
    lines.append("| " + " | ".join("---" for _ in headers) + " |")
    for row in rows:
        lines.append("| " + " | ".join(str(c) for c in row) + " |")
    return "\n".join(lines)


def _fmt_ms(v: float) -> str:
    """格式化毫秒值。"""
    if v == 0:
        return "N/A"
    if v < 1:
        return f"{v:.2f}ms"
    if v < 100:
        return f"{v:.1f}ms"
    return f"{v:.0f}ms"


def _fmt_mb(v: float) -> str:
    """格式化 MB 值。"""
    if v == 0:
        return "N/A"
    return f"{v:.1f}MB"


def _fmt_kb(v: float) -> str:
    """格式化 KB 值。"""
    if v == 0:
        return "N/A"
    return f"{v:.1f}KB"


def generate_report(data: dict) -> str:
    """从基准测试 JSON 生成 Markdown 报告。"""
    meta = data.get("meta", {})
    env = meta.get("environment", {})
    config = meta.get("test_config", {})
    disclaimer = meta.get("disclaimer", "基线值，非 SLA 承诺")

    lines: list[str] = []

    # 标题
    lines.append("# M2.10 NFR 性能基线报告")
    lines.append("")
    lines.append(f"> **{disclaimer}**")
    lines.append("")
    lines.append(f"- 项目：{meta.get('project', 'Leibniz-KERT (DKWS)')}")
    lines.append(f"- 里程碑：{meta.get('milestone', 'M2.10')}")
    lines.append(f"- 生成时间：{datetime.now().isoformat()}")
    lines.append("")

    # 测试环境
    lines.append("## 1. 测试环境")
    lines.append("")
    lines.append(_md_table(
        ["项目", "值"],
        [
            ["操作系统", f"{env.get('os', 'N/A')} {env.get('os_version', '')}"],
            ["CPU 核数", env.get("cpu_count", "N/A")],
            ["架构", env.get("architecture", "N/A")],
            ["Python 版本", env.get("python_version", "N/A")],
            ["主机名", env.get("hostname", "N/A")],
            ["测试时间 (UTC)", env.get("timestamp_utc", "N/A")],
        ],
    ))
    lines.append("")

    # 测试配置
    lines.append("## 2. 测试配置")
    lines.append("")
    lines.append(_md_table(
        ["配置项", "值"],
        [
            ["运行模式", config.get("mode", "deterministic")],
            ["服务地址", config.get("base_url", "N/A")],
            ["延迟采样数", str(config.get("latency_samples", "N/A"))],
            ["吞吐测试并发数", str(config.get("throughput_concurrency", "N/A"))],
            ["吞吐测试持续时间", f"{config.get('throughput_duration_seconds', 'N/A')}s"],
            ["并发测试级别", str(config.get("concurrency_levels", "N/A"))],
        ],
    ))
    lines.append("")

    # 延迟基线
    latency_data = data.get("latency_baseline", [])
    if latency_data:
        lines.append("## 3. 延迟基线")
        lines.append("")
        lines.append("以下为各端点的延迟分布（采样 100 次）：")
        lines.append("")
        rows = []
        for item in latency_data:
            lm = item.get("latency_ms", {})
            rows.append([
                item.get("description", item.get("scenario", "")),
                str(item.get("samples", "")),
                _fmt_ms(lm.get("mean", 0)),
                _fmt_ms(lm.get("p50", 0)),
                _fmt_ms(lm.get("p95", 0)),
                _fmt_ms(lm.get("p99", 0)),
                _fmt_ms(lm.get("min", 0)),
                _fmt_ms(lm.get("max", 0)),
            ])
        lines.append(_md_table(
            ["场景", "样本数", "均值", "P50", "P95", "P99", "最小", "最大"],
            rows,
        ))
        lines.append("")

    # 吞吐基线
    throughput_data = data.get("throughput_baseline", [])
    if throughput_data:
        lines.append("## 4. 吞吐基线")
        lines.append("")
        rows = []
        for item in throughput_data:
            rows.append([
                item.get("description", item.get("scenario", "")),
                str(item.get("concurrency", "")),
                f"{item.get('duration_seconds', '')}s",
                f"{item.get('rps', 0):.2f}",
                _fmt_ms(item.get("p50_ms", 0)),
                _fmt_ms(item.get("p95_ms", 0)),
            ])
        lines.append(_md_table(
            ["场景", "并发数", "持续时间", "RPS", "P50", "P95"],
            rows,
        ))
        lines.append("")

    # 并发基线
    concurrency_data = data.get("concurrency_baseline", [])
    if concurrency_data:
        lines.append("## 5. 并发基线")
        lines.append("")

        # 按 scenario 分组
        by_scenario: dict[str, list] = {}
        for item in concurrency_data:
            key = item.get("scenario", "unknown")
            by_scenario.setdefault(key, []).append(item)

        scenario_labels = {
            "livez": "/livez 健康检查",
            "skill_outreach": "Skill 同步执行 (outreach)",
            "skill_async_outreach": "Skill 异步提交 (outreach)",
        }

        for scenario_key, items in by_scenario.items():
            label = scenario_labels.get(scenario_key, scenario_key)
            lines.append(f"### {label}")
            lines.append("")
            rows = []
            for item in items:
                rows.append([
                    str(item.get("concurrency", "")),
                    f"{item.get('rps', 0):.2f}",
                    _fmt_ms(item.get("p50_ms", 0)),
                    _fmt_ms(item.get("p95_ms", 0)),
                    _fmt_ms(item.get("p99_ms", 0)),
                    f"{item.get('error_rate_pct', 0):.1f}%",
                ])
            lines.append(_md_table(
                ["并发数", "RPS", "P50", "P95", "P99", "错误率"],
                rows,
            ))
            lines.append("")

    # 资源基线
    resource_data = data.get("resource_baseline", {})
    if resource_data:
        lines.append("## 6. 资源基线")
        lines.append("")
        rows = [
            ["服务空闲 RSS", _fmt_mb(resource_data.get("idle_rss_mb", 0))],
            ["服务空闲 VMS", _fmt_mb(resource_data.get("idle_vms_mb", 0))],
            ["单请求 RSS 增量", _fmt_mb(resource_data.get("single_request_rss_delta_mb", 0))],
            ["Worker RSS", _fmt_mb(resource_data.get("worker_rss_mb", 0))],
            ["SQLite 初始大小", _fmt_kb(resource_data.get("sqlite_file_size_kb", 0))],
            ["SQLite 100请求后", _fmt_kb(resource_data.get("sqlite_after_100_kb", 0))],
            ["SQLite 500请求后", _fmt_kb(resource_data.get("sqlite_after_500_kb", 0))],
        ]
        lines.append(_md_table(["指标", "值"], rows))
        lines.append("")

    # 结论
    lines.append("## 7. 结论")
    lines.append("")
    lines.append("本报告记录的是当前版本的 NFR 基线值，**不构成 SLA 承诺**。")
    lines.append("")
    lines.append("### 关键观察")
    lines.append("")

    # 自动生成观察
    observations = []
    if latency_data:
        # 找出 P99 最低和最高的场景
        valid = [(i, i.get("latency_ms", {}).get("p99", 0))
                 for i in latency_data if i.get("latency_ms", {}).get("p99", 0) > 0]
        if valid:
            fastest = min(valid, key=lambda x: x[1])
            slowest = max(valid, key=lambda x: x[1])
            observations.append(
                f"- 延迟最低场景：{fastest[0].get('description', '')} "
                f"(P99={_fmt_ms(fastest[1])})"
            )
            observations.append(
                f"- 延迟最高场景：{slowest[0].get('description', '')} "
                f"(P99={_fmt_ms(slowest[1])})"
            )

    if throughput_data:
        best_rps = max(throughput_data, key=lambda x: x.get("rps", 0))
        observations.append(
            f"- 最高吞吐：{best_rps.get('description', '')} "
            f"(RPS={best_rps.get('rps', 0):.2f})"
        )

    if concurrency_data:
        # 检查高并发下错误率
        high_error = [i for i in concurrency_data if i.get("error_rate_pct", 0) > 5]
        if high_error:
            observations.append(
                f"- 注意：{len(high_error)} 个并发场景错误率 >5%，需关注"
            )
        else:
            observations.append("- 所有并发场景错误率均 <5%")

    if resource_data:
        rss = resource_data.get("idle_rss_mb", 0)
        if rss > 0:
            observations.append(f"- 服务空闲内存占用：{_fmt_mb(rss)}")

    for obs in observations:
        lines.append(obs)
    lines.append("")

    # 后续建议
    lines.append("### 后续建议")
    lines.append("")
    lines.append("1. 在生产环境（有 LLM 调用）下重新测量延迟基线")
    lines.append("2. 建立持续性能监控（CI 集成）")
    lines.append("3. 对高延迟场景进行性能剖析")
    lines.append("4. 制定正式 SLA 指标（基于业务需求）")
    lines.append("5. 考虑引入连接池和缓存优化")
    lines.append("")

    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="DKWS NFR 报告生成器")
    ap.add_argument("--input", required=True,
                    help="基准测试结果 JSON 文件路径")
    ap.add_argument("--output", default=None,
                    help="输出 Markdown 文件路径（默认 stdout）")
    args = ap.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"错误：输入文件不存在 {input_path}", file=sys.stderr)
        sys.exit(1)

    data = json.loads(input_path.read_text(encoding="utf-8"))
    report = generate_report(data)

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(report, encoding="utf-8")
        print(f"[nfr-report] 报告已写入 {out_path}", file=sys.stderr)
    else:
        print(report)


if __name__ == "__main__":
    main()
