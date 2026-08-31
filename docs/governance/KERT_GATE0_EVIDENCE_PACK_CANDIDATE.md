# KERT Gate 0 证据包（WP0-2）

> 状态块：
> - **CANDIDATE**
> - **FROZEN=NO**
> - **IMPLEMENTED=NO**
>
> 本文档是 **WP0-2 交付物**。所有结论均基于对知识工程仓库 `~/dev/Leibniz-KERT` 实际源码/契约/测试/ADR 的逐文件取证，未臆造；未落地或与文档不一致之处均如实标注。

- 生成日期：2026-08-31
- 取证仓库：`~/dev/Leibniz-KERT`（git remote `origin = git@github.com:shaozhongfei001/Leibniz-KERT.git`）
- **取证基线（可复现锚点）**：HEAD commit `0625afbf83a51fc1c256e41aca173248a874a777`（`0625afb`，`fix(ci): establish lint baseline and fix benchmark threshold model`）。**本包所有可复现结论均以该 commit 内容为准**，用 `git show 0625afbf:<path>` 可逐文件复现。
- 取证方式：`read`/`grep` 直接读源码、契约、测试、ADR，未臆造。

---

## 0. 取证清单与基线声明

### 0.1 取证基线（必须从固定 commit 复现）

- 本包对**源码、测试、契约 schema、ADR、README/状态基线**的取证，全部落在 HEAD `0625afbf` 已提交内容上。经 `git status -s` 核验，下列取证文件在 HEAD 均**无未提交改动**（工作区 == HEAD）：
  `src/dkws/**`（server.py/middleware.py/skills.py/errors.py/workspace.py/publish.py/jobs.py/observability.py/backup.py/runtime_config.py）、`tests/**`、`docs/contracts/schemas/*.json`、`docs/adr/ADR-013/ADR-016`、`docs/skill-execute-api-contract-v1.4.md`、`docs/governance/DKWS_STATUS_BASELINE_CANDIDATE.yaml`、`README.md`、`ADR.md`、`pyproject.toml`。
- **唯一例外（如实声明）**：`specs/dkws-openapi-v1.yaml` 存在**未提交工作区改动**，`skills/product-recommendation/` 为**未跟踪新目录**（详见 §2.1/§2.2 与 §10）。本包对这两处的引用**已显式标注为「未提交工作区版本」**，并同时给出 HEAD 基线内容，保证可复现：凡引用 OpenAPI 已提交事实时一律给 HEAD 行号，凡引用 SP-15 增量时一律标注「HEAD 无此内容」。

### 0.2 实际读取的文件

| 类别 | 文件 | 基线 |
|---|---|---|
| 项目 | `README.md`、`pyproject.toml`、`ADR.md` | HEAD |
| 契约 | `specs/dkws-openapi-v1.yaml`（v1.4.0） | HEAD + 标注未提交 delta |
| 契约 | `docs/skill-execute-api-contract-v1.4.md` | HEAD |
| 契约 | `docs/contracts/schemas/{context-package,evidence-bundle,assembly-trace}.schema.json` | HEAD |
| 鉴权 | `src/dkws/api/middleware.py`、`src/dkws/infrastructure/runtime_config.py` | HEAD |
| 执行 | `src/dkws/api/server.py`、`src/dkws/application/skills.py` | HEAD |
| 错误 | `src/dkws/domain/errors.py` | HEAD |
| 存储 | `src/dkws/domain/workspace.py`、`src/dkws/application/publish.py`、`src/dkws/application/jobs.py` | HEAD |
| 可观测 | `src/dkws/infrastructure/observability.py`、`src/dkws/infrastructure/backup.py` | HEAD |
| 治理 | `docs/governance/DKWS_STATUS_BASELINE_CANDIDATE.yaml` | HEAD |
| ADR | `docs/adr/ADR-013-service-authentication.md`、`docs/adr/ADR-016-controlled-hybrid-skill-runtime.md` | HEAD |
| Skill 资产 | `skills/product-recommendation/{SP-15.md,contracts/recommendation-result.md,activation-contracts/AC-PRODUCT-RECOMMEND-001.md,product-cards/README.md,rules/README.md}` | **未跟踪（非 HEAD）** |
| 测试 | `tests/integration/test_skills.py`、`tests/e2e/test_all_skills_execution.py` | HEAD |
| GITS 只读 | `~/dev/gits-cbanking/specs/knowledge-architecture/skills/{SP-02,SP-05,SP-07,SP-15}.json` | 只读引用（GITS 侧） |

---

## 1. a) 正式项目名 / 仓库 / Owner

