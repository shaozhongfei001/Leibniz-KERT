"""P8 测试：HTTP API 薄层（规格 §13）。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from dkws.api.server import create_app


@pytest.fixture
def client(ws, tmp_path):
    """搭建完整数据链路后返回 API 客户端。"""
    from dkws.application.extract import KnowledgeExtractor
    from dkws.application.ingest import Ingestor
    from dkws.application.parse_doc import DocumentParserService
    from dkws.application.projection import ProjectionBuilder
    from dkws.application.publish import Publisher
    from dkws.application.review import ReviewService

    md = tmp_path / "p.md"
    md.write_text("# 政策\n\n产品A利率为3.5%。\n\n产品A需要材料M1。\n\n规则：利率不超过10。\n",
                  encoding="utf-8")
    r = Ingestor(ws).ingest("product", [md], "batch-api-1")
    pr = DocumentParserService(ws).parse("product", r.batch_id)
    ex = KnowledgeExtractor(ws).extract("product", r.batch_id, run_id=pr.run_id)
    ReviewService(ws).review("product", run_id=pr.run_id,
                             object_refs=[c["path"] for c in ex.candidates],
                             decision="APPROVE", reason="ok", decided_by="r")
    Publisher(ws).publish("product", run_id=pr.run_id)
    ProjectionBuilder(ws).build("product")
    return TestClient(create_app(ws))


class TestApi:
    def test_health(self, client):
        r = client.get("/v1/health")
        assert r.status_code == 200
        assert r.json()["data"]["status"] == "OK"

    def test_search(self, client):
        r = client.post("/v1/search", json={
            "request_id": "REQ-1", "query": "利率", "mode": "FULLTEXT", "top_k": 5})
        assert r.status_code == 200
        body = r.json()
        assert body["errors"] == []
        assert body["data"]["hit_count"] >= 1

    def test_rules_evaluate(self, client):
        r = client.post("/v1/rules/evaluate", json={
            "request_id": "REQ-2", "facts": {"rate": 5}})
        assert r.status_code == 200
        assert len(r.json()["data"]["matched_rules"]) >= 1

    def test_graph(self, client, ws, proj_version):
        import pyarrow.parquet as pq

        t = pq.read_table(ws / "04_serve" / "product_knowledge"
                          / f"version={proj_version(ws)}" / "entities.parquet")
        eid = t.column("entity_id").to_pylist()[0]
        r = client.post("/v1/graph/query", json={
            "request_id": "REQ-3", "start_entity_ids": [eid], "max_depth": 1})
        assert r.status_code == 200
        assert "nodes" in r.json()["data"]

    def test_evidence(self, client, ws, proj_version):
        import pyarrow.parquet as pq

        t = pq.read_table(ws / "04_serve" / "product_knowledge"
                          / f"version={proj_version(ws)}" / "statements.parquet")
        sid = t.column("statement_id").to_pylist()[0]
        r = client.get(f"/v1/evidence/{sid}")
        assert r.status_code == 200
        assert "chain" in r.json()["data"]

    def test_catalog(self, client):
        r = client.get("/v1/catalog")
        assert r.status_code == 200
        assert "projections" in r.json()["data"]

    def test_job_not_found(self, client):
        r = client.get("/v1/jobs/JOB-NOT-EXIST")
        assert r.status_code == 404

    def test_extraction_202(self, client, ws):
        # 复用批次路径
        batch_dir = next((ws / "01_raw" / "product").glob("batch=*"))
        doc = next(batch_dir.glob("*.md"))
        rel = f"01_raw/product/{batch_dir.name}/{doc.name}"
        r = client.post("/v1/extractions", json={
            "request_id": "REQ-EXT-1", "idempotency_key": "client-1",
            "domain": "product",
            "input": {"type": "workspace_file", "path": rel},
            "extraction_types": ["ENTITY", "STATEMENT"],
        })
        assert r.status_code == 202
        body = r.json()
        assert body["data"]["result_status"] == "CANDIDATE"
        assert body["data"]["publish_status"] == "NOT_PUBLISHED"
