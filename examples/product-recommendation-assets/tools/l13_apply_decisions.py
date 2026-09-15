#!/usr/bin/env python3
"""应用 Owner 决议（Loop L13）

把 Owner 已签署的决策（90_control/decisions/signed.json）落到加工产物上：

  1. ConflictCase：写入 resolution，status=OPEN → RESOLVED（INV-CNF-01/04）
  2. 冲突字段：新建 SUPPORTED 断言（supersedes 指向 CONFLICT 断言，INV-ASM-06）
  3. NOT_APPLICABLE 字段：新建 NOT_APPLICABLE 断言并携带 reviewDecisionId（INV-ASM-05）
  4. 重算字段体检与候选卡

**本脚本不产生任何决定**：决定内容全部来自 Owner 签署的输入文件，
脚本只做机械应用与不可变追加。未签署的决策文件会被拒绝。

用法:
    python3 tools/l13_apply_decisions.py --decisions 90_control/decisions/signed.json
"""

import argparse
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
DEC_DIR = BASE / "90_control" / "decisions"
POLICY = GITS / "specs" / "product-knowledge" / "field-policy.schema.json"

CST = timezone(timedelta(hours=8))
OWNER_ROLES = {"PRODUCT_OWNER", "RISK_OWNER", "COMPLIANCE_OWNER"}
MONEY_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(万元|亿元|元)")
PRODUCT_ID = "PROD-CM-001"


def sha256_text(t: str) -> str:
    return hashlib.sha256(t.encode("utf-8")).hexdigest()


def sid_key(s: str) -> str:
    return s.replace("-", "")


def now_cst() -> datetime:
    epoch = os.environ.get("SOURCE_DATE_EPOCH")
    return datetime.fromtimestamp(int(epoch), CST) if epoch else datetime.now(CST)


def load(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))


def validate(doc):
    errs = []
    if doc.get("ownerAttested") is not True or not doc.get("attestedBy"):
        errs.append("决策文件未签署（ownerAttested/attestedBy）")
    for i, d in enumerate(doc.get("decisions", [])):
        if d.get("decidedByRole") not in OWNER_ROLES:
            errs.append(f"decisions[{i}].decidedByRole 非 Owner 角色")
        for k in ("decisionId", "subjectKind", "subjectId", "decision", "rationale", "decidedBy"):
            if not d.get(k):
                errs.append(f"decisions[{i}] 缺字段 {k}")
    return errs


def money_value(quote):
    m = MONEY_RE.search(quote or "")
    if not m:
        return None
    mult = {"元": 1.0, "万元": 1e4, "亿元": 1e8}[m.group(2)]
    return float(m.group(1)) * mult


STATE_ORDER = {"SUPPORTED": 5, "REVIEWED": 4, "NOT_APPLICABLE": 3,
               "CONFLICT": 2, "STALE": 2, "CANDIDATE": 1, "UNKNOWN": 0}


