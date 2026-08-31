"""P9 门禁报告测试（§17.4、§18.5：G0—G5 可复现报告）。"""

from __future__ import annotations


import pytest

from dkws.application.extract import KnowledgeExtractor
from dkws.application.gates import GateReporter
from dkws.application.ingest import Ingestor
from dkws.application.parse_doc import DocumentParserService
from dkws.application.projection import ProjectionBuilder
from dkws.application.publish import Publisher
from dkws.application.review import ReviewService
from dkws.domain.contracts import specs
from dkws.domain.contracts.base import validate_contract


@pytest.fixture
def full_workspace(ws, tmp_path):
    md = tmp_path / "p.md"
    md.write_text("# 政策\n\n产品A利率为3.5%。\n\n产品A需要材料M1。\n\n规则：利率不超过10。\n",
                  encoding="utf-8")
    r = Ingestor(ws).ingest("product", [md], "batch-gate-1")
    pr = DocumentParserService(ws).parse("product", r.batch_id)
    ex = KnowledgeExtractor(ws).extract("product", r.batch_id, run_id=pr.run_id)
    ReviewService(ws).review("product", run_id=pr.run_id,
                             object_refs=[c["path"] for c in ex.candidates],
                             decision="APPROVE", reason="ok", decided_by="r")
    Publisher(ws).publish("product", run_id=pr.run_id)
    ProjectionBuilder(ws).build("product")
    return ws


class TestGateReporter:
    def test_all_gates_pass_on_full_workspace(self, full_workspace):
        results = GateReporter(full_workspace).run_all()
        assert [r.gate_id for r in results] == ["G0", "G1", "G2", "G3", "G4", "G5"]
        assert all(r.ok for r in results), [
            (r.gate_id, [(f.level, f.message) for f in r.findings]) for r in results]
        assert all(r.report_rel for r in results)

    def test_reports_contract_valid(self, full_workspace):
        GateReporter(full_workspace).run_all()
        reports = sorted((full_workspace / "90_control" / "quality" / "gates").glob("*.md"))
        assert len(reports) == 6
        for rp in reports:
            rv = validate_contract(rp.read_text(encoding="utf-8"),
                                   specs.GATE_REPORT_SPEC, path=rp.name)
            assert rv.ok, (rp.name, rv.errors)
            assert rv.front_matter["decision"] in (
                "PASS_FOR_NEXT_GATE", "PASS_WITH_REQUIRED_CHANGES",
                "RETURN_TO_WORK", "BLOCKED", "INSUFFICIENT_EVIDENCE")

    def test_g0_detects_hash_tamper(self, full_workspace):
        # 篡改批次文件 → G0 必须返回 RETURN_TO_WORK 且含 HASH_MISMATCH
        batch_dir = next((full_workspace / "01_raw" / "product").glob("batch=*"))
        target = next(f for f in batch_dir.iterdir() if f.is_file() and f.name != "MANIFEST.md")
        target.write_bytes(b"tampered")
        g0 = GateReporter(full_workspace).g0()
        assert not g0.ok
        assert any(f.code == "G0_HASH_MISMATCH" for f in g0.findings)

    def test_g5_health_on_empty_workspace(self, ws):
        results = GateReporter(ws).run_all()
        g5 = results[5]
        # 无服务投影 → G5 不通过但报告仍生成
        assert g5.report_rel
        assert not g5.ok

    def test_reports_idempotent_sequence(self, full_workspace):
        GateReporter(full_workspace).run_all()
        GateReporter(full_workspace).run_all()
        reports = sorted((full_workspace / "90_control" / "quality" / "gates").glob("*.md"))
        # 同一轮生成 6 个；再次运行生成新的 6 个（-02 后缀），不覆盖
        assert len(reports) == 12
