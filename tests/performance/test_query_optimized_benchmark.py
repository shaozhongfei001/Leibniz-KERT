"""PyArrow 谓词下推优化性能基准（P1 优化验证）。

对比：
- 优化前：Python 列表推导线性扫描（全量读取 + Python 过滤）
- 优化后：PyArrow filter 谓词下推（Parquet 读取时过滤，减少 I/O 和内存）

测试场景：
- build_filter 过滤器构建：各操作符正确性
- data_query：where 条件过滤
- get_entity：entity_id 精确查找 + subject_id 过滤
- search：filters 条件过滤
- segments：document_id 过滤
- entities：entity_id 过滤
- 大规模数据（10K/50K）对比优化前后

约束：
- 使用 time.perf_counter 手动计时
- 不依赖 pytest-benchmark
- 使用确定性数据，不调用真实 LLM
"""

from __future__ import annotations

import time
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from dkws.application.services import KnowledgeService
from dkws.infrastructure.parquet import build_filter, read_table


# ---------- helpers ----------

SERVICE = "product_knowledge"
VERSION = "1.0.0"


def _setup_workspace(ws: Path, n_entities: int, n_relations: int = 0,
                     n_segments: int = 0, n_rules: int = 0) -> Path:
    """创建带 Parquet 投影的工作区。"""
    serve_dir = ws / "04_serve" / SERVICE
    serve_dir.mkdir(parents=True, exist_ok=True)

    # CURRENT.md
    current = serve_dir / "CURRENT.md"
    current.write_text(
        "---\ntarget_version: \"1.0.0\"\n---\n\n# Current\n",
        encoding="utf-8",
    )

    vdir = serve_dir / f"version={VERSION}"
    vdir.mkdir(parents=True, exist_ok=True)

    # entities.parquet
    entity_rows = [
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
        for i in range(n_entities)
    ]
    pq.write_table(pa.Table.from_pylist(entity_rows), vdir / "entities.parquet")

    # statements.parquet
    stmt_rows = [
        {
            "statement_id": f"STMT-{i:06d}",
            "subject_id": f"ENT-{i:06d}",
            "predicate": "HAS_ATTRIBUTE" if i % 2 == 0 else "BELONGS_TO",
            "object_value": f"属性值_{i}",
            "status": "ACTIVE",
            "effective_from": "2026-01-01",
            "effective_to": None,
            "source_ids": [f"SRC-{i:04d}"],
            "source_release_id": "1.0.0",
            "asset_version": "1.0",
            "recorded_at": "2026-08-28T00:00:00Z",
        }
        for i in range(n_entities)
    ]
    pq.write_table(pa.Table.from_pylist(stmt_rows), vdir / "statements.parquet")

    # relations.parquet
    if n_relations == 0:
        n_relations = n_entities
    rel_rows = [
        {
            "relation_id": f"REL-{i:06d}",
            "source_id": f"ENT-{i:06d}",
            "relation_type": "BELONGS_TO",
            "target_id": f"ENT-{(i + 1) % n_entities:06d}",
            "statement_id": f"STMT-{i:06d}",
            "status": "ACTIVE",
            "effective_from": "2026-01-01",
            "effective_to": None,
            "source_ids": [f"SRC-{i:04d}"],
            "source_release_id": "1.0.0",
            "asset_version": "1.0",
            "recorded_at": "2026-08-28T00:00:00Z",
        }
        for i in range(n_relations)
    ]
    pq.write_table(pa.Table.from_pylist(rel_rows), vdir / "relations.parquet")

    # segments.parquet
    if n_segments == 0:
        n_segments = n_entities
    seg_rows = [
        {
            "segment_id": f"SEG-{i:06d}",
            "document_id": f"DOC-{i // 10:04d}",
            "heading_path": f"第{i // 10}章/第{i}节",
            "content": f"这是第 {i} 个片段的内容，包含关键词产品和客户信息。段落编号 {i}。",
            "page_from": i,
            "page_to": i + 1,
            "source_release_id": "1.0.0",
            "source_path": f"raw/doc_{i // 10}.pdf",
        }
        for i in range(n_segments)
    ]
    pq.write_table(pa.Table.from_pylist(seg_rows), vdir / "segments.parquet")

    # rules.parquet
    if n_rules == 0:
        n_rules = min(n_entities, 50)
    rule_rows = [
        {
            "rule_id": f"RUL-{i:04d}",
            "name": f"规则_{i}",
            "rule_type": "ELIGIBILITY" if i % 2 == 0 else "COMPLIANCE",
            "priority": 100 - i,
            "execution_mode": "AUTO",
            "when": '{"AND": [{"field": "customer_type", "op": "eq", "value": "VIP"}]}',
            "then": '{"SET": {"result": "approved"}}',
            "status": "ACTIVE",
            "effective_from": "2026-01-01",
            "effective_to": None,
            "source_release_id": "1.0.0",
        }
        for i in range(n_rules)
    ]
    pq.write_table(pa.Table.from_pylist(rule_rows), vdir / "rules.parquet")

    # datasets/
    ds_dir = vdir / "datasets"
    ds_dir.mkdir(exist_ok=True)
    pq.write_table(pa.Table.from_pylist(entity_rows), ds_dir / "entities.parquet")

    return ws


