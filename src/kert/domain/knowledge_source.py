"""知识源 typed capability 与「资产引用 → 读取能力」绑定解析链（M7.1-A 第一片）。

授权与边界
----------
依据 Tech Lead 裁定 ``M7-1-A-AUTHORIZATION``
（``evidence/m7-3/TL_DECISION_M7-1-FIRST-SLICE.md``；设计候选
``evidence/m7-3/CANDIDATE-M7-1-KNOWLEDGE-SOURCE.md`` §2/§3/§6）：

- **只读、不接线**：本模块**不被** ``application/**`` / ``api/**`` 引用；不读任何数据文件
  （Parquet / Kùzu / SQLite）、不做网络访问、不落盘、不开写锁；
- **拒绝码只存在于内部对象**：``ReadDenial`` 是**内部**载体，**不得**经 API / 错误体暴露
  （避免未经追认扩合同错误码面）；
- **第一片不含真实数据读取**：解析链止于「能力已解析 + 读契约已校验 + 读计划（``ReadSpec``）已生成」。
  携带 ``records``/``provenance`` 的读取结果类型（设计候选 §2.3 的 ``ReadResult``）属**第二片**，
  届时由适配器返回，本模块不预先伪造它；
- 声明文件放 ``<ws>/90_control/schema/knowledge_sources.json``（与 ``route_policy.json``、
  ``ontology_reference.json`` 同址）。**不得**放 ``90_control/catalog/``
  —— 该目录已被 ``KM-*.json`` 与管道资产台账 ``asset_catalog`` 的 ``*.md`` 占用。

命名纪律（TL 附加要求 1：消除 ``asset_id`` 两套含义）
----------------------------------------------------
仓内 ``asset_id`` 已有**两套互不相同的含义**：

============================  ==================================================
① 管道资产台账 ``asset_id``     ``asset_catalog/v1`` 的**主键**，登记"数据资产"
                              （``asset_type`` / ``location`` / ``authoritative_layer``
                              / 上下游 / 分类分级）
                              定义：``src/kert/domain/contracts/specs.py:395-418``
                              落盘：``90_control/catalog/<asset_id>.md``
                              生产：``src/kert/application/publish.py:271-287``
② 计划资产引用 ``assetRefId``  知识地图 ``assetRefs[].assetId`` 与
                              ``ActivationPlan.assets[].asset_id``，回答"**读什么内容**"
                              定义：``src/kert/domain/knowledge_map.py:388-418``
                              消费：``src/kert/domain/activation_plan.py:229-230``
============================  ==================================================

**本模块一律用 ``asset_ref_id`` 指代 ②**，**不**使用裸名 ``asset_id``；
``asset_ref_ids_of(plan)`` 负责从 ``ActivationPlan`` 取出该序列（只读，不改计划语义）。
两者**不可互换**：台账 id 指向数据资产登记，asset_ref_id 只用于选取读取能力。

隐式绑定的显式化（TL 附加要求 2）
--------------------------------
现状把 assetRefId 与数据关联起来靠 ``src/kert/application/customer_knowledge.py:31`` 的
**隐式正则** ``^(KI-[\\w-]+)\\s+(.+)$``（在 ``:59-68`` 施加于 ``heading_path[0]``）。
本模块把该约定**升级为声明**（``readContract.assetMatch.pattern``，命名分组
``assetRefId``/``title``），并由 :meth:`KnowledgeSourceResolver.match_heading` 施加：

- 未命中 ⇒ ``KNOWLEDGE_SOURCE_ASSET_REF_UNMATCHED``（具名拒绝，**不得**静默跳过）；
- 命中但命中的 assetRefId 与请求的**不一致** ⇒ 同一拒绝码（防"读错条目"）。

失败分野（TL 附加要求 3 = 设计候选 O-2）
---------------------------------------
- **(R) 解析/契约失败**（未绑定 / 歧义 / 声明非法 / 停用 / 类型不匹配 / 能力不可用 /
  标题不匹配）⇒ **fail-closed 拒绝**；
- **(D) 数据未命中**（能力可用、读取本身正常、只是该主体没有这条内容）⇒ 维持 v1.3 的
  ``ok/skipped`` 语义，**不**在本模块升级为拒绝（本模块不产出 ``skipped``，
  该语义仍由技能侧 trace 决定：``src/kert/application/skills.py:699-711``）。

可用性探针由**调用方注入**（``SourceProbe``），本模块不内置任何探针
⇒ 不碰文件系统、不判"投影是否存在"。缺少探针是**类型错误**（必填关键字参数），
不是"默认可用"：可用性永远需要被**显式判定**，避免失败被静默吞掉
（现状 ``customer_knowledge.py:35`` 的 fail-open 正是这一问题的来源）。

与 D3-A 的关系
--------------
本模块**不**引入任何本体资产、**不**定义资产语义；它只声明"读取绑定"。
语义权威仍在 ``03_core`` 与知识地图；本体仍只以"契约引用 + 内容哈希版本"只读消费
（``src/kert/domain/ontology_reference.py``）。

plan hash（裁定 O-1 = O-A）
---------------------------
绑定指纹 **不进入** ``plan_hash`` 输入、**不进入** ``plan.versions``：
``planHash`` 的输入语义已由 Contract Owner 追认（v1.5），变更属合同级事项。
本模块只**计算并暴露** ``binding_sha256``（供第二片写入 provenance 留痕），不改任何既有计划。
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from . import ids
from .errors import SchemaValidationError, UsageError

if TYPE_CHECKING:  # 仅类型标注：不在运行期依赖 M7.3 的计划对象
    from .activation_plan import ActivationPlan

SCHEMA = "knowledge_sources/v1"
"""声明 schema（须匹配 :data:`kert.domain.ids.SCHEMA_NAME_RE`）。"""

FILENAME = "knowledge_sources.json"
"""声明文件名（``<ws>/90_control/schema/knowledge_sources.json``）。"""

CAPABILITY_ID_PREFIX = "KS-"
"""能力 ID 前缀（与地图 ``KM-`` / 策略 ``RP-`` / 合同 ``CTR-`` 并列，互不混用）。"""

MAX_LIMIT = 1000
"""单次读取的条数上限（与 ``services.py:82-83`` 的既有上限同口径）。"""

DEFAULT_LIMIT = 100
"""默认条数（与 ``services.py:81`` 的既有默认同口径）。"""

SOURCE_KINDS: tuple[str, ...] = (
    "PARQUET_PROJECTION",
    "GRAPH_PROJECTION",
    "CORE_FILE",
    "STAGE_STORE",
)
"""数据源种类**闭集**（新增种类属设计变更，不得由调用方自定义）。"""

DECLARED_TYPES: tuple[str, ...] = (
    "KNOWLEDGE_ITEM_TEXT",
    "ENTITY_RECORD",
    "RELATION_EDGE",
    "GRAPH_NEIGHBORHOOD",
    "RULE_SET",
    "STAGE_STATE",
)
"""能力可返回的资产类型**闭集**（设计候选 §2.2；独立评审 §4.7 要求按 capability 拆分、
拒绝 ``query(statement)`` 式自由入口）。"""

# 允许字段白名单（未知字段一律拒绝，与 knowledge_map / route_policy 同纪律）
_TOP_FIELDS = {"schema", "version", "title", "capabilities", "bindings", "notes"}
_CAPABILITY_FIELDS = {
    "capabilityId", "title", "sourceKind", "declaredTypes", "readContract",
    "freshnessSource", "version", "failClosed", "enabled",
}
_READ_CONTRACT_FIELDS = {"serviceId", "table", "requires", "assetMatch"}
_ASSET_MATCH_FIELDS = {"field", "pattern"}
_BINDING_FIELDS = {"assetRefId", "capabilityId", "priority", "declaredType"}

#: 资产匹配正则必须具备的命名分组（缺任一 ⇒ 声明非法）
REQUIRED_MATCH_GROUPS = ("assetRefId", "title")

# 拒绝码闭集（**新增码族，不复用既有码**；只存在于内部对象，不经 API 暴露）
CODE_OK = "OK"
CODE_DECLARATION_ABSENT = "KNOWLEDGE_SOURCE_DECLARATION_ABSENT"
CODE_DECLARATION_INVALID = "KNOWLEDGE_SOURCE_DECLARATION_INVALID"
CODE_UNBOUND = "KNOWLEDGE_SOURCE_UNBOUND"
CODE_AMBIGUOUS = "KNOWLEDGE_SOURCE_AMBIGUOUS"
CODE_DISABLED = "KNOWLEDGE_SOURCE_DISABLED"
CODE_UNAVAILABLE = "KNOWLEDGE_SOURCE_UNAVAILABLE"
CODE_CONTRACT_MISMATCH = "KNOWLEDGE_SOURCE_CONTRACT_MISMATCH"
CODE_LIMIT_EXCEEDED = "KNOWLEDGE_SOURCE_LIMIT_EXCEEDED"
CODE_ASSET_REF_UNMATCHED = "KNOWLEDGE_SOURCE_ASSET_REF_UNMATCHED"

DENIAL_CODES: tuple[str, ...] = (
    CODE_DECLARATION_ABSENT,
    CODE_DECLARATION_INVALID,
    CODE_UNBOUND,
    CODE_AMBIGUOUS,
    CODE_DISABLED,
    CODE_UNAVAILABLE,
    CODE_CONTRACT_MISMATCH,
    CODE_LIMIT_EXCEEDED,
    CODE_ASSET_REF_UNMATCHED,
)
"""全部拒绝码（**反空转用**：每个码都必须有一个可构造的触发输入，见单元测试的负例夹具表）。"""


# --------------------------------------------------------------------------- #
# 数据对象
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class SourceHealth:
    """探针报告的能力可用性（由调用方注入的探针给出）。"""

    available: bool
    detail: str = ""


class SourceProbe(Protocol):
    """可用性探针协议（**由调用方注入**）。

    本模块不内置任何实现：真实探针（检查 ``04_serve/<serviceId>/CURRENT.md`` 等）
    属第二片；测试注入桩探针即可覆盖可用/不可用两条分支。
    """

    def health(self, capability: "KnowledgeSourceCapability") -> SourceHealth:
        """返回该能力的可用性；**不得**抛异常以外的"未知"第三态。"""


@dataclass(frozen=True)
class AssetMatch:
    """资产匹配规则（把隐式 ``heading_path[0]`` 约定显式化）。"""

    field: str
    pattern: str

    def match(self, heading: str) -> tuple[str, str] | None:
        """按声明正则匹配标题；未命中返回 ``None``。

        :return: ``(asset_ref_id, title)``；未命中为 ``None``。
        """
        m = _compiled(self.pattern).match(heading)
        if m is None:
            return None
        return m.group("assetRefId"), m.group("title")


@dataclass(frozen=True)
class ReadContract:
    """受控读契约（**声明**，不含调用方原始查询语句）。"""

    service_id: str
    table: str
    requires: tuple[str, ...]
    asset_match: AssetMatch


@dataclass(frozen=True)
class KnowledgeSourceCapability:
    """一条知识源能力（不可变；由控制面 JSON 解析而来）。"""

    capability_id: str
    title: str
    source_kind: str
    declared_types: tuple[str, ...]
    read_contract: ReadContract
    version: str
    freshness_source: str
    fail_closed: bool
    enabled: bool
    source_path: str


@dataclass(frozen=True)
class AssetRefBinding:
    """``asset_ref_id`` → 能力的绑定（``declaredType`` 省略时取能力的唯一声明类型）。"""

    asset_ref_id: str
    capability_id: str
    priority: int
    declared_type: str | None = None


@dataclass(frozen=True)
class KnowledgeSourceDeclaration:
    """一份能力清单 + 绑定表（不可变）。"""

    version: str
    title: str
    capabilities: tuple[KnowledgeSourceCapability, ...]
    bindings: tuple[AssetRefBinding, ...]
    source_path: str
    notes: str | None = None

    def capability(self, capability_id: str) -> KnowledgeSourceCapability | None:
        """按 ID 取能力；不存在返回 ``None``（由调用方按 fail-closed 处理）。"""
        for c in self.capabilities:
            if c.capability_id == capability_id:
                return c
        return None

    @property
    def binding_sha256(self) -> str:
        """绑定指纹（声明内容哈希；64 位小写 hex）。

        **只作留痕**（第二片写入读结果 provenance），**不**进入任何 plan hash
        （TL 裁定 O-1 = O-A）。刻意**不含** ``source_path``：路径是环境相关字段。
        """
        return compute_binding_sha256(self)


@dataclass(frozen=True)
class DeclarationLoad:
    """声明加载结果（fail-closed；``allowed`` 为真时 ``declaration`` 非空）。"""

    code: str
    reason: str
    declaration: KnowledgeSourceDeclaration | None = None

    @property
    def allowed(self) -> bool:
        """是否加载到合法声明。"""
        return self.code == CODE_OK and self.declaration is not None


@dataclass(frozen=True)
class CapabilityResolution:
    """资产引用 → 能力的解析结果（fail-closed；无第三态）。"""

    code: str
    reason: str
    asset_ref_id: str = ""
    capability: KnowledgeSourceCapability | None = None
    declared_type: str | None = None
    binding_priority: int | None = None
    probe_detail: str = ""

    @property
    def allowed(self) -> bool:
        """是否解析到唯一可用能力（含确定的声明类型）。"""
        return (self.code == CODE_OK and self.capability is not None
                and self.declared_type is not None)


@dataclass(frozen=True)
class ReadSpec:
    """读取计划（第二片适配器消费的**受控**入参）。"""

    capability_id: str
    source_kind: str
    declared_type: str
    asset_ref_id: str
    subject_ref: str | None
    limit: int
    service_id: str
    table: str
    requires: tuple[str, ...]
    asset_match_field: str
    binding_sha256: str

    def to_dict(self) -> dict:
        """稳定序列化（键序固定，供审计与跨片对照）。"""
        return {
            "capabilityId": self.capability_id,
            "sourceKind": self.source_kind,
            "declaredType": self.declared_type,
            "assetRefId": self.asset_ref_id,
            "subjectRef": self.subject_ref,
            "limit": self.limit,
            "serviceId": self.service_id,
            "table": self.table,
            "requires": list(self.requires),
            "assetMatchField": self.asset_match_field,
            "bindingSha256": self.binding_sha256,
        }


@dataclass(frozen=True)
class ReadDenial:
    """读取拒绝（fail-closed；携带**首个**未通过门禁的具名拒绝码）。

    ⚠ 本对象**只在内部流转**（TL 硬边界 2）：不得经 API / 错误体暴露。
    """

    code: str
    reason: str
    asset_ref_id: str = ""

    @property
    def allowed(self) -> bool:
        """恒为 ``False``（无第三态）。"""
        return False

    def to_dict(self) -> dict:
        """稳定序列化（内部审计用）。"""
        return {"code": self.code, "reason": self.reason, "assetRefId": self.asset_ref_id}


@dataclass(frozen=True)
class HeadingMatch:
    """标题命中一条声明的资产引用。"""

    asset_ref_id: str
    title: str


# --------------------------------------------------------------------------- #
# 路径与加载
# --------------------------------------------------------------------------- #

def schema_dir(workspace: Path) -> Path:
    """返回控制面 ``schema`` 目录（``<ws>/90_control/schema``）。"""
    return Path(workspace) / "90_control" / "schema"


def declaration_path(workspace: Path) -> Path:
    """返回声明文件路径（``<ws>/90_control/schema/knowledge_sources.json``）。"""
    return schema_dir(workspace) / FILENAME


def parse_declaration(doc: object, *, source: str = "<memory>") -> KnowledgeSourceDeclaration:
    """解析并**严格校验**一份能力清单 + 绑定表（未知字段/类型/取值错误一律拒绝）。

    :param doc: 已反序列化的 JSON 对象。
    :param source: 来源标识（文件相对路径），用于错误定位与审计。
    :raises SchemaValidationError: 结构、类型、取值非法（**契约**错误，非调用方参数错误）。
    """
    if not isinstance(doc, dict):
        raise SchemaValidationError(
            f"[{source}] 声明必须是 JSON 对象，实际为 {type(doc).__name__}")

    unknown = sorted(set(doc) - _TOP_FIELDS)
    if unknown:
        raise SchemaValidationError(f"[{source}] 含未声明字段（拒绝静默忽略）: {unknown}")

    schema = _require_str(doc, "schema", source)
    if not ids.SCHEMA_NAME_RE.match(schema):
        raise SchemaValidationError(
            f"[{source}] schema 非法: {schema!r}（须匹配 {ids.SCHEMA_NAME_RE.pattern}）")
    if schema != SCHEMA:
        raise SchemaValidationError(
            f"[{source}] schema 不支持: {schema!r}（本实现只接受 {SCHEMA!r}）")

    version = _require_str(doc, "version", source)
    _validate(ids.SEMVER_RE, version, "version", source)

    title = _require_str(doc, "title", source)

    capabilities = _parse_capabilities(doc.get("capabilities"), source)
    bindings = _parse_bindings(doc.get("bindings"), source, capabilities)

    notes = doc.get("notes")
    if notes is not None and not isinstance(notes, str):
        raise SchemaValidationError(f"[{source}] notes 必须是字符串")

    return KnowledgeSourceDeclaration(
        version=version,
        title=title,
        capabilities=tuple(capabilities),
        bindings=tuple(bindings),
        source_path=source,
        notes=notes,
    )


def load_declaration(workspace: Path) -> KnowledgeSourceDeclaration | None:
    """加载工作区声明文件；**文件不存在**返回 ``None``（由调用方按 fail-closed 拒绝）。

    ⚠ ``None`` **不是**"无声明也放行"，而是"声明缺失 ⇒ 必须拒绝"（同
    :func:`kert.domain.ontology_reference.load_ontology_reference` 的口径）。

    :raises SchemaValidationError: 文件存在但 JSON 非法或结构校验失败。
    """
    p = declaration_path(workspace)
    if not p.is_file():
        return None
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SchemaValidationError(f"[{FILENAME}] 声明无法解析: {exc}") from exc
    return parse_declaration(doc, source=FILENAME)


def resolve_declaration(workspace: Path) -> DeclarationLoad:
    """把工作区声明解析为**放行/拒绝**（fail-closed 的唯一加载入口）。

    - 声明缺失 ⇒ :data:`CODE_DECLARATION_ABSENT`；
    - 声明非法 ⇒ :data:`CODE_DECLARATION_INVALID`（**不**抛异常穿透，转显式拒绝，
      与 ``ontology_reference.resolve_reference`` 的语义一致）；
    - 声明合法 ⇒ :data:`CODE_OK` 且 ``declaration`` 非空。
    """
    ws = Path(workspace)
    try:
        decl = load_declaration(ws)
    except SchemaValidationError as exc:
        return DeclarationLoad(
            code=CODE_DECLARATION_INVALID,
            reason=f"知识源声明非法 ⇒ 拒绝（fail-closed）: {exc.message}",
        )
    if decl is None:
        return DeclarationLoad(
            code=CODE_DECLARATION_ABSENT,
            reason=(f"控制面未声明知识源能力（{FILENAME} 缺失）⇒ 拒绝："
                    f"'资产引用无读取能力'不得静默通过"),
        )
    return DeclarationLoad(code=CODE_OK, reason="", declaration=decl)


def compute_binding_sha256(declaration: KnowledgeSourceDeclaration) -> str:
    """绑定指纹：对 ``capabilities`` + ``bindings`` 做**确定性**序列化后取 sha256。

    刻意**不含**：``source_path``（环境相关）、``notes``（说明性字段，不参与治理判定）。
    """
    payload = {
        "schema": SCHEMA,
        "version": declaration.version,
        "capabilities": [
            {
                "capabilityId": c.capability_id,
                "sourceKind": c.source_kind,
                "declaredTypes": list(c.declared_types),
                "serviceId": c.read_contract.service_id,
                "table": c.read_contract.table,
                "requires": list(c.read_contract.requires),
                "assetMatchField": c.read_contract.asset_match.field,
                "assetMatchPattern": c.read_contract.asset_match.pattern,
                "freshnessSource": c.freshness_source,
                "version": c.version,
                "failClosed": c.fail_closed,
                "enabled": c.enabled,
            }
            for c in declaration.capabilities
        ],
        "bindings": [
            {
                "assetRefId": b.asset_ref_id,
                "capabilityId": b.capability_id,
                "priority": b.priority,
                "declaredType": b.declared_type,
            }
            for b in declaration.bindings
        ],
    }
    blob = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- #
# 解析链
# --------------------------------------------------------------------------- #

class KnowledgeSourceResolver:
    """资产引用 → 唯一读取能力的解析器（fail-closed；纯计算、无 I/O）。

    门禁顺序（**首个未通过者决定拒绝码**；顺序刻意如此，避免归因错位）：

    1. 声明缺失 ⇒ :data:`CODE_DECLARATION_ABSENT`；
    2. 声明非法 ⇒ :data:`CODE_DECLARATION_INVALID`；
    3. ``asset_ref_id`` 未绑定 ⇒ :data:`CODE_UNBOUND`（**默认拒绝，不回落内置清单**）；
    4. 同优先级多能力绑定 ⇒ :data:`CODE_AMBIGUOUS`（歧义不可裁决，不按加载顺序任取）；
    5. 静态契约不匹配（声明类型缺失/不在能力 ``declaredTypes`` 内）⇒
       :data:`CODE_CONTRACT_MISMATCH`；
    6. 能力被停用 ⇒ :data:`CODE_DISABLED`；
    7. 能力不可用（探针）⇒ :data:`CODE_UNAVAILABLE`。

    为何"静态契约"排在"停用/运行期可用性"之前：契约错误说明**声明本身写错**，
    运维开关与可用性说明**运行条件**。若让开关先判，一个写错的声明会长期被
    "能力已停用"掩盖 ⇒ 归因错位（同 ``activation_plan.py:174-180`` 的既有理由）。
    """

    def __init__(self, load: DeclarationLoad):
        """:param load: :func:`resolve_declaration` 的结果（可为缺失/非法）。"""
        self._load = load

    @classmethod
    def load(cls, workspace: Path) -> "KnowledgeSourceResolver":
        """从工作区加载声明并构造解析器。"""
        return cls(resolve_declaration(workspace))

    @property
    def declaration(self) -> KnowledgeSourceDeclaration | None:
        """已加载的声明（缺失/非法时为 ``None``）。"""
        return self._load.declaration

    @property
    def binding_sha256(self) -> str | None:
        """绑定指纹；声明不可用时为 ``None``（**不留占位串**）。"""
        return self._load.declaration.binding_sha256 if self._load.declaration else None

    def resolve(self, asset_ref_id: str, *, probe: SourceProbe) -> CapabilityResolution:
        """把资产引用解析为唯一可用能力。

        :param asset_ref_id: 计划资产引用（``ActivationPlan.assets[].asset_id`` 的值），
            **不是**管道资产台账的 ``asset_id``。
        :param probe: 可用性探针（**必填**：可用性必须被显式判定）。
        :raises UsageError: ``asset_ref_id`` 形态非法（调用方参数错误）。
        """
        if not isinstance(asset_ref_id, str) or not asset_ref_id.strip():
            raise UsageError(f"资产引用 id 必须是非空字符串: {asset_ref_id!r}")
        ref = asset_ref_id.strip()
        if not ids.ID_RE.match(ref):
            # 调用方参数错误（**非**声明契约错误）：与 knowledge_map.resolve_for_task
            # / route_policy.RouteResolver.resolve 对非法输入的既有处置一致（抛参数类异常）。
            raise UsageError(
                f"非法资产引用 id: {ref!r}（须匹配 {ids.ID_RE.pattern}）")

        if not self._load.allowed:
            return CapabilityResolution(code=self._load.code, reason=self._load.reason,
                                        asset_ref_id=ref)
        decl = self._load.declaration
        assert decl is not None  # allowed ⇒ 非空（见 DeclarationLoad.allowed）

        matched = [b for b in decl.bindings if b.asset_ref_id == ref]
        if not matched:
            bound = sorted({b.asset_ref_id for b in decl.bindings})
            return CapabilityResolution(
                code=CODE_UNBOUND,
                reason=(f"资产引用未绑定任何读取能力（默认拒绝，不回落）: {ref}"
                        f"（已绑定: {bound}）"),
                asset_ref_id=ref,
            )

        top_priority = min(b.priority for b in matched)
        top = [b for b in matched if b.priority == top_priority]
        if len(top) > 1:
            candidates = sorted({b.capability_id for b in top})
            return CapabilityResolution(
                code=CODE_AMBIGUOUS,
                reason=(f"资产引用 {ref} 被 {len(top)} 条**同优先级**（{top_priority}）绑定声明，"
                        f"歧义不可裁决（fail-closed）；候选能力: {candidates}"),
                asset_ref_id=ref,
            )

        binding = top[0]
        capability = decl.capability(binding.capability_id)
        if capability is None:
            # 解析期已校验绑定指向存在的能力，此处为防御性分支（声明不可自洽 ⇒ 拒绝）
            return CapabilityResolution(
                code=CODE_CONTRACT_MISMATCH,
                reason=(f"绑定指向未声明的能力: {binding.capability_id}"
                        f"（声明不自洽 ⇒ 拒绝）"),
                asset_ref_id=ref,
            )

        declared_type = self._resolve_declared_type(binding, capability, ref)
        if isinstance(declared_type, ReadDenial):
            return CapabilityResolution(code=declared_type.code, reason=declared_type.reason,
                                        asset_ref_id=ref)

        if not capability.enabled:
            return CapabilityResolution(
                code=CODE_DISABLED,
                reason=(f"能力已被停用（enabled=false）: {capability.capability_id}"
                        f"（停用等同未绑定，不做回落）"),
                asset_ref_id=ref, capability=capability,
                declared_type=declared_type, binding_priority=binding.priority,
            )

        health = probe.health(capability)
        if not health.available:
            return CapabilityResolution(
                code=CODE_UNAVAILABLE,
                reason=(f"能力不可用（探针判定）: {capability.capability_id}"
                        f"（不得静默返回空结果）"),
                asset_ref_id=ref, capability=capability,
                declared_type=declared_type, binding_priority=binding.priority,
                probe_detail=health.detail,
            )

        return CapabilityResolution(
            code=CODE_OK, reason="", asset_ref_id=ref, capability=capability,
            declared_type=declared_type, binding_priority=binding.priority,
            probe_detail=health.detail,
        )

    def plan_read(self, resolution: CapabilityResolution, *,
                  declared_type: str | None = None,
                  subject_ref: str | None = None,
                  limit: int = DEFAULT_LIMIT) -> ReadSpec | ReadDenial:
        """把解析结果转成受控读取计划（仍**不**读取任何数据）。

        :param resolution: :meth:`resolve` 的结果；被拒时原样透传拒绝。
        :param declared_type: 调用方要求的类型；省略则用解析结果给出的类型。
        :param subject_ref: 主体（如 customerId）。
        :param limit: 条数；``> MAX_LIMIT`` ⇒ :data:`CODE_LIMIT_EXCEEDED`（契约边界）。
        :raises UsageError: ``limit`` 非正整数（调用方编程错误，与 ``services.py:82-83`` 同风格）、
            或 ``subject_ref`` 非空但类型非法。
        """
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
            raise UsageError(f"limit 必须是 >= 1 的整数，收到 {limit!r}")
        if subject_ref is not None and (not isinstance(subject_ref, str) or not subject_ref.strip()):
            raise UsageError(f"subject_ref 必须是非空字符串或省略，收到 {subject_ref!r}")

        if not resolution.allowed or resolution.capability is None:
            return ReadDenial(code=resolution.code, reason=resolution.reason,
                              asset_ref_id=resolution.asset_ref_id)

        capability = resolution.capability
        ref = resolution.asset_ref_id
        if limit > MAX_LIMIT:
            return ReadDenial(
                code=CODE_LIMIT_EXCEEDED,
                reason=f"limit={limit} 超过上限 {MAX_LIMIT}（契约边界）",
                asset_ref_id=ref,
            )

        wanted = declared_type or resolution.declared_type
        if wanted not in capability.declared_types:
            return ReadDenial(
                code=CODE_CONTRACT_MISMATCH,
                reason=(f"请求类型 {wanted!r} 不在能力 {capability.capability_id} 的 "
                        f"declaredTypes={list(capability.declared_types)} 内（闭集纪律）"),
                asset_ref_id=ref,
            )

        contract = capability.read_contract
        return ReadSpec(
            capability_id=capability.capability_id,
            source_kind=capability.source_kind,
            declared_type=wanted,
            asset_ref_id=ref,
            subject_ref=subject_ref.strip() if isinstance(subject_ref, str) else None,
            limit=limit,
            service_id=contract.service_id,
            table=contract.table,
            requires=contract.requires,
            asset_match_field=contract.asset_match.field,
            binding_sha256=self.binding_sha256 or "",
        )

    def match_heading(self, resolution: CapabilityResolution, heading: str
                      ) -> HeadingMatch | ReadDenial:
        """按声明正则校验标题，并把命中结果与该资产引用**逐字比对**。

        :param heading: 现状取自 ``segments.parquet`` 的 ``heading_path[0]``
            （``src/kert/application/customer_knowledge.py:59-61``）。
        :raises UsageError: ``heading`` 非字符串。
        """
        if not isinstance(heading, str):
            raise UsageError(f"标题必须是字符串，收到 {type(heading).__name__}")
        if not resolution.allowed or resolution.capability is None:
            return ReadDenial(code=resolution.code, reason=resolution.reason,
                              asset_ref_id=resolution.asset_ref_id)

        ref = resolution.asset_ref_id
        match = resolution.capability.read_contract.asset_match.match(heading)
        if match is None:
            return ReadDenial(
                code=CODE_ASSET_REF_UNMATCHED,
                reason=(f"标题不匹配声明的匹配规则（field="
                        f"{resolution.capability.read_contract.asset_match.field}，"
                        f"pattern={resolution.capability.read_contract.asset_match.pattern!r}）: "
                        f"{_excerpt(heading)}"),
                asset_ref_id=ref,
            )
        matched_ref, title = match
        if matched_ref != ref:
            return ReadDenial(
                code=CODE_ASSET_REF_UNMATCHED,
                reason=(f"标题命中的资产引用与请求不一致: 命中 {matched_ref}，请求 {ref}"
                        f"（不得把别的条目当作本条读出）"),
                asset_ref_id=ref,
            )
        return HeadingMatch(asset_ref_id=ref, title=title)

    def _resolve_declared_type(self, binding: AssetRefBinding,
                               capability: KnowledgeSourceCapability,
                               ref: str) -> str | ReadDenial:
        """确定该绑定的声明类型（绑定显式给出优先，否则要求能力类型唯一）。"""
        if binding.declared_type is not None:
            if binding.declared_type not in capability.declared_types:
                return ReadDenial(
                    code=CODE_CONTRACT_MISMATCH,
                    reason=(f"绑定声明的类型 {binding.declared_type!r} 不在能力 "
                            f"{capability.capability_id} 的 declaredTypes="
                            f"{list(capability.declared_types)} 内"),
                    asset_ref_id=ref,
                )
            return binding.declared_type
        if len(capability.declared_types) == 1:
            return capability.declared_types[0]
        return ReadDenial(
            code=CODE_CONTRACT_MISMATCH,
            reason=(f"能力 {capability.capability_id} 声明了多个类型 "
                    f"{list(capability.declared_types)}，而绑定未给出 declaredType ⇒ "
                    f"读取契约不明确（拒绝，不猜）"),
            asset_ref_id=ref,
        )


def plan_asset_ref_read(workspace: Path, asset_ref_id: str, *, probe: SourceProbe,
                        declared_type: str | None = None,
                        subject_ref: str | None = None,
                        limit: int = DEFAULT_LIMIT) -> ReadSpec | ReadDenial:
    """一步走完解析链：声明 → 能力 → 读取计划（第二片接线时的唯一入口）。

    仍**不读取任何数据**；成功返回 :class:`ReadSpec`（含 ``binding_sha256``），
    失败返回 :class:`ReadDenial`（具名拒绝码）。
    """
    resolver = KnowledgeSourceResolver.load(workspace)
    resolution = resolver.resolve(asset_ref_id, probe=probe)
    return resolver.plan_read(resolution, declared_type=declared_type,
                              subject_ref=subject_ref, limit=limit)


def asset_ref_ids_of(plan: "ActivationPlan") -> tuple[str, ...]:
    """从 :class:`~kert.domain.activation_plan.ActivationPlan` 取**资产引用 id** 序列。

    **只读**消费：不改计划、不改其任何字段、不参与计划构建。
    返回顺序 = 计划的 ``sequence`` 顺序（``knowledge_map.py:388-418`` 已保证
    ``assetRefs`` 按 ``sequence`` 排序，与 ``activation_plan.py:229-230`` 一致）。

    ⚠ 返回的是**计划资产引用 id**（``PlanAsset.asset_id``），
    **不是**管道资产台账 ``asset_catalog/v1`` 的 ``asset_id``（模块 docstring 的 ①②）。
    """
    out: list[tuple[int, str]] = []
    for asset in plan.assets:
        ref = getattr(asset, "asset_id", None)
        if not isinstance(ref, str) or not ref.strip():
            raise UsageError(f"计划资产引用的 asset_id 必须是非空字符串: {ref!r}")
        out.append((int(getattr(asset, "sequence", 0)), ref.strip()))
    return tuple(ref for _, ref in sorted(out, key=lambda x: x[0]))


# --------------------------------------------------------------------------- #
# 内部校验助手（与 knowledge_map / route_policy / ontology_reference 同风格）
# --------------------------------------------------------------------------- #

def _parse_capabilities(value: object, source: str) -> list[KnowledgeSourceCapability]:
    if not isinstance(value, list) or not value:
        raise SchemaValidationError(f"[{source}] capabilities 必须是非空数组")
    out: list[KnowledgeSourceCapability] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, dict):
            raise SchemaValidationError(f"[{source}] capabilities 元素必须是对象: {item!r}")
        unknown = sorted(set(item) - _CAPABILITY_FIELDS)
        if unknown:
            raise SchemaValidationError(f"[{source}] 能力含未声明字段: {unknown}")

        capability_id = _require_str(item, "capabilityId", source)
        _validate(ids.ID_RE, capability_id, "能力 ID", source)
        if not capability_id.startswith(CAPABILITY_ID_PREFIX):
            raise SchemaValidationError(
                f"[{source}] 能力 ID 必须以 {CAPABILITY_ID_PREFIX!r} 开头: {capability_id!r}")
        if capability_id in seen:
            raise SchemaValidationError(f"[{source}] 能力 ID 重复（歧义）: {capability_id}")
        seen.add(capability_id)

        title = _require_str(item, "title", source)

        source_kind = _require_str(item, "sourceKind", source)
        if source_kind not in SOURCE_KINDS:
            raise SchemaValidationError(
                f"[{source}] sourceKind 不在闭集内: {source_kind!r}（允许: {list(SOURCE_KINDS)}）")

        declared_types = _parse_declared_types(item.get("declaredTypes"), source, capability_id)
        read_contract = _parse_read_contract(item.get("readContract"), source, capability_id)

        freshness_source = _require_str(item, "freshnessSource", source)
        if freshness_source.startswith(("/", "\\")):
            raise SchemaValidationError(
                f"[{source}] freshnessSource 必须是**工作区相对路径**（不得以 '/' 开头）: "
                f"{freshness_source!r}")
        if ".." in freshness_source.split("/"):
            raise SchemaValidationError(
                f"[{source}] freshnessSource 不得含 '..' 段（防越出工作区）: {freshness_source!r}")

        version = _require_str(item, "version", source)
        _validate(ids.SEMVER_RE, version, "能力 version", source)

        fail_closed = item.get("failClosed")
        if fail_closed is not True:
            raise SchemaValidationError(
                f"[{source}] failClosed 只允许 true（本实现不接受 fail-open 能力）: "
                f"{fail_closed!r}")

        enabled = item.get("enabled", True)
        if not isinstance(enabled, bool):
            raise SchemaValidationError(f"[{source}] enabled 必须是布尔值: {enabled!r}")

        out.append(KnowledgeSourceCapability(
            capability_id=capability_id, title=title, source_kind=source_kind,
            declared_types=tuple(declared_types), read_contract=read_contract,
            version=version, freshness_source=freshness_source,
            fail_closed=True, enabled=enabled, source_path=source,
        ))
    return out


def _parse_declared_types(value: object, source: str, capability_id: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise SchemaValidationError(
            f"[{source}] {capability_id} 的 declaredTypes 必须是非空数组")
    out: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise SchemaValidationError(
                f"[{source}] {capability_id} 的 declaredTypes 元素必须是非空字符串: {item!r}")
        if item not in DECLARED_TYPES:
            raise SchemaValidationError(
                f"[{source}] {capability_id} 的 declaredTypes 含闭集外取值: {item!r}"
                f"（允许: {list(DECLARED_TYPES)}）")
        out.append(item)
    dup = sorted({t for t in out if out.count(t) > 1})
    if dup:
        raise SchemaValidationError(f"[{source}] {capability_id} 的 declaredTypes 重复: {dup}")
    return out


def _parse_read_contract(value: object, source: str,
                         capability_id: str) -> ReadContract:
    if not isinstance(value, dict):
        raise SchemaValidationError(f"[{source}] {capability_id} 的 readContract 必须是对象")
    unknown = sorted(set(value) - _READ_CONTRACT_FIELDS)
    if unknown:
        raise SchemaValidationError(f"[{source}] {capability_id} 的 readContract 含未声明字段: {unknown}")

    service_id = _require_str(value, "serviceId", source)
    table = _require_str(value, "table", source)

    requires_raw = value.get("requires", [])
    if not isinstance(requires_raw, list):
        raise SchemaValidationError(f"[{source}] {capability_id} 的 readContract.requires 必须是数组")
    requires: list[str] = []
    for item in requires_raw:
        if not isinstance(item, str) or not item.strip():
            raise SchemaValidationError(
                f"[{source}] {capability_id} 的 readContract.requires 元素必须是非空字符串")
        requires.append(item.strip())

    asset_match_raw = value.get("assetMatch")
    if not isinstance(asset_match_raw, dict):
        raise SchemaValidationError(f"[{source}] {capability_id} 的 readContract.assetMatch 必须是对象")
    unknown_match = sorted(set(asset_match_raw) - _ASSET_MATCH_FIELDS)
    if unknown_match:
        raise SchemaValidationError(
            f"[{source}] {capability_id} 的 assetMatch 含未声明字段: {unknown_match}")
    field = _require_str(asset_match_raw, "field", source)
    pattern = _require_str(asset_match_raw, "pattern", source)
    try:
        compiled = re.compile(pattern)
    except re.error as exc:
        raise SchemaValidationError(
            f"[{source}] {capability_id} 的 assetMatch.pattern 不是合法正则: {exc}") from exc
    missing = [g for g in REQUIRED_MATCH_GROUPS if g not in compiled.groupindex]
    if missing:
        raise SchemaValidationError(
            f"[{source}] {capability_id} 的 assetMatch.pattern 缺命名分组: {missing}"
            f"（必需: {list(REQUIRED_MATCH_GROUPS)}）")

    return ReadContract(service_id=service_id, table=table, requires=tuple(requires),
                        asset_match=AssetMatch(field=field, pattern=pattern))


def _parse_bindings(value: object, source: str,
                    capabilities: list[KnowledgeSourceCapability]) -> list[AssetRefBinding]:
    if not isinstance(value, list) or not value:
        raise SchemaValidationError(f"[{source}] bindings 必须是非空数组")
    known = {c.capability_id for c in capabilities}
    out: list[AssetRefBinding] = []
    seen: set[tuple[str, str]] = set()
    for item in value:
        if not isinstance(item, dict):
            raise SchemaValidationError(f"[{source}] bindings 元素必须是对象: {item!r}")
        unknown = sorted(set(item) - _BINDING_FIELDS)
        if unknown:
            raise SchemaValidationError(f"[{source}] 绑定含未声明字段: {unknown}")

        asset_ref_id = _require_str(item, "assetRefId", source)
        _validate(ids.ID_RE, asset_ref_id, "资产引用 id", source)

        capability_id = _require_str(item, "capabilityId", source)
        if capability_id not in known:
            raise SchemaValidationError(
                f"[{source}] 绑定指向未声明的能力: {capability_id!r}"
                f"（已声明: {sorted(known)}）")

        priority = item.get("priority")
        if not isinstance(priority, int) or isinstance(priority, bool) or priority < 0:
            raise SchemaValidationError(f"[{source}] 绑定 priority 必须是非负整数: {priority!r}")

        declared_type = item.get("declaredType")
        if declared_type is not None:
            if not isinstance(declared_type, str) or declared_type not in DECLARED_TYPES:
                raise SchemaValidationError(
                    f"[{source}] 绑定的 declaredType 必须是闭集内字符串或省略: {declared_type!r}")

        # 同一 (assetRefId, capabilityId) 重复 ⇒ 声明自相矛盾，直接拒绝
        # （同优先级指向**不同**能力的情形留到解析期判为 AMBIGUOUS）
        key = (asset_ref_id, capability_id)
        if key in seen:
            raise SchemaValidationError(
                f"[{source}] 同一资产引用的同一能力被重复绑定（歧义）: "
                f"{asset_ref_id} → {capability_id}")
        seen.add(key)

        out.append(AssetRefBinding(asset_ref_id=asset_ref_id, capability_id=capability_id,
                                   priority=priority, declared_type=declared_type))
    return out


def _validate(pattern: "re.Pattern[str]", value: str, label: str, source: str) -> str:
    """按正则校验取值；不符即抛**契约/参数错误**（由调用方选择语义）。"""
    if not pattern.match(value):
        raise SchemaValidationError(
            f"[{source}] 非法{label}: {value!r}（须匹配 {pattern.pattern}）")
    return value


def _require_str(doc: dict, key: str, source: str) -> str:
    value = doc.get(key)
    if not isinstance(value, str) or not value.strip():
        raise SchemaValidationError(f"[{source}] 缺少必填字段或类型错误: {key}（须为非空字符串）")
    return value.strip()


def _excerpt(text: str, limit: int = 60) -> str:
    """截断长文本用于理由（避免把整段原文灌进错误信息）。"""
    flat = " ".join(str(text).split())
    return flat if len(flat) <= limit else flat[:limit] + "…"


#: 正则编译缓存（同一 pattern 只编译一次；纯进程内缓存，无副作用）
_PATTERNS: dict[str, "re.Pattern[str]"] = {}


def _compiled(pattern: str) -> "re.Pattern[str]":
    """取（并缓存）编译后的正则；解析期已校验合法，此处不做二次校验。"""
    cached = _PATTERNS.get(pattern)
    if cached is None:
        cached = re.compile(pattern)
        _PATTERNS[pattern] = cached
    return cached
