#!/usr/bin/env python3
"""POC-2 OS Sandbox Runner (bubblewrap backend).

定位与边界（务必先读）
======================
- 本文件是 **POC 级** OS Sandbox Runner 适配器，用于 DKWS C' 架构中
  `Java Skill Runtime -> Sandbox Runner` 这一段的可执行验证。
- 它 **不是** 已通过独立安全审查的生产安全边界。C-B03 的关闭条件包含
  「独立安全 QA 复核」，本文件与其测试**不能**替代该复核。
- 目标后端优先 `nsjail`；当前环境无 nsjail 且不得提权安装，故采用
  `bubblewrap(bwrap)` 作为等价 OS 级隔离后端，并显式记录后端名称与
  profile 哈希，便于后续替换与比对。
- 严禁把普通 `subprocess` 当作安全沙箱：本 Runner 在 bwrap 不可用时
  返回 `SANDBOX_UNAVAILABLE`，**不降级**为裸 subprocess 执行。

安全设计要点
============
1. 固定 executable 白名单 + argv 数组，**不接受自由 shell 字符串**，
   不经过 shell 解析，因此管道/重定向/复合命令天然不生效。
2. 工作目录隔离：所有任务只能在 `--sandbox-root` 下的专属子目录内活动，
   `workingDirectoryRef` 必须是单段相对名（拒绝绝对路径与 `..`）。
3. 只读根文件系统 + tmpfs `/tmp` + 可写绑定仅限任务工作目录。
4. 禁网：`--unshare-all` 关闭 network namespace（不 `--share-net`）。
5. 资源限制：CPU 秒、地址空间、进程数、文件大小、文件描述符数，
   通过 `preexec_fn` 中 `resource.setrlimit` 施加于子进程树。
6. 环境变量清空（`--clearenv`），仅注入白名单最小变量，避免 Secret 泄露。
7. 输出截断：超过 `maxOutputBytes` 截断并置 `outputTruncated=true`。
8. 回执完整性：返回可直接映射到 `tool-call-receipt.schema.json` 的字段
   （exitCode/cpuTime/memoryPeak/outputHash/outputTruncated/networkUsed/
   sandboxProfileHash/status/errorCode）。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import resource
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

SANDBOX_BACKEND = "bubblewrap"

# 固定可执行白名单。不接受任意路径、不接受 shell。
ALLOWED_EXECUTABLES: dict[str, str] = {
    "python3": "/usr/bin/python3",
}

# 允许注入沙箱的最小环境变量白名单（值由本 Runner 决定，不透传宿主环境）。
ENV_ALLOWLIST: dict[str, str] = {
    "PATH": "/usr/bin:/bin",
    "LANG": "C.UTF-8",
    "HOME": "/work",
    "PYTHONDONTWRITEBYTECODE": "1",
}

DEFAULTS: dict[str, Any] = {
    "timeoutMs": 10_000,
    "cpuSeconds": 5,
    "addressSpaceBytes": 512 * 1024 * 1024,
    "maxProcesses": 64,
    "maxFileSizeBytes": 8 * 1024 * 1024,
    "maxOpenFiles": 64,
    "maxOutputBytes": 64 * 1024,
}


class SandboxTaskError(ValueError):
    """任务描述非法（fail-closed，不尝试猜测修正）。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def backend_available() -> bool:
    return shutil.which("bwrap") is not None


def _current_uid_process_count() -> int:
    """统计当前 UID 已占用的**线程**数，用作 RLIMIT_NPROC 基线。

    关键点：内核对 RLIMIT_NPROC 的检查是「per-UID 的 task 数」，task 包含
    线程而不只是进程。本机实测 PID 数 ~277 但线程数 ~3996（相差一个数量级），
    若只按 PID 数做基线，bwrap 创建 namespace 时立刻 EAGAIN
    （Creating new namespace failed: Resource temporarily unavailable）。
    因此必须按线程数统计。
    """
    uid = os.getuid()
    count = 0
    try:
        for entry in Path("/proc").iterdir():
            if not entry.name.isdigit():
                continue
            try:
                if entry.stat().st_uid != uid:
                    continue
                for line in (entry / "status").read_text().splitlines():
                    if line.startswith("Threads:"):
                        count += int(line.split()[1])
                        break
                else:
                    count += 1
            except (OSError, ValueError):
                continue
    except OSError:
        return 8192
    return count


