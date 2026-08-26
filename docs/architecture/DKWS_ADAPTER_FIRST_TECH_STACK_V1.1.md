# DKWS 适配器优先技术栈 V1.1（候选）

> 状态：CANDIDATE
> 日期：2026-08-26
> 替代：`DKWS_OPEN_SOURCE_TECH_STACK_V1.0.md`（V1.0 范围过大，保留为历史）
> 原则：DKWS 只做能力接口 + 轻量适配器 + 本地默认实现，不负责部署外部重型系统。

## 1. 边界声明

DKWS 不引入/不部署以下系统作为自身组件：

- NebulaGraph / Neo4j / HugeGraph 等服务型图数据库
- Apache Doris / StarRocks / ClickHouse 等 OLAP 集群
- Milvus / Qdrant 等向量数据库服务
- vLLM / Xinference 等 LLM 推理服务
- Apache APISIX / Kong 等 API 网关
- 独立 MQ / Redis / PostgreSQL（Phase 1）

以上系统可以**已经存在**于客户环境，DKWS 只提供访问适配器。

## 2. 核心运行栈

| 层 | 选型 | 理由 |
|---|---|---|
| 语言 | Python 3.11 | 与现有 DKWS 一致，避免重写 |
| Web | FastAPI + Uvicorn | 成熟、异步、OpenAPI 原生 |
| 数据校验 | Pydantic | 与 FastAPI/JSON Schema 一致 |
| 运行态存储 | SQLite WAL | 只存可变运行态，不替代知识权威源 |
| 日志 | structlog / logging + JSON | 轻量可观测 |
| Metrics | Prometheus client | 标准协议，不引入全家桶 |
| Tracing | OpenTelemetry SDK | 标准，可对接已有后端 |
| 部署 | Docker Compose / systemd | 单机生产候选 |

## 3. Skill 运行态选型

| 需求 | 选型 | 说明 |
|---|---|---|
| 导入 Skill | 版本化目录 + `SKILL.md` + `skill.yaml` + `main.py` + `schema.json` | 不引入重型插件框架 |
| 动态导入 | Python `importlib` + `spec_from_file_location` | 运行态加载 |
| 热加载 | 开发态 `watchdog`；生产态版本目录原子切换 | 生产不依赖 watcher 热改 |
| 热更新生效 | `dkws-admin skill activate <skillId> <version>` | 原子切换 CURRENT 指针 |
| Python 沙箱 | `nsjail` / `bubblewrap` + seccomp + CPython `-I` | 轻量进程隔离 |
| Shell 沙箱 | `nsjail` / `bubblewrap` + 资源限制 + 命令白名单 | 防逃逸、防资源耗尽 |
| Tool_call | 自研 Tool ABI：JSON-RPC 2.0 over stdio / gRPC | 与 Skill 版本深度绑定 |
| Tool 校验 | JSON Schema + Pydantic | 输入输出强校验 |
| 外部 Agent 兼容 | 可选 MCP 适配层 | 不作为内部依赖 |

### 与 Spring AI / Spring AI Alibaba 对比结论（修正版）

**先纠正**：我此前把“上游 Spring AI”和“Spring AI Alibaba”混淆了。根据调研，Spring AI Alibaba（spring-ai-alibaba，Agent Framework / Graph Core）确实把 Skills 技能体系作为官方核心能力，且支持：

- `FileSystemSkillRegistry` / `ClasspathSkillRegistry`：动态导入 + 热加载；
- `SkillsAgentHook.autoReload(true)`：运行态重新扫描，新增/修改技能无需重启；
- `groupedTools`：工具与技能深度绑定，渐进式披露；
- `PythonTool`（GraalVM polyglot 沙箱）与 `ShellTool2`：Python/Shell 执行。

因此“Spring AI Alibaba 不能支撑 Skill 运行态”的说法是不准确的。

**对 DKWS 的影响判断**：

| 维度 | Spring AI Alibaba | Python 原生方案 |
|---|---|---|
| Skill 热加载/动态导入 | 官方 Skills Registry + autoReload | Python `importlib` + 版本目录 |
| Tool_call 绑定 | `groupedTools` / SkillsAgentHook | 自研 Tool ABI |
| Python/Shell 沙箱 | GraalVM PythonTool / ShellTool2 | nsjail/bubblewrap |
| 技术栈 | Java/Spring Boot | Python/FastAPI |
| 与现有 DKWS | 需引入 Java 服务或重写 Skill 运行层 | 与现有代码一致 |
| 国产化/企业生态 | 阿里开源，Java 生态成熟 | Python 生态成熟 |
| 风险 | 引入 Java 边车/双运行时；GraalVM Python 对部分库支持有限 | 自研组件需更多工程化 |

