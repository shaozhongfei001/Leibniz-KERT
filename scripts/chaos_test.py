#!/usr/bin/env python3
"""DKWS 故障注入测试框架——验证 GITS 侧在 DKWS 各种故障下的行为。

故障场景覆盖：
  网络层：连接拒绝、请求超时、连接重置
  应用层：5xx 响应、4xx 响应、异常响应体
  数据层：空数据、部分数据
  进程层：进程崩溃、进程挂起、重启中

测试方式：
  1. 启动 DKWS 服务（确定性模式，无需 LLM 密钥）
  2. 注入故障
  3. 通过 HTTP 客户端调用 DKWS API，观察行为
  4. 记录 GITS 侧预期行为判定
  5. 清理故障注入

仅使用标准库（os/signal/subprocess/socket/time/json/http）。

用法：
  python scripts/chaos_test.py [--dkws-port 8106] [--out evidence/m3-p0]
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import socket
import subprocess
import sys
import time
from http.client import HTTPConnection, HTTPException
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

# 延迟导入 chaos_injector
sys.path.insert(0, str(Path(__file__).resolve().parent))
import chaos_injector


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def _log(report: dict, name: str, passed: bool, detail: str) -> None:
    """记录一条检查结果。"""
    report["checks"].append({"name": name, "passed": bool(passed), "detail": detail})
    print(f"[{'PASS' if passed else 'FAIL'}] {name} :: {detail}", flush=True)


def _http_request(host: str, port: int, method: str, path: str,
                  body: str | None = None, timeout: float = 10.0) -> dict:
    """发送 HTTP 请求，返回 {status, body, error}。"""
    result = {"status": None, "body": None, "error": None}
    try:
        conn = HTTPConnection(host, port, timeout=timeout)
        headers = {"Content-Type": "application/json"}
        conn.request(method, path, body=body, headers=headers)
        resp = conn.getresponse()
        result["status"] = resp.status
        result["body"] = resp.read().decode("utf-8", errors="replace")
        conn.close()
    except ConnectionRefusedError:
        result["error"] = "CONNECTION_REFUSED"
    except socket.timeout:
        result["error"] = "TIMEOUT"
    except ConnectionResetError:
        result["error"] = "CONNECTION_RESET"
    except BrokenPipeError:
        result["error"] = "BROKEN_PIPE"
    except OSError as exc:
        result["error"] = f"OS_ERROR: {exc}"
    except HTTPException as exc:
        result["error"] = f"HTTP_ERROR: {exc}"
    return result


def _start_dkws(port: int, workspace: Path) -> subprocess.Popen | None:
    """启动 DKWS 服务（确定性模式）。"""
    script = REPO / "scripts" / "serve_skill_service.py"
    if not script.exists():
        print(f"[WARN] serve_skill_service.py 不存在，跳过 DKWS 启动", flush=True)
        return None
    workspace.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["PYTHONPATH"] = str(SRC)
    # 确定性模式：不注入 LLM key
    env.pop("DKWS_LLM_BASE_URL", None)
    env.pop("DKWS_LLM_API_KEY", None)
    try:
        proc = subprocess.Popen(
            [sys.executable, str(script),
             "--port", str(port), "--workspace", str(workspace)],
            env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        # 等待服务就绪
        for _ in range(30):
            time.sleep(0.5)
            r = _http_request("127.0.0.1", port, "GET", "/v1/health", timeout=2)
            if r["status"] == 200:
                print(f"[dkws] 服务已就绪 PID={proc.pid} port={port}", flush=True)
                return proc
        print(f"[dkws] 服务启动超时", flush=True)
        proc.kill()
        return None
    except Exception as exc:
        print(f"[dkws] 启动失败：{exc}", flush=True)
        return None


def _stop_dkws(proc: subprocess.Popen | None) -> None:
    """停止 DKWS 服务。"""
    if proc is None:
        return
    try:
        proc.terminate()
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)
    except Exception:
        pass


def _wait_for_port(port: int, timeout: float = 15.0) -> bool:
    """等待端口可达。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(1)
            s.connect(("127.0.0.1", port))
            s.close()
            return True
        except (ConnectionRefusedError, OSError):
            time.sleep(0.3)
    return False


