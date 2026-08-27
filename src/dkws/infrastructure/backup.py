"""备份与恢复（M2.6）。

设计原则
--------
1. **备份产物落工作区外**：``check_workspace`` 会对工作区内的非规范文件名
   （如 ``.db-wal``、含时间戳的连字符命名）报 ``WS_BAD_FILENAME``，
   把备份写进工作区会污染一致性检查并打破既有门禁。
2. **Runtime DB 必须在线备份**：WAL 模式下直接拷贝 ``.db`` 文件会与
   ``-wal``/``-shm`` 不一致，故一律走 :meth:`RuntimeStore.backup_to`
   （SQLite 在线备份 API）。
3. **一致性点**：备份时同时捕获 ``CURRENT.md`` 指针与 DB 快照，
   写入 manifest，使恢复后可验证「知识版本 ↔ 运行态」是否匹配。
4. **不自行设定 RPO/RTO**：备份频率、保留策略、演练频率属 Owner 决策，
   本模块只提供能力与参数，不内置业务默认值。
5. **恢复不破坏 M2.4 语义**：不重置 ``attempts``、不清除 ``dead_letter``、
   不复位仍持有有效 lease 的 Job（这些行为受 ``tests/recovery`` 锁定）。
"""

from __future__ import annotations

import json
import shutil
import tarfile
import time
from dataclasses import dataclass, field
from pathlib import Path

from ..domain import hashing, timeutil
from ..domain.errors import ConflictError, UsageError
from ..domain.workspace import (
    CONTROL_SUBDIRS,
    TOP_LEVEL_DIRS,
    is_workspace,
)

#: 工作区标记文件名（无此文件所有命令拒绝执行）
WORKSPACE_MARKER = ".dkws_workspace"

#: Runtime Store 相对工作区的路径
RUNTIME_DB_REL = Path("90_control") / "runtime" / "runtime.db"

#: manifest 文件名
MANIFEST_NAME = "BACKUP_MANIFEST.json"

#: 备份集内的数据子目录名
PAYLOAD_DIR = "payload"

#: 必须备份的顶层目录（不可重建）
#:
#: - ``01_raw``：原始批次，不可重建（``remove_rebuildable_tree`` 拒绝删除）
#: - ``03_core``：唯一知识权威源（ADR-012 边界）
#: - ``90_control``：治理与审计，不可重建
REQUIRED_DIRS: tuple[str, ...] = ("01_raw", "03_core", "90_control")

#: 可选备份的顶层目录（可重建，但重建耗时计入 RTO）
#:
#: ``02_work`` 看似可重建，但 ``04_serve/*/datasets/`` 的重建依赖
#: ``02_work/*/run=*/normalized/*.parquet``；不备份会导致重建后数据集缺失。
#: 故默认**纳入**备份，可显式排除以缩小体积。
OPTIONAL_DIRS: tuple[str, ...] = ("02_work", "04_serve")

#: 一律排除的路径片段（含运行期状态与不可迁移内容）
EXCLUDE_PATTERNS: tuple[str, ...] = (
    "90_control/locks",       # 锁含 pid/host，恢复后必然失效
    "90_control/runtime",     # DB 单独走在线备份，避免热文件不一致
    "__pycache__",
    ".pytest_cache",
)


