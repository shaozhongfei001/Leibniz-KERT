#!/usr/bin/env python3
"""M2-P5 端到端验收：备份恢复与升级回滚演练（M2.6）。

验收标准：恢复演练报告——真实备份、真实恢复、真实校验，并产出可审计报告。

验证内容：
1. 备份产物落工作区外（落入会破坏 check_workspace）
2. Runtime DB 走 SQLite 在线备份 API（非热文件拷贝）
3. 一致性点捕获（知识版本 ↔ 运行态）
4. 完整性校验可检出篡改与缺失
5. 恢复后工作区可用（check_workspace 零 BLOCKER）
6. 恢复保持 M2.4 语义（attempts 不重置、dead-letter 不清除）
7. 失效锁被排除与清理
8. 损坏备份被拒绝恢复（避免覆盖现场）
9. 灾难场景：源工作区被摧毁后可完整恢复
10. 发布清单含 git 锚点（治理文档登记的缺失项）
11. 清单比对可识别升级/回滚差异
12. RTO 观测（仅记录实测耗时，不宣称达标）

用法：
    python scripts/verify_m2p5_backup_restore.py [--out evidence/m2-p5]
"""

from __future__ import annotations

import argparse
import json
import platform
import shutil
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def _log(report: dict, name: str, passed: bool, detail: str) -> None:
    """记录一条检查结果。"""
    report["checks"].append({"name": name, "passed": bool(passed), "detail": detail})
    print(f"[{'PASS' if passed else 'FAIL'}] {name} :: {detail}", flush=True)


def _build_workspace(root: Path) -> Path:
    """构造含真实内容与运行态的工作区。"""
    from dkws.domain import workspace as ws_mod
    from dkws.infrastructure.runtime_store import RuntimeStore

    if root.exists():
        shutil.rmtree(root)
    ws_mod.init_workspace(root)

    (root / "01_raw" / "batch=20260827").mkdir(parents=True)
    for idx in range(5):
        (root / "01_raw" / "batch=20260827" / f"part_{idx}.csv").write_text(
            f"id,value\n{idx},{idx * 10}\n", encoding="utf-8")

    version = "2026.08.27.1"
    core_dir = root / "03_core" / "product_knowledge" / f"version={version}"
    core_dir.mkdir(parents=True)
    (core_dir / "knowledge_item.md").write_text("# 知识条目\n", encoding="utf-8")

    serve_dir = root / "04_serve" / "product_knowledge"
    serve_dir.mkdir(parents=True)
    (serve_dir / f"version={version}").mkdir()
    (serve_dir / "CURRENT.md").write_text(
        f'---\ntarget_version: "{version}"\n---\n# CURRENT\n', encoding="utf-8")

    lock_dir = root / "90_control" / "locks"
    lock_dir.mkdir(parents=True, exist_ok=True)
    (lock_dir / "ingest.lock").write_text('{"pid": 99999, "host": "old-host"}',
                                          encoding="utf-8")

    store = RuntimeStore(root / "90_control" / "runtime" / "runtime.db")
    store.create_job("JOB-DRILL-DONE", "SKILL", {"n": 1}, max_attempts=3)
    store.create_job("JOB-DRILL-DEAD", "SKILL", max_attempts=1)
    store.create_job("JOB-DRILL-PENDING", "SKILL", {"n": 3}, max_attempts=3)
    first = store.claim_job("w-drill", job_types=["SKILL"])
    store.complete_job(first.job_id, "w-drill", {"done": True})
    second = store.claim_job("w-drill", job_types=["SKILL"])
    store.fail_job(second.job_id, "w-drill", error_message="注入失败以造 dead-letter")
    return root


