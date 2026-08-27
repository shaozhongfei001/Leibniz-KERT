#!/usr/bin/env python3
"""M2-P3 端到端验收：可观测性（M2.5）在真实 uvicorn 进程下的采集验证。

验收标准（Owner）：指标与日志可采集，/livez、/readyz、/metrics 可用。

验证内容：
1. 三端点在真实进程下可用且状态码正确
2. /metrics 输出合法 Prometheus 文本格式（可被采集器解析）
3. HTTP 指标含 method/path/status 标签与延迟直方图
4. 路径标签使用路由模板（无高基数泄漏）
5. 队列指标随 Runtime Store 暴露
6. 结构化日志为单行 JSON 且含 request_id/trace_id
7. W3C Trace Context 贯通（沿用上游 trace、生成新 span）
8. 日志与指标对被拒请求同样可观测（4xx 无盲区）
9. 密钥不出现在日志中（脱敏生效）
10. 探针与指标不被限流拦截
11. 生产 profile 下三端点仍可访问

用法：
    python scripts/verify_m2p3_observability.py [--out evidence/m2-p3]
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "src"
PORT = 18733
BASE = f"http://127.0.0.1:{PORT}"

NORMAL_KEY = "m2p3-normal-key-0123456789"
ADMIN_KEY = "m2p3-admin-key-0123456789"
VALID_TRACE = "abcdef0123456789abcdef0123456789"
VALID_SPAN = "fedcba9876543210"


def _log(report: dict, name: str, passed: bool, detail: str) -> None:
    """记录一条检查结果。"""
    report["checks"].append({"name": name, "passed": bool(passed), "detail": detail})
    print(f"[{'PASS' if passed else 'FAIL'}] {name} :: {detail}", flush=True)


def _init_workspace(root: Path) -> Path:
    """初始化真实工作区。"""
    sys.path.insert(0, str(SRC))
    from dkws.domain import workspace as ws_mod

    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    ws_mod.init_workspace(root)
    return root


def _request(method: str, path: str, *, key: str | None = None,
             headers: dict | None = None) -> tuple[int, dict, str]:
    """发送 HTTP 请求，返回 (状态码, 小写响应头, 响应体)。"""
    req_headers = dict(headers or {})
    if key:
        req_headers["X-API-Key"] = key
    req = urllib.request.Request(f"{BASE}{path}", headers=req_headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return (resp.status, {k.lower(): v for k, v in dict(resp.headers).items()},
                    resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return (exc.code, {k.lower(): v for k, v in dict(exc.headers).items()},
                exc.read().decode("utf-8"))


def _wait_ready(proc: subprocess.Popen, timeout: float = 40.0) -> bool:
    """轮询 /livez 直到服务就绪。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc.poll() is not None:
            return False
        try:
            with urllib.request.urlopen(f"{BASE}/livez", timeout=2) as resp:
                if resp.status == 200:
                    return True
        except (urllib.error.URLError, OSError):
            time.sleep(0.3)
    return False


def _server_env(profile: str = "dev") -> dict[str, str]:
    """构造服务端环境变量。"""
    env = dict(os.environ)
    env.update({
        "PYTHONPATH": str(SRC),
        "DKWS_PROFILE": profile,
        "DKWS_BIND_HOST": "127.0.0.1",
        "DKWS_API_KEYS": (f"svc:{NORMAL_KEY}:read|execute,"
                          f"ops:{ADMIN_KEY}:read|execute|admin"),
        "DKWS_RATE_LIMIT_ENABLED": "true",
        "DKWS_RATE_LIMIT_RPM": "60",
        "DKWS_RATE_LIMIT_BURST": "3",
        "DKWS_RUNTIME_STORE_ENABLED": "true",
        "DKWS_STRUCTURED_LOGS": "true",
        "DKWS_LOG_LEVEL": "INFO",
        "DKWS_METRICS_ENABLED": "true",
        "DKWS_TRACING_ENABLED": "true",
    })
    env.pop("DKWS_LLM_API_KEY", None)
    return env


