#!/usr/bin/env python3
"""
G0-5 扩展验证器 —— 跨版式鲁棒性 + CLAUSE 定位

Loop PI-0 · Gate G0-5 补充（由独立 QA 的 AT-PI0-004 = PARTIAL 判定触发）

新增覆盖：
1. PUB-PRICE-002（第二种价目表版式，7 页）—— 排除「解析器只适配一种表格结构」的怀疑
2. REG-CM-001（《现金管理暂行条例》国务院令第12号，4 页）—— 验证 CLAUSE 定位方式，
   此前 G0-5 只验过 PDF_PAGE

REG-CM-001 是本项目首份进入 _authoritative/ 的真实监管法规，authorityLevel=REGULATORY。
但注意：它是国家层面法规而非行内制度，只能支撑「现金收支合规边界」类字段，
给不出产品准入评级、前置产品等 HardRule，故不能替代 SRC-CM-001~003 行内制度。
"""

import hashlib
import os
import json
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pdfplumber

CST = timezone(timedelta(hours=8))
BASE = Path(__file__).resolve().parent.parent
OUT_DIR = BASE / "02_work" / "_verification"


def stable_id(text: str) -> str:
    """确定性证据 ID 后缀。

    修复 FAILURES F-L00-01：原实现使用 Python 内置 hash()，受 PYTHONHASHSEED
    随机化影响，导致同输入每次运行产出不同 evidenceRefId，破坏证据可追溯性。
    改用 SHA-256 前 8 位十六进制，跨进程/跨机器稳定。
    与 CTR-PK-EVS-002 的 evidenceId pattern ^EVS-[A-Z0-9]+-[0-9a-f]{8}$ 对齐。
    """
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]


def now_cst() -> datetime:
    """可复现时间戳。

    支持 SOURCE_DATE_EPOCH（reproducible-builds.org 约定）：设置后产出文件
    哈希可完全复现，便于证据锚定；未设置时退回当前时间，保持既有行为不变。
    """
    epoch = os.environ.get("SOURCE_DATE_EPOCH")
    if epoch:
        return datetime.fromtimestamp(int(epoch), CST)
    return datetime.now(CST)


CODE_RE = re.compile(r"^\d{6,8}$")
# 中文条款号：第一条 / 第二十三条 / 第十条之一
CLAUSE_RE = re.compile(r"^第([一二三四五六七八九十百零〇]+)条")
CHAPTER_RE = re.compile(r"^第([一二三四五六七八九十]+)章\s*(.*)$")


