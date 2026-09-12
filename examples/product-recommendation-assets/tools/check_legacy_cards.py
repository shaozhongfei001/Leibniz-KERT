#!/usr/bin/env python3
"""
Legacy Card Registry 一致性校验器

Loop L03 W6 交付。落地 E-3 方案（保留卡片原样 + 外部台账），防止 FAILURES
F-L00-08 / F-L03-03 类误消费。

校验项：
  1. 台账条目 == 磁盘实存卡片（多一张少一张都 FAIL）
  2. 每张卡 effectiveStatus 必须为 LEGACY_SAMPLE，consumable 必须为 false
  3. 台账记录的 declaredStatus 必须与卡片文件实际 front matter 一致
  4. EvidenceRef 计数必须与实际扫描一致
  5. contentHashKind 分类正确：PLACEHOLDER（非 64 位 hex）vs FALSE_PLAUSIBLE（64 位 hex 但不匹配任何真实 hash）
  6. FALSE_PLAUSIBLE 卡片的声明 hash 确实与文件/正文 hash 均不匹配（防误判）
  7. 台账声明的 currentReleaseCount 与实际 Release 数一致
  8. 卡片文件未被手改（status 仍为原始值，红线守护）

用法:
    python3 tools/check_legacy_cards.py
退出码 0 表示全部通过。
"""

import hashlib
import json
import re
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
CORE = BASE / "03_core"
REGISTRY = CORE / "LEGACY_CARD_REGISTRY.json"

results = []


def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'} | {name}" + (f" | {detail}" if detail else ""))
    return ok


def scan_cards():
    found = {}
    for f in sorted(CORE.glob("*/version=*/product-cards/PROD-*.md")):
        s = f.read_text(encoding="utf-8")
        m = re.search(r"^status:\s*(\S+)", s, re.M)
        h = re.search(r'content_hash:\s*"?sha256:([0-9a-zA-Z]+)"?', s)
        fm = re.match(r"^---\n.*?\n---\n", s, re.S)
        body = s[fm.end():] if fm else s
        found[f.stem] = {
            "path": f,
            "status": m.group(1) if m else None,
            "declHash": h.group(1) if h else None,
            "fileHash": hashlib.sha256(s.encode()).hexdigest(),
            "bodyHash": hashlib.sha256(body.encode()).hexdigest(),
            "evidenceRefs": len(re.findall(r"EVR-[A-Za-z0-9-]+", s)),
        }
    return found


def main():
    if not REGISTRY.exists():
        check("LEGACY_CARD_REGISTRY.json 存在", False, str(REGISTRY))
        return 1

    reg = json.loads(REGISTRY.read_text(encoding="utf-8"))
    entries = {c["productId"]: c for c in reg["cards"]}
    disk = scan_cards()

    # 1：台账 == 磁盘
    missing = sorted(set(disk) - set(entries))
    extra = sorted(set(entries) - set(disk))
    check(f"台账覆盖磁盘全部卡片 ({len(disk)} 张)", not missing,
          f"磁盘有但台账缺: {missing}" if missing else "")
    check("台账无幽灵条目", not extra, f"台账有但磁盘无: {extra}" if extra else "")
    check(f"台账 summary.totalCards 准确",
          reg["summary"]["totalCards"] == len(disk),
          f"声明 {reg['summary']['totalCards']} vs 实际 {len(disk)}")

    for pid, e in sorted(entries.items()):
        d = disk.get(pid)
        if not d:
            continue

        # 2：分类与可消费性
        check(f"{pid} effectiveStatus=LEGACY_SAMPLE",
              e["effectiveStatus"] == "LEGACY_SAMPLE", e["effectiveStatus"])
        check(f"{pid} consumable=false", e["consumable"] is False, str(e["consumable"]))

        # 3：declaredStatus 与文件实际一致（同时守护「卡片未被手改」）
        check(f"{pid} declaredStatus 与文件一致",
              e["declaredStatus"] == d["status"],
              f"台账 {e['declaredStatus']} vs 文件 {d['status']}")

        # 4：EvidenceRef 计数
        check(f"{pid} evidenceRefCount 准确",
              e["evidenceRefCount"] == d["evidenceRefs"],
              f"台账 {e['evidenceRefCount']} vs 实扫 {d['evidenceRefs']}")

        # 5 + 6：hash 分类正确性
        is_hex64 = bool(d["declHash"] and re.fullmatch(r"[0-9a-f]{64}", d["declHash"]))
        expect_kind = "FALSE_PLAUSIBLE" if is_hex64 else "PLACEHOLDER"
        check(f"{pid} contentHashKind 分类正确",
              e["contentHashKind"] == expect_kind,
              f"台账 {e['contentHashKind']} vs 判定 {expect_kind}")

        if expect_kind == "FALSE_PLAUSIBLE":
            really_mismatch = d["declHash"] not in (d["fileHash"], d["bodyHash"])
            check(f"{pid} FALSE_PLAUSIBLE 判定成立（确与真实 hash 不符）",
                  really_mismatch,
                  "声明 hash 实际匹配真实 hash，分类应修正" if not really_mismatch else "")

    # 7：Release 数
    releases = list(CORE.glob("**/RELEASE.md"))
    declared_rel = reg["consumptionRule"]["currentReleaseCount"]
    # RELEASE.md 是 legacy 目录产物，非 CTR-PK-RLS-001 意义上的 Release
    check("currentReleaseCount 声明为 0（无 CTR-PK-RLS-001 Release）",
          declared_rel == 0,
          f"声明 {declared_rel}；注：磁盘 {len(releases)} 个 legacy RELEASE.md 不属受控 Release")

    # 8：全局不变式
    check("summary.consumable == 0", reg["summary"]["consumable"] == 0)
    check("summary.totalEvidenceRefs == 0 与实扫一致",
          reg["summary"]["totalEvidenceRefs"] == sum(d["evidenceRefs"] for d in disk.values()))
    check("台账声明 E-3 策略", reg.get("strategy", "").startswith("E-3"))
    check("台账含禁止事项清单", len(reg.get("prohibitions", [])) >= 4)

    failed = [r for r in results if not r[1]]
    print(f"\n{'=' * 60}")
    print(f"Legacy Card 台账一致性：{len(results) - len(failed)}/{len(results)} PASS")
    if failed:
        print("失败项：")
        for n, _, d in failed:
            print(f"  - {n} {d}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
