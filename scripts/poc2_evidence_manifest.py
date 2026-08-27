#!/usr/bin/env python3
"""生成 POC-2 证据清单（input/source manifest + 总 manifest）。

施工令第十二节要求：每份证据必须记录命令、工作目录、时间、环境版本、
commit 或文件 manifest、退出码、原始结果、PASS/FAIL/NOT_EXECUTED/BLOCKED、
以及对应的评审发现。本脚本负责把这些元数据结构化落盘。

纪律：
- 状态一律来自真实执行结果（读取日志退出码），不得手填 PASS。
- 缺失的证据文件必须显式列为 MISSING，不得静默跳过。
"""

from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_DIR = REPO_ROOT / "evidence" / "poc2"
POC_DIR = REPO_ROOT / "poc" / "spring-ai-alibaba-skill-runtime"
CONTRACT_DIR = REPO_ROOT / "docs" / "contracts" / "internal"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def git(*args: str) -> str | None:
    try:
        return subprocess.run(
            ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def tool_version(*cmd: str) -> str | None:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        out = (proc.stdout or proc.stderr).strip()
        return out.splitlines()[0] if out else None
    except (OSError, subprocess.SubprocessError):
        return None


def manifest_of(root: Path, patterns: list[str], label: str) -> dict:
    files = []
    for pattern in patterns:
        for path in sorted(root.glob(pattern)):
            if path.is_file():
                files.append(
                    {
                        "path": str(path.relative_to(REPO_ROOT)),
                        "sha256": sha256_file(path),
                        "sizeBytes": path.stat().st_size,
                    }
                )
    aggregate = hashlib.sha256()
    for entry in files:
        aggregate.update(entry["path"].encode())
        aggregate.update(b"\0")
        aggregate.update(entry["sha256"].encode())
        aggregate.update(b"\0")
    return {
        "label": label,
        "root": str(root.relative_to(REPO_ROOT)),
        "fileCount": len(files),
        "aggregateHash": aggregate.hexdigest(),
        "files": files,
    }


def read_exit_code(log: Path) -> int | None:
    if not log.is_file():
        return None
    for line in reversed(log.read_text(encoding="utf-8", errors="replace").splitlines()):
        if line.startswith("EXIT_CODE="):
            try:
                return int(line.split("=", 1)[1].strip())
            except ValueError:
                return None
    return None


def contract_bundle_hash() -> str | None:
    script = REPO_ROOT / "scripts" / "internal_contract_hash.py"
    if not script.is_file():
        return None
    try:
        out = subprocess.run(
            [sys.executable, str(script)], cwd=REPO_ROOT, capture_output=True, text=True, check=True
        ).stdout
        return json.loads(out)["bundle_hash"]
    except (OSError, subprocess.CalledProcessError, ValueError, KeyError):
        return None


# 每条证据：文件 -> (命令, 工作目录, 对应评审发现, 未产出时的状态说明)
EVIDENCE_SPEC: list[dict] = [
    {
        "file": "build.log",
        "command": "mvn -B -ntp clean test",
        "cwd": "poc/spring-ai-alibaba-skill-runtime",
        "findings": ["C-B04", "C-M01"],
        "description": "Java 21 离线可重复构建 + 全量单元测试",
    },
    {
        "file": "unit-tests.log",
        "command": "mvn -B -ntp clean test",
        "cwd": "poc/spring-ai-alibaba-skill-runtime",
        "findings": ["C-B04", "C-M02", "C-M05"],
        "description": "Skill 生命周期 / 契约 / 安全组件单元测试",
    },
    {
        "file": "contract-tests.log",
        "command": (
            "python -m pytest tests/contract/test_internal_runtime_contract.py -v"
            " (consumer) + mvn test -Dtest=InternalContractSchemaTest (provider)"
        ),
        "cwd": ".",
        "findings": ["C-B02"],
        "description": "Python/Java 双端 consumer/provider 契约测试",
    },
    {
        "file": "sandbox-security-tests.log",
        "command": "python -m pytest tests/security/test_sandbox_runner_security.py -v",
        "cwd": ".",
        "findings": ["C-B03"],
        "description": "OS Sandbox（bubblewrap）安全负向用例与资源限制",
    },
    {
        "file": "dependency-tree.txt",
        "command": "mvn -B -ntp dependency:tree -DoutputFile=...",
        "cwd": "poc/spring-ai-alibaba-skill-runtime",
        "findings": ["C-M07"],
        "description": "固定依赖版本树",
    },
    {
        "file": "sbom.json",
        "command": "mvn -B -ntp org.cyclonedx:cyclonedx-maven-plugin:2.8.0:makeAggregateBom -DoutputFormat=json",
        "cwd": "poc/spring-ai-alibaba-skill-runtime",
        "findings": ["C-M07"],
        "description": "CycloneDX SBOM（Java 栈）",
    },
    {
        "file": "performance-baseline.json",
        "command": "python scripts/poc2_performance_baseline.py",
        "cwd": ".",
        "findings": ["C-M09"],
        "description": "性能基线测量（非 NFR 达标声明）",
    },
    {
        "file": "integration-tests.log",
        "command": "N/A",
        "cwd": ".",
        "findings": ["C-B04"],
        "description": "Python Core -> Java Runtime 集成测试",
        "expected_missing_status": "NOT_EXECUTED",
        "expected_missing_reason": (
            "Core->Runtime 集成尚未实现（施工令禁止未经 Owner 授权接入生产 Core）；"
            "内部契约已就绪但无运行时联调，故本项未执行。"
        ),
    },
    {
        "file": "reliability-tests.log",
        "command": "N/A",
        "cwd": ".",
        "findings": ["C-B04", "C-M04"],
        "description": "故障注入：Runtime 不可达/重启/取消/熔断",
        "expected_missing_status": "NOT_EXECUTED",
        "expected_missing_reason": "依赖 Core->Runtime 集成，未实现，故未执行。",
    },
]


def main() -> int:
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)

    input_manifest = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "workstream": "DKWS-C-MIXED-ARCH-REMEDIATION-01",
        "primaryInput": {
            "path": "docs/dd/DKWS_生产级混合架构独立评审报告_2026-08-26_V1.0.md",
            "expectedSha256": "2d1f7a1bfe7776df0b4c9dfd4bb2a7c14f30e0bae7c826dd5128e687d4228feb",
        },
        "contracts": manifest_of(CONTRACT_DIR, ["**/*.json", "**/*.yaml", "**/*.md"], "internal-contracts"),
    }
    report = REPO_ROOT / input_manifest["primaryInput"]["path"]
    if report.is_file():
        actual = sha256_file(report)
        input_manifest["primaryInput"]["actualSha256"] = actual
        input_manifest["primaryInput"]["hashMatch"] = (
            actual == input_manifest["primaryInput"]["expectedSha256"]
        )
    else:
        input_manifest["primaryInput"]["actualSha256"] = None
        input_manifest["primaryInput"]["hashMatch"] = False

    (EVIDENCE_DIR / "input-manifest.json").write_text(
        json.dumps(input_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    source_manifest = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "repositoryRoot": str(REPO_ROOT),
        "branch": git("rev-parse", "--abbrev-ref", "HEAD"),
        "commit": git("rev-parse", "HEAD"),
        "dirty": bool(git("status", "--porcelain")),
        "java": manifest_of(POC_DIR, ["src/**/*.java", "pom.xml", "src/main/resources/*.yml"], "poc2-java"),
        "sandbox": manifest_of(POC_DIR, ["sandbox/*.py"], "poc2-sandbox"),
        "tests": manifest_of(
            REPO_ROOT / "tests",
            ["contract/test_internal_runtime_contract.py", "security/test_sandbox_runner_security.py"],
            "poc2-python-tests",
        ),
    }
    (EVIDENCE_DIR / "source-manifest.json").write_text(
        json.dumps(source_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    bundle_hash = contract_bundle_hash()
    (EVIDENCE_DIR / "contract-bundle-manifest.json").write_text(
        json.dumps(
            {
                "generatedAt": datetime.now(timezone.utc).isoformat(),
                "bundleHash": bundle_hash,
                "recomputeCommand": "python scripts/internal_contract_hash.py",
                "contracts": input_manifest["contracts"],
                "note": "bundleHash 可由 recomputeCommand 重算验证；契约变更必导致哈希变化。",
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    artifacts = []
    for spec in EVIDENCE_SPEC:
        path = EVIDENCE_DIR / spec["file"]
        entry = {
            "file": spec["file"],
            "description": spec["description"],
            "command": spec["command"],
            "workingDirectory": spec["cwd"],
            "correspondingFindings": spec["findings"],
        }
        if path.is_file():
            exit_code = read_exit_code(path)
            entry.update(
                {
                    "present": True,
                    "sha256": sha256_file(path),
                    "sizeBytes": path.stat().st_size,
                    "modifiedAt": datetime.fromtimestamp(
                        path.stat().st_mtime, tz=timezone.utc
                    ).isoformat(),
                    "exitCode": exit_code,
                    "status": "PASS" if exit_code == 0 else ("FAIL" if exit_code else "RECORDED"),
                }
            )
        else:
            entry.update(
                {
                    "present": False,
                    "sha256": None,
                    "exitCode": None,
                    "status": spec.get("expected_missing_status", "MISSING"),
                    "reason": spec.get("expected_missing_reason", "证据文件不存在"),
                }
            )
        artifacts.append(entry)

    manifest = {
        "workstream": "DKWS-C-MIXED-ARCH-REMEDIATION-01",
        "poc": "spring-ai-alibaba-skill-runtime",
        "phase": "POC-2",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "environment": {
            "platform": platform.platform(),
            "python": sys.version.split()[0],
            "java": tool_version("java", "-version"),
            "maven": tool_version("mvn", "-v"),
            "bwrap": tool_version("bwrap", "--version"),
            "nsjail": tool_version("nsjail", "--help") or "NOT_INSTALLED",
        },
        "anchors": {
            "branch": source_manifest["branch"],
            "commit": source_manifest["commit"],
            "dirty": source_manifest["dirty"],
            "javaSourceHash": source_manifest["java"]["aggregateHash"],
            "sandboxSourceHash": source_manifest["sandbox"]["aggregateHash"],
            "contractBundleHash": bundle_hash,
            "reportSha256": input_manifest["primaryInput"]["actualSha256"],
            "reportHashMatch": input_manifest["primaryInput"]["hashMatch"],
        },
        "artifacts": artifacts,
        "summary": {
            "pass": sum(1 for a in artifacts if a["status"] == "PASS"),
            "fail": sum(1 for a in artifacts if a["status"] == "FAIL"),
            "notExecuted": sum(1 for a in artifacts if a["status"] == "NOT_EXECUTED"),
            "missing": sum(1 for a in artifacts if a["status"] == "MISSING"),
        },
        "nonClaims": [
            "本证据集不代表方案 C 已成为正式基线。",
            "本证据集不代表 Spring AI Alibaba Runtime 已生产可用。",
            "本证据集不代表 Python/Shell 沙箱已通过独立安全审查（C-B03 需独立安全 QA）。",
            "本证据集不代表 DKWS 已生产就绪。",
            "本证据集不代表 GITS UAT 已通过。",
            "性能数据仅为 baseline measurement，非 NFR 达标声明。",
            "Tech Lead 自测不替代独立 QA 签署。",
        ],
    }

    (EVIDENCE_DIR / "POC2_EVIDENCE_MANIFEST.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifest["summary"] | manifest["anchors"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
