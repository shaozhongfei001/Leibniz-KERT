"""D-31 本体侧集成测试：**解析 → 物化（Parquet + Kùzu）→ 图可查 → 血缘**，以及**篡改即拒绝且不留产物**。

正例：内置资产（provenance 校验）→ 真解析 → 物化到 `04_serve/<svc>/version=<v>/` → Kùzu 图查询命中
      → 血缘 `ontology` 子块与**计划声明**一致（喂给既有 `check_lineage_ontology` 仍放行）；
反例 1：副本被篡改 ⇒ 具名 `ONTOLOGY_ASSET_DRIFT` 且**不产出任何产物**；
反例 2：内置 OWL 与控制面**声明钉值**不符 ⇒ 具名 `ONTOLOGY_ASSET_DECLARATION_MISMATCH`。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (str(REPO_ROOT / "src"), str(REPO_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from kert.application.ontology_materialize import (  # noqa: E402
    FILES,
    GRAPH_SUBDIR,
    materialize_ontology,
)
from kert.application.provision import provision_control_plane  # noqa: E402
from kert.domain import workspace as ws_mod  # noqa: E402
from kert.domain.activation_plan import ActivationPlanBuilder  # noqa: E402
from kert.domain.ontology_assets import (  # noqa: E402
    CODE_ASSET_DECLARATION_MISMATCH,
    CODE_ASSET_DRIFT,
    OntologyAssetError,
    assets_dir,
)
from kert.domain.ontology_reference import check_lineage_ontology  # noqa: E402

SRC = REPO_ROOT / "examples" / "bank-front-knowledge-maps"
ASSETS_SRC = SRC / "90_control" / "ontology"
SERVICE_ID = "product_knowledge"
VERSION = "ont-e2e"

pytest.importorskip("rdflib", reason="D-31 需要 rdflib（真解析 OWL）")
pytest.importorskip("pyshacl", reason="D-31 需要 pyshacl（SHACL 约束）")


@pytest.fixture
def ws_ready(tmp_path):
    """已供给控制面的工作区（本体引用声明 + 知识源声明 + 地图/策略）。"""
    ws_mod.init_workspace(tmp_path)
    provision_control_plane(tmp_path, SRC)
    return tmp_path


def test_positive_parse_materialize_and_query(ws_ready):
    """正例：解析 → 物化 → 图可查 → 血缘与计划声明一致。"""
    ws = ws_ready
    out = materialize_ontology(ws, service_id=SERVICE_ID, version=VERSION,
                               assets_source=ASSETS_SRC)

    # ① 产物与既有投影**同形**（version 目录内 parquet 族 + md + 图子目录 + 血缘 JSON）
    vdir = ws / "04_serve" / SERVICE_ID / f"version={VERSION}"
    for name in FILES:
        assert (vdir / name).is_file(), f"缺少 {name}"
    assert (vdir / GRAPH_SUBDIR).is_file(), "Kùzu 图（单文件存储）缺失"

    # ② Parquet 行数 == 解析统计（不是硬编码：同一 summary 同时驱动两者）
    import pyarrow.parquet as pq
    c = out["counts"]
    assert pq.read_table(vdir / "ontology_classes.parquet").num_rows == c["classes"]
    assert pq.read_table(vdir / "ontology_properties.parquet").num_rows == (
        c["objectProperties"] + c["datatypeProperties"])
    assert pq.read_table(vdir / "ontology_shapes.parquet").num_rows == c["shapeProperties"]
    assert c["classes"] >= 30 and c["shapes"] >= 30

    # ③ 图可查：节点/边数与物化返回值一致（kind 维度亦查）
    import kuzu
    db = kuzu.Database(str(vdir / GRAPH_SUBDIR))
    con = kuzu.Connection(db)
    assert con.execute("MATCH (n:OntoNode) RETURN count(n)").get_next()[0] == out["graph"]["node_count"]
    assert con.execute("MATCH ()-[e:OntoEdge]->() RETURN count(e)").get_next()[0] == out["graph"]["edge_count"]
    kinds = {}
    res = con.execute("MATCH (n:OntoNode) RETURN n.kind")
    while res.has_next():
        k = res.get_next()[0]
        kinds[k] = kinds.get(k, 0) + 1
    assert kinds.get("CLASS") == c["classes"] and kinds.get("PROPERTY") == (
        c["objectProperties"] + c["datatypeProperties"])

    # ④ 血缘：`ontology` 子块**与既有计划血缘同形**（5 键）且能被既有校验器放行
    fm = json.loads((vdir / "ONTOLOGY_LINEAGE.json").read_text(encoding="utf-8"))
    res_plan = ActivationPlanBuilder.load(ws).ontology_resolution()
    assert res_plan.allowed, res_plan.reason
    assert set(fm["ontology"]) == {"contractId", "authorityRepo", "authoritySource",
                                   "contentSha256", "version"}
    assert fm["ontology"]["contentSha256"] == res_plan.reference.content_sha256
    assert check_lineage_ontology(res_plan, fm).allowed
    assert fm["counts"]["classes"] == c["classes"]


def test_negative_tampered_asset_is_refused_and_nothing_written(ws_ready):
    """反例 1：副本被篡改 ⇒ 具名 DRIFT，且**不产出任何产物**（校验先于产出）。"""
    ws = ws_ready
    load = materialize_ontology(ws, service_id=SERVICE_ID, version="ok-1", assets_source=ASSETS_SRC)
    assert load["counts"]["classes"] >= 30

    owl = assets_dir(ws) / "gits-core.owl.ttl"
    owl.write_bytes(owl.read_bytes() + b"\n# tampered\n")

    with pytest.raises(OntologyAssetError) as ei:
        materialize_ontology(ws, service_id=SERVICE_ID, version="bad-1")
    assert ei.value.code == CODE_ASSET_DRIFT
    assert "gits-core.owl.ttl" in ei.value.message
    assert not (ws / "04_serve" / SERVICE_ID / "version=bad-1").exists(), "拒绝时不得留下产物"


def test_negative_asset_vs_declaration_mismatch_is_refused(ws_ready):
    """反例 2：内置 OWL 与控制面**声明钉值**不符 ⇒ 具名 `ONTOLOGY_ASSET_DECLARATION_MISMATCH`。"""
    ws = ws_ready
    decl = ws / "90_control" / "schema" / "ontology_reference.json"
    doc = json.loads(decl.read_text(encoding="utf-8"))
    doc["contentSha256"] = ("0" if doc["contentSha256"][0] != "0" else "1") + doc["contentSha256"][1:]
    decl.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(OntologyAssetError) as ei:
        materialize_ontology(ws, service_id=SERVICE_ID, version="bad-2", assets_source=ASSETS_SRC)
    assert ei.value.code == CODE_ASSET_DECLARATION_MISMATCH
    assert not (ws / "04_serve" / SERVICE_ID / "version=bad-2").exists()
