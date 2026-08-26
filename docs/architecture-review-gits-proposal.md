# DKWS 端架构评审：GITS 服务建议书与交互记忆集成（SP-20/SP-21）

> 评审人：DKWS 端架构师 ｜ 日期：2026-08-23
> 评审对象：GITS `docs/architecture/GITS-DKWS-SERVICE-PROPOSAL-INTEGRATION-DESIGN.md` + 附录 A/B/C/D
> 立场：**知识在 DKWS，业务在 GITS**（延续 v1.3 数据所有权原则），SP-20/SP-21 作为 DKWS 技能落地，
> 闸门/记忆生命周期/业务版本由 GITS 编排，DKWS 提供知识装配、生成、标签、规则与过滤引擎。

---

## 1. 总体结论（先讲立场）

GITS 提案方向正确（把"服务建议书"变成可版本化、可审计、可复用的资产），但**把三类业务状态
（闸门状态机、交互记忆生命周期、业务版本管理）划给了 DKWS**，这与 DKWS 的平台定位（文件目录型
**知识服务**平台，非业务应用）冲突，也与 v1.3 已确立的"知识在 DKWS、业务在 GITS"原则相悖。

**整体最佳方案一句话**：DKWS 承接 **SP-20（建议书知识装配+逐章生成+事实标签+引用+规则校验+确定性
双版本过滤）** 与 **SP-21（记忆抽取）**，输出结构化 ServiceResult；GITS 承接 **闸门状态机（G0-G5）、
交互记忆存储与生命周期、业务版本记录、审批流**；DKWS 只通过知识/技能接口被调用，不成为第二个业务系统。

### 1.1 职责边界总表

| 能力 | 归属 | 理由 |
|---|---|---|
| 行业/财务/模板/规则知识资产 | **DKWS** | 本就是知识资产（03_core 可版本化） |
| SP-20 逐章生成 + 事实标签 + 引用索引 | **DKWS** | 技能/生成是 DKWS 职责；标签与生成同源才能自洽 |
| 6 条 BLOCKING 规则校验（CITATION/DUAL_VERSION/…） | **DKWS（RULE 资产 + evaluate_rule）** | 规则是知识，校验结果随结果返回 |
| 内部版/对客版**过滤执行**（确定性、可审计） | **DKWS（过滤引擎，无 LLM）** | 标签在 DKWS 生成，过滤逻辑就近、可复现 |
| 对客版**发布权**（G1+G2+G3 通过后才放行） | **GITS（闸门）** | 审批权在业务端 |
| 闸门状态机 G0-G5 | **GITS** | 业务编排+人工审批；DKWS 90_control 是平台治理闸门，**不是**业务闸门，不可混用 |
| 交互记忆**抽取**（SP-21） | **DKWS** | 抽取=知识化，LLM 技能职责 |
| 交互记忆**存储与生命周期**（候选/确认/过期/取代+置信度衰减） | **GITS** | 操作性状态，非知识资产；v1.3 已定客户主档不写知识，反之亦然 |
| 建议书**业务版本**（v1.0/v1.1/v2.0） | **GITS（ProposalVersion 记录）+ DKWS（知识快照 release_version）双轨** | 业务版本是 GITS 记录；DKWS 每次生成落一个不可变知识快照供引用 |
| ContextPackage 组装 | **GITS** | 业务上下文组装在业务端（v1.3 只传 customerId 例外：SP-20 是**组合技能**，需显式上下文，见 §3.2） |

---

## 2. 八个决策项逐条裁定（主文档 §13）

### D1：ContextPackage 与五层工作区映射 —— **采纳但改造：按"知识资产"而非"业务文件夹"落位**

GITS 建议的 `01_raw/{customerId}/proposal/...` 按客户+业务对象建目录，**与 DKWS 域/版本模型冲突**
（DKWS 是 `03_core/<domain>/version=<release>/` 的域资产模型，不是客户档案柜）。

裁定方案——**建议书作为"知识文档资产"落库**，保持平台模型不变：

