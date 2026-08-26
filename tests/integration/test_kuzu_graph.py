"""IMP-ADR-011：Kùzu 图谱投影测试（构建、可重建、查询后端、validate 豁免）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from dkws.application.extract import KnowledgeExtractor
from dkws.application.ingest import Ingestor
from dkws.application.parse_doc import DocumentParserService
from dkws.application.projection import ProjectionBuilder
from dkws.application.publish import Publisher
from dkws.application.review import ReviewService
from dkws.application.services import KnowledgeService
from dkws.domain import workspace as ws_mod
from dkws.infrastructure.graph.kuzu_builder import KuzuGraphBuilder


@pytest.fixture
def projected(ws, tmp_path):
    """含知识投影的完整工作区（graph 由 build 自动构建）。"""
    md = tmp_path / "p.md"
    md.write_text("# 政策\n\n产品A利率为3.5%。\n\n产品A需要材料M1。\n\n产品B需要材料M1。\n\n"
                  "规则：利率不超过10。\n", encoding="utf-8")
    r = Ingestor(ws).ingest("product", [md], "batch-graph-1")
    pr = DocumentParserService(ws).parse("product", r.batch_id)
    ex = KnowledgeExtractor(ws).extract("product", r.batch_id, run_id=pr.run_id)
    ReviewService(ws).review("product", run_id=pr.run_id,
                             object_refs=[c["path"] for c in ex.candidates],
                             decision="APPROVE", reason="ok", decided_by="r")
    Publisher(ws).publish("product", run_id=pr.run_id)
    ProjectionBuilder(ws).build("product")
    return ws


class TestKuzuBuilder:
    def test_build_creates_graph(self, projected):
        b = KuzuGraphBuilder(projected)
        assert b.graph_available()
        fp = b.fingerprint_of(b._active_version())
        assert fp and fp["nodes"] >= 2 and fp["edges"] >= 1

    def test_graph_rebuildable(self, projected, proj_version):
        """删 graph → 仅凭投影重建，指纹一致。"""
        ws = projected
        b = KuzuGraphBuilder(ws)
        v = b._active_version()
        fp1 = b.fingerprint_of(v)
        graph_file = b.graph_path(v)
        assert graph_file and graph_file.is_file()
        graph_file.unlink()
        (Path(ws) / "04_serve" / "product_knowledge" / f"version={v}" / "graph.PROJECTION.json").unlink(missing_ok=True)
        b.build(v)
        fp2 = b.fingerprint_of(v)
        assert fp1 == fp2


class TestKuzuGraphBackend:
    def test_neighbor_multi_hop(self, projected, proj_version):
        ws = projected
        svc = KnowledgeService(ws)
        # 找产品A实体
        import pyarrow.parquet as pq
        ents = pq.read_table(Path(ws) / "04_serve" / "product_knowledge"
                             / f"version={proj_version(ws)}" / "entities.parquet").to_pylist()
        start = next(e["entity_id"] for e in ents if "产品A" in e["name"])
        r = svc.graph([start], direction="OUT", max_depth=3, mode="neighbor")
        assert r.data["node_count"] >= 1
        assert r.data["mode"] == "neighbor"

    def test_paths_mode(self, projected, proj_version):
        ws = projected
        svc = KnowledgeService(ws)
        import pyarrow.parquet as pq
        ents = pq.read_table(Path(ws) / "04_serve" / "product_knowledge"
                             / f"version={proj_version(ws)}" / "entities.parquet").to_pylist()
        start = next(e["entity_id"] for e in ents if "产品A" in e["name"])
        r = svc.graph([start], direction="OUT", max_depth=4, mode="paths")
        assert r.data["paths"], r.data

    def test_depth_limit_relaxed(self, projected, proj_version):
        ws = projected
        svc = KnowledgeService(ws)
        import pyarrow.parquet as pq
        ents = pq.read_table(Path(ws) / "04_serve" / "product_knowledge"
                             / f"version={proj_version(ws)}" / "entities.parquet").to_pylist()
        start = next(e["entity_id"] for e in ents if "产品A" in e["name"])
        r = svc.graph([start], max_depth=6)  # 超过原 3 硬限（不再报错）
        assert r.data["node_count"] >= 2


class TestValidateExempt:
    def test_graph_dir_does_not_fail_validate(self, projected):
        ws = projected
        findings = ws_mod.check_workspace(ws, mode="full")
        graph_files = [f for f in findings if "/graph/" in f.path]
        assert graph_files == [], graph_files
        blockers = [f for f in findings if f.level in ("BLOCKER", "MAJOR")]
        assert not blockers, blockers
