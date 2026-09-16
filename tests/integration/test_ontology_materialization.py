"""D-31 本体侧集成测试：**解析 → 物化（Parquet + Kùzu）→ 图可查 → 血缘**，以及**篡改即拒绝且不留产物**。

正例：内置资产（provenance 校验）→ 真解析 → 物化到 `04_serve/<svc>/version=<v>/` → Kùzu 图查询命中
      → 血缘 `ontology` 子块与**计划声明**一致（喂给既有 `check_lineage_ontology` 仍放行）；
反例 1：副本被篡改 ⇒ 具名 `ONTOLOGY_ASSET_DRIFT` 且**不产出任何产物**；
反例 2：内置 OWL 与控制面**声明钉值**不符 ⇒ 具名 `ONTOLOGY_ASSET_DECLARATION_MISMATCH`；
反例 3（④）：实例图**违反** SHACL ⇒ 具名 `ONTOLOGY_INSTANCES_NOT_CONFORMING` 且**不产出**；
反例 4（④）：声明了 SHACL 却**没有实例图可判**（"未校验"）⇒ 同具名拒绝，不得充当通过。
"""
from __future__ import annotations

import hashlib
import json
import re
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
    CODE_INSTANCES_NOT_CONFORMING,
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


def test_fingerprint_is_target_invariant_and_content_sensitive(ws_ready, tmp_path):
    """确定性判据的**双向**钉住（防被读成"任何条件下恒定"）：

    ① 自变量 = 目标工作区/目录，**本体资产不变** ⇒ 因变量 `fingerprint` **不变**；
    ② 自变量 = **本体内容变（且声明同步改钉，即合法换版）** ⇒ 因变量 `fingerprint` **必变**。
    """
    import hashlib
    import shutil

    ws = ws_ready
    base = materialize_ontology(ws, service_id=SERVICE_ID, version="det-1", assets_source=ASSETS_SRC)

    # ① 换工作区（新目录），资产不变 ⇒ fingerprint 不变
    other = tmp_path / "ws-other"
    ws_mod.init_workspace(other)
    provision_control_plane(other, SRC)
    same = materialize_ontology(other, service_id=SERVICE_ID, version="det-1",
                                assets_source=ASSETS_SRC)
    assert same["graph"]["fingerprint"] == base["graph"]["fingerprint"], "目标目录不应影响指纹"

    # ② 资产**内容**变（加一个类）+ 同步 provenance + 同步控制面声明钉值（合法换版）⇒ fingerprint 必变
    alt = tmp_path / "alt-onto"
    shutil.copytree(ASSETS_SRC, alt)
    owl = alt / "gits-core.owl.ttl"
    owl.write_text(owl.read_text(encoding="utf-8") + "\ngits:ExtraClass a owl:Class .\n",
                   encoding="utf-8")
    prov = json.loads((alt / "PROVENANCE.json").read_text(encoding="utf-8"))
    for entry in prov["assets"]:
        if entry["file"] == "gits-core.owl.ttl":
            entry["contentSha256"] = hashlib.sha256(owl.read_bytes()).hexdigest()
            entry["bytes"] = owl.stat().st_size
    (alt / "PROVENANCE.json").write_text(json.dumps(prov, ensure_ascii=False, indent=2) + "\n",
                                         encoding="utf-8")

    changed_ws = tmp_path / "ws-changed"
    ws_mod.init_workspace(changed_ws)
    provision_control_plane(changed_ws, SRC)
    decl = changed_ws / "90_control" / "schema" / "ontology_reference.json"
    doc = json.loads(decl.read_text(encoding="utf-8"))
    doc["contentSha256"] = prov["assets"][0]["contentSha256"]   # 合法换版：声明改钉到新版
    decl.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    _adopt_variant(alt, changed_ws)      # 先清工作区内置副本，否则 assets_source 会被静默忽略

    changed = materialize_ontology(changed_ws, service_id=SERVICE_ID, version="det-2",
                                   assets_source=alt)
    assert (assets_dir(changed_ws) / "gits-core.owl.ttl").read_bytes() == \
        (alt / "gits-core.owl.ttl").read_bytes(), "换版未真正生效（夹具空转）"
    assert changed["counts"]["classes"] == base["counts"]["classes"] + 1
    assert changed["graph"]["fingerprint"] != base["graph"]["fingerprint"], "内容变 ⇒ 指纹必变"


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


