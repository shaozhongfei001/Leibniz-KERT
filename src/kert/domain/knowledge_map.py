"""知识地图注册与解析（M7.3；依据独立评审 §4.7 的目标设计）。

背景
----
清点时确认：`knowledge_map_registry` 在权威状态文件中为 ``DESIGNED_NOT_IMPLEMENTED``，
代码侧唯一"实现"是 ``skills.py`` 中**硬编码**的 mapId 字面量（``KM-CORP-RM-OUTREACH`` /
``-MEETING`` / ``-PREVISIT``），既无定义文件、也无加载/校验/遍历。本模块补齐
`KnowledgeMapRegistry` 的定义模型、加载器与 fail-closed 解析。

权威与位置
----------
- 地图定义是**控制面**元数据，放在 ``<ws>/90_control/catalog/KM-*.json``
  （**不是** ``03_core`` 权威知识资产 —— 本模块不读取也不修改 ``03_core``）。
- 文件名遵循工作区 ID 约定（``workspace.ID_FILENAME_RE``），schema 名复用
  :data:`kert.domain.ids.SCHEMA_NAME_RE`（``knowledge_map/v1``）。

fail-closed 规则（本模块的核心纪律）
-----------------------------------
1. **未知字段拒绝**：出现未声明的字段即 ``SchemaValidationError``（不静默忽略）；
2. **schema/ID/版本/域非法** 拒绝；
3. **歧义拒绝**：同一 ``mapId`` 出现在多个文件 ⇒ ``RuleConflictError``；
   同一任务被**同优先级**的多个地图声明 ⇒ 解析结果拒绝；
4. **默认拒绝**：任务未被任何地图声明 ⇒ 解析结果拒绝（**不回落、不猜测、不取第一个**）；
5. **引用校验**：``assetRefs``/``skillRefs`` 内部重复即拒绝；``sequence`` 在同一地图内必须唯一。

引用只读消费
------------
地图只**引用**资产 / Skill / 路由策略 / 激活合同（ID + 版本），**不复制其内容**；
跨仓权威（如本体）同样只以"契约引用 + 内容哈希版本"形式登记（见
``docs/governance/KERT_PENDING_OWNER_DECISION_M7_EVOLUTION_V1.0.md`` 的 D3-A）。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from . import ids
from .errors import RuleConflictError, SchemaValidationError, UsageError

SCHEMA = "knowledge_map/v1"
"""地图定义 schema（须匹配 :data:`kert.domain.ids.SCHEMA_NAME_RE`）。"""

CATALOG_DIRNAME = "catalog"
"""控制面目录名（``<ws>/90_control/catalog``）。"""

MAP_ID_PREFIX = "KM-"
"""知识地图 ID 前缀（既有硬编码 id 与 gits 侧 `KM-*` 口径一致）。"""

MAP_FILE_RE = re.compile(r"^KM-[A-Z0-9_-]+\.json$")
"""地图定义文件名（同时满足工作区 ``ID_FILENAME_RE``）。"""

SKILL_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{2,127}$")
"""Skill ID 形态。

