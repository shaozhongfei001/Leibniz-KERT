#!/usr/bin/env python3
"""DKWS 备份 / 恢复 / 发布清单运维工具（M2.6）。

子命令：
    backup    创建工作区备份（含 Runtime DB 在线快照与一致性点）
    verify    校验备份集完整性（逐文件 sha256 比对）
    restore   从备份集恢复到目标目录，并做一致性与结构检查
    manifest  生成发布清单（git 锚点 + 版本汇总 + 组件哈希）
    compare   比对两份发布清单，用于升级/回滚前确认差异

用法示例::

    # 备份（目标必须在工作区外）
    python scripts/dkws_ops.py backup --workspace ./workspace --dest /var/backups/dkws

    # 校验
    python scripts/dkws_ops.py verify --backup /var/backups/dkws/backup-20260827T120000Z

    # 恢复（演练建议恢复到新目录，勿直接覆盖生产）
    python scripts/dkws_ops.py restore \
        --backup /var/backups/dkws/backup-20260827T120000Z \
        --target /tmp/restore-drill

    # 发布清单
    python scripts/dkws_ops.py manifest --out evidence/release/RELEASE_MANIFEST.json

    # 升级/回滚前比对
    python scripts/dkws_ops.py compare --left old.json --right new.json

注意：本工具不设定 RPO/RTO，也不内置备份频率与保留策略——
这些属 Owner 决策，应由运维侧在调度层（cron/systemd timer）配置。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))


def cmd_backup(args: argparse.Namespace) -> int:
    """创建备份。"""
    from dkws.domain.errors import DKWSException
    from dkws.infrastructure.backup import create_backup

    try:
        path, manifest = create_backup(
            Path(args.workspace), Path(args.dest),
            backup_id=args.backup_id,
            include_optional=not args.required_only,
            exclude_dirs=tuple(args.exclude or ()),
            service_version=args.service_version,
            archive=args.archive)
    except DKWSException as exc:
        print(f"[backup] 失败：{exc}", file=sys.stderr)
        return 1

    print(f"[backup] 备份集：{path}")
    print(f"[backup] 文件数：{len(manifest.files)}，"
          f"总字节：{manifest.total_bytes}")
    print(f"[backup] 包含目录：{sorted(manifest.included_dirs)}")
    print(f"[backup] 排除目录：{sorted(manifest.excluded_dirs)}")
    db = manifest.runtime_db
    if db.get("present"):
        print(f"[backup] Runtime DB：schema={db.get('schema_version')} "
              f"方式={db.get('method')} 字节={db.get('size')}")
    else:
        print(f"[backup] Runtime DB：{db.get('note')}")
    point = manifest.consistency_point
    print(f"[backup] 一致性点：CURRENT={point.get('current_pointers')} "
          f"core={point.get('core_versions')}")
    for note in manifest.notes:
        print(f"[backup][note] {note}")
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    """校验备份集完整性。"""
    from dkws.infrastructure.backup import verify_backup

    problems = verify_backup(Path(args.backup))
    if problems:
        print(f"[verify] 发现 {len(problems)} 个问题：", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    print("[verify] 备份集完整性校验通过（逐文件 sha256 比对一致）")
    return 0


def cmd_restore(args: argparse.Namespace) -> int:
    """从备份集恢复。"""
    from dkws.domain.errors import DKWSException
    from dkws.infrastructure.backup import restore_backup

    try:
        result = restore_backup(Path(args.backup), Path(args.target),
                                force=args.force,
                                verify_first=not args.skip_verify)
    except DKWSException as exc:
        print(f"[restore] 失败：{exc}", file=sys.stderr)
        return 1

    print(f"[restore] 目标：{result.target}")
    print(f"[restore] 恢复文件数：{result.restored_files}")
    print(f"[restore] 清理残留锁：{result.cleared_locks}")
    consistency = result.consistency
    if consistency.get("matched"):
        print("[restore] 一致性校验：匹配（知识版本 ↔ 运行态一致）")
    else:
        print("[restore] 一致性校验：不匹配", file=sys.stderr)
        for item in consistency.get("mismatches") or []:
            print(f"  - {item}", file=sys.stderr)
    for warning in result.warnings:
        print(f"[restore][warn] {warning}", file=sys.stderr)
    if result.findings:
        print(f"[restore] 结构检查发现 {len(result.findings)} 项：")
        for finding in result.findings[:20]:
            print(f"  - {finding}")
    if not result.ok:
        print(f"[restore] 存在 {len(result.blockers)} 个 BLOCKER，"
              f"恢复后工作区未达可用状态", file=sys.stderr)
        return 1
    print("[restore] 完成：无 BLOCKER 级问题")
    return 0


def cmd_manifest(args: argparse.Namespace) -> int:
    """生成发布清单。"""
    from dkws.infrastructure.release import write_release_manifest

    dest, manifest = write_release_manifest(REPO, Path(args.out),
                                            release_id=args.release_id)
    print(f"[manifest] 已写出：{dest}")
    print(f"[manifest] release_id={manifest.release_id}")
    git = manifest.git
    if git.get("available"):
        print(f"[manifest] git commit={git.get('short_commit')} "
              f"branch={git.get('branch')} dirty={git.get('dirty')}")
    else:
        print(f"[manifest] git：{git.get('note')}", file=sys.stderr)
    print(f"[manifest] fingerprint={manifest.fingerprint()[:24]}…")
    for note in manifest.notes:
        print(f"[manifest][note] {note}")
    # dirty 工作区不应用于生产发布，以非零码提示（可用 --allow-dirty 放行）
    if git.get("dirty") and not args.allow_dirty:
        print("[manifest] 工作区有未提交变更；如确认可接受请加 --allow-dirty",
              file=sys.stderr)
        return 2
    return 0


def cmd_compare(args: argparse.Namespace) -> int:
    """比对两份发布清单。"""
    from dkws.infrastructure.release import compare_manifests

    left = json.loads(Path(args.left).read_text(encoding="utf-8"))
    right = json.loads(Path(args.right).read_text(encoding="utf-8"))
    diff = compare_manifests(left, right)
    print(f"[compare] 同一 commit：{diff['same_commit']}")
    print(f"[compare] 同一指纹：{diff['same_fingerprint']}")
    if diff["version_diff"]:
        print("[compare] 版本差异：")
        for key, change in diff["version_diff"].items():
            print(f"  {key}: {change['from']} → {change['to']}")
    if diff["component_diff"]:
        print("[compare] 组件差异：")
        for name, change in diff["component_diff"].items():
            print(f"  {name}: {str(change['from'])[:12]} → {str(change['to'])[:12]}")
    if not diff["version_diff"] and not diff["component_diff"]:
        print("[compare] 无差异")
    return 0


def build_parser() -> argparse.ArgumentParser:
    """构造命令行解析器。"""
    ap = argparse.ArgumentParser(description="DKWS 备份/恢复/发布清单工具")
    sub = ap.add_subparsers(dest="command", required=True)

    p_backup = sub.add_parser("backup", help="创建工作区备份")
    p_backup.add_argument("--workspace", required=True, help="源工作区")
    p_backup.add_argument("--dest", required=True,
                          help="备份输出根目录（必须在工作区之外）")
    p_backup.add_argument("--backup-id", default=None, help="备份标识")
    p_backup.add_argument("--required-only", action="store_true",
                          help="仅备份不可重建目录（01_raw/03_core/90_control）")
    p_backup.add_argument("--exclude", action="append", default=None,
                          help="额外排除的顶层目录，可重复")
    p_backup.add_argument("--service-version", default="", help="记入清单的版本")
    p_backup.add_argument("--archive", action="store_true", help="额外打包 tar.gz")
    p_backup.set_defaults(func=cmd_backup)

    p_verify = sub.add_parser("verify", help="校验备份集完整性")
    p_verify.add_argument("--backup", required=True, help="备份集目录")
    p_verify.set_defaults(func=cmd_verify)

    p_restore = sub.add_parser("restore", help="从备份集恢复")
    p_restore.add_argument("--backup", required=True, help="备份集目录")
    p_restore.add_argument("--target", required=True, help="恢复目标目录")
    p_restore.add_argument("--force", action="store_true", help="目标非空时覆盖")
    p_restore.add_argument("--skip-verify", action="store_true",
                           help="跳过恢复前完整性校验（不建议）")
    p_restore.set_defaults(func=cmd_restore)

    p_manifest = sub.add_parser("manifest", help="生成发布清单")
    p_manifest.add_argument("--out", required=True, help="输出路径")
    p_manifest.add_argument("--release-id", default=None, help="发布标识")
    p_manifest.add_argument("--allow-dirty", action="store_true",
                            help="允许工作区存在未提交变更")
    p_manifest.set_defaults(func=cmd_manifest)

    p_compare = sub.add_parser("compare", help="比对两份发布清单")
    p_compare.add_argument("--left", required=True, help="旧清单")
    p_compare.add_argument("--right", required=True, help="新清单")
    p_compare.set_defaults(func=cmd_compare)
    return ap


def main() -> int:
    """入口。"""
    args = build_parser().parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