# --------------------------------------------------------------------------- #
# ④ SHACL 违规 ⇒ **拒绝物化**（不是统计）
# --------------------------------------------------------------------------- #

OWL_NS = "https://gientech.com/gits/kno/"
"""shapes / OWL 的命名空间（见 ``gits-core.shacl.ttl`` 的 ``@prefix gits:``）。"""

_SATISFYING = (f"\n@prefix k: <{OWL_NS}> .\n"
               'k:good_product a k:Product ; k:product_id "P1" .\n')
_VIOLATING = (f"\n@prefix k: <{OWL_NS}> .\n"
              'k:bad_action a k:Action ; k:action_id "x" .\n')


def _assets_variant(tmp_path: Path, name: str, *, instances_extra: str = "",
                    drop_instances: bool = False) -> Path:
    """内置资产的受控源变体（provenance 与内容**同步改**，故源侧自身合法）。"""
    import shutil

    root = tmp_path / name
    shutil.copytree(ASSETS_SRC, root)
    doc = json.loads((root / "PROVENANCE.json").read_text(encoding="utf-8"))
    if drop_instances:
        inst = next(a for a in doc["assets"] if a["role"] == "INSTANCES")
        (root / inst["file"]).unlink()
        doc["assets"] = [a for a in doc["assets"] if a["role"] != "INSTANCES"]
        (root / "PROVENANCE.json").write_text(
            json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return root
    if instances_extra:
        inst_path = next(root / a["file"] for a in doc["assets"] if a["role"] == "INSTANCES")
        inst_path.write_text(inst_path.read_text(encoding="utf-8") + instances_extra,
                             encoding="utf-8")
        for entry in doc["assets"]:
            p = root / entry["file"]
            entry["bytes"] = p.stat().st_size
            entry["contentSha256"] = hashlib.sha256(p.read_bytes()).hexdigest()
        (root / "PROVENANCE.json").write_text(
            json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return root


def _adopt_variant(src_variant: Path, ws: Path) -> None:
    """把工作区已有的本体副本清掉，让 ``materialize_ontology(assets_source=…)`` **真的**采用变体。

    ``ensure_assets`` 只在"工作区尚无 ``PROVENANCE.json``"时才引入 ⇒ 若工作区已有一份
    （例如 M7-⑤ 之后 ``kert provision`` 已供给内置本体），``assets_source`` 会被**静默忽略**，
    本文件的三个变体夹具就会变成空转。故先清后引入，并（正例里）断言引入的确实是变体。
    """
    import shutil

    shutil.rmtree(assets_dir(ws), ignore_errors=True)


def _targeted_types(assets_root: Path) -> set[str]:
    """实例图里**被某条 shape 的 targetClass 命中**的类型集合。

    空集 ⇒ 该校验**必然空转**（没有任何实例受约束，``conforms`` 恒真）——
    夹具与被测路径都必须先排除这一点，否则"拒绝"分支永远不会被走到。
    """
    from rdflib import Graph
    from rdflib.namespace import RDF, SH

    doc = json.loads((assets_root / "PROVENANCE.json").read_text(encoding="utf-8"))
    files = {a["role"]: a["file"] for a in doc["assets"]}
    g = Graph()
    g.parse(str(assets_root / files["INSTANCES"]), format="turtle")
    sg = Graph()
    sg.parse(str(assets_root / files["SHACL"]), format="turtle")
    targets = {str(t) for _, _, t in sg.triples((None, SH.targetClass, None))}
    typed = {str(o) for _, _, o in g.triples((None, RDF.type, None))}
    return targets & typed


def test_positive_shacl_validation_is_non_vacuous_and_recorded(ws_ready, tmp_path):
    """正例：实例**真被 shapes 命中**（非空转）且相容 ⇒ 正常产出，结论写进血缘。"""
    ws = ws_ready
    alt = _assets_variant(tmp_path, "alt-shacl-ok", instances_extra=_SATISFYING)
    assert _targeted_types(alt), "夹具失效：实例未被任何 shape 命中 ⇒ 本用例会空转"
    _adopt_variant(alt, ws)

    out = materialize_ontology(ws, service_id=SERVICE_ID, version="shacl-ok", assets_source=alt)
    # 防空转：物化**真的**用了这个变体（否则下面的断言可能是在测内置资产）
    assert (assets_dir(ws) / "products.ttl").read_bytes() == (alt / "products.ttl").read_bytes()
    vdir = ws / "04_serve" / SERVICE_ID / "version=shacl-ok"
    fm = json.loads((vdir / "ONTOLOGY_LINEAGE.json").read_text(encoding="utf-8"))
    # D-35：`vacuous` 必须如实——本例的实例**真的**命中 targetClass ⇒ 校验有信息量
    assert fm["shaclValidation"]["conforms"] is True
    assert fm["shaclValidation"]["violations"] == 0
    assert fm["shaclValidation"]["shapes"] == out["counts"]["shapes"]
    assert fm["shaclValidation"]["instancesFile"] == "products.ttl"
    assert fm["shaclValidation"]["vacuous"] is False, fm["shaclValidation"]
    assert fm["shaclValidation"]["targetedInstances"] >= 1
    assert fm["shaclValidation"]["matchedShapes"] >= 1
    assert fm["counts"]["instanceViolations"] == 0


def test_negative_shacl_violation_is_refused_and_nothing_written(ws_ready, tmp_path):
    """反例 3：实例**违反** shapes ⇒ 具名 `ONTOLOGY_INSTANCES_NOT_CONFORMING`，**不产出**。"""
    ws = ws_ready
    alt = _assets_variant(tmp_path, "alt-shacl-bad", instances_extra=_VIOLATING)
    assert _targeted_types(alt), "夹具失效：违规实例未被 shape 命中 ⇒ 拒绝路径不会被触发"
    _adopt_variant(alt, ws)

    vdir = ws / "04_serve" / SERVICE_ID / "version=shacl-bad"
    with pytest.raises(OntologyAssetError) as ei:
        materialize_ontology(ws, service_id=SERVICE_ID, version="shacl-bad", assets_source=alt)
    assert ei.value.code == CODE_INSTANCES_NOT_CONFORMING
    assert "conforms=false" in ei.value.message and "products.ttl" in ei.value.message
    n = re.search(r"违规 (\d+) 条", ei.value.message)
    assert n and int(n.group(1)) >= 1, f"违规数未如实写出: {ei.value.message}"
    assert not vdir.exists(), "拒绝时不得留下产物（fail-closed）"


def test_negative_shacl_declared_without_instances_is_refused(ws_ready, tmp_path):
    """反例 4：声明了 SHACL 却**无实例图可判**（"未校验"）⇒ 同具名拒绝，不得充当通过。"""
    ws = ws_ready
    alt = _assets_variant(tmp_path, "alt-shacl-noinst", drop_instances=True)
    _adopt_variant(alt, ws)
    vdir = ws / "04_serve" / SERVICE_ID / "version=shacl-none"

    with pytest.raises(OntologyAssetError) as ei:
        materialize_ontology(ws, service_id=SERVICE_ID, version="shacl-none", assets_source=alt)
    assert ei.value.code == CODE_INSTANCES_NOT_CONFORMING
    assert "未校验" in ei.value.message
    assert not vdir.exists(), "拒绝时不得留下产物（fail-closed）"
