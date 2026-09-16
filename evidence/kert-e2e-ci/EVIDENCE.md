# EVIDENCE —— 任务包 `KERT-E2E-C`（CI 启动 KERT 并真跑可跑用例 + 跨服务用例显式登记）

```text
ROLE=Feature Pilot（KERT-E2E-C；未记 QA_PASS、未合并 PR、未代 Owner 授权）
REPO=/home/szf/dev/Leibniz-KERT
BRANCH=feature/PI-ARCH-L10-L13
BASELINE_AT_START=73d0e03（开工时 git status 干净，工作树仅本任务改动）
UPSTREAM_DECISION=evidence/kert-e2e-ci/TECH_LEAD_DECISION.md（D-5 采纳 c+b；D-6/D-7/D-8/D-9/D-10）
SELF_CHECK=DEV_SELF_CHECK_PASS（仅开发自检；独立 QA 方可记 QA_PASS）
FILES_CHANGED=2 改（.github/workflows/ci.yml、tests/e2e/conftest.py）+ evidence/kert-e2e-ci/** 新增
COMMIT=d90e48e（§8 的两处代码哈希对应此提交；本文件随后仅追加本提交哈希，代码文件哈希不变）
PUSHED=否（未 push、未开 PR、未合并）
```

---

## 0. 一句话结论

在 `e2e` job 中**真启动 KERT（本仓代码，dev profile + 确定性适配器，真值端口 8106）**，使本仓可跑的 **26 个用例真跑并通过**；需 GITS 的 **21 个跨服务用例显式 skip 并登记为 `F-E2E-01`**；并以**由本次收集结果推导**的下限断言 + 每轮覆盖账本**杜绝假绿**。覆盖口径：**26/47 真跑，21/47 未覆盖**（CI 绿 ≠ 跨服务链路已验证）。

---

## 1. 改动清单与边界合规

| 文件 | 改动性质 | 说明 |
|---|---|---|
| `tests/e2e/conftest.py` | 修改（唯一功能性改动） | ① `_wait_for()` 拆为「探活返回 bool」+「按策略 skip/fail」；② 新增服务维度 require（`E2E_REQUIRE_KERT/GITS/GITS_FRONTEND`，`E2E_REQUIRE_SERVICES` 向后兼容）；③ 缺失服务短窗口 fast-fail；④ 探活 session 级缓存；⑤ 覆盖账本 + 防假绿下限断言（session 钩子） |
| `.github/workflows/ci.yml` | 修改（**仅 `e2e` job 内**） | ① 新增「Start KERT（dev/确定性）」步骤（含 8106 占用预检、60s 就绪等待、不就绪即 `exit 1`）；② pytest 步骤加 `E2E_REQUIRE_KERT=1` 与账本落盘；③ 新增独立「Assert E2E coverage ledger」步骤；④ 新增账本 artifact 上传 |
| `evidence/kert-e2e-ci/WAIVER-E2E-CROSS-SERVICE.md` | 新增 | AC-8 豁免登记（`F-E2E-01` + 21 条逐项清单 + 三条失效触发条件 + 覆盖账本要求） |
| `evidence/kert-e2e-ci/evidence-runs/**` | 新增（26 个文件） | 实跑日志、账本 JSON、可复现脚本与从 `ci.yml` **逐字抽取**的步骤脚本 |
| `evidence/kert-e2e-ci/EVIDENCE.md` | 新增 | 本文件 |

**未改动（逐条核对）**：

- `src/kert/**`：0 处改动（`git status` 仅 2 个 modified 文件，均非 `src/`）。
- `tests/unit|integration|contract|recovery/**`：0 处改动。
- `tests/e2e/test_*.py`：1 处改动都没有 —— **断言语义、用例数量、用例名均未变**（改动前后均为 47 条、`git diff` 中无 `test_*.py`）。
- 其它 CI job 与 `on:` 段：未改（`git diff .github/workflows/ci.yml` 的 hunk 全部落在 `@@ -117,0 +118,12 @@` ~ `@@ -143,0 +190,64 @@`，即 `e2e` job 区间）。
- `pyproject.toml` / `pytest.ini`：未改（本方案不需要新增 marker —— skip 在夹具内按探活结果动态产生，未使用静态 `mark.skip`）。
- `gits-cbanking` 仓：任何文件都未触碰。
- `generated/`：本仓无该目录，无相关改动。

**红线自检**：

