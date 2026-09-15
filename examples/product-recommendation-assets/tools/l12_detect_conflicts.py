#!/usr/bin/env python3
"""冲突检测 + 字段体检 + 候选卡编译（Loop L12）

输入：L11 的 FieldAssertion 与 EvidenceSpan
输出：
  02_work/conflicts/PROD-CM-001.conflicts.json   （CTR-PK-CNF-001 实例）
  02_work/assertions/PROD-CM-001.assertions.json （追加 CONFLICT 断言，supersedes 链）
  02_work/reports/PROD-CM-001.health.json        （字段体检报告）
  02_work/candidate-cards/PROD-CM-001.candidate-card.json

红线：
  1. 冲突**不自动择一**：只产出 status=OPEN 的 ConflictCase，resolution=null
     （INV-CNF-03：禁止系统自动写入 resolution）；
  2. 断言不可变：冲突字段**新建** CONFLICT 断言并设置 supersedes，
     不原地修改 CANDIDATE 断言（INV-ASM-06）；
  3. 候选卡**不复用 13 张 legacy card**，完全从断言编译；
  4. 未 Owner 复核的断言不产生规范值，候选卡 value 为 null。

用法:
    python3 tools/l12_detect_conflicts.py
"""

import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
GITS = Path("/home/szf/dev/gits-cbanking")
ASM_DIR = BASE / "02_work" / "assertions"
EVS_DIR = BASE / "02_work" / "evidence-spans"
CNF_DIR = BASE / "02_work" / "conflicts"
RPT_DIR = BASE / "02_work" / "reports"
CARD_DIR = BASE / "02_work" / "candidate-cards"
POLICY = GITS / "specs" / "product-knowledge" / "field-policy.schema.json"

CST = timezone(timedelta(hours=8))
MONEY_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(万元|亿元|元)")
RATE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(%|个百分点|个基点)")
ENUM_TOKENS = ["大型企业客户", "集团客户", "机构客户", "小微企业客户",
               "柜面", "企业网银", "银企直联", "开放银行接口"]

PRODUCT_ID = "PROD-CM-001"


def sha256_text(t: str) -> str:
    return hashlib.sha256(t.encode("utf-8")).hexdigest()


def now_cst() -> datetime:
    epoch = os.environ.get("SOURCE_DATE_EPOCH")
    if epoch:
        return datetime.fromtimestamp(int(epoch), CST)
    return datetime.now(CST)


def sid_key(s: str) -> str:
    return s.replace("-", "")


def extract_candidate_value(value_type: str, quote: str):
    """从原文抽取可比对的候选值（仅用于**冲突检测**，不作为规范值写入断言）。"""
    if value_type == "MONEY":
        m = MONEY_RE.search(quote)
        if not m:
            return None
        amount, unit = float(m.group(1)), m.group(2)
        mult = {"元": 1.0, "万元": 1e4, "亿元": 1e8}[unit]
        return amount * mult
    if value_type == "RATE":
        m = RATE_RE.search(quote)
        return float(m.group(1)) if m else None
    if value_type == "ENUM":
        # ENUM 多源列举属于**互补**而非矛盾（如"柜面、网银"与"柜面、直联"），
        # 只有出现互斥信号才构成冲突，故此处不返回可比对值。
        return None
    return None


EXCLUSIVE_NEG = ["不适用", "不予", "不得", "禁止", "不适用本产品"]
EXCLUSIVE_POS = ["适用于", "适用", "可以", "可办理"]


quotes = None  # L12: ENUM 自动冲突判定已移除
def _unused_enum_has_exclusive_conflict(quotes):
    """ENUM 字段：同时出现肯定与否定表述才算 SCOPE_OVERLAP。"""
    has_neg = any(any(k in q for k in EXCLUSIVE_NEG) for q in quotes)
    has_pos = any(any(k in q for k in EXCLUSIVE_POS) for q in quotes)
    return has_neg and has_pos


def vtype_of(spec) -> str:
    return spec.get("valueType", "TEXT")


def load_policy():
    doc = json.loads(POLICY.read_text(encoding="utf-8"))
    return next(e for e in doc["examples"] if e.get("productFamily") == "CASH_MANAGEMENT")


