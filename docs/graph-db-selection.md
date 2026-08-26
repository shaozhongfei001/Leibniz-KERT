# 轻量图数据库选型调研与推荐（DKWS 知识图谱底座）

> 日期：2026-08-21
> 需求基线：简单、轻量、本地化；图搜索足够简单；**10 万节点以上**即可。
> 方法：桌面调研（候选最新状态/许可/活跃度）+ 本机实测（10 万节点/30 万有向边合成图）。
> 规格提醒：DKWS-SPEC-001 §1.5/§2.2/§6.3/§15.4/ADR-002/§18.5 **禁止持久化数据库**——本报告为选型评估；落地形态必须走受控变更或"可重建投影/内存加速层"（见 §6）。

## 1. 候选清单（嵌入式/本地化，排除服务型）

| 候选 | 类型 | 查询方式 | 持久化 | 许可 | 备注 |
|---|---|---|---|---|---|
| **Kùzu** | 嵌入式属性图 DB（C++/Rust 内核） | **Cypher** | 本地目录（列式），`:memory:` 支持 | MIT | 零基础设施、单进程；pip `kuzu` |
| **Oxigraph** | 嵌入式 RDF 存储（Rust） | SPARQL | 本地文件 | MIT/Apache | RDF/三元组语义；pip `pyoxigraph` |
| **python-igraph** | C 内核内存图库 | Python API（无查询语言） | 需自建序列化 | GPL-2 | 图算法最全、加载极快 |
| **NetworkX** | 纯 Python 内存图库 | Python API | 需自建序列化 | BSD | 最简单、生态大、性能最弱 |
| **SQLite**（自建图 schema） | 嵌入式关系库 | SQL（递归 CTE） | 单文件 | 公有领域 | 零依赖基线 |
| **rdflib** | 纯 Python RDF | SPARQL | 内存/文件序列化 | BSD | 慢、10 万三元组勉强 |

排除：Neo4j Community / NebulaGraph / HugeGraph / ArangoDB / TigerGraph（服务型、重部署，与"轻量本地化"不符）；QLever（服务型 SPARQL）。

## 2. 本机实测（100,000 节点 / 299,999 有向边，链式+随机边，Python 3.11）

| 引擎 | 加载耗时 | 一跳邻居 | 深度3可达 | 存储 | 依赖体积 |
|---|---|---|---|---|---|
| SQLite | 0.31s | 1 | 递归 CTE 可用 | 16.5 MB | 0（内置） |
| **Kùzu** | **0.25s** | 1 | 22（`*1..3` 可变长度） | 列式目录（压缩） | 21 MB |
| **igraph** | **0.12s** | 1 | 23 | 内存/自序列化 | 15 MB |
| NetworkX | 0.39s | 1 | 18 | 内存 | 小 |

> 起点 `n50000` 出边少（链式+随机巧合），各引擎邻居数一致（公平）；深度 3 可达差异来自递归实现与去重口径。加载均在亚秒级——**10 万节点对全部候选无压力**，瓶颈在查询表达力与内存。

## 3. 对比矩阵（按 DKWS 需求维度）

| 维度 | Kùzu | Oxigraph | igraph | NetworkX | SQLite |
|---|---|---|---|---|---|
| 嵌入/本地化 | ✅ 无服务 | ✅ 无服务 | ✅ 内存库 | ✅ 内存库 | ✅ 单文件 |
| 安装/依赖 | pip 21MB | pip（Rust） | pip 15MB | pip 小 | 零 |
| **图搜索简单性** | ⭐ Cypher：`*1..N` 路径/聚合/索引，声明式 | SPARQL（RDF 语义，学习成本高） | API 调用（邻居/路径/算法全） | API 调用（需手写 BFS/闭包） | 递归 CTE（表达力中等） |
| 递归/闭包/路径 | ⭐⭐ 原生 Cypher | ⭐⭐ SPARQL 属性路径 | ⭐ 需 API 组合 | ❌ 手写 | ⭐ CTE |
| 复合查询（图+属性） | ⭐⭐ Cypher 属性+图一体 | ⭐ SPARQL+filter | ⚠️ 属性序列化弱 | ⚠️ | ⭐ JOIN |
| 持久化/可重建 | ✅ 目录；可从 Parquet 重建 | ✅ 文件；可重建 | ❌ 弱 | ❌ 弱 | ✅ 单文件 |
| 10 万节点规模 | ✅（实测 0.25s 加载） | ✅ | ✅（0.12s） | ⚠️ 内存 ~1-2GB 可承受 | ✅ |
| 与 Python/DKWS 栈 | ✅ 官方 Python | ✅ pyoxigraph | ✅ | ✅ | ✅ |
| 许可 | MIT | MIT/Apache | GPL-2（注意） | BSD | PD |
| 维护活跃度 | 高（v0.11.3，持续发布） | 高 | 高 | 高 | 极高 |

## 4. 推荐

### 首选：**Kùzu**（嵌入式属性图 + Cypher）

