# 方案：D-23 —— `kert_api_validation.py` 纳入 pytest 收集（**只读方案，不改码**）

```text
PLAN_ID   : M7-CLOSURE-C20-D23-ADOPTION
性质      : **方案（plan only）** —— 本文件**不改任何** 测试 / 配置 / 源码
裁决依据  : D-23（`evidence/m7-3/DECISION_SHEET_M7_CLOSURE.md`）：TL 裁定**选 ①（纳入收集）**，
            但**先出「纳入方案」（只读）**；硬线 = **不以「能收集了」为目标而降低 21 条期望的强度**，
            且**改名若引入 7 ERROR 必须被处置**
作者      : c20（契约/实现面）
DATE      : 2026-09-16
行号基准  : `tests/e2e/kert_api_validation.py` = **588 行 / sha256(16) `b101fb83d656997b`**（HEAD 时点）
            ＋ 函数名双锚（E-2）；下表凡引该文件均为此时点行号
```

## 0. 摘要（一屏）

- **目标**：让该文件里**已存在的 21 条业务期望**真正**被执行**，且**强度一字不降**。
- **形态**：**新增一个 pytest 入口文件**（legacy 脚本的判据**一行不改**），把 `run_validation()` 的结果**按 21 条逐条断言**；并把 7 个遗留 `test_*(base_url, vr)` **改名**为 `check_*`，**消灭"改名即 7 ERROR"的陷阱**。
- **预期收集数（③）**：**+22**（21 逐条 + 1 条"计数/覆盖不变量"）。
- **硬线（⑤）**：禁止聚合单断言、禁止只看 HTTP、禁止 `skip`/`xfail` 包裹、禁止放宽任一 `expect_status`、禁止 `--deselect`/`-k` 排除；**21 条逐条断言复用 legacy 的 `passed` 判据**。

## 1. 现状事实（机读，逐条回源）

| # | 事实 | 证据（本轮实测/回源） |
|---|---|---|
| F-1 | 文件名**不匹配** `python_files`（默认 `test_*.py`）⇒ **默认套件不收** | `pyproject.toml` 的 `[tool.pytest.ini_options]` 只有 `testpaths` / `addopts` / `markers`，**无** `python_files`（`:38-48`）；实测 `tests/e2e/` 收集结果不含该文件 |
| F-2 | **显式收集** ⇒ 收 **7 个** `test_*`；**实跑 ⇒ 7 ERROR**、`EXIT=1` | 实测：`pytest tests/e2e/kert_api_validation.py --collect-only -q` ⇒ 该文件 **7**；实跑 ⇒ **7 ERROR**（`base_url`/`vr` 被当夹具）、账本 `errors=7（必须 0）`、`passed=0 < 下限 7` |
| F-3 | 该文件内含 **21 条**业务期望：`health` 1 + `gates` 1 + `gates/audit` 1 + **12 skill** + job 3 + report 2 + `unknown` 1 | `SKILL_TEST_CASES` **实测 = 12**；供给态只读运行 ⇒ `endpoint_results` = **21**、`21/21 PASS` |
| F-4 | 判定强度**高于** HTTP 层：`expect_http` **且** `expect_status`（业务 `status`）**且** 结构检查 | `:388-410`（`http_ok` / `biz_ok` 双判）、`:131-135`（gates 要求 `{gateId,name,sequence}` ⊆ keys）、`:236-237`（report 的 HTML 判定） |
| F-5 | 该文件**不被任何 CI / Makefile 引用** | 全仓 `grep -rn "kert_api_validation"`（排除 `.git`/缓存）：CI/Makefile **零命中**；命中仅 `evidence/**` 文档、我 Step 2 的注释行号、及 `.pytest_cache` |
| F-6 | `tests/` 与 `tests/e2e/` **均有** `__init__.py` ⇒ 包路径 `tests.e2e.kert_api_validation` 可导入 | `ls -l` 实测；`PYTHONPATH=. .venv/bin/python -c "import tests.e2e.kert_api_validation"` ⇒ **`IMPORT_EXIT=0`**、`run_validation` 可取 |
| F-7 | CI 跑 `python -m pytest tests/e2e/ -rs`，`E2E_REQUIRE_KERT=1`，账本落盘 + **独立第二道下限断言（下限现场重算）** | `ci.yml:290-301`（命令与 env）、`:303-314`（独立断言） |
| F-8 | 该文件 21 条期望**在供给态下成立**（含 SP-20/21 `ok`、previsit `exit_policy_no_new_evidence`） | 只读运行实测 `21/21 PASS`、`VAL_EXIT=0`；未供给态 `19/21`（2 红 = outreach / meeting） |

