#!/usr/bin/env python3
"""KERT API 端点全面验证脚本.

验证 KERT (http://127.0.0.1:8106) 的所有 skill API 端点，
确保它们能正确响应并返回预期格式。

用法:
    python tests/e2e/kert_api_validation.py
    python tests/e2e/kert_api_validation.py --base-url http://127.0.0.1:8106
"""

from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass, field
from typing import Any

import urllib.request
import urllib.error
import urllib.parse

# ── 配置 ──────────────────────────────────────────────────────────────────

DEFAULT_BASE_URL = "http://127.0.0.1:8106"
TEST_CUSTOMER_ID = "CUST-VALIDATION-001"
TIMEOUT_SECONDS = 120  # SP-20 等长任务可能需要较长时间


# ── 数据结构 ──────────────────────────────────────────────────────────────

@dataclass
class EndpointResult:
    """单个端点测试结果."""
    endpoint: str
    method: str
    status_code: int = 0
    response_body: Any = None
    error: str = ""
    elapsed_ms: float = 0.0
    passed: bool = False
    notes: str = ""


@dataclass
class ValidationResult:
    """整体验证结果."""
    base_url: str
    timestamp: str = ""
    endpoint_results: list[EndpointResult] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)
    summary: dict = field(default_factory=dict)

    def add(self, r: EndpointResult) -> None:
        self.endpoint_results.append(r)
        if not r.passed:
            self.issues.append(
                f"[FAIL] {r.method} {r.endpoint} → {r.status_code} "
                f"(error: {r.error or r.notes})"
            )


# ── HTTP 工具 ─────────────────────────────────────────────────────────────

def _request(
    base_url: str,
    method: str,
    path: str,
    body: dict | None = None,
    timeout: int = TIMEOUT_SECONDS,
) -> tuple[int, Any, float]:
    """发送 HTTP 请求，返回 (status_code, parsed_json_or_None, elapsed_ms)."""
    url = f"{base_url}{path}"
    data = None
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")

    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json")

    start = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            elapsed = (time.monotonic() - start) * 1000
            raw = resp.read().decode("utf-8")
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                parsed = raw
            return resp.status, parsed, elapsed
    except urllib.error.HTTPError as e:
        elapsed = (time.monotonic() - start) * 1000
        raw = e.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = raw
        return e.code, parsed, elapsed
    except Exception:
        elapsed = (time.monotonic() - start) * 1000
        return 0, None, elapsed


# ── 测试用例 ──────────────────────────────────────────────────────────────

def test_health(base_url: str, vr: ValidationResult) -> None:
    """GET /api/skill/health — 健康检查 + skill 列表."""
    r = EndpointResult(endpoint="/api/skill/health", method="GET")
    r.status_code, r.response_body, r.elapsed_ms = _request(base_url, "GET", "/api/skill/health")
    r.passed = r.status_code == 200
    if r.passed and isinstance(r.response_body, dict):
        skills = r.response_body.get("skills", [])
        r.notes = f"service={r.response_body.get('service')}, skills_count={len(skills)}"
    vr.add(r)


def test_gates(base_url: str, vr: ValidationResult) -> None:
    """GET /api/skill/gates/{customerId} — 获取客户 gates."""
    path = f"/api/skill/gates/{TEST_CUSTOMER_ID}"
    r = EndpointResult(endpoint=path, method="GET")
    r.status_code, r.response_body, r.elapsed_ms = _request(base_url, "GET", path)
    r.passed = r.status_code == 200
    if r.passed and isinstance(r.response_body, dict):
        gates = r.response_body.get("gates", [])
        r.notes = f"customerId={r.response_body.get('customerId')}, gates_count={len(gates)}"
        # 验证 gates 格式（实际字段: gateId/name/sequence/must/forbidden/assetPath）
        if gates:
            g = gates[0]
            expected_keys = {"gateId", "name", "sequence"}
            missing = expected_keys - set(g.keys())
            if missing:
                r.passed = False
                r.notes += f"; gate 缺少字段: {missing}"
    vr.add(r)


