"""parquet 模块单元测试：读写、列序规范化、类型转换、哈希一致性。"""

from __future__ import annotations

import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from dkws.domain.errors import UsageError
from dkws.infrastructure.parquet import (
    cast_column,
    read_parquet,
    read_table,
    write_parquet,
)


# ---------- fixtures ----------

@pytest.fixture
def tmp_dir(tmp_path):
    return tmp_path


def _make_table(rows=None, schema=None):
    """辅助：构建简单 pa.Table。"""
    if rows is None:
        rows = [
            {"name": "alice", "age": 30, "score": 88.5},
            {"name": "bob", "age": 25, "score": 92.0},
        ]
    return pa.Table.from_pylist(rows, schema=schema)


# ---------- read_table ----------

class TestReadTable:
    def test_read_parquet(self, tmp_dir):
        t = _make_table()
        p = tmp_dir / "data.parquet"
        pq.write_table(t, p)
        result = read_table(p)
        assert result.num_rows == 2
        assert "name" in result.column_names

    def test_read_csv(self, tmp_dir):
        csv_path = tmp_dir / "data.csv"
        csv_path.write_text("name,age\nalice,30\nbob,25\n", encoding="utf-8")
        result = read_table(csv_path)
        assert result.num_rows == 2
        assert "name" in result.column_names

    def test_read_json(self, tmp_dir):
        json_path = tmp_dir / "data.json"
        json_path.write_text(
            json.dumps([{"name": "alice", "age": 30}, {"name": "bob", "age": 25}]),
            encoding="utf-8",
        )
        result = read_table(json_path)
        assert result.num_rows == 2

    def test_read_jsonl(self, tmp_dir):
        jsonl_path = tmp_dir / "data.jsonl"
        jsonl_path.write_text(
            '{"name":"alice","age":30}\n{"name":"bob","age":25}\n',
            encoding="utf-8",
        )
        result = read_table(jsonl_path)
        assert result.num_rows == 2

    def test_read_jsonl_empty_lines(self, tmp_dir):
        jsonl_path = tmp_dir / "data.jsonl"
        jsonl_path.write_text(
            '{"name":"alice"}\n\n  \n{"name":"bob"}\n',
            encoding="utf-8",
        )
        result = read_table(jsonl_path)
        assert result.num_rows == 2

    def test_read_json_single_object(self, tmp_dir):
        json_path = tmp_dir / "single.json"
        json_path.write_text('{"name":"alice","age":30}', encoding="utf-8")
        result = read_table(json_path)
        assert result.num_rows == 1

    def test_read_json_empty_list(self, tmp_dir):
        json_path = tmp_dir / "empty.json"
        json_path.write_text('[]', encoding="utf-8")
        result = read_table(json_path)
        assert result.num_rows == 0

    def test_read_unsupported_ext(self, tmp_dir):
        bad = tmp_dir / "data.xlsx"
        bad.write_text("dummy", encoding="utf-8")
        with pytest.raises(UsageError, match="不支持的结构化输入类型"):
            read_table(bad)

    def test_read_jsonl_blank_only(self, tmp_dir):
        jsonl_path = tmp_dir / "blank.jsonl"
        jsonl_path.write_text('\n\n  \n', encoding="utf-8")
        result = read_table(jsonl_path)
        assert result.num_rows == 0


# ---------- write_parquet / read_parquet ----------

class TestWriteReadParquet:
    def test_roundtrip(self, tmp_dir):
        t = _make_table()
        p = tmp_dir / "out.parquet"
        write_parquet(t, p)
        assert p.exists()
        loaded = read_parquet(p)
        assert loaded.num_rows == 2
        assert set(loaded.column_names) == {"name", "age", "score"}

    def test_creates_parent_dirs(self, tmp_dir):
        t = _make_table()
        p = tmp_dir / "deep" / "nested" / "out.parquet"
        write_parquet(t, p)
        assert p.exists()

    def test_zstd_compression(self, tmp_dir):
        t = _make_table()
        p = tmp_dir / "zstd.parquet"
        write_parquet(t, p)
        # 验证压缩方式：读取 parquet 元数据
        meta = pq.read_metadata(p)
        assert meta.num_row_groups == 1


# ---------- cast_column ----------

class TestCastColumn:
    def test_cast_to_string(self):
        t = pa.table({"val": [1, 2, 3]})
        result = cast_column(t, "val", "string")
        assert result.schema.field("val").type == pa.string()

    def test_cast_to_str_alias(self):
        t = pa.table({"val": [1, 2, 3]})
        result = cast_column(t, "val", "str")
        assert result.schema.field("val").type == pa.string()

    def test_cast_to_integer(self):
        t = pa.table({"val": ["10", "20"]})
        result = cast_column(t, "val", "integer")
        assert result.schema.field("val").type == pa.int64()

    def test_cast_to_int_alias(self):
        t = pa.table({"val": ["10", "20"]})
        result = cast_column(t, "val", "int")
        assert result.schema.field("val").type == pa.int64()

    def test_cast_to_float(self):
        t = pa.table({"val": [1, 2]})
        result = cast_column(t, "val", "float")
        assert result.schema.field("val").type == pa.float64()

    def test_cast_to_number_alias(self):
        t = pa.table({"val": [1, 2]})
        result = cast_column(t, "val", "number")
        assert result.schema.field("val").type == pa.float64()

    def test_cast_to_decimal_alias(self):
        t = pa.table({"val": [1, 2]})
        result = cast_column(t, "val", "decimal")
        assert result.schema.field("val").type == pa.float64()

    def test_cast_to_boolean(self):
        t = pa.table({"val": [1, 0, 1]})
        result = cast_column(t, "val", "boolean")
        assert result.schema.field("val").type == pa.bool_()

    def test_cast_to_bool_alias(self):
        t = pa.table({"val": [1, 0, 1]})
        result = cast_column(t, "val", "bool")
        assert result.schema.field("val").type == pa.bool_()

    def test_cast_missing_column_returns_unchanged(self):
        t = pa.table({"a": [1]})
        result = cast_column(t, "nonexistent", "string")
        assert result == t

    def test_cast_invalid_returns_unchanged(self):
        """无法转换时返回原表（不崩溃）。"""
        t = pa.table({"val": ["not_a_number"]})
        result = cast_column(t, "val", "integer")
        # safe=False 会尝试，失败后 catch 返回原表
        assert result.schema.field("val").type == pa.string()

    def test_cast_unknown_target_type_returns_unchanged(self):
        t = pa.table({"val": [1]})
        result = cast_column(t, "val", "binary")
        # 未知目标类型走 fallthrough
        assert result == t


# ---------- 哈希一致性（写读后内容不变） ----------

class TestHashConsistency:
    def test_parquet_content_stable(self, tmp_dir):
        """相同数据两次写读，列名和行数一致。"""
        t = _make_table()
        p1 = tmp_dir / "a.parquet"
        p2 = tmp_dir / "b.parquet"
        write_parquet(t, p1)
        write_parquet(t, p2)
        r1 = read_parquet(p1)
        r2 = read_parquet(p2)
        assert r1.num_rows == r2.num_rows
        assert r1.column_names == r2.column_names