def _parse_prometheus(text: str) -> dict:
    """极简 Prometheus 文本解析，用于验证可被采集器消费。"""
    samples: dict[str, list[tuple[str, float]]] = {}
    helps: set[str] = set()
    types: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("# HELP "):
            helps.add(line.split()[2])
            continue
        if line.startswith("# TYPE "):
            parts = line.split()
            types[parts[2]] = parts[3]
            continue
        if line.startswith("#"):
            continue
        m = re.match(r"^([a-zA-Z_:][a-zA-Z0-9_:]*)(\{[^}]*\})?\s+(-?[\d.eE+]+|NaN)$", line)
        if m is None:
            raise ValueError(f"非法曝光行：{line!r}")
        name, labels, raw = m.group(1), m.group(2) or "", m.group(3)
        samples.setdefault(name, []).append((labels, float(raw)))
    return {"samples": samples, "helps": helps, "types": types}


def check_endpoints(report: dict) -> None:
    """场景 1：三端点可用。"""
    status, _, body = _request("GET", "/livez")
    payload = json.loads(body) if status == 200 else {}
    _log(report, "livez_available",
         status == 200 and payload.get("status") == "alive",
         f"GET /livez → {status}，status={payload.get('status')}，"
         f"uptime={payload.get('uptime_seconds')}s")

    status, _, body = _request("GET", "/readyz")
    payload = json.loads(body)
    _log(report, "readyz_available",
         status in (200, 503) and "checks" in payload,
         f"GET /readyz → {status}，status={payload.get('status')}，"
         f"检查项={sorted(payload.get('checks', {}))}")

    status, headers, body = _request("GET", "/metrics")
    _log(report, "metrics_available",
         status == 200 and "text/plain" in headers.get("content-type", ""),
         f"GET /metrics → {status}，content-type={headers.get('content-type')}")


def check_prometheus_format(report: dict) -> None:
    """场景 2-5：指标格式与内容。"""
    _request("GET", "/livez")
    _request("GET", "/readyz")
    _, _, body = _request("GET", "/metrics")
    try:
        parsed = _parse_prometheus(body)
        ok = True
        detail = (f"解析成功：{len(parsed['samples'])} 个指标名，"
                  f"{len(parsed['types'])} 个 TYPE 声明")
    except ValueError as exc:
        parsed = {"samples": {}, "types": {}}
        ok = False
        detail = f"解析失败：{exc}"
    _log(report, "metrics_parseable_by_collector", ok, detail)

    samples = parsed["samples"]
    _log(report, "metrics_http_requests_labeled",
         any('method="GET"' in lbl and 'status=' in lbl
             for lbl, _ in samples.get("dkws_http_requests_total", [])),
         f"dkws_http_requests_total 含 method/path/status 标签，"
         f"样本数={len(samples.get('dkws_http_requests_total', []))}")

    _log(report, "metrics_latency_histogram",
         "dkws_http_request_duration_seconds_bucket" in samples
         and "dkws_http_request_duration_seconds_count" in samples
         and "dkws_http_request_duration_seconds_sum" in samples,
         "延迟直方图含 _bucket/_count/_sum 三件套")

    _log(report, "metrics_histogram_type_declared",
         parsed["types"].get("dkws_http_request_duration_seconds") == "histogram",
         f"TYPE 声明={parsed['types'].get('dkws_http_request_duration_seconds')}")

    # 高基数验证：访问带路径参数的端点，标签应为模板
    for oid in ("E2E-OBJ-1", "E2E-OBJ-2", "E2E-OBJ-3"):
        _request("GET", f"/v1/evidence/{oid}", key=NORMAL_KEY)
    _, _, body = _request("GET", "/metrics")
    _log(report, "metrics_no_high_cardinality",
         "{object_id}" in body and "E2E-OBJ-1" not in body,
         "路径标签使用路由模板 {object_id}，未泄漏具体 ID（避免标签爆炸）")

    _log(report, "metrics_queue_gauges",
         all(k in body for k in ("dkws_job_queue_claimable",
                                 "dkws_job_queue_dead_letter",
                                 "dkws_job_queue_expired_leases")),
         "队列深度指标已暴露（claimable/dead_letter/expired_leases）")

    _log(report, "metrics_build_info",
         "dkws_build_info" in body and "dkws_process_uptime_seconds" in body,
         "构建信息与运行时长指标已暴露")


