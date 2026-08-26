# DKWS 系统架构（文件目录型数据知识服务模拟平台）

> 版本：2026-08-22（对齐 v1.3 数据所有权改造）
> 依据：`文件目录型数据知识服务模拟平台_详细需求与详细设计_V1.0.md`（DKWS-SPEC-001）+ ADR（IMP-ADR-001~011）
> 图源：`dkws/docs/architecture.md`（Mermaid）；PNG 渲染：`dkws/docs/assets/dkws-architecture-*.png`

---

## 1. 总览：五层工作区 + 运行时服务

```mermaid
flowchart LR
  subgraph L1["01_raw 原始输入层"]
    N1["文档 / 批次 / 外部数据<br/>(ingest 接入登记)"]
  end
  subgraph L2["02_work 加工工作层"]
    N2["parse 解析切片<br/>extract 抽取候选(实体/关系/声明)<br/>review 审核 APPROVE"]
  end
  subgraph L3["03_core 核心资产层"]
    N3["entities / relations / statements<br/>segments / rules<br/>version= 不可变版本 + RELEASE.md"]
  end
  subgraph L4["04_serve 服务投影层"]
    N4["Parquet 投影<br/>(entities/segments/statements<br/>relations/rules/vectors/datasets)"]
    N4b["Kùzu 图谱<br/>(graph 单文件 + 指纹)"]
  end
  subgraph L5["90_control 治理层"]
    N5["decisions 审核决策<br/>gates G0-G5 门禁<br/>jobs 作业日志"]
  end
  N1 -->|"接入"| N2
  N2 -->|"审核通过"| N3
  N3 -->|"投影构建"| N4
  N3 -->|"图投影"| N4b
  N5 -. "记录/门禁" .-> N2
  N5 -. "记录" .-> N3
  N5 -. "记录" .-> N4
```

**分层职责**：01_raw 只收原始输入；02_work 是可重跑的加工现场（run_id 隔离）；
03_core 是**不可变版本化**的核心资产（发布即冻结）；04_serve 是面向查询/图谱/技能的
**可重建投影**（fingerprint 校验，Kùzu 为受控变更投影层，ADR-011）；90_control 全程
记录决策、门禁与作业审计。

## 2. 运行时服务架构（API → 应用 → 基础设施 → 数据/外部）

```mermaid
flowchart TB
  subgraph CLIENTS["消费方"]
    G["GITS 客户经理工作台<br/>(execute 契约 v1.3 · 只传 customerId)<br/>CRM upsert · KI 卡片对位"]
    D["DSH GUI / 浏览器<br/>(Skill 报告页 · 图谱可视化)"]
    C["命令行 / 脚本 / 评测"]
  end
  subgraph API["DKWS HTTP API（FastAPI :8106）"]
    V1["/v1/* 知识服务<br/>health / extractions / jobs / entities<br/>data/query · search · graph<br/>rules/evaluate · evidence · catalog"]
    SK["/api/skill/* 技能服务<br/>health · execute · report/{requestId}"]
  end
  subgraph APP["应用层 application/"]
    KS["KnowledgeService<br/>检索(全文/向量/混合)·图谱·规则·溯源"]
    SES["SkillExecutionService<br/>幂等 · 无新证据策略 · fail-closed<br/>assemblyTrace（KI 级轨迹）"]
    CK["CustomerKnowledgeProvider<br/>ki_map · entity · supply_chain<br/>interpretation（v1.3 取数层）"]
    RP["报告渲染 report.py<br/>供应链图谱定制模板(Neo4j 风格)"]
  end
  subgraph INFRA["基础设施层 infrastructure/"]
    LLM["LLM 适配器<br/>OpenAI 兼容(DeepSeek) / 确定性回退"]
    KUZU["Kùzu 图后端(嵌入式 Cypher)<br/>内存 BFS 回退(fail-open)"]
  end
  subgraph DATA["数据层（5 层工作区 workspace）"]
    WS["01_raw / 02_work / 03_core<br/>04_serve / 90_control"]
  end
  subgraph EXT["外部集成"]
    DSH["DeepSeek Harness<br/>(SKILL.md 资产同步 · dkws-1 面板)"]
    EXTLLM["DeepSeek API（OpenAI 兼容）"]
    GITS["GITS CRM<br/>PUT upsert（交付物 B）"]
  end
  G --> V1
  G --> SK
  D --> SK
  C --> V1
  V1 --> KS
  SK --> SES
  SES --> CK
  SES --> LLM
  KS --> KUZU
  KS --> WS
  CK --> WS
  SES --> RP
  DSH -. "SKILL.md 资产" .-> SES
  EXTLLM <--> LLM
  GITS <--> G
```

