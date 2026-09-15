#!/usr/bin/env python3
"""SourceVersion / Fragment 构建器（Loop L10）

职责：把 01_raw/_authoritative/ 下的制度文本（本轮为 DEMO 演示文本）
编译为不可变的 SourceVersion 与 Fragment 对象，落到 02_work/。

设计约束：
  1. 字段严格对齐 specs/product-knowledge/migration-candidates 的
     pk_source_version / pk_fragment 表列，不发明合同未定义字段；
  2. ID 规则来自 CTR-PK-EVS-002：
       SV-{sourceId 去横线}-{YYYYMMDD}-{bytesHash 前 8 位}
       FRG-{sourceId 去横线}-{4 位序号}
  3. 确定性：设置 SOURCE_DATE_EPOCH 后同一输入产出逐字节一致
     （reproducible-builds.org 约定，与 L03 W2 一致）；
  4. DEMO 文本 produced 的 SourceVersion 必须 provenanceState=DEMO，
     绝不冒充真实制度（红线）。

用法:
    python3 tools/l10_build_source_versions.py
    SOURCE_DATE_EPOCH=1757000000 python3 tools/l10_build_source_versions.py
"""

import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
AUTH = BASE / "01_raw" / "_authoritative"
SV_DIR = BASE / "02_work" / "source-versions"
FRG_DIR = BASE / "02_work" / "fragments"

CST = timezone(timedelta(hours=8))
CLAUSE_RE = re.compile(r"^\*\*第([一二三四五六七八九十百]+)条\*\*")
CHUNK_SPLIT = re.compile(r"^(#{1,6}\s|\*\*第[一二三四五六七八九十百]+条\*\*)")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def now_cst() -> datetime:
    epoch = os.environ.get("SOURCE_DATE_EPOCH")
    if epoch:
        return datetime.fromtimestamp(int(epoch), CST)
    return datetime.now(CST)


def sid_key(source_id: str) -> str:
    return source_id.replace("-", "")


def parse_front_matter(text: str) -> dict:
    """极简 YAML front matter 解析（只支持 key: value 与 [a, b]）。"""
    if not text.startswith("---"):
        return {}
    parts = text.split("\n---", 1)
    fm = {}
    for line in parts[0].splitlines()[1:]:
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*):\s*(.*)$", line)
        if not m:
            continue
        key, val = m.group(1), m.group(2).strip().strip('"')
        if val.startswith("[") and val.endswith("]"):
            fm[key] = [v.strip().strip('"') for v in val[1:-1].split(",") if v.strip()]
        else:
            fm[key] = val
    return fm


def split_fragments(body: str):
    """按「条」切分。每个 Fragment = 一个条款的完整原文。

    返回 [(clause_no, content_text)]。content_text 必须可在源文件中原样定位，
    这是 INV-EVS-02（quote 必须能在 Fragment 内定位）的前置条件。
    """
    lines = body.splitlines()
    chunks = []
    cur_title = None
    buf = []
    for line in lines:
        if CLAUSE_RE.match(line):
            if cur_title is not None:
                chunks.append((cur_title, "\n".join(buf).strip()))
            cur_title = CLAUSE_RE.match(line).group(1)
            buf = [line]
        elif cur_title is not None:
            if CHUNK_SPLIT.match(line):
                chunks.append((cur_title, "\n".join(buf).strip()))
                cur_title = None
                buf = []
            else:
                buf.append(line)
    if cur_title is not None:
        chunks.append((cur_title, "\n".join(buf).strip()))
    return [(i + 1, c) for i, (_, c) in enumerate(chunks)]


def build_one(path: Path, ingested: datetime):
    raw = path.read_bytes()
    text = raw.decode("utf-8")
    fm = parse_front_matter(text)
    source_id = fm.get("source_id") or path.name.split(".")[0]

    body = text.split("\n---", 1)[1] if text.startswith("---") else text
    body = body.lstrip("\n")

    bytes_sha = sha256_bytes(raw)
    date_part = ingested.strftime("%Y%m%d")
    sv_id = f"SV-{sid_key(source_id)}-{date_part}-{bytes_sha[:8]}"

    is_demo = path.name.endswith(".DEMO.md") or fm.get("provenance_state") == "DEMO"
    sv = {
        "sourceVersionId": sv_id,
        "sourceId": source_id,
        "bytesSha256": bytes_sha,
        "byteSize": len(raw),
        "pageCount": None,
        "ingestedAt": ingested.isoformat(),
        "supersededBy": None,
        "provenanceUrl": None,
        "provenanceState": "DEMO" if is_demo else (fm.get("provenance_state") or "UNVERIFIED"),
        "zone": "_authoritative",
        "sourcePath": f"01_raw/_authoritative/{path.name}",
        "productFamily": fm.get("product_family"),
        "allowedClaimTypes": fm.get("allowed_claim_types", []),
        "authorityLevel": fm.get("authority_level"),
    }

    frgs = []
    for seq, content in split_fragments(body):
        frgs.append({
            "fragmentId": f"FRG-{sid_key(source_id)}-{seq:04d}",
            "sourceVersionId": sv_id,
            "seqNo": seq,
            "pageNo": None,
            "contentText": content,
            "contentSha256": sha256_text(content),
        })
    return sv, frgs


def main():
    if not AUTH.exists():
        print(f"FAIL | 权威区目录不存在: {AUTH}")
        return 1

    ingested = now_cst()
    targets = sorted(AUTH.glob("*.DEMO.md"))
    if not targets:
        print("FAIL | 未找到任何 .DEMO.md 演示文本")
        return 1

    SV_DIR.mkdir(parents=True, exist_ok=True)
    FRG_DIR.mkdir(parents=True, exist_ok=True)

    manifest_svs = []
    for p in targets:
        sv, frgs = build_one(p, ingested)
        (SV_DIR / f"{sv['sourceVersionId']}.json").write_text(
            json.dumps(sv, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8")
        (FRG_DIR / f"{sv['sourceId']}.fragments.json").write_text(
            json.dumps({"sourceId": sv["sourceId"],
                        "sourceVersionId": sv["sourceVersionId"],
                        "fragmentCount": len(frgs),
                        "fragments": frgs},
                       ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8")
        manifest_svs.append({
            "sourceVersionId": sv["sourceVersionId"],
            "sourceId": sv["sourceId"],
            "bytesSha256": sv["bytesSha256"],
            "byteSize": sv["byteSize"],
            "provenanceState": sv["provenanceState"],
            "fragmentCount": len(frgs),
        })
        print(f"OK | {sv['sourceVersionId']} | fragments={len(frgs)} | "
              f"provenanceState={sv['provenanceState']}")

    run_id = "RUN-" + ingested.strftime("%Y%m%d") + "-" + sha256_text(
        "".join(m["bytesSha256"] for m in manifest_svs))[:8]
    manifest = {
        "extractionRunId": run_id,
        "generatedAt": ingested.isoformat(),
        "sourceVersions": manifest_svs,
    }
    (SV_DIR / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")

    print(f"\nrun={run_id} · sources={len(manifest_svs)} · "
          f"fragments={sum(m['fragmentCount'] for m in manifest_svs)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