def latest_state(items):
    """取字段的当前有效断言。

    先剔除被 supersedes 指向的旧断言，再按「状态优先级 → 创建时间 → ID」取末端。
    仅靠 supersedes 链不够：冲突中的多条 CANDIDATE 未被任何断言显式取代，
    若不按状态优先级选取，Owner 裁决出的 SUPPORTED 会被旧 CANDIDATE 掩盖
    （L13 实测：minAccountBalance 显示 UNKNOWN 而非 SUPPORTED）。
    """
    superseded = {a.get("supersedes") for a in items if a.get("supersedes")}
    alive = [a for a in items if a["assertionId"] not in superseded] or items
    return sorted(alive, key=lambda a: (STATE_ORDER.get(a["knowledgeState"], 0),
                                        a.get("createdAt", ""),
                                        a["assertionId"]))[-1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--decisions", required=True)
    args = ap.parse_args()

    doc = load(Path(args.decisions))
    errs = validate(doc)
    if errs:
        print("FAIL | 决策文件不合法：")
        for e in errs:
            print("  -", e)
        return 2

    ts = now_cst()
    asm_doc = load(ASM_DIR / f"{PRODUCT_ID}.assertions.json")
    cnf_doc = load(CNF_DIR / f"{PRODUCT_ID}.conflicts.json")
    policy = next(e for e in load(POLICY)["examples"]
                  if e.get("productFamily") == "CASH_MANAGEMENT")
    spec_by_field = {f["fieldPath"]: f for f in policy["fields"]}
    evs = {s["evidenceId"]: s for p in EVS_DIR.glob("*.evidence-spans.json")
           for s in load(p)["evidenceSpans"]}

    by_field = {}
    for a in asm_doc["assertions"]:
        by_field.setdefault(a["fieldPath"], []).append(a)

    new_assertions = []
    applied = []

    applied_ids = {a.get("reviewDecisionId") for a in asm_doc["assertions"]}
    applied_ids |= {c.get("resolution", {}).get("decisionId")
                    for c in cnf_doc["conflicts"] if c.get("resolution")}

    for d in doc["decisions"]:
        if d["decisionId"] in applied_ids:
            print("SKIP  | 已应用:", d["decisionId"])
            continue
        if d["subjectKind"] == "CONFLICT":
            cid = d["subjectId"]
            target = next((c for c in cnf_doc["conflicts"] if c["conflictId"] == cid), None)
            if target is None:
                print(f"FAIL | 冲突不存在: {cid}")
                return 1
            resolved = next((a for a in asm_doc["assertions"]
                             if a["assertionId"] == d.get("resolvedAssertionId")), None)
            if resolved is None or d["resolvedAssertionId"] not in target["assertionIds"]:
                print(f"FAIL | resolvedAssertionId 不在冲突断言集内: {d.get('resolvedAssertionId')}")
                return 1
            target["status"] = "RESOLVED"
            target["resolution"] = {
                "decisionId": d["decisionId"],
                "resolvedAssertionId": d["resolvedAssertionId"],
                "rationale": d["rationale"],
                "resolvedBy": d["decidedBy"],
                "resolvedByRole": d["decidedByRole"],
                "resolvedAt": d.get("decidedAt", ts.isoformat()),
            }
            # 冲突字段：新建 SUPPORTED 断言，取代 CONFLICT 断言
            conflict_asm = next((a for a in by_field[resolved["fieldPath"]]
                                 if a["knowledgeState"] == "CONFLICT"), None)
            value = None
            for eid in resolved["evidenceIds"]:
                value = money_value(evs[eid]["quote"])
                if value is not None:
                    break
            new_assertions.append({
                "assertionId": f"ASM-{sid_key(PRODUCT_ID)}-"
                               f"{sha256_text(PRODUCT_ID + '|' + resolved['fieldPath'] + '|SUPPORTED')[:8]}",
                "productId": PRODUCT_ID,
                "productVersionScope": asm_doc["productVersionScope"],
                "fieldPath": resolved["fieldPath"],
                "rawValue": resolved["rawValue"],
                "normalizedValue": value,
                "valueType": spec_by_field[resolved["fieldPath"]]["valueType"],
                "knowledgeState": "SUPPORTED",
                "applicabilityScope": {"effectiveFrom": "2026-09-06", "effectiveTo": None},
                "evidenceIds": list(resolved["evidenceIds"]),
                "conflictId": cid,
                "reviewDecisionId": d["decisionId"],
                "supersedes": conflict_asm["assertionId"] if conflict_asm else None,
                "createdByRunId": asm_doc["extractionRunId"],
                "createdAt": ts.isoformat(),
            })
            applied.append(f"CONFLICT {cid} -> {d['resolvedAssertionId']}")

        elif d["subjectKind"] == "FIELD" and d["decision"] == "NOT_APPLICABLE":
            fp = d["subjectId"]
            items = by_field.get(fp, [])
            old = latest_state(items)
            new_assertions.append({
                "assertionId": f"ASM-{sid_key(PRODUCT_ID)}-"
                               f"{sha256_text(PRODUCT_ID + '|' + fp + '|NOT_APPLICABLE')[:8]}",
                "productId": PRODUCT_ID,
                "productVersionScope": asm_doc["productVersionScope"],
                "fieldPath": fp,
                "rawValue": None,
                "normalizedValue": None,
                "valueType": spec_by_field[fp]["valueType"],
                "knowledgeState": "NOT_APPLICABLE",
                "applicabilityScope": {"effectiveFrom": "2026-09-06", "effectiveTo": None},
                "evidenceIds": [],
                "conflictId": None,
                "reviewDecisionId": d["decisionId"],
                "supersedes": old["assertionId"],
                "createdByRunId": asm_doc["extractionRunId"],
                "createdAt": ts.isoformat(),
            })
            applied.append(f"FIELD {fp} -> NOT_APPLICABLE ({d['decisionId']})")

    asm_doc["assertions"].extend(new_assertions)
    asm_doc["assertionCount"] = len(asm_doc["assertions"])
    (ASM_DIR / f"{PRODUCT_ID}.assertions.json").write_text(
        json.dumps(asm_doc, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")
    (CNF_DIR / f"{PRODUCT_ID}.conflicts.json").write_text(
        json.dumps(cnf_doc, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")

    # ---- 重算体检与候选卡 ----
    by_field = {}
    for a in asm_doc["assertions"]:
        by_field.setdefault(a["fieldPath"], []).append(a)

    conflict_by_field = {c["fieldPath"]: c["conflictId"] for c in cnf_doc["conflicts"]}
    health, blockers = [], []
    for spec in policy["fields"]:
        fp = spec["fieldPath"]
        items = by_field.get(fp, [])
        tail = latest_state(items) if items else None
        state = tail["knowledgeState"] if tail else "UNKNOWN"
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
            "needsHumanReview": False,
            "reason": "Owner 已裁决" if state in ("SUPPORTED", "NOT_APPLICABLE") else "待裁决",
        })
    interpretation_ready = not blockers
    RPT_DIR.mkdir(parents=True, exist_ok=True)
    (RPT_DIR / f"{PRODUCT_ID}.health.json").write_text(
        json.dumps({
            "productId": PRODUCT_ID,
            "productVersionScope": asm_doc["productVersionScope"],
            "policyId": policy["policyId"],
            "policyOwnerApproved": policy.get("ownerApproved", False),
            "generatedAt": ts.isoformat(),
            "fieldCount": len(health),
            "interpretationReady": interpretation_ready,
            "recommendationReady": False,
            "recommendationReadyReason": "DEMO 派生知识（provenanceState=DEMO）不得进入 RECOMMENDATION_READY",
            "blockers": blockers,
            "fields": health,
        }, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    card_fields = [{
        "fieldPath": h["fieldPath"],
        "value": None,
        "knowledgeState": h["knowledgeState"],
        "conflictId": h["conflictId"],
        "evidenceIds": sorted({e for a in by_field.get(h["fieldPath"], []) for e in a["evidenceIds"]}),
        "provenanceState": "DEMO",
    } for h in health]
    (CARD_DIR / f"{PRODUCT_ID}.candidate-card.json").write_text(
        json.dumps({"productId": PRODUCT_ID,
                    "productVersionScope": asm_doc["productVersionScope"],
                    "source": "compiled_from_assertions",
                    "legacyCardReused": False,
                    "provenanceState": "DEMO",
                    "interpretationReady": interpretation_ready,
                    "recommendationReady": False,
                    "fieldCount": len(card_fields),
                    "fields": card_fields,
                    "compiledAt": ts.isoformat()},
                   ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    # ---- ReviewDecision 台账（只追加）----
    dec_path = DEC_DIR / "review-decisions.json"
    existing = load(dec_path)["decisions"] if dec_path.exists() else []
    seen = {e["decisionId"] for e in existing}
    merged = list(existing)
    for d in doc["decisions"]:
        if d["decisionId"] in seen:
            continue
        merged.append({k: d[k] for k in ("decisionId", "subjectKind", "subjectId",
                                         "decision", "rationale", "decidedBy",
                                         "decidedByRole")}
                      | {"decidedAt": d.get("decidedAt", ts.isoformat())})
        seen.add(d["decisionId"])
    dec_path.write_text(json.dumps({"attestedBy": doc["attestedBy"],
                                    "attestation": doc.get("attestation", ""),
                                    "attestedAt": doc.get("attestedAt", ts.isoformat()),
                                    "decisions": merged},
                                   ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8")

    for line in applied:
        print("APPLIED |", line)
    print(f"newAssertions={len(new_assertions)} interpretationReady={interpretation_ready} "
          f"blockers={len(blockers)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