| 红线 | 结果 |
|---|---|
| 禁止 `continue-on-error` / `|| true` / 吞异常 | ✅ `e2e` job 与其所有 step 均无 `continue-on-error`（脚本化校验：`any("continue-on-error" in s) == False`）；全 diff 无 `|| true`；探活只吞 `httpx.HTTPError`（视为"尚未就绪"继续轮询），**不吞** skip/fail 判定 |
| 禁止改 `src/kert/**`、`tests/{unit,integration,contract,recovery}/**`、`tests/e2e` 断言语义 | ✅（见上） |
| 禁止引入任何跨仓凭据 | ✅ 全 diff 无 token / PAT / deploy key；`gits-cbanking` 仓未被读取或改动；未新增任何 Secret |
| 只允许改 `tests/e2e/conftest.py` 与 `ci.yml` 的 `e2e` job | ✅（evidence/** 为任务包 §4.1 明确允许的新增范围） |
| `git add` 显式指定文件、不 force push、不 `--no-verify` | ✅（提交命令见 §10；未 push） |

---

## 2. 实施中的发现与订正（先立事实）

| # | 发现 | 处置 |
|---|---|---|
| **A** | **原 `e2e` job 的汇总计数行被 `-q` 吞掉**：`pyproject.toml` 的 `addopts` 已含 `-q`，CI 又传 `-q` → `-qq` → 连 `N passed, M skipped` 都不打印（实测：无服务时日志末尾只有 ERROR 列表，无计数行）。此前该 job 的"绿"连计数都无法从日志核对 | 在 `e2e` job 的 pytest 调用中**去掉冗余 `-q`、改为 `-rs`**（保留 1 个 `-q`，新增 skip reason 短摘要）。这属于任务包 §4.1 允许的 `e2e` job 范围内改动 |
| **B** | 跨服务用例子分组与 D-5 §0.1 的「仅 GITS 17 + 三端 4」不一致：按**实测 fixture 依赖**为「仅 GITS Backend **16** + 多端/含前端 **5**」。原因：`test_gits_calls_kert_skill_execute`、`test_gits_kert_connectivity`、`test_full_insight_flow` 同时声明 `gits_client` 与 `kert_client`，归入"多端"更贴合实测 | **总数 21 与用例集合完全一致**，故不构成范围差异；已在本文件与豁免登记中显式披露（下限断言只依赖「无服务 1 + 仅 KERT 25 = 26」，不受该子分组影响） |
| **C** | 若把 require 判定写成「全局先检所有被 require 的服务」，会**牵连其它用例可独立验证的部分**：`E2E_REQUIRE_GITS=1` 且 GITS 缺失时，25 个仅 KERT 用例会被一并判错（实测确认），比改动前**降低**了可验证量 | 改为**逐用例**判定，且在**夹具解析之前**（`pytest_runtest_setup`）：只对本用例所需的服务判定。实测见 §5 第 6 组（`26 passed, 20 errors, 1 skipped`，KERT 侧仍真跑）与第 4 组（KERT 被 require 且缺失 → 需要的用例**全部 error、0 skip**） |
| **D** | 本机 8106 上运行的是**外部 dkws 检出**实例（`/home/szf/dev/deepseek_harness/data_knowledge_ws/dkws`，pid 4553）——TL §0.3 已警示对其跑 e2e 会得到 `2 failed` 假象 | **未使用、未停止、未改动**该实例。本地取证用两条路径：① 空闲端口 8199；② 用 `unshare -rn`（user+net 命名空间）获得干净的 `127.0.0.1:8106` 做**逐字步骤复现**（见 §6） |

---

## 3. AC-1 ~ AC-11 逐条证据

### AC-1 —— 跑 pytest 前 KERT dev 实例已在 `127.0.0.1:8106` 就绪；启动失败必须使 job 失败（不得继续跑）

**实现**：`ci.yml` → `e2e` job 新增步骤 `Start KERT (dev profile, deterministic adapters)`，逐字内容见 `evidence-runs/REPRO-ci-step-Start.sh`：

1. **占用预检**：`curl -fsS --max-time 2 http://127.0.0.1:8106/api/skill/health` 成功 → `::error::8106 上已有实例在监听，拒绝复用外部实例` → `exit 1`（落实 TL §0.3「不得使用机器上可能已存在的其它 8106 实例」）。
2. **启动**：`nohup env HOME=<空目录> python scripts/serve_skill_service.py --port 8106 --host 127.0.0.1 --workspace <空目录> &`（空 `HOME` 复现"无 LLM 密钥"→ 确定性适配器；空目录即可作 workspace，范式见 `scripts/run_nfr_baseline.sh:80`）。
3. **就绪等待**：最多 60 次 `curl .../api/skill/health`，成功即 `exit 0`；超时 → 打印 `::error::` + 服务日志 → `exit 1`。

**实跑证据（在干净 netns 的真实 8106 上，逐字执行上述脚本）**：

```
########## STEP: Start KERT (dev profile, deterministic adapters) ##########
KERT 就绪（第 2 秒）：GET /api/skill/health = 200
########## Start KERT (dev profile, deterministic adapters) exit=0 ##########
```

**反向证据（端口被占 → 立即失败、不继续跑）**：

```
预占实例健康检查: 200
########## STEP: Start KERT（8106 已被占用） ##########
::error::8106 上已有实例在监听，拒绝复用外部实例（须由本 job 启动本仓代码）
########## Start KERT（8106 已被占用） exit=1 ##########
```

原始日志：`evidence-runs/ci_happy.log`、`evidence-runs/ci_port-occupied.log`。
**结论**：✅ 通过（正向 + 反向均有实跑输出）。

### AC-2 —— 仅 KERT 可用时：`26 passed, 21 skipped, 0 failed, 0 error`

```
26 passed, 21 skipped in 8.52s        ← 默认策略（未设 require）
26 passed, 21 skipped in 8.47s        ← CI job 中 E2E_REQUIRE_KERT=1
```

账本（`evidence-runs/g2_kert_only-ledger.json`）：`passed=26 skipped=21 failed=0 errors=0 collected=47`。
**结论**：✅ 通过（与 AC-2 逐字一致）。

### AC-3 —— 无任何服务时：`1 passed, 46 skipped, 0 failed, 0 error`

```
1 passed, 46 skipped in 11.39s
```

账本（`evidence-runs/g1_no_service-ledger.json`）：`passed=1 skipped=46 failed=0 errors=0`。
**结论**：✅ 计数通过（逐字一致）。

> **须显式说明的交互**：该场景下 pytest 进程退出码为 **1**，但**不是**因为 46 个 error（errors=0），而是因为 D-8 的下限断言（`passed=1 < 26`）主动把退出码升级为失败：
> ```
> ✗ 下限断言失败：
>   - passed=1 < 下限 26（无服务 1 + 仅 KERT 25）——被 require 的服务可能未起来，禁止以 skip 掩盖
>   - skipped=46 > 上限 21（跨服务用例数）——存在计划外跳过
> ::error::E2E 覆盖账本下限断言失败，job 必须失败（禁止以 skip 掩盖未验证）
> ```
> 证据文件 `g1_no_service-ledger.json` 里 `pytest_exitstatus=0` 而 `violations` 非空 —— 即"pytest 自己认为成功"，是钩子把它升级为失败。**这正是 D-8 要求的防假绿行为**（AC-3 描述的是"结果计数"，AC-6 要求的是"下限断言使 job 失败"，两者在此场景下必然同时成立）。

### AC-4 —— 21 条 skip 的 reason 可读，含缺失服务名 + 探活地址

`-rs` 短摘要（`evidence-runs/ci_happy.log`，CI job 的实际输出格式）：

```
SKIPPED [1] tests/e2e/test_cross_service_health.py:21: GITS Backend 不可达 (http://127.0.0.1:8082/actuator/health)
SKIPPED [1] tests/e2e/test_cross_service_health.py:33: GITS Frontend 不可达 (http://127.0.0.1:5173)
SKIPPED [1] tests/e2e/test_gits_to_kert_integration.py:36: GITS Backend 不可达 (http://127.0.0.1:8082/actuator/health)
...
```

覆盖账本中同一 reason 逐条随用例列出（AC-7）。格式与 AC-4 的示例 `GITS Backend 不可达 (http://127.0.0.1:8082/actuator/health)` **逐字一致**。
**结论**：✅ 通过。

### AC-5 —— 服务维度 require 生效；`E2E_REQUIRE_SERVICES=1` 既有语义不变

| 场景 | 命令（KERT 状态） | 结果 | 判定 |
|---|---|---|---|
| 仅 KERT + `E2E_REQUIRE_KERT=1` | KERT 在线 | `26 passed, 21 skipped, 0 failed, 0 error`，exit 0 | ✅ require 不误伤 |
| KERT 未起 + `E2E_REQUIRE_KERT=1` | KERT 离线 | `1 passed, 17 skipped, 29 errors`，exit 1；**29 个需要 KERT 的用例全部 error、0 skip** | ✅ 必须 fail/error，禁止 skip |
| KERT 在线 + GITS 缺失 + `E2E_REQUIRE_GITS=1` | KERT 在线 | `26 passed, 1 skipped, 20 errors`，exit 1；20 个需要 GITS 的用例 error，唯一 skip 是 `test_gits_frontend_reachable`（前端**未**被 require） | ✅ 服务维度精确生效 |
| 三端全缺 + `E2E_REQUIRE_SERVICES=1` | 全离线 | `1 passed, 46 errors`，0 skip，exit 1 | ✅ 全局开关既有语义不变三端全要求 |

机械核验（对 6 份账本 JSON 逐一验证「未覆盖集合 ∩ 需要 KERT 的用例 = ∅」）：**全部为 0**。
原始日志：`g3_kert_only_require_kert.log`、`g4_kert_down_require_kert.log`、`g5_require_gits_without_gits.log`、`g6_no_service_require_all.log`。
**结论**：✅ 通过（含向后兼容）。

### AC-6 —— 防假绿下限断言生效；须提供「人为使 KERT 起不来 → job 失败」的实跑证据

**实现（双层，D-8）**：

1. **session 钩子层**（`tests/e2e/conftest.py`）：`pytest_sessionfinish` 计算账本 → 若 `errors>0 / failed>0 / passed<下限 / skipped>上限 / 有未产生结果的用例` 任一成立，且 `session.exitstatus == OK`，则置为 `TESTS_FAILED`。
2. **CI 独立步骤层**（`ci.yml` → `Assert E2E coverage ledger`）：读账本 JSON，**现场重算** `下限 = len(no_service) + len(kert_only)`、`上限 = len(gits_only) + len(multi_end)`，再断言 `errors==0 && failed==0 && passed>=下限 && skipped<=上限 && 计数自洽`；账本文件缺失也判失败。

**决定性实跑证据（KERT 未起 + `E2E_REQUIRE_KERT=1`，逐字执行 CI 的 Run / Assert 步骤脚本）**：

```
########## STEP: Run E2E tests（KERT 未起） ##########
  passed  = 1   (下限 26 = 无服务 1 + 仅 KERT 25)
  errors  = 29   (必须 0)
  ✗ 下限断言失败：
    - errors=29（必须 0）
    - passed=1 < 下限 26（无服务 1 + 仅 KERT 25）——被 require 的服务可能未起来，禁止以 skip 掩盖
::error::E2E 覆盖账本下限断言失败，job 必须失败（禁止以 skip 掩盖未验证）
1 passed, 17 skipped, 29 errors in 38.79s
########## Run E2E tests（KERT 未起） exit=1 ##########

########## STEP: Assert E2E coverage ledger ##########
E2E 覆盖账本：collected=47 passed=1 skipped=17 failed=0 errors=29
  下限 passed>=26（无服务 1 + 仅 KERT 25）
::error::E2E 覆盖账本下限断言失败：errors=29（必须 0）
::error::E2E 覆盖账本下限断言失败：passed=1 < 下限 26
########## Assert E2E coverage ledger exit=1 ##########
```

（CI 中 Assert 步骤因 Run 步骤已失败而不会执行 —— 此处为独立取证而显式执行；**两道断言各自独立判失败**。）

**下限不是魔数**（D-8 边界 2）：`min_passed = 无服务用例数 + 仅 KERT 用例数`，由 `pytest_collection_modifyitems` 的收集结果推导；用例增删即自动重算，并在账本中打印推导式 `下限 26 = 无服务 1 + 仅 KERT 25`。
原始日志：`evidence-runs/ci_kert-down.log`、`evidence-runs/g4_kert_down_require_kert.log`。
**结论**：✅ 通过。

### AC-7 —— 每轮打印覆盖账本（计数 + 未覆盖逐条清单，按文件分组，共 21 条）

见 AC-2 的账本全文（`evidence-runs/g2_kert_only.log` 与 `-ledger.json`）：`collected/passed/skipped/failed/errors` 计数 + 推导式 + `覆盖口径：26/47 真跑，21/47 未覆盖` + **21 条未覆盖清单按 7 个文件分组逐条列出** + 生效的 require 开关 + 断言结论 + 「未覆盖 ≠ 通过」声明。

账本由运行时统计生成（非人工维护）：`uncovered` 取自实际 skip 的用例，`uncovered_by_file` 由 nodeid 分组。
**结论**：✅ 通过。

### AC-8 —— 豁免登记文件存在且含 `F-E2E-01`、21 条逐项清单、三条失效触发条件、覆盖账本要求

文件：`evidence/kert-e2e-ci/WAIVER-E2E-CROSS-SERVICE.md`。自检：

| 要求 | 位置 |
|---|---|
| 缺口号 `F-E2E-01`（且已检索确认未被占用） | 头部 `RELATED_GAP` + `GAP_ID_CHECK`（全仓检索：仅本任务文档与 `ci.yml` 注释引用，无既有登记占用 → 沿用，无需顺延） |
| 21 条逐项清单（**不得**用"等"概括） | §2，7 个文件分组，编号 1–21，每条给出「用例全名 + 缺失服务」 |
| 三条失效触发条件 | §5 T1（CI 引入 GITS 编排 → 自动作废）/ T2（跨服务用例集合变化）/ T3（每轮账本越界即判 job 失败），明确"任一成立即须重新裁决" |
| 覆盖账本要求 | §6（含账本模板与 4 条硬约束） |
| 附加：不豁免范围、移除步骤、边界声明 | §4 / §8 / §7 |

**结论**：✅ 通过。

### AC-9 —— 仅按需探活：只声明 `kert_*` 的用例不得因 GITS 缺失而 skip

实测（KERT 在线、GITS 双端缺失）：`26 passed, 21 skipped`，其中 `passed` 包含全部 25 个仅 KERT 用例 + 1 个无服务用例；未覆盖集合恰好等于跨服务集合（机械核验：`未覆盖 == gits_only ∪ multi_end` 为 `True`；`未覆盖 ∩ kert_only = 0`）。
**结论**：✅ 通过。

### AC-10 —— 服务齐备环境（若可用）：47 个用例全部实跑

**本机不具备 GITS 后端（8082）与前端（5173）**：`curl` 探活均为 `000`。
**明确标注：AC-10 未验证，留待联调环境 —— 不得默认视为通过。**
（本仓 CI 亦不启动 GITS，因此该验证只能发生在具备三端的联调/UAT 环境，届时设 `E2E_REQUIRE_SERVICES=1` 即可让 21 条缺失时 fail 而非 skip。）

**结论**：⚠️ **未验证**（如实标注，不计为通过）。

### AC-11 —— `tests/{unit,integration,contract,recovery}` 与改动前一致（含 `--cov-fail-under=80` 不退化）

**方法**：在基线 worktree（`73d0e03`，改动前）与主工作树（改动后）各跑**同一条命令**（`pytest tests/unit/ tests/integration/ tests/contract/ tests/recovery/ --cov=kert --cov-fail-under=80 --cov-report=term-missing`，去掉冗余 `-q` 以便打印汇总行；其余逐字一致）：

| 项 | 改动前（worktree @73d0e03） | 改动后（主工作树） | 一致？ |
|---|---|---|---|
| 结果 | `1198 passed, 1 xfailed, 1 warning in 200.12s` | `1198 passed, 1 xfailed, 1 warning in 196.17s` | ✅ |
| 覆盖率 | `TOTAL 10044 1572 84%` / `Total coverage: 84.35%` | `TOTAL 10044 1572 84%` / `Total coverage: 84.35%` | ✅ |
| 门槛 | `Required test coverage of 80% reached` | 同 | ✅ |
| 退出码 | 0 | 0 | ✅ |

原始日志：`evidence-runs/regress_before.log`、`evidence-runs/regress_after.log`。
**结论**：✅ 通过（另：`Lint` job 的 `ruff check src/ tests/` 实测 `All checks passed!`）。

---

## 4. 改动前后对照（计数）

| 环境 | 改动前 | 改动后 |
|---|---|---|
| **无任何服务**（KERT 指向空闲端口） | `1 passed, 46 errors`（exit 1，94.90s） | `1 passed, 46 skipped, 0 failed, 0 error`（exit 1 **仅因下限断言**，11.39s） |
| **仅 KERT 可用** + 默认策略 | `26 passed, 21 errors`（exit 1，64.30s） | `26 passed, 21 skipped, 0 failed, 0 error`（**exit 0**，8.52s） |
| 仅 KERT + `E2E_REQUIRE_KERT=1` | 不适用（无此开关） | `26 passed, 21 skipped, 0 failed, 0 error`（exit 0） |
| KERT 未起 + `E2E_REQUIRE_KERT=1` | 不适用（无此开关；旧全局开关会误伤） | `1 passed, 17 skipped, **29 errors**`，**exit 1** ← 防假绿决定性场景 |

**关键变化**：`error`（掩盖真实回归的"报错"）→ `skipped`（显式的"未覆盖"）；且**未覆盖被计数、被列清单、被上限断言约束**。
**顺带的 job 时长收益**（任务包 §4.8 "缺失服务须快速失败"）：缺失服务探活窗口 30s → 3s（`E2E_PROBE_TIMEOUT`，被 require 的服务仍用 30s `E2E_HEALTH_TIMEOUT`），无服务场景 94.90s → 11.39s。
原始日志：`evidence-runs/before_no_service.log`、`before_only_kert.log`、`g1_no_service.log`、`g2_kert_only.log`。

---

## 5. 五组实跑输出（任务包 §6.1 要求）+ 第 6 组（向后兼容）与 CI 等价复现

| 组 | 场景 | 期望（任务包） | 实测 | 日志 |
|---|---|---|---|---|
| 1 | 无服务 + 默认 | `1 passed, 46 skipped, 0 failed, 0 error` | ✅ `1 passed, 46 skipped`（0 failed / 0 error；exit 1 因下限断言，见 AC-3 说明） | `g1_no_service.log` / `g1b_no_service.log` |
| 2 | 仅 KERT + 默认 | `26 passed, 21 skipped, 0 failed, 0 error` | ✅ `26 passed, 21 skipped` | `g2_kert_only.log` |
| 3 | 仅 KERT + `E2E_REQUIRE_KERT=1` | 同上（全绿，证明 require 不误伤） | ✅ `26 passed, 21 skipped`，exit 0 | `g3_kert_only_require_kert.log` |
| 4 | **KERT 未起** + `E2E_REQUIRE_KERT=1` | **失败**（AC-6） | ✅ `1 passed, 17 skipped, 29 errors`，exit 1；CI 的 Run 步骤 exit 1、Assert 步骤 exit 1 | `g4_kert_down_require_kert.log`、`ci_kert-down.log` |
| 5 | `tests/{unit,integration,contract,recovery}` 回归对照 | 与改动前一致 | ✅ `1198 passed, 1 xfailed`，coverage 84.35%（改动前同为 84.35%） | `regress_before.log` / `regress_after.log` |
| 6（补充） | 三端全缺 + `E2E_REQUIRE_SERVICES=1` | 既有语义不变（AC-5） | ✅ `1 passed, 46 errors`，0 skip，exit 1 | `g6_no_service_require_all.log` |
| 7（补充） | KERT 在线 + GITS 缺失 + `E2E_REQUIRE_GITS=1` | 服务维度精确生效 | ✅ `26 passed, 1 skipped, 20 errors`，exit 1 | `g5_require_gits_without_gits.log` |

组 2 的账本输出（**与 CI 每轮打印的内容同源同格式**，因篇幅截取首尾）：

```text
E2E 覆盖账本（下限由本次收集结果推导，见 TECH_LEAD_DECISION.md D-8）：
  collected = 47
  passed  = 26   (下限 26 = 无服务 1 + 仅 KERT 25)
  skipped = 21   (上限 21 = 跨服务 21（仅 GITS 16 + 多端/含前端 5）)
  failed  = 0   (必须 0)
  errors  = 0   (必须 0)
  覆盖口径：26/47 真跑，21/47 未覆盖
  未覆盖用例清单（按文件分组）：
    tests/e2e/test_cross_service_health.py  (3 条)
      - TestCrossServiceHealth::test_all_services_simultaneously  [Skipped: GITS Backend 不可达 (http://127.0.0.1:8082/actuator/health)]
      ...
    tests/e2e/test_scenario_5_customer_insight.py  (4 条)
      - TestCustomerInsight::test_kyc_gap_analysis  [Skipped: GITS Backend 不可达 (http://127.0.0.1:8082/actuator/health)]
  require 开关：（未设置 → 缺失服务一律 skip）
  ✓ 下限断言通过（errors=0, failed=0, passed>=下限, skipped<=上限）
  说明：本账本是「未覆盖」的显式登记，不等于「通过」；CI 绿不代表跨服务链路已验证。
```

---

## 6. CI job 的逐字本地复现（在其真值端口 8106 上）

**目的**：`e2e` job 的**真值端口是 8106**，而本机 8106 被外部 dkws 实例占用（发现 D）。为在不干扰该实例的前提下取得**端口真值**的证据，用 `unshare -rn` 建立 **user+net 命名空间**（命名空间内 `127.0.0.1:8106` 空闲），并把 `ci.yml` 中 `e2e` job 的 `run` 脚本**逐字抽取**后按 CI 顺序执行。

抽取方式：用 YAML 解析器读取 `.github/workflows/ci.yml` 的 `jobs.e2e.steps[*].run` 原样落盘为 `evidence-runs/REPRO-ci-step-{Install,Start,Run,Assert}.sh`（`bash -n` 全部 rc=0；`Install` 步骤在本机由既有 `.venv` 满足，其余三步全部实跑）。

| 模式 | Start | Run | Assert | 说明 |
|---|---|---|---|---|
| `happy`（KERT 正常启动） | exit 0（第 2 秒就绪） | exit 0（`26 passed, 21 skipped`） | exit 0 | 正向全通 |
| `kert-down`（不启动 KERT） | 未执行 | **exit 1**（`1 passed, 17 skipped, 29 errors`） | **exit 1** | 防假绿决定性证据（AC-6） |
| `port-occupied`（8106 已被占用） | **exit 1**（`::error::8106 上已有实例在监听…`） | 未执行（CI 会在上一步即停） | 未执行 | AC-1 反向证据 + §0.3 禁令落实 |

驱动脚本：`evidence-runs/REPRO-ci-job-locally.sh`（含三种模式）；本地 6 组证据的驱动脚本：`evidence-runs/REPRO-local-groups.sh`。

复现命令（本机可直接重跑）：

```bash
# 6 组证据（KERT 在线 / 离线两批）
bash evidence/kert-e2e-ci/evidence-runs/REPRO-local-groups.sh up
# 关闭自建 KERT 后
bash evidence/kert-e2e-ci/evidence-runs/REPRO-local-groups.sh down

# CI e2e job 逐字复现（netns 内真值 8106）
unshare -rn bash -c 'ip link set lo up; bash <repo>/evidence/kert-e2e-ci/evidence-runs/REPRO-ci-job-locally.sh happy'
```

---

## 7. 未验证 / 未执行事项（如实标注，不得默认视为通过）

| 项 | 状态 | 原因 / 后续 |
|---|---|---|
| **AC-10**（三端齐备时 47 个全部实跑） | ⚠️ **未验证** | 本机与 CI 均无 GITS 后端/前端。留待联调环境；届时设 `E2E_REQUIRE_SERVICES=1` 即可让缺失变 fail |
| **真实 CI 运行链接**（任务包 §6.3） | ⚠️ **未提供** | ① 本分支为 `feature/*`，`ci.yml` 的 `on:` 段只监听 `main`/`develop` 的 push 与到 `main`/`develop` 的 PR，**push 本分支不会触发任何 CI**；② 触发 CI 需向 `develop` 开 PR，而派工单明确「不合并任何 PR / STOP」且未授权变更远端状态。故以 §6 的**逐字步骤本地复现**替代，**待真实 CI 运行补充** |
| `JR1-E2E-SKIP` 的 `superseded_by=KERT-E2E-C` 标注（D-6 形式） | 未执行 | 本循环被授权的文件范围仅 `tests/e2e/conftest.py`、`ci.yml`(e2e job)、新增 `evidence/kert-e2e-ci/**`，**不含 `evidence/jr1/**`**。已在豁免登记 §9 披露，留待 TL/Owner 执行；`evidence/jr1/TASK_PACKAGE_E2E_SKIP.md` 保持原样未删 |
| `Performance Benchmarks` 计时不稳定（`22.36ms > 20.0ms`） | 未处理 | 任务包 §7 明确为非目标 |
| 独立 QA 的 `QA_PASS` | 未记 | 开发角色只能记 `DEV_SELF_CHECK_PASS`；`QA_PASS` 须独立 QA 记录 |
| `PRODUCTION_READY=YES` / `GITS_UAT_PASS=YES` | 未声称 | CI 绿 ≠ 联调通过；本豁免是"未覆盖"登记，不是"通过" |

---

## 8. 证据文件清单

`evidence/kert-e2e-ci/`

| 文件 | 内容 |
|---|---|
| `TECH_LEAD_DECISION.md` / `TASK_PACKAGE_E2E_C_KERT_ONLY.md` | 上游（TL 产出，未改动） |
| `WAIVER-E2E-CROSS-SERVICE.md` | AC-8 豁免登记 |
| `EVIDENCE.md` | 本文件 |
| `evidence-runs/REPRO-ci-step-{Install,Start,Run,Assert}.sh` | 从 `ci.yml` **逐字抽取**的 `e2e` job 步骤脚本（可 `bash -n` 校验） |
| `evidence-runs/REPRO-ci-job-locally.sh` / `REPRO-local-groups.sh` | 复现驱动（含 netns 模式） |
| `evidence-runs/{g1,g1b,g2,g3,g4,g5,g6}*-ledger.json` | 覆盖账本 JSON（机器可核验；CI 中同名文件由 `E2E_LEDGER_PATH` 落盘） |
| `evidence-runs/{g1..g6}*.log`、`before_*.log`、`ci_*.log`、`regress_*.log` | 全部实跑原始日志 |

**被改动文件哈希（本证据对应代码状态）**：

```text
93e9061549b84a819480d54e2db7961063fbb0e3e399bf0b3c4a26842fae5464  tests/e2e/conftest.py
f7a8f761a5a0903dcefe74d47047e1e90b197194e7d0ae92523542c149e9527c  .github/workflows/ci.yml
```

**账本 JSON 哈希**：

```text
dff396366ae9e37bee9dd373ba6ad22975333765a567cfb2778ab92fcc129bf0  g1_no_service-ledger.json
40f25e0fda702c2f22e4c08653d28c86a0cdb34c9feea13c27939723c3b194bf  g1b_no_service-ledger.json
9b0b553de940177af5880953323a92a83f0ddc6cfe338ff518c754e3d23e0c3d  g2_kert_only-ledger.json
00f1b8d31d1043a9b2c71429bc7bcef3cfa1eeedf22067a27b15e0c5760d941b  g3_kert_only_require_kert-ledger.json
cbebb59ac3dcce8515de0bc53593768a2ffe094db1de4ee48c5cba69697dec67  g4_kert_down_require_kert-ledger.json
6bd0ac3384343a3f2cdf630eddce1d8003cbbc2162a137a47e82ef5f56a183c6  g5_require_gits_without_gits-ledger.json
95f17014fe236a3841d96da7ad18101f0e9acbf1d47e9aa40eccdbb567a661db  g6_no_service_require_all-ledger.json
```

> 说明：`g1` 与 `g1b` 是同一场景（无服务）的两次独立取证（KERT 分别指向 8199 / 8931 两个空闲端口），用来证明结论不依赖某个具体端口号。

---

## 9. 复现步骤（供评审逐条重跑）

```bash
# 0) 环境：本仓自带 .venv（Python 3.12.8；pytest 9.1.1 与 requirements-lock.txt 锁定一致）
cd /home/szf/dev/Leibniz-KERT && git status --short          # 期望：仅本任务改动

# 1) 静态检查（对应 CI 的 Lint job）
.venv/bin/python -m ruff check src/ tests/                    # 期望：All checks passed!

# 2) 起本仓 KERT（dev + 确定性适配器；空 HOME 复现无密钥环境）
mkdir -p /tmp/ke2e/{ws,home}
env -u KERT_LLM_BASE_URL -u KERT_LLM_API_KEY -u KERT_LLM_MODEL KERT_PROFILE=dev HOME=/tmp/ke2e/home \
  nohup .venv/bin/python scripts/serve_skill_service.py --port 8199 --host 127.0.0.1 \
  --workspace /tmp/ke2e/ws > /tmp/ke2e/kert.log 2>&1 &
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8199/api/skill/health   # 期望 200

# 3) 组 2/3/5（KERT 在线）；组 1/4/6 需先 kill 该实例
bash evidence/kert-e2e-ci/evidence-runs/REPRO-local-groups.sh up
bash evidence/kert-e2e-ci/evidence-runs/REPRO-local-groups.sh down

# 4) CI e2e job 逐字复现（真值端口 8106，netns 隔离，不干扰外部 8106 实例）
unshare -rn bash -c 'ip link set lo up; bash '"$PWD"'/evidence/kert-e2e-ci/evidence-runs/REPRO-ci-job-locally.sh happy'
unshare -rn bash -c 'ip link set lo up; bash '"$PWD"'/evidence/kert-e2e-ci/evidence-runs/REPRO-ci-job-locally.sh kert-down'
unshare -rn bash -c 'ip link set lo up; bash '"$PWD"'/evidence/kert-e2e-ci/evidence-runs/REPRO-ci-job-locally.sh port-occupied'
```

**已知环境约束**：本机 8106 常驻**外部 dkws 实例**（TL §0.3 警示不得作为证据），故本地取证使用空闲端口 8199/8931，或使用 netns 取得干净的 8106。github runner 上 8106 天然空闲，CI 步骤无需该变通。

---

## 10. 提交与交接

```bash
git add tests/e2e/conftest.py .github/workflows/ci.yml \
        evidence/kert-e2e-ci/EVIDENCE.md \
        evidence/kert-e2e-ci/WAIVER-E2E-CROSS-SERVICE.md \
        evidence/kert-e2e-ci/evidence-runs
git commit -m "fix(e2e-ci): start KERT in CI, run 26 cases, skip+register 21 cross-service

- ci.yml(e2e job): start KERT (dev profile, deterministic) with 8106 pre-check and
  readiness gate; run pytest with E2E_REQUIRE_KERT=1; add independent coverage-ledger
  assertion step; upload ledger artifact
- conftest.py: split probe from skip/fail policy; per-service require switches
  (E2E_REQUIRE_KERT/GITS/GITS_FRONTEND; E2E_REQUIRE_SERVICES kept backward-compatible);
  per-test require gate before fixture resolution; fast-fail probe; session cache;
  coverage ledger + anti-fake-green lower-bound assertion derived from collection
- evidence/kert-e2e-ci: EVIDENCE.md (AC-1..AC-11) + WAIVER (F-E2E-01, 21 items)
- coverage: 26/47 really run, 21/47 registered as uncovered"
# 未 push、未开 PR、未 --no-verify
```

**实际提交**：`d90e48e`（`feature/PI-ARCH-L10-L13`，本地领先 `origin` 1 个提交，**未 push**）。后续仅追加本文件里的 `COMMIT=` 一行，`tests/e2e/conftest.py` 与 `.github/workflows/ci.yml` 的哈希在 `d90e48e` 之后未再变动。

**交接说明**：

1. 本循环只记 `DEV_SELF_CHECK_PASS`；**未**记 `QA_PASS`，**未**合并/开启任何 PR，**未**代 Owner 授权。
2. 建议独立 QA 复核重点：① 在干净环境重跑 §6 的 `kert-down` 模式（这是防假绿的全部要害）；② 逐条比对账本 `uncovered` 与豁免登记 §2 的 21 条；③ 确认 `ci.yml` 的 `on:` 段与其它 job 的 `git diff` 为空。
3. 需要外部动作的事项（本循环无权执行）：向 `develop` 开 PR 以取得**真实 CI 运行链接**；在 `evidence/jr1/TASK_PACKAGE_E2E_SKIP.md` 标注 `superseded_by=KERT-E2E-C`。
