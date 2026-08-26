"""统一 WorkspaceWriter：路径检查、临时写、原子提交、复制、删除（规格 §8.7、§20.3）。"""

from __future__ import annotations

import os
import shutil
import uuid
from pathlib import Path

from ..domain import paths
from ..domain.errors import PathSafetyError, UsageError

# 可重建目录（删除安全）：02_work 与 04_serve（规格 FR-WS-004）
REBUILDABLE_ROOTS = ("02_work", "04_serve")


class WorkspaceWriter:
    def __init__(self, workspace: Path, *, dry_run: bool = False):
        self.workspace = Path(workspace)
        self.dry_run = dry_run

    # ---------- 写入 ----------

    def resolve(self, rel: str) -> Path:
        return paths.resolve_ws_path(self.workspace, rel)

    def _atomic_write(self, target: Path, writer) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.parent / f".{target.name}.tmp-{uuid.uuid4().hex[:8]}"
        try:
            writer(tmp)
            with open(tmp, "rb") as f:
                os.fsync(f.fileno())
            os.replace(tmp, target)
        finally:
            if tmp.exists():
                tmp.unlink(missing_ok=True)

    def write_text(self, rel: str, content: str) -> str:
        """原子写 UTF-8 文本，返回工作区相对路径。"""
        if self.dry_run:
            return rel
        target = self.resolve(rel)

        def _w(tmp: Path):
            with open(tmp, "w", encoding="utf-8", newline="\n") as f:
                f.write(content)

        self._atomic_write(target, _w)
        return rel

    def write_bytes(self, rel: str, data: bytes) -> str:
        if self.dry_run:
            return rel
        target = self.resolve(rel)

        def _w(tmp: Path):
            with open(tmp, "wb") as f:
                f.write(data)

        self._atomic_write(target, _w)
        return rel

    def copy_file(self, src: Path, rel: str) -> str:
        """复制文件到工作区（接入用，绝不移动用户输入）。"""
        if self.dry_run:
            return rel
        target = self.resolve(rel)

        def _w(tmp: Path):
            shutil.copyfile(src, tmp)

        self._atomic_write(target, _w)
        return rel

    def mkdirs(self, rel: str) -> str:
        if self.dry_run:
            return rel
        self.resolve(rel).mkdir(parents=True, exist_ok=True)
        return rel

    # ---------- 读取 ----------

    def read_text(self, rel: str) -> str:
        p = self.resolve(rel)
        if not p.is_file():
            raise UsageError(f"文件不存在: {rel}")
        return p.read_text(encoding="utf-8")

    def exists(self, rel: str) -> bool:
        return self.resolve(rel).exists()

    def list_dir(self, rel: str) -> list[str]:
        p = self.resolve(rel)
        if not p.is_dir():
            return []
        return sorted(x.name for x in p.iterdir())

    # ---------- 目录级操作 ----------

    def atomic_replace_dir(self, tmp_rel: str, final_rel: str) -> None:
        """发布用：把临时版本目录原子改名为正式版本目录。

        目标不存在时直接 rename；存在时先改名旧目录再 rename，失败回滚。
        """
        if self.dry_run:
            return
        tmp = self.resolve(tmp_rel)
        final = self.resolve(final_rel)
        if not tmp.is_dir():
            raise UsageError(f"临时目录不存在: {tmp_rel}")
        final.parent.mkdir(parents=True, exist_ok=True)
        backup = None
        if final.exists():
            backup = final.parent / f".{final.name}.old-{uuid.uuid4().hex[:8]}"
            os.replace(final, backup)
        try:
            os.replace(tmp, final)
        except Exception:
            if backup is not None and not final.exists():
                os.replace(backup, final)
            raise
        if backup is not None:
            shutil.rmtree(backup, ignore_errors=True)

    def remove_rebuildable_tree(self, rel: str) -> None:
        """仅允许删除可重建目录（02_work/04_serve 下的路径）。"""
        norm = paths.normalize_ws_rel(rel)
        first = norm.split("/", 1)[0]
        if first not in REBUILDABLE_ROOTS:
            raise PathSafetyError(f"禁止删除受保护目录: {rel}")
        p = self.resolve(rel)
        if p.is_dir():
            shutil.rmtree(p)
        elif p.is_file():
            p.unlink(missing_ok=True)
