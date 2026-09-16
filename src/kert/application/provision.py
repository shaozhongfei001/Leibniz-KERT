"""控制面供给：把受控控制面元数据安装进运行时工作区（M7.3 第五步 / 授权 D1-A）。

供给内容（**仅**控制面元数据，绝不触碰 ``03_core`` 权威资产）：

============================  ==================================================
``90_control/catalog/KM-*.json``                 知识地图（``KnowledgeMapRegistry`` 读）
``90_control/schema/route_policy.json``          路由策略（``load_route_policy`` 读）
``90_control/schema/ontology_reference.json``    本体引用声明（``load_ontology_reference`` 读）
``90_control/schema/knowledge_sources.json``     知识源能力声明（``load_declaration`` 读；M7.1-A）
``90_control/ontology/**``                        内置本体资产（OWL/SHACL/INSTANCES/R2RML + PROVENANCE；M7-⑤）
``90_control/catalog/provision_manifest.json``   供给留痕（哈希/时刻/来源）
============================  ==================================================

⚠ ``knowledge_sources.json`` **必须**落在 ``90_control/schema/``：``90_control/catalog/``
已被两类内容占用（``KM-*.json`` 知识地图 与 管道资产台账 ``asset_catalog`` 的
``<asset_id>.md``），往里新增文件会污染该目录的两套既有约定。

纪律（每条都对应一个测试）：

1. **先全量校验，后写入**（fail-closed）：源的任一份定义非法 ⇒ **一份都不写**。
   半供给比不供给更危险——部分地图可用会被运维误读为"已配置"，且路由策略缺失时的
   默认拒绝会掩盖真正原因。
2. **幂等**：内容未变 ⇒ 不重写文件（留痕计 ``UNCHANGED``）。
3. **路径来自加载器**（``catalog_dir`` / ``schema_dir`` / ``policy_path`` / ``reference_path``
   / ``knowledge_sources_path``）：写侧与读侧不可能漂移——这是"供给装到哪里"与
   "从哪里读"同源的唯一保证。
4. **不删既有文件**：只增改本清单内的文件，避免误删运维手工放置的内容。
5. **原子替换**：单文件 temp + ``os.replace``，避免读到半截 JSON。
6. **源必须是合法工作区**：供应方与消费方同一套校验（防止"能拷进去但读不出来"）。
7. **知识源声明与本体引用同为"可选但必须校验"**：声明**缺失** ⇒ 不供给（不报错，
   与 :func:`validate_source` 对本体引用的既有口径一致）；声明**非法** ⇒ 全量中止。
   取舍理由：该声明与本体引用同层同性质，且**当前尚无运行时消费方**
   （M7.1-A 只读、未接线）——缺它不应让整个部署起不来；而"非法"必须中止，
   否则会破坏纪律 1。若将来该声明成为读取链的必需件，应在彼时把它改为
   "缺失即拒绝"（属语义升级，须单独授权与评估）。
8. **内置本体资产同样是"可选但必须校验"**（M7-⑤）：``90_control/ontology/**`` 目录内无
   ``PROVENANCE.json`` ⇒ 不供给（不报错）；``PROVENANCE.json`` 在场即必须合法
   （provenance 非法 / 声明的资产文件缺失 / 副本漂移 ⇒ **全量中止**，理由同纪律 1）。
   清单与目标路径由 :mod:`kert.domain.ontology_provision` 产出（写侧与读侧同源，见纪律 3）。
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
from ..domain.knowledge_source import (
    FILENAME as KNOWLEDGE_SOURCES_FILENAME,
    declaration_path as knowledge_sources_path,
    load_declaration,
)
from ..domain.ontology_provision import (
    provision_pairs as ontology_provision_pairs,
    require_source_assets,
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
    # 知识源能力声明（M7.1-A 第 4 类）：与本体引用同为"可选但必须校验"（见模块 docstring 纪律 7）
    ks_src = knowledge_sources_path(src)
    if ks_src.is_file():
        pairs.append((f"90_control/schema/{KNOWLEDGE_SOURCES_FILENAME}",
                      ks_src, knowledge_sources_path(ws)))
    # 内置本体资产（M7-⑤）：与本体引用/知识源声明同口径（模块 docstring 纪律 8）。
    # 清单与目标路径由领域模块产出（写侧/读侧同源，纪律 3）；源侧非法 ⇒ 此处就中止。
    pairs.extend(ontology_provision_pairs(ws, src))
    return pairs


def validate_source(source: Path) -> tuple[KnowledgeMapRegistry, object, object, object]:
    """把**源**当工作区全量校验（与消费侧同一套加载器）。

    校验顺序与"要供给什么"一一对应，且**先于任何写入**（纪律 1）：

    1. 源必须是合法工作区（``.kert_workspace`` 标记）；
    2. 知识地图（``KnowledgeMapRegistry.load``）——须至少一份（否则供给出的是空控制面）；
    3. 路由策略（``load_route_policy``）——**必需**（缺它则路由默认拒绝，供给无意义）；
    4. 本体引用（``load_ontology_reference``）——可选；存在即校验，非法即中止；
    5. 知识源能力声明（``load_declaration``）——可选；存在即校验，非法即中止
       （M7.1-A；与第 4 项同口径，见模块 docstring 纪律 7）；
    6. 内置本体资产（:func:`~kert.domain.ontology_provision.require_source_assets`）——可选；
       ``PROVENANCE.json`` 在场即校验，非法/缺文件/漂移即中止
       （M7-⑤；与第 4/5 项同口径，见模块 docstring 纪律 8）。

    抛 :class:`~kert.domain.errors.SchemaValidationError`（源内某份定义非法）
    或 :class:`~kert.domain.errors.UsageError`（源不是工作区 / 缺少必需件）。

    :return: ``(registry, policy, ontology_reference, knowledge_sources_declaration)``；
        后两项在源未放置对应文件时为 ``None``（**不是**"无声明也放行"）。
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
    decl = load_declaration(src)
    require_source_assets(src)      # M7-⑤：内置本体资产（可选；在场即必须合法）
    if not registry.maps:
        raise UsageError(f"供给源未注册任何知识地图（{catalog_dir(src)}）: {src}")
    if policy is None:
        raise UsageError(f"供给源缺少路由策略（{policy_path(src)}）: {src}")
    return registry, policy, ref, decl


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

    registry, policy, _ref, _decl = validate_source(src)

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