| 层 | DKWS 落位 | 说明 |
|---|---|---|
| 01_raw | `01_raw/proposal/batch=<ingestId>/` | ContextPackage 作为原始输入批次登记（含 sha256），不做业务目录 |
| 02_work | `02_work/proposal/run=RUN-PROPOSAL-<ts>/` | 草稿/引用/未知项/llm-trace 全部按 **run_id 隔离**（与 parse/extract 同一机制，天然可重跑，满足版本管理需求） |
| 03_core | `03_core/proposal/version=<release>/segments+statements+relations` | 发布版建议书**知识化**：每章=segment，每断言=statement（factLabel 为 statement 属性），引用=relation/citation statement |
| 04_serve | `04_serve/proposal_customer/version=<release>/` | 对客版投影：按 factLabel 过滤的 statement 子集（确定性过滤，见 D3） |
| 90_control | 仅记录**知识资产审核**（现有 G0-G5 平台门禁） | 业务闸门**不**写这里（见 D5） |

> run_id 隔离**满足**建议书版本管理需求：每次生成=新 run；发布=新 release_version（不可变）；
> GITS 的 v1.0/v1.1 业务版本号 ↔ DKWS release_version 由引用索引（runId/citation id）关联，互不覆盖。

### D2：HTTP API —— **不新增 `/skills/execute`，复用并扩展 `/api/skill/execute` + 异步作业**

- 新增独立端点会造成两套技能契约并存，GITS 已按 v1.3 实现 `SkillExecutionPort`。
- **裁定**：`POST /api/skill/execute` 契约升级 v1.4（向后兼容）：
  - 请求：`{skillId: "SP-20", requestId, request: {context: <ContextPackage>, proposalType, engagementPhase}}`；
  - 响应：`data.result` = ProposalServiceResult（见附录 A ServiceResult），`data.reportUrl` 指向定制报告；
  - **异步模式**：SP-20 逐章生成 8 次 LLM 调用可能 1-3 分钟，同步 HTTP 易超时 →
    `request.async=true` 时返回 `202 {jobId}`，复用现有 `/v1/jobs/{job_id}` 轮询（平台已有异步作业设施，
    与 `/v1/extractions` 同机制）；
  - 认证：延续无鉴权（演示环境网络层控制）；超时建议 GITS 侧 ≥ 120s（异步则无关紧要）。

### D3：双版本生成逻辑 —— **DKWS 生成内部版 + 确定性过滤出对客版，GITS 控制放行时机**

- 事实标签在生成时产生，过滤规则与标签同源才能自洽、可复现、可审计 → **过滤执行放 DKWS**（无 LLM，
  纯规则，输出 filtering-report.json）。
- **GITS 保留发布权**：对客版在 `data.content.customerVersion` 中**已生成但带 `releaseBlockedUntil: ["G1","G2","G3"]`**，
  GITS 闸门通过后才向前端展示/导出。避免 DKWS 越权审批。

### D4：交互记忆存储 —— **放 GITS，DKWS 只做抽取（SP-21）**

- 记忆有 CANDIDATE→CONFIRMED→EXPIRED/SUPERSEDED 生命周期 + 置信度衰减，是**操作性业务状态**，
  放 DKWS 03_core 会污染"不可变知识资产"语义（记忆在变、知识不可变）。
- **裁定**：GITS 领域模块（H2）存储与生命周期；DKWS SP-21 从纪要抽取候选（输出结构化 statements 风格
  候选 + 与已有记忆的比对建议），GITS 调 `InteractionMemoryPort` 持久化/确认。
- 交互记忆进入建议书：GITS 组装进 ContextPackage.interactionMemory（已有设计），DKWS 不持有记忆库。

### D5：闸门状态机 —— **GITS 唯一权威，DKWS 提供闸门清单知识与就绪度建议**

- 必须明确：DKWS 90_control 的 G0-G5 是**平台知识资产门禁**（ingest→…→projection），与业务 G0-G5
  （证据→核验→专家→审批→对客→复盘）**同名异义**，混用会造成审计混乱。
