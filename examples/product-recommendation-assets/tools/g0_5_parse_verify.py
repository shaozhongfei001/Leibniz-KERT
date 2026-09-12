#!/usr/bin/env python3
"""
G0-5 解析验证器 —— 公开价目 PDF → 结构化条目 + 物理页码定位

Loop PI-0 · Gate G0-5
产出符合 CTR-PK-EVR-001（specs/product-knowledge/evidence-ref.schema.json）的
EvidenceRef 记录，以及量化解析指标。

严格遵守的约束：
1. usage 恒为 VERIFICATION_ONLY —— 本区材料只验证解析器能否读取，不作产品卡依据
2. page 为物理页码（PDF 第 N 页），非印刷页码
3. bbox.origin 显式声明为 TOP_LEFT（pdfplumber 输出左上原点）
4. PDF 无 front matter，只填 sourceBytesHash（纯 hex），不填 sourceContentHash
5. 抽不到的字段填 UNKNOWN，禁止编造
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
# 脚本位于 <assets>/tools/，资产根为其父目录
BASE = Path(__file__).resolve().parent.parent
RAW_DIR = BASE / "01_raw" / "_public_reference"
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


# 价目表 8 列表头，用于识别表头行
EXPECTED_HEADER = ["编号", "服务项目", "服务内容", "服务价格"]
# 服务编号形态：7 位数字
CODE_RE = re.compile(r"^\d{7}$")
# 章节行形态：一、结算业务 / 1.1存取款服务
SECTION_RE = re.compile(r"^([一二三四五六七八九十]+、|\d+\.\d+)")


def sha256_bytes(path: Path) -> str:
    """清单哈希：SHA-256(完整文件字节)，纯 hex 无前缀。PDF 无 front matter，不适用 content_hash。"""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def norm(cell) -> str:
    """单元格归一化：折行空白压缩为单空格。不改写内容。"""
    if cell is None:
        return ""
    return re.sub(r"\s+", " ", str(cell)).strip()


def parse_pdf(pdf_path: Path, source_id: str, source_title: str):
    """
    抽取价目条目。返回 (items, metrics)。

    每个 item 携带物理页码与 bbox，可直接构造 EvidenceRef。
    """
    bytes_hash = sha256_bytes(pdf_path)
    items = []
    metrics = {
        "pages_total": 0,
        "pages_with_table": 0,
        "tables_total": 0,
        "rows_scanned": 0,
        "rows_header": 0,
        "rows_section": 0,
        "rows_empty": 0,
        "items_extracted": 0,
        "items_with_page": 0,
        "items_with_bbox": 0,
        "unknown_field_count": 0,
        "total_field_count": 0,
        "rows_continuation": 0,
        "rows_unparsed": 0,
        "unparsed_samples": [],
    }

    with pdfplumber.open(pdf_path) as pdf:
        metrics["pages_total"] = len(pdf.pages)
        current_section = "UNKNOWN"

        for page_no, page in enumerate(pdf.pages, start=1):  # 物理页码，1-based
            tables = page.find_tables()
            if tables:
                metrics["pages_with_table"] += 1
            metrics["tables_total"] += len(tables)

            for table in tables:
                rows = table.extract()
                # 行 bbox：pdfplumber table.rows 与 extract() 行一一对应
                row_boxes = [r.bbox for r in table.rows] if table.rows else []

                for ri, row in enumerate(rows):
                    metrics["rows_scanned"] += 1
                    cells = [norm(c) for c in row]
                    nonempty = [c for c in cells if c]

                    if not nonempty:
                        metrics["rows_empty"] += 1
                        continue

                    # 表头行
                    if all(h in cells for h in EXPECTED_HEADER):
                        metrics["rows_header"] += 1
                        continue

                    # 章节行：仅首列有值且形如「一、xxx」或「1.1xxx」
                    if len(nonempty) == 1 and SECTION_RE.match(cells[0]):
                        current_section = cells[0]
                        metrics["rows_section"] += 1
                        continue

                    # 数据行：首列为 7 位服务编号
                    if not CODE_RE.match(cells[0]):
                        # 续行：编号/项目/内容三列皆空，说明是上一条目多行单元格的
                        # 溢出内容（典型如分档价格表述被拆成多行）。这不是解析失败，
                        # 而是 PDF 表格换行的正常形态，单独计数避免虚高失败率。
                        head_empty = all(not c for c in cells[:3])
                        if head_empty and items:
                            metrics["rows_continuation"] += 1
                            # 溢出内容并回上一条目，不丢信息
                            tail = " ".join(c for c in cells[3:] if c)
                            if tail:
                                prev = items[-1]
                                if prev["servicePrice"] == "UNKNOWN":
                                    prev["servicePrice"] = tail
                                else:
                                    prev["servicePrice"] = f"{prev['servicePrice']} {tail}"
                                prev["_continuationRows"] = prev.get("_continuationRows", 0) + 1
                            continue
                        metrics["rows_unparsed"] += 1
                        if len(metrics["unparsed_samples"]) < 5:
                            metrics["unparsed_samples"].append(
                                {"page": page_no, "row": ri,
                                 "cells": [c[:40] for c in cells[:4]]}
                            )
                        continue

                    def field(idx):
                        """取列值；缺失或空一律 UNKNOWN，不编造。"""
                        metrics["total_field_count"] += 1
                        val = cells[idx] if idx < len(cells) else ""
                        if not val:
                            metrics["unknown_field_count"] += 1
                            return "UNKNOWN"
                        return val

                    item = {
                        "serviceCode": cells[0],
                        "section": current_section,
                        "serviceName": field(1),
                        "serviceContent": field(2),
                        "servicePrice": field(3),
                        "discount": field(4),
                        "discountFrom": field(5),
                        "discountTo": field(6),
                        "remark": field(7),
                        "_page": page_no,
                        "_bbox": row_boxes[ri] if ri < len(row_boxes) else None,
                    }
                    items.append(item)
                    metrics["items_extracted"] += 1
                    if item["_page"]:
                        metrics["items_with_page"] += 1
                    if item["_bbox"]:
                        metrics["items_with_bbox"] += 1

    return items, metrics, bytes_hash


def to_evidence_ref(item, source_id, source_title, source_path, bytes_hash):
    """构造符合 CTR-PK-EVR-001 的 EvidenceRef。usage 恒为 VERIFICATION_ONLY。"""
    quote_parts = [
        item["serviceCode"],
        item["serviceName"],
        item["serviceContent"],
        item["servicePrice"],
    ]
    quote = " | ".join(p for p in quote_parts if p and p != "UNKNOWN")

    ref = {
        "schemaVersion": "1.0.0",
        "evidenceRefId": f"EVR-{source_id.replace('-', '')}-{item['serviceCode']}",
        "sourceId": source_id,
        "sourceTitle": source_title,
        "sourcePath": source_path,
        # PDF 无 front matter → 只能填 sourceBytesHash，不填 sourceContentHash
        "sourceBytesHash": bytes_hash,
        "locatorType": "PDF_PAGE",
        "page": item["_page"],  # 物理页码
        "quote": quote[:2000],
        "usage": "VERIFICATION_ONLY",
        "authorityLevel": "PUBLIC_PRICE_DISCLOSURE",
        "retrievedAt": now_cst().isoformat(timespec="seconds"),
        "extractedBy": f"parser:pdfplumber@{pdfplumber.__version__}",
        "note": "G0-5 解析验证产出。仅验证解析器能否读取源材料，不得作为产品卡字段权威依据。",
    }
    if item["_bbox"]:
        x0, top, x1, bottom = item["_bbox"]
        ref["bbox"] = {
            "x0": round(x0, 2),
            "y0": round(top, 2),
            "x1": round(x1, 2),
            "y1": round(bottom, 2),
            "unit": "PDF_POINT",
            "origin": "TOP_LEFT",  # pdfplumber 输出左上原点，必须显式声明
        }
    return ref


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    sources = [
        ("PUB-PRICE-001", "对公客户市场调节价服务名录（结算业务类，公开公示 PDF）"),
    ]

    report = {
        "gate": "G0-5",
        "loop": "PI-0",
        "generatedAt": now_cst().isoformat(timespec="seconds"),
        "parser": f"pdfplumber@{pdfplumber.__version__}",
        "sources": [],
    }
    all_refs = []

    for source_id, title in sources:
        pdf_path = RAW_DIR / f"{source_id}.pdf"
        if not pdf_path.exists():
            report["sources"].append({"sourceId": source_id, "status": "MISSING"})
            continue

        items, metrics, bytes_hash = parse_pdf(pdf_path, source_id, title)
        rel_path = f"01_raw/_public_reference/{source_id}.pdf"
        refs = [to_evidence_ref(i, source_id, title, rel_path, bytes_hash) for i in items]
        all_refs.extend(refs)

        data_rows = metrics["items_extracted"] + metrics["rows_unparsed"]
        report["sources"].append({
            "sourceId": source_id,
            "sourceTitle": title,
            "sourcePath": rel_path,
            "status": "AVAILABLE",
            "fileBytes": pdf_path.stat().st_size,
            "sourceBytesHash": bytes_hash,
            "usage": "VERIFICATION_ONLY",
            "authorityLevel": "PUBLIC_PRICE_DISCLOSURE",
            "metrics": {
                **{k: v for k, v in metrics.items() if k != "unparsed_samples"},
                "pageLocationSuccessRate": round(
                    metrics["items_with_page"] / metrics["items_extracted"], 4
                ) if metrics["items_extracted"] else 0.0,
                "bboxLocationSuccessRate": round(
                    metrics["items_with_bbox"] / metrics["items_extracted"], 4
                ) if metrics["items_extracted"] else 0.0,
                "parseFailureRate": round(
                    metrics["rows_unparsed"] / data_rows, 4
                ) if data_rows else 0.0,
                "unknownFieldRate": round(
                    metrics["unknown_field_count"] / metrics["total_field_count"], 4
                ) if metrics["total_field_count"] else 0.0,
            },
            "unparsedSamples": metrics["unparsed_samples"],
        })

    (OUT_DIR / "g0-5-parse-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (OUT_DIR / "g0-5-evidence-refs.json").write_text(
        json.dumps(all_refs, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"\nEvidenceRef 产出: {len(all_refs)} 条 → {OUT_DIR / 'g0-5-evidence-refs.json'}")
    return 0 if all_refs else 1


if __name__ == "__main__":
    sys.exit(main())