| 项 | 值 | 证据（HEAD） |
|---|---|---|
| 仓库名 | `Leibniz-KERT` | `git remote -v` → `origin = git@github.com:shaozhongfei001/Leibniz-KERT.git` |
| 包/项目名 | `dkws`（Data Knowledge Workspace Service） | `pyproject.toml` `[project] name = "dkws"` |
| 正式项目标识 | `DKWS-SPEC-001`，「文件目录型数据知识服务模拟平台」 | `README.md` 第 1 行、`docs/governance/DKWS_STATUS_BASELINE_CANDIDATE.yaml` `project.id` |
| 版本/阶段 | `baseline_state = DRAFT_CANDIDATE`、`production_ready = false`、`uat_pass = false` | `DKWS_STATUS_BASELINE_CANDIDATE.yaml` 第 9-13 行 |
| License | Proprietary | `pyproject.toml` 第 11 行、`specs/dkws-openapi-v1.yaml` `info.license` |
| 代码 Owner（git） | `shaozhongfei001` | `git log -1 --format='%an'` → `shaozhongfei001` |
| 业务 Owner（Skill 域） | SP-02=客户经营Owner、SP-05=KYC知识Owner、SP-07=evidence_owner、SP-15=公司金融产品管理部 | GITS `specs/knowledge-architecture/skills/*.json`（只读引用，见 §6.2） |

> 说明：`DKWS_STATUS_BASELINE_CANDIDATE.yaml`（HEAD）第 21-24 行仍记 `dkws_git_repo: false`、`dkws_git_commit_anchor: null`、`dkws_source_path: /home/szf/dev/deepseek_harness/data_knowledge_ws/dkws`，与本仓库已具 git remote + 固定 HEAD 的现状不一致，属**状态基线陈旧**（该文件生成于 2026-08-26，早于本仓库 git 化）。本包以实际 `git rev-parse HEAD = 0625afbf` 为权威锚点。

**判定：PRESENT_AND_CONTROLLED**（仓库、包名、提交锚点均可取证；工程级 Owner 未在 KERT 仓库内以「单一负责人」字段固化，而是分散在 GITS 侧 skill 描述符的 `owner` 字段，属轻微缺口，不影响 Gate 0）。

---

## 2. b) Skill 执行 OpenAPI 与错误码清单

### 2.1 OpenAPI 基线（HEAD 0625afbf）

- 权威文件：`specs/dkws-openapi-v1.yaml`，`info.version = "1.4.0"`（HEAD 第 11 行）。
- 权威契约文档：`docs/skill-execute-api-contract-v1.4.md`（spec 内 `info.description` 引用，HEAD 第 10 行）。
- 已登记端点（`paths`，HEAD）：`GET /v1/health`、`GET /api/skill/health`、`GET /v1/skills`、`POST /api/skill/execute`、`GET /api/skill/report/{requestId}`、`GET /api/skill/gates/{customerId}`、`POST /api/skill/gates/audit`、`GET /v1/jobs/{jobId}`、`GET /livez`、`GET /readyz`、`GET /metrics`。
- `components.securitySchemes.ApiKeyAuth`（HEAD 第 445-447 行）：`type: apiKey`、`in: header`、`name: X-API-Key`、描述「API Key 认证（演示环境可省略）」。

> **未提交 delta 声明（如实）**：`git diff specs/dkws-openapi-v1.yaml` 显示，工作区相对 HEAD 新增两处、均为**并行任务未提交产物**，**HEAD 中不存在**：
> 1. `+/v1/health` 示例末尾新增 `SP-15 产品适配与综合方案 2.0.0-candidate`（工作区第 60-62 行；HEAD 该示例只到 SP-21，HEAD 第 50-58 行）；
> 2. `+ErrorDetail.code` 描述末尾新增 8 个 `KERT_*` 错误码（工作区第 1024-1031 行；HEAD 该描述止于 `INTERNAL_ERROR`，HEAD 第 1020 行）。
>
> 因此，**凡本包引用 OpenAPI 的已提交事实，一律锚定 HEAD 行号**；上述两处 SP-15 增量属**未提交工作区内容**，不作为 Gate 0 可复现基线，仅在 §2.2(3)/§2.3(4) 作为「未提交、未实现」如实报告。

### 2.2 错误码清单（三层）

**（1）领域/传输层错误码（运行时权威）** — `src/dkws/domain/errors.py` `ERROR_CODES`（HEAD 第 24-44 行，共 19 项）：

| 错误码 | HTTP | retryable |
|---|---|---|
| INVALID_REQUEST | 400 | false |
| PATH_OUTSIDE_WORKSPACE | 400 | false |
| ASSET_NOT_FOUND | 404 | false |
| VERSION_NOT_FOUND | 404 | false |
| IDEMPOTENCY_CONFLICT | 409 | false |
| WORKSPACE_LOCKED | 409 | true |
| UNAUTHENTICATED | 401 | false |
| FORBIDDEN | 403 | false |
| RATE_LIMITED | 429 | true |
| CONCURRENCY_LIMITED | 429 | true |
| SCHEMA_VALIDATION_FAILED | 422 | false |
| QUALITY_GATE_FAILED | 422 | false |
| UNAPPROVED_ASSET | 422 | false |
| UNSUPPORTED_MEDIA_TYPE | 415 | false |
| PAYLOAD_TOO_LARGE | 413 | false |
| SERVICE_NOT_READY | 503 | true |
| INTERNAL_ERROR | 500 | true |
| JOB_ORPHANED | 500 | false |
| RULE_CONFLICT | 409 | false |

