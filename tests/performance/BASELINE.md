# 性能基线报告 — Leibniz-KERT / DKWS

> 生成时间：2026-08-28
> 环境：Linux / Python 3.10.12 / pytest 9.1.1
> 测试总耗时：~8s（CI 友好，< 60s）

## 1. NFR 映射

| NFR | 要求 | 状态 |
|-----|------|------|
| NFR-005 | 性能基准：Parquet 读写 / 查询延迟 | PASS |
| NFR-006 | 容量基准：10K 行数据集可处理 | PASS |
| NFR-007 | 并发基准：多线程锁 / SQLite 并发写入 | PASS |

## 2. Parquet 读写性能

| 操作 | 行数 | 耗时(ms) | 阈值(ms) | 结果 |
|------|------|----------|----------|------|
| write_parquet | 100 | 0.9 | 50 | PASS |
| write_parquet | 1,000 | 1.2 | 50 | PASS |
| write_parquet | 10,000 | 8.0 | 500 | PASS |
| read_parquet | 100 | 30.1 | 50 | PASS |
| read_parquet | 1,000 | 5.2 | 50 | PASS |
| read_parquet | 10,000 | 30.4 | 200 | PASS |
| logical_hash | 100 | 0.8 | 50 | PASS |
| logical_hash | 1,000 | 5.1 | 50 | PASS |
| logical_hash | 10,000 | 49.9 | 300 | PASS |

**结论**：Parquet zstd 压缩写入在 10K 行时仅 8ms，读取 30ms，逻辑哈希 50ms。小数据集（100 行）因 I/O 固定开销约 30ms，属正常范围。

## 3. 并发锁性能

| 操作 | 规模 | 耗时(ms) | 阈值(ms) | 结果 |
|------|------|----------|----------|------|
| WorkspaceLock 单线程平均 | 50 次 | 0.1 | 10 | PASS |
| WorkspaceLock 单线程最大 | 50 次 | 0.5 | 50 | PASS |
| WorkspaceLock 多线程并发 scope | 10 线程×10 次 | <2,000 | 2,000 | PASS |
| WorkspaceLock 同 scope 顺序 | 20 次 | <10 | 10 | PASS |

**结论**：WorkspaceLock 基于 O_EXCL 原子创建，单次 acquire+release 约 0.1ms，满足并发场景需求。

## 4. RuntimeStore 并发性能

| 操作 | 规模 | 耗时(ms) | 阈值(ms) | 结果 |
|------|------|----------|----------|------|
| 写入 100 条 idempotency | 100 条 | 1,364 | 3,000 | PASS |
| 读取 100 条 idempotency | 100 条 | 18.6 | 500 | PASS |
| 创建 50 个 Job | 50 条 | 644 | 1,000 | PASS |
| 领取 50 个 Job | 50 条 | 656 | 1,000 | PASS |
| Job 生命周期 create→claim→complete | 50 条 | 各 <20ms/op | 20 | PASS |

**结论**：SQLite WAL 模式下并发写入性能良好。100 条 idempotency 写入约 1.4s（含 SQLite 事务开销），读取 18.6ms。Job 生命周期各操作平均 <20ms。

## 5. 知识查询性能

| 操作 | 行数 | 耗时(ms) | 阈值(ms) | 结果 |
|------|------|----------|----------|------|
| data_query | 100 | 2.4 | 50 | PASS |
| data_query | 1,000 | 3.1 | 50 | PASS |
| data_query | 10,000 | 17.7 | 500 | PASS |
| data_query (带过滤) | 100 | <50 | 50 | PASS |
| data_query (带过滤) | 1,000 | <50 | 50 | PASS |
| data_query (带过滤) | 10,000 | <500 | 500 | PASS |
| get_entity | 100 | 3.2 | 50 | PASS |
| get_entity | 1,000 | 7.8 | 50 | PASS |
| get_entity | 10,000 | 50.1 | 200 | PASS |
| graph (BFS) | 100 | 4.9 | 50 | PASS |
| graph (BFS) | 1,000 | 5.9 | 100 | PASS |
| graph (BFS) | 10,000 | 55.9 | 1,000 | PASS |
| search (全文) | 100 | 3.2 | 50 | PASS |
| search (全文) | 1,000 | 5.6 | 100 | PASS |
| search (全文) | 10,000 | 41.7 | 1,000 | PASS |
| evaluate_rule | 50 条规则 | <500 | 500 | PASS |
| entities 全量列表 | 100 | 1.4 | 50 | PASS |
| entities 全量列表 | 1,000 | 2.3 | 50 | PASS |
| entities 全量列表 | 10,000 | 72.1 | 500 | PASS |
| relations 全量列表 | 100 | 1.1 | 50 | PASS |
| relations 全量列表 | 1,000 | 1.9 | 50 | PASS |
| relations 全量列表 | 10,000 | 14.2 | 500 | PASS |

**结论**：所有查询操作在 10K 行数据集下均满足阈值要求。`get_entity` 和 `entities` 全量列表在 10K 行时约 50-72ms，主要瓶颈是 Parquet → PyList 全量反序列化。

## 6. 性能瓶颈与优化建议

### 6.1 当前瓶颈

1. **get_entity 线性扫描**：当前 `get_entity` 通过 `to_pylist()` 全量反序列化后线性查找，10K 行约 50ms。数据量增长到 100K+ 后将成为瓶颈。
2. **entities 全量列表**：同上，全量反序列化是主要开销。
3. **RuntimeStore 首次写入**：100 条 idempotency 写入约 1.4s，主要来自 SQLite migration 和 WAL 初始化。

### 6.2 优化建议

| 优先级 | 优化项 | 预期收益 | 复杂度 |
|--------|--------|----------|--------|
| P1 | `get_entity` 改用 PyArrow `filter` 谓词下推 | 10K 行 < 10ms | 低 |
| P1 | `data_query` 改用 PyArrow `filter` 替代 Python 列表推导 | 10K 行 < 5ms | 低 |
| P2 | `entities`/`relations` 全量列表增加分页参数 | 减少单次内存占用 | 低 |
| P2 | RuntimeStore 批量写入接口（`remember_batch`） | 100 条 < 200ms | 中 |
| P3 | 引入 Parquet 行组索引（row group index） | 100K+ 行随机读 < 5ms | 高 |
| P3 | Kùzu 图数据库替代内存 BFS | 10K+ 节点图查询 < 50ms | 高 |

## 7. 测试文件清单

| 文件 | 描述 | 测试数 |
|------|------|--------|
| `tests/performance/__init__.py` | 包初始化 | - |
| `tests/performance/test_parquet_benchmark.py` | Parquet 读写/哈希基准 | 15 |
| `tests/performance/test_concurrency_benchmark.py` | 并发锁/SQLite 基准 | 7 |
| `tests/performance/test_query_benchmark.py` | 知识查询基准 | 22 |
| **合计** | | **44** |

## 8. 运行方式

```bash
PYTHONPATH=src python -m pytest tests/performance/ -q
```
