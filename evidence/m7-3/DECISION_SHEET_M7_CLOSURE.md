# 决策清单：M7 收口待裁决事项（单张汇总）

```text
STATUS    : AWAITING_OWNER —— 本文档是**决策请求**，不是决策，不是授权
DATE      : 2026-09-16
AUTHOR    : Tech Lead
来源      : 本批次三条派工的产出 + TL 过程中发现的缺口（逐项附证据指针）
纪律      : 未经裁决的事项，TL **不**单方执行
```

## A. 合同 / 契约类（Contract Owner）

| # | 事项 | TL 建议 | 阻塞什么 |
|---|---|---|---|
| **A-1** | **契约权威归属（O1）**：`specs/kert-openapi-v1.yaml`（1.5.x，运行中权威）vs `docs/contracts/**`（v2 候选，未批准） | **采纳方案 A**：v1.5 为服务面唯一权威；v2 **降级为非权威设计输入**；`schemas/*.json` 保留为**细节 canonical 层**。**否决**"v2 为权威"与"双权威+映射层"。硬证据：v2 未声明 `/api/skill/report/{requestId}` 而 GITS 正在调用；v2 把 `skill_result` 提到顶层，GITS `DshJobPoller` 读 `data.skill_result` 会抛异常 | C-20 归并**执行**（现仅"列入收口"） |
| **A-2** | **v1 是否升 OpenAPI 3.1.0 / validator 是否放宽**（O5，含 8 处 `nullable`；`validate_contract_bundle.py:75-76` 硬要求 3.1.0） | 登记为**归并 P2 的验收条件**（二选一：v1 升 3.1.0，或 validator 放宽到接受 3.0.3），本轮不动 | 归并 P2 能否验收 |
| **A-3** | **v2 候选处置等级（O6）**：归档 / 降级 / 拆分 | **降级为非权威设计输入 + `schemas` 保留细节层**（= A-1 的组成部分）；归档为可选 P3 | v2 目录的最终定位 |
| **A-4** | **版本 `1.5.0 → 1.5.1` 补丁**：Contract Owner 追认的是**特定 artifact 的 v1.5.0**，而该 artifact 已被更正两次（F2 我修于 `62b967a`；F1/F3/F4/F5/F6 修于 `f7749af`） | **追认 1.5.1 为"形状更正补丁"**，并确认追认覆盖的是 v1.5 的 **additive 增量**（语义不变） | 追认对象的唯一性；TL 已在执行层要求队友 bump |
| **A-5** | **错误信封族 Part B**（实现修复）：`/api/skill/execute` 未捕获异常须返回合同声明的 `ErrorResponse` 信封（现为 FastAPI 默认 500 纯文本） | TL 已按"发现问题直接修"**授权**（仅 `src/kert/api/server.py` 一处；不得改 2xx 路径与认证中间件；500 消息须通用、不得放 `str(exc)`）——**供你知悉**，如反对请驳回 | 无（执行中） |

## B. 治理 / 发布 / 流程类（Owner）