def check_backup(report: dict, ws: Path, dest: Path) -> tuple[Path, dict]:
    """场景 1-3：备份产生与范围。"""
    from dkws.domain.errors import ConflictError
    from dkws.infrastructure.backup import create_backup

    try:
        create_backup(ws, ws / "inner-backup")
        rejected = False
    except ConflictError:
        rejected = True
    _log(report, "backup_rejects_dest_inside_workspace", rejected,
         "备份目标落工作区内被拒绝（否则触发 WS_BAD_FILENAME 破坏一致性检查）")

    started = time.monotonic()
    root, manifest = create_backup(ws, dest, backup_id="drill-001",
                                   service_version="m2p5-drill")
    elapsed = time.monotonic() - started

    _log(report, "backup_created",
         root.is_dir() and len(manifest.files) > 0,
         f"备份集={root.name} 文件数={len(manifest.files)} "
         f"字节={manifest.total_bytes} 耗时={elapsed:.3f}s")

    db = manifest.runtime_db
    _log(report, "backup_db_uses_online_api",
         db.get("present") and db.get("method") == "sqlite_online_backup",
         f"Runtime DB 经 {db.get('method')} 生成快照（schema={db.get('schema_version')}），"
         f"未直接拷贝 WAL 热文件")

    point = manifest.consistency_point
    _log(report, "backup_captures_consistency_point",
         bool(point.get("current_pointers")) and bool(point.get("core_versions"))
         and point.get("runtime_schema_version") is not None,
         f"一致性点：CURRENT={point.get('current_pointers')} "
         f"core={list(point.get('core_versions') or {})} "
         f"db_schema={point.get('runtime_schema_version')}")

    payload = root / "payload"
    _log(report, "backup_excludes_stale_locks",
         not (payload / "90_control" / "locks" / "ingest.lock").exists(),
         "失效锁被排除（锁含 pid/host，恢复到新主机必然失效）")

    _log(report, "backup_includes_marker",
         (payload / ".dkws_workspace").is_file(),
         "工作区标记已备份（缺失会导致恢复后所有命令拒绝执行）")

    report["backup_elapsed_seconds"] = round(elapsed, 3)
    return root, manifest.as_dict()


def check_verify(report: dict, root: Path, dest: Path, ws: Path) -> None:
    """场景 4：完整性校验。"""
    from dkws.infrastructure.backup import create_backup, verify_backup

    _log(report, "verify_passes_on_intact", verify_backup(root) == [],
         "完整备份逐文件 sha256 比对通过")

    tampered_root, _ = create_backup(ws, dest, backup_id="drill-tampered")
    victim = tampered_root / "payload" / "01_raw" / "batch=20260827" / "part_0.csv"
    victim.write_text("TAMPERED", encoding="utf-8")
    problems = verify_backup(tampered_root)
    _log(report, "verify_detects_tampering",
         any("哈希不匹配" in p for p in problems),
         f"篡改被检出：{problems[:1]}")

    missing_root, _ = create_backup(ws, dest, backup_id="drill-missing")
    (missing_root / "payload" / "01_raw" / "batch=20260827" / "part_1.csv").unlink()
    _log(report, "verify_detects_missing",
         any("文件缺失" in p for p in verify_backup(missing_root)),
         "文件缺失被检出")

    report["_tampered_root"] = str(tampered_root)


