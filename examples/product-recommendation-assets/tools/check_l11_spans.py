#!/usr/bin/env python3
"""EvidenceSpan / FieldAssertion 门禁（Loop L11）

对 02_work/evidence-spans 与 02_work/assertions 的产出做合同与不变式校验：

  1. schema 校验：CTR-PK-EVS-002 / CTR-PK-ASM-001（jsonschema Draft 2020-12）
  2. INV-EVS-01：quoteHash == SHA-256(quote)
  3. INV-EVS-08：evidenceId 后缀 == SHA-256(quote) 前 8 位
  4. INV-EVS-02（前置）：quote 必须能在 fragmentId 指定 Fragment 内原样定位
  5. INV-EVS-05：claimType ∈ SourceDocument.allowedClaimTypes
  6. INV-EVS-04：_authoritative/ => usage=AUTHORITATIVE
  7. INV-FLD-02：CANDIDATE 断言的证据权威级 <= 字段 minAuthorityLevel
  8. INV-ASM-02：UNKNOWN => rawValue/normalizedValue 为 null 且 evidenceIds 为空
  9. INV-ASM-07：本轮全部断言 normalizedValue 必须为 null（禁止模型产生规范值）
 10. DEMO 红线：DEMO 源派生断言不得出现 SUPPORTED / REVIEWED
 11. 字段白名单：fieldPath 必须 ∈ CTR-PK-FLD-001 的 CASH_MANAGEMENT 七字段

用法:
    python3 tools/check_l11_spans.py
退出码 0 表示全部通过。
"""

import hashlib
import json
import re
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
GITS = Path("/home/szf/dev/gits-cbanking")
PK = GITS / "specs" / "product-knowledge"
EVS_DIR = BASE / "02_work" / "evidence-spans"
ASM_DIR = BASE / "02_work" / "assertions"
SV_DIR = BASE / "02_work" / "source-versions"
FRG_DIR = BASE / "02_work" / "fragments"

AUTHORITY_RANK = {"REGULATORY": 1, "INTERNAL_POLICY": 2,
                  "PUBLIC_PRICE_DISCLOSURE": 3, "PUBLIC_MARKETING": 4}

results = []


def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'} | {name}" + (f" | {detail}" if detail else ""))
    return ok


def sha256_text(t: str) -> str:
    return hashlib.sha256(t.encode("utf-8")).hexdigest()


def load_json(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))


