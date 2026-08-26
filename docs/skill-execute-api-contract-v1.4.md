# DKWS Skill 执行 API 契约 v1.4 变更说明

> 版本：v1.4（2026-08-23）｜ 前置：v1.3（数据所有权）
> 范围：SP-20 服务建议书 / SP-21 交互记忆抽取 / 异步作业 / 闸门协作
> 权威契约：`docs/dd/skill-execute-api-contract.md`（v1.3 基线）+ 本变更说明（v1.4 增量）
> 对接样例：`docs/architecture/DKWS-V1.4-GITS-INTEGRATION-SAMPLES.md`

---

## 1. 变更总览（增量、向后兼容）

| # | 变更点 | 位置 | 兼容性 |
|---|---|---|---|
| 1 | 请求新增 `request.context`（ContextPackage） | execute 请求 | 可选；旧技能忽略 |
| 2 | 请求新增 `"async": true` → 202 + jobId | execute 请求/响应 | 可选；缺省同步 |
| 3 | 新增异步轮询 `GET /v1/jobs/{jobId}`（完成含 `data.skill_result`） | 新增端点 | 新 |
| 4 | 响应 `data.result` = ServiceResult（SP-20） | execute 响应 | 新技能专属；旧技能 `data.result` 语义不变 |
| 5 | 响应 `data.ruleViolations`（SP-20 规则校验违规） | execute 响应 | 新字段，GITS 忽略未知字段即可 |
| 6 | 新技能注册：`SP-20 对公客户服务建议书生成`、`SP-21 交互记忆抽取` | health 技能清单 | 新 |
| 7 | 新端点 `GET /api/skill/gates/{customerId}`（GATE-BIZ 清单资产） | 新增 | 新 |
| 8 | 新端点 `POST /api/skill/gates/audit`（闸门决策镜像，非权威） | 新增 | 新 |
| 9 | `reportUrl` 行为不变；SP-20 指向建议书报告模板 | 响应 | 不变 |

## 2. 请求变更

### 2.1 `request.context`（ContextPackage，SP-20/SP-21 专用）

```json
{
  "skillId": "SP-20",
  "requestId": "req-…",
  "request": { "context": { "schemaVersion": "1.0.0", "customerId": "…", "…": "…" } }
}
```

- ContextPackage 完整 schema 见 GITS `docs/architecture/GITS-DKWS-SERVICE-PROPOSAL-APPENDIX-A.md` §A.1。
- **兼容**：单客户技能（R1/图谱/外联/会面）仍只传 `customerId`（v1.3），`context` 可缺省；
  SP-20/SP-21 必须传 `request.context`。
- 顶层 `context` 与 `request.context` 二选一（服务端合并，`request.context` 优先）。

### 2.2 `"async": true`（SP-20 长任务）

```json
{ "skillId": "SP-20", "requestId": "…", "async": true, "request": { "context": { "…": "…" } } }
```

- 响应：**202** `{ "jobId": "JOB-SKILL-YYYYMMDD-NNN", "status": "PENDING" }`
- 轮询：`GET /v1/jobs/{jobId}` → 响应 `data.status ∈ {PENDING,RUNNING,COMPLETED,FAILED}`；
  **COMPLETED 时 `data.skill_result` 为完整 execute 响应**（与同步响应同构）。
- 幂等：同 `requestId` 的异步任务复用同一 job（TTL 内）；同 `requestId` 重发返回首次结果。
- SP-21 为同步快任务（≤60s），无需 async。

## 3. 响应变更

### 3.1 顶层结构不变

`{ requestId, status, data, errors, assemblyTrace, modelCalls }`；
`status ∈ {ok, skill_error, exit_policy_no_new_evidence}`（不新增顶层枚举）。

### 3.2 `data.result`（SP-20 = ServiceResult）

```json
"data": {
  "skillId": "SP-20",
  "reportUrl": "/api/skill/report/{requestId}",
  "result": {
    "schemaVersion": "1.0.0", "skillId": "SP-20", "runId": "RUN-PROPOSAL-…",
    "status": "SUCCESS | PARTIAL",
    "timestamp": "…",
    "content": {
      "proposalDraft": "8 章 Markdown 正文",
      "internalVersion": { "content": "…", "factLabels": { "断言": "F|C|B|H|P|A", "…": "…" } },
      "customerVersion": { "content": "…", "filteringNotes": ["…"], "includes": ["F","A"],
                           "excludes": ["C","B","H","P"], "releaseBlockedUntil": ["G1","G2","G3"] },
      "customerVersionNote": "…"
    },
    "citations": [ { "id": "CIT-0001", "claim": "…", "source": "…", "date": "YYYY-MM-DD",
                     "factLabel": "F|C|B|H|P|A", "chapterRef": "CH01" } ],
    "unknowns": [ { "id": "UNK-0001", "description": "…", "suggestedAction": "…", "relatedChapter": "CH03" } ],
    "limitations": ["…"],
    "gateRecommendations": { "currentGate": "G1", "passedGates": ["G0"], "overallReadiness": "READY|BLOCKED",
                             "checklist": [ { "gate": "G0", "state": "PASSED|READY_FOR_REVIEW|BLOCKED|PENDING",
                                              "name": "证据准备", "checklist": {"must":[…],"forbidden":[…] } } ],
                             "nextGatePrerequisites": […] },
    "ruleViolations": [ { "ruleId": "CITATION_REQUIRED|…", "severity": "BLOCKING", "message": "…" } ]
  }
}
```

