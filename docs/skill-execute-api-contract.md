# DKWS Skill 执行 API 精确契约（gits 侧对接用）

> 版本：**1.3（数据所有权，2026-08-22）**——权威契约在 gits 仓 `docs/dd/skill-execute-api-contract.md` v1.3，本文为 DKWS 实现快照。
> v1.3 核心：知识全在 DKWS（本体 FS + 图 + 检索投影），gits 只传 `customerId`（+ 可选 `evidenceTimestamp`/`visitObjective`）；「gits 组 structuredFacts」废止。
> 依据：当前实际实现 `dkws/src/dkws/api/server.py` + `dkws/src/dkws/application/skills.py` + `dkws/src/dkws/application/customer_knowledge.py`。
> 未实现项以 **未定** 标注，勿猜测。

---

## 1. 端点与认证

| 项 | 精确值 |
|---|---|
| 执行端点 | `POST /api/skill/execute` |
| 健康检查 | `GET /api/skill/health` |
| 版本前缀 | **无**（非 `/v1`） |
| 认证 | **无**（未实现鉴权/API key/CORS 白名单；跨机访问需在网络层控制） |
| Content-Type / Accept | 请求 `application/json`；响应 `application/json` |
| 监听端口 | `serve_api.py` 默认 **8100**（`--port` 可配），由 gits `DSH_BASE_URL` 指向 |
| 超时建议 | 服务端 LLM 适配器 60s；真实模型生成 4–60s；**建议 gits 读取超时 ≥ 120s** |

---

## 2. 请求体顶层

```json
{
  "skillId": "skill-customer-previsit-report",
  "requestId": "req-<uuid>",
  "request": { "customerId": "…", "…": "…" }
}
```

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `skillId` | string | ✅ | 枚举见下 |
| `requestId` | string | ❌ | 幂等键；缺省服务端自动生成 |
| `request` | object(map) | ❌ | 业务上下文（**不平铺顶层**）；缺省 `{}` |

**已注册 skillId（10 个）**：

| skillId | 名称 |
|---|---|
| `skill-customer-outreach-script` | 外联脚本 |
| `skill-customer-meeting-script` | 会面脚本 |
| `skill-customer-previsit-report` | R1 拜访报告 |
| `bank-front-commitment-script` | 承诺话术生成 |
| `bank-front-eight-dimension` | 八维分析 |
| `bank-front-fact-reconciliation` | 事实对账 |
| `bank-front-kyc-gap-check` | KYC 缺口检查 |
| `bank-front-product-recommendation` | 产品推荐 |
| `bank-front-report-assembler` | 报告组装 |
| `bank-front-supply-chain-graph` | 供应链图谱 |

- `rmId / operatingCaseId / journeyId`：**未定**（不识别，传入被忽略）。
- 未知字段策略：`request` 为自由 map，**任意键接受不拒绝**；顶层未知字段被 FastAPI 忽略（非报错）。

---

## 3. 三个 Skill 各自输入（executor 实际读取字段）

| Skill | `request` 内识别字段 | 说明 |
|---|---|---|
| 外联 `…-outreach-script` | `customerId`、`structuredFacts.profile/kyc/visitGoals`、`knowledgeContext` | `visitGoals` 为 list[str]。`channel/purpose/tone`：**未定** |
| 会面 `…-meeting-script` | `customerId`、`structuredFacts.profile/productCandidates/sensitivePoints`、`knowledgeContext` | |
| R1 `…-previsit-report` | `customerId`、`knowledgeContext`、`structuredFacts`、`supplyChainMarkdown`、`evidenceTimestamp` | `evidenceTimestamp` 触发无新证据策略 |

---

## 4. 响应体顶层

