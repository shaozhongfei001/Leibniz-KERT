#!/usr/bin/env python3
"""HTTP 负载生成工具（M2.10 NFR 基线）。

功能：
- 可配置并发数、持续时间、请求类型
- 渐进加压模式（ramp-up）
- 结构化 JSON 报告输出
- 仅使用标准库（urllib.request），无需额外依赖

用法：
  python scripts/load_generator.py \
    --base-url http://localhost:8100 \
    --scenario livez \
    --concurrency 10 \
    --duration 30 \
    --ramp-up 5 \
    --output evidence/m2-p6/livez_load.json
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import threading
import time
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# 请求构造
# ---------------------------------------------------------------------------

SKILL_PAYLOADS: dict[str, dict] = {
    "outreach": {
        "skillId": "skill-customer-outreach-script",
        "request": {
            "customerId": "NFR-BENCH-C001",
            "structuredFacts": {"profile": {"name": "NFR测试客户"}},
        },
    },
    "meeting": {
        "skillId": "skill-customer-meeting-script",
        "request": {
            "customerId": "NFR-BENCH-C002",
            "structuredFacts": {"profile": {"name": "NFR测试客户"}},
        },
    },
    "previsit": {
        "skillId": "skill-customer-previsit-report",
        "request": {
            "customerId": "NFR-BENCH-C003",
            "structuredFacts": {"profile": {"name": "NFR测试客户"}},
        },
    },
}

SCENARIOS = {
    "livez": {"method": "GET", "path": "/livez"},
    "readyz": {"method": "GET", "path": "/readyz"},
    "health": {"method": "GET", "path": "/v1/health"},
    "skill_health": {"method": "GET", "path": "/api/skill/health"},
    "skill_outreach": {"method": "POST", "path": "/api/skill/execute",
                       "payload_key": "outreach"},
    "skill_meeting": {"method": "POST", "path": "/api/skill/execute",
                      "payload_key": "meeting"},
    "skill_previsit": {"method": "POST", "path": "/api/skill/execute",
                       "payload_key": "previsit"},
    "skill_async_outreach": {"method": "POST", "path": "/api/skill/execute",
                             "payload_key": "outreach", "async_run": True},
}


def _build_request(base_url: str, scenario: str) -> tuple[str, bytes | None, dict]:
    """构造 HTTP 请求，返回 (url, body_bytes, extra_headers)。"""
    cfg = SCENARIOS[scenario]
    url = f"{base_url}{cfg['path']}"
    body: bytes | None = None
    headers: dict[str, str] = {}

    if cfg["method"] == "POST":
        payload = dict(SKILL_PAYLOADS.get(cfg.get("payload_key"), {}))
        if cfg.get("async_run"):
            payload["async"] = True
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"

    return url, body, headers


# ---------------------------------------------------------------------------
# 单次请求
# ---------------------------------------------------------------------------

@dataclass
class RequestResult:
    """单次 HTTP 请求结果。"""
    success: bool
    status_code: int
    latency_ms: float
    error: str = ""


def _do_request(base_url: str, scenario: str, timeout: float = 30.0) -> RequestResult:
    """执行单次 HTTP 请求并记录延迟。"""
    url, body, headers = _build_request(base_url, scenario)
    method = SCENARIOS[scenario]["method"]
    req = urllib.request.Request(url, data=body, headers=headers, method=method)

    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            _ = resp.read()
        latency_ms = (time.monotonic() - t0) * 1000
        return RequestResult(success=True, status_code=resp.status,
                             latency_ms=round(latency_ms, 2))
    except urllib.error.HTTPError as exc:
        latency_ms = (time.monotonic() - t0) * 1000
        return RequestResult(success=False, status_code=exc.code,
                             latency_ms=round(latency_ms, 2),
                             error=str(exc))
    except Exception as exc:
        latency_ms = (time.monotonic() - t0) * 1000
        return RequestResult(success=False, status_code=0,
                             latency_ms=round(latency_ms, 2),
                             error=str(exc))


# ---------------------------------------------------------------------------
# 负载生成
# ---------------------------------------------------------------------------

@dataclass
class LoadTestConfig:
    """负载测试配置。"""
    base_url: str
    scenario: str
    concurrency: int = 10
    duration_seconds: float = 30.0
    ramp_up_seconds: float = 0.0
    timeout: float = 30.0


@dataclass
class LoadTestResult:
    """负载测试结果。"""
    scenario: str
    concurrency: int
    duration_seconds: float
    ramp_up_seconds: float
    total_requests: int
    successful_requests: int
    failed_requests: int
    requests_per_second: float
    latency_ms: dict[str, float]  # p50, p90, p95, p99, min, max, mean, stdev
    status_codes: dict[str, int]
    errors: list[str]
    started_at: str = ""
    finished_at: str = ""


def _percentile(sorted_data: list[float], pct: float) -> float:
    """计算百分位数。"""
    if not sorted_data:
        return 0.0
    idx = (pct / 100.0) * (len(sorted_data) - 1)
    lo = int(idx)
    hi = min(lo + 1, len(sorted_data) - 1)
    frac = idx - lo
    return round(sorted_data[lo] + frac * (sorted_data[hi] - sorted_data[lo]), 2)


def run_load_test(config: LoadTestConfig) -> LoadTestResult:
    """执行负载测试。"""
    from datetime import datetime, timezone

    results: list[RequestResult] = []
    lock = threading.Lock()
    stop_event = threading.Event()

    started_at = datetime.now(timezone.utc).isoformat()

    def _worker(worker_id: int, start_delay: float):
        """工作线程：在 start_delay 后开始发请求，直到 stop_event。"""
        if start_delay > 0:
            time.sleep(start_delay)
        while not stop_event.is_set():
            r = _do_request(config.base_url, config.scenario, config.timeout)
            with lock:
                results.append(r)
            # 微小间隔避免纯 busy-loop
            if not stop_event.is_set():
                time.sleep(0.001)

    # 启动工作线程
    with ThreadPoolExecutor(max_workers=config.concurrency) as pool:
        futures = []
        for i in range(config.concurrency):
            # 渐进加压：均匀分布在 ramp_up_seconds 内
            delay = (i * config.ramp_up_seconds / max(config.concurrency - 1, 1)
                     if config.ramp_up_seconds > 0 and config.concurrency > 1 else 0)
            futures.append(pool.submit(_worker, i, delay))

        # 等待指定持续时间
        time.sleep(config.duration_seconds)
        stop_event.set()

        # 等待所有线程结束
        for f in as_completed(futures, timeout=60):
            try:
                f.result()
            except Exception:
                pass

    finished_at = datetime.now(timezone.utc).isoformat()

    # 统计
    latencies = sorted(r.latency_ms for r in results if r.success)
    status_codes: dict[str, int] = {}
    errors_set: set[str] = set()
    for r in results:
        key = str(r.status_code)
        status_codes[key] = status_codes.get(key, 0) + 1
        if r.error:
            # 去重错误信息，保留前 10 条
            errors_set.add(r.error[:200])

    successful = sum(1 for r in results if r.success)
    actual_duration = config.duration_seconds

    latency_stats = {
        "p50": _percentile(latencies, 50),
        "p90": _percentile(latencies, 90),
        "p95": _percentile(latencies, 95),
        "p99": _percentile(latencies, 99),
        "min": latencies[0] if latencies else 0,
        "max": latencies[-1] if latencies else 0,
        "mean": round(statistics.mean(latencies), 2) if latencies else 0,
        "stdev": round(statistics.stdev(latencies), 2) if len(latencies) > 1 else 0,
    }

    return LoadTestResult(
        scenario=config.scenario,
        concurrency=config.concurrency,
        duration_seconds=config.duration_seconds,
        ramp_up_seconds=config.ramp_up_seconds,
        total_requests=len(results),
        successful_requests=successful,
        failed_requests=len(results) - successful,
        requests_per_second=round(successful / actual_duration, 2) if actual_duration > 0 else 0,
        latency_ms=latency_stats,
        status_codes=status_codes,
        errors=list(errors_set)[:10],
        started_at=started_at,
        finished_at=finished_at,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="DKWS HTTP 负载生成工具")
    ap.add_argument("--base-url", default="http://localhost:8106",
                    help="服务基础 URL（默认 http://localhost:8106）")
    ap.add_argument("--scenario", required=True, choices=SCENARIOS.keys(),
                    help="测试场景")
    ap.add_argument("--concurrency", type=int, default=10,
                    help="并发数（默认 10）")
    ap.add_argument("--duration", type=float, default=30.0,
                    help="持续时间（秒，默认 30）")
    ap.add_argument("--ramp-up", type=float, default=0.0,
                    help="渐进加压时间（秒，默认 0 即立即全量）")
    ap.add_argument("--timeout", type=float, default=30.0,
                    help="单请求超时（秒，默认 30）")
    ap.add_argument("--output", default=None,
                    help="输出 JSON 文件路径（默认 stdout）")
    args = ap.parse_args()

    config = LoadTestConfig(
        base_url=args.base_url,
        scenario=args.scenario,
        concurrency=args.concurrency,
        duration_seconds=args.duration,
        ramp_up_seconds=args.ramp_up,
        timeout=args.timeout,
    )

    print(f"[load-gen] 场景={args.scenario} 并发={args.concurrency} "
          f"持续={args.duration}s 加压={args.ramp_up}s", file=sys.stderr)

    result = run_load_test(config)

    output = json.dumps(asdict(result), ensure_ascii=False, indent=2)

    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(output, encoding="utf-8")
        print(f"[load-gen] 结果已写入 {args.output}", file=sys.stderr)
    else:
        print(output)

    # 摘要
    print(f"[load-gen] 完成: {result.total_requests} 请求, "
          f"{result.successful_requests} 成功, "
          f"RPS={result.requests_per_second}, "
          f"P50={result.latency_ms['p50']}ms, "
          f"P95={result.latency_ms['p95']}ms, "
          f"P99={result.latency_ms['p99']}ms",
          file=sys.stderr)


if __name__ == "__main__":
    main()
