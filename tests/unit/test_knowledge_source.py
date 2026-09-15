"""知识源 typed capability 与资产引用绑定解析链单元测试（M7.1-A 第一片）。

授权：``evidence/m7-3/TL_DECISION_M7-1-FIRST-SLICE.md``（``M7-1-A-AUTHORIZATION``）
设计：``evidence/m7-3/CANDIDATE-M7-1-KNOWLEDGE-SOURCE.md`` §2/§3/§5

本文件覆盖四类纪律：

1. **反空转（负例夹具缺失即 FAIL）**：``DENIAL_CODES`` 的每个拒绝码都必须在
   ``NEGATIVE_FIXTURES`` 中有**可触发**的负例夹具；缺失或触发不出该码 ⇒ 用例 FAIL
   （不是 skip、不是空过）。这是变异 M10 的打击点。
2. **反虚构**：正例一律锚定**受版本控制**的受控工作区实例
   （``examples/bank-front-knowledge-maps``）与其真实资产引用集合，并由
   ``KnowledgeMapRegistry`` 逐条交叉核对（不靠字段自述）。
3. **只读/不接线的机械证明**：
   - 源码扫描证明本模块不引入任何数据引擎依赖、不写文件（TL 硬边界 1）；
   - 源码扫描证明 ``application/**`` 与 ``api/**`` **尚未**引用本模块（"不接线"不是口头声明）。
4. **fail-closed 全覆盖**：声明缺失/非法、未绑定、歧义、停用、不可用、契约不匹配、
   上限越界、标题不匹配 —— 各有具名拒绝码用例；且**无第三态**。
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Callable

import pytest

from kert.domain.activation_plan import ActivationPlanBuilder, PlanDenial
from kert.domain.errors import SchemaValidationError, UsageError
from kert.domain.knowledge_map import KnowledgeMapRegistry
from kert.domain.knowledge_source import (
    CODE_AMBIGUOUS,
    CODE_ASSET_REF_UNMATCHED,
    CODE_CONTRACT_MISMATCH,
    CODE_DECLARATION_ABSENT,
    CODE_DECLARATION_INVALID,
    CODE_DISABLED,
    CODE_LIMIT_EXCEEDED,
    CODE_OK,
    CODE_UNBOUND,
    CODE_UNAVAILABLE,
    DECLARED_TYPES,
    DEFAULT_LIMIT,
    DENIAL_CODES,
    FILENAME,
    MAX_LIMIT,
    REQUIRED_MATCH_GROUPS,
    SCHEMA,
    SOURCE_KINDS,
    HeadingMatch,
    KnowledgeSourceResolver,
    ReadDenial,
    ReadSpec,
    SourceHealth,
    asset_ref_ids_of,
    declaration_path,
    parse_declaration,
    plan_asset_ref_read,
    resolve_declaration,
    schema_dir,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC = REPO_ROOT / "src"

#: 受控工作区实例（受版本控制；与 tests/unit/test_knowledge_map.py 同一实例）
REAL_WS = REPO_ROOT / "examples" / "bank-front-knowledge-maps"
REAL_DECL = REAL_WS / "90_control" / "schema" / FILENAME

#: 受控声明里**必须**存在的资产引用（= customer_knowledge.KI_ITEMS 的 KI 编号 + KI-009，
#: 亦 = 三张地图 assetRefs 的并集；由 test_declaration_covers_all_map_asset_refs 机械核对）
REAL_ASSET_REFS = ("KI-009", "KI-FRONT-001", "KI-FRONT-002", "KI-FRONT-003",
                   "KI-FRONT-004", "KI-FRONT-005", "KI-FRONT-006")

REAL_CAPABILITY_ID = "KS-CUSTOMER-KI-PARQUET"


class StubProbe:
    """可用性桩探针（本模块不内置探针——可用性必须由调用方显式注入）。"""

    def __init__(self, available: bool = True, detail: str = "stub"):
        self._available = available
        self._detail = detail

    def health(self, capability) -> SourceHealth:  # noqa: ANN001 - 协议签名
        return SourceHealth(self._available, self._detail)


def _baseline_doc() -> dict:
    """受控声明的原样副本（负例夹具一律从它派生，避免凭空造声明）。"""
    return json.loads(REAL_DECL.read_text(encoding="utf-8"))


def _write_decl(ws: Path, doc: dict) -> Path:
    d = schema_dir(ws)
    d.mkdir(parents=True, exist_ok=True)
    p = d / FILENAME
    p.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return p


# --------------------------------------------------------------------------- #
# 负例夹具表：拒绝码 → 触发函数（返回实际观察到的拒绝码）
# --------------------------------------------------------------------------- #

def _neg_declaration_absent(ws: Path) -> str:
    """未写入任何声明文件。"""
    return KnowledgeSourceResolver.load(ws).resolve("KI-009", probe=StubProbe()).code


def _neg_declaration_invalid(ws: Path) -> str:
    doc = _baseline_doc()
    doc["capabilities"][0]["未声明字段"] = 1
    _write_decl(ws, doc)
    return KnowledgeSourceResolver.load(ws).resolve("KI-009", probe=StubProbe()).code


def _neg_unbound(ws: Path) -> str:
    doc = _baseline_doc()
    doc["bindings"] = [b for b in doc["bindings"] if b["assetRefId"] == "KI-009"]
    _write_decl(ws, doc)
    return KnowledgeSourceResolver.load(ws).resolve("KI-FRONT-001", probe=StubProbe()).code


def _neg_ambiguous(ws: Path) -> str:
    doc = _baseline_doc()
    clone = copy.deepcopy(doc["capabilities"][0])
    clone["capabilityId"] = REAL_CAPABILITY_ID + "-B"
    doc["capabilities"].append(clone)
    doc["bindings"].append({"assetRefId": "KI-FRONT-001",
                            "capabilityId": clone["capabilityId"], "priority": 10})
    _write_decl(ws, doc)
    return KnowledgeSourceResolver.load(ws).resolve("KI-FRONT-001", probe=StubProbe()).code


def _neg_disabled(ws: Path) -> str:
    doc = _baseline_doc()
    doc["capabilities"][0]["enabled"] = False
    _write_decl(ws, doc)
    return KnowledgeSourceResolver.load(ws).resolve("KI-009", probe=StubProbe()).code


def _neg_unavailable(ws: Path) -> str:
    _write_decl(ws, _baseline_doc())
    return KnowledgeSourceResolver.load(ws).resolve(
        "KI-009", probe=StubProbe(available=False, detail="投影缺失")).code


def _neg_contract_mismatch(ws: Path) -> str:
    doc = _baseline_doc()
    for b in doc["bindings"]:
        if b["assetRefId"] == "KI-009":
            b["declaredType"] = "ENTITY_RECORD"   # 能力只声明 KNOWLEDGE_ITEM_TEXT
    _write_decl(ws, doc)
    return KnowledgeSourceResolver.load(ws).resolve("KI-009", probe=StubProbe()).code


def _neg_limit_exceeded(ws: Path) -> str:
    _write_decl(ws, _baseline_doc())
    r = KnowledgeSourceResolver.load(ws)
    res = r.resolve("KI-009", probe=StubProbe())
    assert res.allowed, "前置解析必须放行，否则本夹具测的不是上限分支"
    return r.plan_read(res, limit=MAX_LIMIT + 1).code


def _neg_asset_ref_unmatched(ws: Path) -> str:
    _write_decl(ws, _baseline_doc())
    r = KnowledgeSourceResolver.load(ws)
    res = r.resolve("KI-FRONT-001", probe=StubProbe())
    assert res.allowed, "前置解析必须放行，否则本夹具测的不是标题匹配分支"
    return r.match_heading(res, "公司供应链图谱（无编号）").code


NEGATIVE_FIXTURES: dict[str, Callable[[Path], str]] = {
    CODE_DECLARATION_ABSENT: _neg_declaration_absent,
    CODE_DECLARATION_INVALID: _neg_declaration_invalid,
    CODE_UNBOUND: _neg_unbound,
    CODE_AMBIGUOUS: _neg_ambiguous,
    CODE_DISABLED: _neg_disabled,
    CODE_UNAVAILABLE: _neg_unavailable,
    CODE_CONTRACT_MISMATCH: _neg_contract_mismatch,
    CODE_LIMIT_EXCEEDED: _neg_limit_exceeded,
    CODE_ASSET_REF_UNMATCHED: _neg_asset_ref_unmatched,
}


# --------------------------------------------------------------------------- #
# 1. 反空转门禁（变异 M10 的打击点）
# --------------------------------------------------------------------------- #

def test_every_denial_code_has_a_negative_fixture(ws: Path):
    """**门禁**：拒绝码闭集里的每个码都必须有负例夹具 —— 缺失即 FAIL（不得空过）。"""
    missing = [c for c in DENIAL_CODES if c not in NEGATIVE_FIXTURES]
    assert not missing, (
        f"以下拒绝码没有负例夹具，否定式断言将恒真（反空转失败）：{missing}")
    assert len(NEGATIVE_FIXTURES) == len(DENIAL_CODES), (
        "负例夹具表与拒绝码闭集长度不一致（有夹具未被闭集收录 ⇒ 存在不可达码）")


@pytest.mark.parametrize("code", DENIAL_CODES)
def test_negative_fixture_triggers_its_named_code(ws: Path, code: str):
    """**门禁**：每个负例夹具必须真的产出**它自己那个**具名拒绝码（不接受"随便一个拒绝"）。"""
    observed = NEGATIVE_FIXTURES[code](ws)
    assert observed == code, f"夹具 {code} 实际产出 {observed}"


# --------------------------------------------------------------------------- #
# 2. 正例：受控声明 + 真实资产引用集合
# --------------------------------------------------------------------------- #

def test_real_declaration_loads_and_is_non_vacuous():
    """反空转：先证明"真的读了受控声明"，再断言由它派生的绑定。"""
    load = resolve_declaration(REAL_WS)
    assert load.allowed, load.reason
    decl = load.declaration
    assert decl is not None
    assert [c.capability_id for c in decl.capabilities] == [REAL_CAPABILITY_ID]
    assert sorted(b.asset_ref_id for b in decl.bindings) == sorted(REAL_ASSET_REFS)
    assert decl.capabilities[0].declared_types == ("KNOWLEDGE_ITEM_TEXT",)
    assert decl.capabilities[0].enabled is True
    assert decl.capabilities[0].fail_closed is True


def test_declaration_covers_all_map_asset_refs():
    """机械核对：三张地图 ``assetRefs`` 的**并集**必须被声明逐一绑定（不许漏网）。"""
    registry = KnowledgeMapRegistry.load(REAL_WS)
    declared_by_maps = {a.asset_id for m in registry.maps for a in m.asset_refs}
    assert declared_by_maps == set(REAL_ASSET_REFS), (
        f"地图声明的资产集与用例基准不一致: {sorted(declared_by_maps)}")

    load = resolve_declaration(REAL_WS)
    assert load.declaration is not None
    bound = {b.asset_ref_id for b in load.declaration.bindings}
    assert bound == declared_by_maps, (
        f"地图声明的资产未被全部绑定: 仅地图 {sorted(declared_by_maps - bound)} / "
        f"仅绑定 {sorted(bound - declared_by_maps)}")


def test_match_rule_is_equivalent_to_legacy_implicit_regex():
    """隐式→显式：声明的 pattern 必须与现状隐式正则 ``customer_knowledge.py:31`` 等价。

    现状：``^(KI-[\\w-]+)\\s+(.+)$``（分组未命名）。等价性用**真实标题**逐条验证，
    不做字符串比对（字符串可以改写得等价，行为等价才是判据）。
    """
    legacy = re.compile(r"^(KI-[\w-]+)\s+(.+)$")
    load = resolve_declaration(REAL_WS)
    assert load.declaration is not None
    match_rule = load.declaration.capabilities[0].read_contract.asset_match
    samples = [
        "KI-009 企业客户基本信息",
        "KI-FRONT-001 公司供应链图谱",
        "KI-FRONT-006 产品候选组合",
        "公司供应链图谱（无编号）",
        "",
        "前言 KI-009 企业客户基本信息",   # 只锚定行首 ⇒ 不匹配
    ]
    for text in samples:
        assert (match_rule.match(text) is None) == (legacy.match(text) is None), text
    assert match_rule.match("KI-FRONT-001 公司供应链图谱") == ("KI-FRONT-001", "公司供应链图谱")


def test_read_spec_carries_declared_contract_verbatim():
    """读计划必须逐字携带声明里的源定位，不得自行发明。"""
    load = resolve_declaration(REAL_WS)
    assert load.declaration is not None
    cap = load.declaration.capabilities[0]
    resolver = KnowledgeSourceResolver.load(REAL_WS)
    spec = resolver.plan_read(resolver.resolve("KI-009", probe=StubProbe()),
                              subject_ref="CUST-CORP-0001")
    assert isinstance(spec, ReadSpec)
    assert spec.service_id == cap.read_contract.service_id
    assert spec.table == cap.read_contract.table
    assert spec.requires == cap.read_contract.requires
    assert spec.asset_match_field == cap.read_contract.asset_match.field
    assert spec.source_kind == cap.source_kind
    assert spec.limit == DEFAULT_LIMIT
    assert spec.binding_sha256 == resolver.binding_sha256


# --------------------------------------------------------------------------- #
# 3. 声明校验（fail-closed：未知字段/非法取值一律拒绝）
# --------------------------------------------------------------------------- #

def _decl(**overrides) -> dict:
    doc = _baseline_doc()
    doc.update(overrides)
    return doc


def _cap(**overrides) -> dict:
    doc = _baseline_doc()
    doc["capabilities"][0].update(overrides)
    return doc


def _dup_capability() -> dict:
    one = _baseline_doc()["capabilities"][0]
    return _decl(capabilities=[one, copy.deepcopy(one)])


#: 非法声明用例：(标签, 声明工厂, 期望错误片段)。
#: 工厂是**惰性**的：模块导入期不读受控声明文件 —— 否则数据文件缺失会导致**收集期错误**
#: （退出码 2），把"声明缺失"的正例用例与"声明非法"的负例用例混为一谈。
INVALID_CASES: list[tuple[str, Callable[[], dict], str]] = [
    ("顶层未知字段", lambda: _decl(extra=1), "未声明字段"),
    ("schema 不符", lambda: _decl(schema="knowledge_sources/v2"), "schema 不支持"),
    ("version 非 semver", lambda: _decl(version="1.0"), "非法version"),
    ("capabilities 空", lambda: _decl(capabilities=[]), "capabilities 必须是非空数组"),
    ("bindings 空", lambda: _decl(bindings=[]), "bindings 必须是非空数组"),
    ("能力 ID 前缀不符", lambda: _cap(capabilityId="X-CUSTOMER"), "必须以 'KS-' 开头"),
    ("能力 sourceKind 越界", lambda: _cap(sourceKind="RANDOM_DB"), "sourceKind 不在闭集内"),
    ("能力 declaredTypes 越界", lambda: _cap(declaredTypes=["FREE_TEXT"]), "闭集外取值"),
    ("能力 failClosed=false", lambda: _cap(failClosed=False), "failClosed 只允许 true"),
    ("能力 enabled 非布尔", lambda: _cap(enabled="yes"), "enabled 必须是布尔值"),
    ("freshnessSource 绝对路径", lambda: _cap(freshnessSource="/etc/passwd"), "工作区相对路径"),
    ("freshnessSource 含 ..", lambda: _cap(freshnessSource="../../x"), "不得含 '..' 段"),
    ("能力 readContract 缺字段", lambda: _cap(readContract={"serviceId": "s"}), "缺少必填字段"),
    ("assetMatch 非法正则", lambda: _cap(readContract={
        "serviceId": "s", "table": "t", "requires": [],
        "assetMatch": {"field": "f", "pattern": "^(KI-["}}), "不是合法正则"),
    ("assetMatch 缺命名分组", lambda: _cap(readContract={
        "serviceId": "s", "table": "t", "requires": [],
        "assetMatch": {"field": "f", "pattern": "^(.+)$"}}), "缺命名分组"),
    ("绑定指向未声明能力", lambda: _decl(bindings=[
        {"assetRefId": "KI-009", "capabilityId": "KS-NOT-DECLARED", "priority": 1}]),
     "指向未声明的能力"),
    ("绑定 priority 为负", lambda: _decl(bindings=[
        {"assetRefId": "KI-009", "capabilityId": REAL_CAPABILITY_ID, "priority": -1}]),
     "priority 必须是非负整数"),
    ("绑定 assetRefId 非法", lambda: _decl(bindings=[
        {"assetRefId": "ki-009", "capabilityId": REAL_CAPABILITY_ID, "priority": 1}]),
     "非法资产引用 id"),
    ("绑定 declaredType 越界", lambda: _decl(bindings=[
        {"assetRefId": "KI-009", "capabilityId": REAL_CAPABILITY_ID,
         "priority": 1, "declaredType": "FREE_TEXT"}]), "闭集内字符串或省略"),
    ("同一资产同一能力重复绑定", lambda: _decl(bindings=[
        {"assetRefId": "KI-009", "capabilityId": REAL_CAPABILITY_ID, "priority": 1},
        {"assetRefId": "KI-009", "capabilityId": REAL_CAPABILITY_ID, "priority": 2}]),
     "重复绑定"),
    ("能力 ID 重复", _dup_capability, "能力 ID 重复"),
]


@pytest.mark.parametrize("label,factory,needle", INVALID_CASES,
                         ids=[c[0] for c in INVALID_CASES])
def test_invalid_declaration_is_rejected(label: str, factory: Callable[[], dict], needle: str):
    with pytest.raises(SchemaValidationError) as ei:
        parse_declaration(factory(), source="t.json")
    assert needle in ei.value.message, f"{label}: 错误信息未点明原因: {ei.value.message}"


def test_non_object_declaration_is_rejected():
    with pytest.raises(SchemaValidationError, match="必须是 JSON 对象"):
        parse_declaration(["not", "a", "dict"], source="t.json")


def test_load_declaration_returns_none_when_absent(ws: Path):
    """缺失 ⇒ ``None``（**不是**"无声明也放行"）。"""
    from kert.domain.knowledge_source import load_declaration
    assert load_declaration(ws) is None
    assert resolve_declaration(ws).code == CODE_DECLARATION_ABSENT


def test_broken_json_maps_to_declaration_invalid(ws: Path):
    declaration_path(ws).parent.mkdir(parents=True, exist_ok=True)
    declaration_path(ws).write_text("{ not json", encoding="utf-8")
    load = resolve_declaration(ws)
    assert load.code == CODE_DECLARATION_INVALID
    assert "非法" in load.reason


# --------------------------------------------------------------------------- #
# 4. 解析链行为（含门禁顺序）
# --------------------------------------------------------------------------- #

def test_resolve_ok_and_denials_are_named(ws: Path):
    """一个正例 + 四个负例（未绑定/歧义/停用/不可用）在同一份声明上并存。"""
    doc = _baseline_doc()
    doc["capabilities"].append({**_baseline_doc()["capabilities"][0],
                                "capabilityId": REAL_CAPABILITY_ID + "-B",
                                "enabled": False})
    doc["bindings"].append({"assetRefId": "KI-FRONT-006",
                            "capabilityId": REAL_CAPABILITY_ID + "-B", "priority": 1})
    _write_decl(ws, doc)
    r = KnowledgeSourceResolver.load(ws)

    ok = r.resolve("KI-009", probe=StubProbe())
    assert ok.allowed and ok.code == CODE_OK
    assert ok.declared_type == "KNOWLEDGE_ITEM_TEXT"
    assert ok.binding_priority == 10

    assert r.resolve("KI-999", probe=StubProbe()).code == CODE_UNBOUND
    assert r.resolve("KI-FRONT-006", probe=StubProbe()).code == CODE_DISABLED
    assert r.resolve("KI-009", probe=StubProbe(False)).code == CODE_UNAVAILABLE

    ambiguous = _baseline_doc()
    ambiguous["capabilities"].append({**ambiguous["capabilities"][0],
                                      "capabilityId": REAL_CAPABILITY_ID + "-B"})
    ambiguous["bindings"].append({"assetRefId": "KI-FRONT-001",
                                  "capabilityId": REAL_CAPABILITY_ID + "-B", "priority": 10})
    _write_decl(ws, ambiguous)
    a = KnowledgeSourceResolver.load(ws).resolve("KI-FRONT-001", probe=StubProbe())
    assert a.code == CODE_AMBIGUOUS
    assert REAL_CAPABILITY_ID in a.reason and "-B" in a.reason


def test_lower_priority_binding_wins(ws: Path):
    """不同优先级 ⇒ 最小者胜（与路由策略同口径），不得按加载顺序任取。"""
    doc = _baseline_doc()
    doc["capabilities"].append({**doc["capabilities"][0],
                                "capabilityId": REAL_CAPABILITY_ID + "-B"})
    doc["bindings"] = [
        {"assetRefId": "KI-009", "capabilityId": REAL_CAPABILITY_ID + "-B", "priority": 20},
        {"assetRefId": "KI-009", "capabilityId": REAL_CAPABILITY_ID, "priority": 5},
    ]
    _write_decl(ws, doc)
    res = KnowledgeSourceResolver.load(ws).resolve("KI-009", probe=StubProbe())
    assert res.allowed
    assert res.capability is not None and res.capability.capability_id == REAL_CAPABILITY_ID
    assert res.binding_priority == 5


def test_static_contract_error_is_not_masked_by_disabled_switch(ws: Path):
    """门禁顺序：静态契约错误必须先于"停用"报告（否则写错的声明被开关长期掩盖）。"""
    doc = _baseline_doc()
    doc["capabilities"][0]["enabled"] = False
    doc["bindings"][0]["declaredType"] = "ENTITY_RECORD"
    _write_decl(ws, doc)
    assert KnowledgeSourceResolver.load(ws).resolve(
        "KI-009", probe=StubProbe(False)).code == CODE_CONTRACT_MISMATCH


def test_plan_read_type_mismatch_and_multi_type_ambiguity(ws: Path):
    _write_decl(ws, _baseline_doc())
    r = KnowledgeSourceResolver.load(ws)
    res = r.resolve("KI-009", probe=StubProbe())
    assert r.plan_read(res, declared_type="RULE_SET").code == CODE_CONTRACT_MISMATCH

    multi = _baseline_doc()
    multi["capabilities"][0]["declaredTypes"] = ["KNOWLEDGE_ITEM_TEXT", "ENTITY_RECORD"]
    _write_decl(ws, multi)
    r2 = KnowledgeSourceResolver.load(ws)
    # 能力声明多类型而绑定未给 declaredType ⇒ 契约不明确，拒绝（不猜）
    assert r2.resolve("KI-009", probe=StubProbe()).code == CODE_CONTRACT_MISMATCH


def test_plan_read_rejects_bad_caller_input(ws: Path):
    _write_decl(ws, _baseline_doc())
    r = KnowledgeSourceResolver.load(ws)
    res = r.resolve("KI-009", probe=StubProbe())
    with pytest.raises(UsageError, match="limit 必须是 >= 1 的整数"):
        r.plan_read(res, limit=0)
    with pytest.raises(UsageError, match="limit 必须是 >= 1 的整数"):
        r.plan_read(res, limit=True)
    with pytest.raises(UsageError, match="subject_ref 必须是非空字符串"):
        r.plan_read(res, subject_ref="  ")
    with pytest.raises(UsageError, match="非法资产引用 id"):
        r.resolve("ki-009", probe=StubProbe())
    with pytest.raises(UsageError, match="资产引用 id 必须是非空字符串"):
        r.resolve("", probe=StubProbe())


def test_match_heading_rejects_other_asset_and_malformed_heading(ws: Path):
    _write_decl(ws, _baseline_doc())
    r = KnowledgeSourceResolver.load(ws)
    res = r.resolve("KI-FRONT-001", probe=StubProbe())
    assert r.match_heading(res, "KI-FRONT-001 公司供应链图谱") == HeadingMatch(
        asset_ref_id="KI-FRONT-001", title="公司供应链图谱")
    other = r.match_heading(res, "KI-009 企业客户基本信息")
    assert isinstance(other, ReadDenial) and other.code == CODE_ASSET_REF_UNMATCHED
    assert "请求 KI-FRONT-001" in other.reason
    bad = r.match_heading(res, "供应链图谱（无编号）")
    assert isinstance(bad, ReadDenial) and bad.code == CODE_ASSET_REF_UNMATCHED
    with pytest.raises(UsageError, match="标题必须是字符串"):
        r.match_heading(res, None)  # type: ignore[arg-type]


def test_denied_resolution_passes_through_all_steps(ws: Path):
    """解析被拒 ⇒ 后续步骤一律原样透传拒绝（不得出现"某一步入参非法"的旁路）。"""
    load = resolve_declaration(ws)
    assert load.code == CODE_DECLARATION_ABSENT
    r = KnowledgeSourceResolver(load)
    res = r.resolve("KI-009", probe=StubProbe())
    assert res.code == CODE_DECLARATION_ABSENT
    planned = r.plan_read(res)
    assert isinstance(planned, ReadDenial) and planned.code == CODE_DECLARATION_ABSENT
    matched = r.match_heading(res, "KI-009 企业客户基本信息")
    assert isinstance(matched, ReadDenial) and matched.code == CODE_DECLARATION_ABSENT
    assert r.binding_sha256 is None


def test_no_third_state():
    """无第三态：拒绝码闭集不含"未命中/skipped"之类语义（数据未命中不在本片建模）。"""
    assert not any(("SKIP" in c) or ("MISS" in c) or ("EMPTY" in c) for c in DENIAL_CODES)
    assert "OK" not in DENIAL_CODES
    assert CODE_OK not in DENIAL_CODES
    assert len(set(DENIAL_CODES)) == len(DENIAL_CODES)


# --------------------------------------------------------------------------- #
# 5. 绑定指纹（裁定 O-1 = O-A：只留痕，不动 planHash）
# --------------------------------------------------------------------------- #

def test_binding_sha256_is_deterministic_and_content_bound(ws: Path):
    load = resolve_declaration(REAL_WS)
    assert load.declaration is not None
    first = load.declaration.binding_sha256
    assert re.fullmatch(r"[0-9a-f]{64}", first), first

    reloaded = resolve_declaration(REAL_WS)
    assert reloaded.declaration is not None
    assert reloaded.declaration.binding_sha256 == first

    changed = _baseline_doc()
    changed["bindings"] = [b for b in changed["bindings"] if b["assetRefId"] != "KI-FRONT-006"]
    _write_decl(ws, changed)
    after = resolve_declaration(ws)
    assert after.declaration is not None
    assert after.declaration.binding_sha256 != first, (
        "绑定内容变化必须改变指纹（否则指纹是常量 ⇒ 无法留痕）")


def test_binding_sha256_excludes_environment_and_notes():
    """指纹刻意不含 source_path（环境相关）与 notes（说明性字段）。"""
    doc = _baseline_doc()
    a = parse_declaration(doc, source="a/knowledge_sources.json")
    b = parse_declaration(dict(doc, notes="完全不同的说明文字"),
                          source="b/other.json")
    assert a.binding_sha256 == b.binding_sha256
    assert a.binding_sha256 == parse_declaration(_baseline_doc()).binding_sha256


def test_declaration_does_not_touch_plan_hash():
    """裁定 O-A：绑定指纹**不**进入计划（计划对象与 planHash 均不含它）。"""
    plan = ActivationPlanBuilder.load(REAL_WS).build("PRE_VISIT_PREPARATION")
    assert not isinstance(plan, PlanDenial), getattr(plan, "reason", "")
    dumped = plan.to_dict()
    assert "knowledgeSources" not in dumped["versions"]
    assert plan.ontology_key  # 非空证明真的走了完整门禁
    assert all("bindingSha256" not in json.dumps(a) for a in dumped["assets"])


# --------------------------------------------------------------------------- #
# 6. 解析链端到端（计划资产引用 → 能力 → 读计划）
# --------------------------------------------------------------------------- #

def test_plan_asset_refs_resolve_to_read_specs_end_to_end():
    """M7.3 → M7.1 衔接：计划给的资产引用**逐条**解析到读计划（顺序 = sequence）。"""
    plan = ActivationPlanBuilder.load(REAL_WS).build("PRE_VISIT_PREPARATION")
    assert not isinstance(plan, PlanDenial), getattr(plan, "reason", "")
    refs = asset_ref_ids_of(plan)
    assert refs == REAL_ASSET_REFS, f"计划资产引用序列不符: {refs}"

    resolver = KnowledgeSourceResolver.load(REAL_WS)
    specs = [resolver.plan_read(resolver.resolve(r, probe=StubProbe()), subject_ref="CUST-CORP-0001")
             for r in refs]
    assert all(isinstance(s, ReadSpec) for s in specs), (
        f"存在未解析的资产引用: {[s.to_dict() for s in specs if not isinstance(s, ReadSpec)]}")
    assert [s.asset_ref_id for s in specs] == list(REAL_ASSET_REFS)
    assert len({s.binding_sha256 for s in specs}) == 1


def test_plan_asset_ref_read_convenience_matches_stepwise():
    stepwise = KnowledgeSourceResolver.load(REAL_WS)
    res = stepwise.resolve("KI-FRONT-002", probe=StubProbe())
    expected = stepwise.plan_read(res, subject_ref="CUST-CORP-0001")
    actual = plan_asset_ref_read(REAL_WS, "KI-FRONT-002", probe=StubProbe(),
                                 subject_ref="CUST-CORP-0001")
    assert isinstance(expected, ReadSpec) and isinstance(actual, ReadSpec)
    assert actual.to_dict() == expected.to_dict()


def test_missing_binding_does_not_fall_back_to_builtin_list(ws: Path):
    """反空转（G1 对治）：删掉一条绑定 ⇒ 该条**拒绝**，且其余条仍可解析。"""
    doc = _baseline_doc()
    doc["bindings"] = [b for b in doc["bindings"] if b["assetRefId"] != "KI-FRONT-005"]
    _write_decl(ws, doc)
    r = KnowledgeSourceResolver.load(ws)
    assert r.resolve("KI-FRONT-005", probe=StubProbe()).code == CODE_UNBOUND
    assert r.resolve("KI-FRONT-004", probe=StubProbe()).allowed


# --------------------------------------------------------------------------- #
# 7. asset_ref_ids_of（命名纪律：这里拿到的是"计划资产引用"，不是管道台账 asset_id）
# --------------------------------------------------------------------------- #

def test_asset_ref_ids_of_sorts_by_sequence_and_types():
    """顺序判据 = ``sequence``。

    夹具刻意让**序列序 ≠ 字典序**（否则"按 sequence 排序"与"按 id 排序"不可区分，
    断言会空转 —— 该空转由变异 M11 实证过）。
    """
    plan = SimpleNamespace(assets=[
        SimpleNamespace(asset_id="KI-FRONT-002", sequence=1),
        SimpleNamespace(asset_id="KI-009", sequence=2),
        SimpleNamespace(asset_id="KI-FRONT-001", sequence=3),
    ])
    assert asset_ref_ids_of(plan) == ("KI-FRONT-002", "KI-009", "KI-FRONT-001")
    assert asset_ref_ids_of(plan) != tuple(sorted(a.asset_id for a in plan.assets))


def test_asset_ref_ids_of_rejects_malformed_asset():
    plan = SimpleNamespace(assets=[SimpleNamespace(asset_id="", sequence=1)])
    with pytest.raises(UsageError, match="必须是非空字符串"):
        asset_ref_ids_of(plan)


# --------------------------------------------------------------------------- #
# 8. 边界机械证明：不读数据、不接线
# --------------------------------------------------------------------------- #

FORBIDDEN_DATA_ENGINES = (
    "pyarrow", "kuzu", "sqlite3", "duckdb", "pandas", "requests", "urllib",
    "socket", "subprocess", "open(",
)


def test_module_source_has_no_data_engine_or_write_dependency():
    """TL 硬边界 1 的机械证明：模块源码不引入数据引擎、不写文件。"""
    text = (SRC / "kert" / "domain" / "knowledge_source.py").read_text(encoding="utf-8")
    hits = [t for t in FORBIDDEN_DATA_ENGINES if t in text]
    assert not hits, f"模块引入了被禁依赖/写操作: {hits}"


def test_module_is_not_wired_into_application_or_api():
    """TL 硬边界 1 的机械证明：``application/**`` 与 ``api/**`` **尚未**引用本模块。

    第二片/第三片接线时本用例会变红 —— 那是**预期**的：届时须同时提交
    「接线范围 + 合同面影响」的独立评审，不得静默接线。
    """
    offenders = []
    for sub in ("application", "api"):
        for p in (SRC / "kert" / sub).rglob("*.py"):
            if "knowledge_source" in p.read_text(encoding="utf-8"):
                offenders.append(p.relative_to(REPO_ROOT).as_posix())
    assert not offenders, f"存在未经授权的接线: {offenders}"


def test_declaration_is_not_placed_in_catalog_dir():
    """TL 硬边界 3：声明必须放 ``schema/``，不得放 ``catalog/``。"""
    assert declaration_path(REAL_WS).parent == schema_dir(REAL_WS)
    assert not (REAL_WS / "90_control" / "catalog" / FILENAME).exists()


def test_closed_sets_are_not_empty_and_schema_matches_convention():
    """闭集与 schema 名的最低自检（防止常量被清空导致断言恒真）。"""
    assert SCHEMA == "knowledge_sources/v1"
    assert DECLARED_TYPES and SOURCE_KINDS
    assert REQUIRED_MATCH_GROUPS == ("assetRefId", "title")
    assert len(DENIAL_CODES) >= 9