**结论**：

1. Spring AI Alibaba 是 Java 侧构建 Skill 运行态的**强候选**，不应被否定。
2. 是否采用取决于产品架构决策：
   - 如果 DKWS 保持 Python 单体，则继续用 Python 原生轻量方案；
   - 如果允许引入独立的 Java Skill 运行态服务，Spring AI Alibaba 可以作为该服务的基座，DKWS Python 核心只负责知识/数据服务；
   - 如果 GITS Java 侧需要内嵌 Skill 运行态，Spring AI Alibaba 更合适。
3. 建议做一次 PoC 验证：用 FileSystemSkillRegistry + autoReload + groupedTools + PythonTool/ShellTool2 跑通“上传 Skill → 热加载 → Tool 调用 → 沙箱执行”闭环，再决定是否作为正式 Skill Runtime。


## 4. 多数据源适配层选型

统一使用 `KnowledgeSource` SPI，不绑定具体部署。

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

### 4.1 图数据库访问

| 项 | 选型 |
|---|---|
| 本地默认 | Kùzu（已有嵌入式投影） |
| 外部图 | NebulaGraph / Neo4j / HugeGraph 客户端适配器 |
| 协议 | 各图数据库原生驱动 / HTTP / Bolt |
| 不引入 | 不部署图数据库服务 |

### 4.2 JDBC / OLAP 查询分析

| 项 | 选型 |
|---|---|
| JDBC/关系库 | SQLAlchemy / Python DB-API / 可选 JDBC bridge |
| OLAP 访问 | 通过各 OLAP 的 SQL/HTTP 协议适配，不部署集群 |
| 列式传输 | Arrow Flight SQL 客户端（若目标支持） |
| 安全 | 注册 SQL 模板，禁止任意 SQL |

### 4.3 Parquet 列式文件

| 项 | 选型 |
|---|---|
| 内存格式 | Apache Arrow / PyArrow |
| 本地查询 | DuckDB 或 Apache DataFusion（库） |
| 统计分析 | Arrow Compute / DuckDB SQL |
| 对象存储 | S3 兼容 SDK 读取远端 Parquet |

### 4.4 RAG 查询访问

| 项 | 选型 |
|---|---|
| 向量库访问 | 已有 Milvus / Qdrant / pgvector 等 SDK/HTTP 适配 |
| Embedding | 调用已有 Embedding HTTP API，或本地 BGE 库（可选） |
| 不引入 | 不部署 Milvus/Qdrant/vLLM |

### 4.5 非结构化数据访问

| 项 | 选型 |
|---|---|
| 格式解析 | Apache Tika（库/服务） |
| OCR | PaddleOCR（库或已有服务） |
| 版面/NLP | PaddleNLP（可选） |
| 存储 | 本地文件系统 / S3 兼容对象存储 |

## 5. 可选外部系统（仅适配，不部署）

| 外部系统 | DKWS 只做 |
|---|---|
| NebulaGraph | GraphSource 适配器 |
| Neo4j | GraphSource 适配器 |
| Doris/StarRocks/ClickHouse | RelationalSource 适配器 |
| Milvus/Qdrant | VectorRagSource 适配器 |
| vLLM/OpenAI 兼容服务 | LLM Adapter（已有） |
| Tika/PaddleOCR 服务 | UnstructuredSource 适配器 |

## 6. 与 V1.0 的差异

| 项 | V1.0（已废弃） | V1.1（当前） |
|---|---|---|
| 图数据库 | 引入 NebulaGraph | 只做适配器 |
| OLAP | 引入 Doris/StarRocks | 只做适配器 |
| RAG | 引入 Milvus | 只做适配器 |
| LLM | 引入 vLLM | 只保留 LLM Adapter |
| API 网关 | 引入 APISIX | 不强制引入 |
| 权限 | 引入 Casbin | 首期 FastAPI 中间件 + 简单策略，后续按需 |
| 部署 | 大量外部组件 | 保持轻量单机 |

## 7. 待确认

1. 是否接受“适配器优先、不部署外部系统”作为 DKWS 技术栈原则？
2. Skill 运行态采用哪种路线：Python 原生轻量运行时，还是引入独立的 Spring AI Alibaba Java 运行时（需 PoC 后决策）？
3. 是否接受首期沙箱为 nsjail/bubblewrap，后续按需增强？
4. 是否接受统一 `KnowledgeSource` SPI 作为多数据源接入标准？
