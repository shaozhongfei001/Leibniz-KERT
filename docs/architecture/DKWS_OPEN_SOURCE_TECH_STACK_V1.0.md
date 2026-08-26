# DKWS 开源技术栈选型 V1.0（候选）

> 状态：CANDIDATE
> 日期：2026-08-26
> 优先级：企业级稳定性 > 技术栈成熟项目引用 > 高性能 > 国产化
> 关联：Phase 0 整改包、`DKWS_PRODUCTION_EVOLUTION_PLAN_V2_CANDIDATE.md`

## 1. 选型原则

1. **企业级稳定性优先**：优先选择有长期维护、可独立部署、故障可恢复、社区/商业支持明确的项目。
2. **技术栈成熟项目引用**：优先选择已被大量生产系统验证的组件，不选实验性项目。
3. **高性能**：在满足稳定性的前提下，优先列式、向量化、异步、嵌入式高性能组件。
4. **国产化**：在同等条件下优先选择国产开源项目；对非国产但生态事实标准的组件，保留兼容层，避免锁定。

## 2. 总体技术栈候选

| 层 | 首选 | 备选 | 国产化说明 |
|---|---|---|---|
| 操作系统 | openEuler / 麒麟（Kylin）兼容 Linux | Ubuntu LTS / Debian | 首选国产化 OS |
| CPU/架构 | x86_64 + ARM64（鲲鹏/飞腾） | 纯 x86_64 | 支持国产芯片 |
| 应用语言 | Python 3.11（CPython） | Python 3.12 | 与现有 DKWS 工程一致，生态成熟 |
| Web 框架 | FastAPI + Uvicorn | Starlette + Hypercorn | 异步高性能，OpenAPI 原生 |
| API 网关 | Apache APISIX | ShenYu / Nginx | APISIX 为 Apache 国产项目，高性能 |
| 权限策略 | Casbin（Python） | Open Policy Agent | Casbin 为国产开源，适合细粒度权限 |
| 运行态存储 | SQLite（WAL） | openGauss / PostgreSQL（未来触发） | Phase 1 保持 SQLite；未来国产化可选 openGauss |
| 任务执行 | 自研 SQLite-backed Worker | Celery + RocketMQ（未来） | 避免 Phase 1 引入外部 MQ |
| 容器 | Docker + Docker Compose / containerd | Podman | 单机生产；未来 K8s |
| 可观测 | Prometheus + Grafana + OpenTelemetry | SkyWalking（国产 APM） | SkyWalking 可作国产化追踪备选 |
| 知识图谱 | NebulaGraph（企业级分布式）+ Kùzu（嵌入式） | Apache HugeGraph / JanusGraph | NebulaGraph 为国产开源，适合生产图服务 |
| OLAP | Apache Doris / StarRocks | ClickHouse / Apache Kylin | Doris/StarRocks 为国产开源 MPP OLAP |
| 数据虚拟化/联邦 | Apache Calcite + Arrow Flight SQL | openLooKeng | Calcite 成熟；国产化可选 openLooKeng |
| 列式文件引擎 | Apache Arrow + DuckDB/DataFusion | Pandas + PyArrow | Arrow 生态成熟；DuckDB 高吞吐 |
| RAG 向量库 | Milvus | Qdrant / pgvector / Elasticsearch | Milvus 为国产开源，生产级 RAG 主流 |
| Embedding 模型 | BGE（BAAI）系列 | M3E / text2vec | 国产中文向量模型 |
| LLM 推理 | vLLM | Xinference / Ollama | vLLM 高性能；Xinference 国产化部署 |
| 非结构化解析 | Apache Tika + PaddleOCR + PaddleNLP | PyMuPDF / unstructured | Paddle 系列为国产开源 |
| 文档/知识资产 | 五层工作区 + Parquet | 对象存储 MinIO/Ceph | 保留文件权威源 |
| 安全扫描 | Trivy + Grype + Semgrep | SonarQube | 供应链与 SAST |
| 契约 | OpenAPI 3.1 + JSON Schema + Pydantic | AsyncAPI（事件） | 机器可验证 |