- **`result.status=PARTIAL`**：6 条 BLOCKING 规则（CITATION_REQUIRED / NO_UNDISCLOSED_DEGRADATION /
  DUAL_VERSION_PRINCIPLE / GATE_SEQUENCING / FACT_LABEL_MANDATORY / NO_COMMITMENT_WITHOUT_APPROVAL）
  存在违规 → `ruleViolations` 列出违规；顶层 `status` 仍为 `ok`（不返回残缺成功语义变化）。
- **`customerVersion.releaseBlockedUntil`**：G1/G2/G3 全部通过（`proposalContext.gateState.passed` 含之）
  → `[]`，GITS 方可展示/导出对客版。**放行权在 GITS**。

### 3.3 SP-21 `data.result`

```json
"data": { "skillId": "SP-21", "reportUrl": "…",
  "result": {
    "schemaVersion": "1.0.0", "skillId": "SP-21", "interactionId": "…", "status": "SUCCESS|PARTIAL",
    "candidateMemories": [ { "memoryId": "MEM-…", "category": "PREFERENCE|DECISION_PATTERN|RELATIONSHIP|BUSINESS_SIGNAL|EMOTIONAL_STATE",
                             "content": "…", "confidence": 0.0-1.0,
                             "suggestedDecayRule": "NONE|LINEAR|STEP", "evidenceQuote": "…" } ],
    "memoryUpdates": [ { "memoryId": "…", "action": "REINFORCE", "confidenceDelta": 0.05, "reason": "…" } ],
    "memorySupersessions": [ { "memoryId": "…", "supersededBy": "…", "reason": "…" } ],
    "ruleViolations": [ { "ruleId": "CONFIDENCE_CALIBRATION|DECAY_RULE_APPLICATION|DUPLICATE_DETECTION", "severity": "BLOCKING", "message": "…" } ]
  } }
```

- **DKWS 不存记忆**：候选/更新/取代全部交 GITS `InteractionMemoryPort` 持久化（确认/生命周期/衰减在 GITS）。

## 4. 闸门协作端点（新）

| 端点 | 语义 |
|---|---|
| `GET /api/skill/gates/{customerId}` | GATE-BIZ-G0..G5 清单资产（must/forbidden），GITS 渲染闸门页 |
| `POST /api/skill/gates/audit` | 业务闸门决策**镜像**（`{customerId, gate, decision, decidedBy, reason}` → `{recorded:true,…}`，追加 `90_control/audit/gates.jsonl`）。**权威状态机在 GITS**，DKWS 不裁决。 |

## 5. 向后兼容与约束

- v1.3 单客户技能契约完全不变；旧请求字段（structuredFacts 等）继续忽略，不参与判定。
- `data.ruleViolations` / `data.result` 为新增字段；GITS 现有解析器忽略未知字段即可（附录 B 注明）。
- 认证仍无（演示环境网络层控制）；超时建议：同步 ≤ 120s（SP-21 ≤ 60s），SP-20 一律 async。
- **数据所有权（v1.3）延续**：SP-20/21 的 `context` 是组合技能的显式上下文例外，银行内数据只用于生成，
  不落 DKWS 权威库；记忆不落 DKWS；闸门不落 DKWS 决策库。

## 6. 变更记录（追加到主契约）

| 日期 | 变更 |
|---|---|
| 2026-08-23 | **v1.4**：SP-20（服务建议书：ContextPackage 输入 / 逐章生成 / 事实标签 / 双版本 / 6 规则 / 异步 202+jobId）、SP-21（交互记忆抽取：候选/强化/取代 + 3 规则）、`GET /api/skill/gates/{id}`、`POST /api/skill/gates/audit`、`data.result`=ServiceResult、`data.ruleViolations`；全部向后兼容（参考 `docs/architecture/DKWS-V1.4-GITS-INTEGRATION-SAMPLES.md` 真实样例） |