```json
{
  "requestId": "req-…",
  "status": "ok",
  "data": {},
  "errors": [],
  "assemblyTrace": [],
  "modelCalls": []
}
```

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `requestId` | string | ✅ | 回显请求幂等键 |
| `status` | string | ✅ | 枚举：`ok` / `skill_error` / `exit_policy_no_new_evidence`（snake_case，无其它值） |
| `data` | object | ✅ | 各 skill 结构见 §5；失败时 `{}` |
| `errors` | list | ✅ | 成功为空；失败含 `{code,message}` |
| `assemblyTrace` | list | ✅ | 见 §6 |
| `modelCalls` | list | ✅ | 失败时 `[]`；见 §6 |

**错误 HTTP 状态**：

| 场景 | 状态码 | Body |
|---|---|---|
| 未知 `skillId` | **404** | 契约结构，`status=skill_error`，`errors[0].code=UNKNOWN_SKILL` |
| 顶层缺 `skillId` / 非法 JSON | **422** | FastAPI 校验错误 |
| 执行失败（模型故障等） | **200** | `status=skill_error` + `errors`（fail-closed，`data={}`） |

---

## 5. 成功 data 结构（实际返回）

| Skill | `data` 字段（类型） |
|---|---|
| 外联 | `scriptTitle`(string)、`sections`(array[{heading,content}])、`callObjectives`(array[string])、`keyMessages`(array[string])、`evidenceRefs`(array[{id,summary}]) |
| 会面 | `agenda`(array[{time,topic}])、`talkingPoints`(array[{title,detail}])、`sensitivePoints`(array[string])、`actionItems`(array[string])、`evidenceRefs`(array) |
| R1 拜访报告 | `reportTitle`(string)、`executiveSummary`(string)、`sections`(array[{heading,content}])、`evidenceRefs`(array[{id,summary}]) |

**所有 Skill 的 `data` 均附加 `reportUrl`（string，v1.2 新增）**：执行成功后指向可视化报告页
`/api/skill/report/{requestId}`（相对路径，同 host）。供应链图谱 Skill 为该字段定制了
Neo4j 风格图谱报告模板；其余 Skill 回退为暗色 JSON 查看页。报告内容取自执行幂等缓存，
**TTL 约 10 分钟**，过期返回 404（需重新执行）。

**`bank-front-supply-chain-graph`（SK-FRONT-002）`data` 结构**：

| 字段 | 类型 | 说明 |
|---|---|---|
| `skillId` | string | `bank-front-supply-chain-graph` |
| `result.schemaVersion` | string | `1.0` |
| `result.buildStatus` | string | `complete` / `partial`（输入不足时降级，不虚构节点） |
| `result.nodes` | array[{id,name,layer,type,annualAmount,share,trend,dataSource,verifyStatus}] | `layer`: `supplier`/`enterprise`/`customer` 三段式 |
| `result.edges` | array[{source,target,relation,direction,annualAmount,share,settlement}] | `relation`: `purchase`/`sale` |
| `result.interpretation` | object | `supplyChainPosition`/`bargainingPower`/`concentrationRisk`/`keyChanges`/`overallAssessment`/`followUpQuestions`/`confidence` |
| `reportUrl` | string | `/api/skill/report/{requestId}` → 定制图谱分析报告页 |

> 未定字段（如需字段化契约，需 DKWS 侧扩展输出 schema 后另行发布）：
> 外联 `scriptId/talkingPoints/riskReminders/closingLine/followUpAction`；
> 会面 `scriptId/kycQuestions/productDiscussions/closingSummary`；
> R1 `customerOverview/kycGapSummary/productSchemes/keyQuestions/riskReminders/visitStrategy/supplyChainMarkdown`。
> 当前这些主题以**文本章节**形式存在于 `sections`，非结构化字段。

---

## 6. assemblyTrace / modelCalls 精确 schema

**`assemblyTrace[]`**（元素字段全为 string）：

| 字段 | 枚举/示例 |
|---|---|
| `phase` | `resolve` / `idempotency` / `evidence` / `validate` / `dkws` / `model` / `parse` / `compose` |
| `status` | `ok` / `failed` / `blocked` / `skipped` |
| `message` | 自由文本（中文，控制台可直接展示） |
| `kiId` | 可选（string，KI 级步骤附加；管道步骤缺省。gits 忽略未知字段即可） |

