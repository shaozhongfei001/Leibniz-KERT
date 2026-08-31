"""实体/关系查询性能基准（NFR-005）。

测试场景：
- KnowledgeService.data_query：100 / 1K / 10K 行
- KnowledgeService.get_entity：100 / 1K / 10K 行
- KnowledgeService.graph（内存 BFS）：100 / 1K / 10K 行
- KnowledgeService.search（全文检索）：100 / 1K / 10K 行
- KnowledgeService.evaluate_rule：100 / 1K / 10K 行

约束：
- 使用 time.perf_counter 手动计时
- 不依赖 pytest-benchmark
- 使用确定性适配器，不调用真实 LLM
- 每个测试记录：操作名、数据规模、耗时(ms)、是否在合理阈值内
"""

from __future__ import annotations

import time
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from dkws.application.services import KnowledgeService


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


# ---------- benchmarks ----------

SIZES = [100, 1_000, 10_000]

DATA_QUERY_THRESHOLD_MS = 500   # data_query 10K 行 < 500ms
GET_ENTITY_THRESHOLD_MS = 200   # get_entity 10K 行 < 200ms
GRAPH_THRESHOLD_MS = 1000       # graph 10K 行 < 1000ms
SEARCH_THRESHOLD_MS = 1000      # search 10K 行 < 1000ms
RULE_THRESHOLD_MS = 500         # evaluate_rule 50 条规则 < 500ms
MIN_THRESHOLD_MS = 50           # 最小阈值（含 I/O 固定开销）


@pytest.mark.parametrize("n", SIZES, ids=lambda n: f"{n}_rows")
def test_data_query_benchmark(tmp_path: Path, n: int) -> None:
    """KnowledgeService.data_query 性能基准。"""
    ws = _setup_workspace(tmp_path, n)
    svc = KnowledgeService(ws, SERVICE, VERSION)

    t0 = time.perf_counter()
    result = svc.data_query("entities", limit=100)
    elapsed_ms = (time.perf_counter() - t0) * 1000

    assert result.data["count"] <= 100
    threshold = max(MIN_THRESHOLD_MS, DATA_QUERY_THRESHOLD_MS * (n / 10_000))
    assert elapsed_ms < threshold, (
        f"data_query {n} rows: {elapsed_ms:.1f}ms > {threshold:.0f}ms threshold"
    )


@pytest.mark.parametrize("n", SIZES, ids=lambda n: f"{n}_rows")
def test_data_query_with_filter_benchmark(tmp_path: Path, n: int) -> None:
    """KnowledgeService.data_query 带过滤条件性能基准。"""
    ws = _setup_workspace(tmp_path, n)
    svc = KnowledgeService(ws, SERVICE, VERSION)

    t0 = time.perf_counter()
    result = svc.data_query("entities", where={"entity_type": "PRODUCT"}, limit=100)
    elapsed_ms = (time.perf_counter() - t0) * 1000

    assert result.data["count"] > 0
    threshold = max(MIN_THRESHOLD_MS, DATA_QUERY_THRESHOLD_MS * (n / 10_000))
    assert elapsed_ms < threshold, (
        f"data_query_with_filter {n} rows: {elapsed_ms:.1f}ms > {threshold:.0f}ms threshold"
    )


@pytest.mark.parametrize("n", SIZES, ids=lambda n: f"{n}_rows")
def test_get_entity_benchmark(tmp_path: Path, n: int) -> None:
    """KnowledgeService.get_entity 性能基准。"""
    ws = _setup_workspace(tmp_path, n)
    svc = KnowledgeService(ws, SERVICE, VERSION)

    target_id = f"ENT-{n // 2:06d}"

    t0 = time.perf_counter()
    result = svc.get_entity(target_id)
    elapsed_ms = (time.perf_counter() - t0) * 1000

    assert result.data["entity"]["entity_id"] == target_id
    threshold = max(MIN_THRESHOLD_MS, GET_ENTITY_THRESHOLD_MS * (n / 10_000))
    assert elapsed_ms < threshold, (
        f"get_entity {n} rows: {elapsed_ms:.1f}ms > {threshold:.0f}ms threshold"
    )