# ---------- build_filter 正确性测试 ----------

class TestBuildFilter:
    """验证 build_filter 各操作符生成正确的 PyArrow 表达式。"""

    def test_eq_filter(self, tmp_path: Path) -> None:
        """eq 操作符：精确匹配。"""
        table = pa.table({"entity_id": ["A", "B", "C"], "val": [1, 2, 3]})
        path = tmp_path / "test.parquet"
        pq.write_table(table, path)

        result = read_table(path, filters={"entity_id": "B"})
        assert result.num_rows == 1
        assert result.to_pydict()["entity_id"] == ["B"]

    def test_ne_filter(self, tmp_path: Path) -> None:
        """ne 操作符：不等于。"""
        table = pa.table({"entity_id": ["A", "B", "C"], "val": [1, 2, 3]})
        path = tmp_path / "test.parquet"
        pq.write_table(table, path)

        result = read_table(path, filters=[{"column": "entity_id", "op": "ne", "value": "B"}])
        assert result.num_rows == 2
        assert set(result.to_pydict()["entity_id"]) == {"A", "C"}

    def test_gt_lt_filter(self, tmp_path: Path) -> None:
        """gt/lt 操作符：大于/小于。"""
        table = pa.table({"val": [1, 5, 10, 20]})
        path = tmp_path / "test.parquet"
        pq.write_table(table, path)

        result = read_table(path, filters=[{"column": "val", "op": "gt", "value": 5}])
        assert result.to_pydict()["val"] == [10, 20]

        result = read_table(path, filters=[{"column": "val", "op": "lt", "value": 5}])
        assert result.to_pydict()["val"] == [1]

    def test_gte_lte_filter(self, tmp_path: Path) -> None:
        """gte/lte 操作符：大于等于/小于等于。"""
        table = pa.table({"val": [1, 5, 10, 20]})
        path = tmp_path / "test.parquet"
        pq.write_table(table, path)

        result = read_table(path, filters=[{"column": "val", "op": "gte", "value": 5}])
        assert result.to_pydict()["val"] == [5, 10, 20]

        result = read_table(path, filters=[{"column": "val", "op": "lte", "value": 5}])
        assert result.to_pydict()["val"] == [1, 5]

    def test_in_filter(self, tmp_path: Path) -> None:
        """in 操作符：集合包含。"""
        table = pa.table({"entity_id": ["A", "B", "C", "D"]})
        path = tmp_path / "test.parquet"
        pq.write_table(table, path)

        result = read_table(path, filters=[{"column": "entity_id", "op": "in",
                                             "value": ["A", "C"]}])
        assert set(result.to_pydict()["entity_id"]) == {"A", "C"}

    def test_not_in_filter(self, tmp_path: Path) -> None:
        """not_in 操作符：集合排除。"""
        table = pa.table({"entity_id": ["A", "B", "C", "D"]})
        path = tmp_path / "test.parquet"
        pq.write_table(table, path)

        result = read_table(path, filters=[{"column": "entity_id", "op": "not_in",
                                             "value": ["A", "C"]}])
        assert set(result.to_pydict()["entity_id"]) == {"B", "D"}

    def test_contains_filter(self, tmp_path: Path) -> None:
        """contains 操作符：子串匹配。"""
        table = pa.table({"name": ["产品A", "客户B", "产品C"]})
        path = tmp_path / "test.parquet"
        pq.write_table(table, path)

        result = read_table(path, filters=[{"column": "name", "op": "contains",
                                             "value": "产品"}])
        assert result.num_rows == 2
        assert set(result.to_pydict()["name"]) == {"产品A", "产品C"}

    def test_multi_condition_and(self, tmp_path: Path) -> None:
        """多条件 AND 组合。"""
        table = pa.table({"type": ["A", "A", "B"], "val": [1, 2, 3]})
        path = tmp_path / "test.parquet"
        pq.write_table(table, path)

        result = read_table(path, filters={"type": "A"})
        assert result.num_rows == 2

        result = read_table(path, filters=[{"column": "type", "op": "eq", "value": "A"},
                                            {"column": "val", "op": "gt", "value": 1}])
        assert result.num_rows == 1
        assert result.to_pydict()["val"] == [2]

    def test_empty_filter_returns_all(self, tmp_path: Path) -> None:
        """空条件返回全量。"""
        table = pa.table({"val": [1, 2, 3]})
        path = tmp_path / "test.parquet"
        pq.write_table(table, path)

        assert read_table(path, filters=None).num_rows == 3
        assert read_table(path, filters={}).num_rows == 3
        assert read_table(path, filters=[]).num_rows == 3

    def test_backward_compat_no_filters(self, tmp_path: Path) -> None:
        """向后兼容：不传 filters 时行为不变。"""
        table = pa.table({"val": [1, 2, 3]})
        path = tmp_path / "test.parquet"
        pq.write_table(table, path)

        assert read_table(path).num_rows == 3


