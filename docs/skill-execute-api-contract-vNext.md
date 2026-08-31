# DKWS Skill 执行 API 契约 vNext（SP-15 产品推荐执行契约细化）

> 文档编号：`DKWS-SKILL-EXEC-CONTRACT-VNEXT`
> 版本：vNext（2026-08-31）｜ 前置：v1.3（数据所有权）→ v1.4（SP-20/SP-21/异步/闸门）
> 范围：SP-15 产品适配与综合方案（三段式产品推荐）执行契约细化
> 权威契约对齐：`specs/dkws-openapi-v1.yaml`（SkillExecuteRequest/Response）、GITS `specs/product-recommendation/recommendation-result.schema.json`、本仓 `skills/product-recommendation/contracts/recommendation-result.md`

```text
DOC_STATUS=CANDIDATE
FROZEN=NO
IMPLEMENTED=NO
REAL_E2E_PASS=NO
BASELINE_STATE=APPROVED_WITHOUT_FREEZE
```

---

## 0. 取证说明（先取证，后结论）

本契约依据以下**当前可核验**的权威文件形成，未虚构任何路径：

| 顺位 | 输入 | 当前状态 | 用途 |
|---|---|---|---|
| 1 | `specs/dkws-openapi-v1.yaml` | 已落地（未提交） | SkillExecuteRequest/Response、Job 轮询、8 个 KERT_* 错误码 |
| 2 | `skills/product-recommendation/SP-15.md` | 已落地（未提交） | SP-15 输入/输出合同、不变量、失败码 |
| 3 | `skills/product-recommendation/contracts/recommendation-result.md` | 已落地（未提交） | `data.result` = ProductRecommendationResult 的最小结构与必填证据 |
| 4 | GITS 三段式落地方案 V1.0 §7.4/§7.5/§9 | 设计候选 | 执行语义、失败码 GITS 处理、EvidenceBundle 必含项 |

**已识别的缺口（如实报告，不阻断本契约）**：本任务引用的 GITS 侧 `specs/product-recommendation/recommendation-result.schema.json`、`specs/product-recommendation/`（6 schema + README）、`specs/openapi/product-recommendation.openapi.json`、`specs/knowledge-architecture/activations/AC-PRODUCT-RECOMMEND-001.json` 及 `specs/CONTRACT_INDEX.yaml` 中的 `CTR-PR-*` 条目，在**当前 gits-cbanking 工作树中不存在**。因此 `recommendation-result.schema.json` 的对齐目标采用本仓权威镜像 `contracts/recommendation-result.md`（该文件已声明与 GITS 该 schema 对齐），并在字段上严格保持一致。schema.json 落地后须做一次 contract-diff 回验。

---

## 1. 目的与范围

本文件是 SP-15「产品适配与综合方案」在 DKWS Skill 执行通道上的**契约细化**，回答：

1. SP-15 的 `SkillExecuteRequest` 请求结构（含 `request.context` 快照引用）；
2. SP-15 的 `SkillExecuteResponse` 响应结构（`data.result` = `ProductRecommendationResult`）；
3. 8 个 `KERT_*` 错误码及其 GITS 处理语义；
4. `EvidenceBundle` 必含引用项；
5. 同步/异步执行与 `/v1/jobs/{jobId}` 轮询约定。

**不在本契约**：三段式业务状态机（`ProductRecommendationRun` 状态由 GITS Domain 管理）、HG-D01 人工决策（GITS 主责）、授信/定价/审批/写回动作（禁止由 Skill 直接触发）。

**边界声明**：SP-15 输出为「产品适配/组合子方案」，不是完整客户服务建议书，也不代表任何授信/定价/产品/合规审批。SP-15 保持为 GITS 看到的稳定业务门面，KERT 内部拆成 9 个可观测步骤（见 `SP-15.md` §3），不向 GITS 暴露多个不稳定 Skill。

---

## 2. 执行端点与认证（沿用 v1.3/v1.4，不新增）

| 项 | 精确值 |
|---|---|
| 执行端点 | `POST /api/skill/execute` |
| 异步轮询 | `GET /v1/jobs/{jobId}` |
| 健康检查 | `GET /v1/health` / `GET /api/skill/health` |
| Content-Type / Accept | 请求 `application/json`；响应 `application/json` |
| 认证 | 沿用 `X-API-Key`（ApiKeyAuth，演示环境可省略）；权限继承调用人，不允许 KERT 扩大数据范围 |

---

## 3. 请求结构（SkillExecuteRequest → SP-15）

