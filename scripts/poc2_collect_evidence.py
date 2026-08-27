#!/usr/bin/env python3
"""重跑 POC-2 全部可执行验证并落盘带完整元数据的原始证据。

施工令第十二节要求每份证据记录：命令、工作目录、时间、环境版本、
commit/文件 manifest、退出码、原始结果、判定、对应评审发现。
本脚本为每份日志加上结构化头部，再附完整原始输出（不截断、不摘要）。

纪律：判定一律由真实退出码得出；本脚本不接受手工指定 PASS。
"""

from __future__ import annotations

import json
import platform
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
POC_DIR = REPO_ROOT / "poc" / "spring-ai-alibaba-skill-runtime"
EVIDENCE_DIR = REPO_ROOT / "evidence" / "poc2"

VENV_PY = REPO_ROOT / ".venv" / "bin" / "python"
PYTHON = str(VENV_PY) if VENV_PY.is_file() else sys.executable


def git(*args: str) -> str:
    try:
        return subprocess.run(
            ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "UNKNOWN"


def tool_version(*cmd: str) -> str:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
        out = (proc.stdout or proc.stderr).strip()
        return out.splitlines()[0] if out else "UNKNOWN"
    except (OSError, subprocess.SubprocessError):
        return "UNAVAILABLE"


ENVIRONMENT = {
    "platform": platform.platform(),
    "python": sys.version.split()[0],
    "java": tool_version("java", "-version"),
    "maven": tool_version("mvn", "-v"),
    "bwrap": tool_version("bwrap", "--version"),
    "nsjail": tool_version("nsjail", "--help") if shutil.which("nsjail") else "NOT_INSTALLED",
}


def run_evidence(
    *,
    output: str,
    command: list[str],
    cwd: Path,
    findings: list[str],
    description: str,
    timeout: int = 1800,
) -> dict:
    started = datetime.now(timezone.utc)
    proc = subprocess.run(command, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    finished = datetime.now(timezone.utc)
    exit_code = proc.returncode

    header = [
        "=" * 79,
        "DKWS POC-2 EVIDENCE",
        "=" * 79,
        f"workstream:       DKWS-C-MIXED-ARCH-REMEDIATION-01",
        f"description:      {description}",
        f"command:          {' '.join(command)}",
        f"workingDirectory: {cwd.relative_to(REPO_ROOT) if cwd != REPO_ROOT else '.'}",
        f"startedAt:        {started.isoformat()}",
        f"completedAt:      {finished.isoformat()}",
        f"durationSeconds:  {(finished - started).total_seconds():.3f}",
        f"exitCode:         {exit_code}",
        f"verdict:          {'PASS' if exit_code == 0 else 'FAIL'}",
        f"findings:         {', '.join(findings)}",
        f"repositoryBranch: {git('rev-parse', '--abbrev-ref', 'HEAD')}",
        f"repositoryCommit: {git('rev-parse', 'HEAD')}",
        f"workingTreeDirty: {bool(git('status', '--porcelain'))}",
        "environment:",
        *[f"  {k}: {v}" for k, v in ENVIRONMENT.items()],
        "=" * 79,
        "RAW STDOUT",
        "=" * 79,
        proc.stdout,
        "=" * 79,
        "RAW STDERR",
        "=" * 79,
        proc.stderr,
        "=" * 79,
        f"EXIT_CODE={exit_code}",
        "",
    ]

    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    (EVIDENCE_DIR / output).write_text("\n".join(header), encoding="utf-8")
    return {"output": output, "exitCode": exit_code, "verdict": "PASS" if exit_code == 0 else "FAIL"}


def main() -> int:
    results = []

    results.append(
        run_evidence(
            output="build.log",
            command=["mvn", "-B", "-ntp", "clean", "test"],
            cwd=POC_DIR,
            findings=["C-B04", "C-M01"],
            description="Java 21 离线可重复构建 + 全量单元测试（clean test）",
        )
    )
    # 同一次运行既是构建证据也是单元测试证据；分别落盘以对应不同评审发现
    shutil.copy2(EVIDENCE_DIR / "build.log", EVIDENCE_DIR / "unit-tests.log")
    results.append({"output": "unit-tests.log", **{k: results[-1][k] for k in ("exitCode", "verdict")}})

    results.append(
        run_evidence(
            output="dependency-tree.txt",
            command=["mvn", "-B", "-ntp", "dependency:tree"],
            cwd=POC_DIR,
            findings=["C-M07"],
            description="固定依赖版本树（用于双栈依赖治理）",
        )
    )

    results.append(
        run_evidence(
            output="contract-tests.log",
            command=[
                PYTHON, "-m", "pytest",
                "tests/contract/test_internal_runtime_contract.py",
                "-v", "--no-header", "-p", "no:cacheprovider",
            ],
            cwd=REPO_ROOT,
            findings=["C-B02"],
            description="内部契约 consumer 侧（Python Core 视角）契约测试",
        )
    )

    results.append(
        run_evidence(
            output="contract-tests-provider.log",
            command=["mvn", "-B", "-ntp", "test", "-Dtest=InternalContractSchemaTest"],
            cwd=POC_DIR,
            findings=["C-B02"],
            description="内部契约 provider 侧（Java Runtime 视角）契约测试",
        )
    )

    results.append(
        run_evidence(
            output="sandbox-security-tests.log",
            command=[
                PYTHON, "-m", "pytest",
                "tests/security/test_sandbox_runner_security.py",
                "-v", "--no-header", "-p", "no:cacheprovider",
            ],
            cwd=REPO_ROOT,
            findings=["C-B03"],
            description="OS Sandbox（bubblewrap）安全负向用例与资源限制机器验证",
        )
    )

    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0 if all(r["exitCode"] == 0 for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