## 3. Skill 运行态选型

### 3.1 需求

1. 导入 Skill：支持可运行态动态导入 + 热加载
2. 优化 Skill 代码：支持热更新生效
3. 支持 Tool_call：与 Skill 深度绑定
4. 运行程序：支持 Python / Shell 沙箱执行

### 3.2 设计选型

| 能力 | 技术选型 | 说明 |
|---|---|---|
| Skill 包格式 | 目录/zip + `SKILL.md` + `skill.yaml` + `main.py` + `schema.json` | 版本化、哈希化、签名化 |
| Skill 注册表 | 自研 `SkillRegistry` + 版本目录 + `importlib` | 避免全局 `sys.modules` 污染，按版本加载 |
| 动态导入 | Python `importlib` + `spec_from_file_location` | 支持运行态导入 |
| 热加载 | `watchdog`（开发态）+ 版本化目录原子切换（生产态） | 生产不依赖文件系统 watcher 做热更新 |
| 热更新生效 | `dkws-admin skill activate <skillId> <version>` | 原子切换 CURRENT 指针；Worker 重启/重新加载 |
| Skill 隔离 | 子进程 + `nsjail`/`bubblewrap` + seccomp | 单机轻量沙箱 |
| Python 沙箱 | `nsjail` + CPython `-I` 隔离模式 + 受限 sys.path | 不采用不可维护的纯 Python 沙箱 |
| Shell 沙箱 | `nsjail` / `bubblewrap` + 资源限制 | 白名单命令、超时、输出大小限制 |
| 强隔离备选 | gVisor / Kata Containers | 面向不可信 Skill 的后续增强 |
| Tool ABI | JSON-RPC 2.0 over stdio / gRPC | Skill 与 Tool 通过统一 ABI 绑定 |
| Tool 定义 | JSON Schema + Pydantic | 输入输出强校验 |
| MCP 兼容 | 可选 MCP Server 适配层 | 便于外部 Agent 消费，但不作为内部依赖 |

### 3.3 热更新机制

```text
Skill 包 v1.0.0
  → 上传/安装到 skills/<skillId>/versions/1.0.0
  → 校验签名/哈希/schema
  → dkws-admin skill activate <skillId> 1.0.0
  → 更新 skills/<skillId>/CURRENT 指针
  → 通知 Skill Worker 重新加载
  → 新请求使用新版本；旧请求在超时内可继续
```

### 3.4 Tool_call 深度绑定

每个 Skill 声明依赖的工具：

```yaml
tools:
  - name: knowledge.search
    version: ">=1.0,<2"
    required: true
    permission: knowledge.read
```

执行时：

1. 解析 Skill 依赖
2. 校验调用者权限
3. 加载 Tool 版本
4. 校验输入 Schema
5. 执行并记录 `tool_call_receipt`
6. 结果进入 `assemblyTrace`
7. 失败按 Skill/Tool 显式策略处理

## 4. 多数据源适配层选型

### 4.1 需求

1. 图数据库查询访问
2. JDBC、OLAP 查询分析
3. 列式数据文件（Parquet）查询、统计分析
4. RAG 查询访问
5. 其他非结构化数据访问

### 4.2 统一适配层设计

```text
DKWS KnowledgeSource API
├── GraphSource
│   ├── NebulaGraphSource
│   └── KuzuGraphSource
├── RelationalSource
│   ├── JdbcSource (HikariCP/psycopg/pymysql)
│   └── OlapSource (Doris/StarRocks/ClickHouse)
├── ColumnarSource
│   ├── ArrowFlightSqlSource
│   ├── DuckDBParquetSource
│   └── DataFusionSource
├── VectorRagSource
│   ├── MilvusSource
│   └── EmbeddingSource (BGE)
└── UnstructuredSource
    ├── TikaSource
    ├── PaddleOCRPdfSource
    └── FileSystemSource
```

统一接口：

