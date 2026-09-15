"""本体引用（M7.3 第三步；依据 `PENDING_OWNER_DECISION` §0 的 **D3-A** 与独立评审 §4.7）。

职责
----
让「本体模型」在 KERT 侧**有落点**：以「契约引用 + 内容哈希版本」**只读消费** gits 本体，
并让本体版本进入可重放 plan hash。本模块**不**持有本体权威，**不**内置 KERT 自有本体。

D-1：引用是**声明的钉值**（declared pin），运行期**零跨仓耦合**
-----------------------------------------------------------
- KERT **不在运行期**读取另一仓（gits）的任何文件、不调用其接口、不硬编码任何跨仓绝对路径；
- 引用以**控制面声明文件**形式存在：``<ws>/90_control/schema/ontology_reference.json``；
- 该文件是**信任锚**（declared trust anchor）：它声明"我们按此合同与内容哈希消费本体"。
- **代价与非声明**：钉值本身在运行期**不可自证**。声明文件只证明"曾按此值声明消费"，
  **不**证明权威源当下仍等于该哈希 —— 后者只能由 D-2 的**带外核验**在运行期之外复核。

D-2：**带外核验**（out-of-band verification）
-------------------------------------------
:meth:`OntologyReference.verify_external` 接受一个**由调用方传入**的路径，计算其 sha256 与钉值比对。
**运行期不使用**该入口；实现中**不存在**任何指向 gits 仓的硬编码路径。

D-4：fail-closed（**新增拒绝码，不复用既有码**）
--------------------------------------------
- 声明文件**缺失** ⇒ 拒绝（``ONTOLOGY_REFERENCE_ABSENT``）—— "本体未被消费"**不得**静默通过；
- 声明文件**非法** ⇒ 拒绝（``ONTOLOGY_REFERENCE_INVALID``）；
- 声明合法 ⇒ 放行，``version = "<contractId>@sha256:<哈希前16>"``（该值进 plan hash，见 D-3）。

⚠ **运维前提（必须随部署满足，本模块不做代理）**：fail-closed 意味着工作区**必须**经供给
（provisioning）放入声明文件，否则该工作区的计划构建会被**全量拒绝**。供给入口已具备：
``kert provision -w <ws> -s examples/bank-front-knowledge-maps``
（``kert.application.provision``，先全量校验后逐份原子写入）。受控 example 工作区
``examples/bank-front-knowledge-maps/`` 即供给源。
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

from . import ids
from .errors import SchemaValidationError

SCHEMA = "ontology_reference/v1"
"""本体引用声明 schema（须匹配 :data:`kert.domain.ids.SCHEMA_NAME_RE`）。"""

FILENAME = "ontology_reference.json"
"""声明文件名（``<ws>/90_control/schema/ontology_reference.json``，与 ``route_policy.json`` 同层）。"""

CONTRACT_ID_PREFIX = "CTR-"
"""合同 ID 前缀（KERT 既有控制面合同 ID 口径，如 ``CTR-SEM-002``）。"""

SCOPE_SEMANTIC = "semantic"
"""本体/语义作用域（D3-A 明确点到"语义层到数据源"与"本体模型"）。"""

VERSION_HASH_LEN = 16
"""版本字符串中的哈希前缀长度（与 ``activation_plan`` 的 plan hash 长度同口径）。"""

CONTENT_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
"""**全量**内容哈希形态：恰为 64 位**小写** hex（大写、短写一律拒绝）。"""

PINNED_AT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
"""声明日期形态（``YYYY-MM-DD``）。"""

# 允许字段白名单（未知字段一律拒绝，见模块 docstring 的 fail-closed 纪律）
_TOP_FIELDS = {
    "schema", "contractId", "authorityRepo", "authoritySource", "contentSha256", "pinnedAt", "notes",
}

# 解析/校验拒绝码（供 ActivationPlan 与调用方稳定引用；**新增码，不复用既有码**）
CODE_OK = "OK"
CODE_ABSENT = "ONTOLOGY_REFERENCE_ABSENT"
CODE_INVALID = "ONTOLOGY_REFERENCE_INVALID"


@dataclass(frozen=True)
class OntologyReference:
    """一份**声明的**本体引用钉值（不可变；由控制面 JSON 解析而来）。

    本对象只承载"声明"，不承载"证明"：字段值如实来自声明文件，
    其与权威源的一致性只能由 :meth:`verify_external` 带外复核。
    """

    contract_id: str
    authority_repo: str
    authority_source: str
    content_sha256: str
    source_path: str
    pinned_at: str | None = None
    notes: str | None = None
    scope: str = SCOPE_SEMANTIC

    @property
    def version(self) -> str:
        """版本引用：``<contractId>@sha256:<全量哈希前16>``（D-3：该值进入 plan hash）。"""
        return f"{self.contract_id}@sha256:{self.content_sha256[:VERSION_HASH_LEN]}"

    def verify_external(self, path: Path) -> None:
        """**带外核验**：把 ``path`` 指向的实际内容 sha256 与钉值比对。

        路径由**调用方传入**，本模块不内置任何跨仓路径；运行期不使用该入口，
        仅供人类/独立 QA 复核"钉值是否仍与权威源一致"。

        :raises SchemaValidationError: 文件不存在/不可读，或内容哈希与钉值不一致。
        """
        p = Path(path)
        if not p.is_file():
            raise SchemaValidationError(
                f"[{self.source_path}] 核验目标不存在或不是文件: {p}")
        actual = sha256_file(p)
        if actual != self.content_sha256:
            raise SchemaValidationError(
                f"[{self.source_path}] 带外核验不一致: {p} 的实际 sha256={actual}，"
                f"声明钉值={self.content_sha256}（合同 {self.contract_id}）")


@dataclass(frozen=True)
class ReferenceResolution:
    """声明 → 放行/拒绝的解析结果（fail-closed；``allowed`` 为真时 ``reference`` 非空）。"""

    code: str
    reason: str
    reference: OntologyReference | None = None

    @property
    def allowed(self) -> bool:
        """是否解析到合法声明。"""
        return self.code == CODE_OK and self.reference is not None

    @property
    def version(self) -> str | None:
        """放行时的版本引用；拒绝时为 ``None``（**不留占位串**）。"""
        return self.reference.version if self.reference is not None else None


def schema_dir(workspace: Path) -> Path:
    """返回控制面 ``schema`` 目录（``<ws>/90_control/schema``）。"""
    return Path(workspace) / "90_control" / "schema"


def reference_path(workspace: Path) -> Path:
    """返回声明文件路径（``<ws>/90_control/schema/ontology_reference.json``）。"""
    return schema_dir(workspace) / FILENAME


def sha256_file(path: Path) -> str:
    """流式计算文件 sha256（64 位小写 hex；分块读取，不整体载入内存）。"""
    h = hashlib.sha256()
    with open(Path(path), "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_ontology_reference(doc: object, *, source: str = "<memory>") -> OntologyReference:
    """解析并**严格校验**一份本体引用声明（未知字段/类型/取值错误一律拒绝）。

    :param doc: 已反序列化的 JSON 对象。
    :param source: 来源标识（文件相对路径），用于错误定位与审计。
    :raises SchemaValidationError: 结构、类型、取值非法（**契约**错误，非调用方参数错误）。
    """
    if not isinstance(doc, dict):
        raise SchemaValidationError(
            f"[{source}] 本体引用声明必须是 JSON 对象，实际为 {type(doc).__name__}")

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

    contract_id = _require_str(doc, "contractId", source)
    _validate(ids.ID_RE, contract_id, "合同 ID", source)
    if not contract_id.startswith(CONTRACT_ID_PREFIX):
        raise SchemaValidationError(
            f"[{source}] 合同 ID 必须以 {CONTRACT_ID_PREFIX!r} 开头: {contract_id!r}")

    authority_repo = _require_str(doc, "authorityRepo", source)
    if "/" in authority_repo or "\\" in authority_repo or ".." in authority_repo:
        raise SchemaValidationError(
            f"[{source}] authorityRepo 必须只是**仓名**（不得含路径分隔符或 '..'）: {authority_repo!r}")

    authority_source = _require_str(doc, "authoritySource", source)
    if authority_source.startswith("/") or authority_source.startswith("\\"):
        raise SchemaValidationError(
            f"[{source}] authoritySource 必须是**仓内相对路径**（不得以 '/' 开头）: {authority_source!r}")
    if ".." in authority_source.split("/"):
        raise SchemaValidationError(
            f"[{source}] authoritySource 不得含 '..' 段（防越出所属仓）: {authority_source!r}")

    content_sha256 = _require_str(doc, "contentSha256", source)
    if not CONTENT_SHA256_RE.match(content_sha256):
        raise SchemaValidationError(
            f"[{source}] contentSha256 必须是 64 位**小写** hex（全量哈希，不是前 16 位）: "
            f"{content_sha256!r}")

    pinned_at = doc.get("pinnedAt")
    if pinned_at is not None:
        if not isinstance(pinned_at, str) or not PINNED_AT_RE.match(pinned_at):
            raise SchemaValidationError(
                f"[{source}] pinnedAt 必须是 YYYY-MM-DD 字符串或省略: {pinned_at!r}")

    notes = doc.get("notes")
    if notes is not None and not isinstance(notes, str):
        raise SchemaValidationError(f"[{source}] notes 必须是字符串")

    return OntologyReference(
        contract_id=contract_id,
        authority_repo=authority_repo,
        authority_source=authority_source,
        content_sha256=content_sha256,
        source_path=source,
        pinned_at=pinned_at,
        notes=notes,
    )


def load_ontology_reference(workspace: Path) -> OntologyReference | None:
    """加载工作区声明文件；**文件不存在**返回 ``None``（由调用方按 fail-closed 拒绝）。

    ⚠ 与 :class:`ReferenceResolution` 的 ABSENT 分支配对：``None`` **不是**"无本体也放行"，
    而是"声明缺失 ⇒ 必须拒绝"。

    :raises SchemaValidationError: 文件存在但 JSON 非法或结构校验失败。
    """
    p = reference_path(workspace)
    if not p.is_file():
        return None
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SchemaValidationError(f"[{FILENAME}] 本体引用声明无法解析: {exc}") from exc
    return parse_ontology_reference(doc, source=FILENAME)


def resolve_reference(workspace: Path, *, source: str = FILENAME) -> ReferenceResolution:
    """把工作区声明解析为**放行/拒绝**（D-4 的唯一裁决入口；fail-closed）。

    - 声明文件缺失 ⇒ :data:`CODE_ABSENT`（"本体未被消费"不得静默通过）；
    - 声明文件非法 ⇒ :data:`CODE_INVALID`（**不**抛异常穿透，转为显式拒绝，
      与 :class:`~kert.domain.route_policy.RouteResolver` 的拒绝语义一致）；
    - 声明合法 ⇒ :data:`CODE_OK` 且 ``version`` 非空。
    """
    ws = Path(workspace)
    try:
        ref = load_ontology_reference(ws)
    except SchemaValidationError as exc:
        return ReferenceResolution(
            code=CODE_INVALID,
            reason=f"本体引用声明非法 ⇒ 拒绝（fail-closed）: {exc.message}",
        )
    if ref is None:
        return ReferenceResolution(
            code=CODE_ABSENT,
            reason=(f"控制面未声明本体引用（{FILENAME} 缺失）⇒ 拒绝："
                    f"'本体未被消费'不得静默通过"),
        )
    return ReferenceResolution(code=CODE_OK, reason="", reference=ref)


# --------------------------------------------------------------------------- #
# 内部校验助手（与 knowledge_map / route_policy 同风格：契约错误 ⇒ SchemaValidationError）
# --------------------------------------------------------------------------- #

def _validate(pattern: "re.Pattern[str]", value: str, label: str, source: str) -> str:
    if not pattern.match(value):
        raise SchemaValidationError(
            f"[{source}] 非法{label}: {value!r}（须匹配 {pattern.pattern}）")
    return value


def _require_str(doc: dict, key: str, source: str) -> str:
    value = doc.get(key)
    if not isinstance(value, str) or not value.strip():
        raise SchemaValidationError(f"[{source}] 缺少必填字段或类型错误: {key}（须为非空字符串）")
    return value.strip()
