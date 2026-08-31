"""text_parser 模块单元测试：TXT/CSV 解析。"""

from __future__ import annotations


import pytest

from dkws.infrastructure.adapters.text_parser import (
    CsvTextParserAdapter,
    TextParserAdapter,
)


@pytest.fixture
def txt_file(tmp_path):
    p = tmp_path / "sample.txt"
    p.write_text("Hello World\nLine 2", encoding="utf-8")
    return p


@pytest.fixture
def csv_file(tmp_path):
    p = tmp_path / "data.csv"
    p.write_text("name,age\nalice,30\nbob,25\n", encoding="utf-8")
    return p


# ---------- TextParserAdapter ----------

class TestTextParserAdapter:
    def test_parse(self, txt_file):
        a = TextParserAdapter()
        doc = a.parse(txt_file)
        assert doc.title == "sample"
        assert len(doc.pages) == 1
        assert "Hello World" in doc.pages[0].text
        assert doc.parser_id == "text_parser"
        assert doc.parser_version == "1.0.0"

    def test_full_text(self, txt_file):
        a = TextParserAdapter()
        doc = a.parse(txt_file)
        ft = doc.full_text()
        assert "page:1" in ft
        assert "Hello World" in ft

    def test_empty_file(self, tmp_path):
        p = tmp_path / "empty.txt"
        p.write_text("", encoding="utf-8")
        a = TextParserAdapter()
        doc = a.parse(p)
        assert doc.pages[0].text == ""


# ---------- CsvTextParserAdapter ----------

class TestCsvTextParserAdapter:
    def test_parse(self, csv_file):
        a = CsvTextParserAdapter()
        doc = a.parse(csv_file)
        assert doc.title == "data"
        assert doc.parser_id == "csv_parser"
        assert len(doc.pages) == 1
        assert doc.pages[0].tables
        rows = doc.pages[0].tables[0]
        assert rows[0] == ["name", "age"]
        assert len(rows) == 3  # header + 2 data rows

    def test_warning(self, csv_file):
        a = CsvTextParserAdapter()
        doc = a.parse(csv_file)
        assert any("CSV" in w for w in doc.warnings)

    def test_single_column(self, tmp_path):
        p = tmp_path / "single.csv"
        p.write_text("val\n1\n2\n", encoding="utf-8")
        a = CsvTextParserAdapter()
        doc = a.parse(p)
        rows = doc.pages[0].tables[0]
        assert rows[0] == ["val"]
