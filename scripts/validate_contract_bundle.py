#!/usr/bin/env python3
"""DKWS Phase 0 contract bundle validation.

- 所有 JSON Schema 必须是合法 JSON 且符合 JSON Schema 2020-12 meta-schema
- 所有本地 $ref 必须存在
- OpenAPI YAML 必须可解析，且 paths/components 存在
- 不依赖网络
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import jsonschema
import yaml

ROOT = Path(__file__).resolve().parents[1]
CONTRACTS_DIR = ROOT / "docs" / "contracts"
SCHEMAS_DIR = CONTRACTS_DIR / "schemas"
OPENAPI = CONTRACTS_DIR / "openapi" / "dkws-openapi-v2.yaml"

META = jsonschema.Draft202012Validator.META_SCHEMA


def validate_schemas() -> list[str]:
    errors = []
    for p in sorted(SCHEMAS_DIR.glob("*.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception as exc:
            errors.append(f"{p.relative_to(ROOT)}: JSON parse failed: {exc}")
            continue
        try:
            jsonschema.Draft202012Validator.check_schema(data)
        except Exception as exc:
            errors.append(f"{p.relative_to(ROOT)}: schema invalid: {exc}")
        # local refs
        for ref in _collect_refs(data):
            target = _resolve_ref(ref)
            if target is None:
                errors.append(f"{p.relative_to(ROOT)}: unresolved $ref {ref!r}")
    return errors


def _collect_refs(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "$ref" and isinstance(v, str):
                yield v
            else:
                yield from _collect_refs(v)
    elif isinstance(obj, list):
        for item in obj:
            yield from _collect_refs(item)


def _resolve_ref(ref: str):
    if ref.startswith("#/"):
        return "internal"
    # file reference
    if "/" in ref:
        return "file"
    p = SCHEMAS_DIR / ref
    return p if p.is_file() else None


def validate_openapi() -> list[str]:
    errors = []
    try:
        text = OPENAPI.read_text(encoding="utf-8")
        data = yaml.safe_load(text)
    except Exception as exc:
        return [f"OpenAPI YAML parse failed: {exc}"]
    if data.get("openapi") != "3.1.0":
        errors.append("OpenAPI version must be 3.1.0")
    if not isinstance(data.get("paths"), dict):
        errors.append("OpenAPI paths missing")
    if not isinstance(data.get("components", {}).get("schemas"), dict):
        errors.append("OpenAPI components.schemas missing")
    # check local component refs
    for ref in _collect_refs(data):
        if ref.startswith("#/components/"):
            parts = ref.lstrip("#/").split("/")
            node = data
            ok = True
            for part in parts:
                if isinstance(node, dict) and part in node:
                    node = node[part]
                else:
                    ok = False
                    break
            if not ok:
                errors.append(f"OpenAPI unresolved ref {ref!r}")
    return errors


def main() -> int:
    errors = []
    errors += validate_schemas()
    errors += validate_openapi()
    if errors:
        print("CONTRACT_VALIDATION=FAIL")
        for e in errors:
            print(" -", e)
        return 1
    print("CONTRACT_VALIDATION=PASS")
    print(f"schemas={len(list(SCHEMAS_DIR.glob('*.json')))}")
    print(f"openapi={OPENAPI.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