## 3. 核心组件与数据流

| 环节 | 组件 | 说明 |
|---|---|---|
| 接入 | `Ingestor` | 01_raw 登记批次，产出 DOC 登记（sha256 校验） |
| 解析 | `DocumentParserService` | 02_work 分段切片（heading 层级 + content_sha256） |
| 抽取 | `KnowledgeExtractor` | 实体/关系/声明候选（确定性 + 可选 LLM，CANDIDATE） |
| 审核 | `ReviewService` | 决策落 90_control/decisions，状态机 CANDIDATE→IN_REVIEW→APPROVED/REJECTED |
| 发布 | `Publisher` | 03_core 不可变版本（RELEASE.md + G3 门禁 + 幂等键含 run_id） |
| 投影 | `ProjectionBuilder` | 04_serve Parquet（x_* 扩展字段透传）+ Kùzu 图（ADR-011）+ fingerprint |
| 检索 | `KnowledgeService` | search（FULLTEXT/VECTOR/HYBRID）、data_query、get_entity、graph、evaluate_rule、trace |
| 图谱 | `_graph_kuzu` + `_graph_memory` | 邻接/闭包/路径（max_depth≤10，方向拆分防环路，fail-open） |
| 技能 | `SkillExecutionService` | 10 个 Skill（3 客户 + 7 bank-front 外部包）；幂等 TTL 10min；无新证据策略；fail-closed |
| 取数 | `CustomerKnowledgeProvider` | v1.3：按 customerId 读 KI 片段/实体/图谱（数据所有权在 DKWS） |
| 报告 | `report.py` | `/api/skill/report/{id}` 定制图谱报告（vis-network，Neo4j 风格） |
| 模型 | `llm.py` | DeepSeek（环境注入密钥）/ 确定性回退（离线端到端） |

**黄金路径（数据）**：接入 → 解析 → 抽取 → 审核 APPROVE → 发布 → 投影（Parquet + Kùzu）→
查询 / 检索 / 规则 / 图谱 / 溯源。

**黄金路径（技能，v1.3）**：GITS 传 `customerId` → `CustomerKnowledgeProvider` 从
`customer_knowledge` 投影取 7 条 KI / 图谱 → evidence 打点（ok/skipped 只反映库命中）→
LLM 生成（可选，图谱为确定性库构建）→ `data.sections` 按 KI 出章 → GITS 按 heading 对位。

## 4. 关键架构约束（DKWS-SPEC-001 / ADR）

- **文件目录为权威源**：本体 FS（03_core）+ 投影（04_serve）可重建；无隐藏数据库（§18.5）。
- **受控变更例外**：Kùzu 作为**可重建投影层**（IMP-ADR-011，6 条边界），非权威源。
- **数据所有权（v1.3）**：知识全在 DKWS；GITS 只传 `customerId`（+ 可选时间戳/拜访意图）。
- **fail-open / fail-closed**：知识检索失败 fail-open；模型输出不合格 fail-closed（无残缺半成品）。
- **可观测**：assemblyTrace（KI 级，含 kiId）、jobs 作业日志、G0-G5 门禁报告。

---

## 5. 时序图：GITS 调用 execute 完整链路（v1.3）

