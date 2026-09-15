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
| **A-5** | **错误信封族 Part B**（实现修复）：`/api/skill/execute` 未捕获异常须返回合同声明的 `ErrorResponse` 信封（现为 FastAPI 默认 500 纯文本） | 已由 c20 **完成并提交**（`e3bcefe`）；TL 核实：`server.py` 1 处（+29/−1，sha `7e516e610c43d482`）、不改 2xx 路径与中间件、消息通用不回显 `str(exc)`、用例含**金丝雀断言**（异常细节不得出现在响应体） | 无 |
| **A-6** | **F8：9 条"已实现但合同未声明"路径**（`/v1/extractions`(202)、`/v1/extractions/{job_id}/result`、`/v1/entities/{entity_id}`、`/v1/data/query`、`/v1/search`、`/v1/graph/query`、`/v1/rules/evaluate`、`/v1/evidence/{object_id}`、`/v1/catalog`）；**另 1 条反向缺口** `/v1/skills`（合同声明但实现缺失） | **需你裁决**。**TL 建议 A**（9 条一次性登记，`1.5.1 → 1.6.0`），**条件** = 每条须配**机械核对**（实现侧证据 + 用例），否则又是一次"手写声明、从未校验"。**B** 仅在你想压缩工作量时成立，但**豁免清单必须成文**；**C 须先拿出"无外部调用方"的证据**才成立，不接受凭偏好选。附裁 2 项：`/v1/skills` 建议**从合同删除**（合同不得承诺不存在的东西，除非已对某调用方承诺过 —— 需先补"是否有调用方"的事实）；`/v1/graph/query` 与 v2 声明的差异随 **C-20** 归并处理。提案：`evidence/m7-3/PROPOSAL_REGISTER_UNDECLARED_V1_PATHS.md` | `/v1/*` 面合同化完整性 |
| **A-7** | **1.5.1 追认对象**：合同已 bump `1.5.0 → 1.5.1`（形状/错误响应更正），提交于 `e3bcefe` | **待你追认**：确认追认覆盖 v1.5 的 **additive 增量**、且 `1.5.1` 为**形状更正补丁**（语义不变）。同时 `1.5.1` 已含 F4b/F4d/F4e 三处形状更正（execute 400→422、report 404 字符串 detail、maps 500 `oneOf`） | 追认对象的唯一性 |
| **A-8** | **锚点刷新轮（D-8 落地）**：`server.py` 因本批净 **+28 行** ⇒ 冻结件中旧行号引用需刷新：合同 **14 处** + 测试注释 **7 处**；`evidence/m7-3/CANDIDATE-*.md` / `EVIDENCE-*.md` / 本决策清单属**带日期的快照**，**旧行号保留不改** | TL **已授权但设门**：**等 m71 冻结态复测结束**再开工（否则又制造"并发期跑数不可归因"）。附加要求：① 零语义（纯文本）② 附**扫描证据**（`grep -rn "server\.py:[0-9]"` 全量输出 + 显式豁免清单）③ 开工前确认**无任何用例/脚本对 `specs/**` 做内容哈希**（文本改动会连锁改哈希）④ 报新 sha。<br>**c20 开工前自查已 PASS**（TL 复核：`release.py:216-225` 哈希范围不含 `specs/`+`tests/` ✓；无内容哈希消费者 ✓；零位移基线 `1826`/`432` 行 ✓）；**范围确认** `test_routing_api.py` 不纳入（实测 0 处引用）；**新增两条不变式**：A 零位移（刷新保持行数不变 ⇒ 22 个 `.md` 的 `v1:NNN` 引用不漂移）、B 零语义（归一化 JSON 逐字节比对 + 四项自检不变）；扫描须按 **REFRESH / ALREADY-CORRECT / SNAPSHOT-EXEMPT** 三类**逐文件**列举并可核对。<br>**首扫口径差异已闭合**（c20 首扫 60 vs TL 62：固定 3 位模式 `:[0-9]\{3\}` 漏 3 处**2 位数**引用 + 行/出现口径混用差 3）⇒ **以 62 为准**，统一为 `server\.py:[0-9]\+` + **行数**口径 + **`--exclude-dir=__pycache__`**（实测 `git ls-files 'tests/**/__pycache__'`=**0**、`.gitignore:3` ⇒ 归 **DERIVED/BUILD-ARTIFACT**，不刷新亦不豁免；**不靠"碰巧没命中"**）。<br>**偏移规则修正为三段（已用 git 历史验证）**：`git show dafe1fe:…/server.py` vs 现在 ⇒ `_response` **206→208**、`_handle` **308→310** ⇒ **+2**（非 +28）⇒ 旧 `>316` → **+28**；旧 `59..316` → **+2**；旧 `<59` → **0**；**禁止套用统一偏移**。<br>**"快照不可当锚点"的实证**：`CANDIDATE-M7-1-KNOWLEDGE-SOURCE.md:60` 路由行号整体 **+28** 漂移（写于 Part B 前），而同批 `IMPACT-ANALYSIS-M7-1-B.md:288` 的 `:667-671` **正确** ⇒ **同批快照内漂移不一致**（两份均不改）。 | 引用可核性（不影响功能） |
| **A-9** | **F8 §5.1 `/v1/skills`（声明了但未实现）的处置** —— c20 已补事实（**不给倾向**）：GITS **无调用**（`KERT_GITS_CONTRACT_DIFF.md:14/96/145` 三处一致）；代码级唯一调用者是 KERT **自身参考样例**（`examples/gits_adapter/python/kert_client.py:199-201`、`curl/list_skills.sh:24-25`）；文档层面是**"计划"非"承诺"**（`M3_PLAN_GITS_INTEGRATION.md:44/132` 等） | **TL 建议：删除**（合同不得声明不存在的端点；"声明了但不存在"比"未声明"更坏；删除**不破坏任何调用方**，代价=同步 3 处孤儿引用标注）。备选"**实现它**"（P2 曾计划）可同时关闭反向缺口并让参考样例有效，属合法但另立的工作。**无论选哪个，孤儿引用必须同轮同步** | `/v1/*` 面合同化一致性 |

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
| **C-1a** | **第二片-B-1（等价替换）**：仅**成功路径**切能力驱动；源不可用仍 `skipped` + 具名原因 ⇒ 预期 **0 条**既有用例变化 | TL **已授权出实现方案候选（不改码）**；要求在 **HEAD 冻结态**复测"0 变化"。**等价前提（TL 硬规则）**：**声明缺失 ⇒ 回落今日字面量读取路径**（不拒绝、不报错）；"缺失即拒绝"整体归 C-1b。并要求**新增**一个用例钉住"计划放行 + 声明缺失 ⇒ 回落"（该组合**今天完全没测**），变异点须含"声明缺失时拒绝"以证明回落规则有用例保护 | 接线本身（低风险半边） |
| **C-1b** | **第二片-B-2（严格 fail-closed）**：**两处语义升级打包**——① 源不可用由"被吞成 `skipped`"改为**显式拒绝**；② **运行时层**声明缺失（`KnowledgeSourceResolver` → `KNOWLEDGE_SOURCE_DECLARATION_ABSENT`）由"回落字面量"改为**拒绝** | **需你裁决** —— 它改的是**已声明业务语义**：`IMPACT-ANALYSIS-M7-1-B.md` 实跑枚举出的 **A 组 29 条**用例即该语义的断言载体（`test_outreach_ok_no_library` / `test_meeting_ok_no_library` / `test_kert_skipped_without_customer_knowledge` 等），**改它们＝改语义**，不得由开发自行改测试对齐实现。⚠ ②虽**不增加**既有用例破面（44 条中无"计划放行+声明缺失"，唯二声明缺失用例已在计划门禁被拒）**但这不等于无风险**：**第二片-A 之前供给过的工作区/手工配置工作区没有该声明** ⇒ 真实部署可达，只是未测。"未测"不得当作"无风险"。附风险：**代码已接线 + 声明未供给 ⇒ 三技能全拒绝**（危险窗口；正常编排已由 `provision` 前置依赖自动闭合） | M7.1 的真实语义落地 |
| **C-2** | **`required` 强制（M7.3 遗留 (B)）**：必需资产缺失时是否拒绝执行 | 与 v1.3"evidence ok/skipped 不阻塞"纪律冲突 ⇒ 需**域 Owner** 决策；**TL 已裁定不随之升格**，并要求 B-1 加**机械核对**防"未绑定⇒拒绝"顺带把 `required:false` 变成必需 | 失败语义的最终边界 |

