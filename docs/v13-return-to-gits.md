# v1.3 回传 GITS 交付包（DKWS 侧）

> 日期：2026-08-22 ｜ 版本：v1.3 数据所有权 ｜ 主联调客户：`CUST-CORP-0001` 华东精工装备集团有限公司

## 1. 契约修订说明

### 1.1 evidence 语义（R1 / 供应链图谱 Skill）
- `phase=evidence` 的 `ok`/`skipped` **只反映 DKWS 客户知识库**（`customer_knowledge` 服务投影）对
  该 `customerId` + `kiId` 是否取到数。
- 已删除文案：「已使用 request.knowledgeContext / structuredFacts.profile」等；现有文案
  `读取知识条目 KI-xxx（…），取数完成：DKWS 知识库命中` 与 `知识库无该客户/KI 数据，标记待核实（skipped）`。
- 请求里没有 `structuredFacts`/`knowledgeContext`/`supplyChainMarkdown` **不会**导致 skipped；
  旧字段如仍传入将被忽略（不参与判定）。
- 库无该客户或该 KI → `skipped`（待核实），不编造成功；`assemblyTrace` 仅为 Debug。

### 1.2 R1 / 供应链图谱输入（gits 侧）
- `skill-customer-previsit-report` 请求只带：`customerId`（必填）+ `evidenceTimestamp`（必填，无新证据策略）
  + 可选 `visitObjective`（拜访意图，非客户事实）。
- `bank-front-supply-chain-graph` 请求只带：`customerId`。
- gits **不得**再传 `knowledgeContext` / `structuredFacts` / `supplyChainMarkdown` 充当 KI 证据。

### 1.3 R1 `data.sections` 按 KI 出章
- 每个命中的 KI 一节：`heading` 含 KI 编号与稳定标题（如 `KI-009 企业客户基本信息`），`content` 为库中原文。
- 未命中的 KI 不出节（不凑假正文）。gits 按 heading 对位展示，**不解析 DKWS HTML 报告页**。

### 1.4 无新证据策略（保留）
- R1 未传 `evidenceTimestamp` → `exit_policy_no_new_evidence`；
- 传但 ≤ 该 customerId 服务进程内最新 → `exit_policy_no_new_evidence`；
- 传且更新 → 正常执行并记录（进程内记忆，重启清空）。

## 2. 交付物 A — CRM 客户主档夹具

路径：`docs/dd/gits-crm-customer-master.json`（DKWS 源：`dkws/examples/output/gits-crm-customer-master.json`）

- 本次新增/变更的 customerId 清单：**`CUST-CORP-0001`（新增）、`CUST-CORP-0002`（新增，华东新能源汽车有限公司，为 0001 的关键下游客户，演示跨客户上下游链）**
- 字段约束已内建校验（枚举/日期 YYYY-MM-DD/金额人民币元整数/字符串数组），写中文会直接校验失败：
  `industry ∈ {MANUFACTURING|FINANCE|TECHNOLOGY|REAL_ESTATE|ENERGY|HEALTHCARE|AGRICULTURE|LOGISTICS|RETAIL|OTHER}`、
  `enterpriseScale ∈ {LARGE|MEDIUM|SMALL|MICRO}`、`customerTier ∈ {STRATEGIC|KEY|GROWTH|GENERAL}`、
  `listedStatus ∈ {LISTED|UNLISTED|DELISTED}`、`riskLevel ∈ {HIGH|MEDIUM|LOW}`。
- 已同步：gits `docs/dd/gits-crm-customer-master.json`（另保留旧名 `crm_customers.json` 副本）。

## 3. 交付物 B — 运行时 upsert 接入状态

| 项 | 状态 |
|---|---|
| 目标接口 | `PUT {GITS_BASE}/api/v1/engagement/customer/{customerId}`，Body = 单条客户对象，语义 = 按 customerId upsert；Header `X-API-KEY`（可选） |
| DKWS 造数脚本 | 已接入：`scripts/seed_customer_knowledge.py --gits-base <URL> [--api-key <KEY>]`（或环境变量 `GITS_BASE` / `GITS_API_KEY`） |
| 幂等 | 是（PUT upsert；脚本可重复执行，每次生成新 run_id 落库 + 重放 upsert） |
| 失败策略 | upsert 任一失败仅告警，**不阻断造数**（GITS upsert 未发布/不可达时，造数与交付物 A 照常完成） |
| 当前调用 | **未调用**（本次运行未配置 `--gits-base`，仅产出夹具 + customerId 清单） |
| 过渡期 | GITS upsert 发布前，可先灌 `gits-crm-customer-master.json`；过渡期也可用既有 `POST /api/v1/engagement/customer`（201），但重复 ID 可能失败——正式以 PUT upsert 为准 |
| H2 内存库 | GITS 重启后需重新 upsert 或重灌夹具；造数脚本幂等可重复执行 |

配置示例：
```bash
GITS_BASE=http://172.22.90.134:8080 GITS_API_KEY=<key> \
  .venv/bin/python scripts/seed_customer_knowledge.py -w demo_workspace
```

## 4. 逐 customerId 的 7 条 KI 命中情况表