- **裁定**：业务闸门状态机 = GITS（ProposalPort.advanceGate），人工审批在 GITS；
  DKWS 在 SP-20 输出 `gateRecommendations`（就绪度评估 + checklist），checklist 本身作为
  **DKWS RULE/知识资产**（每闸门"必须完成/禁止事项"来自交接文档，落 `03_core/proposal-gates/`）；
  GITS 可（可选）把闸门决策**镜像**到 DKWS 审计端点，但权威在 GITS。

### D6：行业分析框架粒度 —— **采纳 GITS 建议：银行对公常用约 15 类**

- 一级 20 类太粗、二级 97 类太细；定义 `ASSET-KNOW-INDUSTRY-TAXONOMY`（约 15 类 + OTHER），
  ContextPackage.industry（"一级-二级"字符串）映射到该分类，未命中→OTHER 并记入 unknowns。
- 每个行业类一份 `INDUSTRY-<code>-ANALYSIS` 框架资产（八维/景气/政策/竞争模板，可复用现有
  KI-FRONT-002 八维研判结构）。

### D7：分章生成策略 —— **采纳逐章，但"确定性骨架 + 并行 + 章节级结构化输出"**

- 逐章（CHAPTER_BY_CHAPTER）正确：每章独立 LLM 调用可控制质量、可重试、可追踪。
- 优化：① 8 章**并行 2-3 路**（章节间无强依赖；CH02 依赖行业资产、CH05 依赖记忆，其余独立），
  目标总耗时 < 90s；② 每章输出 = **结构化 JSON**（正文 markdown + claims[] + factLabels[] +
  citations[] + unknowns[]），不是纯散文——GITS 才能按断言渲染卡片；③ 每章一次
  `assemblyTrace` 步骤（沿用 KI 级轨迹，chapterRef 标识），控制台可直接看每章取数。
- maxTokensPerChapter 2000 / total 20000 合理（DeepSeek 窗口充足）。

### D8：ContextPackage 大小 —— **采纳 50KB 上限，DKWS 侧相关性裁剪**

- 50KB（压缩后）≈ 25-30K tokens，DeepSeek 上下文可容纳。
- DKWS 侧裁剪策略：行业框架只注入目标章节相关段；交互记忆按置信度/时效 Top-N（≤20 条）；
  财务摘要只取最近 3 年 + 关键比率；裁剪在 `limitations` 中显式声明（不静默降级）。

---

## 3. SP-20 在 DKWS 的实现设计

### 3.1 技能形态（与现有 Skill 模型对齐）

- `implementationType` 建议由 RULE_MODEL 改为 **HYBRID**（确定性装配 + LLM 生成 + 规则后校验），
  与现有 `skill-customer-previsit-report` 同构：`SP-20` 注册进 `SkillExecutionService` 注册表，
  走统一契约（requestId/status/data/assemblyTrace/modelCalls）。
- **资产装配**（确定性，无 LLM）：
  - `ASSET-KNOW-PROPOSAL-TEMPLATE`：8 章 + 5 表模板（ch01~ch08、apx-a~e）→ `03_core/proposal-templates/`
  - `ASSET-KNOW-INDUSTRY-ANALYSIS`：行业框架（≈15 类）
  - `ASSET-KNOW-FINANCIAL-ANALYSIS`：财务比率/现金流/偿债框架
  - `ASSET-KNOW-VISIT-SOP`：拜访 SOP 资产（复用 `skills/customer-engagement` 既有资产）
- **激活合同**：`AC-SERVICE-PROPOSAL-001` 落为知识地图资产（routeMode=ONTOLOGY_THEN_MAP：
  首次从本体/行业框架出发；`AC-SERVICE-PROPOSAL-002` routeMode=MAP_FIRST：先读交互记忆与已有地图）。
  路由模式实现为**检索后端选择**（与 Kùzu/内存回退同层）。
- **规则校验**：6 条 BLOCKING 规则（CITATION_REQUIRED / NO_UNDISCLOSED_DEGRADATION /
  DUAL_VERSION_PRINCIPLE / GATE_SEQUENCING / FACT_LABEL_MANDATORY / NO_COMMITMENT_WITHOUT_APPROVAL）
  落为 **DKWS RULE 资产**（复用 `evaluate_rule` DSL），生成后自动校验，违规以 `data.ruleViolations`
  返回（BLOCKING 违规 → status=PARTIAL + 违规清单，不返回残缺成功）。

