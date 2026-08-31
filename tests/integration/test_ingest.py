"""P2 集成测试：Raw 接入、Manifest、哈希、幂等、任务控制（G0）。"""

from __future__ import annotations


import pytest

from dkws.application.ingest import Ingestor
from dkws.application.jobs import read_job_status
from dkws.domain import hashing
from dkws.domain.contracts import specs
from dkws.domain.contracts.base import validate_contract
from dkws.domain.errors import IdempotencyConflictError, UsageError


@pytest.fixture
def source_file(tmp_path):
    def _make(name="products.csv", content="id,name\n1,A\n2,B\n", suffix=None):
        p = tmp_path / (suffix or name)
        p.write_bytes(content.encode("utf-8"))
        return p
    return _make


class TestIngest:
    def test_ingest_creates_closed_batch(self, ws, source_file):
        src = source_file()
        r = Ingestor(ws).ingest("product", [src], "ingest-001")
        assert not r.noop
        batch_dir = ws / "01_raw" / "product" / f"batch={r.batch_id}"
        assert batch_dir.is_dir()
        manifest = batch_dir / "MANIFEST.md"
        assert manifest.is_file()
        text = manifest.read_text(encoding="utf-8")
        result = validate_contract(text, specs.MANIFEST_SPEC, path="MANIFEST.md")
        assert result.ok, result.errors
        fm = result.front_matter
        assert fm["status"] == "CLOSED"
        assert fm["domain"] == "product"
        assert fm["idempotency_key"] == "ingest-001"
        assert fm["closed_at"]
        # 复制而非移动：源文件保留
        assert src.is_file()
        # 哈希一致
        assert fm["files"][0]["sha256"] == hashing.sha256_file(src)

    def test_ingest_job_completed_with_report(self, ws, source_file):
        r = Ingestor(ws).ingest("product", [source_file()], "ingest-002")
        status = read_job_status(ws, r.job_id)
        assert status["status"] == "COMPLETED"
        assert status["progress"] == 100
        report = ws / "90_control" / "jobs" / r.job_id / "RUN_REPORT.md"
        assert report.is_file()
        rv = validate_contract(report.read_text(encoding="utf-8"),
                               specs.RUN_REPORT_SPEC, path="RUN_REPORT.md")
        assert rv.ok, rv.errors
        log = ws / "90_control" / "logs"
        assert any(log.rglob(f"{r.job_id}.log"))

    def test_idempotent_noop(self, ws, source_file):
        src = source_file()
        ing = Ingestor(ws)
        r1 = ing.ingest("product", [src], "ingest-idem-1")
        r2 = ing.ingest("product", [src], "ingest-idem-1")
        assert r2.noop is True
        assert r2.batch_id == r1.batch_id
        # 批次不重复
        batches = list((ws / "01_raw" / "product").glob("batch=*"))
        assert len(batches) == 1

    def test_idempotent_conflict_different_content(self, ws, source_file):
        ing = Ingestor(ws)
        ing.ingest("product", [source_file()], "ingest-idem-2")
        with pytest.raises(IdempotencyConflictError):
            ing.ingest("product", [source_file(content="id,name\n1,X\n")], "ingest-idem-2")

    def test_disguised_file_rejected(self, ws, source_file):
        fake_pdf = source_file(suffix="fake.pdf", content="not a pdf at all")
        with pytest.raises(UsageError):
            Ingestor(ws).ingest("product", [fake_pdf], "ingest-disguise")

    def test_bad_extension_rejected(self, ws, source_file):
        exe = source_file(suffix="evil.exe", content="MZ...")
        with pytest.raises(UsageError):
            Ingestor(ws).ingest("product", [exe], "ingest-ext")

    def test_dry_run_creates_nothing(self, ws, source_file):
        src = source_file()
        r = Ingestor(ws, dry_run=True).ingest("product", [src], "ingest-dry")
        assert r.plan and r.plan[0].startswith("01_raw/product/batch=")
        prod_dir = ws / "01_raw" / "product"
        assert not prod_dir.exists() or not list(prod_dir.iterdir())

    def test_quarantine_on_manifest_failure_cleanup(self, ws, source_file):
        # 源校验在复制前完成；错误路径不得留下任何批次目录
        with pytest.raises(UsageError):
            Ingestor(ws).ingest("product", [ws / "no_such.csv"], "ingest-bad")
        prod_dir = ws / "01_raw" / "product"
        assert not prod_dir.exists() or not list(prod_dir.iterdir())

    def test_lineage_written(self, ws, source_file):
        Ingestor(ws).ingest("product", [source_file()], "ingest-lg")
        lineage_files = list((ws / "90_control" / "lineage" / "ingest").glob("*.md"))
        assert len(lineage_files) == 1
        text = lineage_files[0].read_text(encoding="utf-8")
        rv = validate_contract(text, specs.LINEAGE_SPEC, path="lineage.md")
        assert rv.ok, rv.errors

    def test_parquet_ingest(self, ws):
        import pyarrow as pa
        import pyarrow.parquet as pq

        src = ws.parent / "products_src.parquet"
        pq.write_table(pa.table({"id": [1, 2], "name": ["A", "B"]}), src)
        r = Ingestor(ws).ingest("product", [src], "ingest-pq")
        fm = validate_contract(
            (ws / "01_raw" / "product" / f"batch={r.batch_id}" / "MANIFEST.md")
            .read_text(encoding="utf-8"), specs.MANIFEST_SPEC).front_matter
        assert fm["files"][0]["media_type"] == "application/vnd.apache.parquet"
        assert fm["files"][0]["role"] == "DATA"


