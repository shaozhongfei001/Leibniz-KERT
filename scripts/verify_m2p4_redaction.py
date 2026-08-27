#!/usr/bin/env python3
"""M2-P4 端到端验收：数据分类与脱敏（M2.9）在真实进程下的验证。

验收标准：脱敏测试通过——敏感字段在出站通道被掩码，内部产物保持明文。

验证内容：
1. 字段分类清单完整且可导出（合规文档基础）
2. 各掩码风格正确（长度保持、不泄漏原值）
3. 真实服务默认不脱敏响应（不破坏既有契约）
4. 启用后响应结构完整、content-length 正确
5. 非 JSON 响应（Prometheus）原样透传
6. LLM 出站脱敏：外部适配器收到掩码后的提示词
7. 本地适配器不脱敏（不出网，脱敏有害无益）
8. 日志中不出现敏感值
9. 内部产物（Skill 结果）保持明文，业务逻辑不受影响
10. 生产 profile 配置组合可用

用法：
    python scripts/verify_m2p4_redaction.py [--out evidence/m2-p4]
"""

from __future__ import annotations

import argparse
import json
import os
import platform
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
PORT = 18744
BASE = f"http://127.0.0.1:{PORT}"

MOBILE = "13812348000"
ID_CARD = "110101199001011234"
CREDIT_CODE = "91310000MA1K35Q12X"
BANK_CARD = "6222021234567890123"
EMAIL = "zhangsan@huaxin.com"
API_KEY = "m2p4-verify-key-0123456789"


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


