"""内置本体资产（Owner 2026-09-16 推翻 D3-A ⇒ **D-31**）：载入 + provenance + **漂移检测**。

位置：``<ws>/90_control/ontology/``；受控源（仓内）：
``examples/bank-front-knowledge-maps/90_control/ontology/``。

键名与既有 :mod:`kert.domain.ontology_reference` **同口径**：
``contractId`` / ``authorityRepo`` / ``authoritySource`` / ``contentSha256`` / ``version``（不新造名字）。

纪律
----
- **provenance 是信任锚**：每件资产的 ``contentSha256`` 与其来源（仓 / 仓内路径）记在 ``PROVENANCE.json``；
- **漂移即**具名拒绝（:data:`CODE_ASSET_DRIFT`）—— 副本被改、或与记录值不符，**不得**静默继续；
- 本模块**不联网**、运行期**不读** gits 仓；对源仓比对只能由调用方**显式**传入 ``source_root``
  （见 :func:`drift_against_source`，供人类 / 独立 QA 使用）；
- **供给面**（M7-⑤）：``kert provision`` 已接管 ``90_control/ontology/`` 的供给
  （清单 = :func:`kert.domain.ontology_provision.provision_pairs`）；:func:`ensure_assets`
  仍是"不经供给面、显式引入"的入口（拷自受控源并校验），并在返回值中如实标注来源。
  两条路径**同一套 provenance 校验**，不存在"供给来的副本不校验"。
"""
from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from . import hashing

SCHEMA = "ontology_assets/v1"
"""``PROVENANCE.json`` 的 schema。"""

DIRNAME = "ontology"
"""内置本体目录名（``<ws>/90_control/ontology/``）。"""

PROVENANCE_FILENAME = "PROVENANCE.json"

ROLE_OWL = "OWL"
ROLE_SHACL = "SHACL"
ROLE_INSTANCES = "INSTANCES"
ROLE_R2RML = "R2RML"

CODE_OK = "OK"
CODE_ASSETS_ABSENT = "ONTOLOGY_ASSETS_ABSENT"
CODE_PROVENANCE_INVALID = "ONTOLOGY_ASSETS_PROVENANCE_INVALID"
CODE_ASSET_DRIFT = "ONTOLOGY_ASSET_DRIFT"
CODE_ASSET_DECLARATION_MISMATCH = "ONTOLOGY_ASSET_DECLARATION_MISMATCH"
CODE_INSTANCES_NOT_CONFORMING = "ONTOLOGY_INSTANCES_NOT_CONFORMING"
"""SHACL 结论不可用/未通过（``conforms`` 为 ``False``，或声明了 SHACL 却无实例图可判）。"""

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_TOP_KEYS = {"schema", "contractId", "authorityRepo", "version", "pinnedAt", "assets", "notes"}
_ASSET_KEYS = {"file", "authoritySource", "role", "bytes", "contentSha256"}
_ROLES = (ROLE_OWL, ROLE_SHACL, ROLE_INSTANCES, ROLE_R2RML)


