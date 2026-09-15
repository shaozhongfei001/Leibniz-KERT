"""控制面供给：把受控控制面元数据安装进运行时工作区（M7.3 第五步 / 授权 D1-A）。

供给内容（**仅**控制面元数据，绝不触碰 ``03_core`` 权威资产）：

============================  ==================================================
``90_control/catalog/KM-*.json``                 知识地图（``KnowledgeMapRegistry`` 读）
``90_control/schema/route_policy.json``          路由策略（``load_route_policy`` 读）
``90_control/schema/ontology_reference.json``    本体引用声明（``load_ontology_reference`` 读）
``90_control/catalog/provision_manifest.json``   供给留痕（哈希/时刻/来源）
============================  ==================================================

纪律（每条都对应一个测试）：

1. **先全量校验，后写入**（fail-closed）：源的任一份定义非法 ⇒ **一份都不写**。
   半供给比不供给更危险——部分地图可用会被运维误读为"已配置"，且路由策略缺失时的
   默认拒绝会掩盖真正原因。
2. **幂等**：内容未变 ⇒ 不重写文件（留痕计 ``UNCHANGED``）。
3. **路径来自加载器**（``catalog_dir`` / ``schema_dir`` / ``policy_path`` / ``reference_path``）：
   写侧与读侧不可能漂移——这是"供给装到哪里"与"从哪里读"同源的唯一保证。
4. **不删既有文件**：只增改本清单内的文件，避免误删运维手工放置的内容。
5. **原子替换**：单文件 temp + ``os.replace``，避免读到半截 JSON。
6. **源必须是合法工作区**：供应方与消费方同一套校验（防止"能拷进去但读不出来"）。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from ..domain import timeutil
from ..domain.errors import UsageError
from ..domain.knowledge_map import (
    KnowledgeMapRegistry,
    catalog_dir,
    map_files,
)
from ..domain.ontology_reference import (
    FILENAME as ONTOLOGY_REFERENCE_FILENAME,
    load_ontology_reference,
    reference_path,
    sha256_file,
)
from ..domain.route_policy import (
    POLICY_FILENAME,
    load_route_policy,
    policy_path,
)
from ..domain.workspace import is_workspace

SCHEMA = "control_plane_provision/v1"
"""供给留痕 schema。"""

MANIFEST_FILENAME = "provision_manifest.json"
"""留痕文件名（放 ``90_control/catalog/``；不匹配 ``KM-*.json``，不会被注册表当作地图读入）。"""

ACTION_CREATED = "CREATED"
ACTION_UPDATED = "UPDATED"
ACTION_UNCHANGED = "UNCHANGED"


@dataclass(frozen=True)
class ProvisionItem:
    """单份控制面文件的供给结果。"""

    rel_path: str
    sha256: str
    action: str

    def to_dict(self) -> dict:
        return {"relPath": self.rel_path, "sha256": self.sha256, "action": self.action}


@dataclass(frozen=True)
class ProvisionResult:
    """一次供给的结果（``items`` **不含**留痕自身，故幂等语义不受时间戳影响）。"""

    workspace: Path
    source: str
    items: tuple[ProvisionItem, ...]
    policy_id: str | None = None
    policy_version: str | None = None
    map_count: int = 0
    dry_run: bool = False
    manifest_rel: str | None = None
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def counts(self) -> dict[str, int]:
        out = {ACTION_CREATED: 0, ACTION_UPDATED: 0, ACTION_UNCHANGED: 0}
        for it in self.items:
            out[it.action] += 1
        return out

    def changed(self) -> bool:
        """是否有控制面文件被新建或改写（留痕本身不计）。"""
        return any(it.action != ACTION_UNCHANGED for it in self.items)

    def to_dict(self) -> dict:
        return {
            "workspace": str(self.workspace),
            "source": self.source,
            "dryRun": self.dry_run,
            "changed": self.changed(),
            "counts": self.counts(),
            "policyId": self.policy_id,
            "policyVersion": self.policy_version,
            "mapCount": self.map_count,
            "manifest": self.manifest_rel,
            "warnings": list(self.warnings),
            "items": [it.to_dict() for it in self.items],
        }


def _write_atomic(path: Path, text: str) -> None:
    """原子写入：同目录 temp + ``os.replace``，避免读者看到半截内容。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _plan_items(ws: Path, src: Path) -> list[tuple[str, Path, Path]]:
    """产出 (rel_path, 源文件, 目标文件) 清单（顺序确定，便于比对留痕）。"""
    pairs: list[tuple[str, Path, Path]] = []
    for f in map_files(src):
        pairs.append((f"90_control/catalog/{f.name}", f, catalog_dir(ws) / f.name))
    pairs.append((f"90_control/schema/{POLICY_FILENAME}",
                  policy_path(src), policy_path(ws)))
    ref_src = reference_path(src)
    if ref_src.is_file():
        pairs.append((f"90_control/schema/{ONTOLOGY_REFERENCE_FILENAME}",
                      ref_src, reference_path(ws)))
    return pairs


