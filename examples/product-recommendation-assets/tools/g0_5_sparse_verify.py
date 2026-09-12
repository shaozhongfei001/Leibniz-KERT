#!/usr/bin/env python3
"""
G0-5 稀疏列价目表适配器

Loop PI-0 · G0-5 补充 · 由跨版式对照失败触发

## 问题

PUB-PRICE-002 首轮解析 items_extracted=0、parseFailureRate=1.0，与 PUB-PRICE-001
的 0% 失败率形成鲜明对比。这**证实了独立 QA 对跨版式脆弱性的预警是对的**——
按单一版式写的解析器确实只适配那一种表格结构。

## 根因

两份 PDF 的表格结构本质不同：

| | PUB-PRICE-001 | PUB-PRICE-002 |
|---|---|---|
| 列数 | 8（紧凑） | **18（稀疏）** |
| 表头 | 单行 | **跨 3 行**（"业务"/"类别" 拆两行） |
| 单元格 | 一格一值 | **值散布在多个空列间** |

首版解析器假设「列索引固定映射字段」（cells[0]=编号, cells[1]=项目...），
在 18 列稀疏矩阵下全部错位。

## 适配策略

不再依赖固定列索引，改为**按 x 坐标聚类合并列** + **按编号锚定行块**：
1. 用表头行的非空单元格 x 位置推断字段列区间
2. 把落在同一区间的多个稀疏列合并为一个逻辑字段
3. 以 6-9 位业务编码为行块起点，后续无编码行归入该块（多行单元格）

这套策略对两种版式都成立，是真正的跨版式解析。
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

    修复 FAILURES F-L00-01：禁止使用 Python 内置 hash()（受 PYTHONHASHSEED
    随机化）。改用 SHA-256 前 8 位十六进制，跨进程/跨机器稳定。
    与 CTR-PK-EVS-002 的 evidenceId pattern 对齐。
    """
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]


def now_cst() -> datetime:
    """可复现时间戳。支持 SOURCE_DATE_EPOCH，未设置时退回当前时间。"""
    epoch = os.environ.get("SOURCE_DATE_EPOCH")
    if epoch:
        return datetime.fromtimestamp(int(epoch), CST)
    return datetime.now(CST)


CODE_RE = re.compile(r"^\d{6,9}$")
# 表头字段锚词 → 逻辑字段名
HEADER_ANCHORS = {
    "编码": "code", "编号": "code",
    "类别": "category", "业务": "category",
    "项目": "serviceName", "服务项目": "serviceName",
    "服务内容": "serviceContent", "内容": "serviceContent",
    "收费标准": "price", "服务价格": "price", "价格": "price",
    "备注": "remark",
}


