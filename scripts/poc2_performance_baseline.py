#!/usr/bin/env python3
"""生成 POC-2 性能基线（baseline measurement，非 NFR 达标声明）。

重要约束（施工令第十一节 §7）：
- 没有 Owner 批准的 NFR 时，本脚本只产出 **baseline measurement**，
  不得据此宣布「性能达标」。
- 未实际执行的项目一律标 NOT_EXECUTED / BLOCKED，不得填估算值。

当前可测项：
- Maven 构建与测试耗时（从构建日志提取）
- Sandbox 启动与执行延迟（真实 bwrap 调用，多次采样取 P50/P95/P99）
- JVM 启动时间（Runtime 未接入 Core，故通过 Spring Boot 启动实测或标 NOT_EXECUTED）

暂不可测项（依赖尚未实现的 Core->Runtime 集成）：
- Python Core -> Java Runtime 额外延迟
- 单次 read_skill / ToolCall 端到端延迟
- 最大安全并发、排队行为
"""

from __future__ import annotations

import importlib.util
import json
import platform
import re
import statistics
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = REPO_ROOT / "poc" / "spring-ai-alibaba-skill-runtime" / "sandbox" / "bwrap_runner.py"
BUILD_LOG = REPO_ROOT / "evidence" / "poc2" / "unit-tests.log"
OUTPUT = REPO_ROOT / "evidence" / "poc2" / "performance-baseline.json"

SAMPLES = 20


def _load_runner():
    spec = importlib.util.spec_from_file_location("dkws_bwrap_runner", RUNNER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _percentiles(values: list[float]) -> dict[str, float]:
    if not values:
        return {}
    ordered = sorted(values)

    def pick(p: float) -> float:
        idx = min(int(round(p / 100 * (len(ordered) - 1))), len(ordered) - 1)
        return round(ordered[idx], 3)

    return {
        "count": len(ordered),
        "minMs": round(ordered[0], 3),
        "maxMs": round(ordered[-1], 3),
        "meanMs": round(statistics.fmean(ordered), 3),
        "p50Ms": pick(50),
        "p95Ms": pick(95),
        "p99Ms": pick(99),
    }


def measure_sandbox() -> dict:
    runner = _load_runner()
    if not runner.backend_available():
        return {
            "status": "NOT_EXECUTED",
            "reason": "bwrap not available in this environment",
        }

    root = Path("/tmp/dkws-perf-sandbox")
    root.mkdir(parents=True, exist_ok=True)

    startup: list[float] = []
    for _ in range(SAMPLES):
        began = time.perf_counter()
        result = runner.run(
            {"executable": "python3", "argv": ["-I", "-c", "pass"]},
            sandbox_root=root,
        )
        elapsed = (time.perf_counter() - began) * 1000
        if result["status"] != "ok":
            return {"status": "FAILED", "reason": result.get("stderr", "")[:500]}
        startup.append(elapsed)

    workload: list[float] = []
    for _ in range(SAMPLES):
        began = time.perf_counter()
        result = runner.run(
            {"executable": "python3", "argv": ["-I", "-c", "sum(range(200000))"]},
            sandbox_root=root,
        )
        workload.append((time.perf_counter() - began) * 1000)
        if result["status"] != "ok":
            return {"status": "FAILED", "reason": result.get("stderr", "")[:500]}

    return {
        "status": "MEASURED",
        "backend": runner.SANDBOX_BACKEND,
        "sandboxStartupNoop": _percentiles(startup),
        "sandboxSmallWorkload": _percentiles(workload),
    }


def measure_build() -> dict:
    if not BUILD_LOG.is_file():
        return {"status": "NOT_EXECUTED", "reason": f"{BUILD_LOG} missing"}
    text = BUILD_LOG.read_text(encoding="utf-8", errors="replace")

    total = re.search(r"Total time:\s+([0-9:.]+)\s*(min|s)?", text)
    tests = re.search(r"Tests run:\s*(\d+), Failures:\s*(\d+), Errors:\s*(\d+), Skipped:\s*(\d+)", text)

    build_seconds = None
    if total:
        raw, unit = total.group(1), total.group(2)
        if ":" in raw:
            mins, secs = raw.split(":")
            build_seconds = int(mins) * 60 + float(secs)
        else:
            build_seconds = float(raw) * (60 if unit == "min" else 1)

    return {
        "status": "MEASURED" if build_seconds is not None else "NOT_EXECUTED",
        "cleanTestSeconds": build_seconds,
        "testsRun": int(tests.group(1)) if tests else None,
        "testsFailed": int(tests.group(2)) + int(tests.group(3)) if tests else None,
        "testsSkipped": int(tests.group(4)) if tests else None,
    }


def measure_java_startup() -> dict:
    """JVM 版本探测；Spring Boot 完整启动未纳入（Runtime 尚未接入 Core）。"""
    try:
        proc = subprocess.run(["java", "-version"], capture_output=True, text=True, timeout=30)
        version = (proc.stderr or proc.stdout).strip().splitlines()[0]
    except (OSError, subprocess.SubprocessError) as exc:
        return {"status": "NOT_EXECUTED", "reason": str(exc)}

    return {
        "status": "PARTIAL",
        "javaVersion": version,
        "springBootStartupMs": None,
        "jvmHeapAtIdleBytes": None,
        "note": (
            "Spring Boot 冷启动、JVM heap、空闲内存需在 Runtime 以生产 profile "
            "独立进程运行时测量；本轮 Runtime 未接入 Core，标记 NOT_EXECUTED。"
        ),
    }


def main() -> int:
    baseline = {
        "kind": "BASELINE_MEASUREMENT",
        "disclaimer": (
            "本文件仅为基线测量，不构成性能达标声明。Owner 未批准 NFR 前"
            "不得据此宣布 PRODUCTION_READY 或性能通过。"
        ),
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "environment": {
            "platform": platform.platform(),
            "python": sys.version.split()[0],
            "cpuCount": __import__("os").cpu_count(),
        },
        "measurements": {
            "javaRuntime": measure_java_startup(),
            "mavenBuild": measure_build(),
            "osSandbox": measure_sandbox(),
        },
        "notExecuted": {
            "coreToRuntimeLatency": "BLOCKED: Python Core -> Java Runtime 集成未实现（C-B04 未关闭）",
            "readSkillLatency": "NOT_EXECUTED: 需要真实模型与运行中的 Runtime 实例",
            "toolCallLatency": "NOT_EXECUTED: ToolCall receipt 拦截器未实现",
            "skillRegistryReload": "NOT_EXECUTED: 需要运行中的 Runtime 实例",
            "maxSafeConcurrency": "NOT_EXECUTED: 未做并发压测，禁止估算",
            "queueingBehavior": "NOT_EXECUTED: 无异步队列接入",
        },
    }

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(baseline, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(baseline, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