def check_restore(report: dict, root: Path, target: Path) -> None:
    """场景 5-7、12：恢复与 RTO 观测。"""
    from dkws.domain import workspace as ws_mod
    from dkws.infrastructure.backup import restore_backup
    from dkws.infrastructure.runtime_store import RuntimeStore

    if target.exists():
        shutil.rmtree(target)
    lock_dir = target / "90_control" / "locks"
    lock_dir.mkdir(parents=True)
    (lock_dir / "residual.lock").write_text('{"pid": 1}', encoding="utf-8")

    started = time.monotonic()
    result = restore_backup(root, target, force=True)
    elapsed = time.monotonic() - started

    _log(report, "restore_completed",
         result.restored_files > 0,
         f"恢复文件数={result.restored_files} 耗时={elapsed:.3f}s")

    _log(report, "restore_workspace_usable",
         ws_mod.is_workspace(target) and result.ok,
         f"恢复后 is_workspace=True，BLOCKER 数={len(result.blockers)}")

    findings = ws_mod.check_workspace(target, mode="full")
    _log(report, "restore_structure_check_clean",
         findings == [],
         f"check_workspace(full) 结果={findings or '无问题'}")

    _log(report, "restore_consistency_matched",
         result.consistency.get("matched") is True,
         f"一致性校验匹配={result.consistency.get('matched')}，"
         f"不匹配项={result.consistency.get('mismatches') or '无'}")

    _log(report, "restore_clears_residual_locks",
         result.cleared_locks >= 1
         and not (lock_dir / "residual.lock").exists(),
         f"清理残留锁 {result.cleared_locks} 个")

    store = RuntimeStore(target / "90_control" / "runtime" / "runtime.db")
    done = store.get_job("JOB-DRILL-DONE")
    dead = store.get_job("JOB-DRILL-DEAD")
    pending = store.get_job("JOB-DRILL-PENDING")
    _log(report, "restore_preserves_m24_semantics",
         done.status == "COMPLETED" and dead.dead_letter is True
         and dead.attempts == 1 and pending.status == "PENDING",
         f"COMPLETED 保持、dead_letter 保持（attempts={dead.attempts} 未重置）、"
         f"PENDING 保持")

    _log(report, "restore_dead_letter_not_reclaimed",
         store.claim_job("w-after-restore", job_types=["SKILL"]).job_id
         == "JOB-DRILL-PENDING",
         "恢复后 dead-letter 不被误领取，仅 PENDING 可领")

    raw = (target / "01_raw" / "batch=20260827" / "part_0.csv").read_text(
        encoding="utf-8")
    _log(report, "restore_data_byte_identical", raw == "id,value\n0,0\n",
         "原始数据逐字节一致")

    report["restore_elapsed_seconds"] = round(elapsed, 3)


def check_corrupted_refused(report: dict, tampered_root: Path, tmp: Path) -> None:
    """场景 8：损坏备份被拒绝。"""
    from dkws.domain.errors import ConflictError
    from dkws.infrastructure.backup import restore_backup

    try:
        restore_backup(tampered_root, tmp / "should-not-exist")
        refused = False
        detail = "未拒绝损坏备份"
    except ConflictError as exc:
        refused = True
        detail = f"拒绝理由：{str(exc)[:64]}…"
    _log(report, "restore_refuses_corrupted_backup", refused,
         f"损坏备份被拒绝恢复，避免覆盖现场（{detail}）")


def check_disaster_recovery(report: dict, ws: Path, root: Path) -> None:
    """场景 9：灾难演练——源工作区被摧毁后恢复。"""
    from dkws.domain import workspace as ws_mod
    from dkws.infrastructure.backup import restore_backup
    from dkws.infrastructure.runtime_store import RuntimeStore

    shutil.rmtree(ws)
    destroyed = not ws.exists()

    started = time.monotonic()
    result = restore_backup(root, ws, force=True)
    elapsed = time.monotonic() - started

    store = RuntimeStore(ws / "90_control" / "runtime" / "runtime.db")
    recovered = (ws_mod.is_workspace(ws)
                 and ws_mod.check_workspace(ws, mode="full") == []
                 and store.get_job("JOB-DRILL-DEAD").dead_letter is True)
    _log(report, "disaster_recovery_from_scratch",
         destroyed and recovered and result.ok,
         f"源工作区完全删除后从备份恢复：文件数={result.restored_files} "
         f"耗时={elapsed:.3f}s，结构检查与运行态均完整")
    report["disaster_recovery_seconds"] = round(elapsed, 3)


