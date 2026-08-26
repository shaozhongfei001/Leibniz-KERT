"""P0 测试：工作区初始化、检查、路径安全、锁。"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from dkws.domain import paths, workspace as ws_mod
from dkws.domain.errors import ConflictError, PathSafetyError, UsageError
from dkws.infrastructure import locks as locks_mod
from dkws.infrastructure.fs import WorkspaceWriter


class TestInit:
    def test_init_creates_five_layers(self, tmp_path):
        r = ws_mod.init_workspace(tmp_path)
        for d in ws_mod.TOP_LEVEL_DIRS:
            assert (tmp_path / d).is_dir(), d
        for sd in ws_mod.CONTROL_SUBDIRS:
            assert (tmp_path / "90_control" / sd).is_dir(), sd
        assert (tmp_path / ws_mod.MARKER_FILE).is_file()
        assert r.already_initialized is False

    def test_init_idempotent(self, tmp_path):
        ws_mod.init_workspace(tmp_path)
        r = ws_mod.init_workspace(tmp_path)
        assert r.already_initialized is True

    def test_init_rejects_nonempty_without_force(self, tmp_path):
        (tmp_path / "some_file.txt").write_text("x", encoding="utf-8")
        with pytest.raises(UsageError):
            ws_mod.init_workspace(tmp_path)

    def test_init_force_allows_nonempty(self, tmp_path):
        (tmp_path / "some_file.txt").write_text("x", encoding="utf-8")
        r = ws_mod.init_workspace(tmp_path, force=True)
        assert r.already_initialized is False
        assert (tmp_path / "01_raw").is_dir()
        # force 不删除既有文件
        assert (tmp_path / "some_file.txt").is_file()


class TestInspect:
    def test_inspect_ok(self, ws):
        data = ws_mod.inspect_workspace(ws)
        assert data["schema"] == ws_mod.MARKER_SCHEMA
        for d in ws_mod.TOP_LEVEL_DIRS:
            assert data[d]["present"] is True
        assert data["current_pointers"] == []
        assert data["stale_locks"] == 0

    def test_inspect_rejects_uninitialized(self, tmp_path):
        tmp_path.mkdir(exist_ok=True)
        with pytest.raises(UsageError):
            ws_mod.inspect_workspace(tmp_path)


class TestCheck:
    def test_check_pass(self, ws):
        assert ws_mod.check_workspace(ws, mode="full") == []

    def test_check_detects_missing_dir(self, ws):
        (ws / "01_raw").rmdir()
        findings = ws_mod.check_workspace(ws, mode="full")
        codes = {f.code for f in findings}
        assert "WS_MISSING_DIR" in codes

    def test_check_detects_bom(self, ws):
        (ws / "90_control" / "schema" / "bad.md").write_bytes(b"\xef\xbb\xbf# x\n")
        findings = ws_mod.check_workspace(ws, mode="fast")
        assert any(f.code == "WS_BOM" for f in findings)

    def test_check_detects_dangling_current(self, ws):
        (ws / "03_core" / "product").mkdir(parents=True)
        (ws / "03_core" / "product" / "CURRENT.md").write_text(
            "---\nschema: current_pointer/v1\ntarget_version: 2026.01.01.1\n---\n\n# x\n",
            encoding="utf-8",
        )
        findings = ws_mod.check_workspace(ws, mode="full")
        assert any(f.code == "WS_DANGLING_CURRENT" for f in findings)


class TestPathSafety:
    def test_traversal_rejected(self, ws):
        with pytest.raises(PathSafetyError):
            paths.resolve_ws_path(ws, "../evil.txt")
        with pytest.raises(PathSafetyError):
            paths.resolve_ws_path(ws, "01_raw/../../etc/passwd")

    def test_absolute_rejected(self, ws):
        with pytest.raises(PathSafetyError):
            paths.resolve_ws_path(ws, "/etc/passwd")

    def test_control_chars_rejected(self, ws):
        with pytest.raises(PathSafetyError):
            paths.resolve_ws_path(ws, "01_raw/\x00bad")

    def test_trailing_space_rejected(self, ws):
        with pytest.raises(PathSafetyError):
            paths.resolve_ws_path(ws, "01_raw/bad ")

    def test_symlink_escape_rejected(self, ws):
        outside = Path("/tmp/dkws_outside_symlink")
        outside.mkdir(exist_ok=True)
        (ws / "01_raw" / "link").symlink_to(outside, target_is_directory=True)
        with pytest.raises(PathSafetyError):
            paths.resolve_ws_path(ws, "01_raw/link/evil.txt")

    def test_normal_path_ok(self, ws):
        p = paths.resolve_ws_path(ws, "01_raw/product/batch=X/file.parquet")
        assert str(p).startswith(str(ws.resolve()))


class TestWriter:
    def test_atomic_write(self, ws):
        w = WorkspaceWriter(ws)
        rel = w.write_text("02_work/product/run=X/a.md", "# 测试\n")
        assert w.read_text(rel) == "# 测试\n"

    def test_rebuildable_delete_guard(self, ws):
        w = WorkspaceWriter(ws)
        w.write_text("02_work/x.txt", "data")
        w.remove_rebuildable_tree("02_work/x.txt")
        assert not w.exists("02_work/x.txt")
        w.write_text("03_core/x.txt", "data")
        with pytest.raises(PathSafetyError):
            w.remove_rebuildable_tree("03_core/x.txt")

    def test_dry_run_writes_nothing(self, ws):
        w = WorkspaceWriter(ws, dry_run=True)
        w.write_text("02_work/x.txt", "data")
        assert not w.exists("02_work/x.txt")


class TestLocks:
    def test_acquire_release(self, ws):
        lk = locks_mod.WorkspaceLock(ws, "product", job_id="JOB-A", owner="tester")
        rel = lk.acquire()
        assert (ws / rel).is_file()
        lk.release()
        assert not (ws / rel).exists()

    def test_conflict(self, ws):
        lk1 = locks_mod.WorkspaceLock(ws, "product", job_id="JOB-A", owner="t")
        lk1.acquire()
        lk2 = locks_mod.WorkspaceLock(ws, "product", job_id="JOB-B", owner="t")
        with pytest.raises(ConflictError):
            lk2.acquire()
        lk1.release()

    def test_expired_lock_requires_recovery(self, ws):
        lk = locks_mod.WorkspaceLock(ws, "product", job_id="JOB-A", owner="t",
                                     ttl_seconds=-1)
        lk.acquire()
        with pytest.raises(ConflictError):
            locks_mod.WorkspaceLock(ws, "product", job_id="JOB-B",
                                    owner="t").acquire()
        stale = locks_mod.list_stale_locks(ws)
        assert len(stale) == 1
        assert stale[0]["job_id"] == "JOB-A"
        # 任务已终止（无 STATUS.md）→ 允许清理
        assert locks_mod.clear_stale_lock(ws, stale[0]["lock_file"])
        lk.release()


class TestHashing:
    def test_md_canonical(self):
        from dkws.domain import hashing

        p1 = hashing.md_semantic_sha256("# x\n\nbody  \ntail  \n")
        p2 = hashing.md_semantic_sha256("# x\n\nbody\ntail\n")
        p3 = hashing.md_semantic_sha256("# x\n\nbody\ntail")  # 末尾无换行
        p4 = hashing.md_semantic_sha256("# x\n\nbody\ntail\n\n\n")  # 多余尾部空行
        assert p1 == p2 == p3 == p4
        # 空行结构不同 → 哈希不同
        q = hashing.md_semantic_sha256("# x\n\nbody\n\ntail\n")
        assert q != p1

    def test_sha256_deterministic(self):
        from dkws.domain import hashing

        assert hashing.sha256_hex("abc") == hashing.sha256_hex("abc")
        assert len(hashing.sha256_hex("abc")) == 64

    def test_parquet_logical_hash_stable(self):
        import pyarrow as pa
        from dkws.domain import hashing

        t1 = pa.table({"a": [1, 2], "b": ["x", "y"]})
        t2 = pa.table({"b": ["x", "y"], "a": [1, 2]})  # 列序不同
        h1 = hashing.parquet_logical_hash(t1, key_columns=["a"])
        h2 = hashing.parquet_logical_hash(t2, key_columns=["a"])
        assert h1 == h2
