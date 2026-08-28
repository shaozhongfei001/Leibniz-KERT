"""paths 模块单元测试：路径规范化、安全校验、越界检测。"""

from __future__ import annotations

from pathlib import Path

import pytest

from dkws.domain.errors import PathSafetyError
from dkws.domain.paths import (
    ensure_inside_workspace,
    is_within,
    normalize_ws_rel,
    resolve_ws_path,
    safe_join,
)


# ---------- normalize_ws_rel ----------

class TestNormalizeWsRel:
    def test_simple_rel(self):
        assert normalize_ws_rel("data/file.txt") == "data/file.txt"

    def test_single_component(self):
        assert normalize_ws_rel("file.txt") == "file.txt"

    def test_backslash_converted(self):
        # 反斜杠被替换为 / 但返回原字符串（内部 split 用 /）
        result = normalize_ws_rel("data\\file.txt")
        assert result == "data\\file.txt"  # 返回原字符串，split 已处理

    def test_empty_raises(self):
        with pytest.raises(PathSafetyError, match="路径为空"):
            normalize_ws_rel("")

    def test_none_raises(self):
        with pytest.raises(PathSafetyError, match="路径为空"):
            normalize_ws_rel(None)

    def test_absolute_unix_raises(self):
        with pytest.raises(PathSafetyError, match="不允许绝对路径"):
            normalize_ws_rel("/etc/passwd")

    def test_absolute_windows_raises(self):
        with pytest.raises(PathSafetyError, match="不允许绝对路径"):
            normalize_ws_rel("C:\\Windows")

    def test_absolute_windows_forward_slash(self):
        with pytest.raises(PathSafetyError, match="不允许绝对路径"):
            normalize_ws_rel("C:/Windows")

    def test_dotdot_raises(self):
        with pytest.raises(PathSafetyError, match="路径穿越被拒绝"):
            normalize_ws_rel("../etc/passwd")

    def test_dotdot_mid_raises(self):
        with pytest.raises(PathSafetyError, match="路径穿越被拒绝"):
            normalize_ws_rel("data/../../etc/passwd")

    def test_single_dot_raises(self):
        with pytest.raises(PathSafetyError, match="路径穿越被拒绝"):
            normalize_ws_rel("./secret")

    def test_control_chars_raises(self):
        with pytest.raises(PathSafetyError, match="路径包含控制字符"):
            normalize_ws_rel("file\x00name")

    def test_tab_control_char(self):
        with pytest.raises(PathSafetyError, match="路径包含控制字符"):
            normalize_ws_rel("file\x01name")

    def test_trailing_space_raises(self):
        with pytest.raises(PathSafetyError, match="路径不允许尾随空格"):
            normalize_ws_rel("file.txt ")

    def test_trailing_tab_raises(self):
        # \t 是控制字符（\x09），先触发控制字符检查
        with pytest.raises(PathSafetyError, match="路径包含控制字符"):
            normalize_ws_rel("file.txt\t")

    def test_segment_trailing_space(self):
        with pytest.raises(PathSafetyError, match="路径段不允许尾随空格"):
            normalize_ws_rel("dir /file.txt")

    def test_valid_deep_path(self):
        assert normalize_ws_rel("a/b/c/d/e.txt") == "a/b/c/d/e.txt"

    def test_double_slash_ignored(self):
        # 连续 // 产生空段，被跳过
        result = normalize_ws_rel("a//b")
        assert result == "a//b"


# ---------- resolve_ws_path ----------

class TestResolveWsPath:
    def test_simple_resolve(self, tmp_path):
        ws = tmp_path / "workspace"
        ws.mkdir()
        result = resolve_ws_path(ws, "data/file.txt")
        assert result == ws / "data" / "file.txt"

    def test_escape_raises(self, tmp_path):
        ws = tmp_path / "workspace"
        ws.mkdir()
        # "../outside" 被 normalize_ws_rel 拦截，抛出"路径穿越被拒绝"
        with pytest.raises(PathSafetyError, match="路径穿越被拒绝"):
            resolve_ws_path(ws, "../outside")

    def test_symlink_escape_raises(self, tmp_path):
        ws = tmp_path / "workspace"
        ws.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()
        link = ws / "link"
        link.symlink_to(outside)
        # 符号链接逃逸被 resolve_ws_path 检测，抛出"路径解析超出工作区"
        with pytest.raises(PathSafetyError, match="路径解析超出工作区"):
            resolve_ws_path(ws, "link/evil.txt")

    def test_resolve_creates_valid_path(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        (ws / "subdir").mkdir()
        result = resolve_ws_path(ws, "subdir/file.txt")
        assert str(result).startswith(str(ws))


# ---------- ensure_inside_workspace ----------

class TestEnsureInsideWorkspace:
    def test_inside(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        p = ws / "data" / "file.txt"
        result = ensure_inside_workspace(ws, p)
        assert result == p.resolve()

    def test_outside_raises(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        outside = tmp_path / "outside"
        with pytest.raises(PathSafetyError, match="路径超出工作区"):
            ensure_inside_workspace(ws, outside)

    def test_workspace_root_itself(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        result = ensure_inside_workspace(ws, ws)
        assert result == ws.resolve()


# ---------- safe_join ----------

class TestSafeJoin:
    def test_join_parts(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        result = safe_join(ws, "dir", "file.txt")
        assert result == (ws / "dir" / "file.txt").resolve()


# ---------- is_within ----------

class TestIsWithin:
    def test_inside(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        assert is_within(ws, ws / "data" / "file.txt") is True

    def test_outside(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        assert is_within(ws, tmp_path / "outside") is False

    def test_root_itself(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        assert is_within(ws, ws) is True
