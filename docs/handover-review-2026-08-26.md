# DKWS 交接评审文档（Handover Review）

> 版本：2026-08-26
> 评审对象：DKWS 当前设计、实现、契约、联调状态、UAT 结论、生产演进设计
> 评审方式：离线评审（本包为评审材料）
> 配套演进设计：`docs/production-evolution-plan.md`
> 交接入口：`$WS/HANDOVER.md` / `$WS/HANDOVER.txt`

---

## 1. 评审目的

本评审文档用于 Owner/架构评审人离线确认：

1. DKWS 当前设计与实现是否与需求一致？
2. 当前与 GITS 的契约/联调状态是否清晰？
3. 当前 UAT 失败结论是否准确？
4. 生产级演进设计是否可执行？
5. 下一步该批准哪个方向？

---

## 2. 交接包清单

### 2.1 入口文档

| 文件 | 说明 |
|---|---|
| `$WS/HANDOVER.md` | 新会话首选阅读，Markdown 版 |
| `$WS/HANDOVER.txt` | 新会话快扫版，纯文本 |
| `$DKWS/docs/handover-review-2026-08-26.md` | 本文档 |
| `$DKWS/docs/production-evolution-plan.md` | 生产级演进设计 |

### 2.2 DKWS 权威设计

| 文件 | 说明 |
|---|---|
| `$WS/文件目录型数据知识服务模拟平台_详细需求与详细设计_V1.0.md` | 权威需求与详细设计（1751 行） |
| `$DKWS/docs/architecture.md` | 系统架构（分层/运行时/时序/部署） |
| `$DKWS/docs/assets/*.png` | 4 张架构图 |
| `$DKWS/ADR.md` | 实现架构决策记录（ADR-001~011） |
| `$DKWS/README.md` | 工程说明与功能清单 |
| `$DKWS/REQUIREMENTS_MATRIX.md` | 需求追踪矩阵 |
| `$DKWS/SKILL_PLATFORM_ARCH.md` | Skill 平台架构 |

### 2.3 契约与联调

| 文件 | 说明 |
|---|---|
| `$DKWS/docs/skill-execute-api-contract.md` | 契约 v1.3 |
| `$DKWS/docs/skill-execute-api-contract-v1.4.md` | 契约 v1.4 |
| `$DKWS/docs/v13-return-to-gits.md` | v1.3 回传说明 |
| `$DKWS/docs/gits-integration-samples-v14.md` | v1.4 真实样例 |
| `$DKWS/docs/v14-joint-debugging-plan.md` | v1.4 联调计划与实测 |
| `$DKWS/docs/gits-codebuddy-techlead-prompt-v14.md` | GITS 技术负责人提示词 |
| `$DKWS/docs/codebuddy-techlead-prompt-v14.txt` | 同上（txt） |
| `$DKWS/docs/architecture-review-gits-proposal.md` | GITS 架构评审提案 |
| `$DKWS/docs/gits-supply-chain-report-dev-prompt.md` | 供应链报告开发提示词 |

### 2.4 辅助/记录

| 文件 | 说明 |
|---|---|
| `$DKWS/docs/graph-db-selection.md` | 图数据库选型 |
| `$DKWS/docs/dsh-computer-use-install.md` | DSH Computer Use 安装记录 |
| `$DKWS/docs/evaluation-sqlite-graph-base.md` | SQLite 图基座评估 |
| `$DKWS/docs/evaluation-sqlite-graph-convenience.md` | SQLite 图便利性评估 |
| `$DKWS/docs/HANDOVER-2026-08-23.md` | 上一版交接文档（历史） |
| `$DKWS/docs/HANDOVER-2026-08-23.txt` | 上一版交接文档（历史） |

---

## 3. 当前系统状态

### 3.1 服务状态