def check_release_manifest(report: dict, out_dir: Path) -> None:
    """场景 10-11：发布清单与比对。"""
    from dkws.infrastructure.release import (
        build_release_manifest,
        compare_manifests,
        write_release_manifest,
    )

    dest, manifest = write_release_manifest(
        REPO, out_dir / "RELEASE_MANIFEST.json")
    git = manifest.git
    _log(report, "release_manifest_has_git_anchor",
         git.get("available") is True and len(git.get("commit", "")) == 40,
         f"git 锚点已补齐（治理文档原登记 dkws_git_commit_anchor=null）："
         f"commit={git.get('short_commit')} branch={git.get('branch')} "
         f"dirty={git.get('dirty')}")

    _log(report, "release_manifest_components",
         all(info.get("present") for info in manifest.components.values()),
         f"组件哈希齐备：{sorted(manifest.components)}")

    _log(report, "release_manifest_records_version_spread",
         any("版本号在代码中分散" in n for n in manifest.notes),
         f"如实记录版本分散：{manifest.versions}")

    left = json.loads(dest.read_text(encoding="utf-8"))
    right = dict(left)
    right["components"] = dict(left["components"])
    right["components"]["python_source"] = {"content_sha256": "changed"}
    right["versions"] = dict(left["versions"], package="9.9.9")
    diff = compare_manifests(left, right)
    _log(report, "release_manifest_compare_detects_diff",
         "python_source" in diff["component_diff"]
         and "package" in diff["version_diff"],
         f"比对识别差异：组件={list(diff['component_diff'])} "
         f"版本={list(diff['version_diff'])}")

    same = compare_manifests(left, left)
    _log(report, "release_manifest_compare_identical",
         same["same_commit"] and same["same_fingerprint"]
         and not same["component_diff"],
         "同一清单比对无差异")

    baseline = build_release_manifest(REPO)
    _log(report, "release_fingerprint_stable",
         baseline.fingerprint() == build_release_manifest(REPO).fingerprint(),
         f"发布指纹稳定：{baseline.fingerprint()[:20]}…")


def main() -> int:
    """执行演练并写出报告。"""
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(REPO / "evidence" / "m2-p5"))
    ap.add_argument("--tmp", default="/tmp/dkws-m2p5-drill")
    args = ap.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp = Path(args.tmp)
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)

    report: dict = {
        "task_package": "M2-P5",
        "scope": "M2.6 备份恢复与升级回滚",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "environment": {"python": sys.version.split()[0],
                        "platform": platform.platform()},
        "checks": [],
    }

    ws = _build_workspace(tmp / "workspace")
    dest = tmp / "backups"

    root, manifest_dict = check_backup(report, ws, dest)
    check_verify(report, root, dest, ws)
    check_restore(report, root, tmp / "restored")
    check_corrupted_refused(report, Path(report.pop("_tampered_root")), tmp)
    check_disaster_recovery(report, ws, root)
    check_release_manifest(report, out_dir)

    report["backup_manifest_excerpt"] = {
        "backup_id": manifest_dict["backup_id"],
        "file_count": manifest_dict["file_count"],
        "included_dirs": manifest_dict["included_dirs"],
        "consistency_point": manifest_dict["consistency_point"],
        "runtime_db": {k: v for k, v in manifest_dict["runtime_db"].items()
                       if k != "stats"},
        "notes": manifest_dict["notes"],
    }
    report["timing_note"] = (
        "上述耗时为本机小规模演练实测值，仅作观测记录。"
        "RPO/RTO 目标属 Owner 决策，本报告不宣称满足任何具体指标。")

    passed = sum(1 for c in report["checks"] if c["passed"])
    total = len(report["checks"])
    report["summary"] = {"passed": passed, "total": total,
                         "result": "PASS" if passed == total else "FAIL"}
    (out_dir / "e2e_backup_restore_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n=== {passed}/{total} 项检查通过 → {report['summary']['result']} ===")
    print(f"报告：{out_dir / 'e2e_backup_restore_report.json'}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