## 2. 纳入方案

### 2.1 命名（①）—— 三选一，**推荐 B**

| 方案 | 做法 | 后果 | 结论 |
|---|---|---|---|
| **A 直接把 legacy 改名为** `test_kert_api_validation.py` | 匹配 `python_files` | **同时**把 7 个 `test_*` 收进来 ⇒ **7 ERROR**（F-2 实测）⇒ CI 立刻红 | **不单独采用**（除非与 §2.3 改名**同轮**） |
| **B 新增入口文件；legacy 文件名不动（推荐）** | 新增 `tests/e2e/test_api_validation_adoption.py` | legacy **继续不被收集**（**0 ERROR**）；21 条期望由**新入口执行**；改动面 = **新增 1 文件** | **推荐** |
| C 在 legacy 模块加 `__test__ = False` | 显式屏蔽收集 | 属**静默屏蔽**：一旦他人加 `python_files` 配置或改名，期望又回到"从未执行"且**无痕迹** | **否决**（与 D-6/D-8/E-12 的口径冲突） |

- **采纳 B**。理由：改动面最小、且**不依赖"文件名恰好不匹配"这种巧合**来维持现状。
- B **不是终态**：§2.3 的改名应作为**同一采纳轮的第二步**（或紧随一轮）落地，使"未来改名 / 加收集配置"**不再复活 7 ERROR**。

### 2.2 签名形态（②）

新增文件（**只**新增；legacy 脚本**一行不改**）：

```python
"""D-23 纳入入口：执行 tests/e2e/kert_api_validation.py 的 21 条业务期望（逐条断言）。

设计要点：
- **不改** legacy 脚本的任何判据；本文件只做「执行 + 逐条断言」。
- 逐条断言**复用** legacy 的 `EndpointResult.passed`
  （= expect_http 且 expect_status 且 结构检查），**不新增**任何"只看 HTTP 200"的弱判据。
- 防空转：静态 ID 表与实测结果**逐条一一对应**；条数不等或某条缺失即失败。
"""
from __future__ import annotations

import pytest

from .kert_api_validation import run_validation  # tests/e2e 是包（F-6 已实测可导入）

#: 21 条**稳定 ID**（动态路径用前缀匹配，见 _pick）
CASE_IDS: tuple[str, ...] = (
    "health", "gates", "gates_audit",
    "skill:SP-20", "skill:SP-21", "skill:skill-customer-previsit-report",
    "skill:bank-front-supply-chain-graph", "skill:skill-customer-outreach-script",
    "skill:skill-customer-meeting-script", "skill:bank-front-commitment-script",
    "skill:bank-front-eight-dimension", "skill:bank-front-fact-reconciliation",
    "skill:bank-front-kyc-gap-check", "skill:bank-front-product-recommendation",
    "skill:bank-front-report-assembler",
    "async_sp20", "job_status", "job_404", "report", "report_404", "unknown_skill",
)


@pytest.fixture(scope="session")
def validation_result(kert_client):
    """用**既有** session 夹具 `kert_client`（KERT 缺失 ⇒ require 语义 fail，不 skip）。"""
    return run_validation(str(kert_client.base_url))


def test_case_count_contract(validation_result):
    """防空转：结果条数 == 静态 ID 条数（防"少跑几条就变绿"）。"""
    assert len(validation_result.endpoint_results) == len(CASE_IDS)
    for case_id in CASE_IDS:                      # 每个 ID 必须恰好命中一条
        assert sum(1 for r in validation_result.endpoint_results if _matches(case_id, r)) == 1


@pytest.mark.parametrize("case_id", CASE_IDS, ids=CASE_IDS)
def test_endpoint(validation_result, case_id):
    r = _pick(validation_result, case_id)
    assert r.passed, f"{r.endpoint} → HTTP {r.status_code}；{r.error}；{r.notes}"
```