| **C-3** | **canonical schema additive 增量**：B-1 会引入两个新 trace 字段（`capabilityId`/`sourceCode`），须**同步** `docs/contracts/schemas/assembly-trace.schema.json` | **待 Contract Owner 追认**（按 v1.5 先例：additive 先行 + 提案 + 登记 §0.1）。理由：只靠 `additionalProperties` 兜底**正是上一轮刚被纠正的**"实现有字段、合同未声明"失实模式，不得重演。**合同本体（`specs/**`、v2 候选）不动**；B-1 实施白名单中新纳入该 schema 文件的"仅追加两字段" | B-1 的观测面孔 |


### C-4 B-1 定稿（Q1–Q5，TL 2026-09-16）

> ⚠ **记录纪律（TL 自查纠正）**：本轮 Q1–Q5 此前**只落在 commit message（`d4935f9`）**中，
> **未落本清单** ⇒ 队友按清单核对时只找到 C-3，并**诚实报告**了这一点。教训：**定稿必须落决策清单**，
> commit message 不作为可核对记录。另：C-3 原被误插入 D 表（已移回本节）。

| 项 | 定稿（TL） |
|---|---|
| **Q1 命名** | `_load_ki_from_declaration`；**签名须与 `_load_ki` 完全一致**（同参同返回 ⇒ 替换机械可判、等价性可证）；前缀刻意保留，使"全部 KI 读取点"可用一个前缀 grep 枚举 |
| **Q2 字段** | `capabilityId` + `sourceCode`（**须同步 canonical schema**，见 C-3） |
| **Q3 留痕粒度** | **逐资产一条**；三约束：**不带 `kiId`**（T1）；`message` **不含子串 `KI-`**（T3，故能力标识只走 `capabilityId` 字段）；**只追加在既有序列末尾**（使"剔除新增条目即可还原"机械可判）。附 TL 自我更正：原拟以"trace 条数敏感断言"驳回逐资产粒度，**实查 grep 皆空**（`len(assembly_trace)` / `assembly_trace[i]` 无命中）⇒ 该风险不存在，采纳队友设计 |
| **Q4 调用点守卫** | **加**，且**白名单精确**：调用点集合 ≠ {outreach, meeting, previsit} 即 FAIL；并显式断言 `_run_supply_chain` **不**调用它（防 D 组被顺手接线）；守卫**不得可静默跳过** |
| **Q5 先后** | **先冻结态复测、再开工**；复测口径：干净工作树 + `git rev-parse HEAD` + 那份 44 条枚举 + 全量四目录（unit/integration/contract/recovery）**原始计数与退出码**；并须复核"**(γ) 组合在接线前确实零覆盖**"这一前提本身（否则补洞定位需重估） |
| **报数规则 R-A…R-D** | m71 实测的**测量学问题**（写入其方案 §6 第 7 项）：同树、同探针**两跑完全一致**（A/B/C/E = **29/9/3/3**，`_load_ki` 观测 = **44**）；但**结构等价的精简探针**跑出 **30/9/3/2**（43 条）⇒ 漂移**不来自树状态**，来自 **`_load_ki` 调用在异步/线程路径上的 nodeid 归属竞态**。规则：异步/线程条目逐条人工确认 / 探针两跑并报差异 / **无法稳定归属一律归 E 不得计入 A** / 报数附探针 sha256 | **TL 采纳并加固**：① **A 组取两跑交集**（任一次缺席即归 E；宁可少不许虚增）② 冻结态**以原版探针** `d73ce3c6…6639b` 为准，精简版仅交叉验证并须说明差异机制 ③ 报告补**探针命令行** + python/pytest 版本 + HEAD + `git status` 原文 |
| **实施授权** | **条件性授权（已给，无需再次审批）**：① c20 落定（已发生）→ ② **冻结态复测确认"0 变化"**并回报原始计数 ⇒ **即可开工**。白名单：`src/kert/application/skills.py`、**新增**测试文件、`docs/contracts/schemas/assembly-trace.schema.json`（**仅追加两字段**）、`evidence/m7-3/**`；**既有测试文件一字不改**（含 `test_skills.py`）；新测试自带夹具。<br>⚠ **冻结时机已修订**：第三方批次在途（改 `provision.py`/`cli/main.py`/`test_provision.py` + 新增 activation 模块与测试）⇒ 四目录跑会掺入别人半成品 ⇒ **正式冻结跑等那批落定**（TL 发新信号）。允许"明确标注含第三方在途"的**预跑**，但不得作为冻结证据 |


