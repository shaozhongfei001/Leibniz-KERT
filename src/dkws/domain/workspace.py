"""工作区初始化、检查与概览（FR-WS-001/002/004/005、规格 §7、§8）。"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from ..domain import timeutil
from ..domain.errors import UsageError
from ..infrastructure import locks

TOP_LEVEL_DIRS = ("01_raw", "02_work", "03_core", "04_serve", "90_control")
CONTROL_SUBDIRS = (
    "catalog", "schema", "lineage", "quality", "jobs", "decisions", "locks", "logs",
)
MARKER_FILE = ".dkws_workspace"
MARKER_SCHEMA = "workspace_marker/v1"

# 固定大写控制文件名（§8.2）
FIXED_UPPER_FILES = {
    "MANIFEST.md", "DOCUMENT.md", "NORMALIZED.md", "RELEASE.md", "CURRENT.md",
    "PROJECTION.md", "STATUS.md", "RUN_REPORT.md", "SCHEMA.md", "GATE_REPORT.md",
    "README.md",
}
MACHINE_FILENAME_RE = re.compile(r"^[a-z0-9_]+(\.[a-z0-9]+)?$")
ID_FILENAME_RE = re.compile(r"^[A-Z][A-Z0-9_-]{2,127}(\.[a-z0-9]+)?$")
DOMAIN_DIR_RE = re.compile(r"^[a-z][a-z0-9_]{1,63}$")
BATCH_DIR_RE = re.compile(r"^batch=[A-Z][A-Z0-9_-]{2,127}$")
RUN_DIR_RE = re.compile(r"^run=[A-Z][A-Z0-9_-]{2,127}$")
VERSION_DIR_RE = re.compile(r"^version=\d{4}\.\d{2}\.\d{2}\.\d+$")


@dataclass
class InitResult:
    created_dirs: list[str] = field(default_factory=list)
    created_files: list[str] = field(default_factory=list)
    already_initialized: bool = False


@dataclass
class Finding:
    level: str  # BLOCKER/MAJOR/MINOR/NOTE
    code: str
    message: str
    path: str = ""


def _marker_path(ws: Path) -> Path:
    return Path(ws) / MARKER_FILE


def is_workspace(ws: Path) -> bool:
    return _marker_path(ws).is_file()


def init_workspace(ws: Path, *, force: bool = False,
                   owner: str = "svc_dkws") -> InitResult:
    ws = Path(ws)
    result = InitResult()
    if is_workspace(ws):
        result.already_initialized = True
        return result
    if ws.exists() and any(ws.iterdir()) and not force:
        raise UsageError(
            f"目标目录非空且未初始化: {ws}。如需在非空目录初始化请显式使用 --force"
        )
    ws.mkdir(parents=True, exist_ok=True)
    for d in TOP_LEVEL_DIRS:
        (ws / d).mkdir(parents=True, exist_ok=True)
        result.created_dirs.append(d)
    for d in CONTROL_SUBDIRS:
        (ws / "90_control" / d).mkdir(parents=True, exist_ok=True)
        result.created_dirs.append(f"90_control/{d}")
    marker = {
        "schema": MARKER_SCHEMA,
        "workspace_version": "1",
        "initialized_at": timeutil.ts_utc(),
        "initialized_by": owner,
    }
    (ws / MARKER_FILE).write_text(
        json.dumps(marker, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    result.created_files.append(MARKER_FILE)
    readme = (
        "# 90_control\n\n"
        "跨领域控制目录：catalog（资产目录）、schema（Schema/词表/映射/策略）、\n"
        "lineage（血缘）、quality（质量规则与结果）、jobs（任务状态与报告）、\n"
        "decisions（决策与审核）、locks（写锁）、logs（原始运行日志）。\n\n"
        "权威说明见 DKWS-SPEC-001 V1.0 §7.5。\n"
    )
    (ws / "90_control" / "README.md").write_text(readme, encoding="utf-8")
    result.created_files.append("90_control/README.md")
    return result


def inspect_workspace(ws: Path) -> dict:
    ws = Path(ws)
    if not is_workspace(ws):
        raise UsageError(f"目录不是已初始化的 DKWS 工作区: {ws}（请先运行 dkws init）")
    out: dict = {"workspace": str(ws), "schema": MARKER_SCHEMA}
    for d in TOP_LEVEL_DIRS:
        p = ws / d
        if not p.is_dir():
            out[d] = {"present": False}
            continue
        entry: dict = {"present": True, "domains": [], "subdirs": []}
        try:
            items = sorted(p.iterdir())
        except OSError:
            items = []
        for it in items:
            if it.is_dir():
                if DOMAIN_DIR_RE.match(it.name):
                    entry["domains"].append(it.name)
                else:
                    entry["subdirs"].append(it.name)
            elif it.is_file():
                entry.setdefault("files", []).append(it.name)
        out[d] = entry
    # CURRENT 指针概览
    current_ptrs = []
    for core_domain in (ws / "03_core").glob("*"):
        if core_domain.is_dir():
            cur = core_domain / "CURRENT.md"
            if cur.is_file():
                current_ptrs.append(f"03_core/{core_domain.name}/CURRENT.md")
    for svc in (ws / "04_serve").glob("*"):
        if svc.is_dir():
            cur = svc / "CURRENT.md"
            if cur.is_file():
                current_ptrs.append(f"04_serve/{svc.name}/CURRENT.md")
    out["current_pointers"] = current_ptrs
    # 锁概览
    out["stale_locks"] = len(locks.list_stale_locks(ws))
    return out


def check_workspace(ws: Path, *, mode: str = "fast") -> list[Finding]:
    """工作区一致性检查（FR-WS-005）。

    fast：结构（目录、文件名规范、UTF-8 无 BOM）。
    full：在 fast 基础上校验 CURRENT 指针目标存在与发布清单哈希（后续阶段增强）。
    """
    if mode not in ("fast", "full"):
        raise UsageError(f"未知检查模式: {mode!r}（fast/full）")
    ws = Path(ws)
    findings: list[Finding] = []
    if not is_workspace(ws):
        return [Finding("BLOCKER", "WS_MISSING_MARKER", f"缺少 {MARKER_FILE} 标记，未初始化", MARKER_FILE)]

    for d in TOP_LEVEL_DIRS:
        p = ws / d
        if not p.is_dir():
            findings.append(Finding("BLOCKER", "WS_MISSING_DIR", f"缺少一级目录 {d}", d))

    ctl = ws / "90_control"
    for sd in CONTROL_SUBDIRS:
        if not (ctl / sd).is_dir():
            findings.append(Finding("BLOCKER", "WS_MISSING_CTL", f"缺少控制子目录 90_control/{sd}", f"90_control/{sd}"))

    _check_text_files(ws, findings)
    if mode == "full":
        _check_current_pointers(ws, findings)
    return findings


def _check_text_files(ws: Path, findings: list[Finding]):
    for p in sorted(ws.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(ws).as_posix()
        if rel.startswith(".git") or p.name == MARKER_FILE:
            continue
        # Kùzu 图谱投影（IMP-ADR-011）：二进制可重建层（单文件 graph + graph.PROJECTION.json）
        if "/graph" in rel:
            continue
        name_exempt = p.name in FIXED_UPPER_FILES or rel.startswith("90_control/logs/")
        if not name_exempt and not MACHINE_FILENAME_RE.match(p.name) \
                and not ID_FILENAME_RE.match(p.name):
            findings.append(
                Finding("MAJOR", "WS_BAD_FILENAME", f"文件名不符合 snake_case 规范: {p.name}", rel)
            )
        if p.suffix in (".md", ".log", ".json", ".txt"):
            try:
                with open(p, "rb") as f:
                    head = f.read(3)
                if head == b"\xef\xbb\xbf":
                    findings.append(Finding("MAJOR", "WS_BOM", "文件含 UTF-8 BOM（§8.1 禁止）", rel))
            except OSError:
                continue


def _check_current_pointers(ws: Path, findings: list[Finding]):
    for scope_root in (ws / "03_core", ws / "04_serve"):
        if not scope_root.is_dir():
            continue
        for scope in sorted(scope_root.iterdir()):
            if not scope.is_dir():
                continue
            cur = scope / "CURRENT.md"
            if not cur.is_file():
                continue
            try:
                text = cur.read_text(encoding="utf-8")
            except OSError:
                continue
            import re as _re
            m = _re.search(r"^target_version:\s*\"?([^\n\" ]+)", text, _re.M)
            if m:
                target = m.group(1)
                if not (scope / f"version={target}").is_dir():
                    findings.append(
                        Finding("BLOCKER", "WS_DANGLING_CURRENT",
                                f"CURRENT 指向不存在的版本 {target}", cur.relative_to(ws).as_posix())
                    )