### 3.2 输入契约：ContextPackage 与 v1.3 的关系

- v1.3 确立"GITS 只传 customerId"适用于**单客户知识技能**（R1/图谱/外联/会面）。
- SP-20 是**组合型业务技能**：需要企业内数据（财务/授信/交易）+ 公开数据 + 交互历史 + 交互记忆，
  这些大多**不在 DKWS 库内**（财务/授信在 GITS 业务侧）。因此 SP-20 的 `request.context`（ContextPackage）
  是**必要例外**：GITS 组装上下文传入，DKWS 负责**知识化 + 生成 + 标签 + 校验**。
- 边界：ContextPackage 里**银行内数据**（授信/交易）只用于生成，**不落 DKWS 权威库**
  （除证据登记到 01_raw 批次），延续"DKWS 不持有业务主档"原则；DKWS 库内的行业/财务框架与交互记忆
  （若有）**优先于** context 中同名数据（知识在 DKWS）。

### 3.3 事实标签（F/C/B/H/P/A）与现有 statement 模型对齐

- 现有 statement/v1 有 `polarity/conflict_status/value_type/object_value_*`；新增枚举
  `factLabel: F|C|B|H|P|A`（映射：F 已核验事实 / C 推断结论 / B 行为事实 / H 假设 / P 计划承诺 / A 已批准）。
- 每条生成断言 = 一条 statement（subject=proposal_run/章节，predicate=断言主题，factLabel=标签，
  source_segment_id=来源证据），引用索引（citations）可由 statements 投影直接生成——**事实标签成为
  一等的知识属性**，GITS 按标签渲染、按标签过滤对客版（D3）。

### 3.4 建议书报告页（复用现有可视化）

- `/api/skill/report/{requestId}` 为 SP-20 增加**建议书报告模板**：双版本切换、8 章目录、
  断言→标签→引用的可点击卡片、未知项/限制/闸门建议面板、规则违规红条（复用 report.py 模板机制）。

---

## 4. SP-21 交互记忆抽取实现设计（P2）

- 输入：interactionId + interactionContent（纪要文本）+ existingMemories（GITS 传入，供比对）。
- 输出：candidateMemories[]（类别 PREFERENCE/DECISION_PATTERN/RELATIONSHIP/BUSINESS_SIGNAL/EMOTIONAL_STATE +
  置信度 + 建议衰减规则 NONE/LINEAR/STEP）、memoryUpdates（强化/新洞察）、memorySupersessions（否定）。
- 规则依赖：CONFIDENCE_CALIBRATION / DECAY_RULE_APPLICATION / DUPLICATE_DETECTION 落为 RULE 资产；
  确定性比对（与既有记忆文本/语义相似度）走规则，生成走 LLM。
- **DKWS 不存记忆**：candidateMemories 交 GITS `InteractionMemoryPort.confirmCandidate` 持久化。
- 抽取过程留 `assemblyTrace`（同现有技能，GITS 调试用）。

---

## 5. 契约 v1.4 扩展点（在 v1.3 上增量，向后兼容）

| 变更 | 说明 |
|---|---|
| `request.context`（ContextPackage） | SP-20/SP-21 专用；单客户技能仍只传 customerId |
| `request.async` | `true` → 202 + jobId 轮询（SP-20 长任务） |
| `data.result` | SP-20 = ProposalServiceResult（附录 A ServiceResult 兼容）；现有技能不变 |
| `data.ruleViolations` | 规则校验违规清单（BLOCKING → PARTIAL） |
| `data.reportUrl` | 已有；SP-20 指向建议书报告模板 |
| 新合同注册 | SP-20/SP-21、AC-SERVICE-PROPOSAL-001/002、KM-CORP-RM-SERVICE-PROPOSAL、ASSET-KNOW-*、CTR-PROPOSAL-001 |
| status 枚举 | 保持 `ok|skill_error|exit_policy_no_new_evidence`，SP-20 部分完成用 `ok` + `data.status=PARTIAL`（不新增顶层枚举，兼容 GITS 解析） |

