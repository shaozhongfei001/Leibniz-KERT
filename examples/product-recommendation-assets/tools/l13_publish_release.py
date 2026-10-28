#!/usr/bin/env python3
"""Release 发布（Loop L13 · KERT 侧）

产出：
  04_serve/releases/RLS-*.json              （CTR-PK-RLS-001 实例）
  90_control/decisions/DECISIONS.template.json（待 Owner 签署的决策模板）

2026-10-28：原产出的 04_serve/interpretation/PROD-*.json（CTR-PK-INT-001 三视图投影）
已随 GITS「产品知识」页下线一并移除生成逻辑 —— GITS 侧消费方
（KertReleaseSnapshotAdapter 与解读/检索端点）已删除，该投影不再有消费者。

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
DEC_DIR = BASE / "90_control" / "decisions"

CST = timezone(timedelta(hours=8))
OWNER_ROLES = {"PRODUCT_OWNER", "RISK_OWNER", "COMPLIANCE_OWNER"}
def _resolve_args() -> argparse.Namespace:
    """PC8 T1：产品可由命令行指定；**默认值保持既有行为不变**（PROD-CM-001）。

    `parse_known_args` 使本模块级解析不与 main() 内既有 `--decisions` 解析冲突。
    """
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("--product", default="PROD-CM-001")
    args, _ = ap.parse_known_args()
    return args


PRODUCT_ID = _resolve_args().product
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
    ap.add_argument("--product", type=str, default=None,
                    help="PC8 T1：覆盖产品（默认取模块级 PROD-CM-001）")
    args = ap.parse_args()
    global PRODUCT_ID
    if args.product:
        PRODUCT_ID = args.product

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
    rule_pkg = BASE / "04_serve" / "rule-packages" / f"{PRODUCT_ID}.rule-package.json"
    # 规则包已依 ADR-PK-PRODUCT-RULES-ASSET 路径 A 建资产并落容器文件；
    # 内容仍为 NOT_BUILT，哈希只代表容器，不代表规则已生效。
    r_hash = (sha256_text(rule_pkg.read_text(encoding="utf-8"))
              if rule_pkg.exists() else sha256_text("RULEPACKAGE:EMPTY"))
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
        # PC8 F-PC8-14（fail-closed）：决策文件**没有任何决策项**时不得据此发布。
        # 依据（实测）：曾用一份 0 决策的签署件发布，得到 lifecycle=PUBLISHED 但 ownerDecisionIds=[]，
        # 直接违反 L13 门禁「已发布 ⇒ ownerDecisionIds 非空」（产出 13 份违规 Release 需事后清理）。
        if not doc.get("decisions"):
            print("FAIL | 决策文件不含任何决策项，拒绝据此发布（否则 PUBLISHED 且 ownerDecisionIds 为空）")
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
