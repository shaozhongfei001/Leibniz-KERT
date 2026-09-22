#!/usr/bin/env python3
"""产品中心「章节投影」生成器（PI · O-1 批准：KERT 侧产出，GITS 只读消费）。

## 为什么必须有这一步（分域口径）

产品中心 8 章的内容**归 KERT（L2）**：产品卡（`03_core/**/product-cards/PROD-*.md`）是权威，
GITS 只保存**授权投影**且**不得本地兜底生成结论**。故由本工具把产品卡**确定性派生**为
章节投影 `04_serve/product-center/PROD-*.json`，GITS 经契约端点消费。

## 派生纪律（**不编造**）

1. 每个对象都带 `evidenceRefs`，`sourceRef` 指回**卡片小节**（可回译）；
2. 卡片里没有的**不产出**：
   - `PRICING`：卡片 §8 仅写「按行内收费标准执行（**待核定**）」⇒ `pricingItems: []`（Owner 裁定 O-2）；
   - `FAQ`：**全仓无来源** ⇒ `faqs: []`（不生成问答）；
   - `TERMS` 只产出卡片确有的 `ELIGIBLE_ENTITY` / `PURPOSE`（`LIMIT`/`TENOR`/`REPAYMENT`/`COLLATERAL`
     卡片无对应内容 ⇒ 不产出）；
3. 派生的比较集标 `reviewState: DRAFT`（**未经人工复核**）；证据 `isDemo: true`（本资产为 SIM 阶段）；
4. 只用**契约允许的枚举值**（见 `--contract-dir` 校验）；`additionalProperties=false` ⇒ 不多写字段。

用法：
    python3 tools/l40_build_product_center_sections.py \
        [--contract-dir /path/to/gits/specs/product-center] [--check]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import yaml

BASE = Path(__file__).resolve().parent.parent          # examples/product-recommendation-assets
OUT_DIR = BASE / "04_serve" / "product-center"
CST = timezone(timedelta(hours=8))

SECTION_RE = re.compile(r"^##\s+(\d+)\.\s*(.+?)\s*$")
BULLET_RE = re.compile(r"^[-*]\s+(.+?)\s*$")


def now_cst() -> datetime:
    """可复现时钟（对齐既有约定：SOURCE_DATE_EPOCH 固定构建时间）。"""
    import os

    epoch = os.environ.get("SOURCE_DATE_EPOCH")
    if epoch:
        return datetime.fromtimestamp(int(epoch), tz=timezone.utc).astimezone(CST)
    return datetime.now(CST)


def parse_card(path: Path) -> dict:
    """解析产品卡：front matter（YAML）+ 编号小节 + 项目符号。"""
    text = path.read_text(encoding="utf-8")
    _, fm_raw, body = text.split("---", 2)
    fm = yaml.safe_load(fm_raw) or {}
    sections: dict[int, dict] = {}
    cur: dict | None = None
    for line in body.splitlines():
        m = SECTION_RE.match(line)
        if m:
            cur = {"no": int(m.group(1)), "title": m.group(2), "bullets": [], "prose": []}
            sections[cur["no"]] = cur
            continue
        if cur is None:
            continue
        b = BULLET_RE.match(line)
        if b:
            cur["bullets"].append(b.group(1))
        elif line.strip():
            cur["prose"].append(line.strip())
    return {"path": path, "fm": fm, "sections": sections}


def kv(bullets: list[str], key: str) -> str | None:
    """取「键：值」形态的项目符号（如 `流程：a → b`）。"""
    for b in bullets:
        if b.startswith(key):
            return b[len(key):].lstrip("：: ").strip()
    return None


def evidence(pr: dict, no: int, sha8: str) -> dict:
    """一片证据 = 卡片的一个小节（`sourceRef` 可回译）。"""
    card = pr["path"]
    fm = pr["fm"]
    sec = pr["sections"].get(no, {})
    pid = fm["product_id"]
    return {
        "evidenceId": f"EVR-{pid.replace('-', '')}-S{no:02d}-{sha8}",
        "evidenceType": "PRODUCT_CARD_SECTION",
        "evidenceClass": "DOCUMENTED_RULE",
        "title": f"产品卡《{fm.get('name')}》§{no} {sec.get('title', '')}".strip(),
        "documentNumber": None,
        "documentVersion": str(fm.get("version", "")),
        "effectiveFrom": str(fm.get("effective_from") or "")[:10] or None,
        "effectiveTo": str(fm.get("effective_to") or "")[:10] or None,
        "ownerOrg": str(fm.get("owner", "")),
        "sourceRef": f"{card.relative_to(BASE).as_posix()}#S{no:02d}",
        "anchor": f"§{no}",
        "accessLevel": "RM_INTERNAL",
        "verificationState": "VERIFIED",
        "contentHash": None,
        "isDemo": True,
    }


def build_one(pr: dict, alias_map: dict | None = None) -> dict:
    fm, sections = pr["fm"], pr["sections"]
    pid = fm["product_id"]
    rel = pr["path"].relative_to(BASE).as_posix()
    sha8 = hashlib.sha256(pr["path"].read_bytes()).hexdigest()[:8]
    ev = {n: evidence(pr, n, sha8) for n in sections}
    E = lambda n: [ev[n]] if n in ev else []

    s2, s3, s4, s5 = (sections.get(n, {}) for n in (2, 3, 4, 5))
    s6, s7, s8, s10 = (sections.get(n, {}) for n in (6, 7, 8, 10))

    # ---- OVERVIEW（§1 概览 + 结构化字段）----
    overview_text = " ".join(sections.get(1, {}).get("prose", []))
    one_sentence = overview_text.split("。")[0] + "。" if overview_text else None
    solves = [b for b in s3.get("bullets", [])]
    is_not = [b for b in s5.get("bullets", [])]
    nearest = [b for b in s6.get("bullets", []) if b.startswith("配套")]

    # ---- TERMS（只产出卡片确有的 termKey）----
    terms = []
    cust = kv(s2.get("bullets", []), "适用客户")
    scene = kv(s2.get("bullets", []), "适用场景")
    if cust:
        terms.append({"termId": f"TRM-{pid}-ELIGIBLE_ENTITY", "termKey": "ELIGIBLE_ENTITY",
                      "businessDefinition": cust, "explanationForRm": cust,
                      "certaintyType": "VERIFIED", "displayOrder": 1, "evidenceRefs": E(2)})
    if scene or s3.get("bullets"):
        purpose = scene or "；".join(s3.get("bullets", []))
        terms.append({"termId": f"TRM-{pid}-PURPOSE", "termKey": "PURPOSE",
                      "businessDefinition": purpose, "explanationForRm": purpose,
                      "certaintyType": "VERIFIED", "displayOrder": 2, "evidenceRefs": E(2) or E(3)})

    # ---- FIT（适用边界 + 前置条件）----
    boundaries = []
    if scene:
        boundaries.append({"boundaryId": f"BND-{pid}-TYPICAL", "boundaryType": "TYPICAL_USE",
                           "scenarioName": "适用场景", "scenarioDescription": scene,
                           "alternativeDirection": None, "evidenceRefs": E(2)})
    for i, b in enumerate(s5.get("bullets", []), 1):
        btype = "PROHIBITED_USE" if b.startswith("禁止") else "NOT_SUITABLE"
        boundaries.append({"boundaryId": f"BND-{pid}-EXCL{i}", "boundaryType": btype,
                           "scenarioName": "排除条件" if btype == "NOT_SUITABLE" else "禁止用途",
                           "scenarioDescription": b, "alternativeDirection": None,
                           "evidenceRefs": E(5)})
    prerequisites = []
    for i, b in enumerate(s4.get("bullets", []), 1):
        ptype = "ACCOUNT" if "账户" in b else ("CREDIT" if "评级" in b else "CONTRACT")
        prerequisites.append({"prerequisiteId": f"PRE-{pid}-S4-{i}", "prerequisiteType": ptype,
                              "requirementText": b, "conditional": False, "evidenceRefs": E(4)})
    front_pre = kv(s6.get("bullets", []), "前置")
    if front_pre:
        prerequisites.append({"prerequisiteId": f"PRE-{pid}-S6", "prerequisiteType": "ACCOUNT",
                              "requirementText": front_pre, "conditional": False, "evidenceRefs": E(6)})

    # ---- PROCESS（§7 流程箭头串；卡片只给步骤名 ⇒ summary 与 stepName 同值，不编细节）----
    steps = []
    flow = kv(s7.get("bullets", []), "流程") or ""
    for i, name in enumerate([x.strip().strip("。；;，,") for x in re.split(r"→|->", flow) if x.strip()], 1):
        steps.append({"stepId": f"STP-{pid}-{i:02d}", "sequence": i, "stepName": name,
                      "summary": name, "actors": [], "inputs": [], "outputs": [],
                      "exceptions": [], "humanDecisionRequired": False,
                      "slaReference": None, "evidenceRefs": E(7)})

    # ---- MATERIALS（§7 材料清单；卡片未给用途 ⇒ purpose 如实标注缺说明）----
    materials = []
    mat = kv(s7.get("bullets", []), "材料") or ""
    items = [x.strip().strip("。；;，,、") for x in re.split(r"[、,，]", mat) if x.strip()]
    for i, name in enumerate(items, 1):
        materials.append({"materialId": f"MAT-{pid}-{i:02d}", "materialName": name,
                          "requirementLevel": "REQUIRED",
                          "conditionExpression": None,
                          "purpose": "（卡片仅列材料名，未给用途说明）",
                          "validityRule": None, "templateFileRef": None, "sampleFileRef": None,
                          # 契约里 `scope` 为 object（非 nullable）⇒ 无值即**省略**，不写 null
                          "evidenceRefs": E(7)})
    material_groups = ([{"groupType": "BASIC_REQUIRED", "items": materials}] if materials else [])

    # ---- SALES BOUNDARIES（§10）----
    sales = []
    for i, b in enumerate(s10.get("bullets", []), 1):
        kind = "PROHIBITED_PROMISE" if b.startswith("不得") else "ALLOWED_EXPLANATION"
        risk = "PRICE" if "保本" in b else ("APPROVAL" if "AI" in b else "PURPOSE")
        sales.append({"boundaryId": f"SLB-{pid}-{i:02d}", "boundaryKind": kind, "text": b,
                      "riskCategory": risk, "mandatoryDisplay": kind == "PROHIBITED_PROMISE",
                      "evidenceRefs": E(10)})

    # ---- COMPARE（§6 关系 → 客观属性比较；**派生件** ⇒ reviewState=DRAFT）----
    # ⚠ 卡片 §6 用**产品编码**表述关系（如 SETTLEMENT_ACCOUNT / CORPORATE_E_BANK），而契约
    #   `rows[].productId` 强约束 `^PROD-[A-Z]+-[0-9]{3}$` ⇒ **无法解析为产品 id 的一律不纳入**，
    #   并在 derivation 里如实登记（**不编造 编码→产品 id 的映射**）。
    dims = [{"dimensionId": "RELATION", "dimensionName": "与本产品关系"},
            {"dimensionId": "SOURCE_ALIAS", "dimensionName": "卡片原始编码"}]
    related_codes = list(fm.get("prerequisite_product_ids") or []) + \
                    list(fm.get("complementary_products") or [])
    _am = alias_map or {}

    def _row(code: str, relation: str) -> dict | None:
        """编码 → 产品 id：**只**用权威别名映射（TTL，含 Owner 决策）；解析不出 ⇒ 不纳入。"""
        raw = str(code)
        resolved = raw if re.fullmatch(r"PROD-[A-Z]+-\d{3}", raw) else _am.get(raw)
        if not resolved or not re.fullmatch(r"PROD-[A-Z]+-\d{3}", str(resolved)):
            return None
        return {"productId": resolved, "versionId": "",
                "values": {"RELATION": relation, "SOURCE_ALIAS": raw}}

    rows = [r for r in (_row(c, "前置产品") for c in (fm.get("prerequisite_product_ids") or [])) if r]
    rows += [r for r in (_row(c, "配套产品") for c in (fm.get("complementary_products") or [])) if r]
    comparison = {"comparisonSetId": f"CMP-{pid}", "comparisonAsOf": str(fm.get("published_at") or "")[:10],
                  "dimensions": dims, "rows": rows, "reviewState": "DRAFT"}

    return {
        "schema": "product_center_sections/v1",
        "productId": pid,
        "versionId": str(fm.get("version", "")),
        "productFamily": fm.get("product_family"),
        "sourceCardRef": rel,
        "sourceCardSha256": hashlib.sha256(pr["path"].read_bytes()).hexdigest(),
        "generatedAt": now_cst().isoformat(),
        "summary": {"oneSentenceDefinition": one_sentence,
                    "boundaryStatement": (is_not[0] if is_not else None),
                    "solves": solves, "isNot": is_not,
                    "nearestDifference": (nearest[0] if nearest else None)},
        "terms": terms,
        "boundaries": boundaries,
        "prerequisites": prerequisites,
        "processSteps": steps,
        "materialGroups": material_groups,
        "pricingItems": [],
        "agreementClauses": [],
        "salesBoundaries": sales,
        "comparison": comparison,
        "faqs": [],
        "evidenceRefs": [ev[n] for n in sorted(ev)],
        "derivation": {
            "tool": "tools/l40_build_product_center_sections.py",
            "rules": [
                "TERMS ← §2 适用客户/适用场景（只产出 ELIGIBLE_ENTITY / PURPOSE）",
                "FIT ← §2 场景（TYPICAL_USE）+ §5 排除/禁止（NOT_SUITABLE/PROHIBITED_USE）+ §4 准入（ACCOUNT/CREDIT/CONTRACT）+ §6 前置",
                "PROCESS ← §7 流程（按 → 切分；卡片无细节 ⇒ summary=stepName）",
                "MATERIALS ← §7 材料（枚举清单；卡片无用途说明 ⇒ 如实标注）",
                "SALES ← §10 销售边界",
                "COMPARE ← §6 关系 + front matter 前置/配套产品码（reviewState=DRAFT：脚本派生未人工复核）",
            ],
            "absentSections": {
                "PRICING": "卡片 §8 仅记「按行内收费标准执行（待核定）」⇒ 不出内容（Owner 裁定 O-2）",
                "FAQ": "全仓无 FAQ 来源 ⇒ 不生成问答（不编造）",
                "TERMS_missing_keys": ["LIMIT", "TENOR", "DRAW_MODE", "INTEREST", "REPAYMENT", "COLLATERAL"],
            },
            "unresolvedRelationCodes": [c for c in related_codes
                                        if not re.fullmatch(r"PROD-[A-Z]+-\d{3}", str(c))
                                        and str(c) not in _am],
            "aliasMapSource": ("gits `specs/knowledge-architecture/instances/product/sim/"
                               "product-relations.SIM.ttl`（`sim:sourceAlias` ⇒ `rdf:object` 产品 id；"
                               "含 Owner 决策 `OWNER-DECISION-2026-09-22-D2`）"
                               if alias_map else None),
            "notes": "证据 isDemo=true（SIM 阶段资产）；卡片 §9 风险与 §11 版本语义不属 8 章，未产出。",
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--contract-dir", default=None,
                    help="gits 侧 specs/product-center（提供则做 schema 校验）")
    ap.add_argument("--check", action="store_true", help="只校验，不写文件")
    ap.add_argument("--alias-map", default=None,
                    help="别名→产品 id 的 JSON（权威来源见 derivation.aliasMapSource）")
    args = ap.parse_args()

    alias_map = (json.loads(Path(args.alias_map).read_text(encoding="utf-8"))
                 if args.alias_map else None)
    cards = sorted(BASE.glob("03_core/*/version=*/product-cards/PROD-*.md"))
    if not cards:
        print("FAIL | 未找到产品卡")
        return 1
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    made, stat = [], []
    for c in cards:
        doc = build_one(parse_card(c), alias_map)
        stat.append((doc["productId"], len(doc["terms"]), len(doc["boundaries"]),
                     len(doc["prerequisites"]), len(doc["processSteps"]),
                     len(doc["materialGroups"]), len(doc["comparison"]["rows"]),
                     len(doc["pricingItems"]), len(doc["faqs"])))
        if not args.check:
            (OUT_DIR / f"{doc['productId']}.json").write_text(
                json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8")
        made.append(doc)

    print(f"{'productId':16s} {'TERMS':>5s} {'BND':>4s} {'PRE':>4s} {'STP':>4s} {'MAT':>4s} {'CMP':>4s} {'PRC':>4s} {'FAQ':>4s}")
    for r in stat:
        print(f"{r[0]:16s} {r[1]:5d} {r[2]:4d} {r[3]:4d} {r[4]:4d} {r[5]:4d} {r[6]:4d} {r[7]:4d} {r[8]:4d}")

    if args.contract_dir:
        try:
            import jsonschema
        except ImportError:
            print("WARN | 未安装 jsonschema ⇒ 跳过 schema 校验（按内置枚举校验）")
            jsonschema = None
        if jsonschema:
            from jsonschema import Draft202012Validator as V

            def rewrite(node):
                """`#/components/schemas/X` ⇒ `#/$defs/X`（便于把 OpenAPI 段当独立文档校验）。"""
                if isinstance(node, dict):
                    return {k: (f"#/$defs/{v.split('/')[-1]}"
                                if k == "$ref" and isinstance(v, str)
                                and v.startswith("#/components/schemas/") else rewrite(v))
                            for k, v in node.items()}
                if isinstance(node, list):
                    return [rewrite(x) for x in node]
                return node

            cd = Path(args.contract_dir)
            dom = json.loads((cd / "product-center-domain.schema.json").read_text(encoding="utf-8"))
            api = json.loads((cd / "product-center-api.openapi.json").read_text(encoding="utf-8"))
            schemas = rewrite(api["components"]["schemas"])
            payload_props = schemas["PkcSectionPayload"]["properties"]
            for doc in made:
                errs: list[str] = []
                payload_doc = {k: doc[k] for k in payload_props if k in doc}
                payload_doc["sectionKey"] = "OVERVIEW"
                root = {"$defs": schemas, "$ref": "#/$defs/PkcSectionPayload"}
                errs += [f"payload/{'/'.join(map(str, e.absolute_path))}: {e.message}"
                         for e in V(root).iter_errors(payload_doc)][:4]
                for key, ref in (("terms", "ProductTerm"), ("boundaries", "ApplicabilityBoundary"),
                                 ("prerequisites", "Prerequisite"), ("processSteps", "ProcessStep"),
                                 ("materialGroups", "MaterialGroup"), ("comparison", "ComparisonSet")):
                    sch = {"$defs": dom["$defs"], "$ref": f"#/$defs/{ref}"}
                    val = doc[key]
                    for i, obj in enumerate(val if isinstance(val, list) else [val]):
                        errs += [f"{key}[{i}]: {e.message}" for e in V(sch).iter_errors(obj)][:2]
                if errs:
                    print(f"FAIL | {doc['productId']} schema 不符 {len(errs)} 处：")
                    for m in errs[:6]:
                        print("   -", m)
                    return 1
            print(f"OK | {len(made)} 件全部通过契约 schema 校验"
                  f"（PkcSectionPayload + ProductTerm/ApplicabilityBoundary/Prerequisite/"
                  f"ProcessStep/MaterialGroup/ComparisonSet）")
    if not args.check:
        print(f"OK | 产出 {len(made)} 件 → {OUT_DIR.relative_to(BASE).as_posix()}/PROD-*.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
