#!/usr/bin/env python3
"""Release 发布与三视图投影（Loop L13 · KERT 侧）

产出：
  04_serve/releases/RLS-*.json              （CTR-PK-RLS-001 实例）
  04_serve/interpretation/PROD-CM-001.json  （CTR-PK-INT-001 三视图投影，供 GITS 消费）
  90_control/decisions/DECISIONS.template.json（待 Owner 签署的决策模板）

**红线：AI / 脚本不得代替 Owner 决定。**
本脚本**不会**自动生成任何 ReviewDecision：
  - 未传入经 Owner 签署的决策文件 ⇒ lifecycleState=DRAFT，publishedAt=null，
    并在 90_control/BLOCKED_ON_OWNER.json 记录最小请求；
  - 传入 `--decisions <file>` 且该文件含 `ownerAttested=true` + `attestedBy`
    + 每项 decidedByRole ∈ {PRODUCT_OWNER, RISK_OWNER, COMPLIANCE_OWNER}
    ⇒ 生成 ReviewDecision 并将 Release 置为 PUBLISHED。

DEMO 派生 Release 的 recommendationReady **恒为 false**（INV-EVS-09）。

用法:
    python3 tools/l13_publish_release.py
    python3 tools/l13_publish_release.py --decisions 90_control/decisions/signed.json
"""

import argparse
import hashlib
import json
import os
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
SV_DIR = BASE / "02_work" / "source-versions"
REL_DIR = BASE / "04_serve" / "releases"
INT_DIR = BASE / "04_serve" / "interpretation"
DEC_DIR = BASE / "90_control" / "decisions"

CST = timezone(timedelta(hours=8))
OWNER_ROLES = {"PRODUCT_OWNER", "RISK_OWNER", "COMPLIANCE_OWNER"}
VIEW_FIELDS = {
    "OVERVIEW": ["identity.productCode", "compliance.regulatoryBasis"],
    "ELIGIBILITY": ["eligibility.customerSegment", "eligibility.minAccountBalance",
                    "eligibility.prerequisiteProducts"],
    "PRICING": ["pricing.serviceFee"],
}
PRODUCT_ID = "PROD-CM-001"
TAXONOMY_VERSION = "CTR-PK-TAX-001@v1"


def sha256_text(t: str) -> str:
    return hashlib.sha256(t.encode("utf-8")).hexdigest()


def now_cst() -> datetime:
    epoch = os.environ.get("SOURCE_DATE_EPOCH")
    if epoch:
        return datetime.fromtimestamp(int(epoch), CST)
    return datetime.now(CST)


def load(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))