def validate_source(source: Path) -> tuple[KnowledgeMapRegistry, object, object]:
    """把**源**当工作区全量校验（与消费侧同一套加载器）。

    抛 :class:`~kert.domain.errors.SchemaValidationError`（源内某份定义非法）
    或 :class:`~kert.domain.errors.UsageError`（源不是工作区 / 缺少必需件）。
    """
    src = Path(source)
    if not is_workspace(src):
        raise UsageError(
            f"供给源不是合法工作区（缺 .kert_workspace 标记）: {src}。"
            "供给源须与消费方同一套校验，否则可能拷得进去却读不出来"
        )
    registry = KnowledgeMapRegistry.load(src)
    policy = load_route_policy(src)
    ref = load_ontology_reference(src)
    if not registry.maps:
        raise UsageError(f"供给源未注册任何知识地图（{catalog_dir(src)}）: {src}")
    if policy is None:
        raise UsageError(f"供给源缺少路由策略（{policy_path(src)}）: {src}")
    return registry, policy, ref


def provision_control_plane(workspace: Path, source: Path, *,
                            dry_run: bool = False,
                            by: str = "svc_kert") -> ProvisionResult:
    """把 ``source`` 工作区的控制面元数据供给到 ``workspace``。

    参数：
        workspace: 目标工作区（须已 ``init``）。
        source:    控制面元数据源（须为合法工作区）。
        dry_run:   仅计算将发生的变更，不落盘。
        by:        留痕主体。

    返回 :class:`ProvisionResult`。**先全量校验源，再逐份原子写入**。
    """
    ws = Path(workspace)
    src = Path(source)

    if not is_workspace(ws):
        raise UsageError(f"目标工作区未初始化: {ws}（请先执行 kert init）")
    if ws.resolve() == src.resolve():
        raise UsageError(f"供给源与目标工作区相同: {ws}")

    registry, policy, _ref = validate_source(src)

    items: list[ProvisionItem] = []
    pending: list[tuple[Path, str]] = []
    for rel, s_path, d_path in _plan_items(ws, src):
        if not s_path.is_file():
            continue
        text = s_path.read_text(encoding="utf-8")
        digest = sha256_file(s_path)
        if not d_path.exists():
            action = ACTION_CREATED
        elif sha256_file(d_path) == digest:
            action = ACTION_UNCHANGED
        else:
            action = ACTION_UPDATED
        items.append(ProvisionItem(rel_path=rel, sha256=digest, action=action))
        if action != ACTION_UNCHANGED:
            pending.append((d_path, text))

    if dry_run:
        return ProvisionResult(workspace=ws, source=str(src), items=tuple(items),
                               policy_id=policy.policy_id,
                               policy_version=policy.version,
                               map_count=len(registry.maps), dry_run=True)

    for d_path, text in pending:
        _write_atomic(d_path, text)

    manifest = {
        "schema": SCHEMA,
        "provisioned_at": timeutil.ts_utc(),
        "provisioned_by": by,
        "source": str(src),
        "policyId": policy.policy_id,
        "policyVersion": policy.version,
        "mapCount": len(registry.maps),
        "counts": {a: sum(1 for it in items if it.action == a)
                   for a in (ACTION_CREATED, ACTION_UPDATED, ACTION_UNCHANGED)},
        "items": [it.to_dict() for it in items],
    }
    manifest_path = catalog_dir(ws) / MANIFEST_FILENAME
    _write_atomic(manifest_path,
                  json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n")

    return ProvisionResult(workspace=ws, source=str(src), items=tuple(items),
                           policy_id=policy.policy_id,
                           policy_version=policy.version,
                           map_count=len(registry.maps),
                           manifest_rel=f"90_control/catalog/{MANIFEST_FILENAME}")