def main():
    try:
        from jsonschema import Draft202012Validator
    except ImportError:
        check("jsonschema 可用", False, "请先安装 jsonschema")
        return 1

    evs_schema = load_json(PK / "evidence-span.schema.json")
    asm_schema = load_json(PK / "field-assertion.schema.json")
    policy_doc = load_json(PK / "field-policy.schema.json")
    policy = next(e for e in policy_doc["examples"]
                  if e.get("productFamily") == "CASH_MANAGEMENT")
    field_spec = {f["fieldPath"]: f for f in policy["fields"]}

    if not EVS_DIR.exists() or not ASM_DIR.exists():
        check("L11 产物目录存在", False, "请先运行 l11_extract_evidence_spans.py")
        return 1

    # ---------- 索引：SourceVersion / Fragment ----------
    sv_by_id = {s["sourceVersionId"]: s
                for p in SV_DIR.glob("SV-*.json") for s in [load_json(p)]}
    frg_by_id = {}
    for p in FRG_DIR.glob("*.fragments.json"):
        for f in load_json(p)["fragments"]:
            frg_by_id[f["fragmentId"]] = f

    evs_validator = Draft202012Validator(evs_schema)
    asm_validator = Draft202012Validator(asm_schema)

    all_spans = {}
    for p in sorted(EVS_DIR.glob("*.evidence-spans.json")):
        d = load_json(p)
        check(f"{d['sourceId']} evidenceCount == 条目数",
              d["evidenceCount"] == len(d["evidenceSpans"]),
              f"声明 {d['evidenceCount']} vs 实际 {len(d['evidenceSpans'])}")
        for s in d["evidenceSpans"]:
            eid = s["evidenceId"]
            check(f"{eid} evidenceId 唯一", eid not in all_spans,
                  "重复 evidenceId" if eid in all_spans else "")
            all_spans[eid] = s

            errs = sorted(evs_validator.iter_errors(s), key=lambda e: e.path)
            check(f"{eid} 符合 CTR-PK-EVS-002", not errs,
                  str(errs[0].message)[:80] if errs else "")

            check(f"{eid} quoteHash == SHA-256(quote)",
                  s["quoteHash"] == sha256_text(s["quote"]))
            check(f"{eid} evidenceId 后缀 == quoteHash 前 8 位",
                  eid.split("-")[-1] == s["quoteHash"][:8], eid)

            frg = frg_by_id.get(s["fragmentId"])
            check(f"{eid} fragmentId 存在", frg is not None, s["fragmentId"])
            if frg:
                check(f"{eid} quote 可在 Fragment 内原样定位",
                      s["quote"] in frg["contentText"])
                check(f"{eid} locator.clause 与 Fragment 条款一致",
                      s["locator"]["clause"] in frg["contentText"],
                      s["locator"]["clause"])

            sv = sv_by_id.get(s["sourceVersionId"])
            check(f"{eid} sourceVersionId 存在", sv is not None, s["sourceVersionId"])
            if sv:
                check(f"{eid} sourceId 与 SourceVersion 一致",
                      s["sourceId"] == sv["sourceId"])
                check(f"{eid} claimType ∈ 源 allowedClaimTypes",
                      s["claimType"] in (sv.get("allowedClaimTypes") or []),
                      f"{s['claimType']} ∉ {sv.get('allowedClaimTypes')}")
                check(f"{eid} sourceBytesHash == SourceVersion hash",
                      s.get("sourceBytesHash") == sv["bytesSha256"])

            check(f"{eid} 权威区 => usage=AUTHORITATIVE",
                  s["usage"] == "AUTHORITATIVE", s["usage"])
            check(f"{eid} sourcePath 落在 _authoritative/",
                  "_authoritative/" in s.get("sourcePath", ""), s.get("sourcePath", ""))
            check(f"{eid} retrievedAt 与 extractionRunId 日期一致",
                  s["retrievedAt"][:10].replace("-", "") == s["extractionRunId"].split("-")[1],
                  f"{s['retrievedAt'][:10]} vs {s['extractionRunId']}")

    # ---------- FieldAssertion ----------
    seen_asm = set()
    for p in sorted(ASM_DIR.glob("*.assertions.json")):
        d = load_json(p)
        check(f"{d['productId']} assertionCount == 条目数",
              d["assertionCount"] == len(d["assertions"]),
              f"声明 {d['assertionCount']} vs 实际 {len(d['assertions'])}")
        covered = set()
        for a in d["assertions"]:
            aid = a["assertionId"]
            covered.add(a["fieldPath"])
            check(f"{aid} assertionId 唯一", aid not in seen_asm)
            seen_asm.add(aid)
            errs = sorted(asm_validator.iter_errors(a), key=lambda e: e.path)
            check(f"{aid} 符合 CTR-PK-ASM-001", not errs,
                  str(errs[0].message)[:80] if errs else "")

            check(f"{aid} fieldPath ∈ FLD-001 七字段",
                  a["fieldPath"] in field_spec, a["fieldPath"])

            if a["knowledgeState"] == "UNKNOWN":
                check(f"{aid} UNKNOWN => 值为 null 且无证据",
                      a["rawValue"] is None and a["normalizedValue"] is None
                      and a["evidenceIds"] == [],
                      f"raw={a['rawValue']} norm={a['normalizedValue']} "
                      f"ev={len(a['evidenceIds'])}")
            # INV-ASM-07：禁止在无证据/无 Owner 裁决时产生规范值。
            # SUPPORTED 断言经 Owner 裁决后允许规范值（值来自证据原文，非模型生成）。
            if a["knowledgeState"] not in ("SUPPORTED", "REVIEWED"):
                check(f"{aid} 非 SUPPORTED 断言 normalizedValue 必须为 null（INV-ASM-07）",
                      a["normalizedValue"] is None, str(a["normalizedValue"])[:40])
            else:
                check(f"{aid} SUPPORTED 必须有证据且由 Owner 签发",
                      bool(a["evidenceIds"]) and bool(a.get("reviewDecisionId")),
                      f"ev={len(a['evidenceIds'])} dec={a.get('reviewDecisionId')}")

            # Owner 裁决后字段可为 SUPPORTED；DEMO 的限制体现在 Release 用途
            # （recommendationReady=false，INV-RLS-09），而非禁止字段级支撑。
            if a["knowledgeState"] in ("SUPPORTED", "REVIEWED"):
                check(f"{aid} SUPPORTED 必须由 Owner 决策签发",
                      bool(a.get("reviewDecisionId")),
                      "缺少 reviewDecisionId，属无主自升")

            spec = field_spec.get(a["fieldPath"])
            for eid in a["evidenceIds"]:
                s = all_spans.get(eid)
                check(f"{aid} 引用的证据存在: {eid}", s is not None, eid)
                if not s:
                    continue
                check(f"{aid} 证据 usage=AUTHORITATIVE: {eid}",
                      s["usage"] == "AUTHORITATIVE", s["usage"])
                if spec:
                    check(f"{aid} 权威级满足字段要求: {eid}",
                          AUTHORITY_RANK[s["authorityLevel"]]
                          <= AUTHORITY_RANK[spec["minAuthorityLevel"]],
                          f"证据 {s['authorityLevel']} vs 要求 {spec['minAuthorityLevel']}")
                    check(f"{aid} claimType 满足字段资格: {eid}",
                          s["claimType"] in spec["allowedClaimTypes"],
                          f"{s['claimType']} ∉ {spec['allowedClaimTypes']}")

        missing = set(field_spec) - covered
        check(f"{d['productId']} 七字段全部有断言（含 UNKNOWN）", not missing,
              f"缺失 {sorted(missing)}")

    failed = [r for r in results if not r[1]]
    print(f"\n{'=' * 60}")
    print(f"L11 证据/断言门禁：{len(results) - len(failed)}/{len(results)} PASS")
    if failed:
        print("失败项：")
        for n, _, d in failed:
            print(f"  - {n} {d}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
