"""M2.6 备份与恢复单元测试。"""

from __future__ import annotations

import json
import shutil
import tarfile

import pytest

from dkws.domain import workspace as ws_mod
from dkws.domain.errors import ConflictError, UsageError
from dkws.infrastructure.backup import (
    EXCLUDE_PATTERNS,
    MANIFEST_NAME,
    OPTIONAL_DIRS,
    PAYLOAD_DIR,
    REQUIRED_DIRS,
    RUNTIME_DB_REL,
    WORKSPACE_MARKER,
    BackupManifest,
    capture_consistency_point,
    create_backup,
    load_manifest,
    restore_backup,
    verify_backup,
    verify_consistency,
)
from dkws.infrastructure.runtime_store import RuntimeStore


@pytest.fixture()
def src_ws(tmp_path):
    """构造含真实内容的源工作区。"""
    ws = tmp_path / "ws"
    ws_mod.init_workspace(ws)
    (ws / "01_raw" / "batch=001").mkdir(parents=True)
    (ws / "01_raw" / "batch=001" / "data.csv").write_text("a,b\n1,2\n",
                                                          encoding="utf-8")
    (ws / "03_core" / "product_knowledge" / "version=2026.08.27.1").mkdir(parents=True)
    (ws / "03_core" / "product_knowledge" / "version=2026.08.27.1" / "ki.md").write_text(
        "# ki\n", encoding="utf-8")
    (ws / "04_serve" / "product_knowledge").mkdir(parents=True)
    # CURRENT 指向的版本目录必须真实存在，否则 check_workspace 报
    # WS_DANGLING_CURRENT（BLOCKER）
    (ws / "04_serve" / "product_knowledge" / "version=2026.08.27.1").mkdir()
    (ws / "04_serve" / "product_knowledge" / "CURRENT.md").write_text(
        '---\ntarget_version: "2026.08.27.1"\n---\n# CURRENT\n', encoding="utf-8")
    return ws


@pytest.fixture()
def dest(tmp_path):
    """备份输出目录（工作区之外）。"""
    return tmp_path / "backups"


def _add_store(ws) -> RuntimeStore:
    """在工作区内建立 Runtime Store 并写入若干 Job。"""
    store = RuntimeStore(ws / RUNTIME_DB_REL)
    store.create_job("JOB-A", "SKILL", {"v": 1}, max_attempts=3)
    store.create_job("JOB-B", "SKILL", max_attempts=1)
    return store


class TestBackupScope:
    """备份范围与排除规则。"""

    def test_required_dirs_are_unrebuildable(self):
        """必备目录为不可重建者。"""
        assert set(REQUIRED_DIRS) == {"01_raw", "03_core", "90_control"}

    def test_optional_dirs_included_by_default(self, src_ws, dest):
        """可重建目录默认纳入：04_serve 数据集重建依赖 02_work 中间产物。"""
        _, manifest = create_backup(src_ws, dest)
        assert set(OPTIONAL_DIRS) <= set(manifest.included_dirs)

    def test_required_only_excludes_optional(self, src_ws, dest):
        """仅备份不可重建目录时排除可选项。"""
        _, manifest = create_backup(src_ws, dest, include_optional=False)
        assert set(manifest.included_dirs) == set(REQUIRED_DIRS)
        assert set(manifest.excluded_dirs) == set(OPTIONAL_DIRS)

    def test_explicit_exclude(self, src_ws, dest):
        """可显式排除顶层目录。"""
        _, manifest = create_backup(src_ws, dest, exclude_dirs=("01_raw",))
        assert "01_raw" not in manifest.included_dirs

    def test_locks_excluded(self, src_ws, dest):
        """锁目录被排除：锁含 pid/host，恢复后必然失效。"""
        lock_dir = src_ws / "90_control" / "locks"
        lock_dir.mkdir(parents=True, exist_ok=True)
        (lock_dir / "x.lock").write_text('{"pid":1}', encoding="utf-8")
        root, _ = create_backup(src_ws, dest)
        assert not (root / PAYLOAD_DIR / "90_control" / "locks" / "x.lock").exists()

    def test_runtime_dir_excluded_from_file_copy(self):
        """runtime 目录不走文件拷贝（避免 WAL 热文件不一致）。"""
        assert any("90_control/runtime" in p for p in EXCLUDE_PATTERNS)

    def test_marker_backed_up(self, src_ws, dest):
        """工作区标记被备份：缺失会导致恢复后所有命令拒绝执行。"""
        root, manifest = create_backup(src_ws, dest)
        assert (root / PAYLOAD_DIR / WORKSPACE_MARKER).is_file()
        assert WORKSPACE_MARKER in manifest.files

    def test_file_content_preserved(self, src_ws, dest):
        """文件内容逐字节保留。"""
        root, _ = create_backup(src_ws, dest)
        copied = root / PAYLOAD_DIR / "01_raw" / "batch=001" / "data.csv"
        assert copied.read_text(encoding="utf-8") == "a,b\n1,2\n"