#### C-4.1 Q1-i 裁定：留痕范围 = **声明的 bindings 集合**（不读计划）

> TL 裁定（2026-09-16）：**签名逐字一致优先于留痕范围**。理由：B-1 的价值在"可证的等价"，纯代入才能只证行为、不证依赖变化；传 `plan` 会把"计划读取"引入一个此前完全不读计划的方法。
> 已**独立核实**前提：声明 `bindings` = **7 条**（`KI-009` + `KI-FRONT-001…006`）、三张地图 `assetRefs` 并集 = **同样 7 条** ⇒ scope=bindings 与 scope=map-union 在受控工作区**相等**；该等式由 `tests/unit/test_knowledge_source.py:228-240` 以**双向等式 + 诊断信息**钉住（非单向包含）。
> **具名依赖**：若该用例被放宽/改写/移除，本 scope 决策必须**重审**。
>
> 配套四条（v1.4 待补）：① 加 `inspect.signature` 等式守卫（比源码扫描更能抓住"参数变了"）；② 上述等式登记为具名依赖并写明后果；③ 显式写明**语义噪声** —— scope 是**并集**而单任务计划资产是其**子集** ⇒ 回落时可能列出多于该任务所需的资产（非等价性问题，但**不得**被读成"该任务需要全量"；且资产 ID 不得进 `message`，T3）；④ **plan-scoped 留痕属 B-2 议题**（需读计划），B-1 不留口子。