def check_trace_context(report: dict) -> None:
    """场景 7：W3C Trace Context 贯通。"""
    _, headers, _ = _request("GET", "/livez")
    request_id = headers.get("x-request-id", "")
    traceparent = headers.get("traceparent", "")
    _log(report, "trace_headers_returned",
         request_id.startswith("REQ-") and traceparent.startswith("00-"),
         f"X-Request-Id={request_id[:20]}…，traceparent={traceparent[:24]}…")

    _, headers, _ = _request("GET", "/livez",
                             headers={"X-Request-Id": "E2E-CALLER-ID"})
    _log(report, "trace_request_id_preserved",
         headers.get("x-request-id") == "E2E-CALLER-ID",
         "沿用调用方 X-Request-Id，便于跨系统关联")

    incoming = f"00-{VALID_TRACE}-{VALID_SPAN}-01"
    _, headers, _ = _request("GET", "/livez", headers={"traceparent": incoming})
    returned = headers.get("traceparent", "").split("-")
    _log(report, "trace_continues_upstream",
         len(returned) == 4 and returned[1] == VALID_TRACE and returned[2] != VALID_SPAN,
         f"沿用上游 trace_id，生成新 span_id={returned[2] if len(returned) > 2 else '?'}")

    _, headers, _ = _request("GET", "/livez", headers={"traceparent": "malformed"})
    new_trace = headers.get("traceparent", "").split("-")
    _log(report, "trace_rejects_malformed",
         len(new_trace) == 4 and len(new_trace[1]) == 32 and new_trace[1] != "malformed",
         "畸形 traceparent 被拒并新建 trace，不污染链路")


def check_observability_no_blindspot(report: dict) -> None:
    """场景 8：被拒请求同样可观测。"""
    status, _, _ = _request("GET", "/v1/catalog")
    _, _, body = _request("GET", "/metrics")
    _log(report, "rejected_requests_observable",
         status == 401 and 'status="401"' in body
         and "dkws_http_client_errors_total" in body,
         f"未认证请求 → {status}，指标含 status=\"401\" 与 4xx 计数"
         f"（可观测性无盲区）")


def check_rate_limit_exemption(report: dict) -> None:
    """场景 10：探针与指标不被限流。"""
    codes = [_request("GET", "/livez")[0] for _ in range(6)]
    _log(report, "probes_exempt_from_rate_limit",
         all(c == 200 for c in codes),
         f"连续 6 次 /livez 状态码={codes}（burst=3 仍全通过）")
    codes = [_request("GET", "/metrics")[0] for _ in range(5)]
    _log(report, "metrics_exempt_from_rate_limit",
         all(c == 200 for c in codes),
         f"连续 5 次 /metrics 状态码={codes}")


def check_structured_logs(report: dict, log_path: Path) -> None:
    """场景 6、9：结构化日志格式与脱敏。"""
    text = log_path.read_text(encoding="utf-8", errors="replace")
    json_lines: list[dict] = []
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            json_lines.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    _log(report, "logs_are_single_line_json", len(json_lines) > 0,
         f"捕获 {len(json_lines)} 条单行 JSON 日志")

    access = [r for r in json_lines if r.get("event_code") == "HTTP_ACCESS"]
    _log(report, "logs_have_access_events", len(access) > 0,
         f"访问日志 {len(access)} 条，事件码 HTTP_ACCESS")

    if access:
        sample = access[-1]
        _log(report, "logs_have_correlation_fields",
             bool(sample.get("request_id")) and bool(sample.get("trace_id")),
             f"含关联字段 request_id/trace_id（示例 status={sample.get('status')}，"
             f"duration_ms={sample.get('duration_ms')}）")
        _log(report, "logs_have_service_field",
             sample.get("service") == "dkws-python-core",
             f"service={sample.get('service')}")
    else:
        _log(report, "logs_have_correlation_fields", False, "无访问日志可校验")
        _log(report, "logs_have_service_field", False, "无访问日志可校验")

    leaked = [k for k in (NORMAL_KEY, ADMIN_KEY) if k in text]
    _log(report, "logs_do_not_leak_api_keys", not leaked,
         "日志中未出现任何 API Key 明文" if not leaked else f"泄漏：{leaked}")