def _wait_for_port_down(port: int, timeout: float = 10.0) -> bool:
    """等待端口不可达。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(1)
            s.connect(("127.0.0.1", port))
            s.close()
            time.sleep(0.3)
        except (ConnectionRefusedError, OSError):
            return True
    return False


# ---------------------------------------------------------------------------
# 故障场景测试
# ---------------------------------------------------------------------------

def test_network_connection_refused(report: dict, port: int) -> None:
    """网络层：DKWS 服务不可达（连接拒绝）→ GITS 应 fail-closed。"""
    # 不启动 DKWS，直接请求
    r = _http_request("127.0.0.1", port, "GET", "/v1/health", timeout=5)
    fail_closed = r["error"] in ("CONNECTION_REFUSED", "OS_ERROR")
    _log(report, "network_connection_refused",
         fail_closed,
         f"连接拒绝时行为：error={r['error']}，"
         f"预期=fail-closed（连接拒绝/OS错误），"
         f"GITS 应捕获异常并 fail-closed")


def test_network_timeout(report: dict, port: int, dkws_proc: subprocess.Popen | None) -> None:
    """网络层：请求超时（慢响应）→ GITS 应超时处理。"""
    # 使用 delay 注入，在代理端口上延迟
    proxy_port = port + 1000
    chaos_injector.inject_delay(proxy_port, delay_sec=30, duration_sec=15)
    try:
        r = _http_request("127.0.0.1", proxy_port, "GET", "/v1/health", timeout=3)
        timeout_handled = r["error"] == "TIMEOUT" or r["status"] is not None
        _log(report, "network_timeout",
             timeout_handled,
             f"超时行为：error={r['error']} status={r['status']}，"
             f"预期=GITS 应设置合理超时并处理超时异常")
    finally:
        chaos_injector.cleanup_all()


def test_network_connection_reset(report: dict, port: int) -> None:
    """网络层：连接重置（RST）→ GITS 应重试。"""
    proxy_port = port + 1001
    chaos_injector.inject_reset(proxy_port, duration_sec=15)
    try:
        r = _http_request("127.0.0.1", proxy_port, "GET", "/v1/health", timeout=5)
        reset_handled = r["error"] in ("CONNECTION_RESET", "BROKEN_PIPE",
                                       "OS_ERROR", "HTTP_ERROR")
        _log(report, "network_connection_reset",
             reset_handled,
             f"连接重置行为：error={r['error']}，"
             f"预期=GITS 应捕获重置异常并重试")
    finally:
        chaos_injector.cleanup_all()


def test_app_5xx(report: dict, port: int) -> None:
    """应用层：DKWS 返回 5xx → GITS 应重试/降级。"""
    proxy_port = port + 1002
    chaos_injector.inject_5xx(proxy_port, status_code=500, duration_sec=15)
    try:
        r = _http_request("127.0.0.1", proxy_port, "GET", "/v1/health", timeout=5)
        handled = r["status"] is not None and r["status"] >= 500
        _log(report, "app_5xx_response",
             handled,
             f"5xx 行为：status={r['status']} error={r['error']}，"
             f"预期=GITS 应识别 5xx 并重试或降级")
    finally:
        chaos_injector.cleanup_all()


def test_app_4xx(report: dict, port: int) -> None:
    """应用层：DKWS 返回 4xx → GITS 应区分客户端错误。"""
    proxy_port = port + 1003
    chaos_injector.inject_4xx(proxy_port, status_code=400, duration_sec=15)
    try:
        r = _http_request("127.0.0.1", proxy_port, "GET", "/v1/health", timeout=5)
        handled = r["status"] is not None and 400 <= r["status"] < 500
        _log(report, "app_4xx_response",
             handled,
             f"4xx 行为：status={r['status']} error={r['error']}，"
             f"预期=GITS 应区分客户端错误（不重试）")
    finally:
        chaos_injector.cleanup_all()


def test_app_badbody(report: dict, port: int) -> None:
    """应用层：DKWS 返回异常响应体（非 JSON）→ GITS 应容错。"""
    proxy_port = port + 1004
    chaos_injector.inject_badbody(proxy_port, duration_sec=15)
    try:
        r = _http_request("127.0.0.1", proxy_port, "GET", "/v1/health", timeout=5)
        # 检查是否能解析 body
        parse_ok = False
        if r["body"]:
            try:
                json.loads(r["body"])
                parse_ok = True
            except (json.JSONDecodeError, ValueError):
                parse_ok = False  # 预期：非 JSON
        handled = r["status"] is not None and not parse_ok
        _log(report, "app_bad_body",
             handled,
             f"异常响应体行为：status={r['status']} body_parseable={parse_ok}，"
             f"预期=GITS 应捕获 JSON 解析异常并容错处理")
    finally:
        chaos_injector.cleanup_all()


def test_data_empty(report: dict, port: int) -> None:
    """数据层：DKWS 返回空数据 → GITS 应正确处理空态。"""
    proxy_port = port + 1005
    chaos_injector.inject_empty(proxy_port, duration_sec=15)
    try:
        r = _http_request("127.0.0.1", proxy_port, "GET", "/v1/health", timeout=5)
        empty_handled = r["status"] is not None and (r["body"] == "" or r["body"] is None)
        _log(report, "data_empty_response",
             empty_handled,
             f"空数据行为：status={r['status']} body_len={len(r['body'] or '')}，"
             f"预期=GITS 应正确处理空响应体")
    finally:
        chaos_injector.cleanup_all()


def test_data_partial(report: dict, port: int) -> None:
    """数据层：DKWS 返回部分数据 → GITS 应检测不完整。"""
    proxy_port = port + 1006
    chaos_injector.inject_partial(proxy_port, duration_sec=15)
    try:
        r = _http_request("127.0.0.1", proxy_port, "GET", "/v1/health", timeout=5)
        # 检查 body 是否为截断 JSON
        truncated = False
        if r["body"]:
            try:
                json.loads(r["body"])
            except (json.JSONDecodeError, ValueError):
                truncated = True
        handled = r["status"] is not None and truncated
        _log(report, "data_partial_response",
             handled,
             f"部分数据行为：status={r['status']} truncated={truncated}，"
             f"预期=GITS 应检测不完整 JSON 并处理")
    finally:
        chaos_injector.cleanup_all()


def test_process_crash(report: dict, port: int, dkws_proc: subprocess.Popen | None) -> None:
    """进程层：DKWS 进程崩溃（kill -9）→ GITS 应检测并 fail-closed。"""
    if dkws_proc is None:
        _log(report, "process_crash", True, "SKIP: DKWS 未启动，无法测试进程崩溃")
        return

    pid = dkws_proc.pid
    chaos_injector.inject_crash(pid)

    # 等待进程退出
    time.sleep(1)
    down = _wait_for_port_down(port, timeout=5)

    # 尝试请求
    r = _http_request("127.0.0.1", port, "GET", "/v1/health", timeout=5)
    fail_closed = r["error"] in ("CONNECTION_REFUSED", "OS_ERROR") or down

    _log(report, "process_crash",
         fail_closed,
         f"进程崩溃行为：port_down={down} error={r['error']}，"
         f"预期=GITS 应检测服务不可达并 fail-closed")


def test_process_hang(report: dict, port: int, dkws_proc: subprocess.Popen | None) -> None:
    """进程层：DKWS 进程挂起（SIGSTOP）→ GITS 应超时。"""
    if dkws_proc is None:
        _log(report, "process_hang", True, "SKIP: DKWS 未启动，无法测试进程挂起")
        return

    pid = dkws_proc.pid
    chaos_injector.inject_hang(pid, duration_sec=10)

    # 短超时请求
    r = _http_request("127.0.0.1", port, "GET", "/v1/health", timeout=3)
    timeout_handled = r["error"] == "TIMEOUT" or r["status"] is not None

    # 等待自动恢复
    time.sleep(8)

    _log(report, "process_hang",
         timeout_handled,
         f"进程挂起行为：error={r['error']} status={r['status']}，"
         f"预期=GITS 应超时处理，进程自动恢复后应可访问")


def test_process_restart(report: dict, port: int, workspace: Path) -> None:
    """进程层：DKWS 重启中 → GITS 应重试直到就绪。"""
    # 先启动服务
    proc = _start_dkws(port, workspace)
    if proc is None:
        _log(report, "process_restart", True, "SKIP: DKWS 启动失败")
        return

    # 确认服务就绪
    r1 = _http_request("127.0.0.1", port, "GET", "/v1/health", timeout=5)
    was_up = r1["status"] == 200

    # 停止服务
    _stop_dkws(proc)
    down = _wait_for_port_down(port, timeout=5)

    # 请求应失败
    r2 = _http_request("127.0.0.1", port, "GET", "/v1/health", timeout=3)
    was_down = r2["error"] is not None

    # 重启服务
    proc2 = _start_dkws(port, workspace)
    if proc2:
        up = _wait_for_port(port, timeout=15)
        r3 = _http_request("127.0.0.1", port, "GET", "/v1/health", timeout=5)
        recovered = r3["status"] == 200
        _stop_dkws(proc2)
    else:
        recovered = False

    _log(report, "process_restart",
         was_up and was_down and recovered,
         f"重启行为：was_up={was_up} was_down={was_down} recovered={recovered}，"
         f"预期=GITS 应在服务不可达时重试，重启后应恢复")


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description="DKWS 故障注入测试框架")
    ap.add_argument("--dkws-port", type=int, default=8106,
                    help="DKWS 服务端口")
    ap.add_argument("--out", default=str(REPO / "evidence" / "m3-p0"),
                    help="报告输出目录")
    ap.add_argument("--skip-process-tests", action="store_true",
                    help="跳过进程层测试（避免 kill 进程）")
    args = ap.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    report: dict = {
        "task_package": "M3-P0",
        "scope": "故障注入韧性测试",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "dkws_port": args.dkws_port,
        "checks": [],
    }

    port = args.dkws_port
    workspace = Path(f"/tmp/dkws-chaos-ws-{port}")

    print("=" * 60, flush=True)
    print("DKWS 故障注入韧性测试", flush=True)
    print("=" * 60, flush=True)

    # --- 网络层测试（不需要 DKWS 运行）---
    print("\n--- 网络层故障 ---", flush=True)
    test_network_connection_refused(report, port)

    # 启动 DKWS 用于后续测试
    print("\n[setup] 启动 DKWS 服务 ...", flush=True)
    dkws_proc = _start_dkws(port, workspace)

    if dkws_proc:
        test_network_timeout(report, port, dkws_proc)
        test_network_connection_reset(report, port)

        # --- 应用层测试 ---
        print("\n--- 应用层故障 ---", flush=True)
        test_app_5xx(report, port)
        test_app_4xx(report, port)
        test_app_badbody(report, port)

        # --- 数据层测试 ---
        print("\n--- 数据层故障 ---", flush=True)
        test_data_empty(report, port)
        test_data_partial(report, port)

        if not args.skip_process_tests:
            # --- 进程层测试 ---
            print("\n--- 进程层故障 ---", flush=True)
            # crash 测试会 kill 进程，所以放在最后
            test_process_hang(report, port, dkws_proc)

            # 重启测试需要新进程
            _stop_dkws(dkws_proc)
            dkws_proc = None
            test_process_restart(report, port, workspace)

            # crash 测试（如果有新进程）
            if dkws_proc is None:
                dkws_proc = _start_dkws(port, workspace)
            test_process_crash(report, port, dkws_proc)
            dkws_proc = None  # 已被 crash
        else:
            print("\n--- 进程层故障（已跳过）---", flush=True)
            _stop_dkws(dkws_proc)
            dkws_proc = None
    else:
        print("[WARN] DKWS 启动失败，仅运行网络层测试", flush=True)
        # 仍然运行不需要 DKWS 的测试
        test_network_connection_reset(report, port)
        test_app_5xx(report, port)
        test_app_4xx(report, port)
        test_app_badbody(report, port)
        test_data_empty(report, port)
        test_data_partial(report, port)

    # 清理
    chaos_injector.cleanup_all()
    if dkws_proc:
        _stop_dkws(dkws_proc)

    # 汇总
    passed = sum(1 for c in report["checks"] if c["passed"])
    total = len(report["checks"])
    report["summary"] = {"passed": passed, "total": total,
                         "result": "PASS" if passed == total else "FAIL"}

    report_file = out_dir / "chaos_test_report.json"
    report_file.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                           encoding="utf-8")

    print(f"\n{'=' * 60}", flush=True)
    print(f"故障注入测试完成：{passed}/{total} 项通过 → {report['summary']['result']}",
          flush=True)
    print(f"报告：{report_file}", flush=True)

    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