@pytest.mark.parametrize("n", SIZES, ids=lambda n: f"{n}_rows")
def test_graph_benchmark(tmp_path: Path, n: int) -> None:
    """KnowledgeService.graph（内存 BFS）性能基准。"""
    ws = _setup_workspace(tmp_path, n)
    svc = KnowledgeService(ws, SERVICE, VERSION)

    start_id = "ENT-000000"

    t0 = time.perf_counter()
    result = svc.graph([start_id], max_depth=2, max_nodes=50)
    elapsed_ms = (time.perf_counter() - t0) * 1000

    assert result.data["node_count"] > 0
    threshold = max(MIN_THRESHOLD_MS, GRAPH_THRESHOLD_MS * (n / 10_000))
    assert elapsed_ms < threshold, (
        f"graph {n} rows: {elapsed_ms:.1f}ms > {threshold:.0f}ms threshold"
    )


@pytest.mark.parametrize("n", SIZES, ids=lambda n: f"{n}_rows")
def test_search_fulltext_benchmark(tmp_path: Path, n: int) -> None:
    """KnowledgeService.search 全文检索性能基准。"""
    ws = _setup_workspace(tmp_path, n)
    svc = KnowledgeService(ws, SERVICE, VERSION)

    t0 = time.perf_counter()
    result = svc.search("产品", mode="FULLTEXT", top_k=10)
    elapsed_ms = (time.perf_counter() - t0) * 1000

    # 全文检索可能无命中（取决于分词），仅检查不抛异常
    assert "hits" in result.data
    threshold = max(MIN_THRESHOLD_MS, SEARCH_THRESHOLD_MS * (n / 10_000))
    assert elapsed_ms < threshold, (
        f"search_fulltext {n} rows: {elapsed_ms:.1f}ms > {threshold:.0f}ms threshold"
    )


def test_evaluate_rule_benchmark(tmp_path: Path) -> None:
    """KnowledgeService.evaluate_rule 性能基准（50 条规则）。"""
    ws = _setup_workspace(tmp_path, n_entities=100, n_rules=50)
    svc = KnowledgeService(ws, SERVICE, VERSION)

    facts = {"customer_type": "VIP", "product_category": "LOAN"}

    t0 = time.perf_counter()
    result = svc.evaluate_rule(facts=facts)
    elapsed_ms = (time.perf_counter() - t0) * 1000

    assert "matched_rules" in result.data
    assert elapsed_ms < RULE_THRESHOLD_MS, (
        f"evaluate_rule 50 rules: {elapsed_ms:.1f}ms > {RULE_THRESHOLD_MS}ms threshold"
    )


@pytest.mark.parametrize("n", SIZES, ids=lambda n: f"{n}_rows")
def test_entities_list_benchmark(tmp_path: Path, n: int) -> None:
    """KnowledgeService.entities 全量列表性能基准。"""
    ws = _setup_workspace(tmp_path, n)
    svc = KnowledgeService(ws, SERVICE, VERSION)

    t0 = time.perf_counter()
    rows = svc.entities()
    elapsed_ms = (time.perf_counter() - t0) * 1000

    assert len(rows) == n
    threshold = max(MIN_THRESHOLD_MS, DATA_QUERY_THRESHOLD_MS * (n / 10_000))
    assert elapsed_ms < threshold, (
        f"entities_list {n} rows: {elapsed_ms:.1f}ms > {threshold:.0f}ms threshold"
    )


@pytest.mark.parametrize("n", SIZES, ids=lambda n: f"{n}_rows")
def test_relations_list_benchmark(tmp_path: Path, n: int) -> None:
    """KnowledgeService.relations 全量列表性能基准。"""
    ws = _setup_workspace(tmp_path, n)
    svc = KnowledgeService(ws, SERVICE, VERSION)

    t0 = time.perf_counter()
    rows = svc.relations()
    elapsed_ms = (time.perf_counter() - t0) * 1000

    assert len(rows) == n
    threshold = max(MIN_THRESHOLD_MS, DATA_QUERY_THRESHOLD_MS * (n / 10_000))
    assert elapsed_ms < threshold, (
        f"relations_list {n} rows: {elapsed_ms:.1f}ms > {threshold:.0f}ms threshold"
    )
