# 方案：D-6 e2e 假绿 —— CI 供给 → 断言强化（**两步走，不改码**）

```text
PLAN_ID   : M7-CLOSURE-C20-D6-E2E-ASSERTION
性质      : **方案（plan only）** —— 本文件**不改任何代码 / 配置 / 测试**
裁决依据  : D-6（`DECISION_SHEET_M7_CLOSURE.md:102`）Owner 已批**方向**，明确"两步走：
            先 CI 供给（部署工作区含声明）→ 再强化断言（区分 ok/skill_error）；本轮不改"
作者      : c20（契约/实现面）
DATE      : 2026-09-16
行号基准  : `docs/contracts` 与 `specs` 本轮未动；下方行号均为 **HEAD 时点**行号（E-2 双锚）
```

## 1. 问题（机读事实，逐条回源）

| # | 事实 | 证据（文件:行号） |
|---|---|---|
| F-1 | `/api/skill/execute` 对**一切业务错误**返回 **HTTP 200**，**只有** `UNKNOWN_SKILL` 是 404 | `src/kert/api/server.py:667-671`（`unknown = result.status == "skill_error" and any(e.get("code") == "UNKNOWN_SKILL" ...)`；`status_code=404 if unknown else 200`） |
| F-2 | e2e 只断言"状态码 ∈ {200,201,202} + 存在某基本字段"，**不区分为 `ok` 还是 `skill_error`** | `tests/e2e/test_all_skills_execution.py:64-74`（`:66` 状态码集合；`:72` `"skillId" in body or "status" in body or "jobId" in body`） |
| F-3 | CI 的 e2e job 用**空临时目录**作工作区起服务，**不执行控制面供给** | `.github/workflows/ci.yml:170-175`（`mkdir -p "$RUNNER_TEMP/kert-ws"`；注释 `:171` 明写"空目录即可作 workspace，无需 `kert init`"）；启动命令 `:172-175` |
| F-4 | 同 job 的"技能就绪断言"**只查技能包**（`/api/skill/health` 的 7 个 `bank-front-*`），**不查控制面声明**是否已供给 | `.github/workflows/ci.yml:188-219`（`:200-208` 期望列表；端点 `:209`） |
| F-5 | 生产/部署编排是**反向**的：`provision --init` 先跑，`api`/`worker` 以 `service_completed_successfully` 为前置 | `deploy/docker-compose.yml:28-52`（provision 服务与 `--init`）、`:74-77`（`depends_on: provision` + 注释"未供给的服务起来也是'三技能全拒绝'的空壳"）、`:144-151`（worker 同） |
| F-6 | 严格 fail-closed 下，**未供给**的工作区会让三个 customer-engagement 技能（outreach / meeting / previsit）**全部拒绝** ⇒ 走 F-1 的 200 路径 | `deploy/docker-compose.yml:24-27`（注释）；计划门禁见 `src/kert/application/skills.py` 的 `_route_plan` 调用点（outreach/meeting/previsit） |

**推论（这就是"假绿"的完整链路）**：
`CI 空工作区`（F-3）→ `三技能计划门禁拒绝`（F-6）→ `skill_error` 但 **HTTP 200**（F-1）
→ `e2e 只看状态码与字段存在`（F-2）⇒ **CI 全绿，而技能实际不可用**。

> 归因说明：F-1 是**实现如实**（合同早已如实声明 404 仅 `UNKNOWN_SKILL`，见
> `specs/kert-openapi-v1.yaml` 的 `SkillExecuteErrorResponse` 与其"修正记录"），
> **不是缺陷**；缺陷在 **F-2 的断言强度**与 **F-3 的供给缺口**这一对组合。

## 2. 两步方案

### Step 1（先做）：CI 供给 —— 让部署工作区**含控制面声明**

**目标**：e2e job 的工作区与 `deploy/` 编排口径一致（F-5），使三技能**真正走到 ok 路径**；
并让"未供给"在**数秒内显式失败**，而不是被 200 掩盖。

**改动点（择一，推荐 ①）**

| 方案 | 内容 | 取舍 |
|---|---|---|
| ① **在 e2e job 内显式供给**（推荐） | 在 `.github/workflows/ci.yml` 的 `Start KERT` **之前**插一步：`python -m kert.cli.main provision --init -w "$RUNNER_TEMP/kert-ws" -s "${{ github.workspace }}/examples/bank-front-knowledge-maps"`（CLI 形态以 `deploy/docker-compose.yml:39-47` 的 `kert provision -w ... -s ... --init` 为准，实施时以 `--help` 实测校准） | 改动最小、与既有 `serve_skill_service.py` 直启方式兼容；**须实测** CLI 子命令名与参数拼写 |
| ② **改用 compose 起栈** | e2e job 改为 `docker compose up`（等价于 `make verify-e2e-local` 的 prod 路径） | 与 B-2（CI 从未跑 prod-profile 路径）合并解决，但**改动面大**、与本轮"不改码"冲突；建议**另立** |

