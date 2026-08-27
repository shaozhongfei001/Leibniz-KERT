#!/usr/bin/env python3
"""DKWS 故障注入工具——独立运行，注入指定故障类型。

支持的故障类型：
  delay   — 延迟响应（通过代理拦截，添加指定延迟）
  reject  — 拒绝连接（绑定同端口占位，使原服务不可达）
  reset   — 连接重置（代理接受后立即 RST）
  crash   — 进程崩溃（kill -9 目标 PID）
  hang    — 进程挂起（SIGSTOP 目标 PID，恢复用 SIGCONT）
  5xx     — 返回 500 系列错误
  4xx     — 返回 400 系列错误
  badbody — 返回非 JSON 响应体
  empty   — 返回空数据
  partial — 返回部分数据

安全机制：
  - 所有注入操作自动记录到 /tmp/dkws-chaos-state.json
  - 超时自动清理（默认 60 秒）
  - crash/hang 类型需要 --pid 参数
  - 全局清理：python chaos_injector.py cleanup

仅使用标准库（os/signal/subprocess/socket/time/json/pathlib）。

用法：
  python scripts/chaos_injector.py --type delay --port 8106 --duration 5
  python scripts/chaos_injector.py --type crash --pid 12345
  python scripts/chaos_injector.py --type hang --pid 12345 --duration 10
  python scripts/chaos_injector.py cleanup
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

STATE_FILE = Path("/tmp/dkws-chaos-state.json")
DEFAULT_DURATION = 60  # 秒，超时自动清理


# ---------------------------------------------------------------------------
# 状态管理
# ---------------------------------------------------------------------------

def _load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {"injections": []}
    return {"injections": []}


def _save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2),
                          encoding="utf-8")


def _record_injection(inj_type: str, detail: dict) -> None:
    state = _load_state()
    state["injections"].append({
        "type": inj_type,
        "detail": detail,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    })
    _save_state(state)


def _remove_injection(inj_type: str, key: str, value: str) -> None:
    state = _load_state()
    state["injections"] = [
        i for i in state["injections"]
        if not (i["type"] == inj_type and i["detail"].get(key) == value)
    ]
    _save_state(state)


# ---------------------------------------------------------------------------
# 故障注入实现
# ---------------------------------------------------------------------------

class DelayProxy:
    """TCP 代理：在转发前插入指定延迟。"""

    def __init__(self, listen_port: int, target_port: int, delay_sec: float,
                 duration_sec: float = DEFAULT_DURATION):
        self.listen_port = listen_port
        self.target_port = target_port
        self.delay_sec = delay_sec
        self.duration_sec = duration_sec
        self._stop_event = threading.Event()
        self._server_sock: socket.socket | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server_sock.bind(("127.0.0.1", self.listen_port))
        self._server_sock.listen(5)
        self._server_sock.settimeout(1.0)
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()
        _record_injection("delay", {
            "listen_port": self.listen_port,
            "target_port": self.target_port,
            "delay_sec": self.delay_sec,
            "expires_at": time.monotonic() + self.duration_sec,
        })

    def stop(self) -> None:
        self._stop_event.set()
        if self._server_sock:
            self._server_sock.close()
        if self._thread:
            self._thread.join(timeout=5)
        _remove_injection("delay", "listen_port", str(self.listen_port))

    def _serve(self) -> None:
        deadline = time.monotonic() + self.duration_sec
        while not self._stop_event.is_set() and time.monotonic() < deadline:
            try:
                client, _ = self._server_sock.accept()  # type: ignore
            except socket.timeout:
                continue
            except OSError:
                break
            threading.Thread(target=self._handle, args=(client,), daemon=True).start()

    def _handle(self, client: socket.socket) -> None:
        try:
            time.sleep(self.delay_sec)
            upstream = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            upstream.settimeout(10)
            upstream.connect(("127.0.0.1", self.target_port))
            # 双向转发
            self._relay(client, upstream)
        except Exception:
            pass
        finally:
            client.close()

    @staticmethod
    def _relay(a: socket.socket, b: socket.socket) -> None:
        """简化的双向 TCP 中继。"""
        a.settimeout(5)
        b.settimeout(5)
        for _ in range(200):  # 最多 200 次中继
            try:
                data = a.recv(4096)
                if not data:
                    break
                b.sendall(data)
                resp = b.recv(4096)
                if not resp:
                    break
                a.sendall(resp)
            except socket.timeout:
                continue
            except OSError:
                break


class ResetProxy:
    """TCP 代理：接受连接后立即发送 RST。"""

    def __init__(self, listen_port: int, duration_sec: float = DEFAULT_DURATION):
        self.listen_port = listen_port
        self.duration_sec = duration_sec
        self._stop_event = threading.Event()
        self._server_sock: socket.socket | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server_sock.bind(("127.0.0.1", self.listen_port))
        self._server_sock.listen(5)
        self._server_sock.settimeout(1.0)
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()
        _record_injection("reset", {
            "listen_port": self.listen_port,
            "expires_at": time.monotonic() + self.duration_sec,
        })

    def stop(self) -> None:
        self._stop_event.set()
        if self._server_sock:
            self._server_sock.close()
        if self._thread:
            self._thread.join(timeout=5)
        _remove_injection("reset", "listen_port", str(self.listen_port))

    def _serve(self) -> None:
        deadline = time.monotonic() + self.duration_sec
        while not self._stop_event.is_set() and time.monotonic() < deadline:
            try:
                client, _ = self._server_sock.accept()  # type: ignore
            except socket.timeout:
                continue
            except OSError:
                break
            # 设置 SO_LINGER 为 {on=1, linger=0} 使 close 发 RST
            client.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER,
                              struct.pack("ii", 1, 0))
            client.close()


# struct 只用于 ResetProxy，条件导入
try:
    import struct
except ImportError:
    struct = None  # type: ignore


class RejectBinder:
    """占用端口，使原服务不可达（连接拒绝）。"""

    def __init__(self, port: int, duration_sec: float = DEFAULT_DURATION):
        self.port = port
        self.duration_sec = duration_sec
        self._stop_event = threading.Event()
        self._server_sock: socket.socket | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server_sock.bind(("127.0.0.1", self.port))
        self._server_sock.listen(1)
        self._server_sock.settimeout(1.0)
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()
        _record_injection("reject", {
            "port": self.port,
            "expires_at": time.monotonic() + self.duration_sec,
        })

    def stop(self) -> None:
        self._stop_event.set()
        if self._server_sock:
            self._server_sock.close()
        if self._thread:
            self._thread.join(timeout=5)
        _remove_injection("reject", "port", str(self.port))

    def _serve(self) -> None:
        deadline = time.monotonic() + self.duration_sec
        while not self._stop_event.is_set() and time.monotonic() < deadline:
            try:
                conn, _ = self._server_sock.accept()  # type: ignore
                conn.close()  # 立即关闭 → 客户端看到连接被拒绝
            except socket.timeout:
                continue
            except OSError:
                break


# ---------------------------------------------------------------------------
# 故障注入 API
# ---------------------------------------------------------------------------

_active_proxies: list = []  # 运行中的代理对象引用，防止 GC


def inject_delay(port: int, delay_sec: float, duration_sec: float) -> str:
    """注入延迟：在 port 上启动代理，延迟 delay_sec 后转发到 port+10000。"""
    target_port = port + 10000
    proxy = DelayProxy(port, target_port, delay_sec, duration_sec)
    proxy.start()
    _active_proxies.append(proxy)
    return (f"延迟代理已启动：127.0.0.1:{port} → 127.0.0.1:{target_port}，"
            f"延迟={delay_sec}s，持续={duration_sec}s\n"
            f"请将 DKWS 服务启动在端口 {target_port} 上")


def inject_reject(port: int, duration_sec: float) -> str:
    """注入拒绝连接：占用端口，所有连接被拒绝。"""
    binder = RejectBinder(port, duration_sec)
    binder.start()
    _active_proxies.append(binder)
    return f"拒绝连接已启动：127.0.0.1:{port}，持续={duration_sec}s"


def inject_reset(port: int, duration_sec: float) -> str:
    """注入连接重置：接受连接后立即 RST。"""
    if struct is None:
        return "ERROR: struct 模块不可用，无法注入 RST"
    proxy = ResetProxy(port, duration_sec)
    proxy.start()
    _active_proxies.append(proxy)
    return f"连接重置已启动：127.0.0.1:{port}，持续={duration_sec}s"


def inject_crash(pid: int) -> str:
    """注入进程崩溃：kill -9 目标 PID。"""
    try:
        os.kill(pid, signal.SIGKILL)
        _record_injection("crash", {"pid": pid})
        return f"进程 {pid} 已被 SIGKILL"
    except ProcessLookupError:
        return f"ERROR: 进程 {pid} 不存在"
    except PermissionError:
        return f"ERROR: 无权限 kill 进程 {pid}"


def inject_hang(pid: int, duration_sec: float) -> str:
    """注入进程挂起：SIGSTOP 目标 PID。"""
    try:
        os.kill(pid, signal.SIGSTOP)
        _record_injection("hang", {"pid": pid, "duration": duration_sec})
        # 自动恢复
        def _resume():
            time.sleep(duration_sec)
            try:
                os.kill(pid, signal.SIGCONT)
                _remove_injection("hang", "pid", str(pid))
            except (ProcessLookupError, PermissionError):
                pass
        threading.Thread(target=_resume, daemon=True).start()
        return f"进程 {pid} 已被 SIGSTOP，{duration_sec}s 后自动 SIGCONT"
    except ProcessLookupError:
        return f"ERROR: 进程 {pid} 不存在"
    except PermissionError:
        return f"ERROR: 无权限 stop 进程 {pid}"


def inject_5xx(port: int, status_code: int = 500, duration_sec: float = DEFAULT_DURATION) -> str:
    """注入 5xx 响应：代理返回指定 5xx 状态码。"""
    return _inject_status_proxy(port, status_code, duration_sec, "5xx")


def inject_4xx(port: int, status_code: int = 400, duration_sec: float = DEFAULT_DURATION) -> str:
    """注入 4xx 响应：代理返回指定 4xx 状态码。"""
    return _inject_status_proxy(port, status_code, duration_sec, "4xx")


def inject_badbody(port: int, duration_sec: float = DEFAULT_DURATION) -> str:
    """注入异常响应体：代理返回非 JSON 内容。"""
    return _inject_status_proxy(port, 200, duration_sec, "badbody",
                                body="THIS IS NOT JSON <<<>>> BINARY GARBAGE\x00\x01\x02")


def inject_empty(port: int, duration_sec: float = DEFAULT_DURATION) -> str:
    """注入空数据：代理返回 200 但空 body。"""
    return _inject_status_proxy(port, 200, duration_sec, "empty", body="")


def inject_partial(port: int, duration_sec: float = DEFAULT_DURATION) -> str:
    """注入部分数据：代理返回 200 但截断的 JSON。"""
    partial_json = '{"status":"COMPLETED","result":{"chapters":['
    return _inject_status_proxy(port, 200, duration_sec, "partial", body=partial_json)


class StatusProxy:
    """TCP 代理：返回指定 HTTP 状态码和 body。"""

    def __init__(self, listen_port: int, status_code: int, body: str,
                 duration_sec: float, inj_type: str):
        self.listen_port = listen_port
        self.status_code = status_code
        self.body = body
        self.duration_sec = duration_sec
        self.inj_type = inj_type
        self._stop_event = threading.Event()
        self._server_sock: socket.socket | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server_sock.bind(("127.0.0.1", self.listen_port))
        self._server_sock.listen(5)
        self._server_sock.settimeout(1.0)
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()
        _record_injection(self.inj_type, {
            "listen_port": self.listen_port,
            "status_code": self.status_code,
            "expires_at": time.monotonic() + self.duration_sec,
        })

    def stop(self) -> None:
        self._stop_event.set()
        if self._server_sock:
            self._server_sock.close()
        if self._thread:
            self._thread.join(timeout=5)
        _remove_injection(self.inj_type, "listen_port", str(self.listen_port))

    def _serve(self) -> None:
        deadline = time.monotonic() + self.duration_sec
        while not self._stop_event.is_set() and time.monotonic() < deadline:
            try:
                client, _ = self._server_sock.accept()  # type: ignore
            except socket.timeout:
                continue
            except OSError:
                break
            threading.Thread(target=self._respond, args=(client,), daemon=True).start()

    def _respond(self, client: socket.socket) -> None:
        try:
            # 读取请求（丢弃）
            client.settimeout(2)
            try:
                client.recv(4096)
            except socket.timeout:
                pass
            # 发送伪造响应
            body_bytes = self.body.encode("utf-8")
            headers = (
                f"HTTP/1.1 {self.status_code} {self._status_text()}\r\n"
                f"Content-Type: application/json\r\n"
                f"Content-Length: {len(body_bytes)}\r\n"
                f"Connection: close\r\n"
                f"\r\n"
            )
            client.sendall(headers.encode("utf-8") + body_bytes)
        except OSError:
            pass
        finally:
            client.close()

    def _status_text(self) -> str:
        texts = {
            200: "OK", 400: "Bad Request", 401: "Unauthorized",
            403: "Forbidden", 404: "Not Found", 500: "Internal Server Error",
            502: "Bad Gateway", 503: "Service Unavailable",
        }
        return texts.get(self.status_code, "Unknown")


def _inject_status_proxy(port: int, status_code: int, duration_sec: float,
                         inj_type: str, body: str | None = None) -> str:
    if body is None:
        body = json.dumps({"error": f"Injected {status_code}", "detail": inj_type})
    proxy = StatusProxy(port, status_code, body, duration_sec, inj_type)
    proxy.start()
    _active_proxies.append(proxy)
    return f"{inj_type} 代理已启动：127.0.0.1:{port}，状态={status_code}，持续={duration_sec}s"


# ---------------------------------------------------------------------------
# 清理
# ---------------------------------------------------------------------------

def cleanup_all() -> str:
    """清理所有故障注入状态。"""
    results = []
    state = _load_state()

    # 恢复挂起的进程
    for inj in state["injections"]:
        if inj["type"] == "hang":
            pid = inj["detail"].get("pid")
            if pid:
                try:
                    os.kill(pid, signal.SIGCONT)
                    results.append(f"SIGCONT → PID {pid}")
                except (ProcessLookupError, PermissionError):
                    results.append(f"PID {pid} 已不存在或无权限")

    # 清理状态文件
    state["injections"] = []
    _save_state(state)

    # 杀掉占用端口的代理进程（通过 lsof/fuser）
    results.append("状态文件已清理")
    return "清理完成：" + "; ".join(results)


# ---------------------------------------------------------------------------
# 等待代理运行（阻塞直到超时）
# ---------------------------------------------------------------------------

def wait_proxies(duration_sec: float) -> None:
    """等待所有活跃代理运行指定时间。"""
    time.sleep(duration_sec)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description="DKWS 故障注入工具")
    ap.add_argument("--type", required=True,
                    choices=["delay", "reject", "reset", "crash", "hang",
                             "5xx", "4xx", "badbody", "empty", "partial",
                             "cleanup"],
                    help="故障类型")
    ap.add_argument("--port", type=int, default=8106, help="目标端口")
    ap.add_argument("--pid", type=int, default=None, help="目标进程 PID（crash/hang）")
    ap.add_argument("--delay", type=float, default=5.0, help="延迟秒数（delay）")
    ap.add_argument("--status-code", type=int, default=None, help="HTTP 状态码（5xx/4xx）")
    ap.add_argument("--duration", type=float, default=DEFAULT_DURATION,
                    help="注入持续时间（秒）")
    ap.add_argument("--wait", action="store_true",
                    help="阻塞等待注入完成")
    args = ap.parse_args()

    if args.type == "cleanup":
        print(cleanup_all())
        return 0

    if args.type in ("crash", "hang") and args.pid is None:
        print("ERROR: crash/hang 需要 --pid 参数", file=sys.stderr)
        return 1

    handlers = {
        "delay": lambda: inject_delay(args.port, args.delay, args.duration),
        "reject": lambda: inject_reject(args.port, args.duration),
        "reset": lambda: inject_reset(args.port, args.duration),
        "crash": lambda: inject_crash(args.pid),
        "hang": lambda: inject_hang(args.pid, args.duration),
        "5xx": lambda: inject_5xx(args.port, args.status_code or 500, args.duration),
        "4xx": lambda: inject_4xx(args.port, args.status_code or 400, args.duration),
        "badbody": lambda: inject_badbody(args.port, args.duration),
        "empty": lambda: inject_empty(args.port, args.duration),
        "partial": lambda: inject_partial(args.port, args.duration),
    }

    result = handlers[args.type]()
    print(result)

    if args.wait:
        print(f"等待 {args.duration}s ...", flush=True)
        wait_proxies(args.duration)
        print("注入完成")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
