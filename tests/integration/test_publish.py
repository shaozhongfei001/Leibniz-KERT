"""P6 集成测试：Core 发布、Release、Current、回滚（FR-PUB-*）。"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from dkws.application.extract import KnowledgeExtractor
from dkws.application.ingest import Ingestor
from dkws.application.parse_doc import DocumentParserService
from dkws.application.publish import Publisher
from dkws.application.review import ReviewService
from dkws.application.rollback import RollbackService
from dkws.domain.contracts import specs
from dkws.domain.contracts.base import validate_contract
from dkws.domain.errors import QualityGateError, UsageError


@pytest.fixture
def approved_set(ws, tmp_path):
    """接入→解析→抽取→全部 APPROVE 的完整前置。"""
    md = tmp_path / "policy.md"
    md.write_text(
        "# 政策\n\n## 产品\n\n产品A利率为3.5%。\n\n产品B利率为4.2%。\n\n"
        "产品A需要材料M1。\n\n规则：利率不超过10。\n",
        encoding="utf-8",
    )
    r = Ingestor(ws).ingest("product", [md], "batch-pub-1")
    pr = DocumentParserService(ws).parse("product", r.batch_id)
    ex = KnowledgeExtractor(ws).extract("product", r.batch_id,
                                        run_id=pr.run_id)
    svc = ReviewService(ws)
    refs = [c["path"] for c in ex.candidates]
    svc.review("product", run_id=pr.run_id, object_refs=refs,
               decision="APPROVE", reason="全部核对一致", decided_by="reviewer")
    return {"ws": ws, "batch_id": r.batch_id, "run_id": pr.run_id}


class TestPublish:
    def test_publish_creates_core_version(self, approved_set):
        ws = approved_set["ws"]
        r = Publisher(ws).publish("product", run_id=approved_set["run_id"])
        version_dir = ws / "03_core" / "product" / f"version={r.release_version}"
        assert version_dir.is_dir()
        release = version_dir / "RELEASE.md"
        assert release.is_file()
        rv = validate_contract(release.read_text(encoding="utf-8"),
                               specs.RELEASE_SPEC, path="RELEASE.md")
        assert rv.ok, rv.errors
        fm = rv.front_matter
        assert fm["status"] == "PUBLISHED"
        assert fm["domain"] == "product"
        assert len(fm["asset_manifest"]) == r.asset_count
        # 清单哈希可重算
        for item in fm["asset_manifest"]:
            p = version_dir / item["path"]
            assert p.is_file()
            from dkws.domain import hashing
            assert hashing.md_semantic_sha256(p.read_text(encoding="utf-8")) == item["sha256"]

    def test_publish_sets_current_pointer(self, approved_set):
        ws = approved_set["ws"]
        r = Publisher(ws).publish("product", run_id=approved_set["run_id"])
        cur = ws / "03_core" / "product" / "CURRENT.md"
        assert cur.is_file()
        cv = validate_contract(cur.read_text(encoding="utf-8"), specs.CURRENT_SPEC,
                               path="CURRENT.md")
        assert cv.ok, cv.errors
        assert cv.front_matter["target_version"] == r.release_version
        assert cv.front_matter["scope_type"] == "CORE_DOMAIN"

    def test_publish_only_approved(self, ws, tmp_path):
        md = tmp_path / "p.md"
        md.write_text("# 政策\n\n产品A利率为3.5%。\n", encoding="utf-8")
        r = Ingestor(ws).ingest("product", [md], "batch-pub-2")
        pr = DocumentParserService(ws).parse("product", r.batch_id)
        KnowledgeExtractor(ws).extract("product", r.batch_id, run_id=pr.run_id)
        # 无 APPROVE → 发布被门禁拒绝（FR-PUB-001）
        with pytest.raises(QualityGateError):
            Publisher(ws).publish("product", run_id=pr.run_id)
        assert not (ws / "03_core" / "product").exists() or not list(
            (ws / "03_core" / "product").glob("version=*"))

    def test_release_requires_decision(self, approved_set):
        ws = approved_set["ws"]
        r = Publisher(ws).publish("product", run_id=approved_set["run_id"])
        rel_text = (ws / "03_core" / "product" / f"version={r.release_version}" / "RELEASE.md"
                    ).read_text(encoding="utf-8")
        fm = validate_contract(rel_text, specs.RELEASE_SPEC).front_matter
        assert fm["approval_decision_ids"]

    def test_version_increment(self, approved_set):
        ws = approved_set["ws"]
        pub = Publisher(ws)
        r1 = pub.publish("product", run_id=approved_set["run_id"])
        r2 = pub.publish("product", run_id=approved_set["run_id"],
                         release_version="2099.01.01.1")
        assert r2.release_version != r1.release_version

    def test_core_assets_contract(self, approved_set):
        ws = approved_set["ws"]
        r = Publisher(ws).publish("product", run_id=approved_set["run_id"])
        version_dir = ws / "03_core" / "product" / f"version={r.release_version}"
        count = 0
        for f in version_dir.rglob("*.md"):
            if f.name == "RELEASE.md":
                continue
            text = f.read_text(encoding="utf-8")
            schema = validate_contract(text, specs.get_spec(
                __import__("dkws.infrastructure.markdown", fromlist=["parse_contract_md"])
                .parse_contract_md(text).front_matter.get("schema", ""))).front_matter.get("schema")
            rv = validate_contract(text, specs.get_spec(schema), path=f.name)
            assert rv.ok, (f.name, rv.errors)
            count += 1
        assert count == r.asset_count


class TestRollback:
    def test_rollback_switches_pointer(self, approved_set):
        ws = approved_set["ws"]
        pub = Publisher(ws)
        r1 = pub.publish("product", run_id=approved_set["run_id"])
        # 第二次发布（显式新版本）
        r2 = pub.publish("product", run_id=approved_set["run_id"],
                         release_version="2099.01.01.1")
        cur = (ws / "03_core" / "product" / "CURRENT.md").read_text(encoding="utf-8")
        assert validate_contract(cur, specs.CURRENT_SPEC).front_matter[
            "target_version"] == "2099.01.01.1"
        # 回滚到 r1
        rb = RollbackService(ws).rollback("CORE_DOMAIN", "product", r1.release_version,
                                          reason="回归")
        assert rb.from_version == "2099.01.01.1"
        assert rb.to_version == r1.release_version
        cur2 = (ws / "03_core" / "product" / "CURRENT.md").read_text(encoding="utf-8")
        assert validate_contract(cur2, specs.CURRENT_SPEC).front_matter[
            "target_version"] == r1.release_version
        # 历史版本保留
        assert (ws / "03_core" / "product" / "version=2099.01.01.1").is_dir()

    def test_rollback_to_missing_version_rejected(self, approved_set):
        ws = approved_set["ws"]
        Publisher(ws).publish("product", run_id=approved_set["run_id"])
        from dkws.domain.errors import VersionNotFoundError

        with pytest.raises(VersionNotFoundError):
            RollbackService(ws).rollback("CORE_DOMAIN", "product", "1999.01.01.9",
                                         reason="不存在版本")
