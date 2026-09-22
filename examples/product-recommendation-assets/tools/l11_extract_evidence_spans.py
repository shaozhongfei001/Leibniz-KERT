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

import argparse
import hashlib
import json
import os
import re
import subprocess
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
CLAUSE_RE = re.compile(r"^\*\*(第[一二三四五六七八九十百零〇]+条)\*\*\s*(.*)$")
# 通知体（无「条」的规范性文件，如 银发〔2018〕3 号）：顶层以「一、二、…」分节。
# ⚠ 与 l10 同规则 —— 仅当**该源全部片段都不是「第X条」**时才启用（见 main 内的 mode 判定）：
#   含「条」文件的附录也可能出现同形标记（如 REG-FIN-001 附录 3 处），一刀切会改动既有证据。
# locator 仍用合同允许的 kind="CLAUSE"（evidence-span.schema.json 为 const），clause 记**节序**（如「一」）；
# 该源的抽取粒度登记为 SECTION（通知体条款项），与"章条号"口径不同。
SECTION_RE = re.compile(r"^\*\*([一二三四五六七八九十]+)、\s*(.*?)\*\*\s*$")

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

def _resolve_args() -> argparse.Namespace:
    """PC8 T1/T2：产品与族可由命令行指定；**默认值保持既有行为不变**（PROD-CM-001 / CASH_MANAGEMENT）。

    `parse_known_args` 使本模块级解析不与各脚本 main() 内既有 argparse 冲突（如 l13 的 --decisions）。
    """
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("--product", default="PROD-CM-001")
    ap.add_argument("--family", default="CASH_MANAGEMENT")
    ap.add_argument("--all", action="store_true")
    args, _ = ap.parse_known_args()
    return args


_ARGS = _resolve_args()
PRODUCT_ID = _ARGS.product
FAMILY = _ARGS.family

# 目录名 ↔ taxonomy(CTR-PK-TAX-001) family id 适配表。
# 依据：03_core/<dir>/version=<x>/product-cards/ 是 KERT workspace 既有约定，dir 名与 taxonomy family 同源。
# 未单点化：taxonomy 目前未提供机器可读的 product→family 反查（记为 F-PC8-06，待单点化）。
FAMILY_BY_DIR = {
    "cash-management": "CASH_MANAGEMENT",
    "financing": "FINANCING",
    "settlement": "SETTLEMENT",
    "trade-finance": "TRADE_FINANCE",
    "cross-border": "CROSS_BORDER",
    "investment-banking": "INVESTMENT_BANKING",
}


def discover_products() -> list:
    """从 03_core 产品卡目录派生产品与族（`--all` 用），不新造产品清单。"""
    found = {}
    for card in sorted((BASE / "03_core").glob("*/version=*/product-cards/PROD-*.md")):
        dir_name = card.parent.parent.parent.name
        found[card.stem] = FAMILY_BY_DIR.get(dir_name)
    return found


SOURCE_REGISTRY = BASE / "01_raw" / "source-registry.md"


def _expand_product_ids(cell: str) -> set:
    """展开 registry 中的产品简写（PC8 F-PC8-20）。

    登记表用简写 `PROD-CM-001/002/003`；原实现只做 `re.findall(r"PROD-[A-Z]+-\\d{3}")`，
    只会命中第一个 id ⇒ **同一族后续产品被漏绑**（实测 `REG-CM-001` 仅绑定 `PROD-CM-001`，
    `PROD-CM-002/003` 因此长期拿不到族专属监管候选）。
    """
    out = set()
    for m in re.finditer(r"PROD-([A-Z]+)-(\d{3})((?:/\d{3})*)", cell):
        fam, first, rest = m.group(1), m.group(2), m.group(3)
        out.add(f"PROD-{fam}-{first}")
        for n in re.findall(r"\d{3}", rest):
            out.add(f"PROD-{fam}-{n}")
    return out


def load_source_product_binding() -> dict:
    """PC8 T8：从 `01_raw/source-registry.md` 族表（§5.1–§5.7）解析 `source_id → 被引用产品卡集合`。

    - 取值为「全部 13 张」⇒ 展开为全部产品卡 id；否则抽取其中的 `PROD-XX-NNN` 串。
    - 同一 source_id 出现在多张表时**取并集**（下游按并集判定合法性）。
    - §5.8 DEMO 行的「无（禁止沿用 13 张 legacy card）」**不并入**：该列的语义是 DEMO 源不得用于
      13 张 legacy 卡的真实结论，**不是**源自身的引用范围；DEMO 轨的合法引用范围取自同 source_id 的族表行。
      （该口径已上报 Owner，见 gits 侧 `B-6`；此处为**显式**选择，不做静默处理。）
    - **fail-closed**：解析不出任何绑定即退出非零（禁止"无绑定"放行）。
    """
    if not SOURCE_REGISTRY.is_file():
        raise SystemExit(f"FAIL | 源登记表不可读：{SOURCE_REGISTRY}（T8 fail-closed）")
    all_products = set(discover_products())
    bind = {}
    for line in SOURCE_REGISTRY.read_text(encoding="utf-8").splitlines():
        if not line.startswith("| ") or line.startswith("|---"):
            continue
        cols = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cols) < 7:
            continue
        sid, last = cols[0], cols[-1]
        if not re.fullmatch(r"(SRC|REG)-[A-Z]+-\d{3}", sid):
            continue
        if last.startswith("无"):
            continue
        ids = set(all_products) if "全部 13" in last else _expand_product_ids(last)
        if ids:
            bind.setdefault(sid, set()).update(ids)
    if not bind:
        raise SystemExit("FAIL | registry 未解析出任何「源→产品」绑定（T8 fail-closed）")
    return bind