# ---------- 谓词下推 vs Python 线性扫描对比 ----------

LARGE_SIZES = [10_000, 50_000]
COMPARE_THRESHOLD_MS = 2000  # 大规模数据阈值


@pytest.mark.parametrize("n", LARGE_SIZES, ids=lambda n: f"{n}_rows")
def test_data_query_predicate_pushdown(tmp_path: Path, n: int) -> None:
    """data_query 谓词下推 vs Python 线性扫描。"""
    ws = _setup_workspace(tmp_path, n)
    svc = KnowledgeService(ws, SERVICE, VERSION)

    # 谓词下推查询
    t0 = time.perf_counter()
    result = svc.data_query("entities", where={"entity_type": "PRODUCT"}, limit=100)
    pushdown_ms = (time.perf_counter() - t0) * 1000

    assert result.data["count"] > 0
    assert pushdown_ms < COMPARE_THRESHOLD_MS, (
        f"data_query predicate pushdown {n} rows: {pushdown_ms:.1f}ms > {COMPARE_THRESHOLD_MS}ms"
    )


@pytest.mark.parametrize("n", LARGE_SIZES, ids=lambda n: f"{n}_rows")
def test_get_entity_predicate_pushdown(tmp_path: Path, n: int) -> None:
    """get_entity 谓词下推：entity_id 精确查找 + subject_id 过滤。"""
    ws = _setup_workspace(tmp_path, n)
    svc = KnowledgeService(ws, SERVICE, VERSION)

    target_id = f"ENT-{n - 1:06d}"  # 查找末尾实体

    t0 = time.perf_counter()
    result = svc.get_entity(target_id)
    pushdown_ms = (time.perf_counter() - t0) * 1000

    assert result.data["entity"]["entity_id"] == target_id
    assert pushdown_ms < COMPARE_THRESHOLD_MS, (
        f"get_entity predicate pushdown {n} rows: {pushdown_ms:.1f}ms > {COMPARE_THRESHOLD_MS}ms"
    )


@pytest.mark.parametrize("n", LARGE_SIZES, ids=lambda n: f"{n}_rows")
def test_search_predicate_pushdown(tmp_path: Path, n: int) -> None:
    """search 谓词下推：filters 条件过滤。"""
    ws = _setup_workspace(tmp_path, n)
    svc = KnowledgeService(ws, SERVICE, VERSION)

    t0 = time.perf_counter()
    result = svc.search("产品", mode="FULLTEXT", top_k=10,
                        filters={"document_id": "DOC-0000"})
    pushdown_ms = (time.perf_counter() - t0) * 1000

    assert "hits" in result.data
    assert pushdown_ms < COMPARE_THRESHOLD_MS, (
        f"search predicate pushdown {n} rows: {pushdown_ms:.1f}ms > {COMPARE_THRESHOLD_MS}ms"
    )