def profile_hash(limits: dict[str, Any]) -> str:
    """沙箱 profile 哈希：后端 + 限制 + 环境白名单 + 可执行白名单。

    profile 变化即哈希变化，便于回执比对与安全基线追溯。
    """
    profile = {
        "backend": SANDBOX_BACKEND,
        "limits": {k: limits[k] for k in sorted(limits)},
        "env": dict(sorted(ENV_ALLOWLIST.items())),
        "executables": dict(sorted(ALLOWED_EXECUTABLES.items())),
        "readOnlyRoot": True,
        "network": "denied",
        "shell": "denied",
    }
    canonical = json.dumps(profile, sort_keys=True, separators=(",", ":"))
    return _sha256(canonical.encode("utf-8"))


def _resolve_executable(task: dict[str, Any]) -> str:
    executable = task.get("executable")
    if not isinstance(executable, str) or not executable:
        raise SandboxTaskError("SANDBOX_TASK_INVALID", "executable is required")
    if executable not in ALLOWED_EXECUTABLES:
        raise SandboxTaskError(
            "SANDBOX_EXECUTABLE_NOT_ALLOWED",
            f"executable not in allowlist: {executable!r}",
        )
    return ALLOWED_EXECUTABLES[executable]


def _resolve_argv(task: dict[str, Any]) -> list[str]:
    argv = task.get("argv", [])
    if not isinstance(argv, list) or not all(isinstance(a, str) for a in argv):
        raise SandboxTaskError("SANDBOX_TASK_INVALID", "argv must be a list of strings")
    return argv


def _resolve_workdir(task: dict[str, Any], sandbox_root: Path) -> Path:
    """解析工作目录，拒绝绝对路径、路径穿越与 symlink 逃逸。"""
    ref = task.get("workingDirectoryRef")
    if ref is None:
        return Path(tempfile.mkdtemp(prefix="sandbox-job-", dir=str(sandbox_root)))

    if not isinstance(ref, str) or not ref:
        raise SandboxTaskError("SANDBOX_TASK_INVALID", "workingDirectoryRef must be a non-empty string")
    if ref != Path(ref).name:
        raise SandboxTaskError(
            "SANDBOX_PATH_TRAVERSAL",
            f"workingDirectoryRef must be a single path segment: {ref!r}",
        )
    if ref in {".", ".."} or ref.startswith("/") or "\\" in ref:
        raise SandboxTaskError("SANDBOX_PATH_TRAVERSAL", f"illegal workingDirectoryRef: {ref!r}")

    candidate = sandbox_root / ref
    if candidate.is_symlink():
        raise SandboxTaskError("SANDBOX_SYMLINK_ESCAPE", f"workingDirectoryRef is a symlink: {ref!r}")

    candidate.mkdir(parents=True, exist_ok=True)
    real_root = sandbox_root.resolve(strict=True)
    real_candidate = candidate.resolve(strict=True)
    if real_candidate != real_root and real_root not in real_candidate.parents:
        raise SandboxTaskError(
            "SANDBOX_SYMLINK_ESCAPE",
            f"resolved working directory escapes sandbox root: {real_candidate}",
        )
    return real_candidate


def _resolve_limits(task: dict[str, Any]) -> dict[str, Any]:
    limits = dict(DEFAULTS)
    for key in DEFAULTS:
        if key not in task:
            continue
        value = task[key]
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise SandboxTaskError("SANDBOX_TASK_INVALID", f"{key} must be a positive integer")
        # 只允许收紧，不允许放宽超过默认上限（防止任务自行提额）。
        limits[key] = min(value, DEFAULTS[key])
    return limits


