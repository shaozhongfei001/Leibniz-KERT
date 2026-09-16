"""D-31 推理评估（**有界**）：实测差异 = 0 / 无业务意义 ⇒ 判定"**引入无收益**"，**不入产物**。

判据（TL）：① 差异**非空且有意义** ⇒ 引入（lock 钉版本 + 测试钉住差异）；
② 差异为 **0 或无业务意义** ⇒ 如实报数字、**不装**。

本文件把 ② 的**数值**钉住：若将来本体/实例变化使推理产生**有意义的**差异，
本文件会**变红** ⇒ 强制重新评估"是否引入推理"（并同步证据与 lock）。
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (str(REPO_ROOT / "src"), str(REPO_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from rdflib import Graph, RDF, RDFS  # noqa: E402
from rdflib.namespace import SH  # noqa: E402

# owlrl 由 pyshacl 传递引入（lock 已钉 owlrl==7.6.2）；此处**直接**调用以实测差异
from owlrl import DeductiveClosure, OWLRL_Semantics  # noqa: E402
from pyshacl import validate  # noqa: E402

ASSETS = REPO_ROOT / "examples" / "bank-front-knowledge-maps" / "90_control" / "ontology"
OWL = ASSETS / "gits-core.owl.ttl"
SHACL = ASSETS / "gits-core.shacl.ttl"
INSTANCES = ASSETS / "products.ttl"
LOCAL = "https://gientech.com/gits/kno/"


def _closure(graph: Graph) -> set:
    """对图施加 OWL-RL 闭包（**关掉公理三元组**，避免把噪声当收益）。"""
    DeductiveClosure(OWLRL_Semantics, axiomatic_triples=False,
                     datatype_axioms=False).expand(graph)
    return set(graph)


def _base(path: Path) -> tuple[Graph, set]:
    g = Graph()
    g.parse(str(path))
    return g, set(g)


def test_no_instance_level_type_assertions_are_inferred():
    """实例级类型断言增量为 **0**（13 个实例，无一条被推断出来）⇒ 对业务无增益。"""
    owl = Graph()
    owl.parse(str(OWL))
    g = Graph()
    g.parse(str(OWL))
    g.parse(str(INSTANCES))
    before = set(g)
    instances = {s for s in g.subjects()} - set(owl.subjects()) - set(owl.objects())
    before_types = {(s, o) for s, p, o in before if p == RDF.type and s in instances}

    _closure(g)
    after_types = {(s, o) for s, p, o in set(g) if p == RDF.type and s in instances}

    assert len(instances) >= 10
    assert after_types - before_types == set(), "出现实例级推断 ⇒ 推理有业务增益，须重新评估"


def test_class_hierarchy_closure_adds_nothing_within_the_local_domain():
    """类层次**闭包新增 = 0**（两侧都是本域具名类、且非自反）⇒ 无业务增益。"""
    g, base = _base(OWL)
    new = _closure(g) - base
    real = [(s, o) for s, p, o in new
            if p == RDFS.subClassOf and s != o
            and str(s).startswith(LOCAL) and str(o).startswith(LOCAL)]
    assert real == [], f"出现真实层次闭包边 ⇒ 须重新评估: {real}"


def test_shacl_validation_is_invariant_under_every_inference_level():
    """SHACL 校验在 ``None / rdfs / owlrl / both`` 四档下**结果完全相同**（当前数据上推理中性）。"""
    results = []
    for inf in (None, "rdfs", "owlrl", "both"):
        data = Graph()
        data.parse(str(INSTANCES))
        sh = Graph()
        sh.parse(str(SHACL))
        ont = Graph()
        ont.parse(str(OWL))
        conforms, rg, _ = validate(data, shacl_graph=sh, ont_graph=ont, inference=inf,
                                   allow_warnings=True, advanced=bool(inf))
        results.append((inf, bool(conforms), len(list(rg.subjects(RDF.type, SH.ValidationResult)))))
    assert len({(c, v) for _, c, v in results}) == 1, f"档位间出现差异 ⇒ 推理有增益: {results}"
    assert results[0][1] is True and results[0][2] == 0


def test_inference_additions_are_axiomatic_or_reflexive_noise():
    """差异**非空但无意义**：增量里绝大多数是自反/公理项（实测 自反 sameAs=242、自反 subClassOf=34）。"""
    g, base = _base(OWL)
    new = _closure(g) - base
    reflexive_sameas = [1 for s, p, o in new if str(p).endswith("sameAs") and s == o]
    reflexive_subclass = [1 for s, p, o in new if p == RDFS.subClassOf and s == o]
    assert len(new) > 200, "闭包应有增量（否则连噪声都没有，结论须重写）"
    assert len(reflexive_sameas) >= 200 and len(reflexive_subclass) >= 30, (
        f"噪声构成变化 ⇒ 须复核: sameAs={len(reflexive_sameas)} subClassOf={len(reflexive_subclass)}")