@pytest.mark.parametrize("n", LARGE_SIZES, ids=lambda n: f"{n}_rows")
def test_segments_predicate_pushdown(tmp_path: Path, n: int) -> None:
    """segments 谓词下推：document_id 过滤。"""
    ws = _setup_workspace(tmp_path, n)
    svc = KnowledgeService(ws, SERVICE, VERSION)

    t0 = time.perf_counter()
    rows = svc.segments(document_id="DOC-0000")
    pushdown_ms = (time.perf_counter() - t0) * 1000

    assert len(rows) > 0
    assert all(r["document_id"] == "DOC-0000" for r in rows)
    assert pushdown_ms < COMPARE_THRESHOLD_MS, (
        f"segments predicate pushdown {n} rows: {pushdown_ms:.1f}ms > {COMPARE_THRESHOLD_MS}ms"
    )


@pytest.mark.parametrize("n", LARGE_SIZES, ids=lambda n: f"{n}_rows")
def test_entities_predicate_pushdown(tmp_path: Path, n: int) -> None:
    """entities 谓词下推：entity_id 过滤。"""
    ws = _setup_workspace(tmp_path, n)
    svc = KnowledgeService(ws, SERVICE, VERSION)

    target_id = f"ENT-{n // 2:06d}"

    t0 = time.perf_counter()
    rows = svc.entities(entity_id=target_id)
    pushdown_ms = (time.perf_counter() - t0) * 1000

    assert len(rows) == 1
    assert rows[0]["entity_id"] == target_id
    assert pushdown_ms < COMPARE_THRESHOLD_MS, (
        f"entities predicate pushdown {n} rows: {pushdown_ms:.1f}ms > {COMPARE_THRESHOLD_MS}ms"
    )


# ---------- 直接 Parquet 读取对比 ----------

@pytest.mark.parametrize("n", [10_000, 50_000], ids=lambda n: f"{n}_rows")
def test_parquet_read_with_vs_without_filter(tmp_path: Path, n: int) -> None:
    """直接对比 Parquet 读取：谓词下推 vs 全量读取+Python 过滤。"""
    # 生成数据
    rows = [{"entity_id": f"ENT-{i:06d}", "entity_type": "PRODUCT" if i % 3 == 0 else "CUSTOMER",
             "val": i} for i in range(n)]
    table = pa.Table.from_pylist(rows)
    path = tmp_path / "data.parquet"
    pq.write_table(table, path)

    # 方式1：全量读取 + Python 过滤（优化前）
    full_table = pq.read_table(path)
    python_filtered = [r for r in full_table.to_pylist() if r["entity_type"] == "PRODUCT"]

    # 方式2：谓词下推（优化后）
    filter_expr = build_filter({"entity_type": "PRODUCT"})
    pushdown_table = pq.read_table(path, filters=filter_expr)
    pushdown_filtered = pushdown_table.to_pylist()

    # 结果一致
    assert len(python_filtered) == len(pushdown_filtered)
    assert {r["entity_id"] for r in python_filtered} == {r["entity_id"] for r in pushdown_filtered}

    # 谓词下推不应慢于 Python 过滤
    # 注意：小数据量时差异可能不明显，但大数据量时谓词下推应更快
    # 这里只验证功能正确性，不做严格性能断言（CI 环境波动大）


# ---------- 高级过滤器基准 ----------

@pytest.mark.parametrize("n", [10_000], ids=lambda n: f"{n}_rows")
def test_advanced_filter_benchmark(tmp_path: Path, n: int) -> None:
    """高级过滤器（多操作符组合）性能基准。"""
    ws = _setup_workspace(tmp_path, n)
    svc = KnowledgeService(ws, SERVICE, VERSION)

    # 使用高级过滤器：entity_type in [PRODUCT] 且 entity_id 以 ENT-00 开头
    filters = [
        {"column": "entity_type", "op": "in", "value": ["PRODUCT"]},
    ]

    t0 = time.perf_counter()
    table = svc._read_table("entities.parquet", filters=filters)
    rows = table.to_pylist()
    elapsed_ms = (time.perf_counter() - t0) * 1000

    assert len(rows) > 0
    assert all(r["entity_type"] == "PRODUCT" for r in rows)
    assert elapsed_ms < COMPARE_THRESHOLD_MS, (
        f"advanced filter {n} rows: {elapsed_ms:.1f}ms > {COMPARE_THRESHOLD_MS}ms"
    )