理由：
1. **唯一同时满足"嵌入式零服务 + 声明式图查询（Cypher）"**：可变长度路径 `MATCH (a)-[:Knows*1..3]->(b)`、聚合、属性过滤、索引，直接对应 DKWS 当前 `graph()` 缺的能力（递归/闭包/复合查询），实测 10 万节点亚秒加载；
2. **MIT + 官方 Python 绑定 + 活跃维护**；列式持久化本地目录，可从 Parquet 投影重建（契合 DKWS 可重建性）；
3. 支持 `:memory:` 模式——若规格约束下走"进程内加速层"，Kùzu 同样可用（比 SQLite 表达力强得多）。

### 补充：**python-igraph**（内存图算法分析）

加载最快、图算法最全（中心性/社区/最短路径等）——适合做**离线图分析**（不作为服务底座）；GPL-2 许可需注意（库引用不影响，分发需兼容）。

### 零依赖基线：**SQLite**（递归 CTE）

若不允许新增依赖：SQLite 递归 CTE 可覆盖 80% 场景（闭包/路径/聚合），零依赖、单文件；表达力弱于 Cypher，但"够用"。

### 不推荐作为底座

- NetworkX：简单但无查询语言、内存/性能最弱（更大图吃力）；
- Oxigraph/rdflib：RDF/SPARQL 语义对"实体-关系-声明"知识模型**其实契合**（DKWS 知识本就近 RDF 三元组），但 SPARQL 学习成本与生态对当前团队不友好；若未来走 RDF 化可重估；
- 服务型图库：与"轻量本地化"需求直接冲突。

## 5. 与 DKWS 的集成路径（若选 Kùzu）

```
04_serve/<service>/version=*/graph/        # 可重建投影层（非权威源）
├── graph.db/                              # Kùzu 目录（或 graph.mdb 单文件形态）
└── PROJECTION.md                          # 记录构建器版本/逻辑哈希/来源版本
```

1. **构建**：`build-projection` 阶段从 `entities.parquet`/`relations.parquet` 构建 Kùzu 图（节点表 + 关系表，边保留 `relation_id/statement_id/effective_from/to` 溯源字段）；
2. **查询**：`application/services.py: graph()` 增加 Kùzu 后端（Cypher 递归/聚合），结果仍回传权威 ID + 证据引用（§15.5）；
3. **可重建性**：删 `graph/` → 仅凭 Core 重建，纳入 §18.4 测试；逻辑哈希记录于 PROJECTION.md；
4. **规格落地形态**：走 `evaluation-sqlite-graph-base.md` 方案 B（受控变更：Owner 决策 + ADR 记录"图库=投影查询加速层，非权威源"）或方案 C（`:memory:` 加速层，零持久化）。

## 6. 结论与建议下一步

- **选型结论**：Kùzu 为最合适的轻量图底座（嵌入式 + Cypher + 10 万+ 节点 + MIT）；igraph 作分析补充；SQLite 作零依赖回退。
- **下一步建议**：
  1. 确认是否启动 **Kùzu 投影层原型**（方案 C `:memory:` 先行验证 Cypher 查询价值，或直接方案 B 受控变更）；
  2. 若批准，我实现：`infrastructure/graph/kuzu_builder.py`（Parquet→Kùzu）+ `services.graph()` Kùzu 后端 + 可重建性/溯源测试 + 契约文档更新；
  3. 决策前可先用 1-2 个真实业务查询（如"供应链多级上游""承诺-产品联动"）在 Kùzu 上跑通，量化收益。

> 备注：实测脚本 `scripts/graph_db_bench.py` 与依赖（kuzu/igraph）已就绪，可随时复跑或扩展真实图谱数据。

## 7. 原型验证（2026-08-21，Kùzu :memory:，脚本 scripts/kuzu_prototype.py）

基于 bank_front 供应链示例（HZB0000001234 杭州智造精密齿轮）+ 合成多级扩展（明确标注演示），4 个典型业务查询全部 Cypher 单条完成：

| 业务查询 | Cypher | 结果 | 耗时 | 现有 graph() |
|---|---|---|---|---|
| 供应链多级上游（不限深） | `MATCH (c)<-[:Supplies*1..5]-(up) RETURN up.name, length(p)` | 5 家（1-3 级） | 10ms | depth≤3 硬限，更深需手写 |
| 递归闭包（可达上游全量） | `MATCH (c)<-[:Supplies*1..6]-(up) RETURN DISTINCT` | 5 家去重 | 3ms | 无闭包，需应用层循环+防环 |
| 路径枚举（铁矿石→客户） | `MATCH p=(ore)-[:Supplies*1..6]->(c) RETURN nodes(p)` | 完整供应链路径串 | 4ms | 只回 nodes/edges 无路径 |
| 图+属性聚合（一级上游金额） | `MATCH (c)<-[r:Supplies]-(s1) RETURN s1.name, r.amount_wan ORDER BY …` | 轴承12000/特钢8000 | 4ms | 多表遍历+内存聚合 30+ 行 |

**结论（原型实证）**：Kùzu Cypher 将 4 类此前不可/难表达的图查询压缩为单条声明式 SQL 级语句、毫秒级返回；`:memory:` 模式零持久化、契合方案 C。真实业务收益成立——建议进入方案 B 受控变更（或先以 :memory: 加速层接入 services.graph()）。