> 微瑕备注（不影响判定）：`JOB_ORPHANED`/`RULE_CONFLICT` 两条的 `ErrorCode(code=...)` 内嵌字符串分别为 `"INTERNAL_ERROR"`/`"INVALID_REQUEST"`（`errors.py` 第 42-43 行，疑为复制粘贴遗留）；HTTP 状态码取值不受影响（`http_status()` 用 dict 键查表），但 `ERROR_CODES[k].code` 会返回错误字符串。属低危一致性缺陷，如实记录。

**（2）Skill 层错误码（运行时真实发出）** — `src/dkws/application/skills.py`：

- `UNKNOWN_SKILL`（未知 skillId，`skills.py` 第 193 行；`server.py` 第 555-559 行映射 HTTP 404）
- `SKILL_EXECUTION_FAILED`（执行器抛异常，fail-closed；`skills.py` 第 230 行）

**（3）KERT_* 失败码 —— 仅「未提交文档」，运行时代码未实现（如实标注 UNCONTROLLED）**：

- 来源一：`specs/dkws-openapi-v1.yaml` 工作区**未提交**版本 `ErrorDetail.code`（工作区第 1024-1031 行），HEAD 无此内容。
- 来源二：`skills/product-recommendation/SP-15.md` 第 82 行（**未跟踪**文件）列出 8 个 `KERT_*`：`KERT_PERMISSION_DENIED / KERT_CONTEXT_INSUFFICIENT / KERT_PRODUCT_KNOWLEDGE_STALE / KERT_RULE_VERSION_MISSING / KERT_EXECUTION_TIMEOUT / KERT_CONTRACT_MISMATCH / KERT_EVIDENCE_INCOMPLETE / KERT_INTERNAL_ERROR`。
- **实测**：`grep "KERT_" src` 命中 = 0；`grep` 证实运行时代码仅发出 `UNKNOWN_SKILL`/`SKILL_EXECUTION_FAILED`。KERT_* 系列失败码当前**无任何运行时代码抛出/返回**，且其两份文档来源**均未提交**；属 SP-15（未实现，见 §6）的「文档先行、实现未落地」。

### 2.3 已发现的合同不一致（如实标注 UNCONTROLLED；行号均为 HEAD）

1. **`assemblyTrace` 类型漂移**：OpenAPI 定义为 `type: object`（HEAD 第 622-623 行），但运行时 `SkillExecuteResult.as_dict()` 返回 `assemblyTrace` 为**数组**（`skills.py` 第 51、61 行）。
2. **`requestId`/`request` 必需性漂移**：OpenAPI `SkillExecuteRequest.required = [skillId, requestId, request]`（HEAD 第 537 行），但代码 `SkillExecuteRequest` 中 `requestId: str | None = None`、`request: dict = default`（`server.py` 第 67-68 行），仅 `skillId` 必填。
3. **`/v1/health` 响应形状漂移**：OpenAPI `HealthResponse` 为 `{status, timestamp, skills}`（HEAD 第 451-462 行），实际 `/v1/health` 返回 `_response` 信封 `{request_id, status, data:{status, service_version, data_version, runtime}, errors, meta}`（`server.py` 第 364-385 行）；`{status, skills}` 形状实际由 `/api/skill/health` 返回（`server.py` 第 525-533 行）。
4. **SP-15 出现在 OpenAPI 健康示例、但不在运行注册表**：此差异仅存在于**未提交工作区** OpenAPI `/v1/health` 示例（工作区第 60-62 行）；HEAD 示例不含 SP-15。无论工作区或 HEAD，运行 `/api/skill/health` 注册表均不含 SP-15（见 §6）。

**判定：PRESENT（OpenAPI 存在且机器可读，HEAD 可复现），但错误码/响应形状存在文档-实现漂移 → 契约层 UNCONTROLLED（详见 §9 例外清单）。**

---

## 3. c) 同步/异步模式与轮询/回调约定

### 3.1 同步模式（默认）

- 端点：`POST /api/skill/execute`，`async` 未传或 `false`。
- 返回：`200` + `SkillExecuteResponse`（`requestId/status/data/errors/assemblyTrace/modelCalls`）。
- 证据：`server.py` 第 550-559 行；`skills.py` `execute()` 第 170-232 行。
- `status` 闭集：`ok` / `skill_error` / `exit_policy_no_new_evidence`（`skills.py` 第 48、191-213、225-232 行；OpenAPI HEAD 第 615 行同枚举）。

### 3.2 异步模式