- `evidence`：知识组装步骤——进入知识地图 + 逐知识条目取数（R1 报告打 7 条 KI：`KI-009` 企业客户基本信息、`KI-FRONT-001` 公司供应链图谱、`KI-FRONT-002` 产业链八维研判、`KI-FRONT-003` 行内变动行为、`KI-FRONT-004` 事实承诺事项、`KI-FRONT-005` KYC 信息缺口、`KI-FRONT-006` 产品候选组合）；有输入 `ok`，无输入 `skipped`（不编造成功）。
- `dkws`：平台知识检索（命中 `ok`；无命中/不可用 `skipped`，fail-open）。

```json
{ "phase": "evidence", "status": "ok", "kiId": "KI-009",
  "message": "读取知识条目 KI-009（企业客户基本信息），取数完成：已使用 request.knowledgeContext / structuredFacts.profile" }
```

**`modelCalls[]`**：

| 字段 | 类型 | 示例 |
|---|---|---|
| `model` | string | `"deepseek-chat"` / `"deterministic_fallback"` |
| `inputTokens` | int | `454` |
| `outputTokens` | int | `506` |
| `latencyMs` | number | `4252.2` |

> `kiId / dataAsset / dataPath`、`role`：**未定**（不存在）。
> 成功响应必有 `assemblyTrace[]` 与 `modelCalls[]`；失败时 `modelCalls=[]`。

---

## 7. 异常与幂等

- **超时/服务不可达**：属 HTTP 网络层；gits 应捕获连接/超时异常（非 200 或 socket 层）→ 回落 `FallbackSkillExecutionAdapter`。服务端不会把"不可达"包装为 `skill_error`。
- **无新证据策略（仅 R1 skill）**：`request.evidenceTimestamp`（string，如 `"2026-08-21T12:00:00Z"`）
  - 未传 → `exit_policy_no_new_evidence`；
  - 传但 ≤ 该 `customerId` 服务进程内已记录最新时间 → `exit_policy_no_new_evidence`；
  - 传且更新 → 正常执行并记录。
- **幂等**：同 `requestId` 重发（进程内存缓存，TTL 10 分钟、上限 500 条）→ 返回首次结果，trace 含 `{"phase":"idempotency","status":"ok","message":"命中缓存（NO_OP）"}`。
  - 注意：**进程重启后缓存清空**（无持久化）。

---

## 8. 版本与稳定性

- **无接口版本号**；契约快照 = `docs/dd/` 两份设计 + 本文档；破坏性变更暂无正式通知机制（建议文档修订 + 发布同步 gits）。
- **大小限制**：FastAPI/uvicorn 默认无 body 上限（供应链大上下文可接受）；建议 gits 侧自设上限（如 10MB）并配长超时。
- 已知小缺陷：`/api/skill/health` 的 `service` 字段写死 `"customer-engagement"`（未随 bank-front 扩展更新；不影响 execute 契约）。

---

## 9. 完整示例

**请求**：

```json
{
  "skillId": "skill-customer-previsit-report",
  "requestId": "REQ-PREVISIT-001",
  "request": {
    "customerId": "HZB0000001234",
    "knowledgeContext": "杭州智造精密齿轮有限公司（91330100MA27XXXXXX），行业 C34，主营新能源汽车变速箱精密齿轮，中游核心制造环节。",
    "structuredFacts": {
      "profile": { "name": "杭州智造精密齿轮有限公司", "industry": "C34" },
      "suppliers": ["浙江轴承集团", "宁波特种钢公司"],
      "customers": ["新能源汽车主机厂A", "变速箱总成厂B"]
    },
    "supplyChainMarkdown": "上游：浙江轴承集团(1.2亿)、宁波特种钢(0.8亿)；下游：主机厂A(2.5亿)、总成厂B(1.8亿)",
    "evidenceTimestamp": "2026-08-21T12:00:00Z"
  }
}
```

