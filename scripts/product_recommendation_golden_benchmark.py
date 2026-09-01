#!/usr/bin/env python3
"""WP6 黄金样本机器基准：把 golden-cases.json 的 8 例经字段映射后跑真实 SP-15 服务(8107)。"""
import json, sys, time, urllib.request

BASE = "http://127.0.0.1:8107/api/skill/execute"

def map_facts(customer: dict, products: list) -> dict:
    rel = ["SETTLEMENT_ACCOUNT"] if customer.get("hasAccount") else []
    # 产品限定机构（applicableInstitutions）作为客户机构上下文；样例未显式给出 institution 时取首个限定机构
    inst = customer.get("institution")
    if not inst:
        for p in products:
            insts = p.get("applicableInstitutions") or []
            if insts:
                inst = insts[0]
                break
    # 材料：样例未显式给材料时，按"产品要求材料默认满足"（样例未测材料场景即隐式满足）
    materials = customer.get("materials")
    if not materials:
        req = set()
        for p in products:
            req.update(p.get("requiredMaterials") or [])
        materials = list(req)
    return {
        "customerId": customer.get("customerId"),
        "institution": inst,
        "customerType": customer.get("enterpriseType"),   # 保留缺失语义（缺失→UNKNOWN）
        "industry": customer.get("industry"),
        "region": customer.get("region"),
        "scale": customer.get("scale"),
        "rating": customer.get("rating"),
        "accountRelationships": rel,
        "heldProducts": customer.get("holdings") or [],
        "materials": materials,
        "asOf": None,
    }

def map_product(p: dict) -> dict:
    return {
        "productId": p.get("productId"),
        "productVersion": p.get("productVersion"),
        "status": p.get("productStatus"),
        "effectiveFrom": p.get("effectiveFrom"),
        "effectiveTo": p.get("effectiveTo"),
        "institutions": p.get("applicableInstitutions"),
        "prohibitedIndustries": p.get("prohibitedIndustries", []),
        "prohibitedRegions": p.get("prohibitedRegions", []),
        "prohibitedUses": p.get("prohibitedUses", []),
        "prerequisites": p.get("prerequisiteProductIds", []),
        "mutualExclusions": p.get("mutexProductIds", []),
        "requiredMaterials": p.get("requiredMaterials", []),
        "owner": "公司金融产品管理部",
        "source": "golden-case",
        "evidenceRefs": ["EV-PROD-CARD"],
    }

def execute(case: dict) -> dict:
    inp = case["input"]
    products = [map_product(p) for p in inp["products"]]
    facts = map_facts(inp["customer"], inp["products"])
    ctx = {
        "schemaVersion": "1.0.0",
        "customerId": inp["customer"].get("customerId"),
        "needVersionIds": ["NEED-GOLDEN"],
        "recommendationObjective": "黄金样本机器基准",
        "requestedProductDomains": ["FINANCING"],
        "asOf": inp.get("asOf", "2026-08-31T09:00:00+08:00"),
        "customerFactSnapshotId": inp.get("customerFactSnapshotId"),
        "productKnowledgeSnapshotRef": "PKS-GOLDEN",
        "ruleBundleRef": "RB-GOLDEN",
        "permissionDecisionId": "PERM-GOLDEN",
        "activationContract": "AC-PRODUCT-RECOMMEND-001",
        "customerFactSnapshot": facts,
        "productKnowledgeSnapshot": {"products": products},
    }
    req = {"skillId": "SP-15", "requestId": "GOLDEN-" + case["caseId"] + "-" + str(int(time.time())),
           "request": {"context": ctx}}
    data = json.dumps(req, ensure_ascii=False).encode("utf-8")
    r = urllib.request.Request(BASE, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(r, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))

def main():
    cases = json.load(open("skills/product-recommendation/rules/golden-cases.json"))["cases"]
    results = []
    passed = 0
    for c in cases:
        exp = c["expected"] or c.get("expectedResult", {})
        expected_status = exp.get("eligibility")
        row = {"caseId": c["caseId"], "tcPrId": c["tcPrId"], "polarity": c["polarity"],
               "name": c["name"], "expected": expected_status}
        try:
            resp = execute(c)
            if resp.get("status") != "ok":
                row["actual"] = "SKILL_ERROR"; row["pass"] = False
                row["detail"] = json.dumps(resp.get("errors"), ensure_ascii=False)[:200]
                results.append(row); continue
            result = (resp.get("data") or {}).get("result") or {}
            elig = result.get("eligibilityResults") or []
            # 目标产品 = 第一个产品
            target = c["input"]["products"][0]["productId"]
            hit = next((e for e in elig if e.get("productId") == target), None)
            actual = hit.get("eligibility") if hit else "NO_PRODUCT"
            row["actual"] = actual
            row["pass"] = (actual == expected_status)
            row["detail"] = f"ruleHits={len(hit.get('ruleResults', [])) if hit else 0} reasonCodes={[r.get('reasonCode') for r in (hit.get('ruleResults') or [])][:3] if hit else []}"
        except Exception as ex:
            row["actual"] = "ERROR"; row["pass"] = False; row["detail"] = str(ex)[:200]
        if row["pass"]:
            passed += 1
        results.append(row)
    total = len(results)
    print(f"黄金样本机器基准：{passed}/{total} PASS（SP-15 :8107 真实执行）")
    for r in results:
        mark = "PASS" if r["pass"] else "FAIL"
        print(f"  [{mark}] {r['caseId']} {r['tcPrId']} {r['polarity']:<8} 期望={r['expected']} 实际={r['actual']} | {r.get('detail','')}")
    return results

if __name__ == "__main__":
    main()