**签名选择理由**

1. 用**既有**夹具 `kert_client`（`tests/e2e/conftest.py:268-277`）⇒ 这些用例自动落入账本的 `kert_only` 组
   ⇒ **`min_passed` 自动 +22**、`max_skipped` 不变 ⇒ **任何一条被 skip 都会被下限断言抓住**（F-7）。
2. **不新造 fixture**（新造夹具正是 F-2 那 7 ERROR 的成因形态）。
3. `run_validation()` 由 **session 夹具**只跑**一次**，21 条各自成为独立用例 ⇒ 既省时，又**保留逐条归因**。
4. **动态路径的处理**（`_pick` / `_matches` 的匹配规则）：
   - `skill:*` ⇒ 端点串含 `f"/api/skill/execute ({skill_id} /"`；
   - `job_status` / `report` ⇒ 前缀 `"/v1/jobs/"` / `"/api/skill/report/"` **且**后缀 ≠ `NONEXISTENT*`；
   - `job_404` = `"/v1/jobs/NONEXISTENT-JOB"`、`report_404` = `"/api/skill/report/NONEXISTENT"`（**精确**）；
   - 其余为**精确**匹配。

### 2.3 七个遗留 `test_*(base_url, vr)` 的逐条处置（④）

**原则：改名，不改判据**（文本-only、语义中性；与 D-21 ④ 的"版本钉提为模块常量"同族）。
连带的唯一改动是 `run_validation()` 内 **7 处调用点**同步改名（`:445-467`）；**无外部引用**（F-5）⇒ 无破坏面。

| # | 现名（现签名） | 处置 | 改后 | 判据是否变动 | 依据/影响 |
|---|---|---|---|---|---|
| 1 | `test_health(base_url, vr)` | **改名** | `check_health` | **不动** | 由 `run_validation` 调用；其余同 |
| 2 | `test_gates(base_url, vr)` | **改名** | `check_gates` | **不动**（含 `{gateId,name,sequence}` 键检查 `:131-135`） | 同上 |
| 3 | `test_gate_audit(base_url, vr)` | **改名** | `check_gate_audit` | **不动** | 同上 |
| 4 | `test_job_status(base_url, vr)` | **改名** | `check_job_status` | **不动**（含 async 202 + job 200 + 404 三查） | 同上 |
| 5 | `test_report(base_url, vr)` | **改名** | `check_report` | **不动**（含 HTML 判定 `:236-237`） | 同上 |
| 6 | `test_skill_execute(base_url, vr)` | **改名** | `check_skill_execute` | **不动**（12 用例循环 + `expect_http`/`expect_status` 双判 `:384-410`） | 同上 |
| 7 | `test_unknown_skill(base_url, vr)` | **改名** | `check_unknown_skill` | **不动**（期望 404） | 同上 |

- **"保留为非收集"这一选项只在方案 B 的"仅新增文件"阶段短暂成立**：它依赖"文件名恰好不匹配"这一**巧合**，
  一旦有人改名或加 `python_files` 就复活 **7 ERROR** ⇒ 故 §2.3 的改名**必须做**，只是可与 §2.2 **同轮或分轮**。
- 不推荐的做法（本方案不予采纳）：把 7 个函数**删除**并把逻辑内联进 `run_validation` —— 改动面更大、易引入判据漂移，收益为零。

### 2.4 强度不降（⑤，硬线）

**禁止形态**（出现任一条即视为降级）：
1. 只断言 `vr.summary["failed"] == 0`（**聚合**，丢失逐条归因）；
2. 只断言 HTTP 2xx（**丢弃** `expect_status` 业务判据）；
3. 用 `xfail` / `skip` / `skipif` 包裹任一条；
4. 放宽任一 `expect_status` / `expect_http`（含把 previsit 改成 `ok`）；
5. 删除或绕过 gates 键检查 / report HTML 检查；
6. 在 CI 中用 `--deselect` / `-k` / `--ignore` 排除该文件。