```python
class KnowledgeSource(Protocol):
    name: str
    source_type: str
    capabilities: list[str]
    health() -> SourceHealth
    search(request: SearchRequest) -> SourceResult
    get(request: GetRequest) -> SourceResult
    graph(request: GraphRequest) -> SourceResult
    execute_registered_query(query_id: str, params: dict) -> SourceResult
```

### 4.3 图数据库

| 项 | 选型 |
|---|---|
| 嵌入式/本地投影 | Kùzu（现有，保留） |
| 企业级分布式图 | NebulaGraph |
| 国产化备选 | Apache HugeGraph |
| 查询语言 | nGQL / Cypher 兼容适配 / Gremlin（HugeGraph） |
| 适用 | 供应链图谱、关系推理、路径分析 |

选型理由：

- NebulaGraph 为国产开源分布式图数据库，支持万亿边级扩展，已有大量国内生产案例。
- Kùzu 适合单机可重建投影，保持轻量。
- 适配层屏蔽 nGQL/Cypher/Gremlin 差异。

### 4.4 JDBC / OLAP

| 场景 | 选型 |
|---|---|
| 标准 JDBC 数据库 | HikariCP（Java）/ SQLAlchemy（Python）+ 连接池 |
| OLAP 分析 | Apache Doris / StarRocks |
| 联邦查询 | Apache Calcite |
| 高性能列式传输 | Apache Arrow Flight SQL |
| 备选 | ClickHouse（高吞吐）、openLooKeng（国产化联邦） |

选型理由：

- Apache Doris/StarRocks 是国产开源 MPP OLAP，支持大规模并行分析、物化视图、高并发点查。
- Arrow Flight SQL 提供高吞吐列式传输，适合 Parquet/OLAP 结果集。
- JDBC 适配器使用注册 SQL 模板，不暴露任意 SQL。

### 4.5 Parquet 列式文件

| 项 | 选型 |
|---|---|
| 列式内存格式 | Apache Arrow |
| SQL 查询引擎 | DuckDB 或 Apache DataFusion |
| Python 集成 | PyArrow + DuckDB |
| 统计分析 | Arrow Compute + DuckDB SQL |
| 国产化扩展 | StarRocks/Doris External Table on Parquet |

选型理由：

- DuckDB 在单机嵌入式 OLAP 场景性能极高，支持直接查询 Parquet。
- Apache Arrow 生态成熟，跨语言标准。
- 保留 Parquet 为知识投影格式，与现有 04_serve 一致。

### 4.6 RAG 查询

| 项 | 选型 |
|---|---|
| 向量数据库 | Milvus |
| 嵌入式备选 | Qdrant / LanceDB / pgvector |
| Embedding | BGE（BAAI）系列 |
| 检索增强 | 自研 RAGSource：向量 + 全文 + 图谱混合检索 |
| 国产化 | BGE + Milvus + 自研中文分词（可接 HanLP/jieba） |

选型理由：

- Milvus 是国产开源、LF AI & Data 项目，生产级向量检索，支持高并发。
- BGE 中文 Embedding 在企业 RAG 中成熟度高。
- 与现有全文/向量混合检索对齐。

### 4.7 非结构化数据

| 项 | 选型 |
|---|---|
| 格式识别 | Apache Tika |
| OCR | PaddleOCR（国产开源） |
| NLP/版面分析 | PaddleNLP / PaddleOCR PP-Structure |
| PDF | PyMuPDF + PaddleOCR |
| 文本切分 | 自研章节切分 + Markdown 契约 |
| 对象存储 | MinIO / Ceph（S3 兼容） |

选型理由：

- Paddle 系列适合中文文档、票据、扫描件。
- Apache Tika 适合通用格式探测与文本抽取。
- 非结构化数据进入 01_raw → 02_work → 03_core 管道，不绕过知识权威源。

## 5. 运行时控制面技术选型

