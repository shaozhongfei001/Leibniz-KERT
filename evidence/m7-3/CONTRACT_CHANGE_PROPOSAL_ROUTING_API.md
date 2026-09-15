# 合同变更提案：知识路由与激活计划 API（v1.4.0 → v1.5.0）

```text
PROPOSAL_ID : M7-3-4-CONTRACT-ROUTING-API
ISSUED_BY   : Tech Lead
ISSUED_AT   : 2026-09-15
TARGET      : specs/kert-openapi-v1.yaml
STATUS      : TL 提案；**已按本提案先行推进实现**（additive），**待 Contract Owner 追认**
AUTHORITY   : docs/governance/KERT_PENDING_OWNER_DECISION_M7_EVOLUTION_V1.0.md §0（D1-A）
              独立评审 §4.7（KnowledgeMapRegistry / RoutePolicy / ActivationPlan + 版本合同）
```

## 1. 变更内容（**仅新增**，不改任何既有端点与字段）

| # | 变更 | 说明 |
|---|---|---|
| 1 | 新 tag `Routing` | "知识路由与激活计划" |
| 2 | `GET /v1/knowledge-maps` | 列出本工作区注册的知识地图（含地图/策略版本） |
| 3 | `GET /v1/knowledge-maps/{mapId}` | 单张地图详情（资产/Skill 引用、版本）；未知 ⇒ **404** |
| 4 | `POST /v1/routing/plan` | 输入 `taskType`（+可选 `subjectId`）⇒ 返回**激活计划**或**显式拒绝** |
| 5 | 新 schema | `RoutingPlanRequest`、`KnowledgeMapSummary`、`KnowledgeMapListResponse`、`KnowledgeMapDetail`、`ActivationPlan`、`PlanAsset`、`PlanDenial`、`RoutingPlanResponse` |
| 6 | `info.version` | `1.4.0` → `1.5.0`（additive 小版本） |

## 2. 关键设计决定（含理由，供追认时逐条核对）

| 决定 | 选择 | 理由 |
|---|---|---|
| **改哪份规范** | 改 `specs/kert-openapi-v1.yaml`（运行中权威，`version 1.4.0`） | `docs/contracts/openapi/kert-openapi-v2.yaml` 自述为 **"Phase 0 候选，不表示生产合同已批准"**；改候选而不改运行合同会让"实现照合同"这一纪律失去对象。v2 归并属后续独立议题（见 §5） |
| **路径前缀** | `/v1/*` | 与既有知识服务面一致（`/v1/health`、`/v1/catalog`、`/v1/search`、`/v1/evidence/{id}`）；`/api/skill/*` 是 Skill 执行面，路由属控制面读 |
| **响应信封** | 复用 `_response()`（`request_id/status/data/errors/meta`） | 与 `/v1/*` 既有端点一致；`/api/skill/*` 的裸响应不改 |
| **拒绝用 200 + `denial`** | `POST /v1/routing/plan` 返回 **200**，body 内 `allowed:false` + `denial{code,reason}` | **拒绝是预期业务结果**（默认拒绝/歧义拒绝），不是协议错误；若改 4xx，调用方需为"正常的拒绝"解析错误体，且会与真正的基础设施错误混淆。**"没有第三态"**：`allowed` 只可能是 `true`（带 plan）或 `false`（带 denial） |
| **未知 mapId 用 404** | `GET /v1/knowledge-maps/{mapId}` ⇒ 404 | 这是**协议级"资源不存在"**，与被拒的计划不同，理应 404 |
| **拒绝码不复用** | `ROUTE_*` / `KNOWLEDGE_MAP_*` / `ONTOLOGY_REFERENCE_*` 三族并列 | 拒绝原因必须可区分（已有用例钉住 `ONTOLOGY_REFERENCE_INVALID != ONTOLOGY_REFERENCE_ABSENT`） |
| **鉴权** | 沿用既有 `ApiKeyAuth` 中间件；不新增开关 | 遵守"未通过安全 Gate 前不放松"的既有纪律；本提案**不**引入新的鉴权语义 |

## 3. 兼容性

- **向后兼容**：全部为新增路径与新增 schema；既有路径、字段、状态码、错误码**零改动**；
- **不破坏**：`/api/skill/execute`（GITS 现行调用面）不受影响；本提案**不**要求调用方切换；
- 版本语义：`1.4.0 → 1.5.0` 表示 additive 增量（与既有 v1.3→v1.4 的增量记法一致）。

## 4. 与 v2 候选的关系（**不在本提案范围内**）

`docs/contracts/openapi/kert-openapi-v2.yaml`（`2.0.0-candidate`）与本规范存在**双权威**风险，
且 `KERT_STATUS_BASELINE_CANDIDATE.yaml` 记 `v13`/`v14` 为 `CONFLICTING`、`openapi_v2_candidate` 为
`DESIGNED_AS_CANDIDATE`。**本提案不解决该冲突**，只在运行中权威上做 additive 增量；
v1↔v2 归并需 Contract Owner 单独立项（建议列入 W8/Phase 0 收口）。

## 5. 非声明

- 本提案**不是** Contract Owner 批准、**不是**规格修订、**不是** ADR；
- 提案**本身不使任何合同生效**；实现按本提案先行推进的事实**不代表**合同已被追认；
- 不声称生产就绪、不声称 GITS UAT 通过；未修改 GITS 仓；未 push（`AGENTS.md` 规则 #10）。
