"""P4 集成测试：文档登记、规范化、稳定切片（FR-DOC-*）。"""

from __future__ import annotations

import re

import pytest

from dkws.application.ingest import Ingestor
from dkws.application.parse_doc import (
    DocumentParserService,
    chunk_document,
    document_id_for,
    segment_id_for,
)
from dkws.domain import hashing
from dkws.domain.contracts import specs
from dkws.domain.contracts.base import validate_contract
from dkws.infrastructure.adapters.base import Page, ParsedDocument


@pytest.fixture
def batch_with_docs(ws, tmp_path):
    """接入含 .md 与 .docx 文档的批次。"""
    md_path = tmp_path / "product_manual.md"
    md_path.write_text(
        "# 产品说明手册\n\n"
        "## 第一章 产品概述\n\n"
        "产品A是标准产品，年利率3.5%。\n\n"
        "产品B为高端产品，利率4.2%。\n\n"
        "## 第二章 材料要求\n\n"
        "产品A需要材料M1。\n\n"
        "| 产品 | 材料 |\n"
        "| --- | --- |\n"
        "| 产品A | M1 |\n",
        encoding="utf-8",
    )
    txt_path = tmp_path / "notes.txt"
    txt_path.write_text("内部备注：利率调整通知。\n", encoding="utf-8")
    r = Ingestor(ws).ingest("product", [md_path, txt_path], "batch-docs-1")
    return r


class TestDocumentParser:
    def test_parse_creates_documents_and_segments(self, ws, batch_with_docs):
        r = DocumentParserService(ws).parse("product", batch_with_docs.batch_id)
        assert len(r.document_ids) == 2
        assert r.segment_count >= 4
        run = ws / "02_work" / "product" / f"run={r.run_id}"
        for doc_id in r.document_ids:
            doc_md = run / "documents" / doc_id / "DOCUMENT.md"
            assert doc_md.is_file()
            rv = validate_contract(doc_md.read_text(encoding="utf-8"),
                                   specs.DOCUMENT_SPEC, path="DOCUMENT.md")
            assert rv.ok, rv.errors
            assert rv.front_matter["source_batch_id"] == batch_with_docs.batch_id
            norm = run / "documents" / doc_id / "NORMALIZED.md"
            assert norm.is_file()
            nv = validate_contract(norm.read_text(encoding="utf-8"),
                                   specs.NORMALIZED_SPEC, path="NORMALIZED.md")
            assert nv.ok, nv.errors

    def test_segments_contract_and_links(self, ws, batch_with_docs):
        r = DocumentParserService(ws).parse("product", batch_with_docs.batch_id)
        run = ws / "02_work" / "product" / f"run={r.run_id}"
        seg_files = sorted((run / "segments").rglob("*.md"))
        assert len(seg_files) == r.segment_count
        ids_seen = []
        for sf in seg_files:
            rv = validate_contract(sf.read_text(encoding="utf-8"),
                                   specs.SEGMENT_SPEC, path=str(sf))
            assert rv.ok, rv.errors
            fm = rv.front_matter
            ids_seen.append(fm["segment_id"])
            # 内容哈希与 ## 原文 一致
            body = rv.body
            m = re.search(r"## 原文\n\n(.*?)(?:\n\n## 解析注记|\Z)", body, re.S)
            assert m, "缺少 ## 原文"
            content = m.group(1).rstrip()
            assert fm["content_sha256"] == hashing.md_semantic_sha256(content)
        assert len(set(ids_seen)) == len(ids_seen)

    def test_segment_id_stable(self):
        sid1 = segment_id_for("DOC-001", ["产品说明手册"], "PARAGRAPH", "产品A是标准产品。")
        sid2 = segment_id_for("DOC-001", ["产品说明手册"], "PARAGRAPH", "产品A是标准产品。")
        assert sid1 == sid2
        sid3 = segment_id_for("DOC-001", ["产品说明手册"], "PARAGRAPH", "产品A是标准产品。改")
        assert sid1 != sid3

    def test_chunk_stable_across_runs(self, ws, batch_with_docs):
        svc = DocumentParserService(ws)
        r1 = svc.parse("product", batch_with_docs.batch_id, idempotency_key="run-A")
        run1 = ws / "02_work" / "product" / f"run={r1.run_id}"
        ids1 = sorted(sf.name for sf in (run1 / "segments").rglob("*.md"))
        # 新 run（不同幂等键）片段 ID 必须一致（FR-DOC-003）
        r2 = svc.parse("product", batch_with_docs.batch_id, idempotency_key="run-B")
        run2 = ws / "02_work" / "product" / f"run={r2.run_id}"
        ids2 = sorted(sf.name for sf in (run2 / "segments").rglob("*.md"))
        assert r2.run_id != r1.run_id
        assert ids1 == ids2

    def test_document_id_stable(self):
        assert document_id_for("BATCH-001", "a.md") == document_id_for("BATCH-001", "a.md")
        assert document_id_for("BATCH-001", "a.md") != document_id_for("BATCH-001", "b.md")


class TestChunker:
    def test_heading_and_paragraph_types(self):
        parsed = ParsedDocument(
            title="t", pages=[Page(number=1, text="# 标题1\n\n段落A。\n\n## 小节\n\n段落B。")],
            parser_id="test", parser_version="1.0.0")
        segs = chunk_document(parsed, "DOC-001")
        types = [s.segment_type for s in segs]
        assert "TITLE" in types and "PARAGRAPH" in types
        assert [s for s in segs if s.segment_type == "TITLE"][0].content == "标题1"
        assert [s for s in segs if s.segment_type == "PARAGRAPH"][0].content == "段落A。"

    def test_sequence_and_links(self):
        parsed = ParsedDocument(
            title="t", pages=[Page(number=1, text="# A\n\np1\n\np2\n\np3")],
            parser_id="test", parser_version="1.0.0")
        segs = chunk_document(parsed, "DOC-001")
        assert [s.sequence for s in segs] == list(range(1, len(segs) + 1))
        assert segs[0].next_segment_id == segs[1].segment_id
        assert segs[-1].next_segment_id is None
        assert segs[0].previous_segment_id is None

    def test_table_segments(self):
        parsed = ParsedDocument(
            title="t", pages=[Page(number=1, text="# T\n\n| a | b |\n| 1 | 2 |")],
            parser_id="test", parser_version="1.0.0")
        segs = chunk_document(parsed, "DOC-001")
        assert any(s.segment_type == "TABLE" for s in segs)