- 服务：`dkws-skill.service`
- 状态：`active (running)`
- 地址：`http://127.0.0.1:8106`
- 监听：`0.0.0.0:8106`
- 技能：12 个 Skill 在线
- 集成测试：137 个用例全绿
- 服务运行时长：systemd 托管，`Restart=always`

### 3.2 技能清单

| skillId | 名称 |
|---|---|
| `skill-customer-outreach-script` | 外联脚本 |
| `skill-customer-meeting-script` | 会面脚本 |
| `skill-customer-previsit-report` | R1 拜访报告 |
| `SP-20` | 对公客户服务建议书生成 |
| `SP-21` | 交互记忆抽取 |
| `bank-front-commitment-script` | 承诺话术 |
| `bank-front-eight-dimension` | 八维分析 |
| `bank-front-fact-reconciliation` | 事实对账 |
| `bank-front-kyc-gap-check` | KYC 缺口检查 |
| `bank-front-product-recommendation` | 产品推荐 |
| `bank-front-report-assembler` | 报告组装 |
| `bank-front-supply-chain-graph` | 供应链图谱 |

### 3.3 数据现状

- 客户知识库：`customer_knowledge` 服务投影
- 已落库客户：
  - `CUST-CORP-0001` 华东精工装备集团有限公司
  - `CUST-CORP-0002` 华东新能源汽车有限公司
- 每个客户 7 条 KI
- 供应链图谱：7 节点 / 6 边（CUST-CORP-0001）
- 另有 1064 节点/1056 边规模化演示图（`supply_chain_graph`）

### 3.4 最近外部请求

- 近 24 小时日志未发现非 `127.0.0.1` 来源的外部请求
- 全部请求状态码 200
- 无 4xx/5xx、无异常堆栈
- 结论：DKWS 服务健康，GITS 尚未实际调用

---

## 4. 架构评审摘要

### 4.1 设计优点

1. **文件系统为权威源**：03_core 不可变，04_serve 可重建，降低数据腐败风险。
2. **五层分离清晰**：原始输入、加工、核心资产、服务投影、治理各司其职。
3. **投影可重建**：Parquet 与 Kùzu 都能删除重建。
4. **数据所有权清晰**：v1.3 后 GITS 只传 `customerId`。
5. **治理有雏形**：幂等、无新证据、门禁、审计镜像、assemblyTrace。
6. **ADR 驱动**：关键决策有记录。
7. **测试覆盖较好**：集成 137 全绿，另有安全/恢复/E2E。

### 4.2 架构风险

1. **内存态过多**：幂等、evidence timestamp、异步任务线程均无持久化。
2. **无安全边界**：无鉴权、无 TLS、无限流。
3. **无通用工具/知识源框架**：当前只是最小 Skill 执行器。
4. **可观测性弱**：无 metrics/tracing/告警。
5. **部署形态单一**：systemd 用户服务，无容器/CI/CD。
6. **无多租户与数据合规**。


### 4.3 五层工作区详细设计

| 层 | 路径 | 内容 | 性质 |
|---|---|---|---|
| 01_raw | `01_raw/<domain>/batch=<id>/` | 原始输入文档/数据、MANIFEST.md、SHA-256 | 只收原始输入，不可变登记 |
| 02_work | `02_work/<domain>/run=<id>/` | 解析切片、抽取候选、清洗结果 | 加工现场，run_id 隔离，可删除重建 |
| 03_core | `03_core/<domain>/version=<v>/` | entities / relations / statements / segments / rules + RELEASE.md | 核心资产，不可变版本，唯一权威源 |
| 04_serve | `04_serve/<service>/version=<v>/` | Parquet 投影 + Kùzu 图 + PROJECTION.md / CURRENT.md | 可重建投影，面向服务读取 |
| 90_control | `90_control/` | decisions / gates / jobs / audit / locks / logs | 治理与审计，非业务事实源 |

要点：

