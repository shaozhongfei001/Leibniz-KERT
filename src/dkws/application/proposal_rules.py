"""SP-20 规则校验（6 条 BLOCKING 规则，确定性，生成后执行）。

规则落为 DKWS RULE 资产语义：ruleId + description + enforcement=BLOCKING；
违规 → data.ruleViolations（BLOCKING 违规使结果 status=PARTIAL）。
"""
from __future__ import annotations

RULES = [
    {"ruleId": "CITATION_REQUIRED", "description": "所有断言必须有引用，标注来源和日期", "enforcement": "BLOCKING"},
    {"ruleId": "NO_UNDISCLOSED_DEGRADATION", "description": "不得隐瞒风险降级，内部版风险红旗必须保留", "enforcement": "BLOCKING"},
    {"ruleId": "DUAL_VERSION_PRINCIPLE", "description": "内部版和对客版分离，对客版仅含F+A标签内容", "enforcement": "BLOCKING"},
    {"ruleId": "GATE_SEQUENCING", "description": "闸门顺序不可跳过：G0→G1→G2→G3→G4→G5", "enforcement": "BLOCKING"},
    {"ruleId": "FACT_LABEL_MANDATORY", "description": "每个断言必须标注事实状态标签（F/C/B/H/P/A）", "enforcement": "BLOCKING"},
    {"ruleId": "NO_COMMITMENT_WITHOUT_APPROVAL", "description": "未经G3审批的内容不得以承诺性表述呈现", "enforcement": "BLOCKING"},
]

VALID_LABELS = {"F", "C", "B", "H", "P", "A"}


def evaluate(chapters: list[dict], customer_version: dict | None, gate_state: dict) -> dict:
    """对生成结果执行 6 条规则。

    chapters: [{chapterId, claims: [{claim, factLabel, source, date, chapterRef}]}]
    customer_version: {content, filteringNotes, includes, excludes}
    gate_state: {passed: [..], current: "G0".."G5"}
    返回 {"violations": [{ruleId, severity, message}], "blocking": bool}
    """
    violations: list[dict] = []
    claims = [dict(c, chapterRef=ch["chapterId"])
              for ch in chapters for c in ch.get("claims", [])]

    # CITATION_REQUIRED：断言必须有 source 与 date
    for c in claims:
        if not (c.get("source") and c.get("date")):
            violations.append({
                "ruleId": "CITATION_REQUIRED", "severity": "BLOCKING",
                "message": f"断言缺少引用（{c.get('chapterRef')}）：{c.get('claim', '')[:60]}",
            })

    # FACT_LABEL_MANDATORY：标签必填且合法
    for c in claims:
        if c.get("factLabel") not in VALID_LABELS:
            violations.append({
                "ruleId": "FACT_LABEL_MANDATORY", "severity": "BLOCKING",
                "message": f"断言缺少合法事实标签（{c.get('chapterRef')}）：{c.get('claim', '')[:60]}",
            })

    # DUAL_VERSION_PRINCIPLE：对客版仅 F/A（过滤引擎保证；此处复核）
    if customer_version:
        leaked = [c for c in claims if c.get("factLabel") not in ("F", "A")]
        for c in leaked:
            if c.get("claim") and c["claim"] in (customer_version.get("content") or ""):
                violations.append({
                    "ruleId": "DUAL_VERSION_PRINCIPLE", "severity": "BLOCKING",
                    "message": f"对客版包含非 F/A 标签断言（{c.get('chapterRef')}）：{c['claim'][:60]}",
                })

    # NO_COMMITMENT_WITHOUT_APPROVAL：P 标签断言在 G3 前不得以承诺呈现（对客版不得含 P）
    g3_passed = "G3" in (gate_state.get("passed") or [])
    for c in claims:
        if c.get("factLabel") == "P" and not g3_passed and customer_version and \
                c.get("claim") in (customer_version.get("content") or ""):
            violations.append({
                "ruleId": "NO_COMMITMENT_WITHOUT_APPROVAL", "severity": "BLOCKING",
                "message": f"未经 G3 审批的承诺进入对客版（{c.get('chapterRef')}）：{c['claim'][:60]}",
            })

    # NO_UNDISCLOSED_DEGRADATION：内部版风险红旗不得被静默移除（对客版过滤必须留 filteringNotes）
    if customer_version and not customer_version.get("filteringNotes"):
        violations.append({
            "ruleId": "NO_UNDISCLOSED_DEGRADATION", "severity": "BLOCKING",
            "message": "对客版过滤未生成过滤报告（filteringNotes 缺失）",
        })

    # GATE_SEQUENCING：gateRecommendations 不得建议跳门
    seq = ["G0", "G1", "G2", "G3", "G4", "G5"]
    passed = gate_state.get("passed") or []
    cur = gate_state.get("current") or "G0"
    for p in passed:
        if p in seq and cur in seq and seq.index(p) > seq.index(cur):
            violations.append({
                "ruleId": "GATE_SEQUENCING", "severity": "BLOCKING",
                "message": f"闸门顺序异常：已过 {p} 但当前 {cur}",
            })

    return {
        "violations": violations,
        "blocking": bool(violations),
        "ruleIds": [r["ruleId"] for r in RULES],
    }
