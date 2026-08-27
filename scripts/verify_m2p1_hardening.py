#!/usr/bin/env python3
"""M2-P1 端到端加固验证（真实 uvicorn 进程 + 真实 HTTP 请求）。

验证内容：
1. 生产 profile 缺少认证/限流 → 拒绝启动（非零退出码）
2. 生产 profile 齐备配置 → 正常启动
3. 未认证请求 → 401；错误密钥 → 401；健康检查匿名可访问 → 200
4. 普通密钥访问闸门审计 → 403；admin 密钥 → 200
5. 超出突发额度 → 429（带 Retry-After）
6. 超过请求体上限 → 413
7. SQLite Runtime Store 落库：WAL、schema_version、幂等记录、闸门审计
8. 重启后按 requestId 幂等复放

用法：
    python scripts/verify_m2p1_hardening.py [--out evidence/m2-p1]

输出：JSON 报告 + 原始日志，写入 --out 目录。
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import signal
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "src"
PORT = 18711
BASE = f"http://127.0.0.1:{PORT}"

VALID_KEY = "e2e-normal-key-0123456789"
ADMIN_KEY = "e2e-admin-key-0123456789"
WRONG_KEY = "e2e-wrong-key-0123456789"

SKILL_ID = "skill-customer-outreach-script"
CUSTOMER = "CUST-CORP-0001"

#: 用于认证/限流验证的受保护端点（真实存在且无需业务前置状态）
PROTECTED_PATH = "/v1/catalog"


def _log(report: dict, name: str, passed: bool, detail: str) -> None:
    """记录一条检查结果。"""
    report["checks"].append({"name": name, "passed": bool(passed), "detail": detail})
    mark = "PASS" if passed else "FAIL"
    print(f"[{mark}] {name} :: {detail}", flush=True)


def _prod_env(workspace: Path, extra: dict[str, str] | None = None) -> dict[str, str]:
    """构造生产 profile 环境变量。"""
    env = dict(os.environ)
    env.update({
        "PYTHONPATH": str(SRC),
        "DKWS_PROFILE": "prod",
        "DKWS_BIND_HOST": "127.0.0.1",
        "DKWS_API_KEYS": (f"svc:{VALID_KEY}:read|execute,"
                          f"ops:{ADMIN_KEY}:read|execute|admin"),
        "DKWS_RATE_LIMIT_ENABLED": "true",
        "DKWS_RATE_LIMIT_RPM": "60",
        "DKWS_RATE_LIMIT_BURST": "3",
        "DKWS_SIZE_LIMIT_ENABLED": "true",
        "DKWS_MAX_REQUEST_BYTES": "2048",
        "DKWS_CONCURRENCY_ENABLED": "true",
        "DKWS_MAX_IN_FLIGHT": "8",
        "DKWS_RUNTIME_STORE_ENABLED": "true",
        "DKWS_LLM_BASE_URL": "",
    })
    env.pop("DKWS_LLM_API_KEY", None)
    if extra:
        env.update(extra)
    return env


def _init_workspace(root: Path) -> Path:
    """初始化一个真实工作区。"""
    sys.path.insert(0, str(SRC))
    from dkws.domain import workspace as ws_mod

    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    ws_mod.init_workspace(root)
    return root


def _wait_ready(proc: subprocess.Popen, timeout: float = 30.0) -> bool:
    """轮询健康检查直到服务就绪。"""
    import urllib.error
    import urllib.request

    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc.poll() is not None:
            return False
        try:
            with urllib.request.urlopen(f"{BASE}/v1/health", timeout=2) as resp:
                if resp.status == 200:
                    return True
        except (urllib.error.URLError, OSError):
            time.sleep(0.4)
    return False


def _request(method: str, path: str, *, key: str | None = None,
             body: dict | bytes | None = None) -> tuple[int, dict, str]:
    """发送 HTTP 请求，返回 (状态码, 响应头, 响应体文本)。

    响应头 key 统一小写化：uvicorn 按 HTTP/1.1 规范输出小写头名，
    直接 ``dict()`` 会得到大小写敏感的映射，故此处归一化后再返回。
    """
    import urllib.error
    import urllib.request

    data = None
    headers = {}
    if body is not None:
        data = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if key:
        headers["X-API-Key"] = key
    req = urllib.request.Request(f"{BASE}{path}", data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, _lower_headers(resp.headers), resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return exc.code, _lower_headers(exc.headers), exc.read().decode("utf-8")


def _lower_headers(headers) -> dict[str, str]:
    """把响应头名统一转为小写，便于稳定断言。"""
    return {str(k).lower(): str(v) for k, v in dict(headers).items()}


def check_fail_fast(report: dict, workspace: Path, log_dir: Path) -> None:
    """场景 1：生产 profile 缺少认证/限流应拒绝启动。"""
    env = dict(os.environ)
    env.update({"PYTHONPATH": str(SRC), "DKWS_PROFILE": "prod",
                "DKWS_BIND_HOST": "127.0.0.1"})
    env.pop("DKWS_API_KEYS", None)
    proc = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "serve_skill_service.py"),
         "--workspace", str(workspace), "--port", str(PORT + 1), "--host", "127.0.0.1"],
        env=env, capture_output=True, text=True, timeout=90)
    output = proc.stdout + proc.stderr
    (log_dir / "01_fail_fast.log").write_text(
        f"exit_code={proc.returncode}\n\n{output}", encoding="utf-8")
    _log(report, "prod_profile_fail_fast",
         proc.returncode != 0 and "拒绝启动" in output,
         f"退出码={proc.returncode}，输出含拒绝启动说明")


def check_running_service(report: dict, workspace: Path, log_dir: Path) -> None:
    """场景 2-8：启动真实服务并验证加固行为与落库。"""
    log_path = log_dir / "02_service.log"
    with log_path.open("w", encoding="utf-8") as log_file:
        proc = subprocess.Popen(
            [sys.executable, str(REPO / "scripts" / "serve_skill_service.py"),
             "--workspace", str(workspace), "--port", str(PORT), "--host", "127.0.0.1"],
            env=_prod_env(workspace), stdout=log_file, stderr=subprocess.STDOUT)
        try:
            ready = _wait_ready(proc)
            _log(report, "prod_profile_starts_with_full_config", ready,
                 f"服务在 127.0.0.1:{PORT} 就绪" if ready else "启动失败，见 02_service.log")
            if not ready:
                return

            status, _, _ = _request("GET", "/v1/health")
            _log(report, "health_public_without_key", status == 200, f"GET /v1/health → {status}")

            status, headers, text = _request("GET", PROTECTED_PATH)
            body = json.loads(text)
            www_auth = headers.get("www-authenticate", "")
            _log(report, "missing_key_401",
                 status == 401 and body["error"]["code"] == "UNAUTHENTICATED"
                 and "X-API-Key" in www_auth,
                 f"无密钥 → {status} {body['error']['code']}；"
                 f"WWW-Authenticate={www_auth!r}")

            status, _, text = _request("GET", PROTECTED_PATH, key=WRONG_KEY)
            _log(report, "wrong_key_401",
                 status == 401 and WRONG_KEY not in text,
                 f"错误密钥 → {status}，响应体不回显密钥")

            status, _, _ = _request("GET", PROTECTED_PATH, key=VALID_KEY)
            _log(report, "valid_key_accepted", status not in (401, 403, 404),
                 f"有效密钥 → {status}（通过认证，非 401/403）")

            gate_body = {"customerId": "E2E-C001", "gate": "GATE-BIZ-01",
                         "decision": "APPROVED", "decidedBy": "e2e@ops", "reason": "e2e"}
            status, _, text = _request("POST", "/api/skill/gates/audit",
                                       key=VALID_KEY, body=gate_body)
            body = json.loads(text)
            _log(report, "non_admin_scope_403",
                 status == 403 and body["error"]["code"] == "FORBIDDEN",
                 f"普通密钥访问闸门审计 → {status} {body['error']['code']}")

            status, _, _ = _request("POST", "/api/skill/gates/audit",
                                    key=ADMIN_KEY, body=gate_body)
            _log(report, "admin_scope_allowed", status == 200,
                 f"admin 密钥访问闸门审计 → {status}")

            big = {"skillId": SKILL_ID, "requestId": "E2E-BIG",
                   "request": {"customerId": CUSTOMER, "blob": "x" * 4096}}
            status, _, text = _request("POST", "/api/skill/execute", key=VALID_KEY, body=big)
            body = json.loads(text)
            _log(report, "oversize_request_413",
                 status == 413 and body["error"]["code"] == "PAYLOAD_TOO_LARGE",
                 f"4KB 请求体（上限 2048） → {status} {body['error']['code']}")

            codes = []
            retry_after = ""
            for _ in range(8):
                status, headers, _ = _request("GET", PROTECTED_PATH, key=ADMIN_KEY)
                codes.append(status)
                if status == 429:
                    retry_after = headers.get("retry-after", "")
                    break
            _log(report, "rate_limit_429",
                 429 in codes and retry_after != "",
                 f"连续请求状态码={codes}，Retry-After={retry_after!r}（burst=3）")

            time.sleep(4.0)
            exec_body = {"skillId": SKILL_ID, "requestId": "E2E-IDEM-1",
                         "request": {"customerId": CUSTOMER}}
            status, _, text = _request("POST", "/api/skill/execute",
                                       key=VALID_KEY, body=exec_body)
            first_ok = status == 200
            _log(report, "skill_execute_succeeds", first_ok,
                 f"POST /api/skill/execute → {status}")

            status, _, text = _request("GET", "/v1/health")
            runtime = json.loads(text)["data"]["runtime"]
            _log(report, "health_reports_hardening",
                 all([runtime["auth_enabled"], runtime["rate_limit_enabled"],
                      runtime["size_limit_enabled"], runtime["concurrency_enabled"],
                      runtime["runtime_store_enabled"]])
                 and runtime["schema_version"] >= 1,
                 f"runtime={json.dumps(runtime, ensure_ascii=False)}")
            report["health_runtime"] = runtime
        finally:
            if proc.poll() is None:
                proc.send_signal(signal.SIGTERM)
                try:
                    proc.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    proc.kill()


def check_store(report: dict, workspace: Path, log_dir: Path) -> None:
    """场景 7：直接查库验证 WAL、schema、幂等与审计落库。"""
    db = workspace / "90_control" / "runtime" / "runtime.db"
    _log(report, "store_under_control_dir", db.is_file(),
         f"数据库路径={db.relative_to(workspace)}")
    if not db.is_file():
        return
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        mode = str(conn.execute("PRAGMA journal_mode").fetchone()[0]).lower()
        _log(report, "wal_enabled", mode == "wal", f"journal_mode={mode}")

        version = int(conn.execute("SELECT MAX(version) v FROM schema_version").fetchone()["v"])
        _log(report, "schema_version_recorded", version >= 1, f"schema_version={version}")

        tables = sorted(r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%'").fetchall())
        expected = ["evidence_audit", "gate_audit", "idempotency_records",
                    "jobs", "schema_version"]
        _log(report, "no_knowledge_tables", tables == expected,
             f"表清单={tables}（不含任何知识内容表，知识权威源仍为文件资产）")

        idem = conn.execute(
            "SELECT * FROM idempotency_records WHERE idem_key=?", ("E2E-IDEM-1",)).fetchone()
        _log(report, "idempotency_persisted", idem is not None,
             f"幂等记录 E2E-IDEM-1 已落库，scope={idem['scope'] if idem else None}")

        gate = conn.execute(
            "SELECT * FROM gate_audit WHERE customer_id=?", ("E2E-C001",)).fetchone()
        _log(report, "gate_audit_persisted",
             gate is not None and gate["decision"] == "APPROVED",
             f"闸门审计已落库，decision={gate['decision'] if gate else None}")

        report["store_stats"] = {
            "schema_version": version,
            "journal_mode": mode,
            "tables": tables,
            "idempotency_records": int(conn.execute(
                "SELECT COUNT(*) c FROM idempotency_records").fetchone()["c"]),
            "gate_audit": int(conn.execute(
                "SELECT COUNT(*) c FROM gate_audit").fetchone()["c"]),
        }
    finally:
        conn.close()

    jsonl = workspace / "90_control" / "audit" / "gates.jsonl"
    _log(report, "gate_audit_jsonl_kept", jsonl.is_file(),
         "JSONL 审计留痕仍在写入（与 Store 互补，均非业务权威）")
    (log_dir / "03_store_dump.json").write_text(
        json.dumps(report.get("store_stats", {}), ensure_ascii=False, indent=2),
        encoding="utf-8")


def check_restart_replay(report: dict, workspace: Path, log_dir: Path) -> None:
    """场景 8：重启服务后按 requestId 幂等复放。"""
    log_path = log_dir / "04_restart.log"
    with log_path.open("w", encoding="utf-8") as log_file:
        proc = subprocess.Popen(
            [sys.executable, str(REPO / "scripts" / "serve_skill_service.py"),
             "--workspace", str(workspace), "--port", str(PORT), "--host", "127.0.0.1"],
            env=_prod_env(workspace, {"DKWS_RATE_LIMIT_BURST": "30"}),
            stdout=log_file, stderr=subprocess.STDOUT)
        try:
            if not _wait_ready(proc):
                _log(report, "restart_idempotency_replay", False, "重启后服务未就绪")
                return
            body = {"skillId": SKILL_ID, "requestId": "E2E-IDEM-1",
                    "request": {"customerId": CUSTOMER}}
            status, _, text = _request("POST", "/api/skill/execute",
                                       key=VALID_KEY, body=body)
            payload = json.loads(text)
            phases = [t.get("phase") for t in payload.get("assemblyTrace", [])]
            _log(report, "restart_idempotency_replay",
                 status == 200 and "idempotency" in phases,
                 f"重启后同 requestId → {status}，assemblyTrace 含 idempotency 阶段")
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
    ap.add_argument("--out", default=str(REPO / "evidence" / "m2-p1"))
    ap.add_argument("--workspace", default="/tmp/dkws-m2p1-e2e-ws")
    args = ap.parse_args()

    out_dir = Path(args.out)
    log_dir = out_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    workspace = _init_workspace(Path(args.workspace))
    report: dict = {
        "task_package": "M2-P1",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "environment": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "workspace": str(workspace),
        },
        "checks": [],
    }

    check_fail_fast(report, workspace, log_dir)
    check_running_service(report, workspace, log_dir)
    check_store(report, workspace, log_dir)
    check_restart_replay(report, workspace, log_dir)

    passed = sum(1 for c in report["checks"] if c["passed"])
    total = len(report["checks"])
    report["summary"] = {"passed": passed, "total": total,
                         "result": "PASS" if passed == total else "FAIL"}
    (out_dir / "e2e_hardening_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n=== {passed}/{total} 项检查通过 → {report['summary']['result']} ===")
    print(f"报告：{out_dir / 'e2e_hardening_report.json'}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
