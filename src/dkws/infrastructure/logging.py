"""原始运行日志（规格 §9.20）。

- 路径：`90_control/logs/<YYYY-MM-DD>/<job_id>.log`；
- UTF-8、LF、仅追加；
- 每行：`timestamp level job_id component event_code message key=value...`；
- level：DEBUG/INFO/WARN/ERROR/FATAL；
- 禁止记录凭据、完整敏感字段、整篇原文和未经脱敏的服务请求。
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from ..domain import paths, timeutil

LEVELS = ("DEBUG", "INFO", "WARN", "ERROR", "FATAL")

# 常见敏感键名：日志写入时自动脱敏
SENSITIVE_KEYS = {"password", "token", "secret", "credential", "authorization",
                  "api_key", "apikey", "private_key", "pwd", "passwd"}


def mask_sensitive(key: str, value) -> str:
    if key.lower() in SENSITIVE_KEYS or any(s in key.lower() for s in ("secret", "token")):
        return "***"
    return str(value)


def _sanitize_message(message: str, max_len: int = 500) -> str:
    message = re.sub(r"\s+", " ", str(message)).strip()
    return message[:max_len]


class JobLogger:
    def __init__(self, workspace: Path, job_id: str, *, component: str = "dkws"):
        self.workspace = Path(workspace)
        self.job_id = job_id
        self.component = component
        self._path: Path | None = None

    def _ensure_path(self) -> Path:
        if self._path is None:
            rel = f"90_control/logs/{timeutil.today_business()}/{self.job_id}.log"
            p = paths.resolve_ws_path(self.workspace, rel)
            p.parent.mkdir(parents=True, exist_ok=True)
            self._path = p
        return self._path

    def log(self, level: str, event_code: str, message: str, **kwargs) -> None:
        if level not in LEVELS:
            level = "INFO"
        ts = timeutil.ts_utc()
        msg = _sanitize_message(message)
        kv = " ".join(f"{k}={mask_sensitive(k, v)}" for k, v in sorted(kwargs.items()))
        line = f"{ts} {level} {self.job_id} {self.component} {event_code} {msg}"
        if kv:
            line += " " + kv
        line += "\n"
        p = self._ensure_path()
        with open(p, "a", encoding="utf-8", newline="\n") as f:
            f.write(line)
            os.fsync(f.fileno())

    def info(self, code: str, message: str, **kv):
        self.log("INFO", code, message, **kv)

    def warn(self, code: str, message: str, **kv):
        self.log("WARN", code, message, **kv)

    def error(self, code: str, message: str, **kv):
        self.log("ERROR", code, message, **kv)

    def sha256(self) -> str | None:
        from ..domain import hashing

        if self._path is None or not self._path.is_file():
            return None
        return hashing.sha256_file(self._path)
