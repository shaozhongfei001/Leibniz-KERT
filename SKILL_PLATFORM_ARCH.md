# 客户经理持续经营 Skill — DSH 端实现架构（V1.0）

> 依据：`docs/dd/改造-客户经理持续经营Skill-v2-deepseek-harness端需求详细设计.md`（DSH 端，V1.0）
> 与 `docs/dd/改造-客户经理持续经营Skill-v2-当前项目端需求详细设计.md`（gits 端，V1.0）。
> 本文记录 DSH 端工程改造的架构映射与实现裁决，满足 D1-D6 验收。

## 1. 设计文档 → DSH 实现映射

| 设计文档表述 | DSH 实际机制 | 落地 |
|---|---|---|
| `SkillRegistry.register(...)`（读 SKILL.md + main.py） | `ctx.skills` 是技能**文档**注册表（无 executor）；执行器需自建 | 自建 `SkillExecutionRegistry`：skillId → {定义, executor}；同时 `ctx.skills.register()` 注册 SKILL.md 文档供模型可见 |
| `main.py` / `skill_api.py`（Python） | DSH 为 TypeScript/Cordis 工程 | 全部用 **TypeScript** 实现（见 ADR-01） |
| "Typert GATEWAY 暴露 `POST /api/skill/execute`" | Typert 是类型化 RPC 注册表（client↔host），**非 HTTP REST**；HTTP 路由由 `webServer.register` 承担 | HTTP 网关用 `webServer`（Node req/res handler）；Typert 不参与对外 REST（见 ADR-02） |
| `dsh 即运行平台`（常驻 HTTP 服务） | `webServer` 路由注册在 **Host 进程内常驻**，浏览器刷新不影响 | 动态插件 Host 半区注册路由即可；HTTP API 常驻 |
| Skill 内接 DeepSeek/OpenAI | `ctx.llm.stream()` + `agentDefaultModel.currentSelection()` | executor 内统一 `callModel()` 封装 |
| 治理：fail-closed / 无新证据 / 脱敏 | 平台自约束 | executor 层强制（见 §5） |

## 2. 裁决记录（ADR）

| ADR | 决策 | 理由 |
|---|---|---|
| `SKILL-ADR-01` | 平台用 TypeScript 实现（设计文档的 main.py/skill_api.py 为示意，不照搬） | DSH 是 Cordis/TS 工程；skill 资产（SKILL.md）保持文档形态 |
| `SKILL-ADR-02` | HTTP REST 用 `webServer.register`，不引入 Typert 做对外 REST | Typert 面向 client↔host RPC；webServer 是 Host 进程 HTTP 载体 |
| `SKILL-ADR-03` | 首版以动态插件落地（进程内注册），不改 DSH 部署本体 | HTTP API 常驻、可快速端到端联调；生产固化可迁移为部署插件（cordis.yml 行） |
| `SKILL-ADR-04` | skill 资产（SKILL.md）存放于 DKWS 项目 `dkws/skills/customer-engagement/` | 随 DKWS 交付、版本控制；DSH 侧通过已知路径读取注册 |
| `SKILL-ADR-05` | skill 执行可调用 DKWS 知识服务（HTTP 查询）补充知识上下文 | 设计输入契约由 gits 传 `knowledgeContext`；DKWS 为可选增强，不改变契约 |
| `SKILL-ADR-06` | `requestId` 幂等采用短窗内存缓存（同 requestId 重复 → 返回缓存或 NO_OP） | 满足 D3；无持久化需求，进程内缓存足够 |

## 3. 组件设计

```
dkws/skills/customer-engagement/          # skill 资产（SKILL.md 族 + 三个子 skill）
├── SKILL.md                              # 族定义
├── outreach-script/SKILL.md
├── meeting-script/SKILL.md
└── previsit-report/SKILL.md

动态插件 Host 半区（dkws-skill-1）：
├── SkillRegistry                         # skillId → {definition, version, executor}
├── executors/
│   ├── outreach.ts                       # 外联脚本（prompt 组装 + llm + 结构化解析）
│   ├── meeting.ts                        # 会面脚本
│   └── previsit.ts                       # R1 报告（含无新证据策略）
├── gateway.ts                            # webServer 路由：
│   │                                     #   POST /api/skill/execute
│   │                                     #   GET  /api/skill/health
├── model.ts                              # callModel(): llm.stream + usage + 计时 + fail-closed
├── policy.ts                             # 无新证据策略 / 幂等 / 脱敏
└── dkwsClient.ts                         # （可选）DKWS 知识服务查询
```

### 3.1 执行器接口

```ts
interface SkillExecutor {
  skillId: string
  version: string
  run(req: SkillExecuteRequest): Promise<SkillExecuteResult>  // 抛错→skill_error
}
interface SkillExecuteRequest {
  requestId: string
  customerId?: string
  knowledgeContext?: string
  structuredFacts?: Record<string, unknown>
  supplyChainMarkdown?: string
  evidenceTimestamp?: string            // previsit 用：最新证据时间
}
interface SkillExecuteResult {
  requestId: string
  status: 'ok' | 'exit_policy_no_new_evidence'
  data: Record<string, unknown>
  assemblyTrace: Array<{ phase: string; status: string; message?: string }>
  modelCalls: Array<{ model: string; inputTokens: number; outputTokens: number; latencyMs: number }>
}
```

### 3.2 HTTP 契约（与跨端契约 §7.1 一致）

- `POST /api/skill/execute`：请求 `{ skillId, requestId, request: {...} }`；
  响应 `{ requestId, status(ok|skill_error|exit_policy_no_new_evidence), data, assemblyTrace[], modelCalls[] }`；
  错误：未知 skillId → 404；JSON 非法 → 400；模型故障 → 200 + status=skill_error（fail-closed，不返回残缺半成品）。
