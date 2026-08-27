"""发布清单与版本锚点（M2.6）。

解决的问题
----------
1. **版本号分散不同步**：仓库中并存 ``__version__="0.1.0"``、
   ``SERVICE_VERSION="1.0.0"``、``BUILDER_VERSION="1.0.0"``、
   ``SCHEMA_VERSION=2`` 等多套版本，无单一视图。
2. **缺 git commit 锚点**：治理文档
   ``DKWS_STATUS_BASELINE_CANDIDATE.yaml`` 明确登记
   ``dkws_git_commit_anchor: null``，evidence manifest 亦将其列为 missing。
3. **无发布 manifest**：部署文档 §7 要求「一个发布 manifest，包含
   Python/Java/契约/Skill hash」。

本模块**只汇总与记录**，不修改任何既有版本常量——统一版本号涉及多处
契约与测试，属独立变更，不在本任务包范围内。
"""

from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from ..domain import hashing, timeutil

#: git 命令超时（秒），避免在无 git 环境或大仓库上长时间阻塞
GIT_TIMEOUT = 10


def _run_git(repo: Path, *args: str) -> str | None:
    """执行 git 命令并返回 stdout；失败返回 ``None``。

    任何异常（无 git、非仓库、超时）均降级为 ``None``，
    因为版本锚点缺失不应阻断发布流程，只需在清单中标注。
    """
    try:
        # 参数为固定字面量（"git" + 调用方传入的子命令），无 shell 注入面
        proc = subprocess.run(
            ["git", *args], cwd=str(repo), capture_output=True, text=True,
            timeout=GIT_TIMEOUT, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.strip() or None


def git_anchor(repo: Path) -> dict:
    """采集 git 版本锚点。

    Returns:
        含 ``commit``/``short_commit``/``branch``/``dirty``/``tag`` 的字典；
        非 git 环境下各字段为 ``None`` 并含 ``available: False``。
    """
    repo = Path(repo)
    commit = _run_git(repo, "rev-parse", "HEAD")
    if commit is None:
        return {"available": False,
                "note": "非 git 仓库或 git 不可用，版本锚点缺失"}
    status = _run_git(repo, "status", "--porcelain")
    return {
        "available": True,
        "commit": commit,
        "short_commit": commit[:12],
        "branch": _run_git(repo, "rev-parse", "--abbrev-ref", "HEAD"),
        "tag": _run_git(repo, "describe", "--tags", "--always"),
        "dirty": bool(status),
        "dirty_file_count": len(status.splitlines()) if status else 0,
        "committed_at": _run_git(repo, "log", "-1", "--format=%cI"),
    }


def collect_version_map() -> dict:
    """汇总代码中分散的各套版本号。

    **不统一、不修改**，只如实记录——统一版本号涉及多处契约与测试，
    属独立变更。本清单使各版本可见，便于后续治理。
    """
    versions: dict = {}
    try:
        from .. import __version__ as pkg_version

        versions["package"] = pkg_version
    except Exception:  # noqa: BLE001 - 版本采集失败不应阻断
        versions["package"] = None
    try:
        from ..api.server import SERVICE_VERSION

        versions["service_http"] = SERVICE_VERSION
    except Exception:  # noqa: BLE001
        versions["service_http"] = None
    try:
        from .runtime_store import SCHEMA_VERSION

        versions["runtime_db_schema"] = SCHEMA_VERSION
    except Exception:  # noqa: BLE001
        versions["runtime_db_schema"] = None
    try:
        from ..application.projection import BUILDER_VERSION

        versions["projection_builder"] = BUILDER_VERSION
    except Exception:  # noqa: BLE001
        versions["projection_builder"] = None
    versions["python"] = sys.version.split()[0]
    versions["platform"] = platform.platform()
    return versions


def hash_directory(root: Path, *, patterns: tuple[str, ...] = ("*",),
                   exclude: tuple[str, ...] = ("__pycache__", ".pyc")) -> dict:
    """计算目录内容的确定性哈希。

    对文件按相对路径排序后串联各自 sha256 再取总哈希，
    使同样内容在不同机器上得到相同结果（可用于比对部署一致性）。
    """
    root = Path(root)
    if not root.is_dir():
        return {"present": False, "path": str(root)}
    entries: list[tuple[str, str]] = []
    for pattern in patterns:
        for item in sorted(root.rglob(pattern)):
            if not item.is_file():
                continue
            rel = item.relative_to(root).as_posix()
            if any(token in rel for token in exclude):
                continue
            entries.append((rel, hashing.sha256_file(item)))
    entries.sort()
    combined = "\n".join(f"{rel}:{digest}" for rel, digest in entries)
    return {
        "present": True,
        "path": str(root),
        "file_count": len(entries),
        "content_sha256": hashing.sha256_hex(combined),
    }


@dataclass
class ReleaseManifest:
    """发布清单（部署文档 §7）。

    Attributes:
        release_id: 发布标识。
        created_at: 生成时间。
        git: git 版本锚点。
        versions: 各套版本号汇总。
        components: 组件哈希（源码/契约/Skill 包）。
        environment: 运行环境信息。
        notes: 非声明与说明事项。
    """

    release_id: str
    created_at: str
    git: dict = field(default_factory=dict)
    versions: dict = field(default_factory=dict)
    components: dict = field(default_factory=dict)
    environment: dict = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        """转为可序列化字典。"""
        return {
            "schema": "dkws_release_manifest/v1",
            "release_id": self.release_id,
            "created_at": self.created_at,
            "git": self.git,
            "versions": self.versions,
            "components": self.components,
            "environment": self.environment,
            "notes": self.notes,
        }

    def fingerprint(self) -> str:
        """发布指纹：由 git commit 与各组件哈希派生。

        用于判断「两次部署是否为同一份代码 + 同一份契约」。
        """
        parts = [str(self.git.get("commit") or "no-git")]
        for name in sorted(self.components):
            info = self.components[name]
            parts.append(f"{name}:{info.get('content_sha256', 'absent')}")
        return hashing.sha256_hex("|".join(parts))


def build_release_manifest(repo: Path, *, release_id: str | None = None
                           ) -> ReleaseManifest:
    """生成发布清单。

    Args:
        repo: 仓库根目录。
        release_id: 发布标识，缺省用 git short commit 或时间戳。

    Returns:
        :class:`ReleaseManifest`。
    """
    repo = Path(repo).resolve()
    anchor = git_anchor(repo)
    rid = release_id or (anchor.get("short_commit")
                         or timeutil.ts_utc().replace(":", "").replace("-", ""))

    manifest = ReleaseManifest(
        release_id=rid,
        created_at=timeutil.ts_utc(),
        git=anchor,
        versions=collect_version_map(),
        environment={
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "profile": os.environ.get("DKWS_PROFILE", "dev"),
        },
    )

    manifest.components = {
        "python_source": hash_directory(repo / "src", patterns=("*.py",)),
        # 公共契约位于 docs/contracts（openapi + schemas），
        # 与 scripts/contract_bundle_hash.py 的白名单一致
        "public_contracts": hash_directory(repo / "docs" / "contracts" / "openapi"),
        "public_schemas": hash_directory(repo / "docs" / "contracts" / "schemas"),
        "internal_contracts": hash_directory(repo / "docs" / "contracts" / "internal"),
        "skill_packages": hash_directory(repo / "skills", patterns=("*.md",)),
        "scripts": hash_directory(repo / "scripts", patterns=("*.py",)),
    }

    notes = [
        "本清单不代表已通过发布门禁或生产验收。",
        ("版本号在代码中分散于多处（package/service_http/runtime_db_schema/"
         "projection_builder），本清单如实记录但未统一——统一涉及多处契约"
         "与测试，属独立变更。"),
    ]
    if not anchor.get("available"):
        notes.append("git 版本锚点不可用：无法确定源码 commit，发布可追溯性受限。")
    elif anchor.get("dirty"):
        notes.append(
            f"工作区存在 {anchor.get('dirty_file_count')} 个未提交变更："
            f"本次发布内容与任何 commit 均不完全对应，不应用于生产。")
    manifest.notes = notes
    return manifest


def write_release_manifest(repo: Path, dest: Path, *,
                           release_id: str | None = None) -> tuple[Path, ReleaseManifest]:
    """生成并写出发布清单。"""
    manifest = build_release_manifest(repo, release_id=release_id)
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    payload = manifest.as_dict()
    payload["fingerprint"] = manifest.fingerprint()
    dest.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                    encoding="utf-8")
    return dest, manifest