class TestJobControl:
    def test_status_contract(self, ws, source_file):
        from dkws.application.jobs import JobController
        from dkws.infrastructure.fs import WorkspaceWriter

        job = JobController(ws, WorkspaceWriter(ws), job_type="TEST",
                            requested_by="t", idempotency_key="k1")
        job.start()
        job.update(progress=50)
        job.finish(output_refs=[], input_count=1, output_count=1)
        text = (ws / "90_control" / "jobs" / job.job_id / "STATUS.md").read_text(encoding="utf-8")
        rv = validate_contract(text, specs.JOB_STATUS_SPEC, path="STATUS.md")
        assert rv.ok, rv.errors
        assert rv.front_matter["status"] == "COMPLETED"

    def test_illegal_jump_rejected(self, ws):
        from dkws.application.jobs import JobController
        from dkws.domain.errors import UsageError
        from dkws.infrastructure.fs import WorkspaceWriter

        job = JobController(ws, WorkspaceWriter(ws), job_type="TEST",
                            requested_by="t", idempotency_key="k2")
        with pytest.raises(UsageError):
            job.update(status="COMPLETED")  # PENDING → COMPLETED 非法

    def test_failed_job_report(self, ws):
        from dkws.application.jobs import JobController
        from dkws.domain.contracts import specs as sp
        from dkws.infrastructure.fs import WorkspaceWriter

        job = JobController(ws, WorkspaceWriter(ws), job_type="TEST",
                            requested_by="t", idempotency_key="k3")
        job.start()
        job.fail("TEST_ERROR", "演示失败")
        status = read_job_status(ws, job.job_id)
        assert status["status"] == "FAILED"
        assert status["error_code"] == "TEST_ERROR"
        report = (ws / "90_control" / "jobs" / job.job_id / "RUN_REPORT.md").read_text(encoding="utf-8")
        assert validate_contract(report, sp.RUN_REPORT_SPEC).ok

    def test_lock_conflict(self, ws):
        from dkws.infrastructure import locks as locks_mod

        lk = locks_mod.WorkspaceLock(ws, "domain:product", job_id="JOB-A", owner="t")
        lk.acquire()
        try:
            with pytest.raises(Exception):
                locks_mod.WorkspaceLock(ws, "domain:product", job_id="JOB-B", owner="t").acquire()
        finally:
            lk.release()
