# 提案：登记 9 条「已实现未登记」的 `/v1/*` 路径（F8）

```text
PROPOSAL_ID : M7-CLOSURE-C20-F8-UNDECLARED-PATHS
性质        : **提案（proposal only）** —— 本文件**不改**合同、**不改** `paths`、**不改** `src/**`/`tests/**`
依据        : evidence/m7-3/CANDIDATE-CONTRACT-MERGE-V1-V2.md §2.1-B⑦ 与 §2.5-F8
授权        : TL 裁定 ④ —— F8 属 **additive 扩展**（非"形状更正"）⇒ 必须走
              **Contract Owner 追认**；本轮**只出提案**
DATE        : 2026-09-16
```

## 1. 问题（机读事实，逐条回源）

`specs/kert-openapi-v1.yaml` 现声明 **14 条 `paths`**（行号：73 / 103 / 130 / 165 / 308 / 345 / 389 /
425 / 591 / 609 / 629 / 643 / 694 / 720），而实现注册的 `/v1/*` 路由**多于此**。逐条对账：

| 类别 | 数量 | 明细 |
|---|---|---|
| **已实现但合同未声明（本提案标的）** | **9** | 见 §2 |
| 合同声明且实现一致 | 12 | `/v1/health`、`/v1/jobs/{jobId}`、`/v1/knowledge-maps`、`/v1/knowledge-maps/{mapId}`、`/v1/routing/plan` + `/api/skill/*` 4 条 + `/livez`/`/readyz`/`/metrics` |
| **合同声明但实现缺失** | **1** | `GET /v1/skills`（合同 `:130`；实现**无**该路由）→ 见 §5.1 |

## 2. 9 条待登记路径（实现位置 = 当前行号，`src/kert/api/server.py`）

> **行号基准快照（2026-09-16，c20 逐条只读复核）**：基准文件 `src/kert/api/server.py` = **783 行 / sha16 `7e516e610c43d482`**，
> 基准 HEAD = **`e7b1b56`**；该文件自 `e3bcefe`（本提案同批提交）起**未再改动** ⇒ 下表 9 条的**起始行逐条与实测一致（9/9「是」）**。
> 引用格式：本表用**裸** `:NNN` / `:NNN-NNN`（文件由本节标题声明），全文另有 **2 处**前缀式 `server.py:NNN`（`:26`、`:80`）。

> 共同点：全部走 `/v1/*` **标准信封** `{request_id, status, data, errors, meta}`
> （`_response()`，`server.py:208-217`）；**GITS 当前均未调用**（`docs/integration/KERT_GITS_CONTRACT_DIFF.md:12-23`）。

| # | 方法 / 路径 | 实现 | 请求模型 | 响应信封 | 建议登记要点 |
|---|---|---|---|---|---|
| 1 | `POST /v1/extractions`（**202**） | `:499-528` | `ExtractionRequest` `:151-158` | **手写信封，`status="ACCEPTED"`**（`:516-526`），非 `_response()` | 202 + `data.{job_id,result_status,publish_status}`；注意 `status` 取值与其它端点不同（`ACCEPTED`） |
| 2 | `GET /v1/extractions/{job_id}/result` | `:538-548` | — | `_response`（`:542`） | `data.{job_id,status,publish_status,output_refs}` |
| 3 | `GET /v1/entities/{entity_id}`（+`as_of` 查询参数） | `:550-556` | — | `_response`（`:554`） | 路径参数 + **查询参数 `as_of`**（合同需显式声明，否则客户端无从得知） |
| 4 | `POST /v1/data/query` | `:558-565` | `DataQueryRequest` `:161-167` | `_response`（`:563`） | `dataset/select/where/limit`（`limit` 默认 100） |
| 5 | `POST /v1/search` | `:567-574` | `SearchRequest` `:169-175` | `_response`（`:572`） | `query/mode/top_k/filters` |
| 6 | `POST /v1/graph/query` | `:576-587` | `GraphRequest` `:177-187` | `_response`（`:585`） | `start_entity_ids/relation_types/direction/max_depth/max_nodes/mode/service/as_of`；**与 v2 既有声明不一致，见 §5.2** |
| 7 | `POST /v1/rules/evaluate` | `:589-595` | `RuleRequest` `:189-190` | `_response`（`:593`） | `rule_set/facts` |
| 8 | `GET /v1/evidence/{object_id}` | `:597-620` | — | `_response`（`:618`） | `data` 为证据引用集合（含审计镜像副作用，`:601-613`） |
| 9 | `GET /v1/catalog` | `:622-632` | — | `_response`（`:629`） | `data.{service_id, version, projections}`（测试 `tests/integration/test_api.py:76-79` 已断言 `projections`） |

## 3. 为什么是 additive，为什么仍必须追认

**技术上是 additive**：不动任何既有路径 / 字段 / 状态码 / 错误码，只把**已经运行的事实**写进合同；
对现有调用方（GITS 仅用 `/api/skill/*` + `/v1/jobs`，见 `KERT_GITS_CONTRACT_DIFF.md:12-23`）**零影响**。

**但仍必须 Contract Owner 追认**，理由两条：

1. **它扩大了对外的服务面承诺**：合同是"实现照合同"纪律的对象（`CONTRACT_CHANGE_PROPOSAL_ROUTING_API.md:30`）。
   登记即宣告这 9 条属**受支持**的公共面，需由合同权威确认（含命名/版本/兼容策略）。
2. **反例纪律**：**不得**以"实现已存在"为由**静默登记**——那正是冲突 **C-20** 的成因
   （`KERT_DOCUMENT_CONFLICT_REGISTER.md:44`：权威声明与服务实际不符）。故本提案**只备料、不改合同**。

## 4. 建议的追认范围（供 Contract Owner 勾选）

| 选项 | 内容 | 代价 / 风险 |
|---|---|---|
| **A（推荐）** | 9 条**一次性**登记，版本 `1.5.1 → 1.6.0`（minor，additive） | 需一次性冻结 9 条的请求/响应 schema（本提案已给实现位置，schema 撰写需另立工作量）；收益 = `/v1/*` 面**合同化完整** |
| B | 只登记**有外部/未来调用方**价值的（如 `/v1/catalog`、`/v1/evidence/{id}`、`/v1/search`、`/v1/entities/{id}`），其余 5 条保持未登记 | 合同面仍不完整（F8 部分关闭）；须显式记录"未登记但已实现"豁免清单 |
| C | 全部**不登记**，改为在合同头部显式声明"内部/实验性端点不属合同面" | 诚实但留覆盖缺口；需明确这些端点**不享有**兼容性承诺（对 GITS 无害，对后续调用方是信息缺失） |

## 5. 需 Owner 一并裁决的 2 项附带事项

### 5.1 `GET /v1/skills` 声明了但**未实现**（反向缺口）

> ✅ **已结案（Owner 裁定 A-9，2026-09-16）**：采纳"**删除声明**"选项 —— 该端点**已从合同删除**
> （`specs/kert-openapi-v1.yaml` 1.6.0；合同不得声明不存在的端点）。
> 同轮已同步 4 处孤儿引用：`examples/gits_adapter/python/kert_client.py`（标注 + 抛错）、
> `examples/gits_adapter/curl/list_skills.sh`（**删除**）、`examples/gits_adapter/README.md`（3 处，删除的**派生**必要同步）、
> `docs/development/M3_PLAN_GITS_INTEGRATION.md`（2 处）。
> 本小节以下的**分析**保留，作为结案依据。

- 合同 `:130-163` 声明该路径与 `SkillListResponse`/`SkillInfo`；实现**无**该路由
  （`server.py` 全量 `/v1/*` 路由见 §2；证据：`docs/integration/KERT_GITS_CONTRACT_DIFF.md:14`「规范要求新增，server.py 尚未实现」、`:96` P2 待做）。
- 三选一：**删除**声明 / 标记 `x-implemented: false` 并保留（推荐，信息不丢失）/ 实现它。
- 现况影响：该路径**被参考客户端使用**（`examples/gits_adapter/python/kert_client.py:199-201` 的 `list_skills()`）⇒ 属"文档-实现-样例"三方不一致，建议与 §2 一并处理。

### 5.2 `/v1/graph/query` 与 v2 既有声明的形状差异

- v2 已声明该路径（`docs/contracts/openapi/kert-openapi-v2.yaml:177-194`，`GraphQueryRequest`/`GraphQueryResponse`，v2:521-567）：
  `required [start_entity_ids, mode]`、`max_depth` **maximum 10**、`max_nodes` **maximum 1000**、含 `service`。
- 实现 `GraphRequest`（`server.py:177-187`）：`required [request_id, start_entity_ids]`、`mode` 默认 `neighbor`、
  额外有 **`as_of`**（v2 无）、`max_depth` 默认 **1**、`max_nodes` 默认 **100**（**无 maximum 上界声明**）。
- ⇒ 若选 A/B 登记，须明确**以实现为准**并逐项说明与 v2 的差异（否则登记动作本身会与 v2 制造新的双口径，
  重演 C-20）。

## 6. 建议随追认一并交付的**防复发**机械核对

在 `tests/integration/test_contract_shape_conformance.py` 增加一条集合断言（当前**未加**，待追认后随登记一起落）：

```text
合同声明的 /v1/* 路径集合  ==  实现的 /v1/* 路由集合  ±  显式豁免清单（须逐条写理由）
```

理由：F8 这类"实现有、合同无"的缺口，单靠逐用例形状核对**永远发现不了**（没有用例就没有核对对象）；
只有**集合级**断言能在新增路由而忘记登记时立刻变红。

## 7. 非声明

本提案**不是** Contract Owner 批准、**不构成**合同修订；**未修改** `specs/**`、`src/**`、`tests/**`、
`docs/contracts/**`、GITS 仓任何文件；不代表生产就绪、不代表 GITS UAT 通过；
v1↔v2 归并**仍未执行**（冲突 C-20 保持 `OPEN`）。