`SkillExecuteRequest` 顶层字段（对齐 `docs/contracts/schemas/skill-execute-request.schema.json`）：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `skillId` | string | ✅ | 固定 `SP-15` |
| `requestId` | string | ✅（生产） | 幂等键；同 `requestId` 重发复用首次结果/同一 job（TTL 内） |
| `async` | boolean | ❌ | 缺省 `false`（同步）；长任务建议 `true` |
| `request` | object | ✅ | 业务上下文容器；SP-15 传 `request.context` |
| `context` | object | ❌ | 顶层 context（v1.3 兼容）；与 `request.context` 二选一，服务端合并时 `request.context` 优先 |

### 3.1 `request.context`（SP-15 上下文快照，必填）

```json
{
  "skillId": "SP-15",
  "requestId": "REC-20260831-0001",
  "async": true,
  "request": {
    "context": {
      "schemaVersion": "1.0.0",
      "customerId": "CUST-001",
      "needVersionIds": ["NEEDV-001"],
      "recommendationObjective": "补充流动资金与跨境结算方案",
      "requestedProductDomains": ["FINANCING", "SETTLEMENT"],
      "asOf": "2026-08-31T09:00:00+08:00",
      "customerFactSnapshotId": "CFS-20260831-0001",
      "productKnowledgeSnapshotRef": "PKS-20260831-0001",
      "ruleBundleRef": "RB-20260831-0001",
      "permissionDecisionId": "PERM-20260831-0001",
      "activationContract": "AC-PRODUCT-RECOMMEND-001"
    }
  }
}
```

`request.context` 字段语义：

| 字段 | 类型 | 必填 | 语义 |
|---|---|---|---|
| `schemaVersion` | string | ✅ | 上下文包版本，`"1.0.0"` |
| `customerId` | string | ✅ | 客户 ID |
| `needVersionIds` | string[] | ✅ | 已核验需求版本 ID 集合（`NeedVersion`） |
| `recommendationObjective` | string | ✅ | 推荐业务目的，禁止空泛「给我推荐产品」 |
| `requestedProductDomains` | string[] | ✅ | 请求产品域（如 `FINANCING`/`SETTLEMENT`） |
| `asOf` | string(date-time) | ✅ | 业务时点（事实/知识/规则均以此时点为准） |
| `customerFactSnapshotId` | string | ✅ | 客户事实快照引用（快照引用 1/3） |
| `productKnowledgeSnapshotRef` | string | ✅ | 产品知识快照引用（快照引用 2/3） |
| `ruleBundleRef` | string | ✅ | 规则包引用（快照引用 3/3） |
| `permissionDecisionId` | string | ✅（生产） | 权限决策引用 |
| `activationContract` | string | ✅（生产） | 固定 `AC-PRODUCT-RECOMMEND-001` |

**快照引用（3 个必含）**：`customerFactSnapshotId`、`productKnowledgeSnapshotRef`、`ruleBundleRef`。三者固化本轮使用的客户事实、产品/规则版本，支持重放与过期判断。缺失任一快照引用 → 输入校验失败，返回 `KERT_CONTRACT_MISMATCH`（fail-closed）。

**复用与新鲜度**：同一客户、同一 `asOf`、同一权限、同一数据与知识版本的 ContextPackage 可显式复用；不得仅凭 ID 存在就跳过新鲜度与权限校验。

---

## 4. 响应结构（SkillExecuteResponse → data.result = ProductRecommendationResult）

顶层结构（对齐 `docs/contracts/schemas/skill-execute-response.schema.json`）：

```json
{
  "requestId": "REC-20260831-0001",
  "status": "ok",
  "data": {
    "skillId": "SP-15",
    "reportUrl": "/api/skill/report/REC-20260831-0001",
    "result": { /* ProductRecommendationResult，见 §4.1 */ }
  },
  "errors": [],
  "assemblyTrace": [],
  "modelCalls": []
}
```

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `requestId` | string | ✅ | 回显请求幂等键 |
| `status` | string | ✅ | 枚举 `ok` / `skill_error` / `exit_policy_no_new_evidence` |
| `data` | object | ✅ | 成功含 `skillId`/`reportUrl`/`result`；失败时 `{}` |
| `errors` | array | ✅ | 成功 `[]`；失败含 `{code, message, detail?}`，`code` 见 §5 |
| `assemblyTrace` | array | ✅ | 知识装配轨迹（phase/status/message，可选 kiId） |
| `modelCalls` | array | ✅ | 模型调用记录（model/inputTokens/outputTokens/latencyMs） |

### 4.1 `data.result` = ProductRecommendationResult

对齐 `contracts/recommendation-result.md`（= GITS `recommendation-result.schema.json`）。最小结构：