- `CURRENT.md` 是指针，切换版本不影响已发布版本。
- 发布时 `atomic_replace_dir` 先改名旧目录再 rename，失败回滚。
- `04_serve` 删除后可由 `03_core` 重建，Kùzu 图指纹校验纳入可重建性测试。
- 写锁文件在 `90_control/locks/<scope>.lock.json`，过期锁需 recover 确认后清理。
- 任务状态在 `90_control/jobs/<job_id>/STATUS.md`，异步技能结果在 `result.json`。

### 4.4 运行时 API 详细清单

| 端点 | 方法 | 说明 |
|---|---|---|
| `/v1/health` | GET | 服务与数据版本健康 |
| `/v1/catalog` | GET | 活动投影文件清单 |
| `/v1/extractions` | POST | 触发抽取，202 + job_id |
| `/v1/jobs/{job_id}` | GET | 作业状态，v1.4 含 `skill_result` |
| `/v1/extractions/{job_id}/result` | GET | 抽取结果摘要 |
| `/v1/entities/{entity_id}` | GET | 实体与相关 statements |
| `/v1/data/query` | POST | 数据集查询 |
| `/v1/search` | POST | 全文/向量/混合检索 |
| `/v1/graph/query` | POST | 图谱 neighbor/closure/paths |
| `/v1/rules/evaluate` | POST | 规则评估 |
| `/v1/evidence/{object_id}` | GET | 证据溯源 |
| `/api/skill/health` | GET | 技能健康与列表 |
| `/api/skill/execute` | POST | 技能执行（同步/异步） |
| `/api/skill/report/{request_id}` | GET | 可视化报告页 |
| `/api/skill/gates/{customer_id}` | GET | 闸门清单资产 |
| `/api/skill/gates/audit` | POST | 闸门决策审计镜像 |

### 4.5 核心应用模块

| 模块 | 职责 |
|---|---|
| `application/ingest.py` | 01_raw 接入登记、哈希、幂等 |
| `application/parse_doc.py` | 文档解析切片（PDF/DOCX/TXT） |
| `application/extract.py` | 候选抽取（实体/关系/声明/规则） |
| `application/review.py` | 审核决策与状态机 |
| `application/publish.py` | Core 不可变发布 + 门禁 |
| `application/projection.py` | Serve 投影构建 |
| `application/rollback.py` | 版本回滚 |
| `application/services.py` | KnowledgeService |
| `application/customer_knowledge.py` | 客户知识取数层 |
| `application/skills.py` | SkillExecutionService |
| `application/service_proposal.py` | SP-20 |
| `application/interaction_memory.py` | SP-21 |
| `application/jobs.py` | JobController |
| `application/gates.py` | 闸门辅助 |
| `application/report.py` | 报告页渲染 |
| `infrastructure/fs.py` | 原子写/路径安全/目录替换 |
| `infrastructure/locks.py` | 工作区写锁 |
| `infrastructure/adapters/llm.py` | LLM 适配器 |
| `infrastructure/graph/kuzu_builder.py` | Kùzu 图投影与查询 |
| `infrastructure/logging.py` | 脱敏日志 |
| `domain/contracts/specs.py` | 26 类 SchemaSpec |
| `domain/rules/dsl.py` | 规则 DSL |

### 4.6 Skill 执行详细流程

1. 接收 `POST /api/skill/execute`
2. `SkillExecutionService.execute()`
3. 生成/复用 `requestId`
4. 检查内存幂等缓存（TTL 10 分钟，上限 500 条）
5. 未知 skillId → 404 + `skill_error`
6. R1 检查 `evidenceTimestamp`，缺失/未更新 → `exit_policy_no_new_evidence`
7. `_load_ki(customerId)`：从 `customer_knowledge` 投影读 KI
8. `_trace_ki()` 逐 KI 打点 `ok/skipped`
9. 按 Skill 类型执行：
   - 外联/会面/R1：组装知识上下文 → LLM → JSON 解析
   - 供应链图谱：库构建 nodes/edges/interpretation，无 LLM
   - SP-20：ContextPackage → 逐章并行 → 规则校验 → 双版本
   - SP-21：交互记忆 → LLM 候选 → 确定性比对 → 规则校验
   - bank-front 包：SKILL.md 指令 + output-schema 提示 → LLM → JSON