**同轮必须补的"供给就绪断言"**（与 F-4 的既有断言并列，**同样 fail-fast**）：

- 断言部署工作区**确含声明文件**（`90_control/schema/knowledge_sources.json` 等，类别口径见 D-5）；
  实现形态二选一：
  - (a) 在 `Assert KERT skill readiness` 步**之后**加一步：对工作区做文件存在性检查（需能访问 `$RUNNER_TEMP/kert-ws`）；**或**
  - (b) 用**端点**间接断言（更贴近"用户可见"）：调 `/v1/routing/plan`（或三技能之一）并以**可区分的业务结论**判定，
    即**提前引入 Step 2 的判据**。
- **判据不得是"请求成功（HTTP 200）"** —— 那正是 F-2 的病灶。

**Step 1 的验收证据（实施时必须给出）**
1. 供给后 `kert provision` 的**原始输出**（新建/覆盖/未变 计数，按 D-5 的**成对口径**书写）；
2. e2e 三技能响应体**逐条**打印 `status` 与 `errors` 字段值（证明它们**真的**是 `ok` / `[]`）；
3. **变异自证**：把工作区还原为空目录 ⇒ 供给就绪断言**必须 FAIL**（否则该断言无捕获力）。

### Step 2（后做）：断言强化 —— 让 e2e **能区分 `ok` / `skill_error`**

**目标**：把 `tests/e2e/test_all_skills_execution.py:64-74` 的断言从"传输层成功"升级为"**业务层成功**"。

**改动点**

| 位置 | 现状 | 强化后 |
|---|---|---|
| `:66` | `assert resp.status_code in (200, 201, 202)` | 保留（传输层仍需 2xx） |
| `:72` | `assert "skillId" in body or "status" in body or "jobId" in body` | **改为显式判定同步成功**：`assert body.get("status") == "ok"`，且 `assert not body.get("errors")`；对 `status == "skill_error"` 的情形，断言消息须**回显 `errors[0].code`**（便于定位拒绝原因） |
| 异步分支（`202` + `jobId`） | 仅断言键存在 | 须**轮询 `GET /v1/jobs/{jobId}`** 直到终态，并断言 `data.status == "COMPLETED"` 且 `data.skill_result.status == "ok"`（**不得**以"提交成功"当作"执行成功"） |

**Step 2 的验收证据（实施时必须给出）**
1. **正常态**：强化后全量 e2e **绿**，并附"三技能 `status=ok`"的响应体摘录；
2. **变异自证（关键）**：把 Step 1 的供给**撤销**（工作区还原为空）⇒ 强化后的 e2e **必须 FAIL**，
   且失败信息中出现 `skill_error` + 具名 `code`（这正是当前 e2e **抓不到**的东西）；
3. **反向变异**：把实现临时改成"业务错误返回非 2xx" ⇒ 同一用例**必须仍 FAIL**（证明它不依赖某个特定状态码口径）。

## 3. 顺序理由（为什么**不能**先做 Step 2）

先强化断言、后补供给 ⇒ **CI 永久红**（F-3 的空工作区使三技能必然 `skill_error`），
于是红会被当成"噪声"而**再被削弱回去** —— 那正是 D-10 明令禁止的"把 flake 洗成通过"的同族错误。
⇒ **供给是前置条件，断言是验收强度**；顺序不可交换。

## 4. 风险与回滚

| # | 风险 | 处置 / 回滚 |
|---|---|---|
| R-1 | 供给 CLI 形态与文档不符（`kert provision` 子命令/参数拼写） | 实施时以 `kert provision --help` **实测**校准；不改 CLI 实现 |
| R-2 | 供给使**其它** e2e 用例的红绿集合变化（技能从"拒绝"变"真跑"，可能暴露真实缺陷） | 这属**预期收益**：先按"**红集变化必须逐条归因**"处理；归因不了即**停下报 TL** |
| R-3 | Step 2 使 e2e 依赖确定性适配器的**内容质量** | 本方案只断言 `status=ok` + `errors` 空，**不断言内容质量**（D-2 明确"模型输出内容质量未验证"） |
| R-4 | 改动 `.github/workflows/ci.yml` 属流水线治理 | 与 **B-2**（CI 是否接入 prod-profile 路径）同域；本方案**只**提出，不代决 |
| 回滚 | 两步各自独立可回滚 | Step 2 回滚 = 恢复 `:72` 的弱断言（**不建议**，会退回假绿）；Step 1 回滚 = 移除供给步（会使 Step 2 变红） |

