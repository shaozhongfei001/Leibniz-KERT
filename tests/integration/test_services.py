"""P8 集成测试：查询/图谱/检索/规则/溯源服务（FR-SRV-*）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from dkws.application.extract import KnowledgeExtractor
from dkws.application.ingest import Ingestor
from dkws.application.parse_doc import DocumentParserService
from dkws.application.process_data import DataProcessor
from dkws.application.projection import ProjectionBuilder
from dkws.application.publish import Publisher
from dkws.application.review import ReviewService
from dkws.application.services import KnowledgeService
from dkws.domain.errors import AssetNotFoundError, ServiceNotReadyError


@pytest.fixture
def served_workspace(ws, tmp_path):
    """完整链路：数据+文档 → Core → Serve。"""
    # 结构化数据
    csv = tmp_path / "products.csv"
    lines = ["product_id,name,price,rate"]
    for i in range(1, 5):
        lines.append(f"P{i:03d},产品{i},{i}.5,{i}")
    csv.write_text("\n".join(lines) + "\n", encoding="utf-8")
    r1 = Ingestor(ws).ingest("product", [csv], "batch-srv-data")
    DataProcessor(ws).process("product", r1.batch_id, "product",
                              mapping_json='{"key_policy": "product_id", "field_mappings": ['
                                            '{"source_field": "product_id", "target_field": "product_id", "target_type": "string"},'
                                            '{"source_field": "name", "target_field": "name", "target_type": "string"},'
                                            '{"source_field": "price", "target_field": "price", "target_type": "decimal"},'
                                            '{"source_field": "rate", "target_field": "rate", "target_type": "decimal"}]}')
    # 文档 → 候选 → 发布
    md = tmp_path / "policy.md"
    md.write_text("# 政策\n\n## 产品\n\n产品A利率为3.5%。\n\n产品B利率为4.2%。\n\n"
                  "产品A需要材料M1。\n\n规则：利率不超过10。\n", encoding="utf-8")
    r2 = Ingestor(ws).ingest("product", [md], "batch-srv-doc")
    pr = DocumentParserService(ws).parse("product", r2.batch_id)
    ex = KnowledgeExtractor(ws).extract("product", r2.batch_id, run_id=pr.run_id)
    ReviewService(ws).review("product", run_id=pr.run_id,
                             object_refs=[c["path"] for c in ex.candidates],
                             decision="APPROVE", reason="ok", decided_by="r")
    Publisher(ws).publish("product", run_id=pr.run_id)
    ProjectionBuilder(ws).build("product")
    return ws


class TestDataQuery:
    def test_query_with_filter(self, served_workspace):
        r = KnowledgeService(served_workspace).data_query(
            "product", where={"rate": 2}, select=["product_id", "name"], limit=10)
        assert r.data["count"] == 1
        assert r.data["records"][0]["product_id"] == "P002"

    def test_query_limit(self, served_workspace):
        r = KnowledgeService(served_workspace).data_query("product", limit=2)
        assert r.data["count"] == 2


class TestEntity:
    def test_get_entity_with_statements(self, served_workspace, proj_version):
        svc = KnowledgeService(served_workspace)
        svc.data_query("product", limit=1)
        # 取实体投影中的第一个实体
        import pyarrow.parquet as pq
        t = pq.read_table(Path(served_workspace) / "04_serve" / "product_knowledge"
                          / f"version={proj_version(served_workspace)}" / "entities.parquet")
        eid = t.column("entity_id").to_pylist()[0]
        r = svc.get_entity(eid)
        assert r.data["entity"]["entity_id"] == eid
        assert r.data["statement_count"] >= 0

    def test_get_entity_missing(self, served_workspace):
        with pytest.raises(AssetNotFoundError):
            KnowledgeService(served_workspace).get_entity("ENT-NOPE")


class TestGraph:
    def test_neighbors(self, served_workspace, proj_version):
        svc = KnowledgeService(served_workspace)
        import pyarrow.parquet as pq
        ents = pq.read_table(Path(served_workspace) / "04_serve" / "product_knowledge"
                             / f"version={proj_version(served_workspace)}" / "entities.parquet")
        names = ents.column("name").to_pylist()
        prod_a = next(n for n in names if "产品A" in n)
        ents2 = ents.to_pylist()
        eid = next(e["entity_id"] for e in ents2 if e["name"] == prod_a)
        r = svc.graph([eid], relation_types=["REQUIRES"], direction="OUT", max_depth=1)
        assert r.data["node_count"] >= 1
        assert r.data["edges"]

    def test_depth_limit_enforced(self, served_workspace):
        with pytest.raises(Exception):
            KnowledgeService(served_workspace).graph(["X"], max_depth=11)


class TestSearch:
    def test_fulltext(self, served_workspace):
        r = KnowledgeService(served_workspace).search("利率", mode="FULLTEXT")
        assert r.data["hit_count"] >= 1
        hit = r.data["hits"][0]
        assert hit["segment_id"].startswith("SEG-")
        assert hit["evidence_uri"]

    def test_hybrid(self, served_workspace):
        r = KnowledgeService(served_workspace).search("产品A", mode="HYBRID", top_k=5)
        assert r.meta.get("ranking_policy_version") == "rank/v1"
        assert r.data["hit_count"] >= 1

    def test_vector_degraded_flag(self, served_workspace):
        r = KnowledgeService(served_workspace).search("材料", mode="VECTOR")
        assert r.data["hit_count"] >= 1 or r.data.get("degraded") is True


class TestRules:
    def test_evaluate_match(self, served_workspace):
        r = KnowledgeService(served_workspace).evaluate_rule(facts={"rate": 5})
        assert len(r.data["matched_rules"]) >= 1
        assert r.data["outcomes"][0]["outcome"].get("result") == "OK"

    def test_evaluate_no_match(self, served_workspace):
        r = KnowledgeService(served_workspace).evaluate_rule(facts={"rate": 99})
        assert r.data["matched_rules"] == []

    def test_missing_input(self, served_workspace):
        r = KnowledgeService(served_workspace).evaluate_rule(facts={})
        assert r.data["missing_inputs"]  # UNKNOWN 不自动等于 FALSE


class TestTrace:
    def test_trace_chain(self, served_workspace, proj_version):
        svc = KnowledgeService(served_workspace)
        import pyarrow.parquet as pq
        stmts = pq.read_table(Path(served_workspace) / "04_serve" / "product_knowledge"
                              / f"version={proj_version(served_workspace)}" / "statements.parquet")
        sid = stmts.column("statement_id").to_pylist()[0]
        r = svc.trace(sid)
        assert r.data["complete"] is True
        layers = [c["layer"] for c in r.data["chain"]]
        assert "04_serve" in layers and "03_core" in layers
        assert r.data["raw_hashes"]

    def test_served_only_active_projection(self, served_workspace):
        """FR-SRV-008：注入 Work 候选不改变正式查询。"""
        svc = KnowledgeService(served_workspace)
        before = len(svc.search("产品A").data["hits"])
        # 注入一个未发布候选实体（直接写 Work candidates 目录）
        from dkws.infrastructure.fs import WorkspaceWriter
        w = WorkspaceWriter(served_workspace)
        w.write_text("02_work/product/run=INJECT/candidates/entities/ENT-INJ.md",
                     "# 注入候选\n")
        after = len(svc.search("产品A").data["hits"])
        assert before == after


class TestServiceReadiness:
    def test_no_projection_raises(self, ws):
        with pytest.raises(ServiceNotReadyError):
            KnowledgeService(ws).search("x")
