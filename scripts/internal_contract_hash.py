#!/usr/bin/env python3
"""Compute DKWS internal contract bundle hash."""
from __future__ import annotations
import hashlib, json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "docs" / "contracts" / "internal"
WHITELIST = [
    "openapi/dkws-skill-runtime-internal-v1.yaml",
    "schemas/execution-plan.schema.json",
    "schemas/execution-result.schema.json",
    "schemas/tool-call-receipt.schema.json",
    "schemas/model-call-receipt.schema.json",
    "schemas/runtime-error.schema.json",
    "schemas/runtime-capabilities.schema.json",
]

def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()

def main() -> None:
    entries = []
    for rel in WHITELIST:
        p = BASE / rel
        if not p.is_file():
            raise FileNotFoundError(p)
        entries.append({"path": rel, "sha256": sha256_file(p)})
    entries.sort(key=lambda e: e["path"])
    h = hashlib.sha256()
    for e in entries:
        h.update(e["path"].encode("utf-8")); h.update(b"\0"); h.update(e["sha256"].encode("ascii")); h.update(b"\0")
    result = {
        "schema": "dkws-internal-contract-bundle/v1",
        "base_dir": "docs/contracts/internal",
        "bundle_hash": h.hexdigest(),
        "files": entries,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