@dataclass
class BackupManifest:
    """备份清单：记录范围、一致性点与校验信息。

    Attributes:
        backup_id: 备份标识。
        created_at: 创建时间（UTC ISO8601）。
        workspace: 源工作区路径。
        included_dirs: 实际纳入的顶层目录。
        excluded_dirs: 显式排除的顶层目录。
        consistency_point: 一致性点（CURRENT 指针 + DB schema 版本）。
        files: 文件清单（相对路径 → sha256）。
        runtime_db: Runtime DB 备份信息。
        service_version: 服务版本。
        notes: 说明与非声明事项。
    """

    backup_id: str
    created_at: str
    workspace: str
    included_dirs: list[str] = field(default_factory=list)
    excluded_dirs: list[str] = field(default_factory=list)
    consistency_point: dict = field(default_factory=dict)
    files: dict = field(default_factory=dict)
    runtime_db: dict = field(default_factory=dict)
    service_version: str = ""
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        """转为可序列化字典。"""
        return {
            "schema": "dkws_backup_manifest/v1",
            "backup_id": self.backup_id,
            "created_at": self.created_at,
            "workspace": self.workspace,
            "included_dirs": sorted(self.included_dirs),
            "excluded_dirs": sorted(self.excluded_dirs),
            "consistency_point": self.consistency_point,
            "file_count": len(self.files),
            "files": self.files,
            "runtime_db": self.runtime_db,
            "service_version": self.service_version,
            "notes": self.notes,
        }

    @property
    def total_bytes(self) -> int:
        """备份文件总字节数。"""
        return sum(int(info.get("size", 0)) for info in self.files.values())


def _should_exclude(rel_path: str) -> bool:
    """判断相对路径是否应被排除。"""
    normalized = rel_path.replace("\\", "/")
    return any(pattern in normalized for pattern in EXCLUDE_PATTERNS)


def capture_consistency_point(ws: Path) -> dict:
    """捕获备份时刻的一致性点。

    同时记录知识版本指针与运行态 DB 版本，使恢复后可验证二者是否匹配。
    这是评审明确指出的缺口：单独备份任一侧都无法保证恢复后语义一致。

    Returns:
        含 ``current_pointers``、``runtime_schema_version`` 等字段的字典。
    """
    point: dict = {"captured_at": timeutil.ts_utc()}

    pointers: dict[str, str] = {}
    serve_root = ws / "04_serve"
    if serve_root.is_dir():
        for current in sorted(serve_root.glob("*/CURRENT.md")):
            try:
                text = current.read_text(encoding="utf-8")
            except OSError:
                continue
            for line in text.splitlines():
                stripped = line.strip()
                if stripped.startswith("target_version:"):
                    value = stripped.split(":", 1)[1].strip().strip('"')
                    pointers[current.parent.name] = value
                    break
    point["current_pointers"] = pointers

    core_versions: dict[str, list[str]] = {}
    core_root = ws / "03_core"
    if core_root.is_dir():
        for service_dir in sorted(p for p in core_root.iterdir() if p.is_dir()):
            versions = sorted(v.name for v in service_dir.glob("version=*"))
            if versions:
                core_versions[service_dir.name] = versions
    point["core_versions"] = core_versions

    db_path = ws / RUNTIME_DB_REL
    if db_path.is_file():
        try:
            from .runtime_store import RuntimeStore

            store = RuntimeStore(db_path)
            point["runtime_schema_version"] = store.schema_version()
            point["runtime_queue"] = store.queue_stats()
        except Exception as exc:  # noqa: BLE001 - 一致性点采集失败不应中断备份
            point["runtime_error"] = str(exc)
    else:
        point["runtime_schema_version"] = None
    return point


# ---------------------------------------------------------------- 备份