## 5. 非声明

本文件**是方案，不是实施**：**未修改** `.github/workflows/**`、`tests/e2e/**`、`deploy/**`、
`src/**`、`specs/**`、`docs/contracts/**`；不代表 CI 已具备区分 `ok`/`skill_error` 的能力；
不代表 D-6 已关闭；不代表任何生产就绪或 UAT 结论。
`tests/e2e/test_all_skills_execution.py` 与 `.github/workflows/ci.yml` 的行号均为 **HEAD 时点**行号，
后续若被改动须按 E-2 重新对齐。

## 6. Step 1 交付记录（实施回填；2026-09-16）

> 按 **E-3**（交付记录必须落产物、不只落消息）回填。**Step 2 仍未做**（等放行）。

### 6.1 改动文件与指纹

| 文件 | numstat | sha256(16)（工作区 = 入库，E-5） |
|---|---|---|
| `.github/workflows/ci.yml` | `69 0` | `d6f9b979e3eb8a73` |

- 入库提交：**`1a772c8`**。
- 插入位置：job **`e2e`**，`Start KERT` **之前** —— 供给步 + 就绪断言步。
  **有意偏离**本方案 Step 1 的"放在 skill readiness 之后"：fail-fast，供给失败即**不启动服务**；已向 TL 披露并获接受。
- CLI 形态经 `--help` + `src/kert/cli/main.py:101-113` 实测标定，与 `deploy/docker-compose.yml:39-47` 同口径。

### 6.2 变异自证（三例；用 ci.yml 里**逐字的 `run` 文本**执行）

| 例 | 工作区 | 结果 | 退出码 |
|---|---|---|---|
| (a) 已供给 | 供给后（源含 activations） | `✓ 控制面供给就绪：8 份声明逐份存在且内容 sha256 一致` | **0** |
| (b) **撤销供给** | 空目录 | `::error::控制面供给不完整：缺少 [8 项]` | **1** ⇒ 断言有捕获力 |
| (c) 源缺在途件 | 源副本删 `schema/activations/` | `✓ 控制面供给就绪：6 份…` | **0** ⇒ 不假红 |

### 6.3 before / after 行为对照

- **before**：空 `$RUNNER_TEMP/kert-ws` 起服务 ⇒ 三技能计划门禁拒绝 ⇒ `skill_error` 但 **HTTP 200**
  ⇒ 既有 e2e 只断言状态码集合 ⇒ **全绿而技能不可用**（假绿）。
- **after**：供给先行 + 就绪断言（**判据非 HTTP 200**）⇒ 未供给即**显式红**，不再假绿。
  ⚠ **Step 2 未做** ⇒ e2e 仍不能区分 `ok`/`skill_error`（本步只关闭"供给缺口"这一半）。

### 6.4 一处自查（已升格 **E-12**）：防空转下限必须锚「入库态」

初版把下限写成 `8`；而 `schema/activations/AC-*.json`（2 份）是**第三方在途、未入库**
⇒ 缺它们时本 job 会**假红**。已改为 **下限 = 入库核心 `6`**
（`git ls-files` 实测：tracked 8 项 = 3 地图 + route_policy + ontology_reference + knowledge_sources + `README.md` + `.kert_workspace`；**声明核心 6 份**）。
口径：**源侧声明什么就要求供给什么（含 sha256 一致），但阈值本身只取入库态**。第 (c) 例即该修复的回归。

### 6.5 版本覆盖（E-11）

`ci.yml:22` 的 CI 侧 python = **`3.11`**；本机**只有** `/usr/bin/python3.10`
（`python3.11` / `python3.12` 系统解释器**均不存在**）⇒ **3.11 无法本地实跑**。
实测：**3.10.12**（`bash` 跑 `run` 文本）与 **3.12.8**（`.venv/bin/python` 跑从 ci.yml 逐字抽出的脚本体）
**均通过**（已供给 `EXIT=0`；未供给 `EXIT=1`）⇒ **两版本实测通过 + 3.11 仅静态判断**（脚本仅用 stdlib）。
