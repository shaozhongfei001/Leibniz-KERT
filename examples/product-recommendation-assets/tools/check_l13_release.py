#!/usr/bin/env python3
"""Release 与解读投影门禁（Loop L13 · KERT 侧）

校验项：
  1. Release 符合 CTR-PK-RLS-001（jsonschema）
  2. INV-RLS-01：recommendationReady ⇒ interpretationReady
  3. INV-RLS-02：存在 REQUIRED_HARD 阻断 ⇒ 两个 purposeFlag 均为 false
  4. INV-RLS-07：bundleHash = SHA-256(a||e||c||r)
  5. DEMO 派生：provenanceState=DEMO 且 recommendationReady=false
  6. lifecycleState != PUBLISHED ⇒ publishedAt 为 null（不得冒充已发布）
  7. 解读投影符合 CTR-PK-INT-001：三视图齐备、非就绪字段 displayValue 为 null
  8. 投影 bundleHash 与 Release 一致；purposeAllowed 与 Release 一致

用法:
    python3 tools/check_l13_release.py
"""

import hashlib
import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
GITS = Path("/home/szf/dev/gits-cbanking")
PK = GITS / "specs" / "product-knowledge"
REL_DIR = BASE / "04_serve" / "releases"
INT_DIR = BASE / "04_serve" / "interpretation"
DEC_DIR = BASE / "90_control" / "decisions"

results = []


def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'} | {name}" + (f" | {detail}" if detail else ""))
    return ok


def load(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))


def main():
    try:
        from jsonschema import Draft202012Validator
    except ImportError:
        check("jsonschema 可用", False)
        return 1

    rel_schema = load(PK / "product-knowledge-release.schema.json")
    int_schema = load(PK / "interpretation-api.openapi.json")
    rel_v = Draft202012Validator(rel_schema)
    # 以组合文档作为 root，使 $ref 可解析（单独传子 schema 会导致 PointerToNowhere）
    resp_v = Draft202012Validator({"components": int_schema["components"],
                                   "$ref": "#/components/schemas/InterpretationResponse"})

    if not REL_DIR.exists() or not INT_DIR.exists():
        check("L13 产物目录存在", False, "请先运行 l13_publish_release.py")
        return 1

    releases = [load(p) for p in sorted(REL_DIR.glob("RLS-*.json"))]
    check("存在至少一个 Release", bool(releases), str(len(releases)))

    for r in releases:
        rid = r["releaseId"]
        errs = sorted(rel_v.iter_errors(r), key=lambda e: e.path)
        check(f"{rid} 符合 CTR-PK-RLS-001", not errs,
              str(errs[0].message)[:80] if errs else "")

        flags = r["purposeFlags"]
        check(f"{rid} INV-RLS-01 蕴含关系",
              (not flags["recommendationReady"]) or flags["interpretationReady"],
              str(flags))
        check(f"{rid} INV-RLS-02 有阻断则两用途均 false",
              (not r["gateReport"]["blockingReasons"]) or
              (not flags["interpretationReady"] and not flags["recommendationReady"]),
              f"blocking={len(r['gateReport']['blockingReasons'])} flags={flags}")

        expect = hashlib.sha256((r["assertionManifestHash"] + r["evidenceManifestHash"]
                                 + r["cardProjectionHash"] + r["rulePackageHash"])
                                .encode()).hexdigest()
        check(f"{rid} INV-RLS-07 bundleHash 自洽", r["bundleHash"] == expect,
              f"{r['bundleHash'][:16]}… vs {expect[:16]}…")

        check(f"{rid} DEMO 派生 => provenanceState=DEMO",
              r.get("provenanceState") == "DEMO", str(r.get("provenanceState")))
        check(f"{rid} DEMO 派生 => recommendationReady=false",
              flags["recommendationReady"] is False, str(flags["recommendationReady"]))

        if r["lifecycleState"] != "PUBLISHED":
            check(f"{rid} 未发布 => publishedAt 为 null（不冒充）",
                  r.get("publishedAt") is None, str(r.get("publishedAt")))
            check(f"{rid} 未发布 => 存在 Owner 阻塞记录",
                  (BASE / "90_control" / "BLOCKED_ON_OWNER.json").exists(),
                  "缺失 BLOCKED_ON_OWNER.json")
        else:
            check(f"{rid} 已发布 => ownerDecisionIds 非空",
                  bool(r["ownerDecisionIds"]), str(r["ownerDecisionIds"]))

    for p in sorted(INT_DIR.glob("*.json")):
        d = load(p)
        pid = d["productId"]
        for view in ("OVERVIEW", "ELIGIBILITY", "PRICING"):
            check(f"{pid} 三视图齐备: {view}", view in d.get("views", {}), view)
        for view, fields in d.get("views", {}).items():
            for f in fields:
                if f["knowledgeState"] in ("UNKNOWN", "CONFLICT", "STALE"):
                    check(f"{pid}/{view}/{f['fieldPath']} 非就绪状态 displayValue 为 null",
                          f.get("displayValue") is None, str(f.get("displayValue")))
                    if f["knowledgeState"] == "UNKNOWN":
                        check(f"{pid}/{view}/{f['fieldPath']} UNKNOWN 证据摘要为空数组",
                              f.get("evidenceSummaries") == [],
                              str(len(f.get("evidenceSummaries", []))))
        match = [r for r in releases if r["releaseId"] == d["releaseId"]]
        check(f"{pid} 投影 bundleHash 与 Release 一致",
              bool(match) and match[0]["bundleHash"] == d["bundleHash"], d["releaseId"])
        if match:
            r = match[0]
            check(f"{pid} 投影 purposeAllowed 与 Release 一致",
                  d["purposeAllowed"]["INTERPRETATION"] == r["purposeFlags"]["interpretationReady"]
                  and d["purposeAllowed"]["RECOMMENDATION"] == r["purposeFlags"]["recommendationReady"],
                  str(d["purposeAllowed"]))
        # 200 响应结构契约校验（views 展开为单视图响应）
        for view_name in ("OVERVIEW", "ELIGIBILITY", "PRICING"):
            probe = {
                "productId": pid, "releaseId": d["releaseId"], "bundleHash": d["bundleHash"],
                "view": view_name, "purpose": "INTERPRETATION",
                "isStale": bool(d.get("isStale")),
                "fields": d["views"].get(view_name, []),
                "generatedAt": d["generatedAt"],
            }
            errs = sorted(resp_v.iter_errors(probe), key=lambda e: e.path)
            check(f"{pid} {view_name} 响应符合 CTR-PK-INT-001", not errs,
                  str(errs[0].message)[:80] if errs else "")
        # CANDIDATE 不得泄漏到呈现层
        leaked = [f"{v}/{f['fieldPath']}" for v, fs in d["views"].items()
                  for f in fs if f.get("knowledgeState") == "CANDIDATE"]
        check(f"{pid} CANDIDATE 未泄漏到呈现层", not leaked, str(leaked))

    check("存在 Owner 决策模板或已签署决策",
          (DEC_DIR / "DECISIONS.template.json").exists()
          or (DEC_DIR / "review-decisions.json").exists(),
          str(DEC_DIR))

    failed = [r for r in results if not r[1]]
    print(f"\n{'=' * 60}")
    print(f"L13 发布/投影门禁：{len(results) - len(failed)}/{len(results)} PASS")
    if failed:
        print("失败项：")
        for n, _, dd in failed:
            print(f"  - {n} {dd}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