def create_backup(ws: Path, dest_dir: Path, *, backup_id: str | None = None,
                  include_optional: bool = True,
                  exclude_dirs: tuple[str, ...] = (),
                  service_version: str = "",
                  archive: bool = False) -> tuple[Path, BackupManifest]:
    """创建工作区备份。

    Args:
        ws: 源工作区（必须已初始化）。
        dest_dir: 备份输出根目录，**必须在工作区之外**。
        backup_id: 备份标识，缺省按时间戳生成。
        include_optional: 是否纳入可重建目录（``02_work``/``04_serve``）。
        exclude_dirs: 额外排除的顶层目录。
        service_version: 记入 manifest 的服务版本。
        archive: 是否额外打包为 ``.tar.gz``。

    Returns:
        ``(备份集目录, manifest)``；``archive=True`` 时第一项为压缩包路径。

    Raises:
        UsageError: 源目录不是工作区。
        ConflictError: 目标目录位于工作区内，或备份集已存在。
    """
    ws = Path(ws).resolve()
    dest_dir = Path(dest_dir).resolve()
    if not is_workspace(ws):
        raise UsageError(f"目录不是已初始化的 DKWS 工作区：{ws}")
    if dest_dir == ws or ws in dest_dir.parents:
        # 备份产物落工作区内会触发 WS_BAD_FILENAME 并打破 check_workspace
        raise ConflictError(
            f"备份目标不得位于工作区内（会污染一致性检查）：{dest_dir}")

    bid = backup_id or f"backup-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}"
    root = dest_dir / bid
    if root.exists():
        raise ConflictError(f"备份集已存在：{root}")
    payload = root / PAYLOAD_DIR
    payload.mkdir(parents=True)

    manifest = BackupManifest(
        backup_id=bid,
        created_at=timeutil.ts_utc(),
        workspace=str(ws),
        service_version=service_version,
        consistency_point=capture_consistency_point(ws),
    )

    selected = list(REQUIRED_DIRS)
    if include_optional:
        selected.extend(OPTIONAL_DIRS)
    selected = [d for d in selected if d not in exclude_dirs]
    manifest.included_dirs = selected
    manifest.excluded_dirs = sorted(set(TOP_LEVEL_DIRS) - set(selected))

    # 工作区标记：缺失会导致恢复后所有命令拒绝执行
    marker = ws / WORKSPACE_MARKER
    if marker.is_file():
        shutil.copy2(marker, payload / WORKSPACE_MARKER)
        manifest.files[WORKSPACE_MARKER] = {
            "sha256": hashing.sha256_file(marker),
            "size": marker.stat().st_size,
        }

    for top in selected:
        src = ws / top
        if not src.is_dir():
            continue
        for item in sorted(src.rglob("*")):
            rel = item.relative_to(ws).as_posix()
            if _should_exclude(rel):
                continue
            target = payload / rel
            if item.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)
            manifest.files[rel] = {
                "sha256": hashing.sha256_file(item),
                "size": item.stat().st_size,
            }

    manifest.runtime_db = _backup_runtime_db(ws, payload)

    manifest.notes = [
        "本备份不代表已通过灾备演练验收。",
        "RPO/RTO 与备份频率、保留策略属 Owner 决策，本清单不预设业务默认值。",
        ("90_control/locks 已排除：锁含 pid/host，恢复后必然失效，"
         "应由 dkws recover --clear-expired 清理。"),
        "Runtime DB 经 SQLite 在线备份 API 生成一致性快照，未直接拷贝热文件。",
    ]

    (root / MANIFEST_NAME).write_text(
        json.dumps(manifest.as_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8")

    if archive:
        tar_path = dest_dir / f"{bid}.tar.gz"
        with tarfile.open(tar_path, "w:gz") as tar:
            tar.add(root, arcname=bid)
        return tar_path, manifest
    return root, manifest


def _backup_runtime_db(ws: Path, payload: Path) -> dict:
    """用 SQLite 在线备份 API 快照 Runtime DB。

    WAL 模式下直接拷贝 ``.db`` 会与 ``-wal``/``-shm`` 不一致，
    故必须走 :meth:`RuntimeStore.backup_to`。
    """
    db_path = ws / RUNTIME_DB_REL
    if not db_path.is_file():
        return {"present": False,
                "note": "未启用 Runtime Store，无运行态需备份"}
    from .runtime_store import RuntimeStore

    store = RuntimeStore(db_path)
    target = payload / RUNTIME_DB_REL
    target.parent.mkdir(parents=True, exist_ok=True)
    store.backup_to(target)
    return {
        "present": True,
        "relative_path": RUNTIME_DB_REL.as_posix(),
        "sha256": hashing.sha256_file(target),
        "size": target.stat().st_size,
        "schema_version": store.schema_version(),
        "method": "sqlite_online_backup",
        "stats": store.stats(),
    }


# ---------------------------------------------------------------- 校验


def verify_backup(backup_root: Path) -> list[str]:
    """校验备份集完整性，返回问题列表（空表示通过）。

    逐文件比对 sha256，确保备份未被截断或篡改。
    """
    backup_root = Path(backup_root)
    manifest_file = backup_root / MANIFEST_NAME
    if not manifest_file.is_file():
        return [f"缺少清单文件：{MANIFEST_NAME}"]
    try:
        manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"清单不可解析：{exc}"]

    problems: list[str] = []
    payload = backup_root / PAYLOAD_DIR
    if not payload.is_dir():
        return [f"缺少数据目录：{PAYLOAD_DIR}"]

    for rel, info in (manifest.get("files") or {}).items():
        target = payload / rel
        if not target.is_file():
            problems.append(f"文件缺失：{rel}")
            continue
        actual = hashing.sha256_file(target)
        if actual != info.get("sha256"):
            problems.append(f"哈希不匹配：{rel}")

    db_info = manifest.get("runtime_db") or {}
    if db_info.get("present"):
        db_file = payload / db_info["relative_path"]
        if not db_file.is_file():
            problems.append("Runtime DB 快照缺失")
        elif hashing.sha256_file(db_file) != db_info.get("sha256"):
            problems.append("Runtime DB 快照哈希不匹配")
    return problems


def load_manifest(backup_root: Path) -> dict:
    """读取备份清单。"""
    path = Path(backup_root) / MANIFEST_NAME
    if not path.is_file():
        raise UsageError(f"备份集缺少清单：{path}")
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------- 恢复


@dataclass
class RestoreResult:
    """恢复结果。

    Attributes:
        target: 恢复到的工作区路径。
        restored_files: 恢复的文件数。
        consistency: 一致性校验结果。
        findings: ``check_workspace`` 的问题列表（字符串化）。
        cleared_locks: 清理的过期锁数量。
        warnings: 恢复过程中的告警。
    """

    target: str
    restored_files: int = 0
    consistency: dict = field(default_factory=dict)
    findings: list[str] = field(default_factory=list)
    cleared_locks: int = 0
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """是否无阻断级问题（BLOCKER 级视为恢复未达可用状态）。"""
        return not self.blockers

    @property
    def blockers(self) -> list[str]:
        """阻断级问题列表。"""
        return [f for f in self.findings if f.startswith("BLOCKER")]

    def as_dict(self) -> dict:
        """转为可序列化字典。"""
        return {"target": self.target, "restored_files": self.restored_files,
                "consistency": self.consistency, "findings": self.findings,
                "blockers": self.blockers, "cleared_locks": self.cleared_locks,
                "warnings": self.warnings, "ok": self.ok}


def restore_backup(backup_root: Path, target: Path, *,
                   force: bool = False, verify_first: bool = True) -> RestoreResult:
    """从备份集恢复到目标目录。

    Args:
        backup_root: 备份集目录（含 ``BACKUP_MANIFEST.json``）。
        target: 恢复目标目录。
        force: 目标非空时是否允许覆盖。
        verify_first: 恢复前是否先校验备份完整性（**强烈建议保持 True**，
            避免用损坏的备份覆盖现场）。

    Returns:
        :class:`RestoreResult`，含一致性校验与结构检查结果。

    Raises:
        UsageError: 备份集不合法。
        ConflictError: 备份校验失败，或目标非空且未指定 ``force``。
    """
    backup_root = Path(backup_root).resolve()
    target = Path(target).resolve()

    if verify_first:
        problems = verify_backup(backup_root)
        if problems:
            raise ConflictError(
                "备份完整性校验失败，拒绝恢复（避免用损坏备份覆盖现场）："
                + "；".join(problems[:5]))

    manifest = load_manifest(backup_root)
    payload = backup_root / PAYLOAD_DIR

    if target.exists() and any(target.iterdir()) and not force:
        raise ConflictError(f"目标目录非空，需显式 force：{target}")

    result = RestoreResult(target=str(target))
    target.mkdir(parents=True, exist_ok=True)

    for item in sorted(payload.rglob("*")):
        rel = item.relative_to(payload)
        dest = target / rel
        if item.is_dir():
            dest.mkdir(parents=True, exist_ok=True)
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, dest)
        result.restored_files += 1

    # 恢复后必须补齐 init 会创建的目录：备份可能因空目录未被 rglob 捕获而缺失
    for top in TOP_LEVEL_DIRS:
        (target / top).mkdir(parents=True, exist_ok=True)
    for sub in CONTROL_SUBDIRS:
        (target / "90_control" / sub).mkdir(parents=True, exist_ok=True)

    if not (target / WORKSPACE_MARKER).is_file():
        result.warnings.append(
            f"备份中缺少 {WORKSPACE_MARKER}，恢复后工作区将不可用；"
            f"需确认备份是否完整")

    result.cleared_locks = _clear_stale_locks(target)
    result.consistency = verify_consistency(target, manifest)
    result.findings = _check_structure(target)
    return result