#### C-4.2 归因观察：第三方在途新增 `src/kert/domain/activation_contract.py`

`git status` 出现 `?? src/kert/domain/activation_contract.py`（§5.5 ② 激活合同注册/解析，读 `<ws>/90_control/schema/activations/AC-*.json`）—— **非 c20、非 m71**。⇒ 冻结信号须附"`git rev-parse HEAD` + 完整 `git status` 快照"以保归因；并**预告**：该模块读控制面 `schema/`，若纳入部署则**供给面清单将再次扩项**（现行 6 类文件），属后续议题（与 D-5 同族）。


## D. 已知缺口（知情项，不阻塞）

| # | 事项 | 现状 |
|---|---|---|
| **D-1** | **21 条跨服务 e2e 未验证**（GITS `:8082` / `:5173` 未起） | **F-E2E-01 缺口仍在**；"本次 26 条绿"**不得**读作跨服务链路已验证 |
| **D-2** | **模型输出内容质量未验证** | 26 条全走确定性适配器（容器内无模型 Key） |
| **D-3** | `_handle()` 对非 KERT 异常返回 `str(exc)`，与 A-5 新处理器口径不一致 | 列为后续议题，本批不动 |
| **D-4** | 容器复测约束 | 镜像会"存在但内容陈旧"；`COPY` 取**构建期工作区**而非 HEAD ⇒ 后续片须**先提交再 build**，证据绑定**镜像 sha256 + 镜像内交付物 sha256** |
| **D-5** | **供给面口径变更（5 → 6 类文件）**：M7.1 第二片-A 起，`90_control/schema/knowledge_sources.json` 纳入供给 ⇒ 新运行的 CLI 输出为"新建 6 / 覆盖 0 / 未变 6" | **历史证据不回填**（`EVIDENCE-PROVISIONING.md`、`EVIDENCE-5B-FULL.md`、`EVIDENCE-E2E-STACK-UP.md` 中的"5"如实反映当时供给面）；本条即口径变更记录。**声明缺失按"不供给、不报错"**处理（与本体引用同口径，已由 TL 复核接受）；若日后要改为"缺失即拒绝"，属**语义升级**，需另裁。⚠ **在途第三方批次已把 `90_control/schema/activations/AC-*.json` 纳入供给（`provision.py`/`cli/main.py`/`test_provision.py` 在改，CLI 输出新增"合同: N"）⇒ 该批落地后应为 **7 类文件**；本条同步**由 TL 负责**（不等落批人）** |
| **D-6** | **e2e 假绿风险**：`/api/skill/execute` 对**一切业务错误**返回 **200**（仅 `UNKNOWN_SKILL` 为 404，`server.py` 读码确认），而 e2e 只断言 `status_code in (200,201,202)` + 字段存在 ⇒ **部署工作区未供给时 e2e 仍绿，而技能实际 `skill_error`** | 已登记为 **C-1b 的交付项之一**；**不在 B-1 改 e2e**。若强化断言（须能区分 `ok`/`skill_error`），会牵动 **CI 供给**（未供给即红）⇒ 属**流水线决策**，需你裁 |
| **D-7** | **读取路径一致性债**：`_run_supply_chain`（技能包 `bank-front-supply-chain-graph`）仍为**字面量驱动**读取，将与能力驱动路径**并存** | **不得**表述为"读取已全部接线"；归 O-6 / M7.2 范围，需另立 |
| **D-8** | **引用纪律**：`src/kert/api/server.py` 常被并行改动（本轮 c20 在途 +29 行） | 引用该文件必须 **"函数名 + 行号"双锚**，并在文档顶部记**行号基准快照**；并发编辑期间的跑数**不可归因**（见"先冻结再跑"规则） |
| **D-9** | **第三方在途未归因**（非 c20、非 m71）：`src/kert/domain/activation_contract.py`、`tests/unit/test_activation_contract.py`、`examples/bank-front-knowledge-maps/90_control/schema/activations/`、**`src/kert/application/provision.py`、`src/kert/cli/main.py`、`tests/unit/test_provision.py`**（均在途修改）、`.understandignore`（他人会话 UA-D10） | 非本轮任何队友所为；**复测/冻结须归因**（附 `git rev-parse HEAD` + 完整 `git status` 快照；期间变动即作废重跑）。该模块读 `<ws>/90_control/schema/activations/AC-*.json`，且**第三方正在改 provisioning** ⇒ **供给面口径可能再变**（现行 6 类文件），与 D-5 同族；B-1 复测的枚举基线也可能随之偏移 （影响：复测归因 / 供给面口径 / B-1 基线） |
| **D-10** | **性能基准 flake**：`tests/performance/test_concurrency_benchmark.py:221` 墙钟阈值（`assert avg_create < 20.0`）在冻结态偶发 FAIL（本轮 2 条；此前 1 条 / 3 条，**失败集合漂移**） | TL **隔离复跑仍 FAIL** ⇒ 已证与 c20 改动无关。**结构性理由（比"机器负载"更强）**：多智能体并发跑测使**墙钟阈值基准结构性不可靠** —— 我们自己的并发就在污染它。⇒ 该文件**不得**作为验收/冻结证据；由你决定放宽阈值 / 加 `perf` marker / 移出默认套件 （影响：每次"冻结态"跑数都会被它污染） |

## 非声明

本清单是**决策请求**，不是批准、不是基线、不是 ADR；不代表 `PRODUCTION_RELEASE_GATE` 变化（仍 **BLOCKED**）、不代表 GITS UAT 通过；未改合同、`03_core`、GITS 仓。
