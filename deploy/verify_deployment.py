#!/usr/bin/env python3
"""DKWS 部署验证脚本（M2.7）。

验证 docker-compose up 后服务是否健康：
  - /livez  存活探针
  - /readyz 就绪探针
  - /metrics 指标端点

用法：
    # 默认检查 localhost:8106
    python deploy/verify_deployment.py

    # 自定义地址
    python deploy/verify_deployment.py --base-url http://192.168.1.10:8106

    # 自定义超时与重试
    python deploy/verify_deployment.py --timeout 60 --interval 5

退出码：
    0  全部通过
    1  部分检查失败
    2  参数错误或不可恢复错误
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
import urllib.error
from dataclasses import dataclass


@dataclass
class CheckResult:
    """单项检查结果。"""
    name: str
    passed: bool
    status_code: int | None
    detail: str


def http_get(url: str, timeout: float = 5.0) -> tuple[int, str]:
    """发起 HTTP GET，返回 (status_code, body_text)。"""
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return resp.status, body
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        return exc.code, body
    except urllib.error.URLError as exc:
        return 0, str(exc.reason)
    except OSError as exc:
        return 0, str(exc)


def check_endpoint(
    base_url: str,
    path: str,
    expected_status: int = 200,
    timeout: float = 5.0,
    keyword: str | None = None,
) -> CheckResult:
    """检查单个 HTTP 端点。"""
    url = f"{base_url.rstrip('/')}{path}"
    status, body = http_get(url, timeout=timeout)

    passed = status == expected_status
    detail = f"HTTP {status}" if status else f"连接失败: {body[:120]}"

    if passed and keyword and keyword not in body:
        passed = False
        detail = f"HTTP {status} 但响应缺少关键词 '{keyword}'"

    return CheckResult(
        name=path,
        passed=passed,
        status_code=status,
        detail=detail,
    )


def wait_for_service(
    base_url: str,
    timeout: float = 60.0,
    interval: float = 3.0,
) -> bool:
    """等待服务可达（/livez 返回非连接错误）。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status, _ = http_get(f"{base_url.rstrip('/')}/livez", timeout=5.0)
        if status > 0:
            return True
        remaining = deadline - time.monotonic()
        if remaining > 0:
            time.sleep(min(interval, remaining))
    return False


def main() -> int:
    """入口。"""
    parser = argparse.ArgumentParser(
        description="验证 DKWS 部署健康状态")
    parser.add_argument(
        "--base-url", default="http://localhost:8106",
        help="API 服务基础 URL（默认 http://localhost:8106）")
    parser.add_argument(
        "--timeout", type=float, default=60.0,
        help="等待服务启动的最大秒数（默认 60）")
    parser.add_argument(
        "--interval", type=float, default=3.0,
        help="等待期间重试间隔秒数（默认 3）")
    parser.add_argument(
        "--skip-wait", action="store_true",
        help="跳过等待服务启动，直接检查")
    args = parser.parse_args()

    base_url = args.base_url

    # 阶段 1：等待服务可达
    if not args.skip_wait:
        print(f"[verify] 等待服务可达 {base_url}（超时 {args.timeout}s）…")
        if not wait_for_service(base_url, timeout=args.timeout, interval=args.interval):
            print("[verify] 服务在超时内未启动，退出", file=sys.stderr)
            return 1
        print("[verify] 服务已可达")
    else:
        print("[verify] 跳过等待，直接检查")

    # 阶段 2：逐项检查
    checks: list[CheckResult] = []

    # /livez — 存活探针，期望 200，响应含 status
    checks.append(check_endpoint(
        base_url, "/livez",
        expected_status=200, keyword="status"))

    # /readyz — 就绪探针，期望 200 或 503（降级但不死）
    readyz_result = check_endpoint(base_url, "/readyz")
    if readyz_result.status_code in (200, 503):
        readyz_result.passed = True
        readyz_result.detail = f"HTTP {readyz_result.status_code}"
        # 503 时解析降级信息
        if readyz_result.status_code == 503:
            try:
                body_json = json.loads(
                    http_get(f"{base_url}/readyz")[1])
                degraded = body_json.get("degraded", [])
                if degraded:
                    readyz_result.detail += f" 降级项: {degraded}"
            except (json.JSONDecodeError, ValueError):
                pass
    checks.append(readyz_result)

    # /metrics — 指标端点，期望 200 或 401（需 admin 密钥）
    metrics_result = check_endpoint(base_url, "/metrics")
    if metrics_result.status_code in (200, 401):
        metrics_result.passed = True
        if metrics_result.status_code == 401:
            metrics_result.detail = "HTTP 401（需 admin 密钥，属正常行为）"
    checks.append(metrics_result)

    # 汇总
    print()
    print("=" * 60)
    print("DKWS 部署验证报告")
    print("=" * 60)
    all_passed = True
    for c in checks:
        icon = "PASS" if c.passed else "FAIL"
        print(f"  [{icon}] {c.name}: {c.detail}")
        if not c.passed:
            all_passed = False
    print("=" * 60)

    if all_passed:
        print("结果：全部通过")
        return 0
    else:
        print("结果：存在失败项", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
