# 任务包 `KERT-E2E-C` —— CI 启动 KERT 并真跑可跑用例 + 跨服务用例显式登记

- **来源决策**：`evidence/kert-e2e-ci/TECH_LEAD_DECISION.md` → **D-5（采纳 c+b）**，并含 **D-6** 对 `JR1-E2E-SKIP` 的三处差异决议
- **批准角色**：Tech Lead（2026-09-14）
- **状态**：`ready_for_dev`（待 Feature Pilot 领取）
- **建议分支**：`fix/e2e-ci-kert-only-and-cross-service-waiver`（从 `feature/PI-ARCH-L10-L13` 拉取，基线 `2de820f`）
- **取代关系**：`evidence/jr1/TASK_PACKAGE_E2E_SKIP.md`（`JR1-E2E-SKIP`）→ `superseded_by=KERT-E2E-C`（该文件**保留不删**，仅状态标注）
- **前置条件**：无（不依赖任何跨仓凭据）
- **不算 JR-1 交付范围**，独立评审、独立回滚

---

## 1. 问题陈述

`.github/workflows/ci.yml` 的 `e2e` job（L119–143）运行 `pytest tests/e2e/ -q`，但**未启动任何服务**；而 `tests/e2e/conftest.py` 的三个 session 级 fixture 直接探活外部服务：

| fixture | 探活地址（默认） | 环境变量 |
|---|---|---|
| `kert_ready` | `http://127.0.0.1:8106/api/skill/health` | `KERT_BASE_URL` |
| `gits_ready` | `http://127.0.0.1:8082/actuator/health` | `GITS_BASE_URL` |
| `gits_frontend_ready` | `http://127.0.0.1:5173` | `GITS_FRONTEND_URL` |

`_wait_for()` 在不可达时抛 `AssertionError` → 用例报 **error（非 failed）**，掩盖真实回归。

**实测基线（47 个用例的直接服务依赖，`item.fixturenames`）**：

| 分组 | 用例数 | 三端全缺时 | 仅 KERT 可用时 |
|---|---|---|---|
| 无服务 | 1 | passed | passed |
| 仅 KERT | 25 | error | passed |
| 仅 GITS | 17 | error | error |
| 三端 | 4 | error | error |
| **合计** | **47** | **1 passed, 46 errors** | **26 passed, 21 errors** |

**本任务包要解决的**：让"本仓本可跑的 26 个用例"在 CI 中**真跑**，并让剩余 21 个跨服务用例**显式 skip + 有登记**，同时**杜绝假绿**。

---

## 2. 目标

1. `e2e` job 在 CI 中启动 **KERT（dev profile、确定性适配器）**，使 26 个本仓用例真跑并通过。
2. 21 个跨服务用例在 CI 中**显式 skip**（可读 reason），并登记为缺口 `F-E2E-01`。
3. 建立**防假绿下限断言**：KERT 未起来时 job **必须失败**，而非"全 skip 后变绿"。
4. 每轮 CI 打印**覆盖账本**，使"未覆盖"显式可见。

---

## 3. 验收标准

| # | 标准 |
|---|---|
| **AC-1** | `e2e` job 在跑 pytest 之前，KERT dev 实例已在 `127.0.0.1:8106` 就绪（`GET /api/skill/health` = 200）；**启动失败必须使 job 失败**（不得继续跑） |
| **AC-2** | 仅 KERT 可用时：`pytest tests/e2e` 结果 = **`26 passed, 21 skipped, 0 failed, 0 error`** |
| **AC-3** | 无任何服务时：结果 = **`1 passed, 46 skipped, 0 failed, 0 error`** |
| **AC-4** | 21 条 skip 的 reason 可读，含**缺失服务名 + 探活地址**，例：`GITS Backend 不可达 (http://127.0.0.1:8082/actuator/health)` |
| **AC-5** | **服务维度 require 生效**（D-7）：`E2E_REQUIRE_KERT=1` 且 KERT 不可达 → **必须 fail/error，禁止 skip**；`E2E_REQUIRE_SERVICES=1` **既有语义不变**（三端全要求） |
| **AC-6** | **防假绿下限断言生效**（D-8）：job 中断言 `errors == 0 且 failed == 0 且 passed >= 26`；**须提供"人为使 KERT 起不来 → job 失败"的实跑证据** |
| **AC-7** | 每轮 CI 打印**覆盖账本**：`passed` / `skipped` / `failed` / `errors` 计数 + **未覆盖用例逐条清单**（按文件分组，共 21 条） |
| **AC-8** | 豁免登记文件 `evidence/kert-e2e-ci/WAIVER-E2E-CROSS-SERVICE.md` 存在，且含：缺口号 `F-E2E-01`、**21 条逐项清单**（不得用"等"概括）、**三条失效触发条件**、覆盖账本要求 |
| **AC-9** | **仅按需探活**：只声明 `kert_*` 的用例**不得**因 GITS 缺失而 skip |
| **AC-10** | 服务齐备环境（若可用）：47 个用例**全部实跑**，断言强度与改动前**逐条一致**。若环境不可用，须在 `EVIDENCE.md` 显式标注「AC-10 未验证，留待联调环境」，**不得默认视为通过** |
| **AC-11** | `tests/unit`、`tests/integration`、`tests/contract`、`tests/recovery` 结果与改动前**一致**（回归对照，含覆盖率门槛 `--cov-fail-under=80` 不退化） |

---

## 4. 实施约束（强制）