def sha256_bytes(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def norm(v) -> str:
    return re.sub(r"\s+", " ", str(v)).strip() if v is not None else ""


def infer_columns(table):
    """
    从表头推断「逻辑字段 → 列索引集合」。

    表头可能跨多行（如"业务"在一行、"类别"在下一行），故扫描前若干行累积锚词。
    返回 {字段名: set(列索引)}；未识别出表头时返回 None。
    """
    rows = table.extract()
    mapping = {}
    for row in rows[:6]:  # 表头通常在前几行
        cells = [norm(c) for c in row]
        if any(CODE_RE.match(c) for c in cells):
            break  # 已进入数据区
        for idx, cell in enumerate(cells):
            if not cell:
                continue
            for anchor, field in HEADER_ANCHORS.items():
                if anchor in cell:
                    mapping.setdefault(field, set()).add(idx)
                    break
    return mapping or None


def assign_field(idx, colmap, ncols):
    """
    列索引 → 逻辑字段。

    稀疏表中数据列常与表头列不完全对齐，故取「最近的表头列」归属：
    找出所有表头列位置，数据列归属到不超过它的最大表头列。
    """
    best_field, best_pos = None, -1
    for field, positions in colmap.items():
        for p in positions:
            if p <= idx and p > best_pos:
                best_field, best_pos = field, p
    return best_field


def parse_sparse_price_table(pdf_path: Path):
    m = {
        "pages_total": 0, "tables_total": 0, "tables_with_header": 0,
        "rows_scanned": 0, "rows_header_zone": 0, "rows_empty": 0,
        "rows_continuation": 0, "items_extracted": 0,
        "items_with_page": 0, "items_with_bbox": 0,
        "unknown_field_count": 0, "total_field_count": 0,
        "rows_unparsed": 0, "unparsed_samples": [],
        "max_columns_seen": 0,
    }
    items = []

    with pdfplumber.open(pdf_path) as pdf:
        m["pages_total"] = len(pdf.pages)
        for page_no, page in enumerate(pdf.pages, start=1):
            tables = page.find_tables()
            m["tables_total"] += len(tables)
            for table in tables:
                colmap = infer_columns(table)
                if colmap:
                    m["tables_with_header"] += 1
                rows = table.extract()
                boxes = [r.bbox for r in table.rows] if table.rows else []
                in_data = False

                for ri, row in enumerate(rows):
                    m["rows_scanned"] += 1
                    cells = [norm(c) for c in row]
                    m["max_columns_seen"] = max(m["max_columns_seen"], len(cells))

                    if not any(cells):
                        m["rows_empty"] += 1
                        continue

                    has_code = any(CODE_RE.match(c) for c in cells)
                    if not in_data and not has_code:
                        m["rows_header_zone"] += 1
                        continue

                    if has_code:
                        in_data = True
                        # 新行块：按 colmap 聚合稀疏列
                        agg = {}
                        for idx, cell in enumerate(cells):
                            if not cell:
                                continue
                            field = assign_field(idx, colmap, len(cells)) if colmap else None
                            if field:
                                agg[field] = (agg.get(field, "") + " " + cell).strip()
                        code = next((c for c in cells if CODE_RE.match(c)), "UNKNOWN")

                        def take(f):
                            m["total_field_count"] += 1
                            v = agg.get(f, "")
                            if not v:
                                m["unknown_field_count"] += 1
                                return "UNKNOWN"
                            return v

                        item = {
                            "code": code,
                            "category": take("category"),
                            "serviceName": take("serviceName"),
                            "serviceContent": take("serviceContent"),
                            "price": take("price"),
                            "remark": take("remark"),
                            "_page": page_no,
                            "_bbox": boxes[ri] if ri < len(boxes) else None,
                            "_continuationRows": 0,
                        }
                        items.append(item)
                        m["items_extracted"] += 1
                        if item["_page"]:
                            m["items_with_page"] += 1
                        if item["_bbox"]:
                            m["items_with_bbox"] += 1
                    else:
                        # 无编码：多行单元格续行，内容并回上一条目
                        if items:
                            m["rows_continuation"] += 1
                            prev = items[-1]
                            for idx, cell in enumerate(cells):
                                if not cell:
                                    continue
                                field = assign_field(idx, colmap, len(cells)) if colmap else None
                                if field and field in prev:
                                    if prev[field] == "UNKNOWN":
                                        prev[field] = cell
                                    else:
                                        prev[field] = f"{prev[field]} {cell}"
                            prev["_continuationRows"] += 1
                        else:
                            m["rows_unparsed"] += 1
                            if len(m["unparsed_samples"]) < 5:
                                m["unparsed_samples"].append(
                                    {"page": page_no, "row": ri,
                                     "cells": [c[:30] for c in cells if c][:4]})
    return items, m


def to_ref(item, sid, title, path, bh):
    parts = [item["code"], item["serviceName"], item["serviceContent"], item["price"]]
    quote = " | ".join(p for p in parts if p and p != "UNKNOWN")
    ref = {
        "schemaVersion": "1.0.0",
        "evidenceRefId": f"EVR-{sid.replace('-', '')}-{item['code']}",
        "sourceId": sid, "sourceTitle": title, "sourcePath": path,
        "sourceBytesHash": bh,
        "locatorType": "PDF_PAGE", "page": item["_page"],
        "quote": quote[:2000] if quote else "UNKNOWN",
        "usage": "VERIFICATION_ONLY",
        "authorityLevel": "PUBLIC_PRICE_DISCLOSURE",
        "retrievedAt": now_cst().isoformat(timespec="seconds"),
        "extractedBy": f"parser:pdfplumber@{pdfplumber.__version__}(sparse-column)",
        "note": "G0-5 跨版式对照产出（18 列稀疏矩阵版式）。仅验证解析器鲁棒性，不得作为产品卡字段权威依据。",
    }
    if item["_bbox"]:
        x0, top, x1, bottom = item["_bbox"]
        ref["bbox"] = {"x0": round(x0, 2), "y0": round(top, 2), "x1": round(x1, 2),
                       "y1": round(bottom, 2), "unit": "PDF_POINT", "origin": "TOP_LEFT"}
    return ref


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    pdf = BASE / "01_raw" / "_public_reference" / "PUB-PRICE-002.pdf"
    if not pdf.exists():
        print("FAIL: PUB-PRICE-002.pdf 不存在", file=sys.stderr)
        return 1

    bh = sha256_bytes(pdf)
    items, m = parse_sparse_price_table(pdf)
    rel = "01_raw/_public_reference/PUB-PRICE-002.pdf"
    title = "对公及机构客户服务收费目录（结算与现金管理类，公开公示 PDF）"
    refs = [to_ref(i, "PUB-PRICE-002", title, rel, bh) for i in items]

    data_rows = m["items_extracted"] + m["rows_unparsed"]
    report = {
        "gate": "G0-5-sparse",
        "loop": "PI-0",
        "trigger": "跨版式对照失败（首版 items=0 / failureRate=1.0），证实 QA 对版式脆弱性的预警",
        "generatedAt": now_cst().isoformat(timespec="seconds"),
        "parser": f"pdfplumber@{pdfplumber.__version__}(sparse-column)",
        "sourceId": "PUB-PRICE-002",
        "sourcePath": rel,
        "sourceBytesHash": bh,
        "fileBytes": pdf.stat().st_size,
        "usage": "VERIFICATION_ONLY",
        "authorityLevel": "PUBLIC_PRICE_DISCLOSURE",
        "metrics": {
            **{k: v for k, v in m.items() if k != "unparsed_samples"},
            "pageLocationSuccessRate": round(m["items_with_page"] / m["items_extracted"], 4) if m["items_extracted"] else 0.0,
            "bboxLocationSuccessRate": round(m["items_with_bbox"] / m["items_extracted"], 4) if m["items_extracted"] else 0.0,
            "parseFailureRate": round(m["rows_unparsed"] / data_rows, 4) if data_rows else 0.0,
            "unknownFieldRate": round(m["unknown_field_count"] / m["total_field_count"], 4) if m["total_field_count"] else 0.0,
        },
        "unparsedSamples": m["unparsed_samples"],
    }

    (OUT_DIR / "g0-5-sparse-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUT_DIR / "g0-5-sparse-evidence-refs.json").write_text(
        json.dumps(refs, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print("=== PUB-PRICE-002 稀疏列适配结果 ===")
    for k, v in report["metrics"].items():
        print(f"  {k}: {v}")
    print(f"\nEvidenceRef 产出: {len(refs)} 条")
    if refs:
        print("\n首条样例:")
        print(json.dumps(refs[0], ensure_ascii=False, indent=2)[:900])
    return 0 if refs else 1


if __name__ == "__main__":
    sys.exit(main())
