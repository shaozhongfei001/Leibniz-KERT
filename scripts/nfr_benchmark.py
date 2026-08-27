#!/usr/bin/env python3
"""NFR 基准测试框架（M2.10 性能与 NFR 基线）。

测试场景：
- 延迟基线：/livez, /readyz, Skill 同步/异步执行 P50/P95/P99
- 吞吐基线：健康检查 RPS、Skill 同步/异步 RPS
- 并发基线：10/50/100 并发下延迟分布
- 资源基线：内存占用、SQLite 文件大小

用法：
  python scripts/nfr_benchmark.py --base-url http://localhost:8100 \
    --output-dir evidence/m2-p6

约束：
- 仅使用标准库，无需额外依赖
- 必须在无 LLM 密钥环境下可运行（确定性模式）
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
import time
import urllib.request
import urllib.error
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# 将项目 src 加入 path 以便 import load_generator
_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
sys.path.insert(0, str(_SCRIPT_DIR))

from load_generator import (
    LoadTestConfig,
    LoadTestResult,
    run_load_test,
    _do_request,
    SCENARIOS,
)


# ---------------------------------------------------------------------------
# 环境信息
# ---------------------------------------------------------------------------

def collect_env_info() -> dict[str, str]:
    """收集测试环境信息。"""
    import resource

    mem_self = resource.getrusage(resource.RUSAGE_SELF)
    return {
        "os": platform.system(),
        "os_version": platform.release(),
        "cpu_count": str(os.cpu_count() or "unknown"),
        "python_version": platform.python_version(),
        "architecture": platform.machine(),
        "hostname": platform.node(),
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# 资源基线
# ---------------------------------------------------------------------------

@dataclass
class ResourceBaseline:
    """资源使用基线。"""
    idle_rss_mb: float = 0.0
    idle_vms_mb: float = 0.0
    single_request_rss_delta_mb: float = 0.0
    single_request_vms_delta_mb: float = 0.0
    worker_rss_mb: float = 0.0
    sqlite_file_size_kb: float = 0.0
    sqlite_after_100_kb: float = 0.0
    sqlite_after_500_kb: float = 0.0


def _get_process_memory_mb(pid: int | None = None) -> tuple[float, float]:
    """获取进程内存使用（RSS, VMS），单位 MB。"""
    try:
        if pid is None:
            pid = os.getpid()
        with open(f"/proc/{pid}/status", "r") as f:
            content = f.read()
        rss_kb = 0.0
        vms_kb = 0.0
        for line in content.splitlines():
            if line.startswith("VmRSS:"):
                rss_kb = float(line.split()[1])
            elif line.startswith("VmSize:"):
                vms_kb = float(line.split()[1])
        return rss_kb / 1024, vms_kb / 1024
    except Exception:
        return 0.0, 0.0


def _find_server_pid(port: int) -> int | None:
    """查找监听指定端口的进程 PID。"""
    try:
        result = subprocess.run(
            ["ss", "-tlnp", f"sport = :{port}"],
            capture_output=True, text=True, timeout=5,
        )
        for line in result.stdout.splitlines():
            if f":{port}" in line and "pid=" in line:
                # 格式: ... pid=12345 ...
                for part in line.split():
                    if part.startswith("pid="):
                        return int(part.split("=")[1].rstrip(","))
    except Exception:
        pass
    return None


def _find_sqlite_path() -> Path | None:
    """查找 SQLite 数据库文件路径。"""
    candidates = [
        _PROJECT_ROOT / "90_control" / "runtime" / "dkws_runtime.db",
        _PROJECT_ROOT / "runtime" / "dkws_runtime.db",
    ]
    for p in candidates:
        if p.exists():
            return p
    # 搜索
    for p in _PROJECT_ROOT.rglob("*.db"):
        if "runtime" in str(p).lower() or "dkws" in str(p).lower():
            return p
    return None


def measure_resource_baseline(base_url: str, port: int = 8100) -> ResourceBaseline:
    """测量资源基线。"""
    baseline = ResourceBaseline()

    # 服务进程内存
    server_pid = _find_server_pid(port)
    if server_pid:
        rss, vms = _get_process_memory_mb(server_pid)
        baseline.idle_rss_mb = round(rss, 2)
        baseline.idle_vms_mb = round(vms, 2)

    # 单请求内存增量
    if server_pid:
        rss_before, _ = _get_process_memory_mb(server_pid)
        health_scenario = _detect_health_scenario(base_url)
        for _ in range(5):
            _do_request(base_url, health_scenario, timeout=10)
        rss_after, _ = _get_process_memory_mb(server_pid)
        baseline.single_request_rss_delta_mb = round(max(0, rss_after - rss_before), 2)
        baseline.single_request_vms_delta_mb = 0.0

    # Worker 内存（查找 worker 子进程）
    if server_pid:
        try:
            result = subprocess.run(
                ["pgrep", "-P", str(server_pid)],
                capture_output=True, text=True, timeout=5,
            )
            for pid_str in result.stdout.strip().splitlines():
                child_pid = int(pid_str.strip())
                rss, _ = _get_process_memory_mb(child_pid)
                if rss > baseline.worker_rss_mb:
                    baseline.worker_rss_mb = round(rss, 2)
        except Exception:
            pass

    # SQLite 文件大小
    db_path = _find_sqlite_path()
    if db_path:
        baseline.sqlite_file_size_kb = round(db_path.stat().st_size / 1024, 2)

        # 测量 100 次请求后的大小
        size_before = db_path.stat().st_size
        for i in range(100):
            _do_request(base_url, "skill_outreach", timeout=30)
        size_after_100 = db_path.stat().st_size
        baseline.sqlite_after_100_kb = round(size_after_100 / 1024, 2)

        # 测量 500 次请求后的大小（再发 400 次）
        for i in range(400):
            _do_request(base_url, "skill_outreach", timeout=30)
        size_after_500 = db_path.stat().st_size
        baseline.sqlite_after_500_kb = round(size_after_500 / 1024, 2)

    return baseline


# ---------------------------------------------------------------------------
# 延迟基线
# ---------------------------------------------------------------------------

@dataclass
class LatencyBaseline:
    """延迟基线结果。"""
    scenario: str
    description: str
    samples: int
    latency_ms: dict[str, float]  # p50, p95, p99, mean, min, max


def measure_latency_baseline(base_url: str, samples: int = 100) -> list[LatencyBaseline]:
    """测量延迟基线。"""
    results: list[LatencyBaseline] = []

    # 检测可用端点
    health_scenario = _detect_health_scenario(base_url)
    has_livez = _probe_endpoint(base_url, "/livez")
    has_readyz = _probe_endpoint(base_url, "/readyz")

    scenarios = [
        ("livez", "/livez 健康检查"),
        ("readyz", "/readyz 就绪检查"),
        ("health", "/v1/health 健康检查"),
        ("skill_outreach", "Skill 同步执行 (outreach)"),
        ("skill_meeting", "Skill 同步执行 (meeting)"),
        ("skill_previsit", "Skill 同步执行 (previsit)"),
        ("skill_async_outreach", "Skill 异步提交 (outreach)"),
    ]

    for scenario_key, desc in scenarios:
        # 跳过不可用的端点
        if scenario_key == "livez" and not has_livez:
            print(f"  [latency] 跳过 {desc}（端点不可用）", file=sys.stderr)
            continue
        if scenario_key == "readyz" and not has_readyz:
            print(f"  [latency] 跳过 {desc}（端点不可用）", file=sys.stderr)
            continue
        # 如果 livez 可用，跳过 /v1/health 延迟测试（重复）
        if scenario_key == "health" and has_livez:
            print(f"  [latency] 跳过 {desc}（已有 /livez）", file=sys.stderr)
            continue
        latencies: list[float] = []
        errors = 0
        for i in range(samples):
            r = _do_request(base_url, scenario_key, timeout=30)
            if r.success:
                latencies.append(r.latency_ms)
            else:
                errors += 1
            # 异步提交间微小间隔避免过快
            if "async" in scenario_key:
                time.sleep(0.01)

        if not latencies:
            results.append(LatencyBaseline(
                scenario=scenario_key, description=desc,
                samples=samples,
                latency_ms={"p50": 0, "p95": 0, "p99": 0,
                            "mean": 0, "min": 0, "max": 0},
            ))
            continue

        latencies.sort()
        n = len(latencies)

        def _pct(pct: float) -> float:
            idx = (pct / 100.0) * (n - 1)
            lo = int(idx)
            hi = min(lo + 1, n - 1)
            frac = idx - lo
            return round(latencies[lo] + frac * (latencies[hi] - latencies[lo]), 2)

        results.append(LatencyBaseline(
            scenario=scenario_key,
            description=desc,
            samples=n,
            latency_ms={
                "p50": _pct(50),
                "p95": _pct(95),
                "p99": _pct(99),
                "mean": round(sum(latencies) / n, 2),
                "min": latencies[0],
                "max": latencies[-1],
            },
        ))
        print(f"  [latency] {desc}: P50={_pct(50)}ms P95={_pct(95)}ms "
              f"P99={_pct(99)}ms (n={n}, err={errors})", file=sys.stderr)

    return results


# ---------------------------------------------------------------------------
# 吞吐基线
# ---------------------------------------------------------------------------

@dataclass
class ThroughputBaseline:
    """吞吐基线结果。"""
    scenario: str
    description: str
    concurrency: int
    duration_seconds: float
    rps: float
    p50_ms: float
    p95_ms: float


def measure_throughput_baseline(base_url: str) -> list[ThroughputBaseline]:
    """测量吞吐基线。"""
    results: list[ThroughputBaseline] = []

    health_scenario = _detect_health_scenario(base_url)
    health_desc = "/livez RPS" if health_scenario == "livez" else "/v1/health RPS"

    scenarios = [
        (health_scenario, health_desc, 10, 10),
        ("skill_outreach", "Skill 同步执行 RPS", 5, 15),
        ("skill_async_outreach", "Skill 异步提交 RPS", 10, 10),
    ]

    for scenario_key, desc, concurrency, duration in scenarios:
        config = LoadTestConfig(
            base_url=base_url,
            scenario=scenario_key,
            concurrency=concurrency,
            duration_seconds=duration,
            ramp_up_seconds=2,
        )
        print(f"  [throughput] {desc} (并发={concurrency}, 持续={duration}s)...",
              file=sys.stderr)
        result = run_load_test(config)
        results.append(ThroughputBaseline(
            scenario=scenario_key,
            description=desc,
            concurrency=concurrency,
            duration_seconds=duration,
            rps=result.requests_per_second,
            p50_ms=result.latency_ms["p50"],
            p95_ms=result.latency_ms["p95"],
        ))
        print(f"  [throughput] {desc}: RPS={result.requests_per_second}, "
              f"P50={result.latency_ms['p50']}ms", file=sys.stderr)

    return results


# ---------------------------------------------------------------------------
# 并发基线
# ---------------------------------------------------------------------------

@dataclass
class ConcurrencyBaseline:
    """并发基线结果。"""
    scenario: str
    concurrency: int
    rps: float
    p50_ms: float
    p95_ms: float
    p99_ms: float
    error_rate_pct: float


def measure_concurrency_baseline(base_url: str) -> list[ConcurrencyBaseline]:
    """测量并发基线。"""
    results: list[ConcurrencyBaseline] = []
    concurrency_levels = [1, 10, 50, 100]
    health_scenario = _detect_health_scenario(base_url)

    for c in concurrency_levels:
        config = LoadTestConfig(
            base_url=base_url,
            scenario=health_scenario,
            concurrency=c,
            duration_seconds=15,
            ramp_up_seconds=3,
        )
        print(f"  [concurrency] 并发={c} ...", file=sys.stderr)
        result = run_load_test(config)
        error_rate = (result.failed_requests / max(result.total_requests, 1)) * 100
        results.append(ConcurrencyBaseline(
            scenario=health_scenario,
            concurrency=c,
            rps=result.requests_per_second,
            p50_ms=result.latency_ms["p50"],
            p95_ms=result.latency_ms["p95"],
            p99_ms=result.latency_ms["p99"],
            error_rate_pct=round(error_rate, 2),
        ))
        print(f"  [concurrency] 并发={c}: RPS={result.requests_per_second}, "
              f"P50={result.latency_ms['p50']}ms, "
              f"P95={result.latency_ms['p95']}ms, "
              f"错误率={error_rate:.1f}%", file=sys.stderr)

    # Skill 并发
    skill_scenarios = [
        ("skill_outreach", "Skill 同步执行"),
        ("skill_async_outreach", "Skill 异步提交"),
    ]
    for scenario_key, desc in skill_scenarios:
        for c in [1, 5, 10]:
            config = LoadTestConfig(
                base_url=base_url,
                scenario=scenario_key,
                concurrency=c,
                duration_seconds=15,
                ramp_up_seconds=2,
            )
            print(f"  [concurrency] {desc} 并发={c} ...", file=sys.stderr)
            result = run_load_test(config)
            error_rate = (result.failed_requests / max(result.total_requests, 1)) * 100
            results.append(ConcurrencyBaseline(
                scenario=scenario_key,
                concurrency=c,
                rps=result.requests_per_second,
                p50_ms=result.latency_ms["p50"],
                p95_ms=result.latency_ms["p95"],
                p99_ms=result.latency_ms["p99"],
                error_rate_pct=round(error_rate, 2),
            ))
            print(f"  [concurrency] {desc} 并发={c}: "
                  f"RPS={result.requests_per_second}, "
                  f"P50={result.latency_ms['p50']}ms", file=sys.stderr)

    return results


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def _probe_endpoint(base_url: str, path: str, timeout: float = 5) -> bool:
    """探测端点是否可用。"""
    try:
        req = urllib.request.Request(f"{base_url}{path}", method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        return False


def _detect_health_scenario(base_url: str) -> str:
    """检测可用的健康检查端点，返回 scenario key。"""
    # 优先使用 /livez（当前源码有此端点）
    if _probe_endpoint(base_url, "/livez"):
        return "livez"
    # 回退到 /v1/health（旧版本兼容）
    if _probe_endpoint(base_url, "/v1/health"):
        return "health"
    return "health"


def wait_for_service(base_url: str, timeout: float = 60) -> bool:
    """等待服务就绪。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        # 尝试 /livez 和 /v1/health
        for path in ["/livez", "/v1/health"]:
            if _probe_endpoint(base_url, path, timeout=5):
                return True
        time.sleep(1)
    return False