def test_gate_audit(base_url: str, vr: ValidationResult) -> None:
    """POST /api/skill/gates/audit — 闸门审计."""
    body = {
        "customerId": TEST_CUSTOMER_ID,
        "gate": "G0",
        "decision": "pass",
        "decidedBy": "kert-validator",
        "reason": "automated validation test",
    }
    r = EndpointResult(endpoint="/api/skill/gates/audit", method="POST")
    r.status_code, r.response_body, r.elapsed_ms = _request(
        base_url, "POST", "/api/skill/gates/audit", body
    )
    r.passed = r.status_code == 200
    if r.passed and isinstance(r.response_body, dict):
        r.notes = f"recorded={r.response_body.get('recorded')}, gate={r.response_body.get('gate')}"
    vr.add(r)


def test_job_status(base_url: str, vr: ValidationResult) -> None:
    """GET /v1/jobs/{jobId} — 异步任务状态查询（先触发异步任务再查询）."""
    # 1) 触发异步 SP-20
    async_body = {
        "skillId": "SP-20",
        "request": {"customerId": TEST_CUSTOMER_ID},
        "context": {
            "customerId": TEST_CUSTOMER_ID,
            "customerName": "验证测试公司",
            "industry": "制造业",
            "enterpriseData": {"basicInfo": {"registeredCapital": "1000万"}},
        },
        "async": True,
    }
    r_async = EndpointResult(endpoint="/api/skill/execute (async SP-20)", method="POST")
    r_async.status_code, r_async.response_body, r_async.elapsed_ms = _request(
        base_url, "POST", "/api/skill/execute", async_body
    )
    r_async.passed = r_async.status_code == 202
    if r_async.passed and isinstance(r_async.response_body, dict):
        job_id = r_async.response_body.get("jobId", "")
        r_async.notes = f"jobId={job_id}, status={r_async.response_body.get('status')}"
    vr.add(r_async)

    # 2) 查询 job 状态
    job_id = ""
    if isinstance(r_async.response_body, dict):
        job_id = r_async.response_body.get("jobId", "")
    if job_id:
        path = f"/v1/jobs/{job_id}"
        r_job = EndpointResult(endpoint=path, method="GET")
        r_job.status_code, r_job.response_body, r_job.elapsed_ms = _request(
            base_url, "GET", path
        )
        r_job.passed = r_job.status_code == 200
        if r_job.passed and isinstance(r_job.response_body, dict):
            data = r_job.response_body.get("data", {})
            r_job.notes = (
                f"job_status={data.get('status')}, "
                f"progress={data.get('progress')}"
            )
        vr.add(r_job)
    else:
        r_job = EndpointResult(endpoint="/v1/jobs/{jobId}", method="GET")
        r_job.passed = False
        r_job.error = "无法获取 jobId，跳过 job 状态查询"
        vr.add(r_job)

    # 3) 查询不存在的 job
    r_404 = EndpointResult(endpoint="/v1/jobs/NONEXISTENT-JOB", method="GET")
    r_404.status_code, r_404.response_body, r_404.elapsed_ms = _request(
        base_url, "GET", "/v1/jobs/NONEXISTENT-JOB"
    )
    r_404.passed = r_404.status_code == 404
    r_404.notes = "期望 404"
    vr.add(r_404)