| # | 事项 | TL 建议 | 阻塞什么 |
|---|---|---|---|
| **B-1** | **发布制品哈希不含 `specs/`**（`src/kert/infrastructure/release.py:217-224` 只含 `docs/contracts/**`）⇒ **运行中权威合同不在发布哈希覆盖内** | 应把 `specs/**` 纳入哈希范围；但**改哈希会改变既有制品比对结果**（发布语义变更）⇒ 需你裁决后我再动 | 发布完整性口径；归并 P2 |
| **B-2** | **CI 是否接入 prod-profile 路径**：CI 用 `KERT_PROFILE=dev`（免鉴权），本仓编排固定 `prod`（强制鉴权）⇒ 本次"只在 prod 才暴露"的问题（e2e 无鉴权通道、`provision --init`）**CI 永远发现不了** | 建议增加一条"本仓编排真跑"的 CI job（或至少把 `make verify-e2e-local` 纳入发布前手检清单）；CI 变更属流水线治理，**我不代决** | 是否再把同类缝漏过去 |
| **B-3** | **状态基线修订候选 R-1~R-5**（`docs/governance/KERT_STATUS_BASELINE_REVISION_CANDIDATE_M7.md`；基线仍记 `knowledge_map_registry: DESIGNED_NOT_IMPLEMENTED`） | 逐条签署 R-1~R-5（`verification` 一律记 **PARTIAL**）；基线文件我**一个字节未改**（守"不静默改写"纪律） | 状态权威源与代码继续脱节 |
| **B-4** | **M7.2 ToolRegistry 默认拒绝**是否开工 | 建议**待 M7.1 设计结论落地后再派**（二者共享"能力注册 + 默认拒绝"模型，避免两次返工） | M7 收口范围 |
| **B-5** | **GITS 侧通知送达**：`docs/integration/KERT_GITS_CONTRACT_DIFF.md`（本仓）已备料列出 F3/F4 等影响调用方口径的差异；**嵌套位置不变、GITS 现有读取不受影响** | 是否需要正式送达 GITS、走何渠道（我**不得**动 GITS 仓） | 跨仓口径同步 |

## C. M7.1（KnowledgeSource）后续

| # | 事项 | TL 建议 | 阻塞什么 |
|---|---|---|---|
| **C-1** | **第二片-B（真实能力适配器 + 接线）**：会把 `knowledge_sources.json` 接到技能读取路径 ⇒ 未供给的工作区将 **fail-closed 拒绝读取**（`DECLARATION_ABSENT`） | 需四道门：① 第二片-A（供给纳入）完成 ② 部署侧供给落地 ③ 影响面 + 回滚方案 ④ **你裁决**（与 ⑤b-full 同节奏）。TL 已明令队友**勿先动** `skills.py`/`api/**` | M7.1 的真实落地 |
| **C-2** | **`required` 强制（M7.3 遗留 (B)）**：必需资产缺失时是否拒绝执行 | 与 v1.3"evidence ok/skipped 不阻塞"纪律冲突 ⇒ 需**域 Owner** 决策；建议维持不实施 | 失败语义的最终边界 |

## D. 已知缺口（知情项，不阻塞）

| # | 事项 | 现状 |
|---|---|---|
| **D-1** | **21 条跨服务 e2e 未验证**（GITS `:8082` / `:5173` 未起） | **F-E2E-01 缺口仍在**；"本次 26 条绿"**不得**读作跨服务链路已验证 |
| **D-2** | **模型输出内容质量未验证** | 26 条全走确定性适配器（容器内无模型 Key） |
| **D-3** | `_handle()` 对非 KERT 异常返回 `str(exc)`，与 A-5 新处理器口径不一致 | 列为后续议题，本批不动 |
| **D-4** | 容器复测约束 | 镜像会"存在但内容陈旧"；`COPY` 取**构建期工作区**而非 HEAD ⇒ 后续片须**先提交再 build**，证据绑定**镜像 sha256 + 镜像内交付物 sha256** |
| **D-5** | **供给面口径变更（5 → 6 类文件）**：M7.1 第二片-A 起，`90_control/schema/knowledge_sources.json` 纳入供给 ⇒ 新运行的 CLI 输出为"新建 6 / 覆盖 0 / 未变 6" | **历史证据不回填**（`EVIDENCE-PROVISIONING.md`、`EVIDENCE-5B-FULL.md`、`EVIDENCE-E2E-STACK-UP.md` 中的"5"如实反映当时供给面）；本条即口径变更记录。**声明缺失按"不供给、不报错"**处理（与本体引用同口径，已由 TL 复核接受）；若日后要改为"缺失即拒绝"，属**语义升级**，需另裁 |

## 非声明

本清单是**决策请求**，不是批准、不是基线、不是 ADR；不代表 `PRODUCTION_RELEASE_GATE` 变化（仍 **BLOCKED**）、不代表 GITS UAT 通过；未改合同、`03_core`、GITS 仓。
