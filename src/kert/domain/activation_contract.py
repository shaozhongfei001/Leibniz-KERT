"""激活合同注册与解析（§5.5 ②；依据 GITS 权威 schema）。

背景
----
激活合同（activation contract）的权威实例在 GITS：
``specs/knowledge-architecture/activations/AC-*.json``。KERT 按 §5.5 ① 在工作区控制面
落**受治理副本**，本模块负责把副本解析为不可变模型并做 fail-closed 注册。

权威与位置
----------
- 权威 schema：``specs/knowledge-architecture/schemas/activation-contract.schema.json``
  （``additionalProperties: false``；13 个已声明属性**全部 required**）。
- 副本位置：``<ws>/90_control/schema/activations/AC-*.json``
  （与 ``route_policy.json`` 同属控制面 ``schema`` 目录；**不**读 ``03_core``）。
- 本模块**只解析副本**，不访问 GITS 仓；跨仓一致性由 §5.5 ① 的**哈希对账**负责
  （见 :func:`contract_key` 与 ``docs/architecture/candidates/``）。

fail-closed 规则
----------------
1. **未知字段拒绝**：出现 schema 未声明的字段即 :class:`SchemaValidationError`
   （不静默忽略——这是权威 ``additionalProperties: false`` 的直接映射）；
2. **``schemaVersion`` 白名单**：只接受 :data:`SUPPORTED_SCHEMA_VERSIONS`；
3. **形态/枚举非法拒绝**：``contractId`` 须匹配权威 pattern、``routeMode`` /
   ``failurePolicy`` 须在权威枚举内（不做大小写静默规整）；
4. **默认拒绝**：任务未被任何合同声明 ⇒ 解析结果拒绝（**不回落、不猜测、不取第一个**）；
5. **歧义拒绝**：同一任务被多份合同声明 ⇒ 拒绝。

严格度策略（2026-09-16 Owner 裁定）
--------------------------------
- ``preconditions`` / ``context`` 在权威中**仅声明为 object**（无 ``properties``、
  也无 ``additionalProperties``）⇒ 本模块**只校验已知子字段的类型**，未知子字段
  **接受**（权威刻意未禁止，属可扩展点）。
- **已知权威缺口（本仓不得自行放宽）**：``AC-PREVISIT-001.json`` 携带
  ``knowledgeItemIds``，而权威 schema 未声明该字段且 ``additionalProperties: false``——
  已用 ``jsonschema`` Draft2020-12 **实测该文件不合权威**。裁定为**严格拒收**，
  须由 GITS 侧按 ``docs/governance/CHANGE-CONTROL-PROCESS.md`` 补 schema 或从数据中
  移除；在变更落地前，控制面只能落 2 份合同（见 :data:`_GAP_HINTS`）。

KERT 侧附加完整性规则（**非权威约束**，刻意显式列出以免被误当权威）
----------------------------------------------------------------
1. ``activations`` 不得为空（空合同无可执行语义）；
2. ``activations`` 的 ``assetId`` 与 ``sequence`` 不得重复（重叠即歧义）；
3. 四组引用数组 ``semanticQueries`` / ``ruleChecks`` / ``skills`` / ``humanGates``
   不得内部重复。

引用只读消费
------------
本模块只**读取**副本的 ID、版本与引用（资产 / 语义查询 / 规则 / Skill / 人闸），
不复制其内容，也不解析被引用对象本身。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from . import ids
from .errors import RuleConflictError, SchemaValidationError, UsageError

AUTHORITY_REPO = "gits-cbanking"
"""权威仓名（供 §5.5 ① 写 provenance 与错误信息引用）。"""

AUTHORITY_PATH = "specs/knowledge-architecture/activations"
"""权威实例目录（GITS 仓内相对路径；本模块不访问）。"""

AUTHORITY_SCHEMA_PATH = "specs/knowledge-architecture/schemas/activation-contract.schema.json"
"""权威 schema 路径（本模块不读取，仅用于文档与错误信息）。"""

SUPPORTED_SCHEMA_VERSIONS = ("1.0.0",)
"""接受的 ``schemaVersion``（权威实例当前取值；其它版本一律拒绝）。"""

ACTIVATIONS_DIRNAME = "activations"
"""控制面副本目录名（``<ws>/90_control/schema/activations``）。"""

CONTRACT_ID_RE = re.compile(r"^AC-[A-Z0-9-]+$")
"""合同 ID 形态（**逐字取自权威 schema 的 ``pattern``**，故意不复用 :data:`ids.ID_RE`
——后者允许 ``_``，而权威不允许）。"""

AC_FILE_RE = re.compile(r"^AC-[A-Z0-9-]+\.json$")
"""副本文件名（同时满足合同 ID 形态）。"""

ROUTE_MODES = ("MAP_FIRST", "ONTOLOGY_FIRST", "MAP_THEN_ONTOLOGY", "ONTOLOGY_THEN_MAP")
"""``routeMode`` 合法取值（权威枚举，逐字）。"""

FAILURE_POLICIES = ("FAIL_CLOSED", "DEGRADE_WITH_DISCLOSURE")
"""``failurePolicy`` 合法取值（权威枚举，逐字）。"""

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_TOP_FIELDS = {
    "schemaVersion", "contractId", "version", "taskType", "routeMode", "preconditions",
    "activations", "semanticQueries", "ruleChecks", "skills", "context", "humanGates",
    "failurePolicy",
}
_ACTIVATION_FIELDS = {"assetId", "required", "purpose", "sequence"}
_PRECONDITION_FIELDS = {"requiredInputs", "requiredRoles", "permissionDecisionRequired"}
_CONTEXT_FIELDS = {"maxTokens", "priorityOrder", "trimPolicy"}
_REF_ARRAY_FIELDS = ("semanticQueries", "ruleChecks", "skills", "humanGates")

_GAP_HINTS = {
    "knowledgeItemIds":
        "该字段在权威 schema 中未声明（且 additionalProperties:false），"
        "AC-PREVISIT-001.json 因此不合权威。本仓**不得自行放宽**："
        "须由 GITS 侧按 CHANGE-CONTROL-PROCESS 补 schema 或从数据中移除后再入副本",
}
"""已知权威缺口的拒绝提示（拒收行为本身仍由通用未知字段规则产生，此处只补原因）。"""

# 解析拒绝码（供 §5.5 ③ 校验器与调用方稳定引用）
CODE_OK = "OK"
CODE_NONE_REGISTERED = "ACTIVATION_CONTRACT_NONE_REGISTERED"
CODE_NOT_MAPPED = "ACTIVATION_CONTRACT_NOT_MAPPED"
CODE_AMBIGUOUS = "ACTIVATION_CONTRACT_AMBIGUOUS"


@dataclass(frozen=True)
class ActivationRef:
    """合同声明的一条激活项（只读引用；不复制资产内容）。"""

    asset_id: str
    required: bool
    purpose: str
    sequence: int


@dataclass(frozen=True)
class Preconditions:
    """调用前置条件（已知子字段；未知子字段按裁定接受但不入模型）。"""

    required_inputs: tuple[str, ...]
    required_roles: tuple[str, ...]
    permission_decision_required: bool | None


@dataclass(frozen=True)
class ContractContext:
    """上下文预算（已知子字段；未知子字段按裁定接受但不入模型）。"""

    max_tokens: int | None
    priority_order: tuple[str, ...]
    trim_policy: str | None


@dataclass(frozen=True)
class ActivationContract:
    """一份激活合同（不可变；由控制面副本解析而来）。"""

    contract_id: str
    schema_version: str
    version: str
    task_type: str
    route_mode: str
    preconditions: Preconditions
    activations: tuple[ActivationRef, ...]
    semantic_queries: tuple[str, ...]
    rule_checks: tuple[str, ...]
    skills: tuple[str, ...]
    context: ContractContext
    human_gates: tuple[str, ...]
    failure_policy: str
    source_path: str

    @property
    def key(self) -> str:
        """版本引用键：``<contractId>@<version>``。"""
        return f"{self.contract_id}@{self.version}"

    @property
    def required_asset_ids(self) -> tuple[str, ...]:
        """全部 ``required=True`` 的资产 ID（按 sequence 升序）。"""
        return tuple(a.asset_id for a in self.activations if a.required)


@dataclass(frozen=True)
class ContractResolution:
    """任务 → 激活合同的解析结果（fail-closed：不允许 ``None`` 泄漏给调用方）。"""

    code: str
    reason: str
    contract: ActivationContract | None = None
    candidates: tuple[str, ...] = ()

    @property
    def allowed(self) -> bool:
        """是否解析到唯一合法合同。"""
        return self.code == CODE_OK and self.contract is not None


def contract_key(contract_id: str, content_sha256_hex: str) -> str:
    """构造 §5.5 ④ 的引用键形态：``<contractId>@sha256:<哈希前16>``。

    ``content_sha256_hex`` 须为 64 位**小写** hex（与
    :mod:`kert.domain.ontology_reference` 的钉值口径一致：全量哈希，不是前 16 位）。
    """
    if not isinstance(contract_id, str) or not CONTRACT_ID_RE.match(contract_id):
        raise SchemaValidationError(
            f"非法合同 ID: {contract_id!r}（须匹配 {CONTRACT_ID_RE.pattern}）")
    if not isinstance(content_sha256_hex, str) or not _SHA256_RE.match(content_sha256_hex):
        raise SchemaValidationError(
            f"content sha256 必须是 64 位小写 hex: {content_sha256_hex!r}")
    return f"{contract_id}@sha256:{content_sha256_hex[:16]}"


def activations_dir(workspace: Path) -> Path:
    """返回控制面副本目录（``<ws>/90_control/schema/activations``）。"""
    return Path(workspace) / "90_control" / "schema" / ACTIVATIONS_DIRNAME


def contract_files(workspace: Path) -> list[Path]:
    """列出控制面下的合同副本文件（按文件名排序，保证确定性）。

    目录不存在时返回空列表（**不**抛异常）：未落副本的工作区此时注册表为空，
    任何解析都会以 :data:`CODE_NONE_REGISTERED` 默认拒绝。
    """
    d = activations_dir(workspace)
    if not d.is_dir():
        return []
    return sorted(p for p in d.glob("AC-*.json") if p.is_file() and AC_FILE_RE.match(p.name))


def parse_activation_contract(doc: object, *, source: str = "<memory>") -> ActivationContract:
    """解析并**严格校验**一份激活合同（未知字段/类型/枚举错误一律拒绝）。

    :param doc: 已反序列化的 JSON 对象。
    :param source: 来源标识（文件相对路径），用于错误定位与审计。
    :raises SchemaValidationError: 结构、类型、取值非法。
    """
    if not isinstance(doc, dict):
        raise SchemaValidationError(
            f"[{source}] 激活合同必须是 JSON 对象，实际为 {type(doc).__name__}")

    unknown = sorted(set(doc) - _TOP_FIELDS)
    if unknown:
        hints = "；".join(f"{k}: {_GAP_HINTS[k]}" for k in unknown if k in _GAP_HINTS)
        suffix = f"（{hints}）" if hints else ""
        raise SchemaValidationError(
            f"[{source}] 含未声明字段（拒绝静默忽略）: {unknown}{suffix}"
            f" —— 权威 schema: {AUTHORITY_SCHEMA_PATH}")

    schema_version = _require_str(doc, "schemaVersion", source)
    _validate(ids.SEMVER_RE, schema_version, "schemaVersion", source)
    if schema_version not in SUPPORTED_SCHEMA_VERSIONS:
        raise SchemaValidationError(
            f"[{source}] schemaVersion 不支持: {schema_version!r}"
            f"（本实现只接受 {list(SUPPORTED_SCHEMA_VERSIONS)}）")

    contract_id = _require_str(doc, "contractId", source)
    _validate(CONTRACT_ID_RE, contract_id, "合同 ID", source)

    version = _require_str(doc, "version", source)
    _validate(ids.SEMVER_RE, version, "version", source)

    task_type = _require_str(doc, "taskType", source)

    route_mode = _require_str(doc, "routeMode", source)
    if route_mode not in ROUTE_MODES:
        raise SchemaValidationError(
            f"[{source}] routeMode 非法: {route_mode!r}（须为 {list(ROUTE_MODES)} 之一，"
            f"不做大小写静默规整）")

    preconditions = _parse_preconditions(doc.get("preconditions"), source)
    activations = _parse_activations(doc.get("activations"), source)

    refs: dict[str, tuple[str, ...]] = {}
    for key in _REF_ARRAY_FIELDS:
        if key not in doc:
            raise SchemaValidationError(f"[{source}] 缺少必填字段: {key}（须为字符串数组）")
        refs[key] = tuple(_parse_ref_array(doc.get(key), key, source))

    context = _parse_context(doc.get("context"), source)

    human_gates = refs["humanGates"]

    failure_policy = _require_str(doc, "failurePolicy", source)
    if failure_policy not in FAILURE_POLICIES:
        raise SchemaValidationError(
            f"[{source}] failurePolicy 非法: {failure_policy!r}"
            f"（须为 {list(FAILURE_POLICIES)} 之一）")

    return ActivationContract(
        contract_id=contract_id,
        schema_version=schema_version,
        version=version,
        task_type=task_type,
        route_mode=route_mode,
        preconditions=preconditions,
        activations=tuple(activations),
        semantic_queries=refs["semanticQueries"],
        rule_checks=refs["ruleChecks"],
        skills=refs["skills"],
        context=context,
        human_gates=human_gates,
        failure_policy=failure_policy,
        source_path=source,
    )


def load_activation_contract_file(path: Path, *, workspace: Path | None = None) -> ActivationContract:
    """从控制面 JSON 文件加载一份激活合同。

    :param path: 合同副本文件路径。
    :param workspace: 工作区根（用于错误信息中的相对路径）。
    :raises SchemaValidationError: 文件不存在、JSON 非法或结构校验失败。
    """
    p = Path(path)
    source = p.name if workspace is None else _rel(p, Path(workspace))
    if not p.is_file():
        raise SchemaValidationError(f"[{source}] 激活合同文件不存在: {p}")
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SchemaValidationError(f"[{source}] 激活合同无法解析: {exc}") from exc
    return parse_activation_contract(doc, source=source)


class ActivationContractRegistry:
    """激活合同注册表（不可变快照；由控制面副本加载）。

    用法::

        reg = ActivationContractRegistry.load(ws)
        res = reg.resolve_for_task("PRE_VISIT_PREPARATION")
        if not res.allowed:            # 默认拒绝 / 歧义拒绝
            ...                        # 调用方必须显式处理，不得回落
    """

    def __init__(self, contracts: list[ActivationContract] | tuple[ActivationContract, ...]):
        self._by_id: dict[str, ActivationContract] = {}
        for c in contracts:
            if c.contract_id in self._by_id:
                prev = self._by_id[c.contract_id]
                raise RuleConflictError(
                    f"激活合同 ID 歧义: {c.contract_id} 同时定义于 "
                    f"{prev.source_path} 与 {c.source_path}"
                )
            self._by_id[c.contract_id] = c
        self._contracts: tuple[ActivationContract, ...] = tuple(
            sorted(self._by_id.values(), key=lambda c: c.contract_id))

    @classmethod
    def load(cls, workspace: Path) -> "ActivationContractRegistry":
        """加载工作区控制面下的全部合同副本（``90_control/schema/activations/AC-*.json``）。"""
        ws = Path(workspace)
        return cls([load_activation_contract_file(p, workspace=ws) for p in contract_files(ws)])

    def __len__(self) -> int:
        return len(self._contracts)

    def __contains__(self, contract_id: object) -> bool:
        return contract_id in self._by_id

    @property
    def contracts(self) -> tuple[ActivationContract, ...]:
        """全部合同（按 contractId 排序）。"""
        return self._contracts

    def get(self, contract_id: str) -> ActivationContract:
        """按 ID 取合同；未注册即拒绝（**不**返回 ``None``）。"""
        c = self._by_id.get(contract_id)
        if c is None:
            raise UsageError(
                f"激活合同未注册: {contract_id!r}（已注册: {sorted(self._by_id)}）")
        return c

    def task_types(self) -> tuple[str, ...]:
        """已声明的全部任务类型（排序）。"""
        return tuple(sorted({c.task_type for c in self._contracts}))

    def resolve_for_task(self, task_type: str) -> ContractResolution:
        """把任务类型解析为唯一合法合同。

        - 注册表为空 ⇒ :data:`CODE_NONE_REGISTERED`（默认拒绝）；
        - 无合同声明该任务 ⇒ :data:`CODE_NOT_MAPPED`（默认拒绝）；
        - 同一任务被多份合同声明 ⇒ 歧义拒绝 :data:`CODE_AMBIGUOUS`
          （fail-closed，不按文件名/加载顺序任取）。
        """
        if not isinstance(task_type, str) or not task_type.strip():
            raise UsageError(f"任务类型必须是非空字符串: {task_type!r}")
        task = task_type.strip()

        if not self._contracts:
            return ContractResolution(
                code=CODE_NONE_REGISTERED,
                reason=f"控制面未落任何激活合同副本（{ACTIVATIONS_DIRNAME}/AC-*.json 为空或缺失）",
            )

        matched = [c for c in self._contracts if c.task_type == task]
        if not matched:
            return ContractResolution(
                code=CODE_NOT_MAPPED,
                reason=f"任务未映射到任何激活合同: {task}（已声明任务: {list(self.task_types())}）",
            )
        if len(matched) == 1:
            return ContractResolution(code=CODE_OK, reason="", contract=matched[0])
        return ContractResolution(
            code=CODE_AMBIGUOUS,
            reason=f"任务 {task} 被 {len(matched)} 份合同声明，歧义不可裁决（fail-closed）",
            candidates=tuple(sorted(c.contract_id for c in matched)),
        )


# --------------------------------------------------------------------------- #
# 内部校验助手
# --------------------------------------------------------------------------- #

def _rel(path: Path, ws: Path) -> str:
    try:
        return path.relative_to(ws).as_posix()
    except ValueError:
        return path.as_posix()


def _validate(pattern: "re.Pattern[str]", value: str, label: str, source: str) -> str:
    if not pattern.match(value):
        raise SchemaValidationError(
            f"[{source}] 非法{label}: {value!r}（须匹配 {pattern.pattern}）")
    return value


def _require_str(doc: dict, key: str, source: str) -> str:
    value = doc.get(key)
    if not isinstance(value, str) or not value.strip():
        raise SchemaValidationError(
            f"[{source}] 缺少必填字段或类型错误: {key}（须为非空字符串）")
    return value.strip()


def _require_object(value: object, key: str, source: str) -> dict:
    if not isinstance(value, dict):
        raise SchemaValidationError(f"[{source}] {key} 必须是对象，实际为 {type(value).__name__}")
    return value


def _str_array(value: object, key: str, source: str, *, reject_dup: bool) -> list[str]:
    if not isinstance(value, list):
        raise SchemaValidationError(f"[{source}] {key} 必须是数组")
    out: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise SchemaValidationError(f"[{source}] {key} 元素必须是非空字符串: {item!r}")
        out.append(item.strip())
    if reject_dup:
        dup = sorted({x for x in out if out.count(x) > 1})
        if dup:
            raise SchemaValidationError(f"[{source}] {key} 重复（歧义）: {dup}")
    return out


def _parse_ref_array(value: object, key: str, source: str) -> list[str]:
    return _str_array(value, key, source, reject_dup=True)


def _parse_preconditions(value: object, source: str) -> Preconditions:
    """解析 ``preconditions``：已知子字段做类型校验，**未知子字段接受**（权威未禁止）。"""
    if value is None:
        raise SchemaValidationError(f"[{source}] 缺少必填字段: preconditions（须为对象）")
    doc = _require_object(value, "preconditions", source)

    inputs = doc.get("requiredInputs", [])
    roles = doc.get("requiredRoles", [])
    return Preconditions(
        required_inputs=tuple(_str_array(inputs, "preconditions.requiredInputs", source,
                                        reject_dup=True)),
        required_roles=tuple(_str_array(roles, "preconditions.requiredRoles", source,
                                       reject_dup=True)),
        permission_decision_required=_optional_bool(
            doc.get("permissionDecisionRequired"), "preconditions.permissionDecisionRequired",
            source),
    )


def _parse_context(value: object, source: str) -> ContractContext:
    """解析 ``context``：已知子字段做类型校验，**未知子字段接受**（权威未禁止）。"""
    if value is None:
        raise SchemaValidationError(f"[{source}] 缺少必填字段: context（须为对象）")
    doc = _require_object(value, "context", source)

    max_tokens = doc.get("maxTokens")
    if max_tokens is not None and (not isinstance(max_tokens, int)
                                   or isinstance(max_tokens, bool) or max_tokens < 1):
        raise SchemaValidationError(
            f"[{source}] context.maxTokens 必须是 >=1 的整数，实际为 {max_tokens!r}")

    trim_policy = doc.get("trimPolicy")
    if trim_policy is not None and (not isinstance(trim_policy, str) or not trim_policy.strip()):
        raise SchemaValidationError(
            f"[{source}] context.trimPolicy 必须是非空字符串或省略，实际为 {trim_policy!r}")

    return ContractContext(
        max_tokens=max_tokens,
        priority_order=tuple(_str_array(doc.get("priorityOrder", []), "context.priorityOrder",
                                        source, reject_dup=True)),
        trim_policy=trim_policy.strip() if isinstance(trim_policy, str) else None,
    )


def _optional_bool(value: object, key: str, source: str) -> bool | None:
    if value is None:
        return None
    if not isinstance(value, bool):
        raise SchemaValidationError(f"[{source}] {key} 必须是布尔值或省略，实际为 {value!r}")
    return value


def _parse_activations(value: object, source: str) -> list[ActivationRef]:
    if not isinstance(value, list):
        raise SchemaValidationError(f"[{source}] activations 必须是数组")
    if not value:
        raise SchemaValidationError(
            f"[{source}] activations 不得为空（空合同无可执行语义；KERT 侧附加完整性规则）")

    refs: list[ActivationRef] = []
    for item in value:
        if not isinstance(item, dict):
            raise SchemaValidationError(f"[{source}] activations 元素必须是对象: {item!r}")
        unknown = sorted(set(item) - _ACTIVATION_FIELDS)
        if unknown:
            raise SchemaValidationError(
                f"[{source}] activations 含未声明字段（拒绝静默忽略）: {unknown}")
        for key in ("assetId", "required", "purpose", "sequence"):
            if key not in item:
                raise SchemaValidationError(f"[{source}] activations 缺少必填字段: {key}")

        asset_id = item["assetId"]
        if not isinstance(asset_id, str) or not asset_id.strip():
            raise SchemaValidationError(f"[{source}] activations.assetId 必须是非空字符串")
        required = item["required"]
        if not isinstance(required, bool):
            raise SchemaValidationError(f"[{source}] activations.required 必须是布尔值")
        purpose = item["purpose"]
        if not isinstance(purpose, str) or not purpose.strip():
            raise SchemaValidationError(f"[{source}] activations.purpose 必须是非空字符串")
        sequence = item["sequence"]
        if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 1:
            raise SchemaValidationError(
                f"[{source}] activations.sequence 必须是 >=1 的整数，实际为 {sequence!r}")

        refs.append(ActivationRef(asset_id=asset_id.strip(), required=required,
                                  purpose=purpose.strip(), sequence=sequence))

    ids_seen = sorted({r.asset_id for r in refs if [x.asset_id for x in refs].count(r.asset_id) > 1})
    if ids_seen:
        raise SchemaValidationError(f"[{source}] activations.assetId 重复（歧义）: {ids_seen}")
    seq_seen = sorted({r.sequence for r in refs if [x.sequence for x in refs].count(r.sequence) > 1})
    if seq_seen:
        raise SchemaValidationError(
            f"[{source}] activations.sequence 在同一合同内必须唯一: {seq_seen}")
    return sorted(refs, key=lambda r: r.sequence)
