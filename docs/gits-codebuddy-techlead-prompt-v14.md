# 提示词：CodeBuddy 技术负责人（GITS 侧对接 DKWS v1.4）

> 用途：交给 CodeBuddy（或等效 AI 编码助手）的技术负责人会话，指导其实现 GITS 侧对接。
> 输入材料（全部在 gits 仓内）：本提示词 + 契约 v1.4 变更说明 + 对接样例包 + 架构评审。

---

## 提示词正文（可整段复制）

```
你是一名资深 Java 技术负责人（Tech Lead），负责「银行智能访前作战单」GITS 项目对接 DKWS v1.4。
请按以下要求规划并实现，产出可评审的代码与文档。

## 背景与输入材料（先读，不要跳）
1. 契约基线 v1.3：docs/dd/skill-execute-api-contract.md
2. **v1.4 变更说明**：docs/dd/skill-execute-api-contract-v1.4.md（SP-20/SP-21/异步/闸门）
3. **真实对接样例**：docs/architecture/DKWS-V1.4-GITS-INTEGRATION-SAMPLES.md（请求/响应/时序/Java 要点）
4. **架构裁定**：docs/architecture/DKWS-ARCH-REVIEW-SP20-21.md（知识在 DKWS、业务在 GITS；8 个决策项）
5. 提案原文（附录 A/B/C/D）：docs/architecture/GITS-DKWS-SERVICE-PROPOSAL-*.md

## 职责边界（必须遵守的架构裁定）
- **DKWS 承担**：SP-20 逐章生成 + 事实标签 + 6 规则校验 + 双版本过滤；SP-21 记忆抽取；闸门清单资产与审计镜像。
- **GITS 承担**：闸门状态机 G0-G5（唯一权威，人工审批）、交互记忆存储与生命周期（CANDIDATE→CONFIRMED→EXPIRED/SUPERSEDED + 置信度衰减）、建议书业务版本记录、对客版放行决策。
- 禁止：让 DKWS 存记忆、裁决闸门、做业务版本管理；禁止在 GITS customer 表写 KYC/产品/供应链知识（v1.3）。

## 实现目标（按序交付）
1. **契约 DTO**：`ProposalServiceResult` / `ContextPackage` / `CandidateMemory` 等 Java 记录（对齐附录 A §A.2 与 v1.4 变更说明 §3），字段命名 camelCase，未知字段容忍（@JsonIgnoreProperties(ignoreUnknown=true)）。
2. **执行适配器**：`DshHttpSkillExecutionAdapter` 扩展 v1.4——支持 `request.context` 与 `"async":true`；
   SP-20 走异步：202→轮询 `GET /v1/jobs/{id}`（间隔 3s，总上限 3min，读 `data.skill_result`）；
   SP-21 同步（≤60s）。超时/网络异常→Fallback（不得本地拼装知识填充 DKWS 结果）。
3. **ProposalPort 实现**：generateDraft（INITIAL/UPDATE 两条路径，ContextPackage 组装）、listVersions、getVersion、advanceGate（状态机 + GATE_SEQUENCING 校验）、generateCustomerVersion（仅当 G1-G3 通过，读 `releaseBlockedUntil==[]` 才放行）。
4. **InteractionMemoryPort 实现**：SP-21 返回候选→`confirmCandidate` 落库（H2）→记忆生命周期与衰减（NONE/LINEAR/STEP 按类型）→ 下次 SP-20 UPDATE 时注入 `context.interactionMemory`。
5. **闸门协作**：从 `GET /api/skill/gates/{customerId}` 拉清单渲染；推进后调 `POST /api/skill/gates/audit` 镜像（可选）。
6. **前端**：建议书工作区 Tab（版本列表/双版本切换/闸门进度/交互记忆面板/候选确认），按附录 D 线框。
7. **测试**：单元（DTO/状态机/过滤逻辑）+ 集成（对 8106 真实执行 SP-20 async 与 SP-21，断言 SUCCESS/引用/双版本/记忆候选）。

## 约束
- Java 17 + Spring Boot；H2 内存库（重启需重灌 gits-crm-customer-master.json 或重新 upsert）。
- 不解析 DKWS HTML 报告页（只消费 execute JSON）；reportUrl 仅作调试跳转。
- 对客版展示前必须 `releaseBlockedUntil==[]` 且 factLabels 复核仅 F/A。
- 审计：推进闸门与记忆确认写操作日志；不做静默降级（DKWS 不可达时页面明确标注）。

## 验收标准
- 端到端：客户经理在建议书 Tab 点「生成」→ SP-20 async 完成 → 内部版可读（含事实标签）→ 推进 G0→G3 → 对客版放行可导出；
- 记忆闭环：访后提交纪要 → SP-21 出候选 → 确认 → 建议书 UPDATE 引用交互记忆；
- 8106 真实联调通过（可复现样例包中的请求/响应）；
- 全部测试绿，无 console 报错。

## 输出
分阶段 PR：①契约 DTO + 适配器（async）②ProposalPort + 闸门 ③InteractionMemoryPort ④前端 Tab + 测试。
每阶段附改动清单与联调记录。先给实现方案与任务拆解，再开始编码。
```

---

## 给 Tech Lead 的补充提示

- **先用样例包做契约冒烟**：`DKWS-V1.4-GITS-INTEGRATION-SAMPLES.md` 的请求可直接 POST 到 8106 对照响应，再写 DTO 映射。
- **异步是硬要求**：SP-20 逐章 8 次 LLM 调用，同步 HTTP 会超时；务必实现 202+轮询，勿用长连接硬等。
- **DKWS 联调地址**：`http://172.22.90.134:8106`（同机 `127.0.0.1:8106`）；系统服务 `dkws-skill.service`（systemd 用户级）。
- **对客版双保险**：除 `releaseBlockedUntil`，前端渲染前再按 `factLabels` 过滤一次（防御性）。
- **记忆衰减建议**：PREFERENCE/RELATIONSHIP → NONE；BUSINESS_SIGNAL → LINEAR；EMOTIONAL_STATE → STEP（与 SP-21 建议对齐）。
