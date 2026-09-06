#!/usr/bin/env python3
"""EvidenceSpan 抽取 + FieldAssertion 编译（Loop L11）

输入：L10 产出的 SourceVersion / Fragment + 制度文本 front matter
输出：02_work/evidence-spans/*.json   （CTR-PK-EVS-002 实例）
      02_work/assertions/*.json       （CTR-PK-ASM-001 实例）

设计约束（红线）：
  1. 不发明合同未定义字段 —— 字段集合与 ID 规则全部取自
     CTR-PK-EVS-002 / CTR-PK-ASM-001；
  2. AI/脚本只能产出 **CANDIDATE** 断言与原文 rawValue，
     **不得**产生 normalizedValue（INV-ASM-07），不得把 UNKNOWN 补齐为值；
  3. 不合格证据一律不参与：claimType ∉ 源 allowedClaimTypes（INV-EVS-05）、
     权威级低于字段 minAuthorityLevel（INV-FLD-02）的证据直接丢弃；
  4. 冲突检测与 ConflictCase 属 L12，本 Loop 不做合并择一，
     同一字段可产出多条 CANDIDATE 断言（含互相矛盾者）。
  5. 确定性：evidenceId/assertionId 后缀 = SHA-256(quote|key)[:8]，
     SOURCE_DATE_EPOCH 固定时产出逐字节可复现。

用法:
    python3 tools/l11_extract_evidence_spans.py
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
AUTH = BASE / "01_raw" / "_authoritative"
SV_DIR = BASE / "02_work" / "source-versions"
FRG_DIR = BASE / "02_work" / "fragments"
EVS_DIR = BASE / "02_work" / "evidence-spans"
ASM_DIR = BASE / "02_work" / "assertions"
POLICY = GITS / "specs" / "product-knowledge" / "field-policy.schema.json"

CST = timezone(timedelta(hours=8))
CLAUSE_RE = re.compile(r"^\*\*(第[一二三四五六七八九十百]+条)\*\*\s*(.*)$")

# 权威级排序：数值越小权威越高。证据权威级必须 <= 字段要求的权威级
AUTHORITY_RANK = {
    "REGULATORY": 1,
    "INTERNAL_POLICY": 2,
    "PUBLIC_PRICE_DISCLOSURE": 3,
    "PUBLIC_MARKETING": 4,
}

# claimType 关键词表（确定性规则，非模型推断）
CLAIM_KEYWORDS = {
    "PRICE": ["服务费", "费率", "收费", "计息", "利率", "罚息", "价格", "百分点"],
    "ELIGIBILITY": ["准入", "客户分层", "评级", "适用于", "最低留存", "日均余额",
                    "不予", "应当同时满足", "条件"],
    "PROCESS": ["渠道", "柜面", "网银", "流程", "办理", "直联", "认证", "签署"],
    "RISK": ["风险", "防范", "隔离", "逾期", "违约", "排查", "控制"],
    "REGULATORY": ["条例", "监管", "合规", "规定", "识别", "报送"],
}

# 字段命中规则：fieldPath -> 关键词（须同时满足 claimType ∈ allowedClaimTypes）
FIELD_KEYWORDS = {
    "identity.productCode": ["产品代码", "产品简称"],
    "eligibility.customerSegment": ["客户分层", "大型企业客户", "集团客户", "机构客户"],
    "eligibility.minAccountBalance": ["最低留存余额", "日均余额"],
    "eligibility.prerequisiteProducts": ["先行", "前置", "不少于三家", "方可", "应当先"],
    "pricing.serviceFee": ["服务费", "收费"],
    "compliance.regulatoryBasis": ["条例", "监管", "合规", "规定"],
    "process.openingChannel": ["渠道", "柜面", "企业网银", "银企直联"],
}

PRODUCT_ID = "PROD-CM-001"
PRODUCT_VERSION_SCOPE = "version=2026.09.06.1"


def sha256_text(t: str) -> str:
    return hashlib.sha256(t.encode("utf-8")).hexdigest()


def now_cst() -> datetime:
    epoch = os.environ.get("SOURCE_DATE_EPOCH")
    if epoch:
        return datetime.fromtimestamp(int(epoch), CST)
    return datetime.now(CST)


def sid_key(s: str) -> str:
    return s.replace("-", "")


def front_matter_effective_date(source_id: str) -> str:
    path = AUTH / f"{source_id}.DEMO.md"
    if not path.exists():
        return "2026-09-06"
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^effective_date:\s*\"?(\d{4}-\d{2}-\d{2})\"?", line)
        if m:
            return m.group(1)
    return "2026-09-06"


def classify_claim_type(quote: str, allowed: list) -> str:
    """按关键词表判定 claimType；只返回源允许的取值，否则 None。"""
    for ctype in allowed:
        for kw in CLAIM_KEYWORDS.get(ctype, []):
            if kw in quote:
                return ctype
    return None


def load_policy_fields():
    """从 CTR-PK-FLD-001 的 CASH_MANAGEMENT 正例读取七字段策略。"""
    doc = json.loads(POLICY.read_text(encoding="utf-8"))
    for ex in doc.get("examples", []):
        if ex.get("productFamily") == "CASH_MANAGEMENT":
            return ex
    raise SystemExit("未找到 CASH_MANAGEMENT 字段策略实例")


def main():
    policy = load_policy_fields()
    fields = policy["fields"]
    retrieved = now_cst()
    run_date = retrieved.strftime("%Y%m%d")

    sv_by_id = {}
    for p in sorted(SV_DIR.glob("SV-*.json")):
        sv = json.loads(p.read_text(encoding="utf-8"))
        sv_by_id[sv["sourceVersionId"]] = sv

    all_spans = []
    for fp in sorted(FRG_DIR.glob("*.fragments.json")):
        d = json.loads(fp.read_text(encoding="utf-8"))
        sv = sv_by_id.get(d["sourceVersionId"])
        if sv is None:
            print(f"FAIL | 找不到 SourceVersion: {d['sourceVersionId']}")
            return 1
        allowed = sv.get("allowedClaimTypes") or []
        eff_from = front_matter_effective_date(d["sourceId"])
        spans = []
        for frg in d["fragments"]:
            m = CLAUSE_RE.match(frg["contentText"].splitlines()[0])
            if not m:
                continue
            clause, quote = m.group(1), m.group(2).strip()
            if not quote:
                continue
            ctype = classify_claim_type(quote, allowed)
            if ctype is None:
                # INV-EVS-05：claimType 不在源允许集内的条款不产出证据
                continue
            quote_hash = sha256_text(quote)
            spans.append({
                "evidenceId": f"EVS-{sid_key(d['sourceId'])}-{quote_hash[:8]}",
                "sourceId": d["sourceId"],
                "sourceVersionId": d["sourceVersionId"],
                "fragmentId": frg["fragmentId"],
                "locator": {"kind": "CLAUSE", "clause": clause, "clauseVerified": False},
                "quote": quote,
                "quoteHash": quote_hash,
                "usage": "AUTHORITATIVE",
                "authorityLevel": sv.get("authorityLevel") or "INTERNAL_POLICY",
                "claimType": ctype,
                "applicabilityScope": {"effectiveFrom": eff_from, "effectiveTo": None},
                "extractionRunId": "RUN-PLACEHOLDER",
                "retrievedAt": retrieved.isoformat(),
                "sourcePath": sv["sourcePath"],
                "sourceBytesHash": sv["bytesSha256"],
            })
        if not spans:
            continue
        EVS_DIR.mkdir(parents=True, exist_ok=True)
        (EVS_DIR / f"{d['sourceId']}.evidence-spans.json").write_text(
            json.dumps({"sourceId": d["sourceId"],
                        "sourceVersionId": d["sourceVersionId"],
                        "evidenceCount": len(spans),
                        "evidenceSpans": spans},
                       ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8")
        all_spans.extend(spans)
        print(f"OK | {d['sourceId']} | evidenceSpans={len(spans)}")

    if not all_spans:
        print("FAIL | 未抽取到任何 EvidenceSpan")
        return 1

    run_id = "RUN-" + run_date + "-" + sha256_text(
        "".join(s["quoteHash"] for s in all_spans))[:8]
    for fp in sorted(EVS_DIR.glob("*.evidence-spans.json")):
        d = json.loads(fp.read_text(encoding="utf-8"))
        for s in d["evidenceSpans"]:
            s["extractionRunId"] = run_id
        fp.write_text(json.dumps(d, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                      encoding="utf-8")
    for s in all_spans:
        s["extractionRunId"] = run_id

    # ---------------- FieldAssertion 编译 ----------------
    ASM_DIR.mkdir(parents=True, exist_ok=True)
    assertions = []
    for spec in fields:
        fp_ = spec["fieldPath"]
        kws = FIELD_KEYWORDS.get(fp_, [])
        allow_types = set(spec["allowedClaimTypes"])
        need_rank = AUTHORITY_RANK[spec["minAuthorityLevel"]]
        matched = []
        for s in all_spans:
            if s["claimType"] not in allow_types:
                continue
            if AUTHORITY_RANK[s["authorityLevel"]] > need_rank:
                continue  # INV-FLD-02：权威级不足的证据不参与
            if not any(k in s["quote"] for k in kws):
                continue
            matched.append(s)

        # OQ-C 未裁决 + ownerDecisionRequired：策略未获 Owner 批准前一律 UNKNOWN
        if spec.get("ownerDecisionRequired") and not policy.get("ownerApproved", False):
            matched = []

        if not matched:
            assertions.append({
                "assertionId": f"ASM-{sid_key(PRODUCT_ID)}-"
                               f"{sha256_text(PRODUCT_ID + '|' + fp_ + '|UNKNOWN')[:8]}",
                "productId": PRODUCT_ID,
                "productVersionScope": PRODUCT_VERSION_SCOPE,
                "fieldPath": fp_,
                "rawValue": None,
                "normalizedValue": None,
                "valueType": spec["valueType"] if spec["valueType"] != "ENUM_ARRAY" else "ENUM",
                "knowledgeState": "UNKNOWN",
                "applicabilityScope": {"effectiveFrom": "2026-09-06", "effectiveTo": None},
                "evidenceIds": [],
                "conflictId": None,
                "reviewDecisionId": None,
                "supersedes": None,
                "createdByRunId": run_id,
                "createdAt": retrieved.isoformat(),
            })
            continue

        for s in matched:
            assertions.append({
                "assertionId": f"ASM-{sid_key(PRODUCT_ID)}-"
                               f"{sha256_text(PRODUCT_ID + '|' + fp_ + '|' + s['evidenceId'])[:8]}",
                "productId": PRODUCT_ID,
                "productVersionScope": PRODUCT_VERSION_SCOPE,
                "fieldPath": fp_,
                "rawValue": s["quote"],
                "normalizedValue": None,  # INV-ASM-07：CANDIDATE 阶段禁止产生规范值
                "valueType": spec["valueType"] if spec["valueType"] != "ENUM_ARRAY" else "ENUM",
                "knowledgeState": "CANDIDATE",
                "applicabilityScope": {"effectiveFrom": s["applicabilityScope"]["effectiveFrom"],
                                       "effectiveTo": None},
                "evidenceIds": [s["evidenceId"]],
                "conflictId": None,
                "reviewDecisionId": None,
                "supersedes": None,
                "createdByRunId": run_id,
                "createdAt": retrieved.isoformat(),
            })

    (ASM_DIR / f"{PRODUCT_ID}.assertions.json").write_text(
        json.dumps({"productId": PRODUCT_ID,
                    "productVersionScope": PRODUCT_VERSION_SCOPE,
                    "policyId": policy["policyId"],
                    "policyOwnerApproved": policy.get("ownerApproved", False),
                    "extractionRunId": run_id,
                    "assertionCount": len(assertions),
                    "assertions": assertions},
                   ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")

    (EVS_DIR / "manifest.json").write_text(
        json.dumps({"extractionRunId": run_id,
                    "generatedAt": retrieved.isoformat(),
                    "evidenceCount": len(all_spans),
                    "assertionCount": len(assertions),
                    "bySource": {d["sourceId"]: d["evidenceCount"]
                                 for d in [json.loads(p.read_text(encoding="utf-8"))
                                           for p in sorted(EVS_DIR.glob("*.evidence-spans.json"))]}},
                   ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")

    states = {}
    for a in assertions:
        states[a["knowledgeState"]] = states.get(a["knowledgeState"], 0) + 1
    print(f"\nrun={run_id} · evidenceSpans={len(all_spans)} · assertions={len(assertions)} · {states}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
