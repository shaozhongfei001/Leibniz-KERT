#!/usr/bin/env python3
"""
源登记表一致性校验器

Loop L03 W3/W4 交付。修复并防止 FAILURES F-L00-03 / F-L00-04 复发：
  F-L00-03: 汇总段与明细行统计口径脱节（27 全 PENDING vs 明细 1 条 AVAILABLE）
  F-L00-04: 登记字节数与文件系统真值不符

校验项：
  1. 明细行状态分布 == 汇总段声明数字
  2. 每条 AVAILABLE 源必须在磁盘存在对应文件
  3. 登记的 bytes 必须等于 stat 实测
  4. 登记的 SHA-256 必须等于实测
  5. 双区路径与 usage 一致性（_public_reference => VERIFICATION_ONLY）
  6. 缺口数 == PENDING_SOURCE 计数
  7. provenance 缺失项必须显式标 UNVERIFIED（不得留空冒充已验证）

用法:
    python3 tools/check_registry_consistency.py
退出码 0 表示全部通过。
"""

import hashlib
import re
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
REGISTRY = BASE / "01_raw" / "source-registry.md"

results = []


def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'} | {name}" + (f" | {detail}" if detail else ""))
    return ok


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_detail_rows(text):
    """解析明细行：| SRC-XXX | ... | STATUS | ...

    返回 (真实源表, DEMO 演示轨表)。DEMO 由所在章节判定（§5.8 DEMO 演示轨）。

    同一 source_id 可同时存在于两张表：真实权威区记 `PENDING_SOURCE`（真实制度未上传），
    DEMO 轨记 `AVAILABLE`（演示文本已生成）。二者语义不同，不得互相抵扣。
    """
    rows = {}
    demo_rows = {}
    heading = ""
    for line in text.splitlines():
        if line.startswith("#"):
            heading = line
        m = re.match(r"^\|\s*`?((?:SRC|REG|PUB)-[A-Z0-9-]+)`?\s*\|(.*)$", line)
        if not m:
            continue
        sid, rest = m.group(1), m.group(2)
        if "别名" in rest or "复用" in rest:
            continue
        st = re.search(r"(PENDING_SOURCE|CLAUSE_VERIFIED|\*\*AVAILABLE\*\*|AVAILABLE)", rest)
        if not st:
            continue
        status = st.group(1).replace("**", "")
        target = demo_rows if "DEMO 演示轨" in heading else rows
        # 首次出现为准（缺口台账段会二次提及）
        target.setdefault(sid, status)
    return rows, demo_rows