- 触发：请求体 `"async": true`（`SkillExecuteRequest.async_run`，别名 `async`，`server.py` 第 71 行）。
- 返回：`202` + `{"jobId": "...", "status": "PENDING"}`（`server.py` 第 544-549 行）。
- 轮询：`GET /v1/jobs/{jobId}`（`server.py` 第 418-424 行 → `application/jobs.py` `read_job_status` 第 312 行）。
- Job 状态机：`PENDING → RUNNING → (VALIDATING) → COMPLETED / FAILED`（`jobs.py` 第 66、150-152、182-190、208-214 行）。
- 完成语义：`COMPLETED` 时 `data.skill_result` 为完整 execute 响应（与同步同构）；`jobs.py` 第 324-329 行从 `90_control/jobs/{job_id}/result.json` 回填 `skill_result`。

### 3.3 两种异步实现（`skills.py` `execute_async` 第 267-342 行）

- **持久化模式（生产唯一允许）**：注入 `RuntimeStore` 时仅入队，由独立 Worker `scripts/run_worker.py` 领取（claim → RUNNING → COMPLETED）；进程崩溃后由 lease 回收重新调度（`infrastructure/runtime_store.py` `reclaim_expired_leases`、`infrastructure/worker.py`）。
- **线程模式（仅 dev 兼容）**：未注入 Store 时后台线程立即执行，进程退出即丢任务（`skills.py` 第 325-342 行）。
- **生产强制约束**：`profile=prod` 且未启用 Runtime Store 时 `execute_async` 抛 `ServiceNotReadyError`（HTTP 503），禁止回退线程模式（`skills.py` 第 299-306 行）。

### 3.4 回调约定

- **无回调机制**：OpenAPI 的 `AsyncAcceptedResponse` 仅含 `jobId/status`（HEAD 第 903-913 行），无 `callbackUrl`/webhook 字段；`paths` 中无 callback 定义。异步结果**只通过轮询 `GET /v1/jobs/{jobId}` 获取**。
- 轮询建议（GITS 侧约定）：间隔 3s、总上限 ~3min（`docs/gits-codebuddy-techlead-prompt-v14.md`、`docs/v14-joint-debugging-plan.md`）。

**判定：PRESENT_AND_CONTROLLED**（同步/异步/轮询均有代码与测试覆盖：`tests/integration/test_skills.py`、`tests/e2e/test_all_skills_execution.py`；回调为「无」而非「缺失」，属设计上未提供，需在 GITS 对接侧确认可接受轮询）。

---

## 4. d) 鉴权现状（X-API-Key 是否实现、演示环境状态）

### 4.1 X-API-Key 已实现（可选启用）

- 认证中间件：`src/dkws/api/middleware.py` `ApiKeyAuthMiddleware`（第 120-176 行）。
- 配置：`AuthConfig.header_name = "X-API-Key"`（`runtime_config.py` 第 82 行），可通过 `DKWS_AUTH_HEADER` 覆盖。
- 密钥存储：仅 SHA-256 摘要 + 常量时间比较（`runtime_config.py` `_digest`/`verify` 第 51-53、91-99 行），明文不落盘、不进日志。
- 作用域：`read`/`execute`/`admin`（`runtime_config.py` 第 42-44 行）；`/api/skill/gates/audit` 属 admin 路径前缀（第 40 行）。
- 白名单：`/v1/health`、`/api/skill/health`、`/livez`、`/readyz` 匿名放行（`DEFAULT_PUBLIC_PATHS`，第 32-33 行）。

### 4.2 演示/当前环境状态

- **默认 `auth.enabled = False`**（`AuthConfig.enabled` 默认 `False`，`runtime_config.py` 第 81 行）——dev 便利模式，全部放行。
- 状态基线：`docs/governance/DKWS_STATUS_BASELINE_CANDIDATE.yaml` 第 35-40 行记录 `listen_host: 0.0.0.0`、`listen_port: 8106`、`auth_enabled: false`、`tls_enabled: false`、`rate_limit_enabled: false`、`request_size_limit_enabled: false`。
- OpenAPI `securitySchemes.ApiKeyAuth` 描述亦写明「演示环境可省略」（HEAD 第 447 行）。

### 4.3 生产强约束（fail-fast）

- `runtime_config.py` `validate_runtime_config`（第 525-554 行）：生产 profile 下**必须**启用认证（且至少一个启用密钥）、限流、请求体大小限制；对外监听（非回环）且 `auth.enabled=false` 时**拒绝启动**。
- ADR-013 状态：`CANDIDATE_AWAITING_OWNER`（`docs/adr/ADR-013-service-authentication.md`），即鉴权方案已实现但 ADR 尚未获 Owner 批准。

**判定：PRESENT_BUT_UNCONTROLLED（演示）** —— X-API-Key 机制已实现且有安全测试（`tests/security/test_api_hardening.py`），但**当前运行环境 auth 默认关闭、无 TLS、无限流**（演示便利模式）；生产强约束已编码为 fail-fast，但 ADR-013 未获 Owner 批准。属 Gate 0 层面的「存在但未受控」。

---

## 5. e) ContextPackage / EvidenceBundle / 执行轨迹 合同现状

### 5.1 ContextPackage