def _build_command(executable: str, argv: list[str], workdir: Path) -> list[str]:
    """构造 bwrap 命令：只读根、tmpfs、禁网、清空 env、仅工作目录可写。

    注意：本机 /bin、/lib、/lib64、/sbin 通常是指向 /usr/* 的符号链接，
    必须逐个 ro-bind（存在才绑），否则动态链接器找不到解释器。
    """
    cmd = ["bwrap", "--ro-bind", "/usr", "/usr"]
    for path in ("/lib", "/lib64", "/bin", "/sbin", "/etc/alternatives"):
        if Path(path).exists():
            cmd += ["--ro-bind", path, path]
    cmd += [
        "--dev", "/dev",
        "--proc", "/proc",
        "--tmpfs", "/tmp",
        "--bind", str(workdir), "/work",
        "--chdir", "/work",
        "--unshare-all",          # 含 network namespace -> 禁网
        "--die-with-parent",
        "--new-session",          # 防止 TIOCSTI 注入
        "--clearenv",
    ]
    for key, value in ENV_ALLOWLIST.items():
        cmd += ["--setenv", key, value]
    cmd += ["--", executable, *argv]
    return cmd


def _make_preexec(limits: dict[str, Any]):
    """施加 rlimit。

    RLIMIT_NPROC 由内核按 **UID 全局 task（含线程）** 计数，不是按进程树计数。
    若直接设为一个绝对小值（如 8），bwrap 自身创建 namespace 时就会 EAGAIN 失败。
    因此以「当前 UID 已有线程数」为基线，额外只允许 maxProcesses 个新 task，
    这样既能限制 fork 炸弹，又不会误杀 bwrap 启动本身。
    """
    cpu = limits["cpuSeconds"]
    addr_space = limits["addressSpaceBytes"]
    fsize = limits["maxFileSizeBytes"]
    nofile = limits["maxOpenFiles"]
    nproc_ceiling = _current_uid_process_count() + limits["maxProcesses"]

    def _preexec() -> None:  # pragma: no cover - 子进程内执行
        resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu))
        resource.setrlimit(resource.RLIMIT_AS, (addr_space, addr_space))
        resource.setrlimit(resource.RLIMIT_NPROC, (nproc_ceiling, nproc_ceiling))
        resource.setrlimit(resource.RLIMIT_FSIZE, (fsize, fsize))
        resource.setrlimit(resource.RLIMIT_NOFILE, (nofile, nofile))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))

    return _preexec


def _truncate(text: str, max_bytes: int) -> tuple[str, bool]:
    raw = text.encode("utf-8", errors="replace")
    if len(raw) <= max_bytes:
        return text, False
    return raw[:max_bytes].decode("utf-8", errors="replace"), True


def _receipt(
    *,
    status: str,
    exit_code: int,
    stdout: str,
    stderr: str,
    truncated: bool,
    cpu_time: float,
    memory_peak: int,
    started_at: float,
    completed_at: float,
    limits: dict[str, Any],
    error_code: str | None = None,
) -> dict[str, Any]:
    receipt: dict[str, Any] = {
        "backend": SANDBOX_BACKEND,
        "status": status,
        "exitCode": exit_code,
        "stdout": stdout,
        "stderr": stderr,
        "outputHash": _sha256(stdout.encode("utf-8", errors="replace")),
        "outputTruncated": truncated,
        "networkUsed": False,
        "cpuTime": round(cpu_time, 6),
        "memoryPeak": memory_peak,
        "sandboxProfileHash": profile_hash(limits),
        "startedAt": started_at,
        "completedAt": completed_at,
        "limits": limits,
    }
    if error_code:
        receipt["errorCode"] = error_code
    return receipt