**保证强度的机制**：
- 逐条断言**复用** legacy 的 `passed`（F-4）⇒ 判据集合与现状**全等**；
- `test_case_count_contract` + 账本 `min_passed`（F-7）⇒ **少跑 / 跳过必红**；
- 分工边界：`test_all_skills_execution.py` 断言 **13 技能的业务结论（含白名单）**，本方案补 **端点面**（job / report / gates / 未知技能）+ 12 技能的**第二重独立期望** ⇒ 二者互不替代，**也不得相互替代**。

## 3. 验收证据（实施轮必须给出）

1. **收集**：`python -m pytest tests/e2e/ --collect-only -q` ⇒ e2e 条数由 **15 → 37**（`adoption` 归 **22**）；
   **且 legacy 文件名不得出现在收集结果中**（证明方案 B 的"零 ERROR"）。
2. **正常态**：供给态活栈 ⇒ `python -m pytest tests/e2e/ -rs` **全绿、`EXIT=0`**；
   四目录计数按 **E-11** 报（`.venv/bin/python` + pytest 版本 + 命令原文 + 退出码），
   计数取 **`--junit-xml`**（TL 已采纳为默认口径：`-q` 的汇总行在缓冲/交错下不稳定）。
3. **变异自证（关键）**：未供给栈（空工作区）⇒ 该文件**至少 2 条红**，实测应为
   `skill-customer-outreach-script` / `skill-customer-meeting-script`（`KERT_PERMISSION_DENIED` / `ROUTE_POLICY_ABSENT`）
   ⇒ 证明**强度未降**（若此时仍全绿，即说明被写成了弱断言，**必须停下报 TL**）。
4. **反向变异（可选）**：把任一条 `expect_status` 临时写错 ⇒ 必红（证明判据真的在跑）。
5. **账本**：`E2E_LEDGER_PATH` 落盘 JSON 中 `min_passed` 应 **+22**、`violations=[]`、`skipped=0`。

## 4. 风险与回滚

| # | 风险 | 处置 |
|---|---|---|
| R-1 | `run_validation()` 会大量 `print`（噪声） | **不改** legacy；仅在断言消息里附 `notes`（保持"零判据改动"） |
| R-2 | `run_validation()` 对服务有**写**副作用（`gates/audit` POST、12 次 skill 执行、async job） | 只在 e2e（临时工作区）跑；**不得**并入 `tests/unit` / `tests/integration` |
| R-3 | 运行时长增加（12 次 skill + job 查询，`_request` 超时 120s） | session 夹具**只跑一次**；时长在实施轮实测并记录 |
| R-4 | **白名单双源**：本脚本的 `expect_status`（previsit = `exit_policy_no_new_evidence`）与 `tests/e2e/test_all_skills_execution.py` 的 `BUSINESS_OUTCOME_WHITELIST` 是**两处独立期望** | 本轮**只登记、不合并**；将来新增非 `ok` 结论时**两处必须同改**（登记为观察项） |
| R-5 | 未供给栈下该文件**会红**（正确行为） | 与 F-7 的 require 口径一致：**不得**以 skip 掩盖（这正是本方案要恢复的捕获力） |
| 回滚 | 删除新增文件即回滚（legacy 未动，§2.3 若已做则反向改名） | 无需其它处置 |

## 5. 非声明

本文件**是方案，不是实施**：**未修改**任何测试 / 配置 / 源码（`kert_api_validation.py` **只读**：未改名、未改签名、未加登记）；
不代表 **D-23 已关闭**；不代表 CI 已具备执行该文件 21 条期望的能力；
本方案**不**主张把 21 条期望降级为聚合断言或 HTTP 层断言。
`tests/e2e/kert_api_validation.py` 行号均为 **HEAD 时点（588 行 / `b101fb83d656997b`）**行号，后续改动须按 E-2 重新对齐。