def test_report(base_url: str, vr: ValidationResult) -> None:
    """GET /api/skill/report/{requestId} — 报告端点."""
    # 先执行一个 skill 获取 requestId
    body = {
        "skillId": "skill-customer-outreach-script",
        "request": {"customerId": TEST_CUSTOMER_ID},
    }
    _, exec_result, _ = _request(base_url, "POST", "/api/skill/execute", body)

    request_id = ""
    if isinstance(exec_result, dict):
        request_id = exec_result.get("requestId", "")

    if request_id:
        path = f"/api/skill/report/{request_id}"
        r = EndpointResult(endpoint=path, method="GET")
        r.status_code, r.response_body, r.elapsed_ms = _request(base_url, "GET", path)
        r.passed = r.status_code == 200
        if r.passed:
            # 报告端点返回 HTML
            is_html = isinstance(r.response_body, str) and "<html" in r.response_body.lower()
            r.notes = f"返回 HTML 报告: {is_html}"
        vr.add(r)
    else:
        r = EndpointResult(endpoint="/api/skill/report/{requestId}", method="GET")
        r.passed = False
        r.error = "无法获取 requestId，跳过报告端点测试"
        vr.add(r)

    # 不存在的 requestId
    r_404 = EndpointResult(endpoint="/api/skill/report/NONEXISTENT", method="GET")
    r_404.status_code, r_404.response_body, r_404.elapsed_ms = _request(
        base_url, "GET", "/api/skill/report/NONEXISTENT"
    )
    r_404.passed = r_404.status_code == 404
    r_404.notes = "期望 404"
    vr.add(r_404)


# ── Skill 执行测试 ────────────────────────────────────────────────────────

# 所有 skill 的测试配置
SKILL_TEST_CASES: list[dict[str, Any]] = [
    # ── GITS 场景核心 skill ──
    {
        "skillId": "SP-20",
        "name": "服务建议书",
        "request": {"customerId": TEST_CUSTOMER_ID},
        "context": {
            "customerId": TEST_CUSTOMER_ID,
            "customerName": "验证测试公司",
            "industry": "制造业",
            "enterpriseData": {"basicInfo": {"registeredCapital": "1000万"}},
        },
        "expect_status": "ok",
        "expect_http": 200,
        "notes": "SP-20 需要 context.enterpriseData，否则报 enterpriseData 缺失",
    },
    {
        "skillId": "SP-21",
        "name": "交互记忆抽取",
        "request": {
            "customerId": TEST_CUSTOMER_ID,
            "interactionId": "INT-VAL-001",
            "interactionContent": "客户对供应链融资产品表示兴趣，希望了解授信额度和利率",
        },
        "expect_status": "ok",
        "expect_http": 200,
        "notes": "SP-21 需要 interactionId + interactionContent",
    },
    {
        "skillId": "skill-customer-previsit-report",
        "name": "客户准入(R1)/访前报告",
        "request": {"customerId": TEST_CUSTOMER_ID},
        "expect_status": "exit_policy_no_new_evidence",
        "expect_http": 200,
        "notes": "R1 访前报告，知识库无数据时返回 exit_policy_no_new_evidence（正常退出策略）",
    },
    {
        "skillId": "bank-front-supply-chain-graph",
        "name": "供应链图谱",
        "request": {"customerId": TEST_CUSTOMER_ID},
        "expect_status": "ok",
        "expect_http": 200,
        "notes": "供应链图谱，知识库无数据时 buildStatus=partial",
    },
    # ── 其他 bank-front skill ──
    {
        "skillId": "skill-customer-outreach-script",
        "name": "客户外联脚本",
        "request": {"customerId": TEST_CUSTOMER_ID},
        "expect_status": "ok",
        "expect_http": 200,
    },
    {
        "skillId": "skill-customer-meeting-script",
        "name": "客户会面脚本",
        "request": {"customerId": TEST_CUSTOMER_ID},
        "expect_status": "ok",
        "expect_http": 200,
    },
    {
        "skillId": "bank-front-commitment-script",
        "name": "承诺话术",
        "request": {"customerId": TEST_CUSTOMER_ID},
        "expect_status": "ok",
        "expect_http": 200,
    },
    {
        "skillId": "bank-front-eight-dimension",
        "name": "八维研判",
        "request": {"customerId": TEST_CUSTOMER_ID},
        "expect_status": "ok",
        "expect_http": 200,
        "notes": "缺少 industryCode 时 status=insufficient",
    },
    {
        "skillId": "bank-front-fact-reconciliation",
        "name": "事实对账",
        "request": {"customerId": TEST_CUSTOMER_ID},
        "expect_status": "ok",
        "expect_http": 200,
    },
    {
        "skillId": "bank-front-kyc-gap-check",
        "name": "KYC 缺口检查",
        "request": {"customerId": TEST_CUSTOMER_ID},
        "expect_status": "ok",
        "expect_http": 200,
    },
    {
        "skillId": "bank-front-product-recommendation",
        "name": "产品推荐",
        "request": {"customerId": TEST_CUSTOMER_ID},
        "expect_status": "ok",
        "expect_http": 200,
    },
    {
        "skillId": "bank-front-report-assembler",
        "name": "作战单组装",
        "request": {"customerId": TEST_CUSTOMER_ID},
        "expect_status": "ok",
        "expect_http": 200,
        "notes": "综合组装，耗时较长",
    },
]


