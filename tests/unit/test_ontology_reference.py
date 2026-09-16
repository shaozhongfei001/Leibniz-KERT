"""本体引用单元测试（M7.3 第三步；`PENDING_OWNER_DECISION` §0 的 D3-A + 独立评审 §4.7）。

覆盖三类纪律：

1. **反空转**：先断言"真的读了受控声明文件"（钉值、仓名、仓内路径逐字段等于权威取值），
   再断言由该声明派生出的版本引用；
2. **反虚构 / 零跨仓耦合**：源码中不得出现任何跨仓绝对路径或 gits 仓目录名
   （逐行扫描，避免"某天有人把路径硬编码进来"）；
3. **fail-closed（D-4）**：声明缺失 ⇒ `ONTOLOGY_REFERENCE_ABSENT`；
   未知字段 / 类型错 / schema 不符 / 合同 ID 前缀不符 / `authoritySource` 绝对路径或含 `..` /
   `contentSha256` 长度或大小写非法 ⇒ `ONTOLOGY_REFERENCE_INVALID`。

另覆盖 **D-2 带外核验**：路径由调用方传入，一致则通过，不一致则报错。
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest

from kert.domain.activation_plan import ActivationPlan, ActivationPlanBuilder
from kert.domain.errors import SchemaValidationError
from kert.domain.ontology_reference import (
    CODE_ABSENT,
    CODE_INVALID,
    CODE_OK,
    CONTENT_SHA256_RE,
    FILENAME,
    SCHEMA,
    VERSION_HASH_LEN,
    OntologyReference,
    load_ontology_reference,
    parse_ontology_reference,
    reference_path,
    resolve_reference,
    schema_dir,
    sha256_file,
)
from kert.domain.workspace import init_workspace

REPO_ROOT = Path(__file__).resolve().parents[2]
REAL_WS = REPO_ROOT / "examples" / "bank-front-knowledge-maps"
ONTOLOGY_MODULE = REPO_ROOT / "src" / "kert" / "domain" / "ontology_reference.py"

# 权威取值（任务包 §1：由 TL 实测给出，与 gits 侧黄金计划 versions.ontology 逐字一致）
AUTHORITY_CONTRACT_ID = "CTR-SEM-002"
AUTHORITY_REPO = "gits-cbanking"
AUTHORITY_SOURCE = "specs/semantic/gits-core.owl.ttl"
AUTHORITY_SHA256 = "705578d6324abd0c1bd2bd670e6f3c0ffd8e04c358d0134246c89a3acfc38d00"
AUTHORITY_VERSION = "CTR-SEM-002@sha256:705578d6324abd0c"

VERSION_RE = re.compile(r"^[A-Z][A-Z0-9_-]{2,127}@sha256:[0-9a-f]{16}$")


def _decl(**overrides) -> dict:
    doc = {
        "schema": SCHEMA,
        "contractId": AUTHORITY_CONTRACT_ID,
        "authorityRepo": AUTHORITY_REPO,
        "authoritySource": AUTHORITY_SOURCE,
        "contentSha256": AUTHORITY_SHA256,
    }
    doc.update(overrides)
    return doc


def _write_decl(ws: Path, doc: dict) -> Path:
    d = schema_dir(ws)
    d.mkdir(parents=True, exist_ok=True)
    p = d / FILENAME
    p.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return p


def _ws(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    init_workspace(ws)
    return ws


# --------------------------------------------------------------------------- #
# 受控工作区：声明真的被读到（反空转）
# --------------------------------------------------------------------------- #

def test_real_workspace_declares_ontology_pin():
    """受控 example 工作区的声明必须逐字段等于权威取值（否则后续断言都在测空气）。"""
    assert reference_path(REAL_WS).is_file(), f"缺少声明文件: {reference_path(REAL_WS)}"

    ref = load_ontology_reference(REAL_WS)
    assert isinstance(ref, OntologyReference), "受控工作区必须提供本体引用声明"
    assert ref.contract_id == AUTHORITY_CONTRACT_ID
    assert ref.authority_repo == AUTHORITY_REPO
    assert ref.authority_source == AUTHORITY_SOURCE
    assert ref.content_sha256 == AUTHORITY_SHA256
    assert len(ref.content_sha256) == 64
    assert ref.source_path == FILENAME


def test_version_format_matches_gits_golden_expectation():
    """版本引用 = ``<contractId>@sha256:<前16>``，与 gits 侧黄金计划逐字一致。"""
    ref = load_ontology_reference(REAL_WS)
    assert ref is not None
    assert ref.version == AUTHORITY_VERSION
    assert VERSION_RE.match(ref.version), ref.version
    assert ref.version.split("@sha256:")[1] == ref.content_sha256[:VERSION_HASH_LEN]


def test_real_workspace_plan_carries_ontology_version():
    """端到端：受控工作区的三张地图都产出**携带本体版本**的计划。"""
    for task in ("OUTREACH_PREPARATION", "MEETING_PREPARATION", "PRE_VISIT_PREPARATION"):
        plan = ActivationPlanBuilder.load(REAL_WS).build(task)
        assert isinstance(plan, ActivationPlan), f"{task} 应产出计划，实际 {plan}"
        assert plan.versions["ontology"] == AUTHORITY_VERSION
        assert plan.ontology_key == AUTHORITY_VERSION
        # 来源路径如实记录，但**不**进 hash
        assert plan.ontology_source == f"{AUTHORITY_REPO}:{AUTHORITY_SOURCE}"
        assert AUTHORITY_SOURCE not in plan.plan_hash
        assert AUTHORITY_REPO not in plan.plan_hash
        # 预留槽位不虚构
        assert plan.versions["activationContract"] is None


def test_ontology_pin_is_not_self_verifying():
    """钉值**不可自证**：未经带外核验时不得声称与权威源一致（用测试锁住这个语义）。"""
    ref = load_ontology_reference(REAL_WS)
    assert ref is not None
    # 声明只断言内容哈希；没有任何"已核验"标志可被读取
    assert not hasattr(ref, "verified")
    with pytest.raises(SchemaValidationError, match="核验目标不存在"):
        ref.verify_external(REPO_ROOT / "no" / "such" / "ontology.ttl")


# --------------------------------------------------------------------------- #
# 零跨仓耦合（D-1）：源码中不得出现跨仓路径
# --------------------------------------------------------------------------- #

def test_module_contains_no_cross_repo_path():
    """逐行扫描：实现里不得有任何跨仓绝对路径或 gits 仓目录名。"""
    lines = ONTOLOGY_MODULE.read_text(encoding="utf-8").splitlines()
    forbidden = ("/home/", "gits-cbanking/", "Leibniz-KERT/", "../gits", "specs/semantic/")
    for lineno, line in enumerate(lines, start=1):
        for token in forbidden:
            assert token not in line, f"{ONTOLOGY_MODULE}:{lineno} 出现跨仓耦合 token {token!r}: {line}"
    # 同时确认真的扫到了文件（防"扫了空列表"式空转）
    assert len(lines) > 50


def test_module_has_no_gits_repo_path_constant():
    """实现不得持有指向权威源的路径常量：仓名/仓内路径只应出现在**声明文件**里。"""
    src = ONTOLOGY_MODULE.read_text(encoding="utf-8")
    assert AUTHORITY_SHA256 not in src, "实现不得内置权威哈希（应由声明文件承载）"
    assert AUTHORITY_SOURCE not in src, "实现不得内置权威源路径（应由声明文件承载）"
    assert '"gits-cbanking"' not in src, "实现不得内置仓名（应由声明文件承载）"


# --------------------------------------------------------------------------- #
# 严格解析（契约拒绝）
# --------------------------------------------------------------------------- #

def test_unknown_field_is_rejected():
    with pytest.raises(SchemaValidationError, match="未声明字段"):
        parse_ontology_reference(_decl(extra=1), source="t.json")


def test_non_object_is_rejected():
    with pytest.raises(SchemaValidationError, match="必须是 JSON 对象"):
        parse_ontology_reference([], source="t.json")


def test_missing_required_field_is_rejected():
    doc = _decl()
    del doc["authorityRepo"]
    with pytest.raises(SchemaValidationError, match="authorityRepo"):
        parse_ontology_reference(doc, source="t.json")


@pytest.mark.parametrize(("override", "match"), [
    ({"schema": "ontology_reference/v2"}, "schema 不支持"),
    ({"schema": "ontology_reference"}, "schema 非法"),
    ({"contractId": "SEM-002"}, "必须以 'CTR-' 开头"),
    ({"contractId": "ctr-sem-002"}, "非法合同 ID"),
    ({"authorityRepo": "gits/repo"}, "只(是|能是)\\*\\*仓名\\*\\*"),
    ({"authorityRepo": "../sibling"}, "只(是|能是)\\*\\*仓名\\*\\*"),
    ({"authoritySource": "/abs/specs/gits-core.owl.ttl"}, "必须是\\*\\*仓内相对路径\\*\\*"),
    ({"authoritySource": "../other-repo/onto.ttl"}, "不得含 '\\.\\.' 段"),
    ({"authoritySource": "  "}, "authoritySource"),
    ({"contentSha256": AUTHORITY_SHA256.upper()}, "64 位\\*\\*小写\\*\\* hex"),
    ({"contentSha256": AUTHORITY_SHA256[:16]}, "64 位\\*\\*小写\\*\\* hex"),
    ({"contentSha256": AUTHORITY_SHA256[:63]}, "64 位\\*\\*小写\\*\\* hex"),
    ({"contentSha256": "z" * 64}, "64 位\\*\\*小写\\*\\* hex"),
    ({"contentSha256": 7055}, "contentSha256"),
    ({"pinnedAt": "2026/09/15"}, "pinnedAt 必须是 YYYY-MM-DD"),
    ({"notes": 5}, "notes 必须是字符串"),
])
def test_contract_violations_are_rejected(override: dict, match: str):
    with pytest.raises(SchemaValidationError, match=match):
        parse_ontology_reference(_decl(**override), source="t.json")


def test_optional_fields_are_accepted_and_trimmed():
    ref = parse_ontology_reference(
        _decl(pinnedAt="2026-09-15", notes=" 说明 "), source="t.json")
    assert ref.pinned_at == "2026-09-15"
    assert ref.notes == " 说明 "


def test_hash_rule_is_exactly_64_lowercase_hex():
    """哈希规则的边界：64 位小写 hex 通过，65 位/大写/非 hex 一律拒绝。"""
    assert CONTENT_SHA256_RE.match(AUTHORITY_SHA256)
    for bad in (AUTHORITY_SHA256 + "0", AUTHORITY_SHA256.upper(), "0" * 63):
        assert not CONTENT_SHA256_RE.match(bad)
        with pytest.raises(SchemaValidationError):
            parse_ontology_reference(_decl(contentSha256=bad), source="t.json")


# --------------------------------------------------------------------------- #
# 加载与 fail-closed 裁决（D-4）
# --------------------------------------------------------------------------- #

def test_reference_file_absent_yields_absent_not_none_ok(tmp_path: Path):
    ws = _ws(tmp_path)
    assert not reference_path(ws).exists()
    assert load_ontology_reference(ws) is None

    res = resolve_reference(ws)
    assert not res.allowed
    assert res.code == CODE_ABSENT
    assert res.version is None, "拒绝时不得产出占位版本串"
    assert "不得静默通过" in res.reason


def test_bad_json_declaration_is_invalid(tmp_path: Path):
    ws = _ws(tmp_path)
    d = schema_dir(ws)
    d.mkdir(parents=True, exist_ok=True)
    (d / FILENAME).write_text("{oops", encoding="utf-8")

    with pytest.raises(SchemaValidationError, match="无法解析"):
        load_ontology_reference(ws)

    res = resolve_reference(ws)
    assert not res.allowed and res.code == CODE_INVALID


def test_invalid_declaration_is_invalid_code(tmp_path: Path):
    ws = _ws(tmp_path)
    _write_decl(ws, _decl(contentSha256=AUTHORITY_SHA256.upper()))
    res = resolve_reference(ws)
    assert not res.allowed and res.code == CODE_INVALID
    assert "fail-closed" in res.reason


def test_valid_declaration_yields_ok(tmp_path: Path):
    ws = _ws(tmp_path)
    _write_decl(ws, _decl())
    res = resolve_reference(ws)
    assert res.allowed and res.code == CODE_OK
    assert res.version == AUTHORITY_VERSION
    assert res.reference is not None and res.reference.contract_id == AUTHORITY_CONTRACT_ID


def test_expected_codes_are_stable():
    """拒绝码是对外契约的一部分，改动需显式（防止静默改名/复用既有码）。"""
    assert (CODE_OK, CODE_ABSENT, CODE_INVALID) == (
        "OK", "ONTOLOGY_REFERENCE_ABSENT", "ONTOLOGY_REFERENCE_INVALID")
    assert CODE_ABSENT != "ROUTE_POLICY_ABSENT"
    assert CODE_INVALID != "SCHEMA_VALIDATION_FAILED"


# --------------------------------------------------------------------------- #
# 带外核验（D-2）：路径由调用方传入
# --------------------------------------------------------------------------- #

def test_verify_external_passes_on_matching_bytes(tmp_path: Path, monkeypatch):
    """核验通过：用**真实文件**驱动（先证明 sha256_file 真的读了内容）。"""
    target = tmp_path / "gits-core.owl.ttl"
    payload = b"@prefix kert: <https://example.invalid/kert#> .\n"
    target.write_bytes(payload)

    real_sha = hashlib.sha256(payload).hexdigest()
    assert sha256_file(target) == real_sha  # 证明哈希真的由内容派生

    ref = parse_ontology_reference(_decl(contentSha256=real_sha), source="t.json")
    ref.verify_external(target)  # 不抛即通过


def test_verify_external_fails_on_mismatch(tmp_path: Path):
    target = tmp_path / "gits-core.owl.ttl"
    target.write_bytes(b"changed bytes\n")
    ref = parse_ontology_reference(_decl(), source="t.json")
    with pytest.raises(SchemaValidationError, match="带外核验不一致"):
        ref.verify_external(target)


def test_verify_external_fails_on_missing_path(tmp_path: Path):
    ref = parse_ontology_reference(_decl(), source="t.json")
    with pytest.raises(SchemaValidationError, match="核验目标不存在"):
        ref.verify_external(tmp_path / "absent.ttl")


def test_sha256_file_is_content_sensitive(tmp_path: Path):
    a = tmp_path / "a.bin"
    b = tmp_path / "b.bin"
    a.write_bytes(b"x" * 4096)
    b.write_bytes(b"x" * 4095 + b"y")
    assert sha256_file(a) != sha256_file(b)
    assert sha256_file(a) == hashlib.sha256(b"x" * 4096).hexdigest()


def test_sha256_file_handles_multi_chunk(tmp_path: Path):
    """跨分块边界的内容必须被完整读取（证明流式哈希无截断）。"""
    payload = b"z" * (1024 * 1024 + 7)
    p = tmp_path / "big.bin"
    p.write_bytes(payload)
    assert sha256_file(p) == hashlib.sha256(payload).hexdigest()