1. **允许修改**：`tests/e2e/conftest.py`、`.github/workflows/ci.yml`（**仅限 `e2e` job 内**）、新增 `evidence/kert-e2e-ci/**`、marker 注册（`pyproject.toml` 的 `[tool.pytest.ini_options]` 或 `pytest.ini`）。
2. **禁止修改**：`src/kert/**`（任何业务源码）、`tests/unit|integration|contract|recovery/**`、`tests/e2e/test_*.py` 的**断言语义**、其它 CI job、workflow 的 `on:` 触发段、`gits-cbanking` 仓的**任何文件**。
3. **禁止** `continue-on-error: true`、`|| true`、吞异常或任何使"未验证"表现为"通过"的手段。
4. **禁止降低断言强度**——不得把 `assert` 改宽或删除。
5. **禁止无条件 skip**——必须基于实际探活结果。
6. **禁止引入任何跨仓凭据**（PAT / deploy key / token）。本任务包不需要它们。
7. KERT 启动**必须**为 dev profile + 确定性适配器（无 LLM 密钥），命令以决策 `§0.3` 为准：
   `KERT_PROFILE=dev python scripts/serve_skill_service.py --port 8106 --host 127.0.0.1 --workspace <可写目录>`
   —— **不得**使用机器上可能已存在的其它 8106 实例（决策 `§0.3` 已警示：dkws 检出会产出 `2 failed` 假象）。
8. 探活超时：服务缺失时须**快速失败**（单独短 timeout，不复用 30s `E2E_HEALTH_TIMEOUT`），避免 3 个 fixture 各等 30s 拖长 job。
9. `git add` **必须显式指定文件**（禁止 `git add .`）；禁止 `force push`、禁止 `--no-verify`、禁止改 `git config`。

---

## 5. 实施要点（参考，不强制细节）

- `_wait_for()` 拆为两层：「探活返回 bool」与「按策略决定 skip / fail」。
- 策略解析顺序：`E2E_REQUIRE_<SERVICE>` → `E2E_REQUIRE_SERVICES` → 默认（缺失即 skip）；多个开关取**并集**。
- 探活结果按 URL 做 **session 级缓存**，避免重复等待。
- `all_services_ready` 依赖三者，语义自然继承。
- 下限断言可放在 session 级 hook、或 job 内独立步骤；**实现方式不限，但必须让"KERT 未起来"表现为 job 失败**。
- 覆盖账本建议从 pytest 的 `-r` 汇总或 session 统计中生成，避免人工维护。

---

## 6. 证据要求

在 `evidence/kert-e2e-ci/` 下提交：

1. **`EVIDENCE.md`** —— 改动前后对照表（`passed`/`skipped`/`failed`/`error` 计数），并含以下**五组实跑输出**：

   | 组 | 场景 | 期望 |
   |---|---|---|
   | 1 | 无服务 + 默认 | `1 passed, 46 skipped, 0 failed, 0 error` |
   | 2 | 仅 KERT + 默认 | `26 passed, 21 skipped, 0 failed, 0 error` |
   | 3 | 仅 KERT + `E2E_REQUIRE_KERT=1` | 同上（全绿，证明 require 不误伤） |
   | 4 | **KERT 未起** + `E2E_REQUIRE_KERT=1` | **失败**（证明防假绿有效，对应 AC-6） |
   | 5 | `tests/{unit,integration,contract,recovery}` 回归对照 | 与改动前一致 |

2. **`WAIVER-E2E-CROSS-SERVICE.md`** —— 21 条逐项清单 + `F-E2E-01` + 三条失效触发条件。
3. **CI 运行链接** + 覆盖账本输出。
4. 若联调环境不可用 → 显式标注「AC-10 未验证」。

---

## 7. 非目标

- **不在 CI 中启动 GITS**（后端 8082 / 前端 5173）；不修复任何 GITS 侧问题；不改 `gits-cbanking` 任何文件。
- **不做 `a` / `a-lite`**（跨仓编排）—— 留待 Owner 授权跨仓凭据后**另行裁决**（决策 D-9）。
- **不改变 `tests/e2e` 的业务覆盖范围**——不得删用例、不得改断言语义。
- **不处理** `Performance Benchmarks` 的计时不稳定（`22.36ms > 20.0ms`），该问题独立。
- **不承诺** CI 全绿等同于联调通过。

---

## 8. 派工提示词（给 Feature Pilot）

```text
你是 KERT-E2E-C 的 Feature Pilot。仓 /home/szf/dev/Leibniz-KERT，
分支 feature/PI-ARCH-L10-L13（基线 HEAD 2de820f，开工先 git status 确认干净）。

先读两份文件（顺序不要颠倒）：
  1) evidence/kert-e2e-ci/TECH_LEAD_DECISION.md   —— D-5~D-10 裁决与边界
  2) evidence/kert-e2e-ci/TASK_PACKAGE_E2E_C_KERT_ONLY.md —— 本任务的 AC 与约束

只做该任务包 scope 内的事：CI 中启动 KERT（dev/确定性）→ 真跑 26 个用例 →
21 个跨服务用例显式 skip 并登记（F-E2E-01）→ 防假绿下限断言 → 每轮打印覆盖账本。

硬约束（违反即退回）：
- 禁止 continue-on-error / || true / 吞异常
- 禁止改 src/kert/**、tests/unit|integration|contract|recovery/**、tests/e2e 的断言语义
- 禁止引入任何跨仓凭据
- 只允许改 tests/e2e/conftest.py 与 .github/workflows/ci.yml 的 e2e job（不得动 on: 段与其它 job）
- git add 必须显式指定文件；不得 force push / --no-verify

完成标准：AC-1~AC-11 逐条给出证据（含 AC-6 的"KERT 起不来 → job 失败"实跑输出）。
写 evidence/kert-e2e-ci/EVIDENCE.md 后 STOP —— 不合并任何 PR、不记 QA_PASS、
不代 Owner 授权。卡住则写 BLOCKED.md，不要向人类提问。
```
