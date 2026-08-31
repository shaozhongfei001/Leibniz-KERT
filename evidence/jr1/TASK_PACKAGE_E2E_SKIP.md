# 任务包 `JR1-E2E-SKIP` —— 外部服务缺失时 E2E 用例可控跳过

- **来源决策**：`evidence/jr1/TECH_LEAD_DECISION.md` → D-3
- **批准角色**：Tech Lead（2026-08-31）
- **状态**：`ready_for_dev`（待 Feature Pilot 领取）
- **建议分支**：`fix/e2e-skip-when-services-absent`（从 `develop` 拉取）
- **前置条件**：CI 修复 PR（`fix/ci-httpx-test-dependency`）已合入 `develop`
- **不属于 JR-1 交付范围**，独立评审、独立回滚

---

## 1. 问题陈述

`tests/e2e/conftest.py` 的 `_wait_for()` 在服务不可达时抛
`AssertionError("服务未就绪: ...")`，且被 3 个 session 级 fixture 使用：

| fixture | 探活地址（默认） | 环境变量 |
|---|---|---|
| `kert_ready` | `http://127.0.0.1:8106/api/skill/health` | `KERT_BASE_URL` |
| `gits_ready` | `http://127.0.0.1:8082/actuator/health` | `GITS_BASE_URL` |
| `gits_frontend_ready` | `http://127.0.0.1:5173` | `GITS_FRONTEND_URL` |

**后果**：任何无外部服务的环境（含 CI）中，`tests/e2e` 下 34 个用例
全部报 `error`（非 `failed`），噪声掩盖真实回归。当前实测 21 个 error
即由 `gits_ready` 触发（`Connection refused`）。

**受影响文件**（8 个，均依赖 `kert_ready`，其中 7 个另需 GITS）：

| 文件 | 用例数 | 依赖 |
|---|---|---|
| `test_cross_service_health.py` | 4 | KERT + GITS + Frontend |
| `test_gits_to_kert_integration.py` | 5 | KERT + GITS |
| `test_scenario_1_continuous_operation.py` | 5 | KERT + GITS |
| `test_scenario_2_previsit_report.py` | 3 | KERT + GITS |
| `test_scenario_3_service_proposal.py` | 4 | KERT + GITS |
| `test_scenario_4_knowledge_graph.py` | 5 | KERT + GITS |
| `test_scenario_5_customer_insight.py` | 5 | KERT + GITS |
| `test_all_skills_execution.py` | 3 | KERT |

## 2. 目标

在**外部服务缺失**时让相关用例 `skip` 而非 `error`，同时**不削弱**
有服务环境下的验证强度。

## 3. 验收标准

| # | 标准 |
|---|---|
| AC-1 | 无任何外部服务时，`pytest tests/e2e` 结果为 `34 skipped`，**0 error / 0 failed** |
| AC-2 | skip 原因可读，含缺失服务名与探活地址，例如 `GITS Backend 不可达 (http://127.0.0.1:8082/actuator/health)` |
| AC-3 | 设 `E2E_REQUIRE_SERVICES=1` 时，服务缺失**必须** error/fail，禁止 skip |
| AC-4 | 服务齐备时，34 个用例全部实跑，断言强度与改动前**逐条一致** |
| AC-5 | 仅按需探活：只用 `kert_*` 的用例不得因 GITS 缺失而 skip |
| AC-6 | `tests/integration`、`tests/unit` 结果不受影响（回归对照） |
| AC-7 | 首次探活失败后缓存结果，同一 session 不重复等待整个 timeout |

## 4. 实施约束（强制）

1. **只改 `tests/e2e/conftest.py`**；如需标记，可加 `pytest.ini` marker 注册。
2. **禁止改动任何业务源码**（`src/dkws/**`）。
3. **禁止降低断言强度**——不得把 `assert` 改宽或删除。
4. **禁止无条件 skip**——必须基于实际探活结果。
5. CI 默认不设 `E2E_REQUIRE_SERVICES`，联调/UAT 环境必须显式设为 `1`。
6. 探活超时在服务缺失时应快速失败（建议单独的短 timeout，不复用 30s
   `E2E_HEALTH_TIMEOUT`），避免 CI 因 3 个 fixture 各等 30s 而拖长。

## 5. 实施要点（参考，不强制实现细节）

- `_wait_for()` 拆为「探活返回 bool」与「按策略决定 skip/fail」两层。
- 三个 `*_ready` fixture 在探活失败时调用 `pytest.skip(reason)`；
  当 `E2E_REQUIRE_SERVICES=1` 时改为 `pytest.fail(reason)` 或维持 `AssertionError`。
- 探活结果按 URL 缓存（session 级），满足 AC-7。
- `all_services_ready` 依赖三者，任一缺失即整体 skip，语义自然继承。

## 6. 证据要求

在 `evidence/jr1-e2e-skip/` 下提交：

1. `EVIDENCE.md` —— 改动前后对照表（error/failed/skipped/passed 计数）
2. 三组实跑输出：
   - 无服务 + 默认 → 期望 `34 skipped`
   - 无服务 + `E2E_REQUIRE_SERVICES=1` → 期望 error/fail
   - `tests/integration` 回归对照 → 与改动前一致
3. 若服务齐备环境可用，补 AC-4 的实跑证据；不可用则在 `EVIDENCE.md`
   显式标注「AC-4 未验证，留待联调环境」，**不得默认视为通过**。

## 7. 非目标

- 不在 CI 中启动 GITS Backend 或 KERT 服务。
- 不修复任何 GITS 侧问题（AGENTS.md §3 第 1 条：不得修改 GITS 仓库）。
- 不改变 `tests/e2e` 的业务覆盖范围。
- 不承诺 CI 全绿等同于联调通过。