class TestBackupTargetValidation:
    """备份目标合法性。"""

    def test_rejects_non_workspace(self, tmp_path, dest):
        """非工作区拒绝备份。"""
        with pytest.raises(UsageError, match="不是已初始化"):
            create_backup(tmp_path / "empty", dest)

    def test_rejects_dest_inside_workspace(self, src_ws):
        """备份目标不得位于工作区内（会污染一致性检查）。"""
        with pytest.raises(ConflictError, match="不得位于工作区内"):
            create_backup(src_ws, src_ws / "backups")

    def test_rejects_dest_equal_workspace(self, src_ws):
        """目标不得为工作区本身。"""
        with pytest.raises(ConflictError):
            create_backup(src_ws, src_ws)

    def test_rejects_duplicate_backup_id(self, src_ws, dest):
        """同一 backup_id 不可重复创建，避免覆盖已有备份。"""
        create_backup(src_ws, dest, backup_id="dup")
        with pytest.raises(ConflictError, match="已存在"):
            create_backup(src_ws, dest, backup_id="dup")


class TestRuntimeDbBackup:
    """Runtime DB 在线备份。"""

    def test_uses_online_backup_api(self, src_ws, dest):
        """DB 走 SQLite 在线备份 API 而非文件拷贝。"""
        _add_store(src_ws)
        _, manifest = create_backup(src_ws, dest)
        assert manifest.runtime_db["method"] == "sqlite_online_backup"
        assert manifest.runtime_db["present"] is True

    def test_snapshot_readable(self, src_ws, dest):
        """DB 快照可被打开且内容完整。"""
        _add_store(src_ws)
        root, _ = create_backup(src_ws, dest)
        snap = RuntimeStore(root / PAYLOAD_DIR / RUNTIME_DB_REL)
        assert snap.get_job("JOB-A").payload == {"v": 1}
        assert snap.schema_version() == 2

    def test_snapshot_captures_latest_state(self, src_ws, dest):
        """快照反映备份时刻的最新状态，含 dead-letter。"""
        store = _add_store(src_ws)
        store.claim_job("w1", job_types=["SKILL"])
        store.complete_job("JOB-A", "w1", {"done": True})
        claimed = store.claim_job("w1", job_types=["SKILL"])
        store.fail_job(claimed.job_id, "w1", error_message="boom")

        root, _ = create_backup(src_ws, dest)
        snap = RuntimeStore(root / PAYLOAD_DIR / RUNTIME_DB_REL)
        assert snap.get_job("JOB-A").status == "COMPLETED"
        assert snap.get_job("JOB-B").dead_letter is True

    def test_absent_db_recorded(self, src_ws, dest):
        """未启用 Store 时明确记录，不报错。"""
        _, manifest = create_backup(src_ws, dest)
        assert manifest.runtime_db["present"] is False
        assert "未启用" in manifest.runtime_db["note"]