def main():
    if not REGISTRY.exists():
        check("source-registry.md 存在", False, str(REGISTRY))
        return 1

    text = REGISTRY.read_text(encoding="utf-8")
    rows, demo = parse_detail_rows(text)

    # DEMO 演示轨单列：不计入真实权威区基数，不抵扣缺口
    auth = {k: v for k, v in rows.items() if not k.startswith("PUB")}
    pub = {k: v for k, v in rows.items() if k.startswith("PUB")}

    n_auth_pending = sum(1 for v in auth.values() if v == "PENDING_SOURCE")
    n_auth_avail = sum(1 for v in auth.values() if v in ("AVAILABLE", "CLAUSE_VERIFIED"))
    n_auth_clause = sum(1 for v in auth.values() if v == "CLAUSE_VERIFIED")

    # 期望基数按明细行真值。L03 核算确认权威区为 28 条（含 REG-CM-002，
    # 该条自 PI-0 起从未被计入汇总，见 FAILURES F-L03-02），非历史沿用的 27。
    EXPECTED_AUTH = 28
    EXPECTED_PUB = 2
    # L10：Owner 决议 DECISION-20260906-01 路径 C 生成的 3 份演示制度文本
    EXPECTED_DEMO = 3

    check(f"权威区明细行解析 {len(auth)} 条", len(auth) == EXPECTED_AUTH,
          f"实际 {len(auth)}，期望 {EXPECTED_AUTH}")
    check(f"公开区明细行解析 {len(pub)} 条", len(pub) == EXPECTED_PUB,
          f"实际 {len(pub)}，期望 {EXPECTED_PUB}")
    check(f"DEMO 演示轨解析 {len(demo)} 条", len(demo) == EXPECTED_DEMO,
          f"实际 {len(demo)}，期望 {EXPECTED_DEMO}")

    # DEMO 源不得混入真实权威区统计
    check("DEMO 源未污染真实权威区基数", len(auth) == EXPECTED_AUTH,
          f"权威区 {len(auth)} 条应排除全部 DEMO 行")

    m_demo = re.search(r"演示源 \*\*(\d+)\*\* 条", text)
    if m_demo:
        check("汇总段 DEMO 计数 == 明细 DEMO 计数", int(m_demo.group(1)) == len(demo),
              f"汇总 {m_demo.group(1)} vs 明细 {len(demo)}")
    else:
        check("汇总段 DEMO 声明可解析", False, "未匹配到 L10 新增的 DEMO 汇总句")

    # 1 + 6：汇总段数字必须与明细一致
    m = re.search(r"权威区登记源 \*\*(\d+)\*\* 条 = \*\*(\d+)\s*`PENDING_SOURCE`\s*\+\s*(\d+)\s*`AVAILABLE`\*\*", text)
    if m:
        tot, pend, avail = int(m.group(1)), int(m.group(2)), int(m.group(3))
        check("汇总总数 == 明细总数", tot == len(auth), f"汇总 {tot} vs 明细 {len(auth)}")
        check("汇总 PENDING == 明细 PENDING", pend == n_auth_pending, f"汇总 {pend} vs 明细 {n_auth_pending}")
        check("汇总 AVAILABLE == 明细 AVAILABLE", avail == n_auth_avail, f"汇总 {avail} vs 明细 {n_auth_avail}")
    else:
        check("汇总段格式可解析", False, "未匹配到 L03 订正后的汇总格式")

    mg = re.search(r"缺口 \*\*(\d+)/(\d+)\*\*", text)
    if mg:
        check("缺口数 == PENDING 计数",
              int(mg.group(1)) == n_auth_pending and int(mg.group(2)) == len(auth),
              f"声明 {mg.group(1)}/{mg.group(2)} vs 实际 {n_auth_pending}/{len(auth)}")
    else:
        check("缺口数可解析", False)

    mc = re.search(r"`CLAUSE_VERIFIED`\s*\*\*(\d+)\*\*\s*条", text)
    if mc:
        check("CLAUSE_VERIFIED 计数一致", int(mc.group(1)) == n_auth_clause,
              f"声明 {mc.group(1)} vs 实际 {n_auth_clause}")

    # 2 + 3 + 4：AVAILABLE 源必须落盘且元数据与真值一致
    zones = {
        "_authoritative": BASE / "01_raw" / "_authoritative",
        "_public_reference": BASE / "01_raw" / "_public_reference",
    }
    on_disk = {}
    demo_disk = {}
    for zone, d in zones.items():
        if d.exists():
            for f in d.iterdir():
                if f.suffix.lower() not in (".pdf", ".html", ".htm", ".md"):
                    continue
                # 目录说明文件与非法命名不作为源材料参与校验
                if f.name.lower().startswith("readme"):
                    continue
                if not re.match(r"^(SRC|REG|PUB)-", f.name):
                    continue
                # 演示文本固定 .DEMO.md 后缀，与真实制度物理隔离
                if f.name.endswith(".DEMO.md"):
                    demo_disk[f.name.split(".")[0]] = (zone, f)
                else:
                    on_disk[f.stem] = (zone, f)

    for sid, status in rows.items():
        if status in ("AVAILABLE", "CLAUSE_VERIFIED"):
            hit = on_disk.get(sid)
            check(f"{sid} AVAILABLE 且文件落盘", hit is not None,
                  "磁盘未找到" if hit is None else str(hit[1].name))
        elif status == "PENDING_SOURCE":
            check(f"{sid} PENDING 且文件确实不存在", sid not in on_disk,
                  "状态 PENDING 但磁盘有文件！" if sid in on_disk else "")

    # 登记元数据 vs 文件系统真值
    for sid, (zone, f) in sorted(on_disk.items()):
        real_bytes = f.stat().st_size
        real_hash = sha256_file(f)
        # 在文档中找该源的入库记录块
        blk = re.search(rf"{re.escape(sid)} 入库记录.*?(?=\n## |\Z)", text, re.S)
        scope = blk.group(0) if blk else text
        mb = re.search(r"文件字节数\s*\|\s*(\d+)", scope)
        if mb:
            check(f"{sid} 登记字节数 == 实测", int(mb.group(1)) == real_bytes,
                  f"登记 {mb.group(1)} vs 实测 {real_bytes}")
        if real_hash in text:
            check(f"{sid} 登记 SHA-256 == 实测", True, real_hash[:16] + "…")
        else:
            check(f"{sid} 登记 SHA-256 == 实测", False, f"实测 {real_hash[:16]}… 未在登记表出现")

        # 5：双区路径与 usage 一致
        if zone == "_public_reference":
            check(f"{sid} 公开区 => VERIFICATION_ONLY 语义", "VERIFICATION_ONLY" in text,
                  "登记表未声明公开轨限制")

    # 8：DEMO 演示轨一致性（L10 · DECISION-20260906-01 路径 C）
    for sid in sorted(demo):
        hit = demo_disk.get(sid)
        if hit is None:
            continue
        zone, f = hit
        check(f"{sid} DEMO 文件命名含 .DEMO.md", f.name.endswith(".DEMO.md"), f.name)
        # 只解析 YAML front matter，避免正文中的引用文本（如 `provenance_state: DEMO`）
        # 骗过检查 —— L10 红测曾暴露该假安全
        body = f.read_text(encoding="utf-8")
        fm = ""
        if body.startswith("---"):
            parts = body.split("\n---", 1)
            if len(parts) == 2:
                fm = parts[0]
        check(f"{sid} front matter 声明 provenance_state: DEMO",
              re.search(r"^provenance_state:\s*DEMO\s*$", fm, re.M) is not None,
              "front matter 未声明 provenance_state: DEMO，存在冒充真实制度风险")
        check(f"{sid} 正文含虚构演示声明", "演示" in body[:2000] and "DEMO" in body[:2000],
              "未声明为演示文本")

        real_bytes = f.stat().st_size
        real_hash = sha256_file(f)
        mrow = re.search(rf"\|\s*{re.escape(sid)}\s*\|\s*(\d+)\s*\|\s*`?([0-9a-f]{{64}})`?", text)
        if mrow:
            check(f"{sid} DEMO 登记字节数 == 实测", int(mrow.group(1)) == real_bytes,
                  f"登记 {mrow.group(1)} vs 实测 {real_bytes}")
            check(f"{sid} DEMO 登记 SHA-256 == 实测", mrow.group(2) == real_hash,
                  f"登记 {mrow.group(2)[:16]}… vs 实测 {real_hash[:16]}…")
        else:
            check(f"{sid} DEMO 入库记录可解析", False, "§5.8 入库记录表未找到该源行")

        check(f"{sid} 真实制度文件尚未上传（DEMO 不冒充真实）", sid not in on_disk,
              "真实制度与 DEMO 文本同名并存，存在冒充风险" if sid in on_disk else "")

    # 7：provenance 缺失必须显式 UNVERIFIED
    for sid in ("PUB-PRICE-001", "PUB-PRICE-002"):
        blk = re.search(rf"{re.escape(sid)} 入库记录.*?(?=\n\*\*|\n## |\Z)", text, re.S)
        if blk and "来源 URL" in blk.group(0):
            has_marker = "UNVERIFIED" in blk.group(0) or "http" in blk.group(0)
            check(f"{sid} provenance 显式标注", has_marker, "既无 URL 也无 UNVERIFIED 标记")

    failed = [r for r in results if not r[1]]
    print(f"\n{'=' * 60}")
    print(f"源登记表一致性：{len(results) - len(failed)}/{len(results)} PASS")
    if failed:
        print("失败项：")
        for n, _, d in failed:
            print(f"  - {n} {d}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
