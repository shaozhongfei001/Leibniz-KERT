"""⑤ 本体**供给面**：受控源 ``90_control/ontology/`` → 工作区，逐份 sha256 留痕（写侧与读侧同源）。

覆盖：正例（逐份清单 + 摘要与 provenance 一致）×1；反例（漂移 / 缺资产文件 / provenance 非法）
×3；"不供给"档（源无 ``PROVENANCE.json``）×1；防空转（清单下限 + rel 前缀 + 目标目录 == 读侧目录）×1。

反例都断言**具名**码出现在消息里（``ONTOLOGY_ASSET_DRIFT`` / ``ONTOLOGY_ASSETS_ABSENT`` /
``ONTOLOGY_ASSETS_PROVENANCE_INVALID``），而不是"随便报个错"。
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (str(REPO_ROOT / "src"), str(REPO_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from kert.domain import hashing  # noqa: E402
from kert.domain.errors import SchemaValidationError  # noqa: E402
from kert.domain.ontology_assets import (  # noqa: E402
    CODE_ASSET_DRIFT,
    CODE_ASSETS_ABSENT,
    CODE_PROVENANCE_INVALID,
    PROVENANCE_FILENAME,
    assets_dir,
)  # noqa: E402
from kert.domain.ontology_provision import (  # noqa: E402
    DIRNAME_REL,
    provision_pairs,
    require_source_assets,
    source_has_assets,
)

SRC = REPO_ROOT / "examples" / "bank-front-knowledge-maps"
ASSETS_SRC = SRC / "90_control" / "ontology"
WS = Path("/nonexistent/ws-for-unit")


def _provenance(root: Path) -> dict:
    return json.loads((root / PROVENANCE_FILENAME).read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- #
# 正例
# --------------------------------------------------------------------------- #

def test_pairs_cover_every_source_file_with_matching_sha256():
    """正例：清单**逐份**覆盖受控源目录，且每份摘要与 provenance 记录一致（留痕可用）。"""
    pairs = provision_pairs(WS, SRC)
    recorded = {a["file"]: a for a in _provenance(ASSETS_SRC)["assets"]}
    roles = {a["role"] for a in recorded.values()}

    assert roles == {"OWL", "SHACL", "INSTANCES", "R2RML"}, f"夹具失效：角色不全 {roles}"
    assert len(pairs) >= 5, f"防空转：清单 {len(pairs)} 份少于下限 5"
    assert {p.name for _, p, _ in pairs} == {p.name for p in ASSETS_SRC.iterdir() if p.is_file()}
    assert PROVENANCE_FILENAME in {p.name for _, p, _ in pairs}, "provenance 必须随资产一起供给"

    for rel, s_path, d_path in pairs:
        assert rel == f"{DIRNAME_REL}/{s_path.name}", rel
        assert d_path == assets_dir(WS) / s_path.name, "目标路径必须来自读侧同一函数（assets_dir）"
        if s_path.name in recorded:
            assert hashing.sha256_file(s_path) == recorded[s_path.name]["contentSha256"], s_path.name


# --------------------------------------------------------------------------- #
# 反例（具名拒绝，fail-closed）
# --------------------------------------------------------------------------- #

@pytest.fixture
def tampered(tmp_path):
    """受控源副本（provenance 与内容**初始一致**），供各反例按需破坏。"""
    root = tmp_path / "src"
    shutil.copytree(SRC, root)
    return root


def test_drifted_asset_is_named_refusal(tampered):
    """反例 1：副本内容被改（与 provenance 记录不符）⇒ 具名 ``ONTOLOGY_ASSET_DRIFT``。"""
    owl = tampered / "90_control" / "ontology" / "gits-core.owl.ttl"
    owl.write_bytes(owl.read_bytes() + b"\n# tampered\n")

    with pytest.raises(SchemaValidationError) as ei:
        require_source_assets(tampered)
    assert CODE_ASSET_DRIFT in str(ei.value)
    assert "gits-core.owl.ttl" in str(ei.value)
    with pytest.raises(SchemaValidationError):
        provision_pairs(WS, tampered)          # 清单构建阶段就必须拒绝（先于任何写入）


def test_missing_asset_file_is_named_refusal(tampered):
    """反例 2：**少供给一份**（provenance 声明了但文件不在）⇒ 具名 ``ONTOLOGY_ASSETS_ABSENT``。"""
    (tampered / "90_control" / "ontology" / "products.ttl").unlink()

    with pytest.raises(SchemaValidationError) as ei:
        provision_pairs(WS, tampered)
    assert CODE_ASSETS_ABSENT in str(ei.value)
    assert "products.ttl" in str(ei.value)


def test_invalid_provenance_is_named_refusal(tampered):
    """反例 3：provenance 结构非法（多一个未声明字段）⇒ 具名 ``…_PROVENANCE_INVALID``。"""
    prov = tampered / "90_control" / "ontology" / PROVENANCE_FILENAME
    doc = json.loads(prov.read_text(encoding="utf-8"))
    doc["unexpectedField"] = 1
    prov.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(SchemaValidationError) as ei:
        require_source_assets(tampered)
    assert CODE_PROVENANCE_INVALID in str(ei.value)


# --------------------------------------------------------------------------- #
# "缺失 ⇒ 不供给"档（与供给纪律 7/8 同口径）
# --------------------------------------------------------------------------- #

def test_source_without_provenance_is_not_supplied(tmp_path):
    """源未声明资产（无 ``PROVENANCE.json``）⇒ 空清单且**不报错**（缺它不应让部署起不来）。"""
    bare = tmp_path / "bare-src"
    bare.mkdir()
    assert not source_has_assets(bare)
    assert provision_pairs(WS, bare) == []
    require_source_assets(bare)          # 不抛


def test_absent_ontology_dir_is_not_supplied(tmp_path):
    """连 ``90_control/ontology/`` 目录都没有 ⇒ 同样是不供给（不是错误）。"""
    src = tmp_path / "src-no-onto"
    (src / "90_control" / "catalog").mkdir(parents=True)
    assert not source_has_assets(src)
    assert provision_pairs(WS, src) == []


def test_source_declaring_asset_and_workspace_are_not_confused(tmp_path):
    """防空转：清单的**目标**必须落在目标工作区、**源**必须落在受控源（两侧不得混用）。"""
    src = tmp_path / "src"
    shutil.copytree(SRC, src)
    ws = tmp_path / "ws"
    ws.mkdir()

    pairs = provision_pairs(ws, src)
    assert pairs, "夹具失效：清单为空"
    for _rel, s_path, d_path in pairs:
        assert s_path.is_relative_to(src), s_path
        assert d_path.is_relative_to(ws), d_path
        assert hashlib.sha256(s_path.read_bytes()).hexdigest() == hashing.sha256_file(s_path)
