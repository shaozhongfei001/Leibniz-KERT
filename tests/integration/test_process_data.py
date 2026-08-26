"""P3 集成测试：数据清洗、类型化、拒绝隔离、对账与血缘（FR-DATA-*）。"""

from __future__ import annotations

from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from dkws.application.ingest import Ingestor
from dkws.application.process_data import DataProcessor
from dkws.domain import hashing
from dkws.domain.errors import UsageError


@pytest.fixture
def batch_with_data(ws, tmp_path):
    """接入一个含 10 行（含错误）的 CSV 批次。"""
    csv_path = tmp_path / "products.csv"
    lines = ["product_id,name,price,rate"]
    for i in range(1, 9):
        lines.append(f"P{i:03d},产品{i},{i}.5,{i}")
    lines.append("P009,产品9,9.9,9")
    lines.append("P009,产品9重复,9.9,9")      # 重复主键拒绝
    lines.append("P010,坏价格,not-a-number,10")  # 类型错误拒绝
    lines.append("P011,,9.9,11")              # name 缺失（必填拒绝）
    csv_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    r = Ingestor(ws).ingest("product", [csv_path], "batch-fixture-1")
    return r


MAPPING_JSON = """{
  "key_policy": "product_id",
  "field_mappings": [
    {"source_field": "product_id", "target_field": "product_id", "target_type": "string", "missing_policy": "REJECT"},
    {"source_field": "name", "target_field": "name", "target_type": "string", "missing_policy": "REJECT"},
    {"source_field": "price", "target_field": "price", "target_type": "decimal", "missing_policy": "REJECT"},
    {"source_field": "rate", "target_field": "rate", "target_type": "decimal", "missing_policy": "REJECT"}
  ]
}"""


class TestProcessData:
    def test_clean_rejects_and_reconciles(self, ws, batch_with_data):
        r = DataProcessor(ws).process(
            "product", batch_with_data.batch_id, "product",
            mapping_json=MAPPING_JSON)
        assert r.input_count == 12
        assert r.passed_count == 9
        assert r.rejected_count == 3
        assert r.input_count == r.passed_count + r.rejected_count  # 对账

    def test_normalized_parquet_columns(self, ws, batch_with_data):
        r = DataProcessor(ws).process(
            "product", batch_with_data.batch_id, "product",
            mapping_json=MAPPING_JSON)
        table = pq.read_table(Path(ws) / r.normalized_rel)
        cols = table.column_names
        assert "product_id" in cols and "price" in cols
        assert "source_batch_id" in cols
        assert "source_record_id" in cols
        assert "processing_run_id" in cols
        assert "recorded_at" in cols
        assert table.num_rows == 9

    def test_rejected_parquet_with_reason(self, ws, batch_with_data):
        r = DataProcessor(ws).process(
            "product", batch_with_data.batch_id, "product",
            mapping_json=MAPPING_JSON)
        table = pq.read_table(Path(ws) / r.rejected_rel)
        reasons = set(table.column("reject_reason").to_pylist())
        assert any("missing" in str(x) for x in reasons)
        assert any("type" in str(x) for x in reasons)
        assert any("duplicate_key" in str(x) for x in reasons)
        assert table.num_rows == 3

    def test_noop_rerun(self, ws, batch_with_data):
        proc = DataProcessor(ws)
        r1 = proc.process("product", batch_with_data.batch_id, "product",
                          mapping_json=MAPPING_JSON)
        r2 = proc.process("product", batch_with_data.batch_id, "product",
                          mapping_json=MAPPING_JSON)
        assert r2.job_id == r1.job_id
        assert r2.run_id == ""

    def test_parquet_input_roundtrip(self, ws, tmp_path):
        src = tmp_path / "src.parquet"
        pq.write_table(pa.table({"id": ["A1", "A2"], "v": [1.0, 2.0]}), src)
        r = Ingestor(ws).ingest("product", [src], "batch-pq-1")
        pr = DataProcessor(ws).process(
            "product", r.batch_id, "pqdata",
            mapping_json='{"key_policy": "id", "field_mappings": ['
                          '{"source_field": "id", "target_field": "id", "target_type": "string"},'
                          '{"source_field": "v", "target_field": "v", "target_type": "decimal"}]}')
        assert pr.passed_count == 2 and pr.rejected_count == 0
        t = pq.read_table(Path(ws) / pr.normalized_rel)
        assert t.num_rows == 2

    def test_hash_mismatch_blocked(self, ws, batch_with_data):
        # 篡改批次文件使哈希不一致 → G0 阻断
        target = next((ws / "01_raw" / "product" / f"batch={batch_with_data.batch_id}").glob("*.csv"))
        target.write_text("tampered", encoding="utf-8")
        with pytest.raises(UsageError):
            DataProcessor(ws).process("product", batch_with_data.batch_id, "product",
                                      mapping_json=MAPPING_JSON)

    def test_dry_run(self, ws, batch_with_data):
        r = DataProcessor(ws, dry_run=True).process(
            "product", batch_with_data.batch_id, "product",
            mapping_json=MAPPING_JSON)
        assert r.plan and all(p.startswith("02_work/") for p in r.plan)

    def test_quality_results_written(self, ws, batch_with_data):
        DataProcessor(ws).process("product", batch_with_data.batch_id, "product",
                                  mapping_json=MAPPING_JSON)
        results = list((ws / "90_control" / "quality" / "results").glob("*.md"))
        assert len(results) >= 2
        rules = list((ws / "90_control" / "quality" / "rules").glob("*.md"))
        assert any("QR-DATA-RECONCILE" in r.name for r in rules)