class TestConsistencyPoint:
    """一致性点捕获。"""

    def test_captures_current_pointers(self, src_ws):
        """捕获 CURRENT.md 的 target_version。"""
        point = capture_consistency_point(src_ws)
        assert point["current_pointers"]["product_knowledge"] == "2026.08.27.1"

    def test_captures_core_versions(self, src_ws):
        """捕获 03_core 版本目录清单。"""
        point = capture_consistency_point(src_ws)
        assert point["core_versions"]["product_knowledge"] == ["version=2026.08.27.1"]

    def test_captures_runtime_schema(self, src_ws):
        """捕获 Runtime DB schema 版本。"""
        _add_store(src_ws)
        assert capture_consistency_point(src_ws)["runtime_schema_version"] == 2

    def test_none_schema_without_db(self, src_ws):
        """无 DB 时 schema 为 None。"""
        assert capture_consistency_point(src_ws)["runtime_schema_version"] is None

    def test_included_in_manifest(self, src_ws, dest):
        """一致性点写入 manifest。"""
        _, manifest = create_backup(src_ws, dest)
        assert "current_pointers" in manifest.consistency_point
        assert "captured_at" in manifest.consistency_point


class TestManifestAndVerify:
    """清单结构与完整性校验。"""

    def test_manifest_written(self, src_ws, dest):
        """manifest 落盘且可解析。"""
        root, _ = create_backup(src_ws, dest)
        data = json.loads((root / MANIFEST_NAME).read_text(encoding="utf-8"))
        assert data["schema"] == "dkws_backup_manifest/v1"

    def test_manifest_has_notes(self, src_ws, dest):
        """manifest 含非声明与说明事项。"""
        _, manifest = create_backup(src_ws, dest)
        joined = " ".join(manifest.notes)
        assert "不代表已通过灾备演练验收" in joined
        assert "RPO/RTO" in joined

    def test_manifest_records_hashes(self, src_ws, dest):
        """每个文件记录 sha256 与大小。"""
        _, manifest = create_backup(src_ws, dest)
        for info in manifest.files.values():
            assert len(info["sha256"]) == 64
            assert info["size"] >= 0

    def test_total_bytes(self, src_ws, dest):
        """可统计总字节数。"""
        _, manifest = create_backup(src_ws, dest)
        assert manifest.total_bytes > 0

    def test_verify_passes_on_intact_backup(self, src_ws, dest):
        """完整备份校验通过。"""
        _add_store(src_ws)
        root, _ = create_backup(src_ws, dest)
        assert verify_backup(root) == []

    def test_verify_detects_missing_file(self, src_ws, dest):
        """检测文件缺失。"""
        root, _ = create_backup(src_ws, dest)
        (root / PAYLOAD_DIR / "01_raw" / "batch=001" / "data.csv").unlink()
        assert any("文件缺失" in p for p in verify_backup(root))

    def test_verify_detects_tampering(self, src_ws, dest):
        """检测内容被篡改。"""
        root, _ = create_backup(src_ws, dest)
        (root / PAYLOAD_DIR / "01_raw" / "batch=001" / "data.csv").write_text(
            "tampered", encoding="utf-8")
        assert any("哈希不匹配" in p for p in verify_backup(root))

    def test_verify_detects_db_tampering(self, src_ws, dest):
        """检测 DB 快照被篡改。"""
        _add_store(src_ws)
        root, _ = create_backup(src_ws, dest)
        (root / PAYLOAD_DIR / RUNTIME_DB_REL).write_bytes(b"corrupted")
        assert any("Runtime DB" in p for p in verify_backup(root))

    def test_verify_missing_manifest(self, tmp_path):
        """缺少清单时报告。"""
        assert any("缺少清单" in p for p in verify_backup(tmp_path))

    def test_load_manifest_missing_raises(self, tmp_path):
        """读取不存在的清单抛错。"""
        with pytest.raises(UsageError, match="缺少清单"):
            load_manifest(tmp_path)

    def test_archive_creates_tarball(self, src_ws, dest):
        """archive=True 生成可解压的 tar.gz。"""
        path, _ = create_backup(src_ws, dest, backup_id="arc", archive=True)
        assert path.suffix == ".gz"
        with tarfile.open(path) as tar:
            assert any(m.name.endswith(MANIFEST_NAME) for m in tar.getmembers())