def validate_decisions(doc):
    """决策文件合法性：必须 Owner 签署 + 每项为 Owner 角色。"""
    errs = []
    if not isinstance(doc, dict):
        return ["决策文件不是对象"]
    if doc.get("ownerAttested") is not True:
        errs.append("缺少 ownerAttested=true（未签署的决策不得用于发布）")
    if not doc.get("attestedBy"):
        errs.append("缺少 attestedBy（须为自然人 Owner 标识）")
    for i, d in enumerate(doc.get("decisions", [])):
        if d.get("decidedByRole") not in OWNER_ROLES:
            errs.append(f"decisions[{i}].decidedByRole 非 Owner 角色: {d.get('decidedByRole')}")
        for k in ("decisionId", "subjectKind", "subjectId", "decision", "rationale", "decidedBy"):
            if not d.get(k):
                errs.append(f"decisions[{i}] 缺字段 {k}")
    return errs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--decisions", type=str, default=None,
                    help="Owner 已签署的决策文件路径")
    args = ap.parse_args()

    asm = load(ASM_DIR / f"{PRODUCT_ID}.assertions.json")
    health = load(RPT_DIR / f"{PRODUCT_ID}.health.json")
    card = load(CARD_DIR / f"{PRODUCT_ID}.candidate-card.json")
    conflicts = load(CNF_DIR / f"{PRODUCT_ID}.conflicts.json")

    evs = {}
    for p in EVS_DIR.glob("*.evidence-spans.json"):
        for s in load(p)["evidenceSpans"]:
            evs[s["evidenceId"]] = s
    svs = {load(p)["sourceVersionId"]: load(p) for p in SV_DIR.glob("SV-*.json")}

    ts = now_cst()
    date_compact = ts.strftime("%Y%m%d")
    release_id = f"RLS-{ts.strftime('%Y.%m.%d')}.1"
    if (REL_DIR / f"{release_id}.json").exists():
        n = 2
        while (REL_DIR / f"RLS-{ts.strftime('%Y.%m.%d')}.{n}.json").exists():
            n += 1
        release_id = f"RLS-{ts.strftime('%Y.%m.%d')}.{n}"

    # ---- 四个 manifest hash ----
    assertion_manifest = sorted(a["assertionId"] for a in asm["assertions"])
    evidence_manifest = sorted(evs)
    a_hash = sha256_text("|".join(assertion_manifest))
    e_hash = sha256_text("|".join(evidence_manifest))
    c_hash = sha256_text(json.dumps(card, sort_keys=True, ensure_ascii=False))
    r_hash = sha256_text("RULEPACKAGE:EMPTY")  # L13 未引入规则包，显式占位
    bundle = sha256_text(a_hash + e_hash + c_hash + r_hash)
    quality_run = "QR-" + date_compact + "-" + sha256_text(bundle)[:8]

    # ---- 用途门禁（INV-RLS-02 / INV-EVS-09）----
    blockers = health["blockers"]
    interpretation_ready = not blockers
    recommendation_ready = False  # DEMO 派生恒 false
    gate_report = {
        "requiredHardFieldsTotal": sum(1 for f in health["fields"]
                                       if f["required"] == "REQUIRED_HARD"),
        "supported": sum(1 for f in health["fields"]
                         if f["required"] == "REQUIRED_HARD" and f["knowledgeState"] == "SUPPORTED"),
        "unknown": sum(1 for f in health["fields"] if f["knowledgeState"] == "UNKNOWN"),
        "conflict": sum(1 for f in health["fields"] if f["knowledgeState"] == "CONFLICT"),
        "stale": 0,
        "notApplicableApproved": 0,
        "blockingReasons": [f"{b['fieldPath']}={b['state']}" for b in blockers],
    }

    # ---- Owner 决议 ----
    decisions = []
    owner_decision_ids = []
    lifecycle = "DRAFT"
    published_at = None
    if args.decisions:
        doc = load(Path(args.decisions))
        errs = validate_decisions(doc)
        if errs:
            print("FAIL | 决策文件不合法：")
            for e in errs:
                print("  -", e)
            return 2
        for d in doc["decisions"]:
            decisions.append({k: d[k] for k in
                              ("decisionId", "subjectKind", "subjectId", "decision",
                               "rationale", "decidedBy", "decidedByRole")}
                             | {"decidedAt": d.get("decidedAt", ts.isoformat())})
            owner_decision_ids.append(d["decisionId"])
        lifecycle = "PUBLISHED"
        published_at = ts.isoformat()

    DEC_DIR.mkdir(parents=True, exist_ok=True)
    if decisions:
        (DEC_DIR / "review-decisions.json").write_text(
            json.dumps({"attestedBy": load(Path(args.decisions))["attestedBy"],
                        "decisions": decisions},
                       ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8")
    else:
        (DEC_DIR / "DECISIONS.template.json").write_text(
            json.dumps({
                "_notice": "模板：须由 Owner 签署后另存为 signed.json 并通过 --decisions 传入。"
                           "脚本不会代替 Owner 生成任何决定。",
                "ownerAttested": False,
                "attestedBy": "",
                "decisions": [
                    {"decisionId": "DEC-YYYYMMDD-xxxxxxxx", "subjectKind": "CONFLICT",
                     "subjectId": conflicts["conflicts"][0]["conflictId"]
                     if conflicts["conflicts"] else "",
                     "decision": "ADOPT_ASSERTION", "rationale": "",
                     "decidedBy": "", "decidedByRole": "PRODUCT_OWNER"}
                ],
            }, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    release = {
        "releaseId": release_id,
        "productIds": [PRODUCT_ID],
        "taxonomyVersion": TAXONOMY_VERSION,
        "lifecycleState": lifecycle,
        "purposeFlags": {"interpretationReady": interpretation_ready,
                         "recommendationReady": recommendation_ready},
        "assertionManifestHash": a_hash,
        "evidenceManifestHash": e_hash,
        "cardProjectionHash": c_hash,
        "rulePackageHash": r_hash,
        "qualityRunId": quality_run,
        "ownerDecisionIds": owner_decision_ids,
        "bundleHash": bundle,
        "publishedAt": published_at,
        "staleFlag": {"isStale": False, "staleReason": None, "staleSince": None,
                      "triggeringSourceVersionId": None},
        "gateReport": gate_report,
        "provenanceState": "DEMO",
    }
    REL_DIR.mkdir(parents=True, exist_ok=True)
    (REL_DIR / f"{release_id}.json").write_text(
        json.dumps(release, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")

    # ---- 三视图投影（CTR-PK-INT-001）----
    field_state = {f["fieldPath"]: f for f in health["fields"]}
    asm_by_field = {}
    for a in asm["assertions"]:
        asm_by_field.setdefault(a["fieldPath"], []).append(a)

    views = {}
    for view, fps in VIEW_FIELDS.items():
        items = []
        for fp in fps:
            st = field_state.get(fp, {})
            state = st.get("knowledgeState", "UNKNOWN")
            # CTR-PK-INT-001 呈现枚举只有 5 态；CANDIDATE 未经 Owner 复核，
            # 按 fail-closed 归一为 UNKNOWN，且不得回链证据（未复核结论不呈现）。
            if state == "CANDIDATE":
                state = "UNKNOWN"
            # 未就绪状态一律 displayValue=null，禁止补齐
            display = None
            if state == "SUPPORTED":
                sup = next((a for a in asm_by_field.get(fp, [])
                            if a["knowledgeState"] == "SUPPORTED"), None)
                val = (sup or {}).get("normalizedValue")
                if isinstance(val, (int, float)):
                    display = f"{val / 10000:g} 万元" if val >= 10000 else f"{val:g} 元"
                elif val is not None:
                    display = str(val)
            summaries = []
            if state not in ("UNKNOWN", "CONFLICT", "STALE"):
                for a in asm_by_field.get(fp, []):
                    for eid in a["evidenceIds"]:
                        ev = evs.get(eid)
                        if not ev:
                            continue
                        loc = ev["locator"]
                        hint = loc.get("clause") or f"p.{loc.get('page', '?')}"
                        summaries.append({
                            "evidenceId": ev["evidenceId"],
                            "sourceId": ev["sourceId"],
                            "sourceVersionId": ev["sourceVersionId"],
                            "authorityLevel": ev["authorityLevel"],
                            "locatorHint": hint,
                            "quoteExcerpt": ev["quote"][:200],
                        })
            items.append({
                "fieldPath": fp,
                "displayValue": display,
                "knowledgeState": state,
                "evidenceSummaries": summaries,
                "conflictId": st.get("conflictId"),
            })
        views[view] = items

    projection = {
        "productId": PRODUCT_ID,
        "releaseId": release_id,
        "bundleHash": bundle,
        "lifecycleState": lifecycle,
        "isStale": False,
        "staleReason": None,
        "provenanceState": "DEMO",
        "purposeAllowed": {"INTERPRETATION": interpretation_ready,
                           "RECOMMENDATION": recommendation_ready},
        "views": views,
        "sourceVersions": sorted(svs),
        "generatedAt": ts.isoformat(),
    }
    INT_DIR.mkdir(parents=True, exist_ok=True)
    (INT_DIR / f"{PRODUCT_ID}.json").write_text(
        json.dumps(projection, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")

    if lifecycle != "PUBLISHED":
        (BASE / "90_control" / "BLOCKED_ON_OWNER.json").write_text(
            json.dumps({
                "blockedAt": ts.isoformat(),
                "releaseId": release_id,
                "lifecycleState": lifecycle,
                "reason": "缺少 Owner 签署的 ReviewDecision，Release 不得 PUBLISHED",
                "minimumRequest": [
                    "对冲突 CNF 的择定（decisionId / resolvedAssertionId / rationale）",
                    "对 UNKNOWN 的 REQUIRED_HARD 字段是否 NOT_APPLICABLE 的裁决",
                    "attestedBy（自然人 Owner 标识）与 ownerAttested=true",
                ],
                "unblockCommand": "python3 tools/l13_publish_release.py "
                                  "--decisions 90_control/decisions/signed.json",
            }, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8")

    print(f"releaseId={release_id} lifecycle={lifecycle} "
          f"interpretationReady={interpretation_ready} "
          f"recommendationReady={recommendation_ready} bundle={bundle[:16]}…")
    if lifecycle != "PUBLISHED":
        print("BLOCKED_ON_OWNER: 未获 Owner 签署决策，Release 保持 DRAFT（不冒充已发布）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