**刻意不复用** :data:`kert.domain.ids.ID_RE`（全大写）：KERT 真实 Skill ID 为混合大小写
（既有注册表同时存在 ``skill-customer-outreach-script`` 这类小写连字符 ID 与 ``SP-20`` 这类大写 ID），
沿用全大写规则会把真实 ID 误判为非法。此规则只放宽**大小写**，长度与字符集仍受限。
"""

# 允许字段白名单（未知字段一律拒绝，见模块 docstring 规则 1）
_TOP_FIELDS = {
    "schema", "mapId", "version", "title", "domain", "tasks", "priority",
    "assetRefs", "skillRefs", "routePolicyRef", "activationContractRef", "notes",
}
_ASSET_REF_FIELDS = {"assetId", "required", "sequence"}

# 解析拒绝码（供 RoutePolicy / ActivationPlan 与调用方稳定引用）
CODE_OK = "OK"
CODE_NONE_REGISTERED = "KNOWLEDGE_MAP_NONE_REGISTERED"
CODE_NOT_MAPPED = "KNOWLEDGE_MAP_NOT_MAPPED"
CODE_AMBIGUOUS = "KNOWLEDGE_MAP_AMBIGUOUS"


@dataclass(frozen=True)
class AssetRef:
    """地图对知识资产的引用（只读；不复制资产内容）。"""

    asset_id: str
    required: bool
    sequence: int


@dataclass(frozen=True)
class KnowledgeMap:
    """一张知识地图的定义（不可变；由控制面 JSON 解析而来）。"""

    map_id: str
    version: str
    title: str
    domain: str
    tasks: tuple[str, ...]
    priority: int
    asset_refs: tuple[AssetRef, ...]
    skill_refs: tuple[str, ...]
    route_policy_ref: str | None
    activation_contract_ref: str | None
    source_path: str
    notes: str | None = None


@dataclass(frozen=True)
class MapResolution:
    """任务 → 知识地图的解析结果（fail-closed：不允许 ``None`` 泄漏给调用方）。

    ``code`` 为 :data:`CODE_OK` 时 ``map`` 非空；否则 ``map`` 为 ``None`` 且
    ``code``/``reason`` 说明拒绝原因。调用方**必须**显式处理拒绝，
    不得以"取第一个"或"回落默认地图"的方式绕过。
    """

    code: str
    reason: str
    map: KnowledgeMap | None = None
    candidates: tuple[str, ...] = ()

    @property
    def allowed(self) -> bool:
        """是否解析到唯一合法地图。"""
        return self.code == CODE_OK and self.map is not None


def catalog_dir(workspace: Path) -> Path:
    """返回工作区的控制面目录（``<ws>/90_control/catalog``）。"""
    return Path(workspace) / "90_control" / CATALOG_DIRNAME


def map_files(workspace: Path) -> list[Path]:
    """列出控制面下的地图定义文件（按文件名排序，保证确定性）。

    目录不存在时返回空列表（**不**抛异常）：既有工作区可能尚未建立 catalog，
    此时注册表为空，任何解析都会以 :data:`CODE_NONE_REGISTERED` 默认拒绝。
    """
    d = catalog_dir(workspace)
    if not d.is_dir():
        return []
    return sorted(p for p in d.glob("KM-*.json") if p.is_file() and MAP_FILE_RE.match(p.name))


def parse_knowledge_map(doc: object, *, source: str = "<memory>") -> KnowledgeMap:
    """解析并**严格校验**一张地图定义（未知字段/类型/枚举错误一律拒绝）。

    :param doc: 已反序列化的 JSON 对象。
    :param source: 来源标识（文件相对路径），用于错误定位与审计。
    :raises SchemaValidationError: 结构、类型、取值非法。
    """
    if not isinstance(doc, dict):
        raise SchemaValidationError(f"[{source}] 地图定义必须是 JSON 对象，实际为 {type(doc).__name__}")

    unknown = sorted(set(doc) - _TOP_FIELDS)
    if unknown:
        raise SchemaValidationError(f"[{source}] 含未声明字段（拒绝静默忽略）: {unknown}")

    schema = _require_str(doc, "schema", source)
    if not ids.SCHEMA_NAME_RE.match(schema):
        raise SchemaValidationError(
            f"[{source}] schema 非法: {schema!r}（须匹配 {ids.SCHEMA_NAME_RE.pattern}）")
    if schema != SCHEMA:
        raise SchemaValidationError(f"[{source}] schema 不支持: {schema!r}（本实现只接受 {SCHEMA!r}）")

    map_id = _require_str(doc, "mapId", source)
    _validate(ids.ID_RE, map_id, "知识地图 ID", source)
    if not map_id.startswith(MAP_ID_PREFIX):
        raise SchemaValidationError(f"[{source}] 知识地图 ID 必须以 {MAP_ID_PREFIX!r} 开头: {map_id!r}")

    version = _require_str(doc, "version", source)
    if not ids.SEMVER_RE.match(version):
        raise SchemaValidationError(
            f"[{source}] version 非法: {version!r}（须为 semver，如 1.0.0）")

    title = _require_str(doc, "title", source)
    domain = _require_str(doc, "domain", source)
    _validate(ids.DOMAIN_RE, domain, "业务域", source)

    tasks_raw = doc.get("tasks")
    if not isinstance(tasks_raw, list) or not tasks_raw:
        raise SchemaValidationError(f"[{source}] tasks 必须是非空数组")
    tasks: list[str] = []
    for item in tasks_raw:
        if not isinstance(item, str) or not item.strip():
            raise SchemaValidationError(f"[{source}] tasks 元素必须是非空字符串: {item!r}")
        tasks.append(item.strip())
    dup_tasks = sorted({t for t in tasks if tasks.count(t) > 1})
    if dup_tasks:
        raise SchemaValidationError(f"[{source}] tasks 重复（歧义）: {dup_tasks}")

    priority = doc.get("priority")
    if not isinstance(priority, int) or isinstance(priority, bool) or priority < 0:
        raise SchemaValidationError(f"[{source}] priority 必须是非负整数，实际为 {priority!r}")

    asset_refs = _parse_asset_refs(doc.get("assetRefs"), source)
    skill_refs = _parse_skill_refs(doc.get("skillRefs"), "skillRefs", source)

    route_policy_ref = _optional_id(doc.get("routePolicyRef"), "routePolicyRef", source)
    activation_contract_ref = _optional_id(
        doc.get("activationContractRef"), "activationContractRef", source)

    notes_raw = doc.get("notes")
    if notes_raw is not None and not isinstance(notes_raw, str):
        raise SchemaValidationError(f"[{source}] notes 必须是字符串")

    return KnowledgeMap(
        map_id=map_id,
        version=version,
        title=title,
        domain=domain,
        tasks=tuple(tasks),
        priority=priority,
        asset_refs=tuple(asset_refs),
        skill_refs=tuple(skill_refs),
        route_policy_ref=route_policy_ref,
        activation_contract_ref=activation_contract_ref,
        source_path=source,
        notes=notes_raw,
    )


def load_knowledge_map_file(path: Path, *, workspace: Path | None = None) -> KnowledgeMap:
    """从控制面 JSON 文件加载一张地图定义。

    :param path: 地图定义文件路径。
    :param workspace: 工作区根（用于错误信息中的相对路径）。
    :raises SchemaValidationError: 文件不存在、JSON 非法或结构校验失败。
    """
    p = Path(path)
    source = p.name if workspace is None else _rel(p, Path(workspace))
    if not p.is_file():
        raise SchemaValidationError(f"[{source}] 地图定义文件不存在: {p}")
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SchemaValidationError(f"[{source}] 地图定义无法解析: {exc}") from exc
    return parse_knowledge_map(doc, source=source)


class KnowledgeMapRegistry:
    """知识地图注册表（不可变快照；由控制面文件加载）。

    用法::

        reg = KnowledgeMapRegistry.load(ws)
        res = reg.resolve_for_task("PRE_VISIT_PREPARATION")
        if not res.allowed:            # 默认拒绝 / 歧义拒绝
            ...                        # 调用方必须显式处理，不得回落
    """

    def __init__(self, maps: list[KnowledgeMap] | tuple[KnowledgeMap, ...]):
        self._by_id: dict[str, KnowledgeMap] = {}
        for m in maps:
            if m.map_id in self._by_id:
                prev = self._by_id[m.map_id]
                raise RuleConflictError(
                    f"知识地图 ID 歧义（同优先级不可裁决）: {m.map_id} 同时定义于 "
                    f"{prev.source_path} 与 {m.source_path}"
                )
            self._by_id[m.map_id] = m
        self._maps: tuple[KnowledgeMap, ...] = tuple(
            sorted(self._by_id.values(), key=lambda m: m.map_id))

    @classmethod
    def load(cls, workspace: Path) -> "KnowledgeMapRegistry":
        """加载工作区控制面下的全部地图定义（``90_control/catalog/KM-*.json``）。"""
        ws = Path(workspace)
        maps = [load_knowledge_map_file(p, workspace=ws) for p in map_files(ws)]
        return cls(maps)

    def __len__(self) -> int:
        return len(self._maps)

    def __contains__(self, map_id: object) -> bool:
        return map_id in self._by_id

    @property
    def maps(self) -> tuple[KnowledgeMap, ...]:
        """全部地图（按 mapId 排序）。"""
        return self._maps

    def get(self, map_id: str) -> KnowledgeMap:
        """按 ID 取地图；未注册即拒绝（**不**返回 ``None``）。"""
        m = self._by_id.get(map_id)
        if m is None:
            raise UsageError(
                f"知识地图未注册: {map_id!r}（已注册: {sorted(self._by_id)}）")
        return m

    def tasks(self) -> tuple[str, ...]:
        """已声明的全部任务（排序去重）。"""
        return tuple(sorted({t for m in self._maps for t in m.tasks}))

    def resolve_for_task(self, task: str) -> MapResolution:
        """把任务解析为唯一合法地图。

        - 注册表为空 ⇒ :data:`CODE_NONE_REGISTERED`（默认拒绝）；
        - 无地图声明该任务 ⇒ :data:`CODE_NOT_MAPPED`（默认拒绝）；
        - 同任务被多张地图声明：优先级最小者胜；**同优先级 ⇒ 歧义拒绝**
          :data:`CODE_AMBIGUOUS`（fail-closed，不按文件名/加载顺序任取）。

        **判定：预留（未接线）** —— 本方法在 src 侧的唯一调用者是
        :meth:`~kert.domain.route_policy.RouteResolver.resolve_via_registry_only`，而后者在生产代码中
        **无调用点**（唯一调用者是单测）。地图经 :meth:`RouteResolver.load` 参与路由的正规路径
        **不经过**本方法 ⇒ **不得**表述为"地图→任务遍历已上线"；若日后接线，须同步更新
        ``tests/unit/test_semantics_carriers_and_reservations.py`` 中的预留断言与证据。
        """
        if not isinstance(task, str) or not task.strip():
            raise UsageError(f"任务类型必须是非空字符串: {task!r}")
        task = task.strip()

        if not self._maps:
            return MapResolution(
                code=CODE_NONE_REGISTERED,
                reason=f"控制面未注册任何知识地图（{CATALOG_DIRNAME}/KM-*.json 为空或缺失）",
            )

        matched = [m for m in self._maps if task in m.tasks]
        if not matched:
            return MapResolution(
                code=CODE_NOT_MAPPED,
                reason=f"任务未映射到任何知识地图: {task}（已声明任务: {list(self.tasks())}）",
            )
        if len(matched) == 1:
            return MapResolution(code=CODE_OK, reason="", map=matched[0])

        top_priority = min(m.priority for m in matched)
        top = [m for m in matched if m.priority == top_priority]
        if len(top) > 1:
            return MapResolution(
                code=CODE_AMBIGUOUS,
                reason=(f"任务 {task} 被 {len(top)} 张**同优先级**（{top_priority}）地图声明，"
                        f"歧义不可裁决（fail-closed）"),
                candidates=tuple(sorted(m.map_id for m in top)),
            )
        return MapResolution(code=CODE_OK, reason="", map=top[0])


# --------------------------------------------------------------------------- #
# 内部校验助手
# --------------------------------------------------------------------------- #

def _rel(path: Path, ws: Path) -> str:
    try:
        return path.relative_to(ws).as_posix()
    except ValueError:
        return path.as_posix()


def _validate(pattern: "re.Pattern[str]", value: str, label: str, source: str) -> str:
    """按给定正则校验取值；不符即抛**契约错误**（而非调用方参数错误）。

    ``ids.validate_id`` / ``ids.validate_domain`` 抛 :class:`UsageError`（面向命令行参数）；
    定义**文件**里的取值非法属**契约**问题，故此处统一转为 :class:`SchemaValidationError`，
    并带上来源文件，便于定位。
    """
    if not pattern.match(value):
        raise SchemaValidationError(
            f"[{source}] 非法{label}: {value!r}（须匹配 {pattern.pattern}）")
    return value


def _require_str(doc: dict, key: str, source: str) -> str:
    value = doc.get(key)
    if not isinstance(value, str) or not value.strip():
        raise SchemaValidationError(f"[{source}] 缺少必填字段或类型错误: {key}（须为非空字符串）")
    return value.strip()


def _optional_id(value: object, key: str, source: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise SchemaValidationError(f"[{source}] {key} 必须是非空字符串或省略")
    _validate(ids.ID_RE, value.strip(), key, source)
    return value.strip()


def _parse_skill_refs(value: object, key: str, source: str) -> list[str]:
    """解析 skillRefs（用 :data:`SKILL_ID_RE`，兼容 KERT 真实的小写 Skill ID）。"""
    if value is None:
        return []
    if not isinstance(value, list):
        raise SchemaValidationError(f"[{source}] {key} 必须是数组")
    out: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise SchemaValidationError(f"[{source}] {key} 元素必须是非空字符串: {item!r}")
        _validate(SKILL_ID_RE, item.strip(), key, source)
        out.append(item.strip())
    dup = sorted({x for x in out if out.count(x) > 1})
    if dup:
        raise SchemaValidationError(f"[{source}] {key} 重复（歧义）: {dup}")
    return out


def _parse_asset_refs(value: object, source: str) -> list[AssetRef]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise SchemaValidationError(f"[{source}] assetRefs 必须是数组")
    refs: list[AssetRef] = []
    for item in value:
        if not isinstance(item, dict):
            raise SchemaValidationError(f"[{source}] assetRefs 元素必须是对象: {item!r}")
        unknown = sorted(set(item) - _ASSET_REF_FIELDS)
        if unknown:
            raise SchemaValidationError(f"[{source}] assetRefs 含未声明字段: {unknown}")
        asset_id = item.get("assetId")
        if not isinstance(asset_id, str) or not asset_id.strip():
            raise SchemaValidationError(f"[{source}] assetRefs.assetId 必须是非空字符串")
        _validate(ids.ID_RE, asset_id.strip(), "资产 ID", source)
        required = item.get("required", True)
        if not isinstance(required, bool):
            raise SchemaValidationError(f"[{source}] assetRefs.required 必须是布尔值")
        sequence = item.get("sequence")
        if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 1:
            raise SchemaValidationError(f"[{source}] assetRefs.sequence 必须是 >=1 的整数")
        refs.append(AssetRef(asset_id=asset_id.strip(), required=required, sequence=sequence))

    dup_assets = sorted({r.asset_id for r in refs if [x.asset_id for x in refs].count(r.asset_id) > 1})
    if dup_assets:
        raise SchemaValidationError(f"[{source}] assetRefs 资产重复（歧义）: {dup_assets}")
    dup_seq = sorted({r.sequence for r in refs if [x.sequence for x in refs].count(r.sequence) > 1})
    if dup_seq:
        raise SchemaValidationError(f"[{source}] assetRefs.sequence 在同一地图内必须唯一: {dup_seq}")
    return sorted(refs, key=lambda r: r.sequence)
