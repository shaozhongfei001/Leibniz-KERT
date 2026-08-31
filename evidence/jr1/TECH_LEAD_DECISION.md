# Tech Lead 决策记录 —— JR-1 CI 修复 PR 的 4 项卡点

- **决策日期**：2026-08-31
- **决策角色**：Tech Lead
- **关联 PR**：`fix/ci-httpx-test-dependency` → `develop`
- **关联提交**：`1ddf788`（fix(ci): declare httpx as a test dependency and run CI on develop PRs）
- **关联说明**：`evidence/jr1/PULL_REQUEST_CI_FIX.md` §5 审查要点
- **基线**：`develop` = `5e61ac0`

---

## D-1 `httpx>=0.27` 归入 `dev` extra 而非 `api` —— **认可**

**裁决**：认可现状，不做变更。

**理由**：`httpx` 的消费者全部在测试侧——`tests/e2e` 直接 import，
`tests/integration` 经 `starlette.testclient.TestClient` 间接依赖。
DKWS 运行时（`dkws.api`）自身不发起出站 HTTP 调用，因此 `httpx` 不属于
`api` extra 的运行时契约。放进 `api` 会让生产镜像携带非必要依赖，
扩大攻击面且违反最小依赖原则。

**约束**：若后续 Core 需要主动出站调用（例如回调 GITS），须将 `httpx`
**另外**加入 `api` extra，而非把测试依赖挪走——两者是不同用途，可并存。

---

## D-2 `pull_request.branches` 加入 `develop`（CI 用量上升）—— **可接受**

**裁决**：接受用量增加，`branches: [main, develop]` 保留。

**理由**：原配置 `branches: [main]` 与 AGENTS.md §4「提交 PR 到 `develop`」
的流程直接矛盾，导致**所有 feature PR 在合并前零自动验证**。这是治理缺口
而非成本优化。用无验证合并换取 CI 额度，代价远高于收益。

**补充**：workflow 已配置 `concurrency` 取消同分支旧运行，用量增幅可控。

---

## D-3 GITS 依赖型 e2e 用例「无服务时 skip」—— **列为独立任务包**

**裁决**：同意。不并入本 CI 修复 PR，另立任务包 `JR1-E2E-SKIP`，
规格见 `evidence/jr1/TASK_PACKAGE_E2E_SKIP.md`。

**理由**：这 21 个 error 的根因是**测试对外部服务的硬依赖**，
与依赖声明缺失是两个不同缺陷。`_wait_for()` 当前以 `AssertionError`
终止，属行为契约变更，需独立评审与回滚边界。混入配置修复会放大评审面，
且破坏该 PR「可独立回滚」的性质。

**边界（强制）**：
1. 改 skip 后**不得**降低有服务环境下的断言强度——联调时必须照常失败；
2. 必须能通过显式开关强制要求服务存在（防止 CI 静默全 skip 掩盖真实故障）；
3. 不改动任何业务源码。

---

## D-4 合并顺序：CI 修复 PR 最先 → PR #1 → PR #2 —— **同意**

**裁决**：按此顺序执行。

**理由**：CI 修复是后两个 PR 获得有效 check run 的前置条件。
若先合 #1/#2，它们仍在无验证状态下进入 `develop`，本次修复失去意义。

**执行序列**：

| 序 | PR | 源分支 | 前置条件 |
|---|---|---|---|
| 1 | CI 修复 | `fix/ci-httpx-test-dependency` | 本决策记录合入 |
| 2 | PR #1 | `feature/jr1-internal-contract-dual-tests` 相关 | 序 1 已合，CI 转绿 |
| 3 | PR #2 | JR-1 交付主体（含 `FAIL-JR1-04`） | 序 2 已合 |

**约束**：按 AGENTS.md §3 第 10 条，**merge 动作须 Owner 授权**，
Tech Lead 只裁决顺序，不代为合并。

---

## 非声明

- 本决策仅裁决上述 4 项，不代表 CI 已全绿（21 个需外部服务的 e2e error 未消除）。
- 本决策不代表 DKWS `PRODUCTION_READY=YES` 或 `GITS_UAT_PASS=YES`。
- 本决策不构成 Independent QA 的 `QA_PASS`。
- Tech Lead 未执行 merge，未代替 Owner 授权。
