#!/usr/bin/env python3
"""JR-1 内部契约端到端验证脚本。

一条命令验证「Python Core 与 Java Skill Runtime 对同一份内部契约
具备可验证的消费/提供能力」，检查项对应任务包 JR-1 §6.5：

1. 受控契约文件齐备（6 份 Schema + 1 份 OpenAPI）
2. 所有 JSON Schema 可解析且自身合法（Draft 2020-12）
3. 内部 OpenAPI 可解析，且其 ``$ref`` 全部指向受控 Schema
4. 所有示例通过对应 Schema
5. Python 侧契约测试通过
6. Java 侧契约测试通过
7. 契约 hash 可重算，且 Python 重算值 == Java 重算值 == 证据记录值

用法::

    python scripts/verify_jr1_internal_contract.py
    python scripts/verify_jr1_internal_contract.py --skip-java   # 无 Maven 环境时
    python scripts/verify_jr1_internal_contract.py --report evidence/jr1/report.md

退出码：0 全部通过；1 存在失败项。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_DIR = ROOT / "docs" / "contracts" / "internal"
SCHEMA_DIR = CONTRACT_DIR / "schemas"
EXAMPLE_DIR = CONTRACT_DIR / "examples"
OPENAPI_FILE = CONTRACT_DIR / "openapi" / "dkws-skill-runtime-internal-v1.yaml"
EVIDENCE_DIR = ROOT / "evidence" / "jr1"
HASH_EVIDENCE = EVIDENCE_DIR / "internal-contract-hash.txt"
JAVA_POC = ROOT / "poc" / "spring-ai-alibaba-skill-runtime"

#: 受控契约文件（与 scripts/internal_contract_hash.py 白名单一致）。
CONTROLLED_FILES = (
    "openapi/dkws-skill-runtime-internal-v1.yaml",
    "schemas/execution-plan.schema.json",
    "schemas/execution-result.schema.json",
    "schemas/tool-call-receipt.schema.json",
    "schemas/model-call-receipt.schema.json",
    "schemas/runtime-error.schema.json",
    "schemas/runtime-capabilities.schema.json",
)

SCHEMA_FILES = tuple(
    name.split("/", 1)[1] for name in CONTROLLED_FILES if name.startswith("schemas/")
)

#: Schema → 应通过该 Schema 的示例文件。
SCHEMA_EXAMPLES: dict[str, tuple[str, ...]] = {
    "execution-plan.schema.json": (
        "execution-plan.valid.json",
        "execution-plan.minimal.json",
    ),
    "execution-result.schema.json": (
        "execution-result.valid.json",
        "execution-result.degraded.json",
    ),
    "tool-call-receipt.schema.json": (
        "tool-call-receipt.valid.json",
        "tool-call-receipt.blocked.json",
    ),
    "model-call-receipt.schema.json": (
        "model-call-receipt.valid.json",
        "model-call-receipt.error.json",
    ),
    "runtime-error.schema.json": (
        "runtime-error.idempotency-conflict.json",
        "runtime-error.deadline-exceeded.json",
    ),
    "runtime-capabilities.schema.json": (
        "runtime-capabilities.valid.json",
        "runtime-capabilities.minimal.json",
    ),
}

_RFC3339 = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$"
)


@dataclass
class CheckResult:
    """单项检查结果。"""

    name: str
    passed: bool
    detail: str = ""
    duration_s: float = 0.0


@dataclass
class Report:
    """验证报告聚合。"""

    results: list[CheckResult] = field(default_factory=list)
    bundle_hash: str | None = None

    def add(self, result: CheckResult) -> None:
        """记录一项结果并即时打印。"""
        self.results.append(result)
        mark = "PASS" if result.passed else "FAIL"
        line = f"[{mark}] {result.name}"
        if result.duration_s >= 0.05:
            line += f" ({result.duration_s:.1f}s)"
        print(line)
        if result.detail:
            for text in result.detail.splitlines():
                print(f"       {text}")

    @property
    def ok(self) -> bool:
        """全部检查是否通过。"""
        return all(r.passed for r in self.results)


def _python_exe() -> str:
    """优先使用仓库虚拟环境解释器，保证依赖齐备。"""
    venv = ROOT / ".venv" / "bin" / "python"
    return str(venv) if venv.is_file() else sys.executable


def _format_checker():
    """构建带 RFC3339 ``date-time`` 断言的 FormatChecker。"""
    from jsonschema import FormatChecker

    checker = FormatChecker()

    @checker.checks("date-time", raises=())
    def _check(value: object) -> bool:
        return not isinstance(value, str) or bool(_RFC3339.match(value))

    return checker


def _build_registry():
    """构建按文件名解析相对 ``$ref`` 的注册表。"""
    from referencing import Registry, Resource

    resources = []
    for name in SCHEMA_FILES:
        contents = json.loads((SCHEMA_DIR / name).read_text(encoding="utf-8"))
        resources.append((name, Resource.from_contents(contents)))
    return Registry().with_resources(resources)


# --------------------------------------------------------------------------
# 检查项
# --------------------------------------------------------------------------


def check_files_present(report: Report) -> None:
    """检查 1：受控契约文件齐备。"""
    missing = [rel for rel in CONTROLLED_FILES if not (CONTRACT_DIR / rel).is_file()]
    report.add(
        CheckResult(
            "受控契约文件齐备（6 Schema + 1 OpenAPI）",
            not missing,
            "" if not missing else f"缺失: {missing}",
        )
    )

    on_disk = sorted(p.name for p in SCHEMA_DIR.glob("*.json"))
    extra = set(on_disk) - set(SCHEMA_FILES)
    report.add(
        CheckResult(
            "Schema 目录无白名单外文件（防影子契约）",
            not extra,
            "" if not extra else f"多余: {sorted(extra)}",
        )
    )


def check_schemas_parseable(report: Report) -> None:
    """检查 2：Schema 可解析且自身合法。"""
    from jsonschema import Draft202012Validator

    failures: list[str] = []
    for name in SCHEMA_FILES:
        try:
            schema = json.loads((SCHEMA_DIR / name).read_text(encoding="utf-8"))
            Draft202012Validator.check_schema(schema)
            if schema.get("additionalProperties") is not False:
                failures.append(f"{name}: 未声明 additionalProperties=false")
            if not schema.get("required"):
                failures.append(f"{name}: 未声明 required")
        except Exception as exc:  # noqa: BLE001 - 汇总所有解析/校验失败
            failures.append(f"{name}: {exc}")

    report.add(
        CheckResult(
            "全部 JSON Schema 可解析且符合 Draft 2020-12",
            not failures,
            "\n".join(failures),
        )
    )


def check_openapi(report: Report) -> None:
    """检查 3：OpenAPI 可解析且引用受控。"""
    import yaml

    failures: list[str] = []
    try:
        doc = yaml.safe_load(OPENAPI_FILE.read_text(encoding="utf-8"))
        if not str(doc.get("openapi", "")).startswith("3."):
            failures.append("openapi 版本非 3.x")
        if not doc.get("paths"):
            failures.append("未定义任何路径")
        for path in doc.get("paths", {}):
            if not path.startswith("/internal/"):
                failures.append(f"出现非内部路径: {path}")

        refs: list[str] = []

        def walk(node: Any) -> None:
            if isinstance(node, dict):
                for key, value in node.items():
                    if key == "$ref" and isinstance(value, str):
                        refs.append(value)
                    else:
                        walk(value)
            elif isinstance(node, list):
                for item in node:
                    walk(item)

        walk(doc)
        if not refs:
            failures.append("未通过 $ref 复用 Schema")
        for ref in refs:
            if ref.startswith("#") or "schemas/" not in ref:
                continue
            target = (OPENAPI_FILE.parent / ref).resolve()
            if not target.is_file():
                failures.append(f"$ref 目标不存在: {ref}")
            elif target.name not in SCHEMA_FILES:
                failures.append(f"$ref 指向白名单外 Schema: {ref}")
    except Exception as exc:  # noqa: BLE001
        failures.append(str(exc))

    report.add(
        CheckResult(
            "内部 OpenAPI 可解析且 $ref 全部指向受控 Schema",
            not failures,
            "\n".join(failures),
        )
    )


def check_examples(report: Report) -> None:
    """检查 4：所有示例通过对应 Schema。"""
    from jsonschema import Draft202012Validator

    registry = _build_registry()
    checker = _format_checker()
    failures: list[str] = []
    total = 0

    for schema_name, examples in SCHEMA_EXAMPLES.items():
        schema = json.loads((SCHEMA_DIR / schema_name).read_text(encoding="utf-8"))
        validator = Draft202012Validator(
            schema, registry=registry, format_checker=checker
        )
        for example_name in examples:
            total += 1
            path = EXAMPLE_DIR / example_name
            if not path.is_file():
                failures.append(f"{example_name}: 文件缺失")
                continue
            instance = json.loads(path.read_text(encoding="utf-8"))
            for error in validator.iter_errors(instance):
                failures.append(
                    f"{example_name} -> {schema_name}: "
                    f"{list(error.path)} {error.message}"
                )

    registered = {e for exs in SCHEMA_EXAMPLES.values() for e in exs}
    on_disk = {p.name for p in EXAMPLE_DIR.glob("*.json")}
    if on_disk - registered:
        failures.append(f"存在未登记示例: {sorted(on_disk - registered)}")

    report.add(
        CheckResult(
            f"全部契约示例通过 Schema 校验（{total} 份）",
            not failures,
            "\n".join(failures),
        )
    )


def _run(cmd: list[str], cwd: Path, log_path: Path | None) -> tuple[bool, str]:
    """执行子进程并可选落盘日志。"""
    started = time.time()
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=False)
    output = proc.stdout + proc.stderr
    if log_path is not None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(
            f"$ {' '.join(cmd)}\n(cwd={cwd})\n"
            f"exit={proc.returncode} elapsed={time.time() - started:.1f}s\n\n{output}",
            encoding="utf-8",
        )
    return proc.returncode == 0, output


def check_python_tests(report: Report, write_logs: bool) -> None:
    """检查 5：Python 侧契约测试通过。

    注意：``pyproject.toml`` 的 ``addopts`` 已含 ``-q``，此处不再重复传入，
    否则会进入 extra-quiet 模式而丢失 ``N passed`` 摘要行。
    """
    started = time.time()
    log = EVIDENCE_DIR / "python-contract-test.log" if write_logs else None
    ok, output = _run([_python_exe(), "-m", "pytest", "tests/contract"], ROOT, log)
    summary = next(
        (
            line.strip()
            for line in reversed(output.splitlines())
            if re.search(r"\d+ (passed|failed|error)", line)
        ),
        "",
    )
    report.add(
        CheckResult(
            "Python 侧契约测试通过（tests/contract）",
            ok,
            summary if summary else output[-800:],
            time.time() - started,
        )
    )


def check_java_tests(report: Report, write_logs: bool, skip: bool) -> None:
    """检查 6：Java 侧契约测试通过。"""
    if skip:
        report.add(CheckResult("Java 侧契约测试（--skip-java 显式跳过）", False,
                               "跳过即视为未验证，不得据此宣称双端通过"))
        return
    if shutil.which("mvn") is None:
        report.add(
            CheckResult(
                "Java 侧契约测试通过", False, "未找到 mvn，无法验证 Java 侧"
            )
        )
        return

    started = time.time()
    log = EVIDENCE_DIR / "java-contract-test.log" if write_logs else None
    ok, output = _run(
        ["mvn", "-o", "-B", "test", "-Dtest=InternalContract*Test",
         "-DfailIfNoTests=false"],
        JAVA_POC,
        log,
    )
    summary = next(
        (
            line.strip()
            for line in reversed(output.splitlines())
            if "Tests run:" in line
        ),
        "",
    )
    report.add(
        CheckResult(
            "Java 侧契约测试通过（poc/spring-ai-alibaba-skill-runtime）",
            ok,
            re.sub(r"\x1b\[[0-9;]*m", "", summary) or output[-800:],
            time.time() - started,
        )
    )


def _sha256_file(path: Path) -> str:
    """计算文件 SHA-256。"""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _recompute_bundle_hash() -> str:
    """按 internal_contract_hash.py 相同算法独立重算 bundle 哈希。"""
    entries = sorted(
        ({"path": rel, "sha256": _sha256_file(CONTRACT_DIR / rel)}
         for rel in CONTROLLED_FILES),
        key=lambda e: e["path"],
    )
    digest = hashlib.sha256()
    for entry in entries:
        digest.update(entry["path"].encode("utf-8"))
        digest.update(b"\0")
        digest.update(entry["sha256"].encode("ascii"))
        digest.update(b"\0")
    return digest.hexdigest()


def check_hash(report: Report) -> None:
    """检查 7：契约哈希可重算并三方一致。"""
    failures: list[str] = []

    script_hash: str | None = None
    ok, output = _run(
        [_python_exe(), "scripts/internal_contract_hash.py"], ROOT, None
    )
    if not ok:
        failures.append(f"哈希脚本执行失败: {output[-400:]}")
    else:
        try:
            script_hash = json.loads(output)["bundle_hash"]
        except Exception as exc:  # noqa: BLE001
            failures.append(f"哈希脚本输出不可解析: {exc}")

    independent = _recompute_bundle_hash()
    if script_hash and script_hash != independent:
        failures.append(f"脚本值={script_hash} 独立重算={independent} 不一致")

    recorded: str | None = None
    if not HASH_EVIDENCE.is_file():
        failures.append(f"缺失哈希证据文件: {HASH_EVIDENCE}")
    else:
        content = HASH_EVIDENCE.read_text(encoding="utf-8")
        if "PENDING_COMPUTE" in content:
            failures.append("证据文件残留 PENDING_COMPUTE 占位符")
        for line in content.splitlines():
            if line.strip().startswith("bundle_hash="):
                recorded = line.split("=", 1)[1].strip()
                break
        if recorded is None:
            failures.append("证据文件未记录 bundle_hash=")
        elif recorded != independent:
            failures.append(f"证据={recorded} 当前={independent} 漂移")

    java_constant = _java_contract_hash_constant()
    if java_constant is None:
        failures.append("未能从 Java 源码读取 CONTRACT_HASH 常量")
    elif java_constant != independent:
        failures.append(f"Java 内置={java_constant} 当前={independent} 漂移")

    report.bundle_hash = independent
    report.add(
        CheckResult(
            "契约 hash 可重算且 Python/Java/证据三方一致",
            not failures,
            "\n".join(failures) if failures else f"bundle_hash={independent}",
        )
    )


def _java_contract_hash_constant() -> str | None:
    """从 Java 控制器源码提取内置契约哈希常量。"""
    source = (
        JAVA_POC
        / "src/main/java/com/dkws/skillruntime/controller/InternalRuntimeController.java"
    )
    if not source.is_file():
        return None
    match = re.search(
        r"CONTRACT_HASH\s*=\s*\n?\s*\"([0-9a-f]{64})\"",
        source.read_text(encoding="utf-8"),
    )
    return match.group(1) if match else None


def write_markdown_report(report: Report, path: Path) -> None:
    """输出 Markdown 验证报告。"""
    lines = [
        "# JR-1 内部契约端到端验证报告",
        "",
        "- 生成命令：`python scripts/verify_jr1_internal_contract.py`",
        f"- 总体结果：**{'PASS' if report.ok else 'FAIL'}**",
        f"- 契约 bundle hash：`{report.bundle_hash or 'N/A'}`",
        "",
        "| # | 检查项 | 结果 | 说明 |",
        "|---|--------|------|------|",
    ]
    for index, result in enumerate(report.results, start=1):
        detail = result.detail.replace("\n", "<br>").replace("|", "\\|")
        lines.append(
            f"| {index} | {result.name} | "
            f"{'PASS' if result.passed else 'FAIL'} | {detail} |"
        )
    lines += [
        "",
        "## 非声明",
        "",
        "- 本报告不代表 DKWS 已生产就绪。",
        "- 本报告不代表 GITS UAT 已通过。",
        "- 本报告不代表安全审计已完成。",
        "- 本报告不代表 Java Runtime 已生产可用。",
        "- 本报告不代表 C′ 混合架构已成为正式基线。",
        "- Feature Pilot 不代替 Owner、Tech Lead 或 Independent QA 签署。",
        "",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    """执行全部检查并返回退出码。"""
    parser = argparse.ArgumentParser(description="JR-1 内部契约端到端验证")
    parser.add_argument(
        "--skip-java", action="store_true", help="跳过 Java 侧测试（无 Maven 环境）"
    )
    parser.add_argument(
        "--no-logs", action="store_true", help="不写测试日志到 evidence/jr1/"
    )
    parser.add_argument(
        "--report", type=Path, default=None, help="输出 Markdown 报告到指定路径"
    )
    args = parser.parse_args()

    print("=" * 72)
    print("JR-1 内部契约端到端验证")
    print("=" * 72)

    report = Report()
    check_files_present(report)
    check_schemas_parseable(report)
    check_openapi(report)
    check_examples(report)
    check_python_tests(report, write_logs=not args.no_logs)
    check_java_tests(report, write_logs=not args.no_logs, skip=args.skip_java)
    check_hash(report)

    passed = sum(1 for r in report.results if r.passed)
    print("-" * 72)
    print(f"结果: {passed}/{len(report.results)} 项通过")
    print(f"契约 bundle hash: {report.bundle_hash}")
    print("总体: " + ("PASS" if report.ok else "FAIL"))

    if args.report is not None:
        write_markdown_report(report, args.report)
        print(f"报告已写入: {args.report}")

    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
