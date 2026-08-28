"""Parquet 读写性能基准（NFR-005）。

测试场景：
- write_parquet：100 / 1K / 10K 行
- read_parquet：100 / 1K / 10K 行
- 逻辑哈希计算：100 / 1K / 10K 行

约束：
- 使用 time.perf_counter 手动计时
- 不依赖 pytest-benchmark
- 每个测试记录：操作名、数据规模、耗时(ms)、是否在合理阈值内
"""

from __future__ import annotations

import io
import time
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from dkws.domain.hashing import parquet_logical_hash


# ---------- helpers ----------

def _make_entity_table(n: int) -> pa.Table:
    """生成 n 行实体 Parquet 表。"""
    rows = [
        {
            "entity_id": f"ENT-{i:06d}",
            "entity_type": "PRODUCT" if i % 3 == 0 else "CUSTOMER",
            "name": f"实体_{i}",
            "aliases": [f"别名_{i}_a", f"别名_{i}_b"],
            "description": f"这是第 {i} 个实体的描述文本，用于性能基准测试。",
            "domain": "product_knowledge",
            "status": "ACTIVE",
            "effective_from": "2026-01-01",
            "effective_to": None,
            "source_ids": [f"SRC-{i:04d}"],
            "source_release_id": "1.0.0",
            "asset_version": "1.0",
            "recorded_at": "2026-08-28T00:00:00Z",
        }
        for i in range(n)
    ]
    return pa.Table.from_pylist(rows)


def _make_relation_table(n: int) -> pa.Table:
    """生成 n 行关系 Parquet 表。"""
    rows = [
        {
            "relation_id": f"REL-{i:06d}",
            "source_id": f"ENT-{i:06d}",
            "relation_type": "BELONGS_TO",
            "target_id": f"ENT-{(i + 1) % n:06d}",
            "statement_id": f"STMT-{i:06d}",
            "status": "ACTIVE",
            "effective_from": "2026-01-01",
            "effective_to": None,
            "source_ids": [f"SRC-{i:04d}"],
            "source_release_id": "1.0.0",
            "asset_version": "1.0",
            "recorded_at": "2026-08-28T00:00:00Z",
        }
        for i in range(n)
    ]
    return pa.Table.from_pylist(rows)


# ---------- benchmarks ----------

SIZES = [100, 1_000, 10_000]
WRITE_THRESHOLD_MS = 500  # 单次写入 10K 行 < 500ms
READ_THRESHOLD_MS = 200   # 单次读取 10K 行 < 200ms
READ_MIN_THRESHOLD_MS = 50  # 最小读取阈值（含 I/O 固定开销）
HASH_THRESHOLD_MS = 300   # 逻辑哈希 10K 行 < 300ms


@pytest.mark.parametrize("n", SIZES, ids=lambda n: f"{n}_rows")
def test_write_parquet_benchmark(tmp_path: Path, n: int) -> None:
    """Parquet 写入性能基准。"""
    table = _make_entity_table(n)
    out_file = tmp_path / "entities.parquet"

    t0 = time.perf_counter()
    pq.write_table(table, out_file, compression="zstd")
    elapsed_ms = (time.perf_counter() - t0) * 1000

    threshold = WRITE_THRESHOLD_MS * (n / 10_000) if n < 10_000 else WRITE_THRESHOLD_MS
    assert elapsed_ms < threshold, (
        f"write_parquet {n} rows: {elapsed_ms:.1f}ms > {threshold:.0f}ms threshold"
    )


@pytest.mark.parametrize("n", SIZES, ids=lambda n: f"{n}_rows")
def test_read_parquet_benchmark(tmp_path: Path, n: int) -> None:
    """Parquet 读取性能基准。"""
    table = _make_entity_table(n)
    out_file = tmp_path / "entities.parquet"
    pq.write_table(table, out_file, compression="zstd")

    t0 = time.perf_counter()
    result = pq.read_table(out_file)
    elapsed_ms = (time.perf_counter() - t0) * 1000

    assert result.num_rows == n
    threshold = max(READ_MIN_THRESHOLD_MS, READ_THRESHOLD_MS * (n / 10_000))
    assert elapsed_ms < threshold, (
        f"read_parquet {n} rows: {elapsed_ms:.1f}ms > {threshold:.0f}ms threshold"
    )


@pytest.mark.parametrize("n", SIZES, ids=lambda n: f"{n}_rows")
def test_parquet_logical_hash_benchmark(n: int) -> None:
    """Parquet 逻辑哈希计算性能基准。"""
    table = _make_entity_table(n)

    t0 = time.perf_counter()
    h = parquet_logical_hash(table, key_columns=["entity_id"])
    elapsed_ms = (time.perf_counter() - t0) * 1000

    assert h, "逻辑哈希不应为空"
    threshold = HASH_THRESHOLD_MS * (n / 10_000) if n < 10_000 else HASH_THRESHOLD_MS
    assert elapsed_ms < threshold, (
        f"logical_hash {n} rows: {elapsed_ms:.1f}ms > {threshold:.0f}ms threshold"
    )


@pytest.mark.parametrize("n", SIZES, ids=lambda n: f"{n}_rows")
def test_write_relation_parquet_benchmark(tmp_path: Path, n: int) -> None:
    """关系 Parquet 写入性能基准。"""
    table = _make_relation_table(n)
    out_file = tmp_path / "relations.parquet"

    t0 = time.perf_counter()
    pq.write_table(table, out_file, compression="zstd")
    elapsed_ms = (time.perf_counter() - t0) * 1000

    threshold = WRITE_THRESHOLD_MS * (n / 10_000) if n < 10_000 else WRITE_THRESHOLD_MS
    assert elapsed_ms < threshold, (
        f"write_relation_parquet {n} rows: {elapsed_ms:.1f}ms > {threshold:.0f}ms threshold"
    )


@pytest.mark.parametrize("n", SIZES, ids=lambda n: f"{n}_rows")
def test_in_memory_parquet_roundtrip_benchmark(n: int) -> None:
    """内存 Parquet 序列化/反序列化往返基准。"""
    table = _make_entity_table(n)

    t0 = time.perf_counter()
    buf = io.BytesIO()
    pq.write_table(table, buf, compression="zstd")
    buf.seek(0)
    result = pq.read_table(buf)
    elapsed_ms = (time.perf_counter() - t0) * 1000

    assert result.num_rows == n
    threshold = (WRITE_THRESHOLD_MS + READ_THRESHOLD_MS) * (n / 10_000) if n < 10_000 else (
        WRITE_THRESHOLD_MS + READ_THRESHOLD_MS
    )
    assert elapsed_ms < threshold, (
        f"roundtrip {n} rows: {elapsed_ms:.1f}ms > {threshold:.0f}ms threshold"
    )
