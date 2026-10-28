#!/usr/bin/env python3
"""Release 门禁（Loop L13 · KERT 侧）

校验项：
  1. Release 符合 CTR-PK-RLS-001（jsonschema）
  2. INV-RLS-01：recommendationReady ⇒ interpretationReady
  3. INV-RLS-02：存在 REQUIRED_HARD 阻断 ⇒ 两个 purposeFlag 均为 false
  4. INV-RLS-07：bundleHash = SHA-256(a||e||c||r)
  5. DEMO 派生：provenanceState=DEMO 且 recommendationReady=false
  6. lifecycleState != PUBLISHED ⇒ publishedAt 为 null（不得冒充已发布）

2026-10-28：CTR-PK-INT-001 三视图投影（04_serve/interpretation）已随 GITS
「产品知识」页下线删除，原第 7/8 项投影校验与 INT_DIR 依赖一并移除。

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
    rel_v = Draft202012Validator(rel_schema)

    if not REL_DIR.exists():
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

    check("存在 Owner 决策模板或已签署决策",
          (DEC_DIR / "DECISIONS.template.json").exists()
          or (DEC_DIR / "review-decisions.json").exists(),
          str(DEC_DIR))

    failed = [r for r in results if not r[1]]
    print(f"\n{'=' * 60}")
    print(f"L13 发布门禁：{len(results) - len(failed)}/{len(results)} PASS")
    if failed:
        print("失败项：")
        for n, _, dd in failed:
            print(f"  - {n} {dd}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
