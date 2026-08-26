"""工作区写锁（规格 §8.7、FR-CTL-006、ADR-008）。

- 锁文件：`90_control/locks/<scope>.lock.json`；
- 内容：job、owner、host、pid、acquired_at、expires_at（RFC 3339 UTC）；
- 获取：O_EXCL 原子创建；已存在且未过期 → WORKSPACE_LOCKED；
- 过期锁只能由恢复命令（recover）验证关联任务已终止后清理；
- 释放：删除锁文件。
"""

from __future__ import annotations

import json
import os
import socket
import uuid
from pathlib import Path

from ..domain import paths, timeutil
from ..domain.errors import ConflictError

LOCK_SUFFIX = ".lock.json"


class WorkspaceLock:
    def __init__(self, workspace: Path, scope: str, *, job_id: str,
                 owner: str, ttl_seconds: int = 600):
        self.workspace = Path(workspace)
        self.scope = paths.normalize_ws_rel(scope)
        self.job_id = job_id
        self.owner = owner
        self.ttl = ttl_seconds
        self._path: Path | None = None

    def _lock_rel(self) -> str:
        safe = self.scope.replace("/", "__").replace("\\", "__")
        return f"90_control/locks/{safe}{LOCK_SUFFIX}"

    def acquire(self) -> str:
        rel = self._lock_rel()
        lock_path = paths.resolve_ws_path(self.workspace, rel)
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        now = timeutil.now_utc()
        payload = {
            "schema": "workspace_lock/v1",
            "scope": self.scope,
            "job_id": self.job_id,
            "owner": self.owner,
            "host": socket.gethostname(),
            "pid": os.getpid(),
            "acquired_at": timeutil.ts_utc(now),
            "expires_at": timeutil.ts_utc(now + __import__("datetime").timedelta(seconds=self.ttl)),
            "token": uuid.uuid4().hex,
        }
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            existing = self._read_existing(lock_path)
            if existing and existing.get("expires_at", "") > timeutil.ts_utc():
                raise ConflictError(
                    f"写锁冲突: scope={self.scope!r} 已被 job={existing.get('job_id')} "
                    f"持有至 {existing.get('expires_at')}",
                    details={"scope": self.scope, "holder_job": existing.get("job_id")},
                )
            raise ConflictError(
                f"写锁已过期但未清理: scope={self.scope!r}，请先运行恢复命令验证任务终止后清理",
                details={"scope": self.scope, "holder_job": existing.get("job_id")},
            )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, sort_keys=True)
        except Exception:
            lock_path.unlink(missing_ok=True)
            raise
        self._path = lock_path
        return rel

    @staticmethod
    def _read_existing(lock_path: Path) -> dict | None:
        try:
            return json.loads(lock_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def release(self) -> None:
        if self._path is not None:
            self._path.unlink(missing_ok=True)
            self._path = None

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *exc):
        self.release()
        return False


def list_stale_locks(workspace: Path) -> list[dict]:
    """列出过期锁（供 recover 命令使用）。"""
    locks_dir = Path(workspace) / "90_control" / "locks"
    result = []
    if not locks_dir.is_dir():
        return result
    now = timeutil.ts_utc()
    for f in sorted(locks_dir.glob(f"*{LOCK_SUFFIX}")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
        if data.get("expires_at", "") <= now:
            data["lock_file"] = f.name
            result.append(data)
    return result


def clear_stale_lock(workspace: Path, lock_file: str) -> bool:
    """清理一个已确认过期的锁文件；返回是否删除。"""
    p = paths.resolve_ws_path(workspace, f"90_control/locks/{lock_file}")
    if p.is_file():
        p.unlink()
        return True
    return False
