"""本体**物化**（D-31）：解析结果 → Parquet + Kùzu 图 + 血缘，落
``04_serve/<service_id>/version=<v>/``（与既有投影**同形**：parquet 族 + ``.md`` + 图子目录 + 血缘 JSON）。

链路（本模块只做本体这一跳）::

    内置本体资产（provenance 校验 / 漂移即拒绝）
      → rdflib/pyshacl 真解析（类/属性/层次/shapes）
      → Parquet + Kùzu 图 + ONTOLOGY.md
      → 血缘 ONTOLOGY_LINEAGE.json（含与计划同形的 ``ontology`` 子块）

纪律
----
- **校验先于产出**：资产漂移、与声明钉值不符、与同版本目录既有 ``PLAN_LINEAGE.json``
  的本体块不一致、或 **SHACL 实例校验未通过** ⇒ **抛具名错误且不写任何产物**；
  SHACL 结论必须是**可判定且为真**（``conforms is True``）——"声明了 SHACL 却无实例图"
  不算通过（``ONTOLOGY_INSTANCES_NOT_CONFORMING``，见 :func:`_assert_shacl_conforms`）；
- 产物落卷走**同一工作区**（``ws``），不写仓库；重复执行是**幂等覆盖**（图先删后建）。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from ..domain import hashing, timeutil
from ..domain.errors import ServiceNotReadyError
from ..domain.ontology_assets import (
    CODE_ASSET_DECLARATION_MISMATCH,
    CODE_INSTANCES_NOT_CONFORMING,
    ROLE_INSTANCES,
    ROLE_SHACL,
    OntologyAssetError,
    ensure_assets,
    load_assets,
)
from ..domain.ontology_parse import parse_ontology

DEFAULT_SERVICE = "product_knowledge"
GRAPH_SUBDIR = "ontology_graph"
SCHEMA_LINEAGE = "ontology_lineage/v1"
SCHEMA_GRAPH = "graph_projection/v1"
BUILDER_ID = "ontology_materializer"
BUILDER_VERSION = "1.0.0"

FILES = ("ontology_classes.parquet", "ontology_properties.parquet",
         "ontology_shapes.parquet", "ONTOLOGY.md", "ONTOLOGY_LINEAGE.json")

_CLASSES_COLUMNS = (("id", pa.string()), ("label", pa.string()), ("parents", pa.string()))
_PROPS_COLUMNS = (("id", pa.string()), ("kind", pa.string()), ("label", pa.string()),
                  ("domain", pa.string()), ("range_", pa.string()))
_SHAPES_COLUMNS = (("shape_id", pa.string()), ("target_class", pa.string()),
                   ("path", pa.string()), ("datatype", pa.string()),
                   ("min_count", pa.int64()))


def materialize_ontology(workspace: Path | str,
                         *, service_id: str = DEFAULT_SERVICE,
                         version: str | None = None,
                         assets_source: Path | str | None = None) -> dict:
    """把内置本体物化进 ``04_serve/<service_id>/version=<version>/``。

    :param workspace: 工作区根。
    :param service_id: 目标服务（缺省 ``product_knowledge``，与既有投影同层）。
    :param version: 目标版本目录；``None`` ⇒ 取 ``CURRENT.md`` 的活动版本（无活动投影则拒绝）。
    :param assets_source: 受控源目录（如 ``examples/.../90_control/ontology``）；
        给出时先用 :func:`~kert.domain.ontology_assets.ensure_assets` 引入工作区。
    :raises OntologyAssetError: 资产缺失/漂移/与声明不一致/与既有计划血缘不一致/
        **SHACL 实例校验未通过（或不可判）**（**具名**）。
    :raises ServiceNotReadyError: 无活动版本且未显式给 ``version``。
    :returns: ``{service_id, version, counts, files, graph, lineage_path}``。
    """
    ws = Path(workspace)
    load = ensure_assets(ws, source=assets_source) if assets_source is not None else load_assets(ws)
    if not load.allowed or load.assets is None:
        raise OntologyAssetError(load.code, load.reason)
    assets = load.assets

    # 与**声明钉值**对齐（声明说 CTR-SEM-002@sha256:… 指的就是这件 OWL）
    res = _declared_resolution(ws)
    if res is not None and res.allowed and res.reference is not None:
        if res.reference.content_sha256 != assets.owl.content_sha256:
            raise OntologyAssetError(
                CODE_ASSET_DECLARATION_MISMATCH,
                f"内置 OWL 与声明钉值不符: 内置={assets.owl.content_sha256}，"
                f"声明={res.reference.content_sha256}（{assets.owl.authority_source}）")

    version = version or _active_version(ws, service_id)
    if not version:
        raise ServiceNotReadyError(
            f"服务 {service_id} 无活动投影（``CURRENT.md``）且未显式指定 version")

    vdir = ws / "04_serve" / service_id / f"version={version}"
    lineage_path = vdir / "ONTOLOGY_LINEAGE.json"
    _assert_plan_lineage_consistent(res, vdir)   # 校验先于产出

    summary = parse_ontology(
        assets.owl.path,
        shacl_path=(assets.get(ROLE_SHACL).path if assets.get(ROLE_SHACL) else None),
        instances_path=(assets.get(ROLE_INSTANCES).path if assets.get(ROLE_INSTANCES) else None),
    )
    _assert_shacl_conforms(summary, assets)     # 校验先于产出：违规 ⇒ 具名拒绝，不写任何产物

    vdir.mkdir(parents=True, exist_ok=True)
    rows_classes = [{"id": c.iri, "label": c.label, "parents": "|".join(c.parents)}
                    for c in summary.classes]
    rows_props = [{"id": p.iri, "kind": p.kind, "label": p.label, "domain": p.domain,
                   "range_": p.range_}
                  for p in (*summary.object_properties, *summary.datatype_properties)]
    rows_shapes = [{"shape_id": s.shape_id, "target_class": s.target_class, "path": s.path,
                    "datatype": s.datatype, "min_count": s.min_count} for s in summary.shapes]
    _write_parquet(vdir / "ontology_classes.parquet", rows_classes, _CLASSES_COLUMNS)
    _write_parquet(vdir / "ontology_properties.parquet", rows_props, _PROPS_COLUMNS)
    _write_parquet(vdir / "ontology_shapes.parquet", rows_shapes, _SHAPES_COLUMNS)

    graph = _build_graph(vdir, rows_classes, rows_props, rows_shapes)
    instances_asset = assets.get(ROLE_INSTANCES)
    lineage = {
        "schema": SCHEMA_LINEAGE,
        "builtAt": timeutil.ts_utc(),
        "serviceId": service_id,
        "version": version,
        "builderId": BUILDER_ID,
        "builderVersion": BUILDER_VERSION,
        "counts": summary.counts(),
        "assets": [{"file": a.file, "authoritySource": a.authority_source, "role": a.role,
                    "bytes": a.bytes, "contentSha256": a.content_sha256} for a in assets.assets],
        "graph": graph,
        # SHACL 判据的**结论留痕**：产出这件事本身就带上了"哪份 shapes 对哪份实例图判过、判成什么"
        "shaclValidation": {
            "conforms": summary.instances_conforms,
            "violations": summary.instance_violations,
            "shapes": summary.shape_count,
            "instancesFile": instances_asset.file if instances_asset is not None else None,
        },
        "ontology": _ontology_block(res, assets),
    }
    (vdir / "ONTOLOGY.md").write_text(
        _render_md(service_id, version, summary, assets, graph), encoding="utf-8")
    lineage_path.write_text(json.dumps(lineage, ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8")
    return {"service_id": service_id, "version": version, "counts": summary.counts(),
            "files": [f"04_serve/{service_id}/version={version}/{n}" for n in FILES],
            "graph": graph, "lineage_path": str(lineage_path.relative_to(ws))}


# --------------------------------------------------------------------------- #
# 内部
# --------------------------------------------------------------------------- #

def _assert_shacl_conforms(summary, assets) -> None:  # noqa: ANN001
    """SHACL 判据必须**可判定且为真**；否则**具名拒绝**（``ONTOLOGY_INSTANCES_NOT_CONFORMING``）。

    两档（同一具名码，拒绝语义一致）：

    1. ``conforms is False`` ⇒ 实例图**违反** shapes：给出违规条数（来自真实 pyshacl 结果）；
    2. ``conforms is None``（声明了 SHACL 却没有实例图可判）⇒ **不**当作"无事发生"——
       否则"删掉实例图"就等于把校验绕过去了（fail-open）。

    未声明 SHACL（``shacl_path is None``）时保持既有语义：无约束可判 ⇒ 放行。
    """
    if assets.get(ROLE_SHACL) is None:
        return
    if summary.instances_conforms is None:
        raise OntologyAssetError(
            CODE_INSTANCES_NOT_CONFORMING,
            f"声明了 SHACL（{assets.get(ROLE_SHACL).file}）但没有实例图可判（缺 "
            f"{ROLE_INSTANCES} 资产）⇒ 拒绝物化：**未校验**不得充当通过（fail-closed）")
    if not summary.instances_conforms:
        raise OntologyAssetError(
            CODE_INSTANCES_NOT_CONFORMING,
            f"SHACL 实例校验未通过 ⇒ 拒绝物化：conforms=false，违规 "
            f"{summary.instance_violations} 条（shapes={summary.shape_count}，"
            f"实例图={assets.get(ROLE_INSTANCES).file}）")


def _declared_resolution(ws: Path):  # noqa: ANN202
    """读工作区的本体引用声明解析结果（未供给 ⇒ ``None``，不视为错误）。"""
    from ..domain.ontology_reference import resolve_reference

    p = ws / "90_control" / "schema" / "ontology_reference.json"
    if not p.is_file():
        return None
    return resolve_reference(ws)


def _ontology_block(res, assets) -> dict:  # noqa: ANN001
    """血缘的 ``ontology`` 子块（**与既有计划血缘同形**：5 键）。"""
    from ..domain.ontology_reference import lineage_ontology_fields

    fields = lineage_ontology_fields(res) if res is not None else None
    if fields is not None:
        return fields
    owl = assets.owl
    return {"contractId": assets.contract_id, "authorityRepo": assets.authority_repo,
            "authoritySource": owl.authority_source, "contentSha256": owl.content_sha256,
            "version": assets.version}


def _assert_plan_lineage_consistent(res, vdir: Path) -> None:  # noqa: ANN001
    """同版本目录已有 ``PLAN_LINEAGE.json`` 时，其本体块必须与本工作区声明一致。"""
    plan_lineage = vdir / "PLAN_LINEAGE.json"
    if not plan_lineage.is_file() or res is None or not res.allowed:
        return
    from ..domain.ontology_reference import check_lineage_ontology

    fm = json.loads(plan_lineage.read_text(encoding="utf-8"))
    chk = check_lineage_ontology(res, fm)
    if not chk.allowed:
        raise OntologyAssetError(chk.code,
                                 f"同版本目录的计划血缘本体块与本工作区声明不一致：{chk.reason}")


def _active_version(ws: Path, service_id: str) -> str | None:
    cur = ws / "04_serve" / service_id / "CURRENT.md"
    if not cur.is_file():
        return None
    m = re.search(r"^target_version:\s*\"?([^\n\" ]+)", cur.read_text(encoding="utf-8"), re.M)
    return m.group(1) if m else None


def _write_parquet(path: Path, rows: list[dict], columns) -> None:  # noqa: ANN001
    if rows:
        table = pa.Table.from_pylist(rows)
    else:
        table = pa.table({name: pa.array([], type=typ) for name, typ in columns})
    pq.write_table(table, path)


def _build_graph(vdir: Path, classes: list[dict], props: list[dict], shapes: list[dict]) -> dict:
    """建 Kùzu 图（``OntoNode`` / ``OntoEdge``）；返回计数与逻辑指纹。"""
    import kuzu

    graph_file = vdir / GRAPH_SUBDIR
    proj_file = vdir / f"{GRAPH_SUBDIR}.PROJECTION.json"
    for p in (graph_file, proj_file):
        if p.exists():
            p.unlink()

    raw_nodes: list[tuple[str, str, str]] = []
    for c in classes:
        raw_nodes.append((c["id"], "CLASS", c["label"]))
    for p in props:
        raw_nodes.append((p["id"], "PROPERTY", p["label"]))
    for s in shapes:
        raw_nodes.append((s["shape_id"], "SHAPE", s["target_class"]))
    # 图节点按 id 去重（SHACL 每 shape 有多行属性约束 ⇒ 同 id 多行；parquet 仍保留全部约束行）
    seen: dict[str, tuple[str, str, str]] = {}
    for nid, kind, label in raw_nodes:
        seen.setdefault(nid, (nid, kind, label))
    nodes = list(seen.values())

    ids = {n[0] for n in nodes}
    edges: list[tuple[str, str, str]] = []
    for c in classes:
        for parent in filter(None, c["parents"].split("|")):
            if parent in ids:
                edges.append((c["id"], "SUBCLASS_OF", parent))
    for p in props:
        for kind, target in (("DOMAIN", p["domain"]), ("RANGE", p["range_"])):
            if target and target in ids:
                edges.append((p["id"], kind, target))
    for s in shapes:
        if s["target_class"] and s["target_class"] in ids:
            edges.append((s["shape_id"], "TARGETS", s["target_class"]))
        if s["path"] and s["path"] in ids:
            edges.append((s["shape_id"], "SHAPE_PROPERTY", s["path"]))

    db = kuzu.Database(str(graph_file))
    con = kuzu.Connection(db)
    con.execute("CREATE NODE TABLE OntoNode(id STRING, kind STRING, label STRING, PRIMARY KEY(id))")
    con.execute("CREATE REL TABLE OntoEdge(FROM OntoNode TO OntoNode, kind STRING)")
    for nid, kind, label in nodes:
        con.execute("CREATE (:OntoNode {id:$i, kind:$k, label:$l})",
                    {"i": nid, "k": kind, "l": label})
    for src, kind, dst in sorted(set(edges)):
        con.execute("MATCH (a:OntoNode {id:$s}), (b:OntoNode {id:$d}) "
                    "CREATE (a)-[:OntoEdge {kind:$k}]->(b)",
                    {"s": src, "d": dst, "k": kind})
    node_count = con.execute("MATCH (n:OntoNode) RETURN count(n)").get_next()[0]
    edge_count = con.execute("MATCH ()-[e:OntoEdge]->() RETURN count(e)").get_next()[0]
    db.close()

    fp = hashing.sha256_hex(json.dumps({"nodes": sorted(nodes), "edges": sorted(edges)},
                                       ensure_ascii=False, sort_keys=True))
    graph = {"dir": GRAPH_SUBDIR, "node_count": node_count, "edge_count": edge_count,
             "fingerprint": fp}
    proj_file.write_text(json.dumps({"schema": SCHEMA_GRAPH, "builder_id": BUILDER_ID,
                                     "builder_version": BUILDER_VERSION,
                                     "built_at": timeutil.ts_utc(), **graph},
                                    ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return graph


def _render_md(service_id: str, version: str, summary, assets, graph: dict) -> str:  # noqa: ANN001
    c = summary.counts()
    lines = [
        "# 本体物化（ONTOLOGY）",
        "",
        f"- 服务 / 版本：`{service_id}` / `version={version}`",
        f"- 合同 / 版本：`{assets.contract_id}` / `{assets.version}`",
        f"- 图：`{graph['dir']}/`（节点 {graph['node_count']}，边 {graph['edge_count']}，"
        f"指纹 `{graph['fingerprint'][:16]}…`）",
        "",
        "## 可运行统计（解析自真实 OWL / SHACL）",
        "",
        f"- 类：**{c['classes']}**；对象属性：**{c['objectProperties']}**；"
        f"数据属性：**{c['datatypeProperties']}**",
        f"- SHACL：NodeShape **{c['shapes']}**，属性约束 **{c['shapeProperties']}**；"
        f"实例校验 conforms=**{summary.instances_conforms}**，违规 **{c['instanceViolations']}**",
        f"- 类层次边：**{c['subclassEdges']}**；三元组：**{c['triples']}**",
        "",
        "## 推理（**已评估，未启用**）",
        "",
        "- 实测 `owlrl` 闭包与 pyshacl `inference` 四档（None / rdfs / owlrl / both）：",
        "  **类层次闭包 +0、实例级类型断言 +0、SHACL 结果完全相同**；增量全为自反/公理噪声",
        "  （自反 `sameAs` 242、自反 `subClassOf` 34）⇒ 判定“**引入无收益**”，**不写入产物**。",
        "  判据与数值钉在 `tests/unit/test_ontology_reasoning_is_neutral.py`"
        "（将来若出现有意义差异，该测试变红 ⇒ 重新评估）。",
        "",
        "## 资产与 provenance",
        "",
        "| 角色 | 文件 | 来源（仓内路径） | sha256(前16) |",
        "|---|---|---|---|",
    ]
    for a in assets.assets:
        lines.append(f"| {a.role} | `{a.file}` | `{a.authority_source}` | `{a.content_sha256[:16]}…` |")
    lines += [
        "",
        f"来源仓：`{assets.authority_repo}`；provenance：`{assets.provenance_path.name}`"
        "（漂移 ⇒ 具名拒绝，见 `kert.domain.ontology_assets`）",
        "",
        "## 查询（Kùzu）",
        "",
        "```python",
        "import kuzu",
        f"db = kuzu.Database('{graph['dir']}'); con = kuzu.Connection(db)",
        "con.execute('MATCH (n:OntoNode) RETURN n.kind, count(n)')",
        "con.execute('MATCH (a:OntoNode)-[e:OntoEdge]->(b:OntoNode) "
        "RETURN e.kind, count(e)')",
        "```",
    ]
    return "\n".join(lines) + "\n"