- `GET /api/skill/health`：`{ status:"ok", skills:[{ skillId, name, version }] }`。

## 4. 三个 Skill

| skillId | 版本 | 产物 data 结构（映射 gits DTO） | 特有输入 |
|---|---|---|---|
| `skill-customer-outreach-script` | 1.0.0 | `{ scriptTitle, sections[], callObjectives[], keyMessages[] }` | customerId / 画像 / 访前目标 |
| `skill-customer-meeting-script` | 1.0.0 | `{ agenda[], talkingPoints[], sensitivePoints[], actionItems[] }` | 产品候选 / 敏感点 |
| `skill-customer-previsit-report` | 1.0.0 | `{ reportTitle, executiveSummary, sections[], evidenceRefs[] }` | knowledgeContext / structuredFacts / supplyChainMarkdown / evidenceTimestamp |

## 5. 治理与纪律（executor 层硬边界）

- **fail-closed**：`callModel()` 任一步骤失败/超时 → 抛错 → 网关返回 `status=skill_error`，`data` 不返回残缺内容；模型不可用不落半成品。
- **无新证据不闭合**：previsit 请求若未携带 `evidenceTimestamp` 或时间不晚于平台已记录的该客户最新证据 → 返回 `exit_policy_no_new_evidence`，不生成"新报告"。
- **机器事实优先**：structuredFacts/知识上下文仅作为数据注入 prompt（注入隔离：不作为控制指令）；输出经 JSON 结构化校验，缺失必填字段 → skill_error。
- **敏感数据**：不落盘 key；日志/错误响应脱敏（ID 引用，不打印完整请求体）。
- **无人值守**：平台默认不对外声明"已批准"；产物为 `humanGate` 性质，响应不携带任何审批状态。

## 6. 验证计划（D1-D6）

| 验收 | 验证方式 |
|---|---|
| D1 health 列出三 skill + 版本 | `GET /api/skill/health` curl |
| D2 execute 返回结构化结果 + trace + modelCalls | 三 skill 各一次 POST，断言字段 |
| D3 requestId 幂等 + fail-closed | 同 requestId 重放（返回缓存）；注入模型故障（临时不可达）→ skill_error |
| D4 无新证据 → exit_policy_no_new_evidence | previsit 不带 evidenceTimestamp / 旧时间 |
| D5 元数据正确、无敏感泄露 | modelCalls 数值断言；日志检查无 key/完整请求 |
| D6 gits 侧真实调用 | 模拟 gits `SkillExecutionPort` 的 HTTP 调用脚本（RestClient 等价 curl/Node fetch）端到端 |

## 7. DKWS 协作（可选增强）

skill 执行前可经 `dkwsClient` 查询 DKWS 平台（`demo_workspace` 知识投影）：
- 实体/声明/证据查询（`/v1/entities/{id}`、`/v1/evidence/{id}`、`/v1/search`）；
- 命中则注入 `knowledgeContext` 增强（附加 evidenceRefs），不命中不影响主流程（fail-open 于 DKWS 侧）。
- 实现为可配置（`DKWS_KNOWLEDGE_URL` 环境变量），默认关闭；不影响 D1-D6。

---

## 8. 落地记录（方案 A：DKWS 承载全部）

> 2026-08-21 经 Owner 确认：Skill 平台为 **DKWS 工程的一部分能力**（非独立插件，非 DSH 运行时插件）。
> 基线：`SKILL-ADR-03/05` 修订为方案 A。

### 8.1 最终职责边界

| 端 | 职责 | 交付 |
|---|---|---|
| **DKWS 工程**（承载全部） | SkillRegistry + 三 executor + 治理 + HTTP 端点 + LLM 适配器 | `src/dkws/application/skills.py`、`src/dkws/infrastructure/adapters/llm.py`、`api/server.py`（`/api/skill/*`） |
| **DSH 工程**（仅资产） | SKILL.md 资产随 DSH `skills/` 目录供 `ctx.skills` 发现注册（模型可见） | `deepseek-harness/skills/customer-engagement/`（4 个 SKILL.md） |
| gits 侧 | HTTP 调用方（`DSH_BASE_URL` 指向 DKWS 服务） | 按 gits 端设计实现 `SkillExecutionPort` |

### 8.2 端点与契约（不变，设计文档 §7.1）

- `POST /api/skill/execute`：`{skillId, requestId, request}` → `{requestId, status(ok|skill_error|exit_policy_no_new_evidence), data, errors, assemblyTrace, modelCalls}`；未知 skillId→404，缺字段→422。
- `GET /api/skill/health`：`{status:"ok", service:"customer-engagement", skills:[{skillId,name,version}]}`。

### 8.3 验证结果（D1-D6）

- 单元/集成：`tests/integration/test_skills.py`（16 项，含 DKWS 协作注入与 fail-open）；
- 真实 HTTP 端到端：`examples/skill_e2e.py` → **16/16 PASS**（health / 三 skill 执行 / 幂等 / 无新证据 / modelCalls / 404+422）；
- 全量回归：pytest 全绿（含修复测试硬编码版本号的时间依赖 bug）。

### 8.4 环境约束（记录）

- DSH checkout（`/home/szf/env/deepseek-harness`）在本会话沙箱中仅允许一次性授权写入；SKILL.md 资产同步已完成（4 文件）。
- 外部模型未配置时（无 `DKWS_LLM_*` 环境变量），Skill 平台经**确定性适配器**端到端可用（规格 §1.6）；配置 `DKWS_LLM_BASE_URL/API_KEY/MODEL` 后自动切换 OpenAI 兼容真实模型，modelCalls 记录 token/延迟。