| 能力 | 选型 |
|---|---|
| Runtime Store | SQLite WAL（Phase 1） |
| Schema Migration | 自研版本化迁移 + `PRAGMA user_version` |
| 任务队列 | SQLite-backed Worker（原子 claim + lease） |
| 限流 | 自研滑动窗口 + 可接 Redis（未来） |
| 缓存 | 本地进程缓存 + 可选 Redis（未来） |
| 密钥管理 | 环境变量 / Docker Secret / 文件注入；未来 Vault/KMS |
| 日志 | structlog / logging + JSON formatter |
| Metrics | Prometheus client |
| Tracing | OpenTelemetry SDK + SkyWalking/Jaeger |
| 审计 | SQLite audit_events + 防篡改哈希链 |

## 6. 国产化适配矩阵

| 国产化需求 | 选型 |
|---|---|
| 操作系统 | openEuler、麒麟 |
| CPU | 鲲鹏、飞腾、海光（x86 兼容） |
| 图数据库 | NebulaGraph / Apache HugeGraph |
| OLAP | Apache Doris / StarRocks |
| RAG 向量库 | Milvus |
| Embedding | BGE |
| OCR/NLP | PaddleOCR / PaddleNLP |
| API 网关 | Apache APISIX |
| 权限 | Casbin |
| 数据库（未来） | openGauss |
| MQ（未来） | Apache RocketMQ |
| APM | SkyWalking |

## 7. 技术栈成熟度参考

| 组件 | 成熟度信号 |
|---|---|
| FastAPI/Uvicorn | 大型 Python API 生态，OpenAPI 原生 |
| Apache APISIX | Apache 顶级项目，云原生网关 |
| NebulaGraph | 国内互联网/金融图场景广泛使用 |
| Apache Doris/StarRocks | 国内大数据分析场景广泛使用 |
| Milvus | LF AI & Data 项目，RAG 生产常用 |
| DuckDB/Arrow | 列式分析生态，社区快速增长 |
| PaddleOCR/PaddleNLP | 百度开源，中文 NLP/OCR 成熟 |
| Casbin | 国产开源权限库，多语言 |
| vLLM | 高性能 LLM 推理，社区活跃 |

## 8. Phase 映射

| Phase | 引入技术 |
|---|---|
| Phase 0 | OpenAPI/JSON Schema、Pydantic、契约校验、SQLite 设计 |
| Phase 1 | FastAPI 安全、SQLite WAL、nsjail/bubblewrap、API Key、Casbin、Prometheus/Grafana、Docker Compose、Trivy |
| Phase 2 | 自研 SQLite Worker 完善、OpenTelemetry、SkyWalking、LLM Gateway、vLLM/Xinference |
| Phase 3 | NebulaGraph/Kùzu 双图源、DuckDB/Arrow、Milvus+BGE、Tika+Paddle、APISIX |
| Phase 4 | 目录级多租户、openGauss/PostgreSQL（按触发）、RocketMQ（按触发） |
| Phase 5 | K8s、对象存储、多实例、按真实指标决策 |

## 9. 风险和约束

- **不推翻现有 Python 工程**：技术栈以增量引入为主。
- **SQLite 不是万能**：达到并发/容量触发条件后切换 openGauss/PostgreSQL。
- **沙箱隔离强度**：nsjail/bubblewrap 适合内部可信 Skill；不可信第三方 Skill 需 gVisor/Kata。
- **国产化不等于全部替换**：保留 Kubernetes 生态、Prometheus 等事实标准，通过兼容层集成。
- **热更新与稳定性冲突**：生产热更新采用版本化原子切换，不采用文件 watcher 直接改运行代码。

## 10. 待 Owner/架构确认

1. 是否采用 NebulaGraph 作为企业级图数据库，Kùzu 仅作本地投影？
2. 是否采用 Apache Doris 或 StarRocks 作为 OLAP 标准？
3. 是否采用 Milvus + BGE 作为 RAG 标准？
4. 是否接受 nsjail/bubblewrap 作为首期沙箱，gVisor/Kata 作为后续？
5. 是否接受 APISIX + Casbin 作为网关与权限标准？
6. 未来数据库若需替换，是否以 openGauss 为国产化首选？
