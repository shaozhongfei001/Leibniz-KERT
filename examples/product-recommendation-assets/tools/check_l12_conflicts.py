#!/usr/bin/env python3
"""冲突 / 体检 / 候选卡门禁（Loop L12）

校验项：
  1. ConflictCase 符合 CTR-PK-CNF-001（jsonschema）
  2. INV-CNF-02：OPEN 冲突的字段必须存在 CONFLICT 断言且引用该 conflictId
  3. INV-CNF-03：系统产出必须 status=OPEN 且 resolution=null（禁止自动决议）
  4. INV-ASM-03/04：CONFLICT 断言 normalizedValue=null 且 conflictId 非空
  5. INV-ASM-06：CONFLICT 断言必须设置 supersedes（不可原地覆盖）
  6. 候选卡：不复用 legacy card、provenanceState=DEMO、未复核字段值为 null
  7. 体检自洽：存在 REQUIRED_HARD 阻断项 ⇒ interpretationReady=false；
     DEMO 派生 ⇒ recommendationReady 必须为 false

用法:
    python3 tools/check_l12_conflicts.py
"""

import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
GITS = Path("/home/szf/dev/gits-cbanking")
PK = GITS / "specs" / "product-knowledge"
CNF_DIR = BASE / "02_work" / "conflicts"
ASM_DIR = BASE / "02_work" / "assertions"
RPT_DIR = BASE / "02_work" / "reports"
CARD_DIR = BASE / "02_work" / "candidate-cards"

results = []


def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'} | {name}" + (f" | {detail}" if detail else ""))
    return ok


def load_json(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))


