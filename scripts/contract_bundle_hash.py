#!/usr/bin/env python3
"""DKWS Phase 0 contract bundle hash.

规则：
- 固定白名单：docs/contracts/openapi/dkws-openapi-v2.yaml + docs/contracts/schemas/*.json
- 固定路径排序：按 POSIX 相对路径排序
- 编码：UTF-8，按原始字节哈希（不进行换行归一）
- 不包含自引用 hash 字段；清单单独输出时由本脚本生成，不作为输入
- 可重复计算
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRACTS_DIR = ROOT / "docs" / "contracts"
DEFAULT_WHITELIST = [
    "openapi/dkws-openapi-v2.yaml",
    "schemas/context-package.schema.json",
    "schemas/error.schema.json",
    "schemas/skill-execute-request.schema.json",
    "schemas/skill-execute-response.schema.json",
    "schemas/job.schema.json",
    "schemas/assembly-trace.schema.json",
    "schemas/supply-chain-graph.schema.json",
    "schemas/sp20.schema.json",
    "schemas/sp21.schema.json",
    "schemas/gate.schema.json",
    "schemas/evidence-bundle.schema.json",
]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def compute(whitelist: list[str]) -> dict:
    entries = []
    for rel in whitelist:
        p = CONTRACTS_DIR / rel
        if not p.is_file():
            raise FileNotFoundError(f"contract file missing: {p}")
        entries.append({"path": rel, "sha256": sha256_file(p)})
    entries.sort(key=lambda e: e["path"])
    h = hashlib.sha256()
    for e in entries:
        h.update(e["path"].encode("utf-8"))
        h.update(b"\0")
        h.update(e["sha256"].encode("ascii"))
        h.update(b"\0")
    return {
        "schema": "dkws-contract-bundle/v1",
        "base_dir": "docs/contracts",
        "encoding": "utf-8",
        "sort": "path_asc",
        "bundle_hash": h.hexdigest(),
        "files": entries,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Compute DKWS contract bundle hash")
    ap.add_argument("--output", help="optional JSON output path")
    args = ap.parse_args()
    result = compute(DEFAULT_WHITELIST)
    text = json.dumps(result, ensure_ascii=False, indent=2)
    print(text)
    if args.output:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
