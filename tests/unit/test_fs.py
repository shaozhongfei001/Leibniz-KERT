"""fs 模块单元测试：WorkspaceWriter 读写、原子操作、安全约束。"""

from __future__ import annotations

from pathlib import Path

import pytest

from dkws.domain.errors import PathSafetyError, UsageError
from dkws.infrastructure.fs import REBUILDABLE_ROOTS, WorkspaceWriter


@pytest.fixture
def ws(tmp_path):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    return workspace


@pytest.fixture
def writer(ws):
    return WorkspaceWriter(ws)


# ---------- resolve ----------

class TestResolve:
    def test_simple(self, writer, ws):
        p = writer.resolve("data/file.txt")
        assert p == ws / "data" / "file.txt"

    def test_escape_raises(self, writer):
        with pytest.raises(PathSafetyError):
            writer.resolve("../outside")


# ---------- write_text / read_text ----------

class TestWriteReadText:
    def test_roundtrip(self, writer):
        writer.write_text("dir/hello.txt", "你好世界")
        assert writer.read_text("dir/hello.txt") == "你好世界"

    def test_creates_dirs(self, writer, ws):
        writer.write_text("a/b/c.txt", "deep")
        assert (ws / "a" / "b" / "c.txt").exists()

    def test_overwrite(self, writer):
        writer.write_text("f.txt", "v1")
        writer.write_text("f.txt", "v2")
        assert writer.read_text("f.txt") == "v2"

    def test_dry_run(self, ws):
        w = WorkspaceWriter(ws, dry_run=True)
        result = w.write_text("f.txt", "content")
        assert result == "f.txt"
        assert not (ws / "f.txt").exists()

    def test_read_nonexistent_raises(self, writer):
        with pytest.raises(UsageError, match="文件不存在"):
            writer.read_text("nope.txt")


# ---------- write_bytes ----------

class TestWriteBytes:
    def test_roundtrip(self, writer, ws):
        data = b"\x00\x01\x02\xff"
        writer.write_bytes("bin.dat", data)
        assert (ws / "bin.dat").read_bytes() == data

    def test_dry_run(self, ws):
        w = WorkspaceWriter(ws, dry_run=True)
        result = w.write_bytes("bin.dat", b"data")
        assert result == "bin.dat"


# ---------- copy_file ----------

class TestCopyFile:
    def test_copy(self, writer, ws, tmp_path):
        src = tmp_path / "orig.txt"
        src.write_text("original", encoding="utf-8")
        writer.copy_file(src, "copied.txt")
        assert (ws / "copied.txt").read_text(encoding="utf-8") == "original"

    def test_dry_run(self, ws, tmp_path):
        w = WorkspaceWriter(ws, dry_run=True)
        src = tmp_path / "orig.txt"
        src.write_text("x", encoding="utf-8")
        result = w.copy_file(src, "copied.txt")
        assert result == "copied.txt"
        assert not (ws / "copied.txt").exists()


# ---------- mkdirs ----------

class TestMkdirs:
    def test_mkdirs(self, writer, ws):
        writer.mkdirs("deep/nested/dir")
        assert (ws / "deep" / "nested" / "dir").is_dir()

    def test_dry_run(self, ws):
        w = WorkspaceWriter(ws, dry_run=True)
        result = w.mkdirs("deep/nested")
        assert result == "deep/nested"
        assert not (ws / "deep").exists()


# ---------- exists / list_dir ----------

class TestExistsListDir:
    def test_exists_true(self, writer):
        writer.write_text("f.txt", "x")
        assert writer.exists("f.txt") is True

    def test_exists_false(self, writer):
        assert writer.exists("nope.txt") is False

    def test_list_dir(self, writer):
        writer.write_text("dir/a.txt", "a")
        writer.write_text("dir/b.txt", "b")
        assert writer.list_dir("dir") == ["a.txt", "b.txt"]

    def test_list_dir_empty(self, writer):
        writer.mkdirs("empty")
        assert writer.list_dir("empty") == []

    def test_list_dir_nonexistent(self, writer):
        assert writer.list_dir("nope") == []


# ---------- atomic_replace_dir ----------

class TestAtomicReplaceDir:
    def test_replace_no_existing(self, writer, ws):
        (ws / "tmp_v1").mkdir()
        (ws / "tmp_v1" / "f.txt").write_text("v1", encoding="utf-8")
        writer.atomic_replace_dir("tmp_v1", "final")
        assert (ws / "final" / "f.txt").read_text(encoding="utf-8") == "v1"
        assert not (ws / "tmp_v1").exists()

    def test_replace_with_existing(self, writer, ws):
        (ws / "final").mkdir()
        (ws / "final" / "old.txt").write_text("old", encoding="utf-8")
        (ws / "tmp_v2").mkdir()
        (ws / "tmp_v2" / "new.txt").write_text("new", encoding="utf-8")
        writer.atomic_replace_dir("tmp_v2", "final")
        assert (ws / "final" / "new.txt").read_text(encoding="utf-8") == "new"
        assert not (ws / "final" / "old.txt").exists()

    def test_dry_run(self, ws):
        w = WorkspaceWriter(ws, dry_run=True)
        (ws / "tmp").mkdir()
        w.atomic_replace_dir("tmp", "final")  # no-op

    def test_missing_tmp_raises(self, writer):
        with pytest.raises(UsageError, match="临时目录不存在"):
            writer.atomic_replace_dir("nonexistent", "final")


# ---------- remove_rebuildable_tree ----------

class TestRemoveRebuildableTree:
    def test_remove_work_dir(self, writer, ws):
        (ws / "02_work" / "sub").mkdir(parents=True)
        (ws / "02_work" / "sub" / "f.txt").write_text("x", encoding="utf-8")
        writer.remove_rebuildable_tree("02_work/sub")
        assert not (ws / "02_work" / "sub").exists()

    def test_remove_serve_dir(self, writer, ws):
        (ws / "04_serve" / "f.txt").mkdir(parents=True)
        writer.remove_rebuildable_tree("04_serve/f.txt")
        assert not (ws / "04_serve" / "f.txt").exists()

    def test_remove_protected_raises(self, writer, ws):
        (ws / "01_input").mkdir()
        with pytest.raises(PathSafetyError, match="禁止删除受保护目录"):
            writer.remove_rebuildable_tree("01_input")

    def test_remove_unknown_root_raises(self, writer):
        with pytest.raises(PathSafetyError, match="禁止删除受保护目录"):
            writer.remove_rebuildable_tree("99_misc/data")

    def test_rebuildable_roots(self):
        assert REBUILDABLE_ROOTS == ("02_work", "04_serve")