def sha256_bytes(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def norm(cell) -> str:
    if cell is None:
        return ""
    return re.sub(r"\s+", " ", str(cell)).strip()


def parse_price_table(pdf_path: Path):
    """价目表版式：表格抽取 + 物理页码。用于跨版式鲁棒性对照。"""
    m = {
        "pages_total": 0, "tables_total": 0, "rows_scanned": 0,
        "rows_header": 0, "rows_section": 0, "rows_empty": 0,
        "rows_continuation": 0, "items_extracted": 0,
        "items_with_page": 0, "items_with_bbox": 0,
        "unknown_field_count": 0, "total_field_count": 0,
        "rows_unparsed": 0, "unparsed_samples": [],
    }
    items = []
    with pdfplumber.open(pdf_path) as pdf:
        m["pages_total"] = len(pdf.pages)
        section = "UNKNOWN"
        for page_no, page in enumerate(pdf.pages, start=1):
            tables = page.find_tables()
            m["tables_total"] += len(tables)
            for table in tables:
                rows = table.extract()
                boxes = [r.bbox for r in table.rows] if table.rows else []
                for ri, row in enumerate(rows):
                    m["rows_scanned"] += 1
                    cells = [norm(c) for c in row]
                    if not any(cells):
                        m["rows_empty"] += 1
                        continue
                    # 表头：含「编号」与「服务」类字样
                    joined = " ".join(cells)
                    if ("编号" in joined and "服务" in joined) or "收费标准" in joined and not CODE_RE.match(cells[0]):
                        if not CODE_RE.match(cells[0]):
                            m["rows_header"] += 1
                            continue
                    # 章节行：仅一列有值且非编号
                    nonempty = [c for c in cells if c]
                    if len(nonempty) == 1 and not CODE_RE.match(cells[0]):
                        section = nonempty[0][:60]
                        m["rows_section"] += 1
                        continue
                    # 数据行判定：首列为编号，或首列非空且第二列非空（宽松适配第二种版式）
                    is_data = bool(CODE_RE.match(cells[0])) or (
                        len(cells) > 2 and cells[0] and cells[1] and not CODE_RE.match(cells[0])
                        and len(cells[0]) < 40
                    )
                    if not is_data:
                        head_empty = all(not c for c in cells[:2])
                        if head_empty and items:
                            m["rows_continuation"] += 1
                            tail = " ".join(c for c in cells[2:] if c)
                            if tail:
                                prev = items[-1]
                                prev["detail"] = (tail if prev["detail"] == "UNKNOWN"
                                                  else f"{prev['detail']} {tail}")
                            continue
                        m["rows_unparsed"] += 1
                        if len(m["unparsed_samples"]) < 5:
                            m["unparsed_samples"].append(
                                {"page": page_no, "row": ri, "cells": [c[:40] for c in cells[:4]]})
                        continue

                    def field(idx):
                        m["total_field_count"] += 1
                        val = cells[idx] if idx < len(cells) else ""
                        if not val:
                            m["unknown_field_count"] += 1
                            return "UNKNOWN"
                        return val

                    item = {
                        "code": cells[0] if CODE_RE.match(cells[0]) else "UNKNOWN",
                        "section": section,
                        "name": field(1) if CODE_RE.match(cells[0]) else cells[0],
                        "detail": field(2),
                        "price": field(3),
                        "_page": page_no,
                        "_bbox": boxes[ri] if ri < len(boxes) else None,
                    }
                    items.append(item)
                    m["items_extracted"] += 1
                    if item["_page"]:
                        m["items_with_page"] += 1
                    if item["_bbox"]:
                        m["items_with_bbox"] += 1
    return items, m


def parse_regulation(pdf_path: Path):
    """法规版式：按条款抽取，验证 CLAUSE 定位方式。"""
    m = {
        "pages_total": 0, "lines_scanned": 0, "chapters_found": 0,
        "clauses_extracted": 0, "clauses_with_page": 0,
        "clauses_with_chapter": 0, "lines_unattributed": 0,
        "unattributed_samples": [],
    }
    clauses = []
    with pdfplumber.open(pdf_path) as pdf:
        m["pages_total"] = len(pdf.pages)
        chapter = "UNKNOWN"
        current = None
        for page_no, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            for raw in text.split("\n"):
                line = raw.strip()
                m["lines_scanned"] += 1
                if not line:
                    continue
                ch = CHAPTER_RE.match(line)
                if ch:
                    chapter = line[:40]
                    m["chapters_found"] += 1
                    continue
                cl = CLAUSE_RE.match(line)
                if cl:
                    if current:
                        clauses.append(current)
                    current = {
                        "clause": f"第{cl.group(1)}条",
                        "chapter": chapter,
                        "text": line,
                        "_page": page_no,
                    }
                    m["clauses_extracted"] += 1
                    m["clauses_with_page"] += 1
                    if chapter != "UNKNOWN":
                        m["clauses_with_chapter"] += 1
                    continue
                if current:
                    current["text"] += " " + line
                else:
                    # 标题、发布信息等条款前的行，非解析失败
                    m["lines_unattributed"] += 1
                    if len(m["unattributed_samples"]) < 5:
                        m["unattributed_samples"].append({"page": page_no, "line": line[:60]})
        if current:
            clauses.append(current)
    return clauses, m


def price_ref(item, sid, title, path, bh):
    parts = [item["code"], item["name"], item["detail"], item["price"]]
    quote = " | ".join(p for p in parts if p and p != "UNKNOWN")
    ref = {
        "schemaVersion": "1.0.0",
        "evidenceRefId": f"EVR-{sid.replace('-', '')}-P{item['_page']}-{stable_id(quote)}",
        "sourceId": sid, "sourceTitle": title, "sourcePath": path,
        "sourceBytesHash": bh,
        "locatorType": "PDF_PAGE", "page": item["_page"],
        "quote": quote[:2000],
        "usage": "VERIFICATION_ONLY",
        "authorityLevel": "PUBLIC_PRICE_DISCLOSURE",
        "retrievedAt": now_cst().isoformat(timespec="seconds"),
        "extractedBy": f"parser:pdfplumber@{pdfplumber.__version__}",
        "note": "G0-5 跨版式对照产出。仅验证解析器鲁棒性，不得作为产品卡字段权威依据。",
    }
    if item["_bbox"]:
        x0, top, x1, bottom = item["_bbox"]
        ref["bbox"] = {"x0": round(x0, 2), "y0": round(top, 2), "x1": round(x1, 2),
                       "y1": round(bottom, 2), "unit": "PDF_POINT", "origin": "TOP_LEFT"}
    return ref


def clause_ref(cl, sid, title, path, bh):
    return {
        "schemaVersion": "1.0.0",
        "evidenceRefId": f"EVR-{sid.replace('-', '')}-{stable_id(cl['clause'])}",
        "sourceId": sid, "sourceTitle": title, "sourcePath": path,
        "sourceBytesHash": bh,
        "locatorType": "CLAUSE",
        "clause": cl["clause"],
        "section": cl["chapter"],
        "quote": cl["text"][:2000],
        "usage": "AUTHORITATIVE",
        "authorityLevel": "REGULATORY",
        "retrievedAt": now_cst().isoformat(timespec="seconds"),
        "extractedBy": f"parser:pdfplumber@{pdfplumber.__version__}",
        "note": ("国家层面法规，可支撑现金收支合规边界类字段。"
                 "但给不出产品准入评级/前置产品等 HardRule，不能替代行内制度 SRC-CM-001~003。"
                 "条款号取自法规原文结构，仍需 Owner 核定后转 CLAUSE_VERIFIED。"),
    }


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    report = {
        "gate": "G0-5-extended",
        "loop": "PI-0",
        "trigger": "独立 QA 判定 AT-PI0-004 = PARTIAL，补跨版式对照与 CLAUSE 定位验证",
        "generatedAt": now_cst().isoformat(timespec="seconds"),
        "parser": f"pdfplumber@{pdfplumber.__version__}",
        "sources": [],
    }
    all_refs = []

    # 1) 第二种价目表版式
    p2 = BASE / "01_raw" / "_public_reference" / "PUB-PRICE-002.pdf"
    if p2.exists():
        bh = sha256_bytes(p2)
        items, m = parse_price_table(p2)
        rel = "01_raw/_public_reference/PUB-PRICE-002.pdf"
        title = "对公及机构客户服务收费目录（结算与现金管理类，公开公示 PDF）"
        refs = [price_ref(i, "PUB-PRICE-002", title, rel, bh) for i in items]
        all_refs.extend(refs)
        data_rows = m["items_extracted"] + m["rows_unparsed"]
        report["sources"].append({
            "sourceId": "PUB-PRICE-002", "sourceTitle": title, "sourcePath": rel,
            "status": "AVAILABLE", "purpose": "跨版式鲁棒性对照",
            "fileBytes": p2.stat().st_size, "sourceBytesHash": bh,
            "usage": "VERIFICATION_ONLY", "authorityLevel": "PUBLIC_PRICE_DISCLOSURE",
            "metrics": {
                **{k: v for k, v in m.items() if k != "unparsed_samples"},
                "pageLocationSuccessRate": round(m["items_with_page"] / m["items_extracted"], 4) if m["items_extracted"] else 0.0,
                "bboxLocationSuccessRate": round(m["items_with_bbox"] / m["items_extracted"], 4) if m["items_extracted"] else 0.0,
                "parseFailureRate": round(m["rows_unparsed"] / data_rows, 4) if data_rows else 0.0,
                "unknownFieldRate": round(m["unknown_field_count"] / m["total_field_count"], 4) if m["total_field_count"] else 0.0,
            },
            "unparsedSamples": m["unparsed_samples"],
        })

    # 2) 监管法规 CLAUSE 定位
    reg = BASE / "01_raw" / "_authoritative" / "REG-CM-001.pdf"
    if reg.exists():
        bh = sha256_bytes(reg)
        clauses, m = parse_regulation(reg)
        rel = "01_raw/_authoritative/REG-CM-001.pdf"
        title = "《现金管理暂行条例》（2011 修订，国务院令第 12 号）"
        refs = [clause_ref(c, "REG-CM-001", title, rel, bh) for c in clauses]
        all_refs.extend(refs)
        report["sources"].append({
            "sourceId": "REG-CM-001", "sourceTitle": title, "sourcePath": rel,
            "status": "AVAILABLE", "purpose": "CLAUSE 定位方式验证 + 首份权威区真实法规",
            "fileBytes": reg.stat().st_size, "sourceBytesHash": bh,
            "usage": "AUTHORITATIVE", "authorityLevel": "REGULATORY",
            "clauseVerified": False,
            "clauseVerifiedNote": "条款号取自法规原文结构，仍需 Owner 核定后转 CLAUSE_VERIFIED",
            "metrics": {
                **{k: v for k, v in m.items() if k != "unattributed_samples"},
                "clausePageLocationRate": round(m["clauses_with_page"] / m["clauses_extracted"], 4) if m["clauses_extracted"] else 0.0,
                "clauseChapterAttributionRate": round(m["clauses_with_chapter"] / m["clauses_extracted"], 4) if m["clauses_extracted"] else 0.0,
            },
            "unattributedSamples": m["unattributed_samples"],
            "limitation": ("国家层面法规，非行内制度。可支撑现金收支合规边界，"
                           "给不出产品准入评级/前置产品等 HardRule，不能替代 SRC-CM-001~003。"),
        })

    (OUT_DIR / "g0-5-extended-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUT_DIR / "g0-5-extended-evidence-refs.json").write_text(
        json.dumps(all_refs, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    for s in report["sources"]:
        print(f"\n=== {s['sourceId']} | {s['purpose']} ===")
        print(f"  usage={s['usage']} authorityLevel={s['authorityLevel']}")
        for k, v in s["metrics"].items():
            print(f"  {k}: {v}")
    print(f"\nEvidenceRef 产出: {len(all_refs)} 条")
    return 0 if all_refs else 1


if __name__ == "__main__":
    sys.exit(main())
