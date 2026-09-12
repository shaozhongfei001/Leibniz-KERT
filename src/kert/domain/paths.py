"""工作区路径规范与安全（规格 §8.2、§16.1）。

统一入口：把工作区相对路径解析为绝对路径，拒绝：
- 绝对路径；
- `..` 路径穿越；
- 控制字符、尾随空格；
- 解析后（含符号链接跟随）位于工作区允许根之外的路径。
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from .errors import PathSafetyError

_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
_FORBIDDEN_PARTS = {"..", "."}


def normalize_ws_rel(rel: str) -> str:
    """规范化并校验工作区相对路径字符串。"""
    if not isinstance(rel, str) or not rel:
        raise PathSafetyError("路径为空")
    if rel.startswith("/") or re.match(r"^[A-Za-z]:[\\/]", rel):
        raise PathSafetyError(f"不允许绝对路径: {rel!r}")
    if _CONTROL_RE.search(rel):
        raise PathSafetyError("路径包含控制字符")
    if rel.endswith((" ", "\t")):
        raise PathSafetyError("路径不允许尾随空格")
    parts = rel.replace("\\", "/").split("/")
    for p in parts:
        if p in _FORBIDDEN_PARTS:
            raise PathSafetyError(f"路径穿越被拒绝: {rel!r}")
        if not p:
            continue
        if p.endswith((" ", "\t")):
            raise PathSafetyError(f"路径段不允许尾随空格: {p!r}")
    return rel


def resolve_ws_path(workspace: Path, rel: str) -> Path:
    """把工作区相对路径解析为安全绝对路径；越界或链接逃逸抛 PathSafetyError。"""
    rel = normalize_ws_rel(rel)
    ws_root = Path(workspace).resolve()
    candidate = Path(ws_root, *rel.split("/"))
    # 符号链接逃逸检查：逐级 resolve 后必须仍位于工作区内
    resolved = candidate.resolve()
    if resolved != ws_root and ws_root not in resolved.parents:
        raise PathSafetyError(f"路径解析超出工作区: {rel!r}")
    # 显式检查工作区内部不存在指向外部的符号链接（resolve 已覆盖，但保持明确）
    probe = ws_root
    for part in rel.split("/"):
        probe = probe / part
        if probe.is_symlink() and probe.resolve() != probe and ws_root not in probe.resolve().parents:
            raise PathSafetyError(f"符号链接逃逸被拒绝: {rel!r}")
    return resolved


def ensure_inside_workspace(workspace: Path, path: Path) -> Path:
    """校验一个（可能为绝对）路径必须位于工作区内。"""
    ws_root = Path(workspace).resolve()
    p = Path(path).resolve()
    if p != ws_root and ws_root not in p.parents:
        raise PathSafetyError(f"路径超出工作区: {p}")
    return p


def safe_join(workspace: Path, *parts: str) -> Path:
    return resolve_ws_path(workspace, "/".join(parts))


def is_within(workspace: Path, path: Path) -> bool:
    ws_root = Path(workspace).resolve()
    p = Path(path).resolve()
    return p == ws_root or ws_root in p.parents


def fsync_dir(path: Path) -> None:
    try:
        fd = os.open(path, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError:  # pragma: no cover - 某些平台不支持目录 fsync
        pass