10. 输出结构校验失败 → `skill_error`
11. 写幂等缓存，返回 `requestId/status/data/errors/assemblyTrace/modelCalls`

### 4.7 数据投影详细清单

`customer_knowledge` 服务下 `04_serve/customer_knowledge/version=*/` 包含：

| 文件 | 内容 |
|---|---|
| `entities.parquet` | 客户与对手方实体，含 `x_*` 扩展字段 |
| `relations.parquet` | 关系（如 SUPPLIES），含来源/金额/账期 |
| `segments.parquet` | KI 片段，heading_path 含 KI 编号 |
| `statements.parquet` | 声明/事实 |
| `datasets/*.parquet` | 数据集投影 |
| `graph/` | Kùzu 图库文件 |
| `PROJECTION.md` / `CURRENT.md` | 投影说明与指针 |

### 4.8 测试体系详细清单

| 测试目录 | 覆盖 |
|---|---|
| `tests/unit` | 工作区、路径、哈希、Markdown、Schema |
| `tests/contract` | 26 类合同合法/非法样例 |
| `tests/integration` | 137 用例：接入/解析/抽取/审核/发布/投影/服务/API/Skill/SP-20/SP-21/闸门 |
| `tests/e2e` | 黄金场景（含 LLM 慢用例） |
| `tests/security` | 路径穿越、伪装、注入、DOCX 只读 |
| `tests/recovery` | 半发布、重建、幂等、回滚 |

### 4.9 已知约束与坑

1. `/tmp` 每次命令隔离，跨命令共享文件需用 `$WS` 下持久路径。
2. 沙箱写工作区外需宽权限；本环境策略为 danger-full-access。
3. GITS H2 内存库重启需重灌 `gits-crm-customer-master.json`。
4. `reportUrl` 仅调试跳转，GITS 只消费 execute JSON。
5. 幂等/异步任务状态目前为内存态/文件态，进程重启后部分失效。
6. 投影器需 `_pad_x_fields` 补键，防止 `from_pylist` 丢列。
7. 行业映射：ContextPackage.industry → INDUSTRY-TAXONOMY，未命中 OTHER。

---

## 5. 契约评审摘要

### 5.1 v1.3 要点

- 知识全在 DKWS，GITS 只传 `customerId`
- R1 `data.sections` 按 KI 出章
- `bank-front-supply-chain-graph` 只认 `customerId`，库构建 `data.result`
- `evidenceTimestamp` 缺失/未更新 → `exit_policy_no_new_evidence`
- 响应顶层：`requestId / status / data / errors / assemblyTrace / modelCalls`

### 5.2 v1.4 要点

- SP-20：ContextPackage + `async` + ServiceResult + ruleViolations
- SP-21：交互记忆抽取，DKWS 不存记忆
- 闸门：`GET /api/skill/gates/{customerId}` + `POST /api/skill/gates/audit`
- 错误：未知技能 404、坏请求 422、幂等 TTL 10min
- SP-20 必须异步：202 + jobId + 轮询 3s/3min

### 5.3 契约风险

- GITS P30 分支未带 Skill HTTP 适配器
- `application.yaml` 未配置 `dsh.base-url`
- 当前 UAT 分支不会调 DKWS
- 供应链图谱端点、assemblyTrace 等在 P24 合同，不在当前 W9 合同
- 需要合同 Loop 或 fail-closed 空态

### 5.4 详细请求/响应结构

#### 5.4.1 Skill 执行请求

```json
{
  "skillId": "skill-customer-previsit-report",
  "requestId": "req-001",
  "request": {
    "customerId": "CUST-CORP-0001",
    "evidenceTimestamp": "2026-08-26T00:00:00Z",
    "visitObjective": "了解经营情况"
  }
}
```

