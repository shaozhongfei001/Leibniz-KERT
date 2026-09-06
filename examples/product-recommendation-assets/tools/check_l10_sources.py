#!/usr/bin/env python3
"""SourceVersion / Fragment 门禁（Loop L10）

校验 02_work/ 下由 l10_build_source_versions.py 产出的 SourceVersion 与
Fragment 是否满足不可变性、确定性与 DEMO 红线。

校验项：
  1. manifest.extractionRunId 格式（RUN-YYYYMMDD-hash8）
  2. SourceVersion: ID 格式、hash/字节数与磁盘真值一致、provenanceState 合法
  3. Fragment: ID 格式、seqNo 连续、contentSha256 = SHA-256(contentText)
  4. Fragment 可定位：contentText 必须能在源文件中原样找到（INV-EVS-02 前置）
  5. 覆盖完整性：fragment 数 == 源登记表 §5.8 声明的条款数
  6. DEMO 红线：.DEMO.md 产出的 SourceVersion 必须 provenanceState=DEMO

用法:
    python3 tools/check_l10_sources.py
退出码 0 表示全部通过。
"""

import hashlib
import json
import re
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
SV_DIR = BASE / "02_work" / "source-versions"
FRG_DIR = BASE / "02_work" / "fragments"
REGISTRY = BASE / "01_raw" / "source-registry.md"

VALID_PROV = {"VERIFIED", "UNVERIFIED", "CONFLICTING_EVIDENCE", "DEMO"}
SV_RE = re.compile(r"^SV-[A-Z0-9-]+-\d{8}-[0-9a-f]{8}$")
FRG_RE = re.compile(r"^FRG-[A-Z0-9-]+-\d{4}$")
RUN_RE = re.compile(r"^RUN-\d{8}-[0-9a-f]{8}$")

results = []


def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'} | {name}" + (f" | {detail}" if detail else ""))
    return ok


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def declared_clause_counts():
    """从源登记表 §5.8 入库记录表解析声明的条款数。"""
    if not REGISTRY.exists():
        return {}
    text = REGISTRY.read_text(encoding="utf-8")
    out = {}
    for m in re.finditer(r"\|\s*((?:SRC|REG|PUB)-[A-Z0-9-]+)\s*\|\s*\d+\s*\|\s*`?[0-9a-f]{64}`?\s*\|\s*(\d+)\s*\|", text):
        out.setdefault(m.group(1), int(m.group(2)))
    return out


def main():
    if not SV_DIR.exists() or not FRG_DIR.exists():
        check("02_work 产物目录存在", False, "请先运行 l10_build_source_versions.py")
        return 1

    manifest = SV_DIR / "manifest.json"
    if not manifest.exists():
        check("manifest.json 存在", False)
        return 1
    man = json.loads(manifest.read_text(encoding="utf-8"))
    check("extractionRunId 格式", bool(RUN_RE.match(man.get("extractionRunId", ""))),
          man.get("extractionRunId", ""))

    declared = declared_clause_counts()
    sv_files = sorted(p for p in SV_DIR.glob("SV-*.json"))
    check("SourceVersion 文件数 == manifest 声明",
          len(sv_files) == len(man.get("sourceVersions", [])),
          f"磁盘 {len(sv_files)} vs manifest {len(man.get('sourceVersions', []))}")

    demo_count = 0
    for p in sv_files:
        sv = json.loads(p.read_text(encoding="utf-8"))
        sid = sv["sourceVersionId"]
        check(f"{sid} 文件名与 ID 一致", p.stem == sid, p.name)
        check(f"{sid} ID 格式", bool(SV_RE.match(sid)), sid)
        check(f"{sid} ingestedAt 日期 == ID 日期段",
              sv["ingestedAt"][:10].replace("-", "") == sid.split("-")[-2],
              f"{sv['ingestedAt'][:10]} vs {sid.split('-')[-2]}")
        check(f"{sid} provenanceState 合法", sv.get("provenanceState") in VALID_PROV,
              str(sv.get("provenanceState")))

        src = BASE / sv["sourcePath"]
        if not src.exists():
            check(f"{sid} 源文件存在", False, sv["sourcePath"])
            continue
        raw = src.read_bytes()
        check(f"{sid} bytesSha256 == 实测",
              sv["bytesSha256"] == hashlib.sha256(raw).hexdigest())
        check(f"{sid} byteSize == 实测", sv["byteSize"] == len(raw),
              f"登记 {sv['byteSize']} vs 实测 {len(raw)}")
        check(f"{sid} ID hash 段 == bytesSha256 前 8 位",
              sid.split("-")[-1] == sv["bytesSha256"][:8])

        if src.name.endswith(".DEMO.md"):
            demo_count += 1
            check(f"{sid} DEMO 源必须 provenanceState=DEMO",
                  sv.get("provenanceState") == "DEMO",
                  f"实为 {sv.get('provenanceState')}")

    # Fragment 校验
    body_cache = {}
    for fp in sorted(FRG_DIR.glob("*.fragments.json")):
        d = json.loads(fp.read_text(encoding="utf-8"))
        sid = d["sourceId"]
        frgs = d["fragments"]
        check(f"{sid} fragmentCount == 条目数", d["fragmentCount"] == len(frgs),
              f"声明 {d['fragmentCount']} vs 实际 {len(frgs)}")
        check(f"{sid} 条款数 == 登记表声明",
              declared.get(sid) == len(frgs),
              f"登记表 {declared.get(sid)} vs 产出 {len(frgs)}")

        seqs = [f["seqNo"] for f in frgs]
        check(f"{sid} seqNo 从 1 连续", seqs == list(range(1, len(frgs) + 1)),
              f"{seqs[:3]}…{seqs[-1:]}")

        bad_id = [f["fragmentId"] for f in frgs if not FRG_RE.match(f["fragmentId"])]
        check(f"{sid} fragmentId 格式全部合法", not bad_id, str(bad_id[:3]))

        bad_hash = [f["fragmentId"] for f in frgs
                    if f["contentSha256"] != sha256_text(f["contentText"])]
        check(f"{sid} contentSha256 == SHA-256(contentText)", not bad_hash, str(bad_hash[:3]))

        bad_sv = [f["fragmentId"] for f in frgs if f["sourceVersionId"] != d["sourceVersionId"]]
        check(f"{sid} fragment 全部指向同一 sourceVersionId", not bad_sv, str(bad_sv[:3]))

        # 可定位性：contentText 必须能在源文件中原样找到
        src_path = None
        for p in sv_files:
            s = json.loads(p.read_text(encoding="utf-8"))
            if s["sourceId"] == sid:
                src_path = BASE / s["sourcePath"]
                break
        if src_path is None:
            check(f"{sid} 找到对应 SourceVersion", False)
            continue
        if sid not in body_cache:
            body_cache[sid] = src_path.read_text(encoding="utf-8")
        body = body_cache[sid]
        missing = [f["fragmentId"] for f in frgs if f["contentText"] not in body]
        check(f"{sid} 全部 fragment 可在源文件原样定位", not missing, str(missing[:3]))

    check("DEMO 源数量 == 3（DECISION-20260906-01 路径 C）", demo_count == 3,
          f"实际 {demo_count}")

    failed = [r for r in results if not r[1]]
    print(f"\n{'=' * 60}")
    print(f"L10 源版本/片段门禁：{len(results) - len(failed)}/{len(results)} PASS")
    if failed:
        print("失败项：")
        for n, _, d in failed:
            print(f"  - {n} {d}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