**响应（200）**：

```json
{
  "requestId": "REQ-PREVISIT-001",
  "status": "ok",
  "data": {
    "reportTitle": "杭州智造精密齿轮有限公司访前报告",
    "executiveSummary": "……",
    "sections": [ { "heading": "客户概况", "content": "……" } ],
    "evidenceRefs": [ { "id": "profile", "summary": "客户名称、行业分类及主营业务信息" } ],
    "reportUrl": "/api/skill/report/REQ-PREVISIT-001"
  },
  "errors": [],
  "assemblyTrace": [
    { "phase": "resolve", "status": "ok", "message": "skillId=skill-customer-previsit-report requestId=REQ-PREVISIT-001" },
    { "phase": "validate", "status": "ok", "message": "请求校验通过" },
    { "phase": "model", "status": "ok", "message": "模型调用完成" },
    { "phase": "compose", "status": "ok", "message": "结果组装完成" }
  ],
  "modelCalls": [
    { "model": "deepseek-chat", "inputTokens": 454, "outputTokens": 506, "latencyMs": 4252.2 }
  ]
}
```

**报告页示例**（`GET /api/skill/report/{requestId}`，`bank-front-supply-chain-graph`）：
`http://127.0.0.1:8106/api/skill/report/scg-report-demo-0002` → 供应链图谱分析报告
（力导向三段式图谱 + 四类解读卡片 + 节点/边明细表；截图见 `dkws/examples/output/`）。

---

## 10. 变更记录

| 日期 | 变更 |
|---|---|
| 2026-08-21 | 契约 v1.0 快照（对齐当前实现）；修复 `_run_previsit` 回归缺陷（此前 previsit 误返回 skill_error） |
| 2026-08-21 | v1.1：assemblyTrace 升级为 KI 级知识组装轨迹（evidence 步骤逐 KI 取数 + 可选 kiId 字段）；管道步骤保留；真实响应验证通过 |
| 2026-08-21 | v1.2：新增 `GET /api/skill/report/{requestId}` 可视化报告端点（结果取幂等缓存，TTL 10 分钟，过期 404）；所有 execute 响应 `data` 附加 `reportUrl`；`bank-front-supply-chain-graph` 使用定制「供应链图谱分析报告」模板（Neo4j 风格力导向图谱 + 解读卡片 + 明细表），其余 Skill 回退暗色 JSON 查看页；`knowledgeContext` 支持 dict/str（归一化修复） |
| 2026-08-22 | **v1.3（数据所有权）**：evidence ok/skipped 只反映 DKWS 客户知识库对该 `customerId`+`kiId` 是否取到数（删除「已使用 request.knowledgeContext / structuredFacts.profile」文案）；R1 `data.sections` 按命中的 KI 出章（heading 含 KI 编号、content 为库中原文，未命中不凑章）；`bank-front-supply-chain-graph` 只认 `customerId` 从 `customer_knowledge` 服务投影构建 `data.result`（nodes/edges/interpretation/buildStatus，无 LLM，model=library）；R1 无新证据策略保留（`evidenceTimestamp` 未传/未更新 → `exit_policy_no_new_evidence`）；造数脚本 `scripts/seed_customer_knowledge.py` 落库 CUST-CORP-0001 华东精工 7 条 KI + 6 对手方图谱，并产出 CRM 主档投影（`examples/output/crm_customers.json`，已同步 gits `docs/dd/crm_customers.json`）；投影器支持 `x_*` 扩展字段透传（pa.Table 异构键补齐） |

**gits 侧对接（v1.3）**：R1 / 供应链图谱请求只带 `customerId`（+ 可选 `visitObjective` / `evidenceTimestamp`）；`data.sections` 按 heading 对位展示（不解析 DKWS HTML 报告页）；`assemblyTrace` 仅 Debug。CRM 主档灌表：`docs/dd/crm_customers.json`（交付物 A，字段 camelCase，见 §2.2 禁止项）。
