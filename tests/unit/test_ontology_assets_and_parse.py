"""D-31 本体侧单元测试：内置资产 provenance / **漂移具名拒绝** / OWL+SHACL **真解析统计**。

口径：内置资产 = `examples/bank-front-knowledge-maps/90_control/ontology/`（gits 只读副本，带 provenance）。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (str(REPO_ROOT / "src"), str(REPO_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from kert.domain.ontology_assets import (  # noqa: E402
    CODE_ASSET_DRIFT,
    CODE_PROVENANCE_INVALID,
    PROVENANCE_FILENAME,
    ROLE_INSTANCES,
    ROLE_SHACL,
    ensure_assets,
    load_assets_from_dir,
)
from kert.domain.ontology_parse import parse_ontology  # noqa: E402

ASSETS_SRC = REPO_ROOT / "examples" / "bank-front-knowledge-maps" / "90_control" / "ontology"
DECLARED = (REPO_ROOT / "examples" / "bank-front-knowledge-maps" / "90_control"
            / "schema" / "ontology_reference.json")


def _summary():
    load = load_assets_from_dir(ASSETS_SRC)
    assert load.allowed, load.reason
    a = load.assets
    return a, parse_ontology(a.owl.path, shacl_path=a.get(ROLE_SHACL).path,
                             instances_path=a.get(ROLE_INSTANCES).path)


def test_builtin_assets_match_the_declared_pin():
    """内置 OWL 副本的 sha256 必须与**控制面声明的钉值**逐字相同（同一件本体）。"""
    load = load_assets_from_dir(ASSETS_SRC)
    assert load.allowed, load.reason
    declared = json.loads(DECLARED.read_text(encoding="utf-8"))
    assert load.assets.owl.content_sha256 == declared["contentSha256"]
    assert load.assets.contract_id == declared["contractId"]
    assert load.assets.version == f"{declared['contractId']}@sha256:{declared['contentSha256'][:16]}"


def test_parse_gives_real_statistics_on_real_assets():
    """统计来自真实图遍历：类/对象属性/数据属性/类层次/shapes/实例校验全部可运行。"""
    _, s = _summary()
    c = s.counts()
    assert c["classes"] >= 30 and c["objectProperties"] >= 30 and c["datatypeProperties"] >= 1
    assert c["shapes"] >= 30 and c["shapeProperties"] > c["shapes"]     # shape 内含多条属性约束
    assert c["subclassEdges"] >= 5 and c["triples"] > 100
    assert s.instances_conforms is True and c["instanceViolations"] == 0
    assert all(cl.iri.startswith("http") for cl in s.classes)
    assert any(p.parents for p in s.classes), "类层次（rdfs:subClassOf）应被解析出来"


def test_drift_is_named_refusal(tmp_path):
    """漂移检测：副本被改（append 一字节）⇒ **具名拒绝** `ONTOLOGY_ASSET_DRIFT`，且指到文件名。"""
    dst = tmp_path / "90_control" / "ontology"
    load = ensure_assets(tmp_path, source=ASSETS_SRC)
    assert load.allowed, load.reason
    assert dst.is_dir()

    owl = dst / "gits-core.owl.ttl"
    owl.write_bytes(owl.read_bytes() + b"\n# tampered\n")

    again = load_assets_from_dir(dst)
    assert not again.allowed
    assert again.code == CODE_ASSET_DRIFT
    assert "gits-core.owl.ttl" in again.reason
    # ensure_assets 不得用源覆盖掉工作区副本（否则漂移被静默掩盖）
    assert not ensure_assets(tmp_path, source=ASSETS_SRC).allowed


def test_invalid_provenance_is_named_refusal(tmp_path):
    """provenance 结构非法（含未声明字段）⇒ 具名 `ONTOLOGY_ASSETS_PROVENANCE_INVALID`。"""
    dst = tmp_path / "90_control" / "ontology"
    dst.mkdir(parents=True)
    doc = json.loads((ASSETS_SRC / PROVENANCE_FILENAME).read_text(encoding="utf-8"))
    doc["unexpectedField"] = 1
    (dst / PROVENANCE_FILENAME).write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")

    load = load_assets_from_dir(dst)
    assert not load.allowed
    assert load.code == CODE_PROVENANCE_INVALID
    assert load.assets is None
