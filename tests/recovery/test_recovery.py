"""P9 恢复测试（规格 §18.1 Recovery）：故障注入、半发布、重建。"""

from __future__ import annotations

from pathlib import Path

import pytest

from dkws.application.extract import KnowledgeExtractor
from dkws.application.ingest import Ingestor
from dkws.application.parse_doc import DocumentParserService
from dkws.application.process_data import DataProcessor
from dkws.application.publish import Publisher
from dkws.application.review import ReviewService
from dkws.domain.errors import QualityGateError


@pytest.fixture
def ready_to_publish(ws, tmp_path):
    md = tmp_path / "p.md"
    md.write_text("# 政策\n\n产品A利率为3.5%。\n\n产品A需要材料M1。\n\n规则：利率不超过10。\n",
                  encoding="utf-8")
    r = Ingestor(ws).ingest("product", [md], "batch-rec-1")
    pr = DocumentParserService(ws).parse("product", r.batch_id)
    ex = KnowledgeExtractor(ws).extract("product", r.batch_id, run_id=pr.run_id)
    ReviewService(ws).review("product", run_id=pr.run_id,
                             object_refs=[c["path"] for c in ex.candidates],
                             decision="APPROVE", reason="ok", decided_by="r")
    return {"ws": ws, "batch_id": r.batch_id, "run_id": pr.run_id}


class TestRecovery:
    def test_half_publish_leaves_no_version(self, ready_to_publish, monkeypatch):
        """§11.8/18.1：发布中途失败不得留下被误认为有效版本。"""
        ws = ready_to_publish["ws"]
        pub = Publisher(ws)

        def _boom(*a, **k):
            raise RuntimeError("注入的发布故障")

        monkeypatch.setattr(pub, "_write_current", _boom)
        with pytest.raises(RuntimeError):
            pub.publish("product", run_id=ready_to_publish["run_id"])
        # 发布失败：CURRENT 指针不得切换（§11.8：先新版本后指针）
        assert not (ws / "03_core" / "product" / "CURRENT.md").exists()
        # 无残留临时目录
        assert not list((ws / "03_core" / "product").glob(".tmp-*"))
        # 任务被记录为 FAILED

    def test_failed_publish_job_recorded(self, ready_to_publish, monkeypatch):
        ws = ready_to_publish["ws"]
        pub = Publisher(ws)

        def _boom(*a, **k):
            raise RuntimeError("gate 故障")

        monkeypatch.setattr(pub, "_run_g3_gate", _boom)
        with pytest.raises(RuntimeError):
            pub.publish("product", run_id=ready_to_publish["run_id"])
        jobs = list((ws / "90_control" / "jobs").glob("JOB-PUBLISH-*"))
        assert jobs
        status = (jobs[0] / "STATUS.md").read_text(encoding="utf-8")
        assert "status: FAILED" in status or 'status: "FAILED"' in status

    def test_delete_work_rebuild_projection(self, ready_to_publish, proj_version):
        """§18.4：删除 02_work 后仅用 Core 重建投影。"""
        import shutil

        from dkws.application.projection import ProjectionBuilder

        ws = ready_to_publish["ws"]
        Publisher(ws).publish("product", run_id=ready_to_publish["run_id"])
        ProjectionBuilder(ws).build("product")
        # 记录逻辑摘要
        proj = ws / "04_serve" / "product_knowledge" / f"version={proj_version(ws)}"
        from dkws.domain import hashing
        pqmod = __import__("pyarrow.parquet", fromlist=["read_table"])
        t1 = pqmod.read_table(proj / "entities.parquet")
        if "recorded_at" in t1.column_names:
            t1 = t1.drop_columns(["recorded_at"])
        h1 = hashing.parquet_logical_hash(t1, key_columns=["entity_id"])
        # 删除 02_work 与 Serve 版本
        shutil.rmtree(ws / "02_work")
        shutil.rmtree(proj)
        # 重建投影（仅 Core + 控制合同）
        ProjectionBuilder(ws).build("product", idempotency_key="rec-rebuild")
        t2 = pqmod.read_table(proj / "entities.parquet")
        if "recorded_at" in t2.column_names:
            t2 = t2.drop_columns(["recorded_at"])
        h2 = hashing.parquet_logical_hash(t2, key_columns=["entity_id"])
        assert h1 == h2

    def test_rerun_after_interrupt_no_duplicates(self, ws, tmp_path):
        """§18.1：中断重试不得产生重复批次（幂等）。"""
        src = tmp_path / "d.csv"
        src.write_text("id,v\n1,a\n", encoding="utf-8")
        ing = Ingestor(ws)
        r1 = ing.ingest("product", [src], "rec-idem-1")
        r2 = ing.ingest("product", [src], "rec-idem-1")
        assert r2.noop and r2.batch_id == r1.batch_id
        assert len(list((ws / "01_raw" / "product").glob("batch=*"))) == 1