v1.4 扩展字段：

```json
{
  "skillId": "SP-20",
  "requestId": "req-002",
  "request": {
    "customerId": "CUST-CORP-0001",
    "customerName": "华东精工装备集团有限公司",
    "industry": "制造业-高端装备",
    "enterpriseData": {},
    "proposalContext": {}
  },
  "context": {},
  "async": true
}
```

#### 5.4.2 Skill 执行响应顶层

```json
{
  "requestId": "req-001",
  "status": "ok",
  "data": {},
  "errors": [],
  "assemblyTrace": [],
  "modelCalls": []
}
```

- `status`：`ok` / `skill_error` / `exit_policy_no_new_evidence`
- `errors`：`[{code, message}]`
- `assemblyTrace`：`[{phase, status, message, kiId?}]`
- `modelCalls`：`[{model, inputTokens, outputTokens, latencyMs}]`

#### 5.4.3 关键 Skill 数据结构

| Skill | data 关键字段 |
|---|---|
| 外联 | `scriptTitle`, `sections[]`, `callObjectives[]`, `keyMessages[]` |
| 会面 | `agenda[]`, `talkingPoints[]`, `sensitivePoints[]`, `actionItems[]` |
| R1 | `reportTitle`, `executiveSummary`, `sections[]`, `evidenceRefs[]` |
| 供应链图谱 | `skillId`, `result.nodes[]`, `result.edges[]`, `result.interpretation{}`, `reportUrl` |
| SP-20 | `skillId`, `result{status, content, citations, unknowns, limitations, gateRecommendations, ruleViolations}` |
| SP-21 | `skillId`, `result{candidateMemories[], memoryUpdates[], memorySupersessions[], ruleViolations}` |

#### 5.4.4 错误与状态码

| 场景 | HTTP | 说明 |
|---|---|---|
| 未知 skillId | 404 | `status=skill_error`，`UNKNOWN_SKILL` |
| 非法 JSON / 缺字段 | 422 | FastAPI 校验 |
| 业务失败 | 200 | `status=skill_error` + `errors[]` |
| 无新证据 | 200 | `status=exit_policy_no_new_evidence` |
| 异步创建 | 202 | `{jobId, status:"PENDING"}` |
| 异步轮询 | 200 | `GET /v1/jobs/{id}` 含 `skill_result` |

---

## 6. UAT 结论（2026-08-26）

### 6.1 结论

`UAT_PASS = NO`

### 6.2 根因

- GITS 上一版 `feature/P24-dkws-supplychain` 能调 DKWS
- 当前分支 `feature/P30-gits-bank-experience-shell` 没有带上 Skill HTTP 适配器
- `application.yaml` 没有 `dsh.base-url`
- 服务即使修好，当前 jar 也不会调 DKWS

### 6.3 当前一键访前实际链路（问题）

| 页面/能力 | 当前行为 | 问题 |
|---|---|---|
| R1 访前报告 | 本地知识快照 + Mock LLM + H2 规则 | 未调 DKWS |
| R2 速战卡 | H2 规则卡 | 未调 DKWS |
| 外联话术 | Mock LLM / 本地模板 | 未调 DKWS |
| 会面话术 | Mock LLM / 本地模板 | 未调 DKWS |
| 供应链图谱 | 占位句，无图 | 未调 DKWS |
| 装配控制台 | 前端零实现 | 未展示 assemblyTrace |
| 产品推荐 | H2 流水规则 | 未调 DKWS |
| 服务建议书 | C2 空壳 | 未调 SP-20 |
| 交互记忆 | 无 V14 控制器 | 未调 SP-21 |
| 闸门 | 无 | 未接 DSH gate |

### 6.4 禁止事项

- 未配置 `dsh.base-url` 或 DKWS 失败时，禁止本地补数
- 禁止解析本地 HTML 报告页冒充图谱
- 禁止把 G0-G5 写成可写阶段机
- 集团股权图（P05）与 P38 知识地图快照不属于 DKWS，可保留本地