class TestRestore:
    """恢复流程。"""

    def test_restore_to_new_dir(self, src_ws, dest, tmp_path):
        """恢复到空目录成功。"""
        _add_store(src_ws)
        root, _ = create_backup(src_ws, dest)
        result = restore_backup(root, tmp_path / "restored")
        assert result.restored_files > 0
        assert result.ok is True

    def test_restored_workspace_is_usable(self, src_ws, dest, tmp_path):
        """恢复后工作区可用且结构检查无问题。"""
        _add_store(src_ws)
        root, _ = create_backup(src_ws, dest)
        target = tmp_path / "restored"
        restore_backup(root, target)
        assert ws_mod.is_workspace(target)
        assert ws_mod.check_workspace(target, mode="full") == []

    def test_restored_data_matches(self, src_ws, dest, tmp_path):
        """原始数据逐字节一致。"""
        root, _ = create_backup(src_ws, dest)
        target = tmp_path / "restored"
        restore_backup(root, target)
        assert (target / "01_raw" / "batch=001" / "data.csv").read_text(
            encoding="utf-8") == "a,b\n1,2\n"

    def test_restored_db_preserves_m24_semantics(self, src_ws, dest, tmp_path):
        """恢复不重置 attempts、不清除 dead_letter（受 tests/recovery 锁定）。"""
        store = _add_store(src_ws)
        claimed = store.claim_job("w1", job_types=["SKILL"])
        store.complete_job(claimed.job_id, "w1", {"done": True})
        second = store.claim_job("w1", job_types=["SKILL"])
        store.fail_job(second.job_id, "w1", error_message="boom")

        root, _ = create_backup(src_ws, dest)
        target = tmp_path / "restored"
        restore_backup(root, target)
        snap = RuntimeStore(target / RUNTIME_DB_REL)
        dead = snap.get_job("JOB-B")
        assert dead.dead_letter is True
        assert dead.attempts == 1
        assert snap.claim_job("w-new") is None

    def test_restore_clears_stale_locks(self, src_ws, dest, tmp_path):
        """恢复后清理残留锁（锁含 pid/host，跨主机必然失效）。"""
        root, _ = create_backup(src_ws, dest)
        target = tmp_path / "restored"
        (target / "90_control" / "locks").mkdir(parents=True)
        (target / "90_control" / "locks" / "old.lock").write_text('{"pid":1}',
                                                                 encoding="utf-8")
        result = restore_backup(root, target, force=True)
        assert result.cleared_locks >= 1
        assert not (target / "90_control" / "locks" / "old.lock").exists()

    def test_restore_recreates_all_dirs(self, src_ws, dest, tmp_path):
        """恢复后补齐 init 会创建的全部目录（空目录不被 rglob 捕获）。"""
        root, _ = create_backup(src_ws, dest)
        target = tmp_path / "restored"
        restore_backup(root, target)
        for top in ws_mod.TOP_LEVEL_DIRS:
            assert (target / top).is_dir()
        for sub in ws_mod.CONTROL_SUBDIRS:
            assert (target / "90_control" / sub).is_dir()

    def test_restore_rejects_nonempty_without_force(self, src_ws, dest, tmp_path):
        """目标非空且未指定 force 时拒绝。"""
        root, _ = create_backup(src_ws, dest)
        target = tmp_path / "restored"
        target.mkdir()
        (target / "existing.txt").write_text("x", encoding="utf-8")
        with pytest.raises(ConflictError, match="非空"):
            restore_backup(root, target)

    def test_restore_force_overwrites(self, src_ws, dest, tmp_path):
        """force 允许覆盖非空目标。"""
        root, _ = create_backup(src_ws, dest)
        target = tmp_path / "restored"
        target.mkdir()
        (target / "existing.txt").write_text("x", encoding="utf-8")
        assert restore_backup(root, target, force=True).restored_files > 0

    def test_restore_refuses_corrupted_backup(self, src_ws, dest, tmp_path):
        """损坏的备份被拒绝恢复，避免覆盖现场。"""
        root, _ = create_backup(src_ws, dest)
        (root / PAYLOAD_DIR / "01_raw" / "batch=001" / "data.csv").write_text(
            "corrupt", encoding="utf-8")
        with pytest.raises(ConflictError, match="完整性校验失败"):
            restore_backup(root, tmp_path / "restored")

    def test_restore_skip_verify_allows_corrupted(self, src_ws, dest, tmp_path):
        """显式跳过校验时允许恢复（不建议，但保留能力）。"""
        root, _ = create_backup(src_ws, dest)
        (root / PAYLOAD_DIR / "01_raw" / "batch=001" / "data.csv").write_text(
            "corrupt", encoding="utf-8")
        result = restore_backup(root, tmp_path / "restored", verify_first=False)
        assert result.restored_files > 0

    def test_restore_result_serializable(self, src_ws, dest, tmp_path):
        """恢复结果可序列化，便于写入演练报告。"""
        root, _ = create_backup(src_ws, dest)
        result = restore_backup(root, tmp_path / "restored")
        assert json.dumps(result.as_dict(), ensure_ascii=False)
        assert "blockers" in result.as_dict()