# T4 挂起：本常量的语义待澄清（产品卡目录版本 vs Release 版本），澄清前**不改为派生**。
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


def load_policy_fields(family: str = FAMILY):
    """从 CTR-PK-FLD-001 读取**指定族**的字段策略实例。

    PC8 T2：**fail-closed** —— 找不到该族实例即非零退出，**不再回落** CASH_MANAGEMENT。
    理由：回落会让缺实例的族产出"现金管理字段"的假断言（看起来在干活，字段集其实是错的）。
    """
    doc = json.loads(POLICY.read_text(encoding="utf-8"))
    candidates = [ex for ex in doc.get("examples", [])
                  if ex.get("productFamily") == family
                  and (ex.get("_case") or "").split("—")[0].strip() == "POSITIVE"]
    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        raise SystemExit(
            f"FAIL | 未找到 {family} 的 POSITIVE 字段策略实例（CTR-PK-FLD-001 · field-policy.schema.json）；"
            f"按 fail-closed 拒绝回落其他族 —— 需先补齐该族实例（PC8 T3 / B-5b）"
        )
    raise SystemExit(
        f"FAIL | {family} 的 POSITIVE 实例数 = {len(candidates)}（期望恰好 1）——"
        f"拒绝在歧义下产出断言"
    )


def main():
    # PC8 T1：`--all` 从 03_core 产品卡目录派生逐产品执行（族由目录名映射，不新造清单）。
    # 注意：缺字段策略实例的族会在子进程中 fail-closed 退出 ⇒ 这是**期望行为**（T2 的依赖可见化）。
    if _ARGS.all:
        rc = 0
        for pid, fam in sorted(discover_products().items()):
            if fam is None:
                print(f"FAIL | {pid}: 目录名无法映射到 taxonomy family id")
                return 1
            print(f"\n=== {pid}（family={fam}）===")
            r = subprocess.run([sys.executable, __file__, "--product", pid, "--family", fam], check=False)
            rc = rc or r.returncode
        return rc

    policy = load_policy_fields(FAMILY)
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
        # 文档级模式开关（PC8 · REG-CB-001）：该源无任何「第X条」⇒ 按通知体顶层「一、」分节取条款。
        _heads = [f["contentText"].splitlines()[0] for f in d["fragments"] if f["contentText"].strip()]
        _sec_mode = not any(CLAUSE_RE.match(h) for h in _heads)
        boundary_re = SECTION_RE if _sec_mode else CLAUSE_RE
        for frg in d["fragments"]:
            _lines = frg["contentText"].splitlines()
            m = boundary_re.match(_lines[0])
            if not m:
                continue
            # 通知体：标记行**只有节标题**（不是引文）⇒ 引文一律取该节首个非空正文行；
            # 条式：沿用「标记行余下文本」为引文（既有行为，不改）。
            clause = m.group(1)
            quote = "" if _sec_mode else m.group(2).strip()
            if not quote:
                quote = next((ln.strip() for ln in _lines[1:] if ln.strip()), "")
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

    # PC8 T8：源 ↔ 产品绑定（**W2 强制前置**）。
    # 根因（F-PC8-07 实证）：此前按全部 fragments 无差别匹配，导致 PROD-CM-001 吸收了 SRC-CB-001/SRC-FIN-001
    # 等非登记源的证据。此处按 registry 族表的「被引用产品卡」列收窄参与集合。
    binding = load_source_product_binding()
    legal_sources = {sid for sid, prods in binding.items() if PRODUCT_ID in prods}
    if not legal_sources:
        print(f"FAIL | {PRODUCT_ID} 在 registry 中没有任何被引用源（T8 fail-closed，拒绝无绑定产出）")
        return 1
    scoped_spans = [s for s in all_spans if s["sourceId"] in legal_sources]
    print(f"SCOPE | {PRODUCT_ID} 合法源 {len(legal_sources)} 个｜参与证据 {len(scoped_spans)}/{len(all_spans)}"
          f"（剔除 {len(all_spans) - len(scoped_spans)} 条非登记源证据）")

    # ---------------- FieldAssertion 编译 ----------------
    ASM_DIR.mkdir(parents=True, exist_ok=True)
    assertions = []
    for spec in fields:
        fp_ = spec["fieldPath"]
        kws = FIELD_KEYWORDS.get(fp_, [])
        allow_types = set(spec["allowedClaimTypes"])
        need_rank = AUTHORITY_RANK[spec["minAuthorityLevel"]]
        matched = []
        for s in scoped_spans:
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
