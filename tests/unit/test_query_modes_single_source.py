"""D-28 层 2 第六片：**检索 / 图谱查询词表**单源核对（清单 #23 / #24 / #25）。

分工：

- **源** = ``kert.domain.query_modes``（三个词表 + 具名常量 + `GRAPH_CYPHER_ARROWS`）—— 本文件 ①；
- **闭集校验（真实方法）** = `KnowledgeService.search` / `KnowledgeService.graph` —— 本文件 ②；
- **Cypher 箭头查表（真实函数 + 短接后端）** = `KnowledgeService._graph_kuzu` —— 本文件 ③
  （kuzu 后端**短接**为捕获 SQL 的假连接：确定性、不依赖真实图库，且断言"确实走了 Kuzu 路径"）；
- **合同** = `SearchRequest.mode` / `GraphQueryRequest.direction` / `GraphQueryRequest.mode`
  —— 由 `test_contract_enum_single_source.py` 的 `MAPPINGS`（三行）核对。

范围与残留（**显式登记**，见 ④）：本片按 E-13 **不碰** `src/kert/cli/main.py`
（含他人在途改动）⇒ 其 3 处默认值字面量为已知残留；防复发断言**显式限定**到本片实际改动范围。

⚠ 同名异域（不得合并）：`cli/main.py` 的 `--mode fast|full`（无关开关）；
以及 `SearchRequest.mode` 与 `GraphQueryRequest.mode`（两个 schema、值域不同）—— 见 ⑤。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (str(REPO_ROOT / "src"), str(REPO_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from kert.application.services import KnowledgeService  # noqa: E402
from kert.domain.errors import UsageError  # noqa: E402
from kert.domain.query_modes import (  # noqa: E402
    DIRECTION_BOTH,
    DIRECTION_IN,
    DIRECTION_OUT,
    GRAPH_CYPHER_ARROWS,
    GRAPH_DIRECTIONS,
    GRAPH_MODE_CLOSURE,
    GRAPH_MODE_NEIGHBOR,
    GRAPH_MODE_PATHS,
    GRAPH_MODES,
    SEARCH_MODE_FULLTEXT,
    SEARCH_MODE_HYBRID,
    SEARCH_MODE_VECTOR,
    SEARCH_MODES,
)

SERVICE_SRC = REPO_ROOT / "src" / "kert" / "application" / "services.py"
SERVER_SRC = REPO_ROOT / "src" / "kert" / "api" / "server.py"
GATES_SRC = REPO_ROOT / "src" / "kert" / "application" / "gates.py"
CLI_SRC = REPO_ROOT / "src" / "kert" / "cli" / "main.py"

SEGMENTS = [
    {"segment_id": "SEG-1", "document_id": "DOC-1", "content": "利率走势与定价说明",
     "page_from": 1, "page_to": 1, "source_release_id": "R1", "source_path": "01_raw/x.md"},
    {"segment_id": "SEG-2", "document_id": "DOC-2", "content": "无关内容",
     "page_from": 2, "page_to": 2},
]


class _FakeTable:
    def __init__(self, rows: list[dict]):
        self._rows = rows

    def to_pylist(self) -> list[dict]:
        return list(self._rows)


class _MetaSpy:
    """`_meta(**extra)` 的**捕获替身**：不查活动投影，只记录调用实参（仍是行为钉子）。"""

    def __init__(self):
        self.calls: list[dict] = []

    def __call__(self, **extra) -> dict:
        self.calls.append(dict(extra))
        return dict(extra)


def _patched_svc(monkeypatch, ws) -> tuple[KnowledgeService, _MetaSpy]:
    """短接**投影读取**与**活动版本查询**（本用例只关心模式分派，不关心投影是否就绪）。

    - `segments.parquet` 给定行、其余为空 ⇒ VECTOR 走"无向量 ⇒ 降级"分支；
    - `_meta` 换捕获替身 ⇒ 可断言 `ranking_policy_version` 的**实参**（无需供货工作区）。
    """
    svc = KnowledgeService(ws)
    spy = _MetaSpy()

    def _fake_read_table(name: str, *, filters=None):
        return _FakeTable(SEGMENTS if name == "segments.parquet" else [])

    monkeypatch.setattr(svc, "_read_table", _fake_read_table)
    monkeypatch.setattr(svc, "_meta", spy)
    return svc, spy


class _FakeKuzuConnection:
    def __init__(self):
        self.sql: list[str] = []

    def execute(self, sql: str, params=None):  # noqa: ANN001, ARG002 - 探针
        self.sql.append(sql)
        return _FakeKuzuResult()


class _FakeKuzuResult:
    def get_all(self) -> list:
        return []


class _FakeKuzuDatabase:
    def close(self) -> None:
        pass


class _FakeKuzuModule:
    """kuzu 模块替身：记录 `execute` 收到的 Cypher（**短接后端**，不依赖真实图库）。"""

    def __init__(self):
        self.connections: list[_FakeKuzuConnection] = []

    def Database(self, path):  # noqa: N802 - 复刻上游命名
        return _FakeKuzuDatabase()

    def Connection(self, db):  # noqa: N802 - 复刻上游命名
        con = _FakeKuzuConnection()
        self.connections.append(con)
        return con


class _FakeKuzuBuilder:
    def __init__(self, workspace, service_id="product_knowledge"):  # noqa: ARG002 - 探针
        pass

    def graph_available(self, version=None) -> bool:  # noqa: ARG002 - 探针
        return True

    def graph_path(self, version=None) -> Path:  # noqa: ARG002 - 探针
        return Path("/nonexistent/graph")


def _cypher_for(monkeypatch, ws, direction: str, mode: str) -> list[str]:
    """走**公开入口** `graph()`（含闭集校验）→ 短接的 Kuzu 路径 → 返回捕获的 Cypher 列表。"""
    fake = _FakeKuzuModule()
    monkeypatch.setitem(sys.modules, "kuzu", fake)
    monkeypatch.setattr("kert.infrastructure.graph.kuzu_builder.KuzuGraphBuilder",
                        _FakeKuzuBuilder)
    svc = KnowledgeService(ws)
    monkeypatch.setattr(svc, "_meta", _MetaSpy())      # 免活动投影（本用例只关心 Cypher）
    svc.graph(["E1"], direction=direction, mode=mode, max_depth=2)
    assert fake.connections, "未走到 Kuzu 路径（短接失败会静默回退内存实现 ⇒ 必须显式失败）"
    return fake.connections[-1].sql


# --------------------------------------------------------------------------- #
# ① 源自身
# --------------------------------------------------------------------------- #

def test_sources_are_closed_ordered_and_named():
    assert SEARCH_MODES == ("FULLTEXT", "VECTOR", "HYBRID")
    assert (SEARCH_MODE_FULLTEXT, SEARCH_MODE_VECTOR, SEARCH_MODE_HYBRID) == SEARCH_MODES
    assert GRAPH_DIRECTIONS == ("OUT", "IN", "BOTH")
    assert (DIRECTION_OUT, DIRECTION_IN, DIRECTION_BOTH) == GRAPH_DIRECTIONS
    assert GRAPH_MODES == ("neighbor", "closure", "paths")
    assert (GRAPH_MODE_NEIGHBOR, GRAPH_MODE_CLOSURE, GRAPH_MODE_PATHS) == GRAPH_MODES


def test_cypher_arrow_map_is_complete_and_byte_pinned():
    """**查表地图**：键 == 源、值逐项钉死（缺键即 KeyError；改一个箭头 ⇒ 本用例红）。"""
    assert GRAPH_CYPHER_ARROWS == {DIRECTION_OUT: "->", DIRECTION_IN: "<-", DIRECTION_BOTH: "-"}
    assert set(GRAPH_CYPHER_ARROWS) == set(GRAPH_DIRECTIONS)
    assert len(set(GRAPH_CYPHER_ARROWS.values())) == len(GRAPH_CYPHER_ARROWS), "箭头必须互异"


# --------------------------------------------------------------------------- #
# ② 闭集校验 + 各模式产出（真实方法，短接投影读取）
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("bad", ["bogus", "fulltext", "", "HYBRID "])
def test_search_rejects_out_of_set_modes(monkeypatch, ws, bad):
    svc, _spy = _patched_svc(monkeypatch, ws)
    with pytest.raises(UsageError) as ei:
        svc.search("利率", mode=bad)
    assert "非法检索模式" in str(ei.value), ei.value


def test_search_closed_set_values_are_unchanged(monkeypatch, ws):
    """**值域一字未变的证据面**：三个合法值都**不被**判非法，且各自走对自己的分支。"""
    svc, spy = _patched_svc(monkeypatch, ws)

    ft = svc.search("利率", mode=SEARCH_MODE_FULLTEXT)
    assert ft.data["mode"] == "FULLTEXT", "立源是零行为变化：回显的模式值必须不变"
    assert ft.data["hit_count"] >= 1 and ft.data["hits"][0]["score_type"] == "FULLTEXT"
    assert ft.data["degraded"] is False
    assert spy.calls[-1]["ranking_policy_version"] == "none"

    hy = svc.search("利率", mode=SEARCH_MODE_HYBRID)
    assert hy.data["mode"] == "HYBRID"
    assert hy.data["hit_count"] >= 1 and hy.data["hits"][0]["score_type"] == "HYBRID"
    assert hy.data["degraded"] is False
    assert spy.calls[-1]["ranking_policy_version"] == "rank/v1"

    ve = svc.search("利率", mode=SEARCH_MODE_VECTOR)
    assert ve.data["mode"] == "VECTOR"
    assert ve.data["hit_count"] == 0, "无向量投影 ⇒ 无命中"
    assert ve.data["degraded"] is True, "VECTOR 且无向量 ⇒ 降级标记必须为真"
    assert spy.calls[-1]["ranking_policy_version"] == "none"


@pytest.mark.parametrize("direction, mode", [("OUT", "neighbor"), ("IN", "closure"),
                                             ("BOTH", "paths")])
def test_graph_closed_set_values_are_unchanged(monkeypatch, ws, direction, mode):
    """**值域一字未变的证据面（字面量级）**：三组合法值都必须被受理且原样回显。

    走内存回退路径（裸工作区无图 ⇒ `graph_available()` 为假）——不依赖 Kùzu 后端。
    """
    svc, _spy = _patched_svc(monkeypatch, ws)
    res = svc.graph(["E1"], direction=direction, mode=mode)   # 不得抛 UsageError
    assert res.data["mode"] == mode


@pytest.mark.parametrize("bad_dir", ["out", "INBOTH", ""])
def test_graph_rejects_out_of_set_directions(monkeypatch, ws, bad_dir):
    with pytest.raises(UsageError) as ei:
        KnowledgeService(ws).graph(["E1"], direction=bad_dir)
    assert "非法 direction" in str(ei.value), ei.value


@pytest.mark.parametrize("bad_mode", ["neighbors", "closure ", "PATHS"])
def test_graph_rejects_out_of_set_modes(monkeypatch, ws, bad_mode):
    with pytest.raises(UsageError) as ei:
        KnowledgeService(ws).graph(["E1"], mode=bad_mode)
    assert "非法 mode" in str(ei.value), ei.value


# --------------------------------------------------------------------------- #
# ③ Cypher 箭头查表（真实 `_graph_kuzu`，短接后端）
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("direction, expect, forbidden", [
    (DIRECTION_OUT, "->", "<-"),
    (DIRECTION_IN, "<-", "->"),
    (DIRECTION_BOTH, "-", "->"),
])
def test_arrow_lookup_drives_the_generated_cypher(monkeypatch, ws, direction, expect, forbidden):
    """**查表用例**：方向 → 箭头必须**由地图决定**（改地图里一个箭头 ⇒ 本用例红）。"""
    sqls = _cypher_for(monkeypatch, ws, direction, GRAPH_MODE_NEIGHBOR)
    hops = [s for s in sqls if ":Rel*1..2" in s]
    assert hops, sqls
    assert all(f"-[:Rel*1..2]{expect}(" in s for s in hops), hops
    assert all(forbidden not in s for s in hops), hops
    # 单跳边查询（`-[r:Rel]{arrow}(`）同样由地图决定
    assert any(f"-[r:Rel]{expect}(" in s for s in sqls), sqls


def test_both_direction_is_directionless_in_cypher(monkeypatch, ws):
    """`BOTH` 的箭头是 `-`（无方向）⇒ 生成的 Cypher **不得**出现任何方向箭头。"""
    sqls = _cypher_for(monkeypatch, ws, DIRECTION_BOTH, GRAPH_MODE_NEIGHBOR)
    assert all("->" not in s and "<-" not in s for s in sqls), sqls


def test_paths_mode_splits_both_into_out_then_in(monkeypatch, ws):
    """`paths` 模式必须**方向敏感**：`BOTH` 拆成 `OUT` 再 `IN`（避免环路打转）。"""
    sqls = _cypher_for(monkeypatch, ws, DIRECTION_BOTH, GRAPH_MODE_PATHS)
    path_sqls = [s for s in sqls if "nodes(p)" in s]
    assert len(path_sqls) == 2, sqls
    assert "->" in path_sqls[0] and "<-" not in path_sqls[0], path_sqls
    assert "<-" in path_sqls[1] and "->" not in path_sqls[1], path_sqls

    only_out = _cypher_for(monkeypatch, ws, DIRECTION_OUT, GRAPH_MODE_PATHS)
    out_sqls = [s for s in only_out if "nodes(p)" in s]
    assert len(out_sqls) == 1 and "->" in out_sqls[0], only_out


# --------------------------------------------------------------------------- #
# ④ 防复发（**显式限定范围**）+ CLI 残留显式登记
# --------------------------------------------------------------------------- #

def test_scoped_producers_have_no_stray_vocab_literals():
    """本片改动范围内的三个文件不得再散落词表字面量。

    ⚠ 注意 `data["paths"]` 是**响应字段名**（合同声明），不是模式值 ⇒ 不纳入模式。
    """
    patterns = ('"FULLTEXT"', '"VECTOR"', '"HYBRID"', '"neighbor"', '"closure"',
                '== "paths"', '"OUT"', '"IN"', '"BOTH"')
    for path in (SERVICE_SRC, SERVER_SRC, GATES_SRC):
        text = path.read_text(encoding="utf-8")
        hits = [p for p in patterns if p in text]
        assert hits == [], f"{path.relative_to(REPO_ROOT)} 仍有词表字面量：{hits}"


def test_cli_residual_is_explicitly_registered():
    """**E-13 残留显式登记**：`cli/main.py` 含他人在途改动 ⇒ 本片不碰，其 3 处默认值仍是字面量。

    该文件清空后：应把这三处改为引用 `kert.domain.query_modes` 的常量，
    并把本用例改成"不得含字面量"（届时本断言会因字面量消失而红 ⇒ 强制更新登记）。
    """
    text = CLI_SRC.read_text(encoding="utf-8")
    residual = [p for p in ('"neighbor"', '"FULLTEXT"') if p in text]
    assert residual == ['"neighbor"', '"FULLTEXT"'], (
        f"CLI 残留登记已失效（实测 {residual}）⇒ 若该文件已清空，请改两处为命名源并更新本登记")
    assert text.count("typer.Option") > 0, "CLI 结构变化 ⇒ 请复核本登记"


# --------------------------------------------------------------------------- #
# ⑤ 同名异域边界（禁止合并）
# --------------------------------------------------------------------------- #

def test_two_mode_fields_and_cli_switch_are_distinct_domains():
    assert set(SEARCH_MODES) != set(GRAPH_MODES), "两个 mode 字段值域相同 ⇒ 请重新裁定归属"
    assert not (set(SEARCH_MODES) & set(GRAPH_MODES)), "两域取值不得共享"
    # `cli/main.py:178` 的 `--mode fast|full` 是**无关开关**（同名异域）
    assert not ({"fast", "full"} & (set(SEARCH_MODES) | set(GRAPH_MODES) | set(GRAPH_DIRECTIONS)))