- OpenAPI 定义：`ContextPackage`，`required: [schemaVersion, customerId]`（HEAD 第 581-605 行），用于 SP-20/SP-21。
- 候选 schema：`docs/contracts/schemas/context-package.schema.json`（HEAD），`required: []`、`additionalProperties: true`，自述「v1.4 ContextPackage 候选 Schema；权威 GITS 附录待对齐」。
- 运行时：`server.py` `SkillExecuteRequest.context` 为 `dict`，合并到 `request.context`（第 69、542-543 行）；**服务端不做 ContextPackage schema 强校验**（dict 透传）。

### 5.2 EvidenceBundle

- 候选 schema：`docs/contracts/schemas/evidence-bundle.schema.json`（HEAD），`required: [evidenceId, objectId, source, version, contentHash]`、`additionalProperties: false`。
- **运行路径未落地**：实际 Skill 结果仅含 `evidenceRefs`（`[{id, summary}]`，见 `skills.py` 第 564、598、626-633 行），无 EvidenceBundle 实体；`EvidenceBundleAssembler` 是 SP-15 内部步骤 8（`skills/product-recommendation/SP-15.md` 第 50 行，未跟踪文件），SP-15 未实现，故 EvidenceBundle **CANDIDATE 未实现**。

### 5.3 执行轨迹（assemblyTrace）

- 运行时已实现：`SkillExecuteResult.assembly_trace`（`skills.py` 第 51 行），以 **数组** 返回 `assemblyTrace`（`skills.py` 第 61 行）。
- 候选 schema：`docs/contracts/schemas/assembly-trace.schema.json`（HEAD），描述**单步** `AssemblyTraceStep`，`phase` 枚举 `resolve/idempotency/validate/dkws/evidence/model/parse/compose/tool`。
- 不一致：实际代码额外产生 `phase=llm_redaction`（`skills.py` 第 399 行），不在 schema 枚举内；且 OpenAPI 把 `assemblyTrace` 声明为 `type: object` 而非数组（见 §2.3）。

**判定：**
- ContextPackage：**PRESENT_BUT_UNCONTROLLED**（OpenAPI 有定义，但机器可读 schema 为 CANDIDATE 且未与 GITS 权威附录对齐、服务端不校验）。
- EvidenceBundle：**ABSENT（运行路径）**，仅 CANDIDATE schema + SP-15 设计。
- 执行轨迹：**PRESENT（已实现）**，但 schema/OpenAPI 类型未对齐 → 契约层 UNCONTROLLED。

---

## 6. f) Skill 注册表（SP-02 / SP-05 / SP-07 / SP-15 真实状态与版本）

### 6.1 运行时真实注册表（权威在 `src/dkws/application/skills.py` `registry()` 第 150-160 行 + 外部包加载）

**内置 5 个（版本均 1.0.0）：**

| skillId | 名称 | 版本 | 执行器 |
|---|---|---|---|
| `skill-customer-outreach-script` | 外联脚本 | 1.0.0 | `_run_outreach` |
| `skill-customer-meeting-script` | 会面脚本 | 1.0.0 | `_run_meeting` |
| `skill-customer-previsit-report` | R1 拜访报告 | 1.0.0 | `_run_previsit` |
| `SP-20` | 对公客户服务建议书生成 | 1.0.0 | `_run_service_proposal` |
| `SP-21` | 交互记忆抽取 | 1.0.0 | `_run_interaction_memory` |

**外部 bank-front 包 7 个（`examples/bank-front-skills/`，经 `_load_packages` 动态注册）：**
`bank-front-kyc-gap-check`、`bank-front-eight-dimension`、`bank-front-fact-reconciliation`、`bank-front-product-recommendation`、`bank-front-commitment-script`、`bank-front-report-assembler`、`bank-front-supply-chain-graph`。

→ 合计 **12 个**，与 `tests/e2e/test_all_skills_execution.py` `SKILL_IDS`（第 12-24 行，12 项）一致。

### 6.2 SP-02 / SP-05 / SP-07 / SP-15 真实状态

| skillId | KERT 仓库是否有资产 | 是否在 registry() | 是否有执行器 | 真实状态 |
|---|---|---|---|---|
| **SP-02** | 无（`grep SP-02 src` 命中 0） | 否 | 否 | **ABSENT**（仅 GITS `specs/knowledge-architecture/skills/SP-02.json` 有描述符：`version=1.1.0-p20`、`status=VALIDATION`、`owner=客户经营Owner`；KERT 无资产无执行器） |
| **SP-05** | 无 | 否 | 否 | **ABSENT**（仅 GITS `SP-05.json`：`version=1.1.0-p20`、`status=VALIDATION`、`owner=KYC知识Owner`） |
| **SP-07** | 无 | 否 | 否 | **ABSENT**（仅 GITS `SP-07.json`：`version=1.1.0-p20`、`status=VALIDATION`、`owner=evidence_owner`） |
| **SP-15** | **有 CANDIDATE 文档资产**（未跟踪 `skills/product-recommendation/SP-15.md`） | **否** | **否** | **CANDIDATE，未实现**（KERT `SP-15.md` front matter `version: 2.0.0-candidate`、`status: CANDIDATE`；`registry()` 不含、`_executor()` 第 472-511 行无 SP-15 分支） |