def main():
    asm_path = ASM_DIR / f"{PRODUCT_ID}.assertions.json"
    if not asm_path.exists():
        print("FAIL | 未找到 L11 断言产物")
        return 1
    asm_doc = json.loads(asm_path.read_text(encoding="utf-8"))
    policy = load_policy()
    spec_by_field = {f["fieldPath"]: f for f in policy["fields"]}

    evs_by_id = {}
    for p in EVS_DIR.glob("*.evidence-spans.json"):
        for s in json.loads(p.read_text(encoding="utf-8"))["evidenceSpans"]:
            evs_by_id[s["evidenceId"]] = s

    detected = now_cst()
    run_id = asm_doc["extractionRunId"]

    # ---------- 1. 冲突检测 ----------
    by_field = {}
    for a in asm_doc["assertions"]:
        if a["knowledgeState"] != "CANDIDATE":
            continue
        by_field.setdefault(a["fieldPath"], []).append(a)

    conflicts = []
    new_assertions = []
    for field, items in sorted(by_field.items()):
        spec = spec_by_field.get(field, {})
        vtype = spec.get("valueType", "TEXT")
        quotes = [evs_by_id[e]["quote"]
                  for a in items for e in a["evidenceIds"] if e in evs_by_id]

        ctype = None
        groups = {}
        if vtype in ("MONEY", "RATE"):
            for a in items:
                for eid in a["evidenceIds"]:
                    ev = evs_by_id.get(eid)
                    if not ev:
                        continue
                    val = extract_candidate_value(vtype, ev["quote"])
                    if val is None:
                        continue
                    groups.setdefault(val, []).append(a)
            if len(groups) >= 2:
                ctype = "VALUE_MISMATCH"
        # ENUM/TEXT 不做自动冲突判定：多源列举多为互补，且"适用/不适用"常出现在
        # 同一条款内部的限定语中，自动判定极易误报（L12 实测误报 customerSegment）。
        # 此类字段交由体检报告标注 needsHumanReview，由 Owner 复核，不冒充系统结论。

        if ctype is None:
            continue

        involved = sorted({a["assertionId"] for g in groups.values() for a in g})
        cid = "CNF-" + sid_key(PRODUCT_ID) + "-" + sha256_text(
            field + "|" + "|".join(involved))[:8]
        conflicts.append({
            "conflictId": cid,
            "productId": PRODUCT_ID,
            "fieldPath": field,
            "conflictType": ctype,
            "assertionIds": involved,
            "impactedObjects": [PRODUCT_ID],
            "status": "OPEN",
            "resolution": None,
            "detectedByRunId": run_id,
            "detectedAt": detected.isoformat(),
        })

        # 断言不可变：新建 CONFLICT 断言，supersedes 指向首条 CANDIDATE
        ev_ids = sorted({e for a in items for e in a["evidenceIds"]})
        new_assertions.append({
            "assertionId": f"ASM-{sid_key(PRODUCT_ID)}-"
                           f"{sha256_text(PRODUCT_ID + '|' + field + '|CONFLICT')[:8]}",
            "productId": PRODUCT_ID,
            "productVersionScope": asm_doc["productVersionScope"],
            "fieldPath": field,
            "rawValue": None,
            "normalizedValue": None,
            "valueType": spec.get("valueType", "TEXT") if spec.get("valueType") != "ENUM_ARRAY" else "ENUM",
            "knowledgeState": "CONFLICT",
            "applicabilityScope": {"effectiveFrom": "2026-09-06", "effectiveTo": None},
            "evidenceIds": ev_ids,
            "conflictId": cid,
            "reviewDecisionId": None,
            "supersedes": involved[0],
            "createdByRunId": run_id,
            "createdAt": detected.isoformat(),
        })

    CNF_DIR.mkdir(parents=True, exist_ok=True)
    (CNF_DIR / f"{PRODUCT_ID}.conflicts.json").write_text(
        json.dumps({"productId": PRODUCT_ID, "conflictCount": len(conflicts),
                    "conflicts": conflicts}, ensure_ascii=False, indent=2,
                   sort_keys=True) + "\n", encoding="utf-8")

    if new_assertions:
        asm_doc["assertions"].extend(new_assertions)
        asm_doc["assertionCount"] = len(asm_doc["assertions"])
        asm_path.write_text(json.dumps(asm_doc, ensure_ascii=False, indent=2,
                                       sort_keys=True) + "\n", encoding="utf-8")

    # ---------- 2. 字段体检 ----------
    conflict_by_field = {c["fieldPath"]: c["conflictId"] for c in conflicts}
    final_by_field = {}
    for a in asm_doc["assertions"]:
        final_by_field.setdefault(a["fieldPath"], []).append(a)

    health = []
    blockers = []
    for spec in policy["fields"]:
        fp = spec["fieldPath"]
        items = final_by_field.get(fp, [])
        states = [a["knowledgeState"] for a in items]
        if "CONFLICT" in states:
            state, reason = "CONFLICT", "同字段多来源值不一致，冲突未决"
        elif all(s == "UNKNOWN" for s in states):
            state, reason = "UNKNOWN", "无合格证据（资格/权威级/Owner 未裁决）"
        elif "CANDIDATE" in states:
            state, reason = "CANDIDATE", "有候选证据，未 Owner 复核"
        else:
            state, reason = "UNKNOWN", "无断言"
        if spec["required"] == "REQUIRED_HARD" and state in ("UNKNOWN", "CONFLICT", "STALE"):
            blockers.append({"fieldPath": fp, "state": state, "required": spec["required"]})
        health.append({
            "fieldPath": fp,
            "required": spec["required"],
            "purposeGate": spec["purposeGate"],
            "knowledgeState": state,
            "assertionCount": len(items),
            "evidenceCount": sum(len(a["evidenceIds"]) for a in items),
            "conflictId": conflict_by_field.get(fp),
            "needsHumanReview": vtype_of(spec) in ("ENUM", "ENUM_ARRAY", "TEXT")
                                and state in ("CANDIDATE", "UNKNOWN"),
            "reason": reason,
        })

    interpretation_ready = not blockers
    RPT_DIR.mkdir(parents=True, exist_ok=True)
    (RPT_DIR / f"{PRODUCT_ID}.health.json").write_text(
        json.dumps({
            "productId": PRODUCT_ID,
            "productVersionScope": asm_doc["productVersionScope"],
            "policyId": policy["policyId"],
            "policyOwnerApproved": policy.get("ownerApproved", False),
            "generatedAt": detected.isoformat(),
            "fieldCount": len(health),
            "interpretationReady": interpretation_ready,
            "recommendationReady": False,
            "recommendationReadyReason": "DEMO 派生知识（provenanceState=DEMO）不得进入 RECOMMENDATION_READY",
            "blockers": blockers,
            "fields": health,
        }, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    # ---------- 3. 候选卡编译（不复用 legacy card） ----------
    card_fields = []
    for h in health:
        items = final_by_field.get(h["fieldPath"], [])
        card_fields.append({
            "fieldPath": h["fieldPath"],
            "value": None,  # 未 Owner 复核，不产生规范值
            "knowledgeState": h["knowledgeState"],
            "conflictId": h["conflictId"],
            "evidenceIds": sorted({e for a in items for e in a["evidenceIds"]}),
            "provenanceState": "DEMO",
        })
    CARD_DIR.mkdir(parents=True, exist_ok=True)
    (CARD_DIR / f"{PRODUCT_ID}.candidate-card.json").write_text(
        json.dumps({
            "productId": PRODUCT_ID,
            "productVersionScope": asm_doc["productVersionScope"],
            "source": "compiled_from_assertions",
            "legacyCardReused": False,
            "provenanceState": "DEMO",
            "interpretationReady": interpretation_ready,
            "recommendationReady": False,
            "fieldCount": len(card_fields),
            "fields": card_fields,
            "compiledAt": detected.isoformat(),
        }, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"conflicts={len(conflicts)} · newConflictAssertions={len(new_assertions)} · "
          f"interpretationReady={interpretation_ready} · blockers={len(blockers)}")
    for c in conflicts:
        print(f"  {c['conflictId']} {c['fieldPath']} {c['conflictType']} "
              f"assertions={len(c['assertionIds'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