def run_full_benchmark(base_url: str, output_dir: str, port: int = 8100) -> dict:
    """执行完整 NFR 基准测试。"""
    print(f"[nfr] 等待服务就绪 {base_url} ...", file=sys.stderr)
    if not wait_for_service(base_url):
        print("[nfr] 服务未就绪，退出", file=sys.stderr)
        sys.exit(1)

    env_info = collect_env_info()
    print(f"[nfr] 环境: Python={env_info['python_version']} "
          f"CPU={env_info['cpu_count']} OS={env_info['os']}", file=sys.stderr)

    # 1. 延迟基线
    print("[nfr] === 延迟基线 ===", file=sys.stderr)
    latency_results = measure_latency_baseline(base_url, samples=100)

    # 2. 吞吐基线
    print("[nfr] === 吞吐基线 ===", file=sys.stderr)
    throughput_results = measure_throughput_baseline(base_url)

    # 3. 并发基线
    print("[nfr] === 并发基线 ===", file=sys.stderr)
    concurrency_results = measure_concurrency_baseline(base_url)

    # 4. 资源基线
    print("[nfr] === 资源基线 ===", file=sys.stderr)
    resource_results = measure_resource_baseline(base_url, port)

    # 汇总
    report = {
        "meta": {
            "project": "Leibniz-KERT (DKWS)",
            "milestone": "M2.10 NFR Baseline",
            "disclaimer": "基线值，非 SLA 承诺",
            "environment": env_info,
            "test_config": {
                "mode": "deterministic (no LLM keys)",
                "base_url": base_url,
                "latency_samples": 100,
                "throughput_concurrency": 10,
                "throughput_duration_seconds": 10,
                "concurrency_levels": [1, 10, 50, 100],
            },
        },
        "latency_baseline": [asdict(r) for r in latency_results],
        "throughput_baseline": [asdict(r) for r in throughput_results],
        "concurrency_baseline": [asdict(r) for r in concurrency_results],
        "resource_baseline": asdict(resource_results),
    }

    # 写入 JSON
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    json_path = out_path / "nfr_benchmark_results.json"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                         encoding="utf-8")
    print(f"[nfr] 结果已写入 {json_path}", file=sys.stderr)

    return report


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="DKWS NFR 基准测试框架")
    ap.add_argument("--base-url", default="http://localhost:8106",
                    help="服务基础 URL")
    ap.add_argument("--port", type=int, default=8106,
                    help="服务端口（用于资源监控）")
    ap.add_argument("--output-dir", default="evidence/m2-p6",
                    help="输出目录")
    args = ap.parse_args()

    report = run_full_benchmark(args.base_url, args.output_dir, args.port)

    # 摘要
    print("\n[nfr] ===== 基准测试摘要 =====", file=sys.stderr)
    for item in report["latency_baseline"]:
        lm = item["latency_ms"]
        print(f"  延迟 {item['description']}: "
              f"P50={lm['p50']}ms P95={lm['p95']}ms P99={lm['p99']}ms",
              file=sys.stderr)
    for item in report["throughput_baseline"]:
        print(f"  吞吐 {item['description']}: RPS={item['rps']}",
              file=sys.stderr)
    res = report["resource_baseline"]
    print(f"  资源: 空闲RSS={res['idle_rss_mb']}MB, "
          f"SQLite={res['sqlite_file_size_kb']}KB", file=sys.stderr)


if __name__ == "__main__":
    main()