> 版本差异备注（如实）：GITS 侧 `SP-15.json` 描述符为 `version=1.1.0-p20`、`status=VALIDATION`、`owner=公司金融产品管理部`；KERT 侧未跟踪 `SP-15.md` 为 `version=2.0.0-candidate`、`status=CANDIDATE`。二者版本号不一致，属跨仓契约未对齐，如实记录。

### 6.3 SP-15 如实标注

- `skills/product-recommendation/SP-15.md`（**未跟踪，非 HEAD**）front matter：`skillId: SP-15`、`version: 2.0.0-candidate`、`implementationType: RULE_MODEL`、`humanGatePolicy: REQUIRED`、`sideEffectPolicy: PROPOSE_ONLY`、`activationContract: AC-PRODUCT-RECOMMEND-001`、`status: CANDIDATE`。
- 配套候选资产（均未跟踪、均未接运行时）：`contracts/recommendation-result.md`（输出合同）、`product-cards/README.md`（产品卡结构）、`rules/README.md`（RuleBundle 八类规则）、`activation-contracts/AC-PRODUCT-RECOMMEND-001.md`（激活合同）。
- **结论**：SP-15 为 **CANDIDATE 未实现** —— 有文档/契约资产，但**未注册进 registry()、无 `_executor()` 分支、无任何测试用例**（`tests/integration/test_skills.py` 无 SP-15；`tests/e2e/test_all_skills_execution.py` `SKILL_IDS` 12 项不含 SP-15）。

**判定：注册表本身 PRESENT_AND_CONTROLLED（12 个 skill 可注册/可执行，有测试）；但 SP-02/SP-05/SP-07 = ABSENT，SP-15 = CANDIDATE 未实现 → 属 UNCONTROLLED/缺失（详见 §9）。**

---

## 7. g) 产品知识资产与规则资产存储/发布机制（五层工作区 01_raw→03_core→04_serve）

### 7.1 五层工作区（平台机制已实现，HEAD）

- 目录定义：`src/dkws/domain/workspace.py` `TOP_LEVEL_DIRS = ("01_raw","02_work","03_core","04_serve","90_control")`（第 14 行）。
- 权威源：`03_core` 为唯一权威源（`README.md`、未跟踪 `skills/product-recommendation/rules/README.md` 亦声明「规则资产落 DKWS 五层工作区（01_raw → 03_core → 04_serve），03_core 为唯一权威源」）。

### 7.2 发布机制（`src/dkws/application/publish.py` `Publisher.publish` 第 61 行起，HEAD）

1. 收集 APPROVED 候选（+证据闭包）→ 2. G3 门禁 → 3-4. 临时版本目录 + `RELEASE.md`（含 SHA-256 清单）→ 5. 全量重读校验 → 6. 原子提交 `03_core/<domain>/version=<ver>/` → 7. 原子更新 `03_core/<domain>/CURRENT.md` 指针（失败保留旧指针）。
- 回滚仅切换指针、不删除版本（`application/rollback.py`；`publish.py` 第 323-346 行 `_write_current`）。
- 投影：`04_serve` 投影（实体/关系/声明/片段/向量/规则/数据集/图谱），Kùzu 图为可重建投影层（`ADR.md` IMP-ADR-011）。

### 7.3 产品知识/规则资产「本身」的现状

- **机制已实现，但产品卡/规则包数据尚未填充**：未跟踪 `product-cards/README.md` 定义产品卡最小结构（Owner/版本/来源/内容哈希），`rules/README.md` 定义 RuleBundle 八类规则；这些是**结构定义**，仓库中**无已发布的产品卡实例、无规则包种子数据、无产品版本数据落库**。
- 产品卡/规则包的「权威材料 + 试点产品族」由公司金融产品 Owner 裁决（`product-cards/README.md` `OQ-02`），当前**未提供**。
- 已有真实数据资产（可作对照，非产品推荐域）：`customer_knowledge` 客户知识（`scripts/seed_customer_knowledge.py`）、`supply_chain_graph` 合成图谱演示数据。

**判定：存储/发布「机制」PRESENT_AND_CONTROLLED（五层+发布链+门禁有代码与测试）；但「产品知识资产与规则资产」本体 = ABSENT/未填充（属 SP-15 前置，CANDIDATE）。**

---

## 8. h) 健康检查 / 可观测 / 审计保留策略

### 8.1 健康检查（HEAD）

- `GET /v1/health`：OK/DEGRADED（投影缺失时 DEGRADED），并报告 runtime 配置（`server.py` 第 364-385 行）。
- `GET /api/skill/health`：已注册 skill 清单（`server.py` 第 525-533 行）。
- `GET /livez`（存活）、`GET /readyz`（就绪，含 workspace/runtime_store/job_queue 检查，503 语义）、`GET /metrics`（Prometheus 文本）—— `server.py` 第 234-362 行。