def run(task: dict[str, Any], sandbox_root: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    """执行一个受控沙箱任务，返回可映射到 ToolCallReceipt 的回执。

    任何非法任务/后端缺失都 fail-closed，绝不退回裸 subprocess。
    """
    started_at = time.time()
    limits = DEFAULTS

    if not backend_available():
        return _receipt(
            status="error",
            exit_code=-1,
            stdout="",
            stderr="bwrap not available; refusing to fall back to plain subprocess",
            truncated=False,
            cpu_time=0.0,
            memory_peak=0,
            started_at=started_at,
            completed_at=time.time(),
            limits=limits,
            error_code="SANDBOX_UNAVAILABLE",
        )

    root = Path(sandbox_root) if sandbox_root else Path(tempfile.gettempdir()) / "dkws-sandbox"
    root.mkdir(parents=True, exist_ok=True)

    try:
        executable = _resolve_executable(task)
        argv = _resolve_argv(task)
        limits = _resolve_limits(task)
        workdir = _resolve_workdir(task, root)
    except SandboxTaskError as exc:
        return _receipt(
            status="blocked",
            exit_code=-1,
            stdout="",
            stderr=str(exc),
            truncated=False,
            cpu_time=0.0,
            memory_peak=0,
            started_at=started_at,
            completed_at=time.time(),
            limits=limits,
            error_code=exc.code,
        )

    cmd = _build_command(executable, argv, workdir)
    timeout_s = limits["timeoutMs"] / 1000.0

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env={},
        preexec_fn=_make_preexec(limits),
    )
    usage_before = resource.getrusage(resource.RUSAGE_CHILDREN)
    timed_out = False
    try:
        stdout, stderr = proc.communicate(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        timed_out = True
        proc.kill()
        stdout, stderr = proc.communicate()

    usage_after = resource.getrusage(resource.RUSAGE_CHILDREN)
    cpu_time = (
        (usage_after.ru_utime - usage_before.ru_utime)
        + (usage_after.ru_stime - usage_before.ru_stime)
    )
    memory_peak = max(usage_after.ru_maxrss - usage_before.ru_maxrss, 0) * 1024

    max_output = limits["maxOutputBytes"]
    stdout, stdout_truncated = _truncate(stdout or "", max_output)
    stderr, stderr_truncated = _truncate(stderr or "", max_output)

    if timed_out:
        status, error_code = "timeout", "SANDBOX_TIMEOUT"
    elif proc.returncode == 0:
        status, error_code = "ok", None
    elif proc.returncode is not None and (proc.returncode < 0 or proc.returncode > 128):
        # bwrap 作为 init 进程时，会把被信号杀死的子进程转成 128+signo 退出码
        # （如 SIGKILL -> 137）。直接 kill bwrap 自身则为负值。两者都算「进程被杀」。
        status, error_code = "failed", "SANDBOX_PROCESS_KILLED"
    else:
        status, error_code = "failed", "SANDBOX_NONZERO_EXIT"

    return _receipt(
        status=status,
        exit_code=proc.returncode if proc.returncode is not None else -1,
        stdout=stdout,
        stderr=stderr,
        truncated=stdout_truncated or stderr_truncated,
        cpu_time=cpu_time,
        memory_peak=memory_peak,
        started_at=started_at,
        completed_at=time.time(),
        limits=limits,
        error_code=error_code,
    )


def main() -> int:
    ap = argparse.ArgumentParser(description="DKWS POC-2 OS Sandbox Runner (bubblewrap)")
    ap.add_argument("--task", required=True, help="JSON task file path or inline JSON string")
    ap.add_argument("--sandbox-root", default=None, help="sandbox root directory")
    args = ap.parse_args()

    try:
        task = json.loads(args.task)
    except json.JSONDecodeError:
        task = json.loads(Path(args.task).read_text(encoding="utf-8"))

    result = run(task, sandbox_root=args.sandbox_root)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