def test_skill_execute(base_url: str, vr: ValidationResult) -> None:
    """逐一执行所有 skill，记录结果."""
    for tc in SKILL_TEST_CASES:
        skill_id = tc["skillId"]
        name = tc.get("name", skill_id)
        body: dict[str, Any] = {
            "skillId": skill_id,
            "request": tc.get("request", {}),
        }
        if tc.get("context"):
            body["context"] = tc["context"]

        r = EndpointResult(
            endpoint=f"/api/skill/execute ({skill_id} / {name})",
            method="POST",
        )
        r.status_code, r.response_body, r.elapsed_ms = _request(
            base_url, "POST", "/api/skill/execute", body
        )

        expect_http = tc.get("expect_http", 200)
        expect_status = tc.get("expect_status", "ok")

        # HTTP 状态码检查
        http_ok = r.status_code == expect_http

        # 业务状态检查
        biz_ok = True
        if isinstance(r.response_body, dict):
            actual_status = r.response_body.get("status", "")
            if expect_status and actual_status != expect_status:
                biz_ok = False
                r.notes = f"业务状态: {actual_status} (期望: {expect_status})"
            else:
                # 提取关键信息
                errors = r.response_body.get("errors", [])
                model_calls = r.response_body.get("modelCalls", [])
                total_latency = sum(m.get("latencyMs", 0) for m in model_calls)
                r.notes = (
                    f"requestId={r.response_body.get('requestId', '')}, "
                    f"model_calls={len(model_calls)}, "
                    f"model_latency={total_latency:.0f}ms"
                )
                if errors:
                    r.notes += f", errors={errors}"

        r.passed = http_ok and biz_ok
        if not http_ok:
            r.error = f"HTTP {r.status_code} != {expect_http}"

        vr.add(r)


def test_unknown_skill(base_url: str, vr: ValidationResult) -> None:
    """执行不存在的 skill，期望 404."""
    body = {"skillId": "NONEXISTENT-SKILL", "request": {"customerId": TEST_CUSTOMER_ID}}
    r = EndpointResult(endpoint="/api/skill/execute (UNKNOWN)", method="POST")
    r.status_code, r.response_body, r.elapsed_ms = _request(
        base_url, "POST", "/api/skill/execute", body
    )
    r.passed = r.status_code == 404
    r.notes = "期望 404 UNKNOWN_SKILL"
    vr.add(r)


# ── 主流程 ────────────────────────────────────────────────────────────────