def _clear_stale_locks(ws: Path) -> int:
    """清理残留锁文件。

    锁内含 ``pid``/``host``，恢复到新主机后必然失效；
    若不清理会导致后续写操作被无主锁阻塞。
    """
    lock_dir = ws / "90_control" / "locks"
    if not lock_dir.is_dir():
        return 0
    cleared = 0
    for lock_file in sorted(lock_dir.rglob("*")):
        if lock_file.is_file():
            lock_file.unlink()
            cleared += 1
    return cleared


def _check_structure(ws: Path) -> list[str]:
    """运行工作区一致性检查并字符串化结果。"""
    try:
        from ..domain.workspace import check_workspace

        findings = check_workspace(ws, mode="full")
    except Exception as exc:  # noqa: BLE001 - 检查失败本身也是一条发现
        return [f"BLOCKER 一致性检查执行失败：{exc}"]
    out: list[str] = []
    for finding in findings:
        # Finding 的字段名为 level（非 severity），此处按实际结构读取
        level = getattr(finding, "level", "")
        code = getattr(finding, "code", "")
        message = getattr(finding, "message", str(finding))
        path = getattr(finding, "path", "")
        out.append(f"{level} {code} {message} [{path}]".strip())
    return out


def verify_consistency(ws: Path, manifest: dict) -> dict:
    """校验恢复后的一致性点是否与备份时匹配。

    比对内容：知识版本指针、``03_core`` 版本目录、Runtime DB schema 版本。
    不匹配不代表失败（例如故意恢复到旧版本），但必须**显式报告**，
    避免「知识版本 ↔ 运行态」错配被静默忽略。
    """
    expected = manifest.get("consistency_point") or {}
    actual = capture_consistency_point(ws)

    mismatches: list[str] = []
    exp_pointers = expected.get("current_pointers") or {}
    act_pointers = actual.get("current_pointers") or {}
    for service, version in exp_pointers.items():
        if act_pointers.get(service) != version:
            mismatches.append(
                f"CURRENT 指针不一致：{service} 期望 {version}，"
                f"实际 {act_pointers.get(service)}")

    exp_schema = expected.get("runtime_schema_version")
    act_schema = actual.get("runtime_schema_version")
    if exp_schema is not None and act_schema is not None and exp_schema != act_schema:
        mismatches.append(
            f"Runtime DB schema 版本不一致：期望 {exp_schema}，实际 {act_schema}")

    exp_core = expected.get("core_versions") or {}
    act_core = actual.get("core_versions") or {}
    for service, versions in exp_core.items():
        missing = sorted(set(versions) - set(act_core.get(service) or []))
        if missing:
            mismatches.append(f"03_core 版本缺失：{service} 缺 {missing}")

    return {"matched": not mismatches, "mismatches": mismatches,
            "expected": expected, "actual": actual}
