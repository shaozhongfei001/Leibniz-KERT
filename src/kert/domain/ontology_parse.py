"""本体**真解析**（D-31）：rdflib 解析 OWL（类 / 对象属性 / 数据属性 / 类层次）
+ 解析 SHACL shapes，并用 pyshacl 对实例图跑一次校验（给可运行统计）。

设计
----
- **不做推理就不装推理机**：本模块只用 ``rdflib``（图解析）+ ``pyshacl``（SHACL），
  **不**引入 ``owlready2``/推理机 —— 当前需求是"可解析、可统计、可物化"，不是"可推理"；
- 统计口径全部来自**真实图遍历**（不是正则数行、不是硬编码期望值）；
- 解析失败（TTL 语法错 / 文件缺失）⇒ 抛 :class:`~kert.domain.errors.SchemaValidationError`
  （带文件路径），由调用方按 fail-closed 处理。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from rdflib import Graph, RDF, RDFS, URIRef
from rdflib.namespace import OWL, SH

from .errors import SchemaValidationError

KIND_OBJECT = "OBJECT"
KIND_DATATYPE = "DATATYPE"


@dataclass(frozen=True)
class OntologyClass:
    """一个具名 ``owl:Class``。"""

    iri: str
    label: str
    parents: tuple[str, ...]


@dataclass(frozen=True)
class OntologyProperty:
    """一条具名属性（对象属性或数据属性）。"""

    iri: str
    kind: str
    label: str
    domain: str
    range_: str


@dataclass(frozen=True)
class OntologyShape:
    """一条 SHACL 属性约束（``sh:NodeShape`` 下的一个 ``sh:property``）。"""

    shape_id: str
    target_class: str
    path: str
    datatype: str
    min_count: int


@dataclass(frozen=True)
class OntologySummary:
    """解析结果（不可变；统计口径见各字段）。"""

    classes: tuple[OntologyClass, ...]
    object_properties: tuple[OntologyProperty, ...]
    datatype_properties: tuple[OntologyProperty, ...]
    shapes: tuple[OntologyShape, ...]
    triples: int
    subclass_edges: int
    instances_conforms: bool | None
    instance_violations: int

    @property
    def shape_count(self) -> int:
        """SHACL ``sh:NodeShape`` 个数（去重后）。"""
        return len({s.shape_id for s in self.shapes})

    def counts(self) -> dict[str, int]:
        """可运行统计（落盘 / 报数用）。"""
        return {
            "classes": len(self.classes),
            "objectProperties": len(self.object_properties),
            "datatypeProperties": len(self.datatype_properties),
            "shapes": self.shape_count,
            "shapeProperties": len(self.shapes),
            "subclassEdges": self.subclass_edges,
            "triples": self.triples,
            "instanceViolations": self.instance_violations,
        }


def parse_ontology(owl_path: Path | str, *, shacl_path: Path | str | None = None,
                   instances_path: Path | str | None = None) -> OntologySummary:
    """解析 OWL（必需）与 SHACL（可选），并对实例图（可选）跑一次 SHACL 校验。

    :raises SchemaValidationError: 文件缺失或 TTL 无法解析。
    """
    g = _parse(owl_path, "OWL")
    classes = _classes(g)
    obj, dat = _properties(g)
    subclass_edges = sum(len(c.parents) for c in classes)

    shapes: tuple[OntologyShape, ...] = ()
    conforms: bool | None = None
    violations = 0
    if shacl_path is not None:
        sg = _parse(shacl_path, "SHACL")
        shapes = _shapes(sg)
        if instances_path is not None:
            conforms, violations = _validate(shacl_path, instances_path, owl_path)
    return OntologySummary(classes=classes, object_properties=obj, datatype_properties=dat,
                           shapes=shapes, triples=len(g), subclass_edges=subclass_edges,
                           instances_conforms=conforms, instance_violations=violations)


# --------------------------------------------------------------------------- #
# 内部
# --------------------------------------------------------------------------- #

def _parse(path: Path | str, label: str) -> Graph:
    p = Path(path)
    if not p.is_file():
        raise SchemaValidationError(f"{label} 文件不存在: {p}")
    g = Graph()
    try:
        g.parse(str(p), format="turtle")
    except Exception as exc:  # rdflib 的解析异常族较杂，统一转契约错误
        raise SchemaValidationError(f"{label} 解析失败: {p}（{type(exc).__name__}: {exc}）") from exc
    return g


def _label(g: Graph, node: URIRef) -> str:
    for _, _, o in g.triples((node, RDFS.label, None)):
        return str(o)
    return ""


def _first_uri(g: Graph, s, p) -> str:  # noqa: ANN001
    for _, _, o in g.triples((s, p, None)):
        if isinstance(o, URIRef):
            return str(o)
    return ""


def _classes(g: Graph) -> tuple[OntologyClass, ...]:
    out: list[OntologyClass] = []
    for s in g.subjects(RDF.type, OWL.Class):
        if not isinstance(s, URIRef):
            continue  # 匿名类（restriction / union）不计入具名类统计
        parents = tuple(sorted(str(o) for o in g.objects(s, RDFS.subClassOf) if isinstance(o, URIRef)))
        out.append(OntologyClass(iri=str(s), label=_label(g, s), parents=parents))
    return tuple(sorted(out, key=lambda c: c.iri))


def _properties(g: Graph) -> tuple[tuple[OntologyProperty, ...], tuple[OntologyProperty, ...]]:
    def collect(owl_type, kind: str) -> tuple[OntologyProperty, ...]:
        items: list[OntologyProperty] = []
        for s in g.subjects(RDF.type, owl_type):
            if not isinstance(s, URIRef):
                continue
            items.append(OntologyProperty(iri=str(s), kind=kind, label=_label(g, s),
                                          domain=_first_uri(g, s, RDFS.domain),
                                          range_=_first_uri(g, s, RDFS.range)))
        return tuple(sorted(items, key=lambda p: p.iri))

    return collect(OWL.ObjectProperty, KIND_OBJECT), collect(OWL.DatatypeProperty, KIND_DATATYPE)


def _shapes(g: Graph) -> tuple[OntologyShape, ...]:
    out: list[OntologyShape] = []
    for shape in g.subjects(RDF.type, SH.NodeShape):
        target = _first_uri(g, shape, SH.targetClass)
        props = list(g.objects(shape, SH.property))
        if not props:
            out.append(OntologyShape(shape_id=str(shape), target_class=target,
                                     path="", datatype="", min_count=0))
            continue
        for p in props:
            min_count = 0
            for _, _, o in g.triples((p, SH.minCount, None)):
                try:
                    min_count = int(str(o))
                except ValueError:
                    min_count = 0
            out.append(OntologyShape(shape_id=str(shape), target_class=target,
                                     path=_first_uri(g, p, SH.path),
                                     datatype=_first_uri(g, p, SH.datatype),
                                     min_count=min_count))
    return tuple(sorted(out, key=lambda s: (s.shape_id, s.path)))


def _validate(shacl_path: Path | str, data_path: Path | str, ont_path: Path | str) -> tuple[bool, int]:
    """pyshacl 校验实例图；返回 ``(conforms, 违规条数)``。"""
    from pyshacl import validate

    data = _parse(data_path, "INSTANCES")
    shacl = _parse(shacl_path, "SHACL")
    ont = _parse(ont_path, "OWL")
    conforms, results_graph, _ = validate(data, shacl_graph=shacl, ont_graph=ont,
                                         inference="rdfs", allow_warnings=True)
    violations = len(list(results_graph.subjects(RDF.type, SH.ValidationResult)))
    return bool(conforms), violations