---

## 6. 主要风险与对策

| 风险 | 对策 |
|---|---|
| 8 次 LLM 调用延迟（可能 1-3 分钟） | 异步作业 + 章节并行 2-3 路 + 逐章 maxTokens 2000 + 重试 2 次退避 1s |
| 两套"G0-G5"（平台门禁 vs 业务闸门）语义混淆 | 命名分离：DKWS `GATE-PLATFORM-*`，GITS `GATE-BIZ-*`；文档明示 |
| ContextPackage 含银行内数据越界 | 只生成不落权威库；证据登记 01_raw 批次；DKWS 库知识优先于 context 同名数据 |
| 对客版泄密（C/B/H/P 误入对客版） | DUAL_VERSION 过滤为确定性规则 + filtering-report 全量记录 + GITS 放行闸门双保险 |
| 逐章标签不一致（同一断言跨章标签漂移） | 章节共享"断言登记表"（run 内 statements 先聚合再分章引用）；规则 FACT_LABEL_MANDATORY 兜底 |
| RULE_MODEL 被误读为"无 LLM" | 契约写明 HYBRID：确定性装配 + LLM 生成 + 规则校验 |

---

## 7. 实施路径（DKWS 侧工作分解）

> 状态更新 2026-08-23：Phase 1 ✅ 完成；Phase 2 完成 7/8/9 的 DKWS 侧（7-8 已落地，9 待 GITS 联调）。

**Phase 1（已完成）—— SP-20 骨架**
1. ✅ 契约 v1.4（execute 扩展 + async + context + ServiceResult）
2. ✅ 资产：8 章/5 表模板 + 行业框架（3 类演示）+ 财务框架 + AC-SERVICE-PROPOSAL-001（skills/service-proposal/）
3. ✅ 激活合同 + routeMode 路由（ONTOLOGY_THEN_MAP / MAP_FIRST）
4. ✅ SP-20 执行器（逐章并行 3 路 + 断言/标签/引用 + assemblyTrace）
5. ✅ 6 条规则校验 → ruleViolations
6. ✅ `/api/skill/report` 建议书报告模板（双版本 Tab/闸门条/断言表）

**Phase 2（DKWS 侧完成）—— 双版本 + 闸门协作**
7. ✅ 确定性对客版过滤引擎（factLabel 段落级过滤 + filteringNotes + releaseBlockedUntil）
8. ✅ 闸门清单知识资产 GATE-BIZ-G0..G5 + `GET /api/skill/gates/{id}` + `POST /api/skill/gates/audit`（镜像）+ gateRecommendations
9. ⏳ GITS 联调：ProposalPort ↔ execute v1.4（待 GITS 侧实现调用方）

**Phase 3（已完成）—— 记忆与阶段演进**
10. ✅ SP-21 抽取技能（LLM + 确定性比对 REINFORCE/SUPERSEDE）+ CONFIDENCE/DECAY/DUPLICATE 规则
11. ✅ AC-SERVICE-PROPOSAL-002（MAP_FIRST）+ AC-ONGOING-ENGAGEMENT-001（持续经营记忆积累）
12. ✅ E2E：交互→SP-21 抽取→（GITS 确认）→SP-20 UPDATE（MAP_FIRST + 记忆注入）→对客版放行（测试覆盖）
> 剩余：GITS 侧 `InteractionMemoryPort`（候选确认/记忆库/生命周期）与阶段演进 UI——属 GITS 实现范围。

---

## 8. 一句话总结

DKWS 把 SP-20/SP-21 做成**一等技能**（知识装配 + 逐章生成 + 事实标签 + 规则校验 + 确定性双版本过滤 +
异步作业 + 报告页），把**闸门状态机、交互记忆生命周期、业务版本**留在 GITS；
契约升级 v1.4 向后兼容，五层工作区按"知识资产"落位（域/版本/run_id 模型不变）——
两边各司其职，不互相越权，全链路可审计可重跑。
