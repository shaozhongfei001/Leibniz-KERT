#!/usr/bin/env python3
"""bank-front 报告组装链 SKILL 验证（用已加载的 assemblyMaterials 参考数据）。

验证方式：
- 参考基准：04_serve/bank_front_data/version=*/datasets/assembly_materials.parquet
  （袁阳 assemblyMaterials.zip 的 7 个 TASK-FRONT 输出，即各 SKILL 的预期产物）
- 对每个 bank-front SKILL：POST /api/skill/execute（输入取自 01_raw 对应批次 mock 数据），
  断言 status=ok + 输出结构与参考基准对齐（skillId / 关键字段 / 关键内容）；
- 最后以 7 个参考任务输出为输入执行 bank-front-report-assembler，断言 battleOrder 产出。

用法：python validate_bank_front_skills.py --base http://127.0.0.1:8111 [--workspace ../demo_workspace]
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.request
from pathlib import Path

import pyarrow.parquet as pq

# skillId → (预期 SK-FRONT id, 对应批次 mock 文件所在 batch, 参考 payload taskId)
SKILLS = [
    ("bank-front-supply-chain-graph",  "SK-FRONT-002", "BATCH-20260821-007", "TASK-FRONT-002"),
    ("bank-front-eight-dimension",     "SK-FRONT-003", "BATCH-20260821-002", "TASK-FRONT-003"),
    ("bank-front-fact-reconciliation", "SK-FRONT-004", "BATCH-20260821-003", "TASK-FRONT-004"),
    ("bank-front-commitment-script",   "SK-FRONT-005", "BATCH-20260821-001", "TASK-FRONT-005"),
    ("bank-front-kyc-gap-check",       "SK-FRONT-006", "BATCH-20260821-004", "TASK-FRONT-006"),
    ("bank-front-product-recommendation", "SK-FRONT-007", "BATCH-20260821-005", "TASK-FRONT-007"),
]

PASS: list[bool] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    PASS.append(cond)
    print(f"  [{'PASS' if cond else 'FAIL'}] {label}" + (f"  {detail}" if detail and not cond else ""))


def post(base: str, skill_id: str, payload: dict):
    # 唯一 requestId：避免命中服务端幂等缓存（幂等 TTL 600s）
    rid = f"val-{skill_id}-{int(time.time() * 1000)}"
    body = json.dumps({"skillId": skill_id, "requestId": rid,
                       "request": {"input": payload}}, ensure_ascii=False).encode()
    req = urllib.request.Request(base + "/api/skill/execute", data=body, method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode())
        except Exception:
            return e.code, {"status": "skill_error"}


def load_reference(ws: Path) -> dict[str, dict]:
    """assembly_materials 投影 → {taskId: payload}。"""
    cur = ws / "04_serve/bank_front_data/CURRENT.md"
    target = next(ws.glob("04_serve/bank_front_data/version=*/datasets/assembly_materials.parquet"))
    out: dict[str, dict] = {}
    for row in pq.read_table(target).to_pylist():
        out[row["taskId"]] = row["payload"]
    return out


def mock_input(ws: Path, batch_id: str, skill_id: str = "") -> dict:
    """工作区批次 mock 数据：顶层键即数据源（T-CRM-001/T-CORE-001/...），
    无 input/mockSourceData 包装（与 skill 包参考文件结构不同）。"""
    f = ws / f"01_raw/bank_front/batch={batch_id}/mock-input-data.json"
    d = json.loads(f.read_text(encoding="utf-8"))
    inp: dict = {"customerId": "HZB0000001234", "userId": "cm_zhangwei",
                 "goal": "授信营销-流动资金贷款渗透"}
    if skill_id == "bank-front-eight-dimension":
        inp.update({"customerName": "杭州智造精密齿轮有限公司",
                    "industryCode": "C34", "industry": "C34",
                    "registeredAddress": "杭州市钱塘区XX路XX号",
                    "mainProducts": "精密齿轮制造（新能源汽车变速箱）"})
    for k, v in d.items():
        if k != "_meta":
            inp[k] = v
    return inp


def validate_skill(base: str, ws: Path, skill_id: str, sk_id: str,
                   batch_id: str, ref: dict) -> None:
    print(f"== {skill_id}（预期 {sk_id}）==")
    inp = mock_input(ws, batch_id, skill_id)
    code, body = post(base, skill_id, inp)
    ok = body.get("status") == "ok" and isinstance(body.get("data"), dict)
    check("执行 ok", ok, f"status={body.get('status')} code={code}")
    if not ok:
        return
    result = body["data"].get("result") or {}
    check("skillId 对齐", result.get("skillId") == sk_id, f"got={result.get('skillId')}")
    ref_payload = ref.get("TASK-FRONT-" + sk_id.split("-")[-1], {})
    # 各 SKILL 关键字段断言
    if sk_id == "SK-FRONT-002":  # 供应链图谱
        check("buildStatus", result.get("buildStatus") in ("complete", "partial"), str(result.get("buildStatus"))[:40])
        nodes = [n.get("name") for n in (result.get("nodes") or [])]
        for want in ("浙江轴承集团", "宁波特种钢公司", "新能源汽车主机厂A"):
            check(f"节点含 {want}", want in nodes)
    elif sk_id == "SK-FRONT-003":  # 八维研判
        dims = result.get("dimensions") or {}
        ref_dims = (ref_payload.get("dimensions") or {})
        check("八维齐全", len(dims) >= 8, str(list(dims.keys())))
        scores = [(v or {}).get("score") for v in dims.values()]
        check("评分均为 1-5 整数", all(isinstance(s, int) and 1 <= s <= 5 for s in scores),
              str(scores))
        if dims and ref_dims:
            # 参考快照键为 tech，schema 键为 technology（归一化后对比）
            norm = {("technology" if k == "tech" else k): (v or {}).get("score")
                    for k, v in dims.items()}
            ref_norm = {k: (v or {}).get("score") for k, v in ref_dims.items()}
            dev = {k: (norm.get(k), ref_norm.get(k)) for k in ref_norm
                   if k in norm and norm[k] != ref_norm[k]}
            check("评分与参考偏差 ≤1", all(abs(a - b) <= 1 for a, b in dev.values()),
                  f"dev={dev}")
        check("结论非空", bool(result.get("conclusion") or result.get("overallConclusion")))
    elif sk_id == "SK-FRONT-004":  # 事实对账
        check("indicators 非空", bool(result.get("indicators")))
        check("conflicts 为列表", isinstance(result.get("conflicts"), list))
    elif sk_id == "SK-FRONT-005":  # 承诺话术
        coms = result.get("commitments") or []
        check("commitments 非空", bool(coms))
        joined = json.dumps(coms, ensure_ascii=False)
        check("含代发薪承诺", "代发" in joined)
    elif sk_id == "SK-FRONT-006":  # KYC 缺口
        gaps = result.get("kycGaps") or []
        check("kycGaps 非空", bool(gaps))
    elif sk_id == "SK-FRONT-007":  # 产品组合
        cands = result.get("candidates") or []
        check("candidates 非空", bool(cands))
        rec = result.get("recommendations") or {}
        joined = json.dumps(rec, ensure_ascii=False)
        check("主推含流贷 P-LOAN-001", "P-LOAN-001" in joined, str(rec)[:80])


def validate_assembler(base: str, ws: Path, ref: dict) -> None:
    print("== bank-front-report-assembler（SK-FRONT-001 访前报告组装）==")
    # 以 7 个参考任务输出为素材输入（模拟上游七模块产出已就绪）
    materials = {}
    for row in pq.read_table(next(ws.glob(
            "04_serve/bank_front_data/version=*/datasets/assembly_materials.parquet"))).to_pylist():
        materials[row["taskId"]] = row["payload"]
    inp = {
        "customerId": "HZB0000001234",
        "userId": "cm_zhangwei",
        "goal": "授信营销-流动资金贷款渗透",
        "optional": {"customerName": "杭州智造精密齿轮有限公司",
                     "industryCode": "C34",
                     "creditCode": "91330100MA27XXXXXX"},
        "materials": materials,
    }
    code, body = post(base, "bank-front-report-assembler", inp)
    ok = body.get("status") == "ok" and isinstance(body.get("data"), dict)
    check("全量素材执行 ok", ok, f"status={body.get('status')} code={code}")
    if not ok:
        check("fail-closed 无残缺产物", not (body.get("data") or {}).get("result"),
              str(body.get("errors"))[:100])
        return
    result = body["data"].get("result") or {}
    check("skillId 对齐", result.get("skillId") == "SK-FRONT-001", str(result.get("skillId")))
    bo = result.get("battleOrder") or {}
    check("battleOrder 产出", bool(bo))
    if bo:
        for sec in ("meta", "summary", "sections", "riskAndAction", "disclaimer"):
            check(f"battleOrder 含 {sec}", sec in bo, str(list(bo.keys())))
        secs = bo.get("sections") or []
        check("sections 非空（七模块素材已组装）", bool(secs), f"n={len(secs)}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8111")
    ap.add_argument("--workspace", "-w", default="demo_workspace")
    args = ap.parse_args()
    base = args.base.rstrip("/")
    ws = Path(args.workspace).resolve()

    ref = load_reference(ws)
    print(f"参考基准：assembly_materials 投影（{len(ref)} 个任务）\n")

    for skill_id, sk_id, batch_id, task_id in SKILLS:
        validate_skill(base, ws, skill_id, sk_id, batch_id, ref)
        print()
    validate_assembler(base, ws, ref)
    print()
    total, good = len(PASS), sum(PASS)
    print(f"结果: {good}/{total} PASS")
    raise SystemExit(0 if good == total else 1)


if __name__ == "__main__":
    main()