| customerId | 客户 | KI-009 | FRONT-001 | FRONT-002 | FRONT-003 | FRONT-004 | FRONT-005 | FRONT-006 | 图谱 Skill |
|---|---|---|---|---|---|---|---|---|---|
| CUST-CORP-0001 | 华东精工装备集团有限公司 | ok | ok | ok | ok | ok | ok | ok | complete（7 节点/6 边） |
| CUST-CORP-0002 | 华东新能源汽车有限公司 | ok | ok | ok | ok | ok | ok | ok | complete（7 节点/6 边，上游含 0001） |

> 生成方式：`CustomerKnowledgeProvider(workspace).ki_map(customerId)` + `supply_chain(customerId)`（确定性，无 LLM）。
> 两家客户互为上下游（0001 供应 0002），Kùzu 图谱 12 节点 / 11 边（去重后）。

## 5. 真实 execute 样例（无 structuredFacts）

### 请求
```json
{
  "skillId": "skill-customer-previsit-report",
  "requestId": "return-sample-0001",
  "request": { "customerId": "CUST-CORP-0001", "evidenceTimestamp": "2026-08-22T13:00:00Z" }
}
```

### 响应（摘要，status=ok，sections 7 节按 KI 出章）
```json
{
  "requestId": "return-sample-0001",
  "status": "ok",
  "data": {
    "reportTitle": "华东精工装备集团有限公司访前报告",
    "executiveSummary": "……（模型生成，基于知识库取数）",
    "sections": [
      { "heading": "KI-009 企业客户基本信息", "content": "华东精工装备集团有限公司（统一社会信用代码 91330000MA27DEMO，成立于 2005-03-15…）" },
      { "heading": "KI-FRONT-001 公司供应链图谱", "content": "上游供应商…华鑫轴承材料集团…下游客户…华东新能源汽车…" },
      { "heading": "KI-FRONT-002 产业链八维研判", "content": "①产业链位置…②需求景气…" },
      { "heading": "KI-FRONT-003 行内变动行为", "content": "近 12 个月行内变动…" },
      { "heading": "KI-FRONT-004 事实承诺事项 / 沟通话术", "content": "近期沟通记录与承诺…" },
      { "heading": "KI-FRONT-005 KYC 信息缺口", "content": "KYC 缺口…" },
      { "heading": "KI-FRONT-006 产品候选组合", "content": "产品候选组合…" }
    ],
    "evidenceRefs": [ { "id": "KI-009", "summary": "企业客户基本信息（DKWS 知识库）" }, "…" ],
    "reportUrl": "/api/skill/report/return-sample-0001"
  },
  "errors": [],
  "assemblyTrace": [
    { "phase": "resolve", "status": "ok", "message": "skillId=skill-customer-previsit-report requestId=return-sample-0001" },
    { "phase": "evidence", "status": "ok", "message": "进入知识地图 KM-CORP-RM-PREVISIT，任务 PRE_VISIT_PREPARATION" },
    { "phase": "evidence", "status": "ok", "kiId": "KI-009", "message": "读取知识条目 KI-009（企业客户基本信息），取数完成：DKWS 知识库命中" },
    { "phase": "evidence", "status": "ok", "kiId": "KI-FRONT-001", "message": "读取知识条目 KI-FRONT-001（公司供应链图谱），取数完成：DKWS 知识库命中" },
    "…（KI-FRONT-002～006 同 ok）…",
    { "phase": "dkws", "status": "ok", "message": "DKWS 客户知识库检索完成（CUST-CORP-0001 命中 7 条 KI）" },
    { "phase": "model", "status": "ok", "message": "模型调用完成" },
    { "phase": "compose", "status": "ok", "message": "结果组装完成" }
  ],
  "modelCalls": [ { "model": "deterministic_fallback", "inputTokens": 0, "outputTokens": 0, "latencyMs": 0 } ]
}
```
> 本样例为离线确定性适配器回放；线上 8106 接真实 DeepSeek（`deepseek-chat`，见 `modelCalls[0].model`）。
> 完整真实响应可在 8106 复现：同上请求重发（换 requestId + 更新 evidenceTimestamp）即得。

## 6. 供应链图谱样例（库构建，无 LLM）

```json
{
  "skillId": "bank-front-supply-chain-graph",
  "request": { "customerId": "CUST-CORP-0001" }
}
```
→ `data.result`: `buildStatus=complete`，`nodes` 7（enterprise 1 / supplier 3 / customer 3），`edges` 6，
`interpretation` 含 supplyChainPosition / bargainingPower / concentrationRisk / keyChanges / overallAssessment /
followUpQuestions / confidence，`modelCalls[0].model = "library"`（确定性库构建，非 LLM）。

## 7. 验收对照（DKWS 已自测通过）
- ✅ 仅 customerId + evidenceTimestamp 调 R1：evidence 7/7 ok 与库一致；message 不提 request.structuredFacts
- ✅ sections heading 可对位 KI-009 / KI-FRONT-001～006
- ✅ 仅 customerId 调图谱：result 来自平台库（complete 7 节点/6 边；未知客户 partial 空图不虚构）
- ✅ 夹具 customerId/customerName/unifiedSocialCreditCode/rmId 与 KI-009 身份段一致
- ✅ 新增客户规则：夹具（及 upsert）与知识库、图节点同天更新；无「图里有、CRM 没有」的客户（当前仅 1 户）
- ✅ 测试：`tests/integration/test_skills.py` 25 用例 + 全量集成 117 用例绿