```json
{
  "schemaVersion": "1.0.0",
  "runId": "REC-XXX",
  "skillId": "SP-15",
  "skillVersion": "2.0.0-candidate",
  "productKnowledgeSnapshotRef": "PKS-XXX",
  "ruleExecutionRef": "RULE-RUN-XXX",
  "evidenceBundleId": "EVB-XXX",
  "contentHash": "sha256:...",
  "traceId": "TRACE-XXX",
  "eligibilityResults": [],
  "fitResults": [],
  "portfolioCandidates": [],
  "needProfile": [],
  "unknowns": [],
  "conflicts": [],
  "generatedAt": "2026-08-31T09:00:00+08:00"
}
```

**必填字段（8 个，机器校验点）**：

| 字段 | 语义 |
|---|---|
| `schemaVersion` | 结果 schema 版本 |
| `runId` | 本轮推荐运行 ID |
| `productKnowledgeSnapshotRef` | 产品知识快照引用 |
| `ruleExecutionRef` | 规则执行轨迹引用 |
| `evidenceBundleId` | 证据包 ID |
| `contentHash` | 结果内容哈希（`sha256:...`） |
| `traceId` | 执行轨迹 ID |
| `generatedAt` | 生成时间 |

**关键数组**：

| 数组 | 元素要点 |
|---|---|
| `eligibilityResults[]` | 每产品 `productId/productVersion/eligibility/ruleResults/unknowns/reviewRequirements`；`eligibility ∈ {ELIGIBLE, INELIGIBLE, UNKNOWN, REVIEW_REQUIRED}` |
| `ruleResults[]` | 每条必须 `ruleId + ruleVersion + inputFactRefs + result + reasonCode`（+ `evidenceRefs`） |
| `fitResults[]` | 仅 `ELIGIBLE` 产品；`rank/fitScore/dimensionMatches/matchedNeeds/recommendationReasons/conditions/materialGaps/riskNotes/salesBoundaries` |
| `portfolioCandidates[]` | `portfolioId/primaryProduct/supportingProducts/dependencies/conflicts/recommendationCategory` |
| `needProfile[]` | `needId/needStatus/evidenceRefs`；`needStatus ∈ {VERIFIED_FACT, HUMAN_CONFIRMED, INFERRED_NEED, UNKNOWN, CONFLICT}` |

**机器可测不变量（fail-closed，本契约硬性）**：

```text
INV-01 Active(ProductVersion)=false → 不得进入正式候选
INV-02 Eligibility=INELIGIBLE → rankScore/fitScore = null   ← 反例样例见 contracts/examples/invalid-sp15-ineligible-with-score.json
INV-03 Eligibility=UNKNOWN → 不得按 ELIGIBLE 处理
INV-04 CandidateReason → 至少一条 EvidenceRef
INV-05 HardRule → 一个已批准 Owner + 一个权威来源
INV-07 KERT 不可达 → 禁止 GITS 本地生产推荐回退
INV-08 ProductVersion/RuleVersion 变化 → 下游 STALE
INV-09 AI 输出 → 不得直接创建授信/定价/审批/写回动作
INV-10 权威证据冲突 → 禁止确定性解读
```

---

## 5. KERT_* 错误码（8 个）

`errors[].code` 在 `specs/dkws-openapi-v1.yaml` `ErrorDetail.code` 已登记。SP-15 专属 8 个语义及 GITS 处理：

| 错误码 | 语义 | GITS 处理 |
|---|---|---|
| `KERT_PERMISSION_DENIED` | 权限不允许 | run=`FAILED_CLOSED`，不重试 |
| `KERT_CONTEXT_INSUFFICIENT` | 必须事实不足 | run=`HELD/NEEDS_DATA`，生成核实任务 |
| `KERT_PRODUCT_KNOWLEDGE_STALE` | 产品知识版本失效 | run=`FAILED_CLOSED`，通知知识 Owner |
| `KERT_RULE_VERSION_MISSING` | 规则不可复现 | run=`FAILED_CLOSED` |
| `KERT_EXECUTION_TIMEOUT` | 技术超时 | 保留 attempt，按策略重试，不启用本地推荐 |
| `KERT_CONTRACT_MISMATCH` | 输入或输出不符合合同 | run=`FAILED_CLOSED`，触发契约告警 |
| `KERT_EVIDENCE_INCOMPLETE` | 结果缺乏必要证据 | 不创建 HG-D01 |
| `KERT_INTERNAL_ERROR` | 未分类技术错误 | 技术重试后仍失败则关闭本轮 |

**通用码沿用**：`INVALID_PARAMETER` / `SKILL_NOT_FOUND` / `SKILL_EXECUTION_ERROR` / `CONTEXT_VALIDATION_ERROR` / `GATE_CHECK_FAILED` / `JOB_NOT_FOUND` / `INTERNAL_ERROR`（见 openapi §ErrorDetail）。