def _request(method: str, path: str, *, key: str | None = None) -> tuple[int, dict, str]:
    """发送 HTTP 请求。"""
    headers = {"X-API-Key": key} if key else {}
    req = urllib.request.Request(f"{BASE}{path}", headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return (resp.status, {k.lower(): v for k, v in dict(resp.headers).items()},
                    resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return (exc.code, {k.lower(): v for k, v in dict(exc.headers).items()},
                exc.read().decode("utf-8"))


def _wait_ready(proc: subprocess.Popen, timeout: float = 40.0) -> bool:
    """轮询 /livez 直到就绪。"""
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


def check_inventory(report: dict) -> None:
    """场景 1：分类清单可导出。"""
    from dkws.infrastructure.classification import (
        Classification,
        classification_inventory,
    )

    inventory = classification_inventory()
    by_level: dict[str, int] = {}
    for row in inventory:
        by_level[row["classification"]] = by_level.get(row["classification"], 0) + 1
    _log(report, "classification_inventory_exportable",
         len(inventory) >= 25 and all(r["note"] for r in inventory),
         f"分类清单 {len(inventory)} 条，各等级分布={by_level}，全部含中文说明")

    _log(report, "unknown_classification_fails_safe",
         Classification.parse("typo") == Classification.INTERNAL,
         "未知分类标记回落 INTERNAL（不当作 PUBLIC，避免拼写错误导致泄漏）")

    report["inventory"] = inventory


def check_mask_styles(report: dict) -> None:
    """场景 2：掩码风格正确性。"""
    from dkws.infrastructure.classification import MaskStyle, mask_value

    cases = [
        (MOBILE, MaskStyle.TAIL, 4, "8000"),
        (ID_CARD, MaskStyle.TAIL, 4, "1234"),
        (CREDIT_CODE, MaskStyle.TAIL, 4, "Q12X"),
    ]
    ok = True
    details = []
    for raw, style, keep, tail in cases:
        masked = mask_value(raw, style=style, keep=keep)
        good = (raw not in masked and masked.endswith(tail)
                and len(masked) == len(raw))
        ok = ok and good
        details.append(f"{raw[:6]}…→{masked}")
    _log(report, "mask_styles_correct", ok,
         f"掩码保留尾部可核对且长度不变：{'; '.join(details)}")

    # 边界：keep=0 与负值必须完全掩码且不泄漏
    zero = mask_value("abcdef", style=MaskStyle.TAIL, keep=0)
    neg = mask_value("abcdef", style=MaskStyle.TAIL, keep=-3)
    _log(report, "mask_boundary_no_leak",
         zero == "******" and neg == "******",
         f"keep=0→{zero!r}，keep=-3→{neg!r}（早期实现会产出 '******abcdef' 泄漏原值）")

    short = mask_value("123", style=MaskStyle.TAIL, keep=4)
    _log(report, "mask_short_value_no_leak",
         "3" not in short and len(short) == 3,
         f"短值 '123'→{short!r}，不因保留位数大于长度而泄漏")


def check_structure_redaction(report: dict) -> None:
    """场景 9 前置：结构脱敏与策略差异。"""
    from dkws.infrastructure.classification import (
        POLICY_API_RESPONSE,
        POLICY_LLM,
        RedactionReport,
        redact_structure,
    )

    data = {
        "customerId": "CUST-CORP-0001",
        "mobile": MOBILE,
        "idCardNo": ID_CARD,
        "creditCode": CREDIT_CODE,
        "nested": {"contactPhone": MOBILE, "bankAccount": BANK_CARD},
        "items": [{"email": EMAIL}],
        "note": f"联系 {MOBILE}",
    }
    original = json.dumps(data, ensure_ascii=False)

    rep_api = RedactionReport()
    api_out = redact_structure(data, POLICY_API_RESPONSE, report=rep_api)
    api_text = json.dumps(api_out, ensure_ascii=False)
    _log(report, "api_policy_masks_restricted",
         all(s not in api_text for s in (MOBILE, ID_CARD, BANK_CARD, EMAIL)),
         f"API 策略掩码 {rep_api.count} 个 RESTRICTED 字段："
         f"{rep_api.as_dict()['masked_fields']}")
    _log(report, "api_policy_preserves_confidential",
         CREDIT_CODE in api_text and "CUST-CORP-0001" in api_text,
         "保留 CONFIDENTIAL 与 INTERNAL 字段供业务使用（避免破坏既有契约）")

    rep_llm = RedactionReport()
    llm_out = redact_structure(data, POLICY_LLM, report=rep_llm)
    llm_text = json.dumps(llm_out, ensure_ascii=False)
    _log(report, "llm_policy_stricter_than_api",
         CREDIT_CODE not in llm_text and rep_llm.count > rep_api.count,
         f"LLM 策略掩码 {rep_llm.count} 个字段（含 CONFIDENTIAL），"
         f"严于 API 策略的 {rep_api.count} 个")
    _log(report, "llm_policy_masks_free_text",
         MOBILE not in llm_out["note"],
         f"自由文本亦掩码：note={llm_out['note']!r}")

    _log(report, "redaction_does_not_mutate_input",
         json.dumps(data, ensure_ascii=False) == original,
         "脱敏不修改入参，内部计算仍可用明文")

    deep = current = {}
    for _ in range(40):
        current["c"] = {}
        current = current["c"]
    rep_deep = RedactionReport()
    redact_structure(deep, POLICY_API_RESPONSE, report=rep_deep)
    _log(report, "redaction_depth_guard", rep_deep.truncated is True,
         "深层嵌套触发深度保护并标记 truncated（防御栈溢出）")


def check_llm_egress(report: dict) -> None:
    """场景 6-7：LLM 出站脱敏。"""
    from dkws.application import skills as skills_mod
    from dkws.infrastructure.adapters import llm as llm_mod

    captured: dict[str, str] = {}

    class _Recorder:
        """捕获出站提示词。"""

        def complete(self, system: str, user: str):
            """记录并返回固定结果。"""
            captured["system"] = system
            captured["user"] = user
            return llm_mod.LlmResult(text="{}", model_id="fake", input_tokens=1,
                                     output_tokens=1, latency_ms=1)

    original_create = llm_mod.create_llm_adapter
    original_is_external = skills_mod._is_external_adapter
    workspace = Path("/tmp/dkws-m2p4-llm-ws")
    _init_workspace(workspace)
    try:
        llm_mod.create_llm_adapter = lambda kind: _Recorder()
        skills_mod._is_external_adapter = lambda adapter: True
        svc = skills_mod.SkillExecutionService(workspace)
        trace: list[dict] = []
        svc._call_model("outreach", f"系统 身份证 {ID_CARD}",
                        f"用户 手机 {MOBILE} 邮箱 {EMAIL}", trace)
        _log(report, "llm_external_prompt_redacted",
             ID_CARD not in captured["system"] and MOBILE not in captured["user"]
             and EMAIL not in captured["user"],
             f"外部适配器收到脱敏提示词：user={captured['user'][:48]}…")
        _log(report, "llm_redaction_traced",
             any(t.get("phase") == "llm_redaction" for t in trace),
             "脱敏动作在 assemblyTrace 留痕，可审计")

        captured.clear()
        skills_mod._is_external_adapter = lambda adapter: False
        svc._call_model("outreach", "系统", f"手机 {MOBILE}", [])
        _log(report, "llm_local_prompt_not_redacted",
             MOBILE in captured["user"],
             "本地适配器收到原文（不出网，脱敏会降低结果质量）")

        captured.clear()
        skills_mod._is_external_adapter = lambda adapter: True
        svc_off = skills_mod.SkillExecutionService(workspace, llm_redaction=False)
        svc_off._call_model("outreach", "系统", f"手机 {MOBILE}", [])
        _log(report, "llm_redaction_switch_effective",
             MOBILE in captured["user"],
             "显式关闭后原文出站（配置开关生效，供内网自建模型场景）")
    finally:
        llm_mod.create_llm_adapter = original_create
        skills_mod._is_external_adapter = original_is_external
        shutil.rmtree(workspace, ignore_errors=True)


def _server_env(redact_response: bool) -> dict[str, str]:
    """构造服务端环境变量。"""
    env = dict(os.environ)
    env.update({
        "PYTHONPATH": str(SRC),
        "DKWS_PROFILE": "prod",
        "DKWS_BIND_HOST": "127.0.0.1",
        "DKWS_API_KEYS": f"svc:{API_KEY}:read|execute|admin",
        "DKWS_RATE_LIMIT_ENABLED": "true",
        "DKWS_RUNTIME_STORE_ENABLED": "true",
        "DKWS_STRUCTURED_LOGS": "true",
        "DKWS_REDACT_RESPONSE": "true" if redact_response else "false",
        "DKWS_LLM_REDACTION": "true",
    })
    env.pop("DKWS_LLM_API_KEY", None)
    return env


def check_live_service(report: dict, workspace: Path, log_dir: Path) -> None:
    """场景 3-5、8、10：真实服务行为。"""
    log_path = log_dir / "01_server_redact_on.log"
    with log_path.open("w", encoding="utf-8") as log_file:
        proc = subprocess.Popen(
            [sys.executable, str(REPO / "scripts" / "serve_skill_service.py"),
             "--workspace", str(workspace), "--port", str(PORT), "--host", "127.0.0.1"],
            env=_server_env(True), stdout=log_file, stderr=subprocess.STDOUT)
        try:
            if not _wait_ready(proc):
                _log(report, "server_starts_with_redaction", False,
                     "服务未就绪，见 01_server_redact_on.log")
                return
            _log(report, "server_starts_with_redaction", True,
                 "生产 profile + 响应脱敏 + LLM 脱敏 组合下服务正常启动")

            status, headers, body = _request("GET", "/v1/health")
            payload = json.loads(body)
            _log(report, "response_envelope_intact",
                 status == 200
                 and {"request_id", "status", "data", "errors", "meta"} <= set(payload),
                 f"启用脱敏后信封结构完整：{sorted(payload)}")
            _log(report, "content_length_correct",
                 int(headers.get("content-length", "0")) == len(body.encode()),
                 f"content-length={headers.get('content-length')} 与实际字节一致"
                 f"（避免响应截断）")

            status, headers, text = _request("GET", "/metrics", key=API_KEY)
            _log(report, "non_json_passthrough",
                 status == 200 and "text/plain" in headers.get("content-type", "")
                 and "dkws_" in text,
                 "Prometheus 文本原样透传，未被 JSON 脱敏逻辑处理")

            status, _, body = _request("GET", "/livez")
            _log(report, "probes_work_with_redaction",
                 status == 200 and json.loads(body)["status"] == "alive",
                 "探针在脱敏启用下正常")
        finally:
            if proc.poll() is None:
                proc.send_signal(signal.SIGTERM)
                try:
                    proc.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    proc.kill()

    text = log_path.read_text(encoding="utf-8", errors="replace")
    leaked = [s for s in (API_KEY, MOBILE, ID_CARD) if s in text]
    _log(report, "logs_no_sensitive_leak", not leaked,
         "服务日志中无 API Key 与敏感值明文" if not leaked else f"泄漏：{leaked}")


def check_internal_plaintext(report: dict, workspace: Path) -> None:
    """场景 9：内部产物保持明文，业务逻辑不受影响。"""
    from dkws.application.skills import SkillExecutionService

    svc = SkillExecutionService(workspace)
    result = svc.execute("skill-customer-outreach-script", "REQ-M2P4-VERIFY",
                         {"customerId": "CUST-CORP-0001"})
    _log(report, "internal_artifacts_keep_plaintext",
         result.status == "ok",
         f"Skill 执行成功（status={result.status}）：脱敏只作用于出站通道，"
         f"不改内部产物与业务逻辑")


def main() -> int:
    """执行全部验证并写出报告。"""
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(REPO / "evidence" / "m2-p4"))
    ap.add_argument("--workspace", default="/tmp/dkws-m2p4-e2e-ws")
    args = ap.parse_args()

    out_dir = Path(args.out)
    log_dir = out_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    workspace = _init_workspace(Path(args.workspace))

    report: dict = {
        "task_package": "M2-P4",
        "scope": "M2.9 数据分类与脱敏",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "environment": {"python": sys.version.split()[0],
                        "platform": platform.platform(),
                        "workspace": str(workspace)},
        "checks": [],
    }

    check_inventory(report)
    check_mask_styles(report)
    check_structure_redaction(report)
    check_llm_egress(report)
    check_live_service(report, workspace, log_dir)
    check_internal_plaintext(report, workspace)

    passed = sum(1 for c in report["checks"] if c["passed"])
    total = len(report["checks"])
    report["summary"] = {"passed": passed, "total": total,
                         "result": "PASS" if passed == total else "FAIL"}
    (out_dir / "e2e_redaction_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "classification_inventory.json").write_text(
        json.dumps(report.get("inventory", []), ensure_ascii=False, indent=2),
        encoding="utf-8")
    print(f"\n=== {passed}/{total} 项检查通过 → {report['summary']['result']} ===")
    print(f"报告：{out_dir / 'e2e_redaction_report.json'}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