```mermaid
sequenceDiagram
    autonumber
    participant G as GITS 工作台
    participant D as DKWS API (:8106)
    participant S as SkillExecutionService
    participant CK as CustomerKnowledgeProvider
    participant KS as KnowledgeService(customer_knowledge 投影)
    participant LLM as LLM 适配器(DeepSeek / 确定性回退)
    G->>D: POST /api/skill/execute {skillId, requestId, request:{customerId, evidenceTimestamp}}
    D->>S: execute(skillId, requestId, request)
    S->>S: 幂等检查(requestId)
    alt 命中幂等缓存
        S-->>G: 返回首次结果(trace 含 idempotency)
    else 新请求
        S->>S: 无新证据策略(仅 R1)：evidenceTimestamp 校验
        alt 时间戳缺失或未更新
            S-->>G: status=exit_policy_no_new_evidence
        else 校验通过
            S->>CK: 按 customerId 取 7 条 KI
            CK->>KS: segments(document_id=customerId)
            KS-->>CK: KI 片段全文
            CK-->>S: {KI-009, KI-FRONT-001..006: title+content}
            S->>S: evidence 打点(ok=库命中 / skipped=库无数据)
            S->>LLM: 组装知识上下文 + visitObjective，生成报告
            LLM-->>S: JSON 输出(记录 modelCalls)
            S->>S: sections 按命中 KI 出章(heading 含 KI 编号)
            S-->>D: SkillExecuteResult(status=ok, data, assemblyTrace)
            D-->>G: 200 {data.sections, evidenceRefs, reportUrl}
        end
    end
    Note over G,D: 图谱分支 bank-front-supply-chain-graph：CK.supply_chain(customerId) 库构建 data.result，model=library，无 LLM
```

PNG：`docs/assets/dkws-sequence-execute.png`

## 6. 部署拓扑图（8106 / DSH / GITS / H2）

```mermaid
flowchart TB
    subgraph HOST["同一主机 172.22.90.134"]
        subgraph DSH["DSH · DeepSeek Harness :3080"]
            GUI["DSH Web GUI(dkws-1 知识面板插件)"]
            SKM["SKILL.md 资产库(customer-engagement 同步)"]
        end
        subgraph DKWS["DKWS 服务 · systemd dkws-skill :8106"]
            API["FastAPI /v1/* 知识服务 + /api/skill/* 技能服务"]
            WS5["5 层工作区(demo_workspace)"]
            KZ["Kùzu 图谱文件(04_serve 投影)"]
        end
        subgraph GITSAPP["GITS 应用 · Java/Spring Boot"]
            GAPI["GITS API :8080 /api/v1/engagement/*"]
            FE["前端 Vue(SupplyChainGraphReport)"]
            H2["H2 内存库 customer 表(CRM 主档)"]
        end
        STATIC["静态资源 :8090(报告页/图谱可视化)"]
    end
    subgraph EXT["外部"]
        DSAPI["DeepSeek API(OpenAI 兼容)"]
        USER["用户浏览器"]
    end
    FE --> GAPI
    GAPI --> H2
    GAPI -->|"execute 契约 v1.3 只传 customerId"| API
    DKWS -->|"PUT upsert / 夹具(交付物 B)"| GAPI
    DSH -->|"SKILL.md 资产同步"| DKWS
    DKWS -->|"LLM 调用"| DSAPI
    USER --> GUI
    USER --> FE
    USER --> STATIC
    API --> WS5
    API --> KZ
    GUI --> STATIC
```

PNG：`docs/assets/dkws-deployment-topology.png`

**部署要点**：
- 全部同机（172.22.90.134）：DSH Web（:3080）、DKWS 服务（:8106，systemd 用户服务，Restart=always）、
  GITS API（:8080）+ 前端、静态资源（:8090）。
- **H2 为内存库**：GITS 重启后须重新 upsert / 重灌 `gits-crm-customer-master.json`（造数脚本幂等）。
- 数据流：GITS API → DKWS execute（v1.3 只传 customerId）；DKWS → GITS `PUT /api/v1/engagement/customer/{id}`
  同步 CRM 主档（交付物 B）；DKWS → DeepSeek API（LLM，密钥不落盘）。