def compare_manifests(left: dict, right: dict) -> dict:
    """比对两份发布清单，用于升级/回滚前的差异确认。

    Returns:
        含 ``same_commit``/``same_fingerprint``/``version_diff``/
        ``component_diff`` 的字典。
    """
    left_git = left.get("git") or {}
    right_git = right.get("git") or {}
    version_diff = {}
    for key in sorted(set(left.get("versions") or {})
                      | set(right.get("versions") or {})):
        lv = (left.get("versions") or {}).get(key)
        rv = (right.get("versions") or {}).get(key)
        if lv != rv:
            version_diff[key] = {"from": lv, "to": rv}

    component_diff = {}
    for name in sorted(set(left.get("components") or {})
                       | set(right.get("components") or {})):
        lc = (left.get("components") or {}).get(name) or {}
        rc = (right.get("components") or {}).get(name) or {}
        if lc.get("content_sha256") != rc.get("content_sha256"):
            component_diff[name] = {"from": lc.get("content_sha256"),
                                    "to": rc.get("content_sha256")}
    return {
        "same_commit": left_git.get("commit") == right_git.get("commit"),
        "same_fingerprint": left.get("fingerprint") == right.get("fingerprint"),
        "version_diff": version_diff,
        "component_diff": component_diff,
    }