def check_prod_profile(report: dict, workspace: Path, log_dir: Path) -> None:
    """场景 11：生产 profile 下三端点仍可访问。"""
    log_path = log_dir / "02_prod_server.log"
    with log_path.open("w", encoding="utf-8") as log_file:
        proc = subprocess.Popen(
            [sys.executable, str(REPO / "scripts" / "serve_skill_service.py"),
             "--workspace", str(workspace), "--port", str(PORT), "--host", "127.0.0.1"],
            env=_server_env("prod"), stdout=log_file, stderr=subprocess.STDOUT)
        try:
            ready = _wait_ready(proc)
            if not ready:
                _log(report, "prod_profile_probes_public", False,
                     "生产 profile 服务未就绪，见 02_prod_server.log")
                return
            results = {p: _request("GET", p)[0] for p in ("/livez", "/readyz", "/metrics")}
            _log(report, "prod_profile_probes_public",
                 results["/livez"] == 200 and results["/readyz"] in (200, 503)
                 and results["/metrics"] == 200,
                 f"生产 profile 下匿名访问：{results}（探针不被 401 拦截）")
            status, _, _ = _request("GET", "/v1/catalog")
            _log(report, "prod_profile_business_still_protected", status == 401,
                 f"业务端点仍要求认证 → {status}")
        finally:
            if proc.poll() is None:
                proc.send_signal(signal.SIGTERM)
                try:
                    proc.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    proc.kill()


def main() -> int:
    """执行全部验证并写出报告。"""
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(REPO / "evidence" / "m2-p3"))
    ap.add_argument("--workspace", default="/tmp/dkws-m2p3-e2e-ws")
    args = ap.parse_args()

    out_dir = Path(args.out)
    log_dir = out_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    workspace = _init_workspace(Path(args.workspace))

    report: dict = {
        "task_package": "M2-P3",
        "scope": "M2.5 可观测性（结构化日志 / livez / readyz / metrics / 追踪）",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "environment": {"python": sys.version.split()[0],
                        "platform": platform.platform(),
                        "workspace": str(workspace)},
        "checks": [],
    }

    log_path = log_dir / "01_dev_server.log"
    with log_path.open("w", encoding="utf-8") as log_file:
        proc = subprocess.Popen(
            [sys.executable, str(REPO / "scripts" / "serve_skill_service.py"),
             "--workspace", str(workspace), "--port", str(PORT), "--host", "127.0.0.1"],
            env=_server_env("dev"), stdout=log_file, stderr=subprocess.STDOUT)
        try:
            if not _wait_ready(proc):
                _log(report, "server_starts", False, "服务未就绪，见 01_dev_server.log")
            else:
                _log(report, "server_starts", True,
                     f"服务在 127.0.0.1:{PORT} 就绪（结构化日志已启用）")
                check_endpoints(report)
                check_prometheus_format(report)
                check_trace_context(report)
                check_observability_no_blindspot(report)
                check_rate_limit_exemption(report)
        finally:
            if proc.poll() is None:
                proc.send_signal(signal.SIGTERM)
                try:
                    proc.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    proc.kill()

    check_structured_logs(report, log_path)
    check_prod_profile(report, workspace, log_dir)

    passed = sum(1 for c in report["checks"] if c["passed"])
    total = len(report["checks"])
    report["summary"] = {"passed": passed, "total": total,
                         "result": "PASS" if passed == total else "FAIL"}
    (out_dir / "e2e_observability_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n=== {passed}/{total} 项检查通过 → {report['summary']['result']} ===")
    print(f"报告：{out_dir / 'e2e_observability_report.json'}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
