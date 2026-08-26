# 评估：SQLite 图谱底座的功能便利性（排除规格冲突后的纯技术视角）

> 日期：2026-08-21
> 前置：本文**假设不存在规格约束**，仅评估 SQLite 相对当前文件化图谱（Parquet + 内存邻接 BFS，`application/services.py: graph()`）的功能便利性。
> 规格冲突与决策路径见 `docs/evaluation-sqlite-graph-base.md`（结论：默认不引入，除非受控变更或内存加速层）。
> 演示：`:memory:` SQLite 从 demo_workspace 图谱（3 节点/1 边）加载，真实输出见文末附录。

## 1. 结论速览

| 查询类型 | 当前内存 BFS | SQLite | 便利性提升 |
|---|---|---|---|
| 一跳邻居 | ✅ 原生 | ✅ 原生 | 无 |
| 有限 N 跳（N≤3 硬上限） | ✅ 但 depth≤3 写死 | ✅ 任意深度参数化 | **明显** |
| 传递闭包 / 不限深度可达 | ❌ 需手写循环扩展 | ✅ `WITH RECURSIVE` 一行 | **显著** |
| 路径枚举（含路径字符串） | ❌ 需手写回溯 | ✅ 递归 CTE 带 path 列 | **显著** |
| 最短路径 / 最少跳 | ❌ 手写 BFS 层序 | ✅ 递归 + `MIN(depth)` | **显著** |
| 属性/类型/时间过滤 | ⚠️ 全量遍历过滤 | ✅ 索引 + `WHERE` | **明显** |
| 复合查询（图+声明+数据集） | ❌ 应用层多表拼装 | ✅ `JOIN` | **显著** |
| 聚合（度分布/中心性） | ❌ 手写计数 | ✅ `GROUP BY` | **显著** |
| 排序 / 分页 | ⚠️ 应用层 | ✅ `ORDER BY/LIMIT` 走索引 | 明显 |
| 双向/多关系类型组合 | ⚠️ 需预建多邻接表 | ✅ 边表 + 谓词 | 明显 |

**总评：SQLite 的便利性集中在"图查询表达力"——递归/闭包/路径/复合查询用声明式 SQL 表达，而当前内存实现每类都要手写遍历逻辑；一跳邻居这类简单场景差异不大。**

## 2. 逐类对比（含 SQL 示例）

### 2.1 传递闭包 / 不限深度可达（当前实现做不到或需大改）

当前 `graph()` 的 `max_depth` 硬上限 3（超过抛错），实现不定深度需扩展为迭代式 BFS 直到无新节点（应用层 20+ 行 + 防环）。

SQLite 一行（演示真实输出）：

```sql
WITH RECURSIVE reach(src, tgt, depth) AS (
  SELECT src, tgt, 1 FROM relations WHERE src = :start
  UNION
  SELECT r.src, r.tgt, reach.depth + 1
    FROM relations r JOIN reach ON r.src = reach.tgt
) SELECT DISTINCT tgt, MIN(depth) FROM reach GROUP BY tgt ORDER BY 2;
-- 输出: [('ENT-NOBN4474EWU5', 1)]
```

### 2.2 路径枚举（当前需手写回溯/记录前驱）

```sql
WITH RECURSIVE paths(src, tgt, path, depth) AS (
  SELECT src, tgt, src || '->' || tgt, 1 FROM relations WHERE src = :start
  UNION ALL
  SELECT r.src, r.tgt, paths.path || '->' || r.tgt, paths.depth + 1
    FROM relations r JOIN paths ON r.src = paths.tgt
  WHERE paths.depth < :max_depth
) SELECT path FROM paths ORDER BY depth;
-- 输出: [('ENT-4HGACCAQZHAH->ENT-NOBN4474EWU5')]
```

### 2.3 复合查询：图 + 声明 + 属性 一次返回（当前需多次读表 + 应用层 join）

```sql
SELECT e.name, r.rel, t.name, s.pred, s.val
FROM relations r
JOIN entities e ON e.eid = r.src
JOIN entities t ON t.eid = r.tgt
LEFT JOIN statements s ON s.subj = r.src
WHERE r.rel = 'REQUIRES';
-- 输出: [('产品A', 'REQUIRES', '材料M1', NULL, NULL)]
```

当前实现要分别读 entities/relations/statements 三个 parquet → `to_pylist` → 内存三表 join → 过滤——约 30-50 行代码 vs SQL 5 行。

### 2.4 聚合与统计（当前需手写计数）

```sql
-- 出度 TOP
SELECT src, COUNT(*) AS c FROM relations GROUP BY src ORDER BY c DESC LIMIT 3;
-- 每节点入/出度、按关系类型计数、按实体类型统计，均为 GROUP BY 一行
```

### 2.5 性能（非便利性，附带说明）

- 索引：`idx_rel_src/tgt`（B+Tree）使邻居/递归 JOIN 走索引，10 万边场景远优于每次全量 `to_pylist`；
- 时间过滤（`effective_from/to`）：`WHERE effective_from <= :as_of AND effective_to >= :as_of` 走索引；
- 但演示/当前量级（NFR-005：1 万实体一跳 P95≤1s）下，内存 BFS 已达标，SQLite 的索引优势在更大图才显性。

## 3. 即使不考虑规格，SQLite 也需付出的成本

| 成本 | 说明 |
|---|---|
| Schema 与同步 | 需定义节点/边表、从投影构建（`build-projection` 阶段生成 `graph.db`），投影变更需重建 |
| 可重建性 | `graph.db` 必须纳入"删库→从 Parquet 重建"测试，否则成为新事实源/断链点 |
| 溯源字段 | 边表必须保留 `relation_id/statement_id` 等证据引用，SQL 结果才可回传溯源（§15.5） |
| 多写者 | 图谱若允许写，SQLite 单写锁 + 外部锁协调（规格默认单写者，代价小） |
| 版本/迁移 | 图谱 schema 变更需版本化；与 `04_serve` 版本目录对齐（`graph.db` 按版本存放） |

## 4. 结论

1. **便利性确凿**：SQLite 把"图查询表达力"从"每类手写遍历"变成"声明式 SQL"——传递闭包、路径枚举、复合 JOIN、聚合统计的提升是**实质性的**（演示已证明 4 类查询各 1 条 SQL 完成）。
2. **非万能**：一跳邻居、简单 BFS 与当前实现差异不大；图算法（最短加权路径、PageRank 等）SQLite 也不比手写省多少。
3. **代价可控**：即便不考虑规格冲突，引入需同步承担 schema/重建/溯源/版本四件事——工作量约 1-2 天（构建器 + 重建测试 + 契约更新）。
4. **建议**：若业务方的真实诉求是"递归/闭包/复合查询"，SQLite（或内存 SQLite）是便利的；若只是现有一跳查询，当前实现已够。**规格冲突仍是一票否决项**——落地须走 `evaluation-sqlite-graph-base.md` 的方案 B（受控变更）或 C（:memory: 加速层）。

## 附录：演示真实输出（:memory: SQLite，demo_workspace 图谱 3 节点/1 边）

```
=== 1) 递归闭包 === 可达节点: [('ENT-NOBN4474EWU5', 1)]
=== 2) 路径枚举 === 路径示例: ['ENT-4HGACCAQZHAH->ENT-NOBN4474EWU5']
=== 3) 聚合：出度 TOP === [('ENT-4HGACCAQZHAH', 1)]
=== 4) 复合查询 === [('产品A', 'REQUIRES', '材料M1', None, None)]
```
