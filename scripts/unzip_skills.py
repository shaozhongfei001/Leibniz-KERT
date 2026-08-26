#!/usr/bin/env python3
"""安全解压 Skill+示例数据 ZIP（规格 §16.1：拒绝路径穿越/绝对路径/超限）。

用法：python unzip_skills.py --source <袁阳目录> --target <解压目标>
"""

from __future__ import annotations

import argparse
import zipfile
from pathlib import Path

MAX_TOTAL_BYTES = 50 * 1024 * 1024
MAX_ENTRIES = 200


def unzip_safely(zip_path: Path, target: Path) -> list[str]:
    errors: list[str] = []
    written: list[str] = []
    with zipfile.ZipFile(zip_path) as zf:
        infos = zf.infolist()
        if len(infos) > MAX_ENTRIES:
            raise ValueError(f"条目数超限: {len(infos)} > {MAX_ENTRIES}")
        total = sum(i.file_size for i in infos)
        if total > MAX_TOTAL_BYTES:
            raise ValueError(f"总大小超限: {total} > {MAX_TOTAL_BYTES}")
        for info in infos:
            name = info.filename.replace("\\", "/")
            if name.startswith("/") or ".." in name.split("/"):
                errors.append(f"路径穿越被拒绝: {info.filename}")
                continue
            dest = target / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            if info.is_dir():
                continue
            with zf.open(info) as src, open(dest, "wb") as out:
                out.write(src.read())
            written.append(name)
    return written if not errors else errors


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True, help="袁阳目录（含 zip）")
    ap.add_argument("--target", required=True, help="解压目标目录")
    args = ap.parse_args()

    source = Path(args.source)
    target = Path(args.target)
    target.mkdir(parents=True, exist_ok=True)
    total = 0
    for z in sorted(source.glob("*.zip")):
        name = z.stem
        dest = target / name
        try:
            result = unzip_safely(z, dest)
            if result and isinstance(result[0], str) and result[0].startswith("路径穿越"):
                print(f"[REJECT] {z.name}: {result[0]}")
                continue
            total += 1
            print(f"[OK] {z.name} → {dest}（{len(result)} 个文件）")
        except Exception as exc:
            print(f"[FAIL] {z.name}: {exc}")
    print(f"\n共解压 {total} 个 Skill 包 → {target}")


if __name__ == "__main__":
    main()