def run_validation(base_url: str) -> ValidationResult:
    """执行全部验证，返回结果."""
    vr = ValidationResult(
        base_url=base_url,
        timestamp=time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    )

    print(f"{'='*70}")
    print(f"KERT API 验证 — {base_url}")
    print(f"时间: {vr.timestamp}")
    print(f"{'='*70}\n")

    # 1. 基础端点
    print("── 1. 基础端点 ──")
    test_health(base_url, vr)
    test_gates(base_url, vr)
    test_gate_audit(base_url, vr)
    print()

    # 2. Skill 执行
    print("── 2. Skill 执行 ──")
    test_skill_execute(base_url, vr)
    print()

    # 3. 异步模式
    print("── 3. 异步模式 ──")
    test_job_status(base_url, vr)
    print()

    # 4. 报告端点
    print("── 4. 报告端点 ──")
    test_report(base_url, vr)
    print()

    # 5. 异常场景
    print("── 5. 异常场景 ──")
    test_unknown_skill(base_url, vr)
    print()

    # 汇总
    total = len(vr.endpoint_results)
    passed = sum(1 for r in vr.endpoint_results if r.passed)
    failed = total - passed
    vr.summary = {
        "total": total,
        "passed": passed,
        "failed": failed,
        "pass_rate": f"{passed/total*100:.1f}%" if total else "N/A",
    }

    print(f"{'='*70}")
    print(f"验证结果汇总: {passed}/{total} PASS ({vr.summary['pass_rate']})")
    if vr.issues:
        print(f"\n发现 {len(vr.issues)} 个问题:")
        for issue in vr.issues:
            print(f"  {issue}")
    print(f"{'='*70}")

    return vr


def print_detailed_report(vr: ValidationResult) -> None:
    """打印详细报告."""
    print(f"\n{'='*70}")
    print("详细端点报告")
    print(f"{'='*70}\n")

    for i, r in enumerate(vr.endpoint_results, 1):
        status_icon = "PASS" if r.passed else "FAIL"
        print(f"[{i}] {status_icon} {r.method} {r.endpoint}")
        print(f"    HTTP {r.status_code} | 耗时 {r.elapsed_ms:.0f}ms")
        if r.notes:
            print(f"    备注: {r.notes}")
        if r.error:
            print(f"    错误: {r.error}")
        # 打印响应体摘要
        if isinstance(r.response_body, dict):
            # 精简输出
            summary_keys = ["status", "requestId", "jobId", "customerId", "recorded"]
            parts = []
            for k in summary_keys:
                if k in r.response_body:
                    parts.append(f"{k}={r.response_body[k]}")
            if parts:
                print(f"    响应: {', '.join(parts)}")
            # 对于 skill 执行，打印 errors 和 modelCalls 摘要
            errors = r.response_body.get("errors", [])
            if errors:
                print(f"    errors: {errors}")
            model_calls = r.response_body.get("modelCalls", [])
            if model_calls:
                for mc in model_calls:
                    print(
                        f"    model: {mc.get('model')} | "
                        f"in={mc.get('inputTokens',0)} out={mc.get('outputTokens',0)} | "
                        f"latency={mc.get('latencyMs',0):.0f}ms"
                    )
        print()


def main() -> int:
    """主入口."""
    import argparse

    parser = argparse.ArgumentParser(description="KERT API 端点验证")
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help=f"KERT 服务地址 (默认: {DEFAULT_BASE_URL})",
    )
    parser.add_argument(
        "--json-output",
        default="",
        help="将完整结果写入 JSON 文件",
    )
    parser.add_argument(
        "--detailed",
        action="store_true",
        help="打印详细报告",
    )
    args = parser.parse_args()

    vr = run_validation(args.base_url)

    if args.detailed:
        print_detailed_report(vr)

    # JSON 输出
    if args.json_output:
        output = {
            "timestamp": vr.timestamp,
            "base_url": vr.base_url,
            "summary": vr.summary,
            "issues": vr.issues,
            "endpoints": [
                {
                    "endpoint": r.endpoint,
                    "method": r.method,
                    "status_code": r.status_code,
                    "elapsed_ms": round(r.elapsed_ms, 1),
                    "passed": r.passed,
                    "notes": r.notes,
                    "error": r.error,
                    "response_body": r.response_body if isinstance(r.response_body, (dict, list)) else str(r.response_body)[:500],
                }
                for r in vr.endpoint_results
            ],
        }
        with open(args.json_output, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
        print(f"\n结果已写入: {args.json_output}")

    # 返回码：全部通过返回 0，否则返回 1
    return 0 if not vr.issues else 1


if __name__ == "__main__":
    sys.exit(main())