class TestConsistencyVerification:
    """恢复后一致性校验。"""

    def test_matched_after_clean_restore(self, src_ws, dest, tmp_path):
        """干净恢复后一致性匹配。"""
        _add_store(src_ws)
        root, _ = create_backup(src_ws, dest)
        target = tmp_path / "restored"
        restore_backup(root, target)
        result = verify_consistency(target, load_manifest(root))
        assert result["matched"] is True
        assert result["mismatches"] == []

    def test_detects_pointer_mismatch(self, src_ws, dest, tmp_path):
        """检测 CURRENT 指针不一致。"""
        root, _ = create_backup(src_ws, dest)
        target = tmp_path / "restored"
        restore_backup(root, target)
        (target / "04_serve" / "product_knowledge" / "CURRENT.md").write_text(
            '---\ntarget_version: "9999.01.01.1"\n---\n# CURRENT\n', encoding="utf-8")
        result = verify_consistency(target, load_manifest(root))
        assert result["matched"] is False
        assert any("CURRENT 指针不一致" in m for m in result["mismatches"])

    def test_detects_missing_core_version(self, src_ws, dest, tmp_path):
        """检测 03_core 版本缺失。"""
        root, _ = create_backup(src_ws, dest)
        target = tmp_path / "restored"
        restore_backup(root, target)
        shutil.rmtree(target / "03_core" / "product_knowledge" / "version=2026.08.27.1")
        result = verify_consistency(target, load_manifest(root))
        assert any("03_core 版本缺失" in m for m in result["mismatches"])

    def test_reports_expected_and_actual(self, src_ws, dest, tmp_path):
        """报告同时含期望与实际，便于人工判断。"""
        root, _ = create_backup(src_ws, dest)
        target = tmp_path / "restored"
        restore_backup(root, target)
        result = verify_consistency(target, load_manifest(root))
        assert "expected" in result
        assert "actual" in result


class TestBackupManifestDataclass:
    """BackupManifest 结构。"""

    def test_as_dict_schema(self):
        """含 schema 标识便于版本演进。"""
        manifest = BackupManifest(backup_id="b", created_at="t", workspace="/w")
        assert manifest.as_dict()["schema"] == "dkws_backup_manifest/v1"

    def test_file_count_derived(self):
        """file_count 由 files 派生，避免手工维护不一致。"""
        manifest = BackupManifest(backup_id="b", created_at="t", workspace="/w")
        manifest.files = {"a": {"sha256": "x", "size": 1},
                          "b": {"sha256": "y", "size": 2}}
        assert manifest.as_dict()["file_count"] == 2
        assert manifest.total_bytes == 3
