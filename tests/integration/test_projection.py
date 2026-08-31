"""P7 集成测试：Serve 投影构建与可重建性（FR-SRV-001/002、§18.4）。"""

from __future__ import annotations


import pyarrow.parquet as pq
import pytest

from dkws.application.extract import KnowledgeExtractor
from dkws.application.ingest import Ingestor
from dkws.application.parse_doc import DocumentParserService
from dkws.application.projection import ProjectionBuilder
from dkws.application.publish import Publisher
from dkws.application.review import ReviewService
from dkws.domain.contracts import specs
from dkws.domain.contracts.base import validate_contract


def _drop_time_cols(table):
    """可重建性逻辑比较：排除生成时间列（§18.4）。"""
    cols = [c for c in ("recorded_at", "generated_at") if c in table.column_names]
    return table.drop_columns(cols)


@pytest.fixture
def published_core(ws, tmp_path):
    md = tmp_path / "p.md"
    md.write_text(
        "# 政策\n\n## 产品\n\n产品A利率为3.5%。\n\n产品B利率为4.2%。\n\n"
        "产品A需要材料M1。\n\n规则：利率不超过10。\n",
        encoding="utf-8",
    )
    r = Ingestor(ws).ingest("product", [md], "batch-prj-1")
    pr = DocumentParserService(ws).parse("product", r.batch_id)
    ex = KnowledgeExtractor(ws).extract("product", r.batch_id, run_id=pr.run_id)
    ReviewService(ws).review("product", run_id=pr.run_id,
                             object_refs=[c["path"] for c in ex.candidates],
                             decision="APPROVE", reason="ok", decided_by="r")
    pub = Publisher(ws).publish("product", run_id=pr.run_id)
    return {"ws": ws, "core_version": pub.release_version}


class TestProjection:
    def test_build_projection_tables(self, published_core):
        ws = published_core["ws"]
        r = ProjectionBuilder(ws).build("product")
        svc_dir = ws / "04_serve" / "product_knowledge" / f"version={r.projection_version}"
        assert (svc_dir / "entities.parquet").is_file()
        assert (svc_dir / "relations.parquet").is_file()
        assert (svc_dir / "statements.parquet").is_file()
        assert (svc_dir / "segments.parquet").is_file()
        assert (svc_dir / "rules.parquet").is_file()
        assert (svc_dir / "vectors.parquet").is_file()
        # 行数：实体>=3（产品A/B、材料M1），关系>=1，声明>=2，规则>=1
        ents = pq.read_table(svc_dir / "entities.parquet")
        assert ents.num_rows >= 3
        rels = pq.read_table(svc_dir / "relations.parquet")
        assert rels.num_rows >= 1
        stmts = pq.read_table(svc_dir / "statements.parquet")
        assert stmts.num_rows >= 2
        segs = pq.read_table(svc_dir / "segments.parquet")
        assert segs.num_rows >= 1

    def test_projection_contract_and_current(self, published_core):
        ws = published_core["ws"]
        r = ProjectionBuilder(ws).build("product")
        svc_dir = ws / "04_serve" / "product_knowledge" / f"version={r.projection_version}"
        pmd = svc_dir / "PROJECTION.md"
        rv = validate_contract(pmd.read_text(encoding="utf-8"), specs.PROJECTION_SPEC,
                               path="PROJECTION.md")
        assert rv.ok, rv.errors
        assert rv.front_matter["verification_status"] == "VERIFIED"
        assert rv.front_matter["logical_hashes"]
        cur = ws / "04_serve" / "product_knowledge" / "CURRENT.md"
        cv = validate_contract(cur.read_text(encoding="utf-8"), specs.CURRENT_SPEC)
        assert cv.ok and cv.front_matter["target_version"] == r.projection_version

    def test_rebuild_reproducible(self, published_core):
        """§18.4：删除 Serve 版本后仅凭 Core 重建，逻辑哈希一致（排除时间列）。"""
        import shutil

        from dkws.domain import hashing as hmod

        ws = published_core["ws"]
        b = ProjectionBuilder(ws)
        r1 = b.build("product")
        svc_dir = ws / "04_serve" / "product_knowledge" / f"version={r1.projection_version}"
        t1 = pq.read_table(svc_dir / "entities.parquet")
        h1 = hmod.parquet_logical_hash(_drop_time_cols(t1), key_columns=["entity_id"])
        # 删除投影版本
        shutil.rmtree(svc_dir)
        r2 = b.build("product", core_version=published_core["core_version"],
                     idempotency_key="rebuild-test")
        svc_dir2 = ws / "04_serve" / "product_knowledge" / f"version={r2.projection_version}"
        t2 = pq.read_table(svc_dir2 / "entities.parquet")
        h2 = hmod.parquet_logical_hash(_drop_time_cols(t2), key_columns=["entity_id"])
        assert h1 == h2
        assert set(t1.column("entity_id").to_pylist()) == set(
            t2.column("entity_id").to_pylist())

    def test_statements_typed_columns(self, published_core):
        ws = published_core["ws"]
        r = ProjectionBuilder(ws).build("product")
        svc_dir = ws / "04_serve" / "product_knowledge" / f"version={r.projection_version}"
        stmts = pq.read_table(svc_dir / "statements.parquet")
        dec = stmts.column("object_value_decimal").to_pylist()
        assert any(v is not None for v in dec)
        # 每行只有一个类型化值列非空
        rows = stmts.to_pylist()
        for row in rows:
            if row["value_type"] in ("STRING", "CODE"):
                assert row["object_value_string"] is not None
            elif row["value_type"] in ("INTEGER", "DECIMAL"):
                assert row["object_value_decimal"] is not None
            elif row["value_type"] == "BOOLEAN":
                assert row["object_value_boolean"] is not None

    def test_g4_dangling_relation_blocked(self, published_core):
        # 篡改 Core：删除关系端点实体使悬空 → 投影构建应失败（G4）
        ws = published_core["ws"]
        core_dir = ws / "03_core" / "product" / \
            f"version={published_core['core_version']}"
        rel_files = sorted((core_dir / "relations").glob("*.md"))
        assert rel_files
        import re as _re
        rel_text = rel_files[0].read_text(encoding="utf-8")
        m = _re.search(r"^source_id:\s*\"?([^\n\" ]+)", rel_text, _re.M)
        assert m
        target = core_dir / "entities" / f"{m.group(1)}.md"
        assert target.is_file()
        target.unlink()
        with pytest.raises(Exception):
            ProjectionBuilder(ws).build("product")