### 8.2 可观测（HEAD）

- 中间件：`ObservabilityMiddleware`（`middleware.py` 第 419-530 行）：W3C `traceparent` 贯通、`X-Request-Id` 回传、请求计数/延迟直方图、结构化访问日志。
- 指标：自研 `MetricsRegistry` 输出 Prometheus 文本（`observability.py` 第 266-393 行）；可选桥接 `prometheus_client`（第 536 行起，能力上报）。
- 追踪：`Tracer` 内置轻量实现 + 可选 OpenTelemetry（`observability.py` 第 433-527 行）。
- 结构化日志：`JsonLogFormatter`（单行 JSON）+ 日志/密钥脱敏（`observability.py` 第 149-226 行）。
- 配置项：`ObservabilityConfig`（`runtime_config.py` 第 170-197 行）。

### 8.3 审计保留策略（如实标注）

- Skill 幂等缓存：内存 + Runtime Store，TTL = **600s**（`skills.py` `IDEMPOTENCY_TTL_S = 600` 第 32 行）；Runtime Store 幂等记录默认 TTL 600s（`runtime_config.py` 第 161 行）。
- 执行结果报告缓存：TTL ≈ **10 分钟**（`server.py` 第 565 行、`application/report.py` 第 8 行；源自幂等缓存 600s）。
- 闸门审计镜像：追加 `90_control/audit/gates.jsonl`（`skills.py` `record_gate_audit` 第 689-711 行）+ 可选 Runtime Store `gate_audit` 表；**无保留期/无清理逻辑**。
- Job 状态文件：`90_control/jobs/{job_id}/STATUS.md` + `RUN_REPORT.md`（`jobs.py`，未见清理）。
- **统一审计保留策略 = 缺失**：`infrastructure/backup.py` 第 13、268 行明确「RPO/RTO 与备份频率、保留策略属 Owner 决策，本清单不预设业务默认值」；状态基线 `backup_recovery_sop: MISSING`（`DKWS_STATUS_BASELINE_CANDIDATE.yaml` 第 90-91 行）。仓库中无审计保留周期、清理/归档 SOP 定义。

**判定：健康检查 + 可观测 = PRESENT_AND_CONTROLLED（有代码与测试：`tests/integration/test_observability_endpoints.py`、`tests/unit/test_observability.py`）；审计保留策略 = UNCONTROLLED/缺失（无保留周期与清理 SOP）。**

---

## 9. GATE0 结论

**结论（单一枚举值）：PRESENT_AND_CONTROLLED。**

KERT 可执行主体（Skill 平台 + 五层工作区 + 发布/投影 + 可观测）已 PRESENT 且可取证、可运行、有测试，证据可从固定 commit `0625afbf` 复现，满足 Gate 0「证据存在且受控」的门槛。

**其限定条件（7 项 UNCONTROLLED/缺失例外，须在 Gate 0 通过条件中显式闭环）**：

| # | 项 | 判定 | 关键证据路径 |
|---|---|---|---|
| a | 项目名/仓库/Owner | PRESENT_AND_CONTROLLED | `pyproject.toml`、`README.md`、git remote `Leibniz-KERT`、HEAD `0625afbf` |
| b | Skill 执行 OpenAPI + 错误码 | **PRESENT（但契约漂移；KERT_* 未实现且未提交）** | `specs/dkws-openapi-v1.yaml`（HEAD）、`src/dkws/domain/errors.py`、`src/dkws/application/skills.py` |
| c | 同步/异步/轮询（无回调） | PRESENT_AND_CONTROLLED | `src/dkws/api/server.py`、`src/dkws/application/skills.py`、`src/dkws/application/jobs.py` |
| d | 鉴权（X-API-Key） | **PRESENT_BUT_UNCONTROLLED（演示）** | `src/dkws/api/middleware.py`、`src/dkws/infrastructure/runtime_config.py`、`DKWS_STATUS_BASELINE_CANDIDATE.yaml` |
| e | ContextPackage / EvidenceBundle / 执行轨迹 | **部分 UNCONTROLLED / EvidenceBundle ABSENT** | `docs/contracts/schemas/*.schema.json`、`specs/dkws-openapi-v1.yaml` |
| f | Skill 注册表（SP-02/05/07/15） | **注册表 PRESENT；SP-02/05/07 ABSENT，SP-15 CANDIDATE 未实现** | `src/dkws/application/skills.py`、未跟踪 `skills/product-recommendation/SP-15.md` |
| g | 产品/规则资产存储发布机制 | **机制 PRESENT；产品卡/规则包本体 ABSENT** | `src/dkws/application/publish.py`、未跟踪 `skills/product-recommendation/{product-cards,rules}/README.md` |
| h | 健康/可观测/审计保留 | **健康+可观测 PRESENT；审计保留策略 UNCONTROLLED/缺失** | `src/dkws/infrastructure/observability.py`、`src/dkws/infrastructure/backup.py` |

