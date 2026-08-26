#!/usr/bin/env python3
"""Skill 运行平台端到端验证（D1-D6，模拟 gits 侧 SkillExecutionPort HTTP 调用）。

用法：python skill_e2e.py --base http://127.0.0.1:3080
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request

PASS = []


def request(base: str, method: str, path: str, body: dict | None = None):
    url = base + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode())
        except Exception:
            return e.code, {"status": "skill_error", "errors": [{"message": e.reason}]}


def check(label: str, cond: bool, detail: str = ""):
    PASS.append(cond)
    print(f"  [{'PASS' if cond else 'FAIL'}] {label}" + (f"  {detail}" if detail and not cond else ""))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:3080")
    args = ap.parse_args()
    base = args.base.rstrip("/")

    print("== D1: GET /api/skill/health ==")
    code, body = request(base, "GET", "/api/skill/health")
    check("health 200", code == 200, f"code={code}")
    ids = [s["skillId"] for s in body.get("skills", [])]
    for want in ("skill-customer-outreach-script", "skill-customer-meeting-script"):
        check(f"health 含 {want}", want in ids)
    versions = {s["skillId"]: s["version"] for s in body.get("skills", [])}
    check("版本为 1.0.0", all(v == "1.0.0" for v in versions.values()), str(versions))

    def execute(skill_id, request_id, request_body):
        return request(base, "POST", "/api/skill/execute",
                       {"skillId": skill_id, "requestId": request_id, "request": request_body})

    print("== D2: 两 Skill 执行（结构化结果 + trace + modelCalls）==")
    cases = [
        ("skill-customer-outreach-script", "req-e2e-outreach-1", {
            "customerId": "CUST-CORP-0001",
            "structuredFacts": {"profile": {"name": "示例制造集团", "industry": "装备制造"},
                                "kyc": {"rating": "AA"}, "visitGoals": ["建立联系，介绍综合服务"]},
            "knowledgeContext": "该客户为本地装备制造龙头，近一年营收稳定增长。",
        }),
        ("skill-customer-meeting-script", "req-e2e-meeting-1", {
            "customerId": "CUST-CORP-0001",
            "structuredFacts": {"profile": {"name": "示例制造集团"},
                                "productCandidates": ["供应链金融", "现金管理"],
                                "sensitivePoints": ["担保额度已近上限"]},
            "knowledgeContext": "前期会面中客户对供应链金融表达兴趣。",
        }),
    ]
    for skill_id, rid, req_body in cases:
        code, body = execute(skill_id, rid, req_body)
        ok = body.get("status") == "ok" and isinstance(body.get("data"), dict) \
            and isinstance(body.get("assemblyTrace"), list) \
            and isinstance(body.get("modelCalls"), list) \
            and len(body.get("modelCalls", [])) >= 1
        check(f"{skill_id} 执行 ok+data+trace+modelCalls", ok, f"status={body.get('status')} code={code}")
        if body.get("status") == "skill_error":
            print("     errors:", json.dumps(body.get("errors", []), ensure_ascii=False)[:300])
            print("     trace:", json.dumps(body.get("assemblyTrace", []), ensure_ascii=False)[:300])

    print("== D4: requestId 幂等 + fail-closed ==")
    code1, body1 = execute("skill-customer-outreach-script", "req-idem-1", {
        "customerId": "CUST-X", "structuredFacts": {"profile": {"name": "幂等客户"}}})
    code2, body2 = execute("skill-customer-outreach-script", "req-idem-1", {
        "customerId": "CUST-X", "structuredFacts": {"profile": {"name": "幂等客户"}}})
    check("同 requestId 重放命中幂等（NO_OP）", body2.get("status") == "ok" and
          any(t.get("phase") == "idempotency" for t in body2.get("assemblyTrace", [])),
          f"s1={body1.get('status')} s2={body2.get('status')}")

    print("== D5: modelCalls 元数据 ==")
    code, body = execute("skill-customer-meeting-script", "req-meta-1", {
        "customerId": "CUST-M", "structuredFacts": {"profile": {"name": "元数据客户"}}})
    mc = body.get("modelCalls", [{}])[0]
    check("modelCalls 含 model", bool(mc.get("model")), str(mc))
    check("modelCalls 含 latencyMs>=0", isinstance(mc.get("latencyMs"), (int, float)) and mc["latencyMs"] >= 0)
    check("modelCalls 含 tokens>=0", isinstance(mc.get("inputTokens"), (int, float))
          and isinstance(mc.get("outputTokens"), (int, float)))

    print("== D6: 错误路径 ==")
    code, body = request(base, "POST", "/api/skill/execute",
                         {"skillId": "skill-unknown", "requestId": "req-404", "request": {}})
    check("未知 skillId → 404", code == 404, f"code={code}")
    code, body = request(base, "POST", "/api/skill/execute", {})
    # FastAPI 对缺必填字段返回 422（请求合同错误，§13.6 SCHEMA_VALIDATION_FAILED）
    check("缺字段 → 422 合同错误拒绝", code == 422, f"code={code}")

    print()
    total, good = len(PASS), sum(PASS)
    print(f"结果: {good}/{total} PASS")
    sys.exit(0 if good == total else 1)


if __name__ == "__main__":
    main()