### 6.5 下一步选项

- **Option A**：给可达的 `DSH_BASE_URL`，开独立 Loop 把 P24 Skill 路径合回来
- **Option B**：先 fail-closed 空态（“DKWS 未配置/未返回”），撤掉 H2/Mock 拼装
- 推荐：**A+B**，既恢复真链路，也保留失败兜底

---

## 7. 生产级差距评审

详见 `docs/production-evolution-plan.md` 第 3 节。简要结论：

| 维度 | 状态 |
|---|---|
| 安全 | 不满足生产 |
| 持久化 | 不满足生产 |
| 可观测 | 不满足生产 |
| 可靠执行 | 不满足生产 |
| 工具/知识源 | 未产品化 |
| 多租户/合规 | 未开始 |
| 部署运维 | 仅演示级 |

---

## 8. 生产演进设计评审要点

详见 `docs/production-evolution-plan.md`。评审时请关注：

1. 是否认同“先单机生产、后多实例”的方向？
2. 是否同意 Phase 1 优先做安全/持久化/可观测/容器化？
3. 是否同意 Phase 2 做持久化队列、LLM Gateway、Schema 校验、Metrics/Tracing？
4. 是否同意 Phase 3 做统一 KnowledgeSource + ToolRegistry？
5. 是否同意 Phase 4 做多租户与数据治理？
6. 是否同意 Phase 5 作为远期？

---

## 9. 离线评审检查单

### 9.1 功能完整性

- [ ] 五层工作区是否符合 DKWS-SPEC-001？
- [ ] 26 个 SchemaSpec 是否完整？
- [ ] 黄金路径是否可跑通？
- [ ] 12 个 Skill 是否都在线？
- [ ] v1.3/v1.4 契约是否覆盖 GITS 需要？

### 9.2 工程质量

- [ ] 137 集成测试是否足够？
- [ ] 安全测试是否覆盖路径穿越/注入/脱敏？
- [ ] 恢复测试是否覆盖半发布/重建/回滚？
- [ ] E2E 是否覆盖真实链路？

### 9.3 生产风险

- [ ] 是否接受当前无鉴权？
- [ ] 是否接受幂等/异步任务内存态？
- [ ] 是否接受无 metrics/tracing？
- [ ] 是否接受单机部署？

### 9.4 决策

- [ ] GITS 下一步选 A、B 还是 A+B？
- [ ] 生产演进是否批准？
- [ ] Phase 1 是否立即启动？

---

## 10. 评审结论填写区

```text
评审人：
日期：
结论：
- 功能评审：通过 / 不通过 / 有条件通过
- 工程质量：通过 / 不通过 / 有条件通过
- 生产演进：批准 / 不批准 / 修改后批准
意见：
1.
2.
3.
下一步：
- [ ] 启动 Phase 1
- [ ] 先做 GITS UAT 修复
- [ ] 其他
```

---

## 11. 附录：关键文件路径速查

| 内容 | 路径 |
|---|---|
| 交接入口 | `$WS/HANDOVER.md` |
| 交接快扫 | `$WS/HANDOVER.txt` |
| 生产演进设计 | `$DKWS/docs/production-evolution-plan.md` |
| 本评审文档 | `$DKWS/docs/handover-review-2026-08-26.md` |
| 架构 | `$DKWS/docs/architecture.md` |
| 契约 v1.3 | `$DKWS/docs/skill-execute-api-contract.md` |
| 契约 v1.4 | `$DKWS/docs/skill-execute-api-contract-v1.4.md` |
| 联调计划 | `$DKWS/docs/v14-joint-debugging-plan.md` |
| 样例 | `$DKWS/docs/gits-integration-samples-v14.md` |
| ADR | `$DKWS/ADR.md` |
| README | `$DKWS/README.md` |
