"""知识地图注册与解析单元测试（M7.3）。

纪律（依据 `docs/development/RULES.md` 测试纪律与文档纪律）：
- **不使用 Mock 代替真实文件**：全部用例都在真实工作区目录上读写 JSON 定义；
- **反空转**：先断言加载到的地图数量与引用基数非零，再断言行为；
- **反虚构**：交叉核对真实地图的 assetRefs 必须是 `skills.py` 中真实读取的 KI；
- **fail-closed 全覆盖**：未知字段 / 非法 ID / 歧义 / 未映射 各自有用例。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from kert.domain.errors import RuleConflictError, SchemaValidationError, UsageError
from kert.domain.knowledge_map import (
    CODE_AMBIGUOUS,
    CODE_NONE_REGISTERED,
    CODE_NOT_MAPPED,
    KnowledgeMapRegistry,
    catalog_dir,
    load_knowledge_map_file,
    parse_knowledge_map,
)
from kert.domain.workspace import init_workspace, is_workspace

REPO_ROOT = Path(__file__).resolve().parents[2]

# 受控工作区实例：`bank_front_ws/` 被 `.gitignore:49` 忽略（运行时数据），
# 权威定义必须放在**受版本控制**的位置，故使用 examples 下的工作区实例
# （与既有 `examples/product-recommendation-assets` 同构，且被代码引用）。
REAL_WS = REPO_ROOT / "examples" / "bank-front-knowledge-maps"

REAL_MAPS = {
    "KM-CORP-RM-OUTREACH": "OUTREACH_PREPARATION",
    "KM-CORP-RM-MEETING": "MEETING_PREPARATION",
    "KM-CORP-RM-PREVISIT": "PRE_VISIT_PREPARATION",
}


def _write_map(ws: Path, filename: str, doc: dict) -> Path:
    d = catalog_dir(ws)
    d.mkdir(parents=True, exist_ok=True)
    p = d / filename
    p.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return p


def _map_doc(**overrides) -> dict:
    doc = {
        "schema": "knowledge_map/v1",
        "mapId": "KM-TEST-0001",
        "version": "1.0.0",
        "title": "测试地图",
        "domain": "customer",
        "tasks": ["TEST_TASK"],
        "priority": 10,
        "assetRefs": [
            {"assetId": "KI-009", "required": True, "sequence": 1},
            {"assetId": "KI-FRONT-004", "required": False, "sequence": 2},
        ],
        "skillRefs": ["skill-customer-outreach-script"],
    }
    doc.update(overrides)
    return doc


# --------------------------------------------------------------------------- #
# 真实工作区（集成性质）：三个既有硬编码 mapId 必须都有真实定义
# --------------------------------------------------------------------------- #

def test_real_workspace_registers_three_maps_with_nonzero_refs():
    """受控工作区实例必须注册 3 张地图，且每张都有非空 assetRefs/skillRefs。"""
    # 先证明这确实是一个**合法工作区**（有 marker），而不是随手放的目录
    assert is_workspace(REAL_WS), f"{REAL_WS} 不是已初始化的 KERT 工作区"

    reg = KnowledgeMapRegistry.load(REAL_WS)

    # 反空转：数量与 ID 基数先断言（否则"加载成功"可能什么都没读到）
    assert len(reg) == 3, f"期望 3 张地图，实际 {len(reg)}：{[m.map_id for m in reg.maps]}"
    assert set(REAL_MAPS) == {m.map_id for m in reg.maps}
    assert set(reg.tasks()) == set(REAL_MAPS.values())

    for map_id, task in REAL_MAPS.items():
        m = reg.get(map_id)
        assert m.asset_refs, f"{map_id} 的 assetRefs 不得为空"
        assert m.skill_refs, f"{map_id} 的 skillRefs 不得为空"
        # sequence 必须唯一且连续从 1 开始（确定性顺序）
        assert [r.sequence for r in m.asset_refs] == list(range(1, len(m.asset_refs) + 1))

        res = reg.resolve_for_task(task)
        assert res.allowed, f"{task} 应解析到 {map_id}，实际 {res.code}: {res.reason}"
        assert res.map is not None and res.map.map_id == map_id
        assert res.map.source_path.endswith(f"{map_id}.json")


def test_real_maps_reference_only_kis_that_skills_actually_read():
    """反虚构：真实地图的 assetRefs 必须出现在 skills.py 真实读取的 KI 中。"""
    skills_src = (REPO_ROOT / "src" / "kert" / "application" / "skills.py").read_text(encoding="utf-8")
    reg = KnowledgeMapRegistry.load(REAL_WS)

    checked = 0
    for m in reg.maps:
        for ref in m.asset_refs:
            assert ref.asset_id in skills_src, (
                f"{m.map_id} 引用了 skills.py 中从未读取的资产 {ref.asset_id}（疑似虚构）"
            )
            checked += 1
    assert checked == 10, f"期望核对 10 条 assetRef，实际 {checked}"  # 3+4+3


# --------------------------------------------------------------------------- #
# fail-closed：默认拒绝 / 歧义拒绝 / 契约拒绝
# --------------------------------------------------------------------------- #

def test_default_deny_when_no_maps_registered(tmp_path: Path):
    """控制面无地图 ⇒ 默认拒绝（不回落、不猜测）。"""
    ws = tmp_path / "ws"
    init_workspace(ws)
    reg = KnowledgeMapRegistry.load(ws)

    assert len(reg) == 0
    res = reg.resolve_for_task("ANY_TASK")
    assert not res.allowed
    assert res.code == CODE_NONE_REGISTERED
    assert res.map is None


def test_default_deny_for_unmapped_task(tmp_path: Path):
    """任务未被任何地图声明 ⇒ 默认拒绝。"""
    ws = tmp_path / "ws"
    init_workspace(ws)
    _write_map(ws, "KM-TEST-0001.json", _map_doc())
    reg = KnowledgeMapRegistry.load(ws)

    assert len(reg) == 1
    res = reg.resolve_for_task("NOT_DECLARED")
    assert not res.allowed and res.code == CODE_NOT_MAPPED
    assert "TEST_TASK" in res.reason  # 拒绝原因必须列出已声明任务，便于排障


def test_same_priority_ambiguity_is_denied(tmp_path: Path):
    """同任务被同优先级的两张地图声明 ⇒ 歧义拒绝（不得按文件名/加载顺序任取）。"""
    ws = tmp_path / "ws"
    init_workspace(ws)
    _write_map(ws, "KM-TEST-0001.json", _map_doc(mapId="KM-TEST-0001", priority=10))
    _write_map(ws, "KM-TEST-0002.json", _map_doc(mapId="KM-TEST-0002", priority=10))
    reg = KnowledgeMapRegistry.load(ws)

    res = reg.resolve_for_task("TEST_TASK")
    assert not res.allowed
    assert res.code == CODE_AMBIGUOUS
    assert res.map is None
    assert res.candidates == ("KM-TEST-0001", "KM-TEST-0002")


def test_lower_priority_wins_deterministically(tmp_path: Path):
    """优先级不同 ⇒ 数值最小者唯一获胜（可裁决，非歧义）。"""
    ws = tmp_path / "ws"
    init_workspace(ws)
    _write_map(ws, "KM-TEST-0001.json", _map_doc(mapId="KM-TEST-0001", priority=30))
    _write_map(ws, "KM-TEST-0002.json", _map_doc(mapId="KM-TEST-0002", priority=10))
    reg = KnowledgeMapRegistry.load(ws)

    res = reg.resolve_for_task("TEST_TASK")
    assert res.allowed and res.map is not None
    assert res.map.map_id == "KM-TEST-0002"


def test_duplicate_map_id_across_files_is_rejected(tmp_path: Path):
    """同一 mapId 出现在多个文件 ⇒ 冲突拒绝（registry 构造即失败）。"""
    ws = tmp_path / "ws"
    init_workspace(ws)
    _write_map(ws, "KM-TEST-0001.json", _map_doc())
    _write_map(ws, "KM-TEST-0002.json", _map_doc(mapId="KM-TEST-0001"))

    with pytest.raises(RuleConflictError, match="歧义"):
        KnowledgeMapRegistry.load(ws)


def test_get_unregistered_map_raises(tmp_path: Path):
    ws = tmp_path / "ws"
    init_workspace(ws)
    reg = KnowledgeMapRegistry.load(ws)
    with pytest.raises(UsageError, match="未注册"):
        reg.get("KM-NOT-EXIST")


@pytest.mark.parametrize("task", ["", "   ", None, 123])
def test_resolve_rejects_blank_task(tmp_path: Path, task):
    ws = tmp_path / "ws"
    init_workspace(ws)
    reg = KnowledgeMapRegistry.load(ws)
    with pytest.raises(UsageError):
        reg.resolve_for_task(task)


# --------------------------------------------------------------------------- #
# 契约校验：未知字段 / 非法取值 / 重复引用
# --------------------------------------------------------------------------- #

def test_unknown_field_is_rejected():
    """未声明字段必须拒绝（不得静默忽略）。"""
    doc = _map_doc()
    doc["unexpectedField"] = "x"
    with pytest.raises(SchemaValidationError, match="未声明字段"):
        parse_knowledge_map(doc, source="t.json")


@pytest.mark.parametrize(
    ("override", "match"),
    [
        ({"schema": "knowledge_map/v2"}, "schema 不支持"),
        ({"mapId": "MAP-LOWER"}, "必须以 'KM-' 开头"),   # ID 形态合法但前缀不符
        ({"mapId": "KM"}, "非法知识地图 ID"),            # 长度不足（ID_RE 要求 >=3 字符）
        ({"version": "1.0"}, "version 非法"),
        ({"domain": "Bad-Domain"}, "非法业务域"),
        ({"tasks": []}, "tasks 必须是非空数组"),
        ({"tasks": ["A", "A"]}, "tasks 重复"),
        ({"priority": -1}, "priority 必须是非负整数"),
        ({"priority": True}, "priority 必须是非负整数"),
        ({"title": "   "}, "title"),
    ],
)
def test_contract_violations_are_rejected(override: dict, match: str):
    with pytest.raises(SchemaValidationError, match=match):
        parse_knowledge_map(_map_doc(**override), source="t.json")


def test_asset_ref_violations_are_rejected():
    with pytest.raises(SchemaValidationError, match="assetRefs 资产重复"):
        parse_knowledge_map(
            _map_doc(assetRefs=[
                {"assetId": "KI-009", "required": True, "sequence": 1},
                {"assetId": "KI-009", "required": True, "sequence": 2},
            ]),
            source="t.json",
        )
    with pytest.raises(SchemaValidationError, match="sequence 在同一地图内必须唯一"):
        parse_knowledge_map(
            _map_doc(assetRefs=[
                {"assetId": "KI-009", "required": True, "sequence": 1},
                {"assetId": "KI-FRONT-004", "required": True, "sequence": 1},
            ]),
            source="t.json",
        )
    with pytest.raises(SchemaValidationError, match="未声明字段"):
        parse_knowledge_map(
            _map_doc(assetRefs=[{"assetId": "KI-009", "required": True,
                                 "sequence": 1, "extra": 1}]),
            source="t.json",
        )
    with pytest.raises(SchemaValidationError, match="assetRefs.sequence 必须是 >=1 的整数"):
        parse_knowledge_map(
            _map_doc(assetRefs=[{"assetId": "KI-009", "required": True, "sequence": 0}]),
            source="t.json",
        )


def test_duplicate_skill_refs_are_rejected():
    with pytest.raises(SchemaValidationError, match="skillRefs 重复"):
        parse_knowledge_map(
            _map_doc(skillRefs=["skill-customer-outreach-script",
                                "skill-customer-outreach-script"]),
            source="t.json",
        )


def test_asset_refs_are_sorted_by_sequence():
    m = parse_knowledge_map(
        _map_doc(assetRefs=[
            {"assetId": "KI-FRONT-006", "required": False, "sequence": 3},
            {"assetId": "KI-009", "required": True, "sequence": 1},
            {"assetId": "KI-FRONT-004", "required": True, "sequence": 2},
        ]),
        source="t.json",
    )
    assert [r.asset_id for r in m.asset_refs] == ["KI-009", "KI-FRONT-004", "KI-FRONT-006"]


def test_non_object_and_bad_json_are_rejected(tmp_path: Path):
    with pytest.raises(SchemaValidationError, match="必须是 JSON 对象"):
        parse_knowledge_map([], source="t.json")

    bad = tmp_path / "KM-BAD-0001.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(SchemaValidationError, match="无法解析"):
        load_knowledge_map_file(bad)

    missing = tmp_path / "KM-MISSING-0001.json"
    with pytest.raises(SchemaValidationError, match="不存在"):
        load_knowledge_map_file(missing)


def test_load_ignores_non_map_files(tmp_path: Path):
    """控制面目录下非 KM-*.json 的文件不得被当作地图（避免误纳）。"""
    ws = tmp_path / "ws"
    init_workspace(ws)
    _write_map(ws, "KM-TEST-0001.json", _map_doc())

    from kert.domain.knowledge_map import map_files
    (catalog_dir(ws) / "README.md").write_text("说明\n", encoding="utf-8")
    (catalog_dir(ws) / "lower_case.json").write_text("{}\n", encoding="utf-8")

    assert [p.name for p in map_files(ws)] == ["KM-TEST-0001.json"]
    assert len(KnowledgeMapRegistry.load(ws)) == 1
