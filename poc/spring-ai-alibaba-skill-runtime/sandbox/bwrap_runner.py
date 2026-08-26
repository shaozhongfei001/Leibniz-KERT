#!/usr/bin/env python3
"""POC-2 OS Sandbox Runner using bubblewrap (bwrap).

Not a production security boundary; only a POC adapter.
"""
import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path


def run(task: dict) -> dict:
    executable = task.get("executable", "python3")
    argv = task.get("argv", [])
    timeout_ms = int(task.get("timeoutMs", 10000))
    workdir = task.get("workingDirectoryRef") or tempfile.mkdtemp(prefix="sandbox-")
    Path(workdir).mkdir(parents=True, exist_ok=True)

    cmd = [
        "bwrap",
        "--ro-bind", "/", "/",
        "--dev", "/dev",
        "--proc", "/proc",
        "--tmpfs", "/tmp",
        "--unshare-all",
        "--die-with-parent",
        "--chdir", "/",
        "--",
        executable,
        *argv,
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_ms / 1000.0,
        )
        return {
            "status": "ok" if proc.returncode == 0 else "failed",
            "exitCode": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "truncated": len(proc.stdout) > 1024 * 1024,
        }
    except subprocess.TimeoutExpired:
        return {"status": "timeout", "exitCode": -1, "stdout": "", "stderr": "timeout"}
    except Exception as exc:
        return {"status": "error", "exitCode": -1, "stdout": "", "stderr": str(exc)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", required=True, help="JSON task file or JSON string")
    args = ap.parse_args()
    try:
        task = json.loads(args.task)
    except json.JSONDecodeError:
        task = json.loads(Path(args.task).read_text(encoding="utf-8"))
    result = run(task)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