class OntologyAssetError(Exception):
    """内置本体资产的**具名**失败（漂移 / 与声明不一致 / 与计划血缘不一致）。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"[{code}] {message}")
        self.code = code
        self.message = message


@dataclass(frozen=True)
class OntologyAsset:
    """一件内置本体资产（不可变）。"""

    file: str
    authority_source: str
    role: str
    bytes: int
    content_sha256: str
    path: Path


@dataclass(frozen=True)
class OntologyAssets:
    """一整套内置本体资产 + 其 provenance。"""

    root: Path
    provenance_path: Path
    contract_id: str
    authority_repo: str
    version: str
    assets: tuple[OntologyAsset, ...]

    def get(self, role: str) -> OntologyAsset | None:
        """按角色取资产（无则 ``None``）。"""
        for a in self.assets:
            if a.role == role:
                return a
        return None

    @property
    def owl(self) -> OntologyAsset:
        """OWL 主资产（缺失即前置校验失败，此处不可达）。"""
        a = self.get(ROLE_OWL)
        assert a is not None  # load_assets 强制要求 OWL 存在
        return a


@dataclass(frozen=True)
class AssetsLoad:
    """载入结果（fail-closed；``allowed`` 为真时 ``assets`` 非空）。"""

    code: str
    reason: str = ""
    assets: OntologyAssets | None = None

    @property
    def allowed(self) -> bool:
        """是否放行。"""
        return self.code == CODE_OK and self.assets is not None


def assets_dir(workspace: Path | str) -> Path:
    """返回内置本体目录（``<ws>/90_control/ontology``）。"""
    return Path(workspace) / "90_control" / DIRNAME


def load_assets(workspace: Path | str, *, verify: bool = True) -> AssetsLoad:
    """载入工作区内置本体资产（``<ws>/90_control/ontology``）并按 provenance 校验。

    语义等同 ``load_assets_from_dir(assets_dir(workspace), verify=verify)``。
    """
    return load_assets_from_dir(assets_dir(workspace), verify=verify)


def load_assets_from_dir(root: Path | str, *, verify: bool = True) -> AssetsLoad:
    """载入**指定目录**内的内置本体资产（受控源目录 / QA 直接指向时用）。

    - ``PROVENANCE.json`` 缺失 ⇒ :data:`CODE_ASSETS_ABSENT`；
    - provenance 结构非法 / 缺 OWL 主资产 ⇒ :data:`CODE_PROVENANCE_INVALID`；
    - 任一资产文件缺失 ⇒ :data:`CODE_ASSETS_ABSENT`（具名到文件）；
    - ``verify=True`` 且实际 sha256 ≠ 记录值 ⇒ :data:`CODE_ASSET_DRIFT`（具名给期望 / 实际）。
    """
    root = Path(root)
    prov_path = root / PROVENANCE_FILENAME
    if not prov_path.is_file():
        return AssetsLoad(code=CODE_ASSETS_ABSENT,
                          reason=f"内置本体目录无 provenance：{prov_path}")
    try:
        doc = json.loads(prov_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return AssetsLoad(code=CODE_PROVENANCE_INVALID,
                          reason=f"provenance 无法解析: {exc}")

    err = _validate_provenance_shape(doc)
    if err:
        return AssetsLoad(code=CODE_PROVENANCE_INVALID, reason=err)

    items: list[OntologyAsset] = []
    for entry in doc["assets"]:
        p = root / entry["file"]
        if not p.is_file():
            return AssetsLoad(code=CODE_ASSETS_ABSENT,
                              reason=f"provenance 声明的资产缺失: {entry['file']}")
        actual = hashing.sha256_file(p)
        if verify and actual != entry["contentSha256"]:
            return AssetsLoad(
                code=CODE_ASSET_DRIFT,
                reason=(f"内置本体资产漂移: {entry['file']} 实际 sha256={actual}，"
                        f"provenance 记录={entry['contentSha256']}"
                        f"（来源 {entry['authoritySource']}）"))
        items.append(OntologyAsset(file=entry["file"], authority_source=entry["authoritySource"],
                                   role=entry["role"], bytes=int(entry["bytes"]),
                                   content_sha256=entry["contentSha256"], path=p))

    assets = OntologyAssets(root=root, provenance_path=prov_path,
                            contract_id=doc["contractId"], authority_repo=doc["authorityRepo"],
                            version=doc["version"], assets=tuple(items))
    if assets.get(ROLE_OWL) is None:
        return AssetsLoad(code=CODE_PROVENANCE_INVALID, reason="provenance 未声明 OWL 主资产")
    return AssetsLoad(code=CODE_OK, reason="", assets=assets)


def ensure_assets(workspace: Path | str, *, source: Path | str, verify: bool = True) -> AssetsLoad:
    """把**受控源**的内置本体引入工作区（仅当工作区尚无副本），再按 :func:`load_assets` 校验。

    :param source: 受控源目录（如 ``examples/bank-front-knowledge-maps/90_control/ontology``）。
    :returns: 载入结果；工作区副本与源**不一致**时**不覆盖**，而是如实报漂移。

    说明：M7-⑤ 起供给面（``provision_pairs``）也接管本子树；此处仍是**显式引入**入口；
    引入后仍以工作区副本 + 其 provenance 为准（provenance 随副本一起拷贝）。
    """
    src = Path(source)
    dst = assets_dir(workspace)
    if not (dst / PROVENANCE_FILENAME).is_file():
        if not (src / PROVENANCE_FILENAME).is_file():
            return AssetsLoad(code=CODE_ASSETS_ABSENT,
                              reason=f"受控源无 provenance：{src / PROVENANCE_FILENAME}")
        dst.mkdir(parents=True, exist_ok=True)
        for p in sorted(src.iterdir()):
            if p.is_file():
                shutil.copyfile(p, dst / p.name)
    return load_assets(workspace, verify=verify)


def drift_against_source(assets: OntologyAssets, source_root: Path | str) -> dict:
    """把内置副本与**源仓**逐件比对（**只读**；仅供人类 / QA 显式调用）。

    :return: ``{file: {"builtin": sha, "source": sha|None, "match": bool}}``
    """
    root = Path(source_root)
    out: dict[str, dict] = {}
    for a in assets.assets:
        p = root / a.authority_source
        src_sha = hashing.sha256_file(p) if p.is_file() else None
        out[a.file] = {"builtin": a.content_sha256, "source": src_sha,
                       "match": src_sha == a.content_sha256}
    return out


def _validate_provenance_shape(doc: object) -> str:
    """provenance 结构校验（未知字段 / 类型错 / 哈希形态错 ⇒ 消息）。"""
    if not isinstance(doc, dict):
        return "provenance 必须是 JSON 对象"
    unknown = sorted(set(doc) - _TOP_KEYS)
    if unknown:
        return f"provenance 含未声明字段: {unknown}"
    for key in ("schema", "contractId", "authorityRepo", "version"):
        if not isinstance(doc.get(key), str) or not doc[key].strip():
            return f"provenance 缺少必填字段或类型错误: {key}"
    if doc["schema"] != SCHEMA:
        return f"provenance schema 不支持: {doc['schema']!r}（期望 {SCHEMA!r}）"
    items = doc.get("assets")
    if not isinstance(items, list) or not items:
        return "provenance.assets 必须是非空数组"
    seen: set[str] = set()
    for entry in items:
        if not isinstance(entry, dict):
            return "provenance.assets 元素必须是对象"
        missing = _ASSET_KEYS - set(entry)
        if missing:
            return f"资产条目缺字段: {sorted(missing)}"
        if entry["role"] not in _ROLES:
            return f"资产 role 非法: {entry['role']!r}"
        if not _SHA256_RE.match(str(entry["contentSha256"])):
            return f"资产 contentSha256 形态非法: {entry['contentSha256']!r}"
        if not isinstance(entry["bytes"], int) or entry["bytes"] < 0:
            return f"资产 bytes 非法: {entry['bytes']!r}"
        if entry["file"] in seen:
            return f"资产 file 重复: {entry['file']!r}"
        seen.add(entry["file"])
    return ""
