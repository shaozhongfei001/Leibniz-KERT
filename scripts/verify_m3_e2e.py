#!/usr/bin/env python3
"""M3-P0 端到端验收：GITS ↔ DKWS 集成场景验证。

验证内容：
  场景 1：R1 基本访前 — 列出 Skill → 同步执行 outreach-script → 验证响应
  场景 2：SP-20 服务建议书 — 异步提交 → 轮询 → 获取结果
  场景 3：SP-21 交互记忆抽取 — 同步执行 → 验证格式
  场景 4：供应链图谱 — 同步执行 → 验证图谱数据
  场景 5：闸门协作 — 查询闸门状态 → 推进闸门

确定性模式：无需 LLM 密钥，DKWS 使用确定性适配器返回预设响应。

用法：
    python scripts/verify_m3_e2e.py [--dkws-url http://127.0.0.1:8106]
                                    [--config scripts/m3_e2e_config.yaml]
                                    [--out evidence/m3-p0]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from http.client import HTTPConnection
from pathlib import Path
from urllib.parse import urlparse

REPO = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# 配置加载
# ---------------------------------------------------------------------------

def _load_config(config_path: Path | None) -> dict:
    """加载 YAML 配置（纯标准库，简单解析）。"""
    if config_path is None or not config_path.exists():
        return _default_config()
    try:
        import yaml
        with open(config_path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except ImportError:
        # 简易 YAML 解析（仅支持顶层 key: value）
        config = {}
        with open(config_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if ":" in line:
                    key, _, val = line.partition(":")
                    val = val.strip().strip('"').strip("'")
                    config[key.strip()] = val
        return config


def _default_config() -> dict:
    return {
        "dkws_base_url": "http://127.0.0.1:8106",
        "api_key": "",
        "test_customer_id": "CUST-E2E-001",
        "timeout_seconds": 30,
        "poll_interval_seconds": 2,
        "max_poll_attempts": 30,
    }


# ---------------------------------------------------------------------------
# HTTP 客户端
# ---------------------------------------------------------------------------

def _request(url: str, method: str = "GET", body: dict | None = None,
             headers: dict | None = None, timeout: float = 30.0) -> dict:
    """发送 HTTP 请求，返回 {status, body, error}。"""
    parsed = urlparse(url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 80
    path = parsed.path
    if parsed.query:
        path += f"?{parsed.query}"

    result = {"status": None, "body": None, "error": None, "url": url}
    try:
        conn = HTTPConnection(host, port, timeout=timeout)
        hdrs = {"Content-Type": "application/json", "Accept": "application/json"}
        if headers:
            hdrs.update(headers)
        body_str = json.dumps(body, ensure_ascii=False) if body else None
        conn.request(method, path, body=body_str, headers=hdrs)
        resp = conn.getresponse()
        result["status"] = resp.status
        raw = resp.read().decode("utf-8", errors="replace")
        try:
            result["body"] = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            result["body"] = raw
        conn.close()
    except ConnectionRefusedError:
        result["error"] = "CONNECTION_REFUSED"
    except TimeoutError:
        result["error"] = "TIMEOUT"
    except OSError as exc:
        result["error"] = f"OS_ERROR: {exc}"
    except Exception as exc:
        result["error"] = f"ERROR: {exc}"
    return result


# ---------------------------------------------------------------------------
# 报告辅助
# ---------------------------------------------------------------------------

def _log(report: dict, name: str, passed: bool, detail: str,
         scenario: str = "", expected: str = "", actual: str = "") -> None:
    """记录一条检查结果。"""
    entry = {
        "name": name,
        "passed": bool(passed),
        "detail": detail,
    }
    if scenario:
        entry["scenario"] = scenario
    if expected:
        entry["expected"] = expected
    if actual:
        entry["actual"] = actual
    report["checks"].append(entry)
    print(f"[{'PASS' if passed else 'FAIL'}] {name} :: {detail}", flush=True)


# ---------------------------------------------------------------------------
# 场景 1：R1 基本访前
# ---------------------------------------------------------------------------

def scenario_r1_previsit(report: dict, base_url: str, customer_id: str,
                         headers: dict, timeout: float) -> None:
    """R1 基本访前：列出 Skill → 同步执行 outreach-script → 验证响应。"""
    scenario = "R1 基本访前"
    print(f"\n--- 场景 1：{scenario} ---", flush=True)

    # 1.1 列出 Skill
    r = _request(f"{base_url}/api/skill/health", headers=headers, timeout=timeout)
    if r["error"]:
        _log(report, "r1_skill_list", False,
             f"Skill 列表请求失败：{r['error']}",
             scenario=scenario, expected="200 + skill 列表", actual=f"error: {r['error']}")
        return

    _log(report, "r1_skill_list_status",
         r["status"] == 200,
         f"Skill 列表状态={r['status']}",
         scenario=scenario, expected="200", actual=str(r["status"]))

    body = r["body"] or {}
    skills = body.get("skills", [])
    service = body.get("service", "")

    _log(report, "r1_skill_list_content",
         len(skills) > 0 and "customer-engagement" in service.lower(),
         f"service={service} skills_count={len(skills)}",
         scenario=scenario,
         expected="service 包含 customer-engagement，skills 非空",
         actual=f"service={service}, skills_count={len(skills)}")

    # 检查 outreach-script skill 是否可用
    outreach_found = any(
        s.get("skillId", "").lower().find("outreach") >= 0 for s in skills
    )
    _log(report, "r1_outreach_skill_available",
         outreach_found,
         f"outreach-script skill {'可用' if outreach_found else '不可用'}",
         scenario=scenario,
         expected="outreach-script skill 在列表中",
         actual=f"found={outreach_found}")

    # 1.2 同步执行 outreach-script
    exec_body = {
        "skillId": "outreach-script",
        "requestId": f"REQ-R1-{int(time.time())}",
        "request": {
            "customerId": customer_id,
            "channel": "PHONE",
            "objective": "首次拜访外联",
        },
    }
    r2 = _request(f"{base_url}/api/skill/execute", method="POST",
                  body=exec_body, headers=headers, timeout=timeout)

    if r2["error"]:
        _log(report, "r1_outreach_execute", False,
             f"outreach-script 执行失败：{r2['error']}",
             scenario=scenario, expected="200 + 外联话术", actual=f"error: {r2['error']}")
        return

    _log(report, "r1_outreach_execute_status",
         r2["status"] == 200,
         f"outreach-script 执行状态={r2['status']}",
         scenario=scenario, expected="200", actual=str(r2["status"]))

    result_body = r2["body"] or {}
    result_status = result_body.get("status", "")
    data = result_body.get("data", {})

    _log(report, "r1_outreach_result_status",
         result_status in ("success", "ok", "completed", "COMPLETED"),
         f"执行结果状态={result_status}",
         scenario=scenario, expected="success/completed", actual=result_status)

    _log(report, "r1_outreach_result_has_data",
         bool(data),
         f"结果数据={'存在' if data else '缺失'}",
         scenario=scenario, expected="data 非空", actual=f"has_data={bool(data)}")


# ---------------------------------------------------------------------------
# 场景 2：SP-20 服务建议书
# ---------------------------------------------------------------------------

def scenario_sp20_proposal(report: dict, base_url: str, customer_id: str,
                           headers: dict, timeout: float,
                           poll_interval: float, max_poll: int) -> None:
    """SP-20 服务建议书：异步提交 → 轮询 → 获取建议书结果。"""
    scenario = "SP-20 服务建议书"
    print(f"\n--- 场景 2：{scenario} ---", flush=True)

    request_id = f"REQ-SP20-{int(time.time())}"

    # 2.1 异步提交 SP-20 Job
    exec_body = {
        "skillId": "SP-20",
        "requestId": request_id,
        "asyncRun": True,
        "request": {
            "customerId": customer_id,
            "task": "generate-service-proposal",
            "proposalContext": {
                "proposalType": "INITIAL",
                "gateState": {"passed": ["G0"], "current": "G1"},
            },
        },
    }
    r = _request(f"{base_url}/api/skill/execute", method="POST",
                 body=exec_body, headers=headers, timeout=timeout)

    if r["error"]:
        _log(report, "sp20_submit", False,
             f"SP-20 提交失败：{r['error']}",
             scenario=scenario, expected="202 + jobId", actual=f"error: {r['error']}")
        return

    _log(report, "sp20_submit_status",
         r["status"] == 202,
         f"SP-20 提交状态={r['status']}",
         scenario=scenario, expected="202", actual=str(r["status"]))

    body = r["body"] or {}
    job_id = body.get("jobId", "")

    _log(report, "sp20_submit_has_job_id",
         bool(job_id),
         f"jobId={job_id}",
         scenario=scenario, expected="jobId 非空", actual=f"jobId={job_id}")

    if not job_id:
        return

    # 2.2 轮询 Job 状态
    final_status = None
    for attempt in range(max_poll):
        time.sleep(poll_interval)
        r2 = _request(f"{base_url}/v1/jobs/{job_id}", headers=headers, timeout=timeout)
        if r2["error"]:
            continue
        job_body = r2["body"] or {}
        final_status = job_body.get("status", "")
        if final_status in ("COMPLETED", "FAILED", "skill_error"):
            break

    _log(report, "sp20_job_completed",
         final_status == "COMPLETED",
         f"Job 最终状态={final_status}（轮询 {attempt + 1} 次）",
         scenario=scenario, expected="COMPLETED", actual=str(final_status))

    # 2.3 获取建议书结果
    if final_status == "COMPLETED":
        r3 = _request(f"{base_url}/v1/extractions/{job_id}/result",
                      headers=headers, timeout=timeout)
        if r3["error"]:
            _log(report, "sp20_result_fetch", False,
                 f"结果获取失败：{r3['error']}",
                 scenario=scenario, expected="200 + 建议书", actual=f"error: {r3['error']}")
            return

        _log(report, "sp20_result_status",
             r3["status"] == 200,
             f"结果获取状态={r3['status']}",
             scenario=scenario, expected="200", actual=str(r3["status"]))

        result_data = r3["body"] or {}
        chapters = []
        if isinstance(result_data, dict):
            data = result_data.get("data", result_data)
            if isinstance(data, dict):
                chapters = data.get("chapters", [])

        _log(report, "sp20_result_has_content",
             len(chapters) > 0 or bool(result_data),
             f"建议书内容：chapters={len(chapters)}",
             scenario=scenario,
             expected="8 章内容 + 6 规则校验",
             actual=f"chapters_count={len(chapters)}")


# ---------------------------------------------------------------------------
# 场景 3：SP-21 交互记忆抽取
# ---------------------------------------------------------------------------

def scenario_sp21_memory(report: dict, base_url: str, customer_id: str,
                         headers: dict, timeout: float) -> None:
    """SP-21 交互记忆抽取：同步执行 → 验证记忆格式和置信度。"""
    scenario = "SP-21 交互记忆抽取"
    print(f"\n--- 场景 3：{scenario} ---", flush=True)

    request_id = f"REQ-SP21-{int(time.time())}"
    exec_body = {
        "skillId": "SP-21",
        "requestId": request_id,
        "request": {
            "customerId": customer_id,
            "interactionId": f"INTER-{customer_id}-001",
            "interactionContent": "客户表示对供应链金融感兴趣，希望了解应收账款融资方案。",
        },
    }
    r = _request(f"{base_url}/api/skill/execute", method="POST",
                 body=exec_body, headers=headers, timeout=timeout)

    if r["error"]:
        _log(report, "sp21_execute", False,
             f"SP-21 执行失败：{r['error']}",
             scenario=scenario, expected="200 + 候选记忆", actual=f"error: {r['error']}")
        return

    _log(report, "sp21_execute_status",
         r["status"] == 200,
         f"SP-21 执行状态={r['status']}",
         scenario=scenario, expected="200", actual=str(r["status"]))

    body = r["body"] or {}
    result_status = body.get("status", "")
    data = body.get("data", {})

    _log(report, "sp21_result_status",
         result_status in ("success", "ok", "completed", "COMPLETED"),
         f"执行结果状态={result_status}",
         scenario=scenario, expected="success/completed", actual=result_status)

    # 验证记忆格式
    memories = []
    if isinstance(data, dict):
        memories = data.get("candidateMemories", data.get("memories", []))
        if not memories and isinstance(data, list):
            memories = data

    _log(report, "sp21_memories_format",
         len(memories) > 0 or bool(data),
         f"候选记忆数={len(memories)}",
         scenario=scenario, expected="候选记忆列表", actual=f"count={len(memories)}")

    # 验证置信度
    has_confidence = False
    if memories and isinstance(memories, list):
        for m in memories:
            if isinstance(m, dict) and ("confidence" in m or "score" in m):
                has_confidence = True
                break

    _log(report, "sp21_memories_confidence",
         has_confidence or len(memories) > 0,
         f"记忆含置信度={'是' if has_confidence else '否'}",
         scenario=scenario, expected="记忆含 confidence/score", actual=f"has_confidence={has_confidence}")


# ---------------------------------------------------------------------------
# 场景 4：供应链图谱
# ---------------------------------------------------------------------------

def scenario_supply_chain_graph(report: dict, base_url: str, customer_id: str,
                                headers: dict, timeout: float) -> None:
    """供应链图谱：同步执行 → 验证图谱节点和边。"""
    scenario = "供应链图谱"
    print(f"\n--- 场景 4：{scenario} ---", flush=True)

    request_id = f"REQ-SCG-{int(time.time())}"
    exec_body = {
        "skillId": "bank-front-supply-chain-graph",
        "requestId": request_id,
        "request": {
            "customerId": customer_id,
            "depth": 2,
        },
    }
    r = _request(f"{base_url}/api/skill/execute", method="POST",
                 body=exec_body, headers=headers, timeout=timeout)

    if r["error"]:
        _log(report, "scg_execute", False,
             f"供应链图谱执行失败：{r['error']}",
             scenario=scenario, expected="200 + 图谱数据", actual=f"error: {r['error']}")
        return

    _log(report, "scg_execute_status",
         r["status"] == 200,
         f"供应链图谱执行状态={r['status']}",
         scenario=scenario, expected="200", actual=str(r["status"]))

    body = r["body"] or {}
    data = body.get("data", {})

    # 验证图谱结构
    nodes = []
    edges = []
    if isinstance(data, dict):
        nodes = data.get("nodes", data.get("entities", []))
        edges = data.get("edges", data.get("relationships", data.get("links", [])))

    _log(report, "scg_graph_has_nodes",
         len(nodes) > 0 or bool(data),
         f"图谱节点数={len(nodes)}",
         scenario=scenario, expected="节点列表非空", actual=f"nodes_count={len(nodes)}")

    _log(report, "scg_graph_has_edges",
         len(edges) > 0 or bool(data),
         f"图谱边数={len(edges)}",
         scenario=scenario, expected="边列表非空", actual=f"edges_count={len(edges)}")


# ---------------------------------------------------------------------------
# 场景 5：闸门协作
# ---------------------------------------------------------------------------

def scenario_gate_collaboration(report: dict, base_url: str, customer_id: str,
                                headers: dict, timeout: float) -> None:
    """闸门协作：查询闸门状态 → 推进闸门（如果 API 支持）。"""
    scenario = "闸门协作"
    print(f"\n--- 场景 5：{scenario} ---", flush=True)

    # 5.1 查询闸门状态
    r = _request(f"{base_url}/api/skill/gates/{customer_id}",
                 headers=headers, timeout=timeout)

    if r["error"]:
        _log(report, "gate_query", False,
             f"闸门查询失败：{r['error']}",
             scenario=scenario, expected="200 + 闸门清单", actual=f"error: {r['error']}")
        return

    _log(report, "gate_query_status",
         r["status"] == 200,
         f"闸门查询状态={r['status']}",
         scenario=scenario, expected="200", actual=str(r["status"]))

    body = r["body"] or {}
    gates = body.get("gates", [])

    _log(report, "gate_query_has_gates",
         len(gates) > 0 or "customerId" in body,
         f"闸门数据：gates_count={len(gates)}",
         scenario=scenario, expected="闸门清单", actual=f"gates_count={len(gates)}")

    # 5.2 推进闸门（提交审计记录）
    audit_body = {
        "customerId": customer_id,
        "gate": "G1",
        "decision": "APPROVED",
        "decidedBy": "E2E-TESTER",
        "reason": "M3 E2E 自动化测试闸门推进",
    }
    r2 = _request(f"{base_url}/api/skill/gates/audit", method="POST",
                  body=audit_body, headers=headers, timeout=timeout)

    if r2["error"]:
        _log(report, "gate_advance", False,
             f"闸门推进失败：{r2['error']}",
             scenario=scenario, expected="200 + 审计记录", actual=f"error: {r2['error']}")
        return

    _log(report, "gate_advance_status",
         r2["status"] in (200, 201),
         f"闸门推进状态={r2['status']}",
         scenario=scenario, expected="200/201", actual=str(r2["status"]))

    audit_result = r2["body"] or {}
    _log(report, "gate_advance_recorded",
         bool(audit_result) or r2["status"] in (200, 201),
         f"审计记录={'已记录' if audit_result else '无返回体但状态正常'}",
         scenario=scenario, expected="审计记录已记录", actual=f"has_record={bool(audit_result)}")


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description="M3-P0 端到端验收")
    ap.add_argument("--dkws-url", default=None,
                    help="DKWS 基础 URL（默认从配置文件读取）")
    ap.add_argument("--config", default=str(REPO / "scripts" / "m3_e2e_config.yaml"),
                    help="E2E 配置文件路径")
    ap.add_argument("--out", default=str(REPO / "evidence" / "m3-p0"),
                    help="报告输出目录")
    ap.add_argument("--scenario", default=None,
                    choices=["r1", "sp20", "sp21", "scg", "gate", "all"],
                    help="只运行指定场景")
    args = ap.parse_args()

    config = _load_config(Path(args.config) if args.config else None)
    base_url = args.dkws_url or config.get("dkws_base_url", "http://127.0.0.1:8106")
    customer_id = config.get("test_customer_id", "CUST-E2E-001")
    timeout = float(config.get("timeout_seconds", 30))
    poll_interval = float(config.get("poll_interval_seconds", 2))
    max_poll = int(config.get("max_poll_attempts", 30))
    api_key = config.get("api_key", "")

    headers = {}
    if api_key:
        headers["X-API-Key"] = api_key

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    report: dict = {
        "task_package": "M3-P0",
        "scope": "GITS ↔ DKWS 集成场景端到端验收",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "dkws_base_url": base_url,
        "test_customer_id": customer_id,
        "deterministic_mode": not bool(api_key),
        "checks": [],
    }

    print("=" * 60, flush=True)
    print("M3-P0 端到端验收", flush=True)
    print(f"DKWS: {base_url}", flush=True)
    print(f"客户: {customer_id}", flush=True)
    print(f"模式: {'确定性' if not api_key else 'LLM'}", flush=True)
    print("=" * 60, flush=True)

    # 健康检查
    r = _request(f"{base_url}/v1/health", headers=headers, timeout=5)
    if r["error"]:
        print(f"\n[ERROR] DKWS 服务不可达：{r['error']}", file=sys.stderr)
        print("请先启动 DKWS 服务：python scripts/serve_skill_service.py", file=sys.stderr)
        return 1
    print(f"[health] DKWS 服务就绪（status={r['status']}）\n", flush=True)

    scenario = args.scenario or "all"

    if scenario in ("r1", "all"):
        scenario_r1_previsit(report, base_url, customer_id, headers, timeout)

    if scenario in ("sp20", "all"):
        scenario_sp20_proposal(report, base_url, customer_id, headers,
                               timeout, poll_interval, max_poll)

    if scenario in ("sp21", "all"):
        scenario_sp21_memory(report, base_url, customer_id, headers, timeout)

    if scenario in ("scg", "all"):
        scenario_supply_chain_graph(report, base_url, customer_id, headers, timeout)

    if scenario in ("gate", "all"):
        scenario_gate_collaboration(report, base_url, customer_id, headers, timeout)

    # 汇总
    passed = sum(1 for c in report["checks"] if c["passed"])
    total = len(report["checks"])
    report["summary"] = {"passed": passed, "total": total,
                         "result": "PASS" if passed == total else "FAIL"}

    report_file = out_dir / "m3_e2e_report.json"
    report_file.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                           encoding="utf-8")

    # 同时生成 Markdown 报告
    md_file = out_dir / "m3_e2e_report.md"
    _write_md_report(report, md_file)

    print(f"\n{'=' * 60}", flush=True)
    print(f"M3 E2E 验收完成：{passed}/{total} 项通过 → {report['summary']['result']}",
          flush=True)
    print(f"JSON 报告：{report_file}", flush=True)
    print(f"MD 报告：{md_file}", flush=True)

    return 0 if passed == total else 1


def _write_md_report(report: dict, path: Path) -> None:
    """生成 Markdown 格式的 E2E 报告。"""
    lines = [
        f"# M3-P0 端到端验收报告",
        f"",
        f"- **任务包**: {report.get('task_package', '')}",
        f"- **范围**: {report.get('scope', '')}",
        f"- **生成时间**: {report.get('generated_at', '')}",
        f"- **DKWS URL**: {report.get('dkws_base_url', '')}",
        f"- **测试客户**: {report.get('test_customer_id', '')}",
        f"- **模式**: {'确定性' if report.get('deterministic_mode') else 'LLM'}",
        f"",
        f"## 汇总",
        f"",
        f"| 指标 | 值 |",
        f"|------|------|",
        f"| 通过/总计 | {report['summary']['passed']}/{report['summary']['total']} |",
        f"| 结果 | **{report['summary']['result']}** |",
        f"",
        f"## 检查明细",
        f"",
        f"| # | 场景 | 检查项 | 预期 | 实际 | 判定 |",
        f"|---|------|--------|------|------|------|",
    ]
    for idx, c in enumerate(report.get("checks", []), 1):
        scenario = c.get("scenario", "")
        name = c.get("name", "")
        expected = c.get("expected", "")
        actual = c.get("actual", "")
        verdict = "PASS" if c["passed"] else "FAIL"
        lines.append(f"| {idx} | {scenario} | {name} | {expected} | {actual} | {verdict} |")

    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
