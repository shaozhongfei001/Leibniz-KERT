# Feature Pilot 派工提示词 —— `JR1-E2E-SKIP`

- **签发角色**：Tech Lead
- **签发日期**：2026-08-31
- **任务包规格**：`evidence/jr1/TASK_PACKAGE_E2E_SKIP.md`
- **来源决策**：`evidence/jr1/TECH_LEAD_DECISION.md` → D-3
- **派工时机（Owner 决定）**：**等 CI 修复 PR #4 合入 `develop` 后再派**
- **当前状态**：`blocked_by_pr4`（PR #4 因既存红灯暂缓，见 `evidence/jr1/FAILURES.md` FAIL-JR1-05）

---

## 一、派工提示词（复制以下整段发给 Feature Pilot）

```text
你是 Leibniz-KERT / DKWS 项目的 Feature Pilot。本次只做任务包 JR1-E2E-SKIP，
完成后 STOP，不做任何其他工作。

开场（改任何文件前静默执行）：
1. git status --short && git branch --show-current && git rev-parse HEAD
2. 读 AGENTS.md（强制 Rules 全部适用，特别是第 1、7、9、10 条）
3. 读 evidence/jr1/TASK_PACKAGE_E2E_SKIP.md（本次任务的唯一规格，7 条 AC + 6 条强制约束）
4. 读 evidence/jr1/TECH_LEAD_DECISION.md 的 D-3（裁决理由与边界）
5. 读 evidence/jr1/FAILURES.md 的 FAIL-JR1-05 F-3（CI 实证：失败不止 GITS）
6. 确认 develop 已包含 PR #4（pyproject.toml 的 dev extra 含 httpx>=0.27）。
   若不包含，STOP 并报告前置未满足——缺 httpx 时 e2e 在收集阶段即失败，拿不到有效对照证据。

分支：从 develop 拉取 fix/e2e-skip-when-services-absent

任务：让 tests/e2e 在外部服务缺失时 skip 而非 error，且不削弱有服务环境下的验证强度。

关键事实（勿重复调查）：
- tests/e2e/conftest.py 的 _wait_for() 在不可达时抛 AssertionError，被 3 个 session 级
  fixture 使用：kert_ready(:8106/api/skill/health)、gits_ready(:8082/actuator/health)、
  gits_frontend_ready(:5173)。基址均可用环境变量覆盖（KERT_BASE_URL/GITS_BASE_URL/
  GITS_FRONTEND_URL）。
- tests/e2e 下共 34 个用例，分布在 8 个文件，全部依赖 kert_ready，其中 7 个另需 GITS。
- CI 日志已证实 :8106 与 :8082 同时 Connection refused。因此必须覆盖全部 3 个 fixture，
  只修 gits_ready 不满足验收。

必须满足的验收标准（逐条自检，写进证据）：
AC-1 无任何外部服务时 pytest tests/e2e 结果为 34 skipped，0 error / 0 failed
AC-2 skip 原因含缺失服务名与探活地址
AC-3 设 E2E_REQUIRE_SERVICES=1 时服务缺失必须 error/fail，禁止 skip
AC-4 服务齐备时 34 个用例全部实跑，断言强度与改动前逐条一致
AC-5 只用 kert_* 的用例不得因 GITS 缺失而 skip
AC-6 tests/integration、tests/unit 结果不受影响
AC-7 探活结果按 URL 缓存，同一 session 不重复等待整个 timeout

强制约束（违反即退回）：
1. 只改 tests/e2e/conftest.py；如需 marker 可在 pyproject.toml 注册
2. 禁止改动 src/dkws/** 任何业务源码
3. 禁止降低断言强度——不得放宽或删除任何 assert
4. 禁止无条件 skip，必须基于实际探活结果
5. CI 默认不设 E2E_REQUIRE_SERVICES；联调/UAT 必须显式设为 1
6. 服务缺失时应快速失败，用独立短 timeout，不复用 30s 的 E2E_HEALTH_TIMEOUT
   （3 个 fixture 各等 30s 会显著拖长 CI）

不要做（超出范围）：
- 不在 CI 中启动 GITS 或 KERT 服务
- 不修改 GITS 仓库（AGENTS.md 第 1 条）
- 不修 ruff 267 个既存错误（F-1，独立任务包，非本次范围）
- 不修 tests/performance 的 3 个基准失败（F-2，独立任务包，非本次范围）
- 不改变 tests/e2e 的业务覆盖范围

证据要求（提交到 evidence/jr1-e2e-skip/EVIDENCE.md）：
1. 改动前后对照表：error / failed / skipped / passed 四项计数
2. 三组实跑输出：
   a. 无服务 + 默认 → 期望 34 skipped
   b. 无服务 + E2E_REQUIRE_SERVICES=1 → 期望 error/fail
   c. tests/integration 回归对照 → 与改动前一致
3. AC-4 若无服务齐备环境，在 EVIDENCE.md 显式标注
   「AC-4 未验证，留待联调环境」，不得默认视为通过

收工：
- 用 git add <显式文件列表> 提交，禁止 git add .
- 提交信息说明这是 D-3 派生的独立任务包
- 可 push 分支并开 PR 到 develop
- 但禁止自行 merge（AGENTS.md 第 10 条，merge 须 Owner 授权）
- 不得自签 QA_PASS，只能记录 DEV_SELF_CHECK_PASS
- 输出收工声明：完成的 AC 编号、未验证项、待 Owner 决策项
```

---

## 二、Tech Lead 备注（不发给 Feature Pilot）

### 为何强调「勿重复调查」

任务包规格与本提示词已给出 fixture 清单、端口、用例计数、文件分布。
Feature Pilot 直接进入实现即可，避免重复消耗在已完成的勘察上。

### 为何 AC-3 是硬要求

改 skip 的最大风险是**CI 静默全 skip**——那比现在的 error 更危险，
因为绿灯会掩盖真实故障。`E2E_REQUIRE_SERVICES=1` 是联调/UAT 环境的
安全阀，必须在同一 PR 内一并交付，不能留作后续。

### 为何显式列出「不要做」

FAIL-JR1-05 暴露的 F-1（ruff 267 错）与 F-2（性能基准阻断）就在同一
CI 运行里。若不划清边界，Feature Pilot 极可能顺手去修，导致 PR 范围
失控、无法独立回滚——这正是 D-3 拆包要避免的。

### 派工前置检查（Tech Lead 执行）

派工前须确认：

1. PR #4 已合入 `develop`；
2. `develop` 上 `pyproject.toml` 的 `dev` extra 含 `httpx>=0.27`；
3. F-1 / F-2 的处置已有 Owner 决策（否则 Feature Pilot 的 PR 仍拿不到
   绿灯 check run，只是红灯原因从 3 项减为 2 项）。

第 3 项不阻塞本任务包的**实现与自检**（本地可验证 AC-1/2/3/5/6/7），
但会阻塞其 PR 的绿灯。派工时须向 Feature Pilot 说明这一点，避免其
误判为自身改动导致 CI 失败。