def main():
    try:
        from jsonschema import Draft202012Validator
    except ImportError:
        check("jsonschema 可用", False)
        return 1

    cnf_schema = load_json(PK / "conflict-case.schema.json")
    asm_schema = load_json(PK / "field-assertion.schema.json")
    cnf_v = Draft202012Validator(cnf_schema)
    asm_v = Draft202012Validator(asm_schema)

    if not CNF_DIR.exists() or not RPT_DIR.exists() or not CARD_DIR.exists():
        check("L12 产物目录存在", False, "请先运行 l12_detect_conflicts.py")
        return 1

    asm_by_field = {}
    for p in ASM_DIR.glob("*.assertions.json"):
        for a in load_json(p)["assertions"]:
            asm_by_field.setdefault(a["fieldPath"], []).append(a)

    # ---- ConflictCase ----
    for p in sorted(CNF_DIR.glob("*.conflicts.json")):
        d = load_json(p)
        check(f"{d['productId']} conflictCount == 条目数",
              d["conflictCount"] == len(d["conflicts"]),
              f"声明 {d['conflictCount']} vs 实际 {len(d['conflicts'])}")
        for c in d["conflicts"]:
            cid = c["conflictId"]
            errs = sorted(cnf_v.iter_errors(c), key=lambda e: e.path)
            check(f"{cid} 符合 CTR-PK-CNF-001", not errs,
                  str(errs[0].message)[:80] if errs else "")
            check(f"{cid} assertionIds >= 2", len(c["assertionIds"]) >= 2,
                  str(len(c["assertionIds"])))
            if c.get("resolution") is None:
                check(f"{cid} 未裁决 => status=OPEN 且 resolution 为空（INV-CNF-03）",
                      c["status"] == "OPEN", f"status={c['status']}")
            else:
                res = c["resolution"]
                check(f"{cid} 已裁决 => status=RESOLVED", c["status"] == "RESOLVED",
                      f"status={c['status']}")
                check(f"{cid} INV-CNF-04 resolvedAssertionId ∈ assertionIds",
                      res.get("resolvedAssertionId") in c["assertionIds"],
                      str(res.get("resolvedAssertionId")))
                check(f"{cid} INV-CNF-01 裁决人须为 Owner 角色",
                      res.get("resolvedByRole") in
                      {"PRODUCT_OWNER", "RISK_OWNER", "COMPLIANCE_OWNER"},
                      str(res.get("resolvedByRole")))

            field_asms = asm_by_field.get(c["fieldPath"], [])
            conflict_asms = [a for a in field_asms
                             if a["knowledgeState"] == "CONFLICT"
                             and a.get("conflictId") == cid]
            if c["status"] in ("OPEN", "UNDER_REVIEW"):
                check(f"{cid} 未裁决字段存在引用它的 CONFLICT 断言（INV-CNF-02）",
                      bool(conflict_asms), c["fieldPath"])

            for aid in c["assertionIds"]:
                hit = [a for a in field_asms if a["assertionId"] == aid]
                check(f"{cid} assertionId 存在: {aid}", bool(hit), aid)

            for a in conflict_asms:
                errs2 = sorted(asm_v.iter_errors(a), key=lambda e: e.path)
                check(f"{a['assertionId']} 符合 CTR-PK-ASM-001", not errs2,
                      str(errs2[0].message)[:80] if errs2 else "")
                check(f"{a['assertionId']} CONFLICT => normalizedValue 为 null",
                      a["normalizedValue"] is None, str(a["normalizedValue"])[:40])
                check(f"{a['assertionId']} CONFLICT => supersedes 非空（INV-ASM-06）",
                      a.get("supersedes") is not None, str(a.get("supersedes")))

    # ---- INV-ASM-09：SUPPORTED 保留 conflictId 时必须与裁决一致 ----
    cnf_by_id = {c["conflictId"]: c
                 for p in CNF_DIR.glob("*.conflicts.json")
                 for c in load_json(p)["conflicts"]}
    asm_all = [a for items in asm_by_field.values() for a in items]
    for a in asm_all:
        if a["knowledgeState"] != "SUPPORTED" or not a.get("conflictId"):
            continue
        aid = a["assertionId"]
        c = cnf_by_id.get(a["conflictId"])
        check(f"{aid} INV-ASM-09 冲突存在", c is not None, str(a["conflictId"]))
        if not c:
            continue
        check(f"{aid} INV-ASM-09 冲突已 RESOLVED", c.get("status") == "RESOLVED",
              str(c.get("status")))
        check(f"{aid} INV-ASM-09 裁决 ID 与断言一致",
              (c.get("resolution") or {}).get("decisionId") == a.get("reviewDecisionId"),
              f"冲突 {((c.get('resolution') or {}).get('decisionId'))} vs "
              f"断言 {a.get('reviewDecisionId')}")
        # 采信证据 ∩ 被否决证据 = ∅
        resolved_id = (c.get("resolution") or {}).get("resolvedAssertionId")
        rejected = {e for x in asm_all
                    if x["assertionId"] in c["assertionIds"] and x["assertionId"] != resolved_id
                    for e in x["evidenceIds"]}
        overlap = sorted(set(a["evidenceIds"]) & rejected)
        check(f"{aid} INV-ASM-09 不得含被否决证据", not overlap, str(overlap))

    # ---- 体检报告 ----
    for p in sorted(RPT_DIR.glob("*.health.json")):
        d = load_json(p)
        pid = d["productId"]
        check(f"{pid} 体检覆盖七字段", d["fieldCount"] == 7, str(d["fieldCount"]))
        check(f"{pid} 有阻断项 => interpretationReady=false",
              (not d["blockers"]) or d["interpretationReady"] is False,
              f"blockers={len(d['blockers'])} ready={d['interpretationReady']}")
        check(f"{pid} DEMO 派生 => recommendationReady=false",
              d["recommendationReady"] is False, str(d["recommendationReady"]))
        for f in d["fields"]:
            if f["knowledgeState"] == "CONFLICT":
                check(f"{pid} {f['fieldPath']} CONFLICT 带 conflictId",
                      bool(f["conflictId"]), str(f["conflictId"]))
            if f["knowledgeState"] in ("UNKNOWN", "CONFLICT"):
                check(f"{pid} {f['fieldPath']} 非就绪字段证据计数与状态自洽",
                      f["knowledgeState"] == "CONFLICT" or f["evidenceCount"] == 0,
                      f"state={f['knowledgeState']} ev={f['evidenceCount']}")

    # ---- 候选卡 ----
    for p in sorted(CARD_DIR.glob("*.candidate-card.json")):
        d = load_json(p)
        pid = d["productId"]
        check(f"{pid} 候选卡未复用 legacy card", d["legacyCardReused"] is False,
              str(d["legacyCardReused"]))
        check(f"{pid} 候选卡 provenanceState=DEMO", d["provenanceState"] == "DEMO",
              str(d["provenanceState"]))
        check(f"{pid} 候选卡未复核字段值为 null",
              all(f["value"] is None for f in d["fields"]),
              str([f["fieldPath"] for f in d["fields"] if f["value"] is not None]))
        check(f"{pid} 候选卡字段数 == 七字段", d["fieldCount"] == 7, str(d["fieldCount"]))

    failed = [r for r in results if not r[1]]
    print(f"\n{'=' * 60}")
    print(f"L12 冲突/体检/候选卡门禁：{len(results) - len(failed)}/{len(results)} PASS")
    if failed:
        print("失败项：")
        for n, _, dd in failed:
            print(f"  - {n} {dd}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