**fail-closed 原则**：`KERT_CONTEXT_INSUFFICIENT` 不得被软评分覆盖；`KERT_PRODUCT_KNOWLEDGE_STALE` / `KERT_RULE_VERSION_MISSING` 时整轮不得产出可批准方案。

---

## 6. EvidenceBundle 必含引用项

`evidenceBundleId` 指向的 `EvidenceBundle` **至少覆盖**（缺失 → `KERT_EVIDENCE_INCOMPLETE`）：

| 必含项 | 语义 |
|---|---|
| `customerFactSnapshotId` | 客户事实快照 |
| `productKnowledgeSnapshotRef` | 产品知识快照 |
| `ruleExecutionRef` | 规则执行轨迹 |
| `skillId` + `skillVersion` | Skill 身份与版本 |
| `model` + `promptVersion` | 如使用模型（含提示词版本） |
| `permissionDecisionId` | 权限决策 |
| 每项理由的 `factRefs + knowledgeRefs` | 逐理由的事实/知识引用 |
| 未知项与冲突项 | `unknowns` / `conflicts` |
| `contentHash` + `traceId` + 生成时间 | 内容哈希、轨迹、时间 |

> 「模型置信度 0.82」不能替代证据充分度，也不能作为对客户的推荐理由（INV-04）。

---

## 7. 同步/异步与轮询（/v1/jobs/{jobId}）

### 7.1 同步（缺省）

`async` 缺省或 `false` → `POST /api/skill/execute` 返回 **200** + 完整 `SkillExecuteResponse`。

### 7.2 异步

`async: true` → 返回 **202**：

```json
{ "jobId": "JOB-SKILL-20260831-001", "status": "PENDING" }
```

轮询 `GET /v1/jobs/{jobId}`：

```json
{
  "jobId": "JOB-SKILL-20260831-001",
  "status": "COMPLETED",
  "createdAt": "2026-08-31T09:00:00Z",
  "startedAt": "2026-08-31T09:00:01Z",
  "completedAt": "2026-08-31T09:02:30Z",
  "data": {
    "skill_result": { /* 与同步响应同构的完整 SkillExecuteResponse */ }
  }
}
```

| 项 | 精确值 |
|---|---|
| job 状态枚举 | `PENDING` / `RUNNING` / `COMPLETED` / `FAILED` |
| COMPLETED | `data.skill_result` 为完整 execute 响应（与同步响应同构） |
| FAILED | `error = { code, message }`（`code` 取 §5 错误码） |
| 404 | `jobId` 不存在 |

### 7.3 幂等与重试

- 同 `requestId` 异步任务复用同一 job（TTL 内）；同 `requestId` 重发返回首次结果。
- 超时后先 `GET /v1/jobs/{jobId}` 查询原 execution 状态，不得直接创建重复 job。
- 每次重试产生新 `attemptId`，保留同一业务 run；需刷新事实/产品版本时必须创建新 proposal version 并标记旧版本 `SUPERSEDED`。
- `GET` 与页面刷新不得触发生成或重试。

---

## 8. 样例

| 文件 | 用途 |
|---|---|
| `skills/product-recommendation/contracts/examples/valid-sp15-result.json` | 正向样例：满足 `recommendation-result.schema.json` 必填 8 字段 + 至少一条 `ELIGIBLE` 且 ruleResults 完整 |
| `skills/product-recommendation/contracts/examples/invalid-sp15-ineligible-with-score.json` | 反例样例：故意违反 INV-02（`INELIGIBLE` 产品在 `fitResults` 中 `fitScore` 非 null） |

两个样例均为**纯 ProductRecommendationResult 数据实例**（无额外治理字段，可直接作 schema 校验 fixture）；其状态块（CANDIDATE/FROZEN=NO/IMPLEMENTED=NO）与违反说明见 `contracts/examples/README.md`。

---

## 9. 门禁结论

```text
GATE_DECISION=CANDIDATE
REVIEW_OBJECT=DKWS Skill 执行 API vNext（SP-15 产品推荐执行契约细化）
TARGET_TRANSITION=OWNER_REVIEW_AND_CONTRACT_DESIGN
FROZEN=NO
IMPLEMENTED=NO
REAL_E2E_PASS=NO
```

本契约是**候选**，未冻结、未实现、未经真实 GITS→KERT 联调。允许的下一步：Owner 裁决本契约与 GITS `recommendation-result.schema.json` 的 contract-diff，完成后方可进入真实 HTTP 适配器建设。