### 9.1 UNCONTROLLED / 缺失清单（必须闭环）

1. **鉴权演示关闭**：当前 `auth_enabled=false`、无 TLS、无限流（`DKWS_STATUS_BASELINE_CANDIDATE.yaml` 第 37-40 行）；ADR-013 仍 `CANDIDATE_AWAITING_OWNER`。→ 生产前需启用认证+TLS+限流并获 Owner 批准。
2. **SP-15 CANDIDATE 未实现**：未跟踪 `skills/product-recommendation/SP-15.md` 有 `status: CANDIDATE`、`version: 2.0.0-candidate`，但未注册、无执行器、无测试。
3. **SP-02 / SP-05 / SP-07 ABSENT**：KERT 仓库无任何资产/执行器，仅 GITS 侧 `specs/knowledge-architecture/skills/*.json` 描述符。
4. **KERT_* 失败码未落地且未提交**：`grep "KERT_" src` = 0；仅在未提交工作区 OpenAPI 与未跟踪 `SP-15.md` 中定义，HEAD 无。
5. **EvidenceBundle 运行路径未落地**：仅候选 schema + SP-15 步骤 8 设计；运行时只有 `evidenceRefs`。
6. **契约漂移**：`assemblyTrace` 类型（object vs array）、`requestId/request` 必需性、`/v1/health` 响应形状（均为 HEAD 基线内容，可复现）。
7. **审计保留策略缺失**：无保留周期/清理 SOP（`infrastructure/backup.py` 第 13/268 行明示属 Owner 决策，未预设）。

### 9.2 结论措辞（避免复合混读）

- KERT 的**可执行主体**（Skill 平台 + 五层工作区 + 发布/投影 + 可观测）已 PRESENT 且可取证、可运行、有测试 → 满足 Gate 0「证据存在」最低门槛，故整体判定取单一值 **PRESENT_AND_CONTROLLED**。
- 但「产品推荐」业务面（SP-15 及前置 SP-02/05/07、产品卡/规则包数据、EvidenceBundle、KERT_* 失败码）目前**停留在 CANDIDATE 文档/契约层，未进入实现**；鉴权与审计保留亦属「存在但未受控」。这 7 项作为上述结论的**限定条件**列出，**不得将 SP-15 / 产品推荐链路视为已实现**。

---

## 10. 附：交付纪律自检（如实）

- 本文档状态：CANDIDATE / FROZEN=NO / IMPLEMENTED=NO。
- 所有结论均引用实际文件路径并区分「HEAD 基线」与「未提交工作区」；未落地项已如实标注 UNCONTROLLED/缺失。
- 合法性校验：本文件为 Markdown，无 JSON 需 `python3 -m json.tool` 校验（GITS 侧 SP-* 描述符为只读引用，未改写）。

### 10.1 工作区实际变更清单（`git status -s`，取证时刻）

| 工作区变更 | 归属 | WP0-2 是否造成 |
|---|---|---|
| ` M evidence/jr1/DISPATCH_E2E_SKIP.md` | 其他并行任务（JR1 E2E-skip 派工前置核验） | **否** |
| ` M skills/service-proposal/templates/ch07-product-recommendation.md` | 其他并行任务（SP-20 CH07 产品推荐章节模板改造） | **否** |
| ` M specs/dkws-openapi-v1.yaml` | 其他并行任务（SP-15 OpenAPI 增量：+SP-15 health 示例、+8 KERT_* 错误码） | **否** |
| `?? docs/governance/KERT_GATE0_EVIDENCE_PACK_CANDIDATE.md` | **WP0-2（本交付物）** | **是** |
| `?? skills/product-recommendation/`（5 文件：SP-15.md、contracts/recommendation-result.md、activation-contracts/AC-PRODUCT-RECOMMEND-001.md、product-cards/README.md、rules/README.md） | 其他并行任务（SP-15 候选资产） | **否** |

### 10.2 自检结论（修正版）

- **WP0-2 自身唯一新增的文件 = `docs/governance/KERT_GATE0_EVIDENCE_PACK_CANDIDATE.md`。**
- 工作区中另存在 **3 个既有文件被修改** 与 **1 个新目录（skills/product-recommendation/，5 文件）**，均为**其他并行任务**产物，非本任务造成；本任务未改动这些文件，也未以任何方式让它们「看起来」由本任务产生。
- 更正：**本任务不再声称「git status 确认只新增本文件」**——该表述与事实不符，已撤回。准确的取证记录是：`git status -s` 显示除本交付物外还有上述 3 个 `M` + 1 个 `??` 目录。
- 与 Gate 0 可复现性关系：本包全部可复现证据锚定 HEAD `0625afbf`；`specs/dkws-openapi-v1.yaml` 的 SP-15 增量与 `skills/product-recommendation/` 均为未提交内容，本包已显式标注「非 HEAD 基线」，因此 Gate 0 证据可从固定 commit `0625afbf` 复现，不受并行任务未提交改动影响。
