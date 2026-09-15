# 独立 QA 报告 —— `KERT-E2E-C` 交付验收

- **报告角色**：Independent QA（独立于实现者与 TL 核验）
- **验收对象**：`.github/workflows/ci.yml` 的 `e2e` job + `tests/e2e/conftest.py`
- **受测提交**：`c865365`（`feature/PI-ARCH-L10-L13`）；交付实现 `d90e48e` / `8131c7a`，TL 核验 `7b3d5cb`，基线 `73d0e03`
- **输入**：`INDEPENDENT_QA_PACKAGE.md` §2/§4/§6/§7、`TECH_LEAD_DECISION.md`、`TASK_PACKAGE_E2E_C_KERT_ONLY.md`(AC-1~AC-11)、`WAIVER-E2E-CROSS-SERVICE.md`、交付方 `EVIDENCE.md` 与 `evidence-runs/g1~g6` 账本
- **报告提交状态**：**未提交、未 push**（`git status` 仅显示本文件为未跟踪新增；是否入库由 Owner/TL 决定）
- **结论**：**`QA_PASS`**（附 §10.2 边界声明与 §8 自身偏差披露）

---

## 0. 独立性自查（第 0 步）

| 检查项 | 结论 |
|---|---|
| 是否参与实现 `d90e48e` / `8131c7a` | **否**（本次会话未对该仓做过任何写操作） |
| 是否参与 TL 核验 `7b3d5cb` | **否** |
| 是否以 `7b3d5cb` 的结论作为验收依据 | **否**（其自述"不是 QA_PASS"；本报告 §2 全部结论来自我自己的实跑） |
| 是否修改实现或测试 | **否**（`tests/e2e/conftest.py`、`.github/workflows/ci.yml` 的 sha256 与交付 `EVIDENCE.md` §8 逐字一致，见 §1） |
| 是否触碰 `src/kert/**` | **否**（`diff -rq` 改动前后 `src/` 零差异） |
| 是否配置跨仓凭据 | **否**（全程无 token / PAT / deploy key；`gits-cbanking` 仓未被读取或改动） |
| 是否 merge / force push / `--no-verify` | **否**；未执行任何 `git add` |
| **结构性限制（必须披露）** | 该仓 `d90e48e`/`8131c7a`/`7b3d5cb`/`c865365` 的 git author 均为**同一身份** `shaozhongfei001`。在单操作者环境下，角色分离是**流程性**的，**git 元数据无法区分执行者**。故本报告的独立性依据是**会话级隔离**（本会话动作留痕见 §9、§8），如需更强证明须由运维侧提供终端/会话审计日志 |

**独立性判定：通过**（允许出 `QA_PASS`，但受上表末行的证明力限制）。

---

## 1. 环境指纹

```text
OS            : Ubuntu 22.04.4 LTS (kernel 6.8.0-47-generic, x86_64)
Repo          : /home/szf/dev/Leibniz-KERT
Branch        : feature/PI-ARCH-L10-L13
HEAD          : c865365fdf5c3612eb90222a425a962aa33e94f6
git status    : 干净（仅本报告为未跟踪新增）
python        : 3.12.8  (/home/szf/dev/Leibniz-KERT/.venv/bin/python)
pytest        : 9.1.1 ; httpx 0.28.1 ; ruff: All checks passed!
node          : 未涉及（本任务无前端）
8106 占用情况 : 宿主机 8106 常驻外部 dkws 实例
                (/home/szf/dev/deepseek_harness/data_knowledge_ws/dkws，
                 pid 4553 → 事件后 416155；**未被复用为证据**，见 §8)
干净 8106 取得: unshare -rn + `ip link set lo up`（user+net 命名空间，与交付一致）
本机六组取证   : 干净空闲端口 8210（E2E_PROBE_TIMEOUT 默认 3s）
```

受测代码与交付声明**绑定一致**：

```text
93e9061549b84a819480d54e2db7961063fbb0e3e399bf0b3c4a26842fae5464  tests/e2e/conftest.py
f7a8f761a5a0903dcefe74d47047e1e90b197194e7d0ae92523542c149e9527c  .github/workflows/ci.yml
```

（与交付 `EVIDENCE.md` §8 声明的哈希**逐字相同** → 受测状态即交付状态。）

---

## 2. 逐 AC 判定表

### AC-1 —— 跑 pytest 前 KERT 就绪；启动失败必须使 job 失败

**命令（我自行从 `ci.yml` 抽取步骤脚本后执行，非使用交付方 REPRO 脚本）**

```bash
unshare -rn bash -c 'ip link set lo up; bash /tmp/qa-e2e-c/qa_ci_repro.sh happy'          # 正向
unshare -rn bash -c 'ip link set lo up; bash /tmp/qa-e2e-c/qa_ci_repro.sh port-occupied'  # 反向
```

**抽取脚本与交付方脚本逐字节比对**（我用 `yaml.safe_load` 独立抽取 `jobs.e2e.steps[*].run`）：

```text
Install  一致=True  QA抽取=151B  交付方=151B
Start    一致=True  QA抽取=1211B 交付方=1211B
Run      一致=True  QA抽取=205B  交付方=205B
Assert   一致=True  QA抽取=2524B 交付方=2524B
```

**原始输出（正向）**

```text
########## STEP: Start KERT (dev profile, deterministic adapters) ##########
curl: (7) Failed to connect to 127.0.0.1 port 8106 after 0 ms: 连接被拒绝
KERT 就绪（第 2 秒）：GET /api/skill/health = 200
########## Start KERT (dev profile, deterministic adapters) exit=0 ##########
```

**原始输出（反向：8106 已被占用）**

```text
预占实例健康检查: 200
########## STEP: Start KERT（8106 已被占用） ##########
::error::8106 上已有实例在监听，拒绝复用外部实例（须由本 job 启动本仓代码）
########## Start KERT（8106 已被占用） exit=1 ##########
```

**判定**：**PASS（job 逻辑，fail-closed 成立）**；**「在真实 CI 中」属性：未验证（R-2，见 §7）**。
> 备注：CI 中「Start 失败 → Run 不执行」由 GitHub Actions「step 失败即中止 job」的 runner 语义保证，属 runner 行为，本地不可证（与 R-2 的证明边界一致）。

### AC-2 —— 仅 KERT 可用：`26 passed, 21 skipped, 0 failed, 0 error`

```bash
cd /home/szf/dev/Leibniz-KERT
env KERT_PROFILE=dev KERT_BASE_URL=http://127.0.0.1:8210 E2E_LEDGER_PATH=/tmp/qa-e2e-c/g2-ledger.json \
  .venv/bin/python -m pytest tests/e2e/ -rs
```

```text
26 passed, 21 skipped in 8.90s
exit=0
  ✓ 下限断言通过（errors=0, failed=0, passed>=下限, skipped<=上限）
```

**判定**：**PASS**（与 AC-2 逐字一致）。

### AC-3 —— 无任何服务：`1 passed, 46 skipped`；退出码非 0 属设计

```text
1 passed, 46 skipped in 11.35s
exit=1
✗ 下限断言失败：
  - passed=1 < 下限 26（无服务 1 + 仅 KERT 25）——被 require 的服务可能未起来，禁止以 skip 掩盖
  - skipped=46 > 上限 21（跨服务用例数）——存在计划外跳过
::error::E2E 覆盖账本下限断言失败，job 必须失败（禁止以 skip 掩盖未验证）
```

账本 JSON：`passed=1 skipped=46 failed=0 errors=0`，**`pytest_exitstatus=0`**，`violations` 长度 2 → **证实"pytest 自认成功、被 D-8 钩子升级为失败"**的设计，而非因 error 导致退出码 1（`errors=0`）。

**判定**：**PASS**。

### AC-4 —— 21 条 skip reason 含缺失服务名 + 探活地址

```bash
grep -c 'SKIPPED' /tmp/qa-e2e-c/g2_kert_only.log                      # 21
grep 'SKIPPED' /tmp/qa-e2e-c/g2_kert_only.log \
  | grep -cE '\(http://127\.0\.0\.1:(8082|5173)'                      # 21
```

```text
SKIPPED [1] tests/e2e/test_cross_service_health.py:21: GITS Backend 不可达 (http://127.0.0.1:8082/actuator/health)
SKIPPED [1] tests/e2e/test_cross_service_health.py:33: GITS Frontend 不可达 (http://127.0.0.1:5173)
...
26 passed, 21 skipped in 8.90s
```

**判定**：**PASS**（21/21 带地址；reason 全量取值仅 2 种，与服务数一致，无空 reason / `None`）。

### AC-5 —— 服务维度 require 生效 + `E2E_REQUIRE_SERVICES` 语义不变

| 场景 | 关键 env（KERT 状态） | 实测 | 退出码 | 判定 |
|---|---|---|---|---|
| g3 仅 KERT | `E2E_REQUIRE_KERT=1`（在线） | `26 passed, 21 skipped, 0 failed, 0 error` | 0 | PASS（不误伤） |
| g4 KERT 缺失 | `E2E_REQUIRE_KERT=1`（离线） | `1 passed, 17 skipped, **29 errors**`；29 个需要 KERT 的用例 **0 skip** | 1 | PASS |
| g7 KERT 在线 | `E2E_REQUIRE_GITS_FRONTEND=1` | `26 passed, 19 skipped, **2 errors**`（error 恰为 2 个需要前端的用例） | 1 | PASS（第三维度亦生效） |
| g5 KERT 在线 | `E2E_REQUIRE_GITS=1`（GITS 缺失） | `26 passed, 1 skipped, **20 errors**`；唯一 skip 为 `test_gits_frontend_reachable`（前端未被 require） | 1 | PASS（逐用例、维度精确） |
| g6 三端全缺 | `E2E_REQUIRE_SERVICES=1` | `1 passed, **46 errors**, 0 skip` | 1 | PASS（全局开关向后兼容） |

机械核验：`g4 未覆盖集合 ∩ 需要 KERT 的用例 = 0`。

**判定**：**PASS**（D-7 三个服务维度开关**逐一实跑验证**，其中 `E2E_REQUIRE_GITS_FRONTEND` 为交付证据未覆盖、由 QA 补测）。

### AC-6 —— 防假绿下限断言生效（决定性证据）

```text
########## STEP: Run E2E tests（KERT 未起） ##########
  passed  = 1   (下限 26 = 无服务 1 + 仅 KERT 25)
  errors  = 29   (必须 0)
  ✗ 下限断言失败：
    - errors=29（必须 0）
    - passed=1 < 下限 26（无服务 1 + 仅 KERT 25）——被 require 的服务可能未起来，禁止以 skip 掩盖
::error::E2E 覆盖账本下限断言失败，job 必须失败（禁止以 skip 掩盖未验证）
1 passed, 17 skipped, 29 errors in 38.57s
########## Run E2E tests（KERT 未起） exit=1 ##########

########## STEP: Assert E2E coverage ledger ##########
E2E 覆盖账本：collected=47 passed=1 skipped=17 failed=0 errors=29
  下限 passed>=26（无服务 1 + 仅 KERT 25）
::error::E2E 覆盖账本下限断言失败：errors=29（必须 0）
::error::E2E 覆盖账本下限断言失败：passed=1 < 下限 26
########## Assert E2E coverage ledger exit=1 ##########
```

**双层防线各自独立判失败**（Run 步 exit 1 + Assert 步 exit 1）。

**判定**：**PASS**。

### AC-7 —— 每轮打印覆盖账本（计数 + 21 条未覆盖逐条清单）

账本由运行时统计生成（`uncovered` 取自实际 skip 结果，**非**静态分组）：

| 组 | 账本 `uncovered` 条数 | 静态跨服务集合 | 是否运行时派生 |
|---|---|---|---|
| g1 无服务 | **46** | 21 | 是（≠21 即证明） |
| g2 仅 KERT | 21 | 21 | 是 |
| g4 KERT 缺失 + require | **17** | 21 | 是（≠21 即证明） |
| g5 `REQUIRE_GITS` | 1 | 21 | 是 |

账本含 `collected/passed/skipped/failed/errors` + 下限推导式 + `覆盖口径：26/47 真跑，21/47 未覆盖` + **按 7 个文件分组的 21 条清单** + 生效开关 + 断言结论 + 「未覆盖 ≠ 通过」声明。

**判定**：**PASS**。

### AC-8 —— 豁免登记文件内容齐备

| 要求 | 独立核验结果 |
|---|---|
| 缺口号 `F-E2E-01` | 存在（`RELATED_GAP`）；独立全仓检索：引用者仅 `evidence/kert-e2e-ci/**` 五份文档 + `ci.yml` 注释，**无其它登记文件占用该号** → 沿用成立 |
| 21 条逐项清单、不得用"等" | §2 解析得 **21 条**；§2 正文**不含"等"字**；分文件计数 3/2/4/2/3/3/4 |
| 三条失效触发条件 | §5 T1/T2/T3，明写"任一成立即须重新裁决" |
| 覆盖账本要求 | §6（模板 + 4 条硬约束） |

**清单三方逐条一致（nodeid 级，差异 0）**：

```text
WAIVER 解析条数      = 21
g2 账本 uncovered 条数 = 21
QA 独立跨服务集合条数  = 21
WAIVER vs 账本     差异 = 0
账本   vs QA独立   差异 = 0
WAIVER vs QA独立   差异 = 0
```

**判定**：**PASS**。

### AC-9 —— 仅按需探活

g2（KERT 在线、GITS 双端缺失）：25 个仅 KERT 用例**全部 passed**，1 个无服务用例 passed；未覆盖集合**恰好等于**跨服务集合（`uncovered == 跨服务` 为 `True`）。

**判定**：**PASS**。

### AC-10 —— 服务齐备环境 47 个全跑

本机探活：`8082 → conn-fail`、`5173 → conn-fail`；仓内仅 `ci.yml` 一个 workflow 且**不启动 GITS**。

**判定**：**⚠️ 未验证（R-1）** —— 按要求显式标注，**不因其余全通过而推定其通过**。

### AC-11 —— `tests/{unit,integration,contract,recovery}` 与改动前一致

**方法**：用 `git worktree`（**保留 `.git`**；先前用 `git archive` 快照会因缺 `.git` 使 3 个 `test_release.py::TestGitAnchor*` 用例失败，属取证伪影，已识别并弃用该方法）分别检出 `73d0e03` 与 `c865365`，跑**同一条命令**：

```bash
python -m pytest tests/unit/ tests/integration/ tests/contract/ tests/recovery/ \
  --cov=kert --cov-fail-under=80 --cov-report=term-missing
```

| 项 | 改动前 `73d0e03` | 改动后 `c865365` | 一致？ |
|---|---|---|---|
| 结果 | `1198 passed, 1 xfailed, 1 warning in 200.89s` | `1198 passed, 1 xfailed, 1 warning in 197.38s` | ✅ |
| 覆盖率 | `Total coverage: 84.35%`；`TOTAL 10044 1575 84%` | `Total coverage: 84.35%`；`TOTAL 10044 1575 84%` | ✅ |
| 门槛 | `Required test coverage of 80% reached` | 同 | ✅ |
| 退出码 | 0 | 0 | ✅ |

**全文对照**：剔除耗时/路径行后 `diff` 为**空**（逐条一致）。
另：`diff -rq` 改动前后 `tests/` 除 `conftest.py` 一个文件外零差异（**47 个 `test_*.py` 与断言语义未被触碰**），`src/` 零差异。

**判定**：**PASS**。

### 2.1 附加项 X-1 / X-2 / X-3

| # | 判定 | 证据 |
|---|---|---|
| **X-1** | **PASS** | 计数行确证可见：`26 passed, 21 skipped in 8.48s`（CI 步骤用 `-rs`）。**反证**：把命令多传一个 `-q`（`addopts` 已含 `-q` → `-qq`）后，日志中 `grep -cE '[0-9]+ passed'` = **0**（计数行消失）；`-rs` 下为 1 → 交付所述"历史绿无法从日志核对"的机理成立，修复有效 |
| **X-2** | **PASS** | `E2E_REQUIRE_GITS=1` 且 GITS 缺失时 `26 passed`（25 个仅 KERT 用例**仍真跑通过**），仅 20 个需要 GITS 的用例 error → **逐用例判定，无连带误伤** |
| **X-3** | **PASS** | `Start` 步骤含 8106 占用预检 + `exit 1`（原文见 AC-1 反向输出）；netns 内实测 `::error::8106 上已有实例在监听…` → `exit=1` |

---

## 3. 独立复算表（QA 自算，不引用本包/TL 结论）

### 3.1 数据来源与推导方式

- 用**自写** pytest 插件（`/tmp/qa-e2e-c/qa_collect.py`，**位于仓外**）导出 47 个用例的 `item.fixturenames` 原始数据；
- 服务依赖**由夹具闭包自行推导**：以三个探活夹具为根（`kert_ready`→KERT / `gits_ready`→GITS / `gits_frontend_ready`→GITS 前端），沿 `name2fixturedefs.argnames` 递归展开，**不读取实现里的 `_FIXTURE_TO_SERVICES` 常量**；
- 与**行为证据**交叉校验：g2 的 `passed=26` 必须等于「无服务 + 仅 KERT」；g4 的 `errors=29` 必须等于「需要 KERT」。

```text
collected                     = 47
无服务 no_service             = 1
仅 KERT kert_only             = 25
仅 GITS gits_only             = 16
多端/含前端 multi_end         = 5
跨服务 cross_service          = 21
需要 KERT                     = 29
不需 KERT                     = 18
需要前端                      = 2
下限 = no_service + kert_only = 26
上限 = cross_service          = 21
g4 自洽：1 + 17 + 29 = 47
```

### 3.2 与 TL/QA 包 §4 表的逐项比对

| TL 表条目 | QA 独立值 | 一致 |
|---|---|---|
| `47 = 无服务 + 仅 KERT + 仅 GITS + 多端` | 47 = 1+25+16+5 | **MATCH** |
| `需要 KERT 29 = 25 + 4` | 29（多端中含 KERT 4 = 2×`test_gits_to_kert_*` + `test_all_services_simultaneously` + `test_full_insight_flow`） | **MATCH** |
| `不需 KERT 18 = 1 + 16 + 1` | 18（多端中不含 KERT 1 = `test_gits_frontend_reachable`） | **MATCH** |
| `跨服务 21 = 16 + 5` | 21；分文件 3/2/4/2/3/3/4 | **MATCH** |
| `需要前端 = 2` | 2 | **MATCH** |
| `g4 自洽 1 + 17 + 29 = 47` | 47 | **MATCH** |
| `下限 26 = 1 + 25` | 26 | **MATCH** |
| `上限 21 = 16 + 5` | 21 | **MATCH** |

**结论：8/8 全部相符，无一项不符 → 不触发「复算不符即退回」。**

### 3.3 账本分组 vs QA 独立分组（nodeid 级）

```text
no_service  ledger= 1 QA= 1 一致=True
kert_only   ledger=25 QA=25 一致=True
gits_only   ledger=16 QA=16 一致=True
multi_end   ledger= 5 QA= 5 一致=True
-> 分组完全一致: True
```

### 3.4 证据可复现性（额外收获，强佐证）

我用**自己的端口（8210）**独立跑出的账本 JSON，与交付方账本**逐字节比对**：

```text
g2 sha_mine=9b0b553de940 sha_delivered=9b0b553de940 identical=True
g3 sha_mine=00f1b8d31d10 sha_delivered=00f1b8d31d10 identical=True
g4 sha_mine=cbebb59ac3dc sha_delivered=cbebb59ac3dc identical=True
g5 sha_mine=6bd0ac338434 sha_delivered=6bd0ac338434 identical=True
g6 sha_mine=95f17014fe23 sha_delivered=95f17014fe23 identical=True
g1 identical=False —— 仅 uncovered_reasons 中的 KERT 探活地址不同：
     mine=http://127.0.0.1:8210/api/skill/health
     delivered=http://127.0.0.1:8199/api/skill/health
     （g1 中 KERT 是缺失服务，故地址必然入账；交付 EVIDENCE §8 已声明 g1 用 8199）
```

→ 交付方 `evidence-runs/` 的账本**可被独立复现且未被篡改**，且"结论不依赖具体端口号"成立。

---

## 4. `g1`~`g6` 六组账本复现

驱动：`/tmp/qa-e2e-c/qa_groups.sh`（KERT 走干净端口 **8210**；KERT 缺失组把 `KERT_BASE_URL` 指向同一空闲端口）。命令统一为 `python -m pytest tests/e2e/ -rs`。

| 组 | 场景 | 关键 env | QA 实测 | 期望 | 判定 |
|---|---|---|---|---|---|
| g1 | 无服务 + 默认 | — | `1 passed, 46 skipped`，**exit 1** | 同 | ✅ |
| g2 | 仅 KERT + 默认 | — | `26 passed, 21 skipped`，**exit 0** | 同 | ✅ |
| g3 | 仅 KERT + `E2E_REQUIRE_KERT=1` | +KERT | `26 passed, 21 skipped`，**exit 0** | 同 | ✅ |
| g4 | KERT 缺失 + `E2E_REQUIRE_KERT=1` | +KERT | `1 passed, 17 skipped, **29 errors**`，**exit 1** | 失败 | ✅ |
| g5 | KERT 在线 + `E2E_REQUIRE_GITS=1` | +GITS | `26 passed, 1 skipped, **20 errors**`，**exit 1** | 失败 | ✅ |
| g6 | 无服务 + `E2E_REQUIRE_SERVICES=1` | +全部 | `1 passed, **46 errors**, 0 skip`，**exit 1** | 失败 | ✅ |
| （补）g7 | KERT 在线 + `E2E_REQUIRE_GITS_FRONTEND=1` | +前端 | `26 passed, 19 skipped, **2 errors**`，**exit 1** | 失败 | ✅ |

账本字段（QA 自跑）：

```text
g1: collected=47 passed=1  skipped=46 failed=0 errors=0  min=26 max=21 pytest_exitstatus=0 violations=2 require={}
g2: collected=47 passed=26 skipped=21 failed=0 errors=0  min=26 max=21 pytest_exitstatus=0 violations=0 require={}
g3: ... passed=26 skipped=21  require={'E2E_REQUIRE_KERT': True}
g4: ... passed=1  skipped=17 errors=29  require={'E2E_REQUIRE_KERT': True} violations=2
g5: ... passed=26 skipped=1  errors=20  require={'E2E_REQUIRE_GITS': True} violations=1
g6: ... passed=1  skipped=0  errors=46  require={'E2E_REQUIRE_SERVICES': True} violations=2
g7: ... passed=26 skipped=19 errors=2   require={'E2E_REQUIRE_GITS_FRONTEND': True}
```

**六组（+1 补测）账本与交付 `EVIDENCE.md` §5 表述完全一致，无一项偏差。**

### 4.1 CI job 逐字复现（真值端口 8106，netns 隔离）

用**我自己抽取**的步骤脚本（与交付方脚本逐字节相同，见 AC-1）：

| 模式 | Start | Run | Assert | 结论 |
|---|---|---|---|---|
| `happy` | exit 0（第 2 秒就绪） | exit 0（`26 passed, 21 skipped`） | exit 0（`✓ 覆盖账本下限断言通过`） | 正向全通 |
| `kert-down` | 未执行 | **exit 1** | **exit 1** | 防假绿有效 |
| `port-occupied` | **exit 1** | 未执行 | 未执行 | 拒绝复用外部实例 |

---

## 5. 对抗性检查（QA 主动加做，防"断言空转"）

| # | 检查 | 构造方式 | 结果 | 说明 |
|---|---|---|---|---|
| A | **`failed > 0` 分支是否为死代码** | 仓外桩服务（`/tmp/qa-e2e-c/stub_kert.py`）：`/api/skill/health` 返回 200（骗过探活），其余端点一律 503 | `24 failed, 2 passed, 21 skipped`，**exit 1**；账本 `violations = ["failed=24（必须 0）", "passed=2 < 下限 26…"]` | **该分支有效**：服务就绪但用例真失败 ⇒ job 必失败，不会被 skip/空转掩盖 |
| B | **`errors > 0` 分支** | g4（KERT 缺失 + require） | `violations=["errors=29（必须 0）", …]`，exit 1 | 有效 |
| C | **下限/上限推导是否随用例集合自适应** | 比较 g1（`uncovered=46`）、g4（`uncovered=17`）与静态跨服务 21 | 不一致即证明 `uncovered` 来自**运行时结果**而非静态清单 | 有效 |
| D | **断言是否可被"静态集合"蒙混** | `min_passed` 由收集阶段分组算出（与运行时服务可用性无关），故 KERT 起不来时 `passed=1 < 26` 必然触发 | g4 实测触发 | 有效（这正是防假绿的关键机理） |

> 说明：受"不得修改实现或测试"约束，A 项用**外部桩**替代改动断言，等效地证明该分支可达且有效。

---

## 6. 红线核验（静态）

| 红线 | 核验方式 | 结果 |
|---|---|---|
| `src/kert/**` 未触碰 | `diff -rq` 改动前后 `src/` | ✅ 零差异 |
| `tests/{unit,integration,contract,recovery}/**` 未触碰 | `diff -rq` | ✅ 零差异 |
| `tests/e2e/test_*.py` 断言语义未改 | `diff -rq tests/` 仅 `conftest.py` 不同（47 个 test 文件零差异） | ✅ |
| 其它 CI job / `on:` 段未改 | `git diff 73d0e03 c865365 -- .github/workflows/ci.yml` 的 hunk 仅 `@@ -115,6 +115,18 @@`、`@@ -137,10 +149,108 @@`（均落在 `e2e` job 内）；唯一删除行是旧的 `run: python -m pytest tests/e2e/ -q` | ✅ `on:` 仍为 `push/pull_request: branches: [main, develop]` |
| 无 `continue-on-error` | YAML 解析：`jobs.e2e.continue-on-error` 未设置；其 7 个 step 全部 `None` | ✅ |
| 无 `|| true` / 吞异常 | `e2e` job 段内 `|| true` **0** 次（仓内 2 处在 `lint` job，为**既有**代码，未被本次改动引入）；新增行中仅 `except httpx.HTTPError`（探活轮询用，**只决定"是否就绪"**，skip/fail 判定在其后由策略决定，不吞结论） | ✅ |
| 无跨仓凭据 | `e2e` job 无 secret/token；`gits-cbanking` 未被读写 | ✅ |
| `E2E_REQUIRE_SERVICES` 既有语义 | g6：`46 errors, 0 skip` | ✅ |
| 无无条件 skip | 全仓 `pytest.skip` 仅 1 处调用点，位于探活失败后的 `_resolve()` | ✅ |

---

## 7. 残留项（必须随结论流转，不得默认通过）

| # | 项 | QA 判定 | 影响与后续 |
|---|---|---|---|
| **R-1** | **AC-10** 服务齐备（GITS 后端 8082 + 前端 5173）下 47 例全跑、断言强度逐条一致 | **未验证** | 本机与 CI 均无 GITS（`8082/5173` 探活 `conn-fail`）。**不得因其余全通过而推定通过**。留待联调/UAT 环境（届时设 `E2E_REQUIRE_SERVICES=1`，缺失即 fail 而非 skip） |
| **R-2** | **AC-1 的「在真实 CI 中」属性** | **未验证** | 全仓仅 `.github/workflows/ci.yml` 一个 workflow，`on:` **仅** `push/pull_request` 到 `main`/`develop` → 本分支 push（**即便已推到 origin**）**不触发任何工作流**；触发需向 `develop` 开 PR，超出派工授权。**替代证据的证明边界**：本地逐字执行 job 的 `run` 脚本（netns 取干净 8106）证明的是 **job 逻辑**；**不覆盖** GitHub runner 特有条件（`$RUNNER_TEMP`、`actions/checkout`、runner 镜像）与 runner 的 step 失败即中止语义。**待本分支首次触发 CI 时必须复验** |
| **R-3** | `Performance Benchmarks` 计时不稳定（`22.36ms > 20.0ms`） | **不在本 QA 范围** | 该 job 为既有 `continue-on-error: true`，与本交付无关；**不得**因它红判本交付失败，也**不得**因此忽略它。另行处理 |
| **R-4**（QA 追加） | `E2E_REQUIRE_GITS_FRONTEND` 未在交付证据中实测 | **已由 QA 补测通过**（g7） | 不构成残留，仅记录覆盖来源 |
| **R-5**（QA 追加） | 交付时 `EVIDENCE.md` 记 `PUSHED=否`，但当前 `origin/feature/PI-ARCH-L10-L13 == c865365`（**已推送**） | **观察项，非阻断** | 属**时点差异**（EVIDENCE 写于 `d90e48e` 之后的 `8131c7a`；其后的 QA 包提交 `c865365` 已在远端）。不影响 R-2 结论（`on:` 未监听本分支）。**建议 Owner 知悉**：本仓相关提交均已推送至 `origin`，与"未 push"的表述现况不符 |

---

## 8. QA 自身偏差披露（**必须一字不漏读完**）

| 项 | 事实 | 影响评估 |
|---|---|---|
| **偏差** | 我在自写的 CI 复现驱动 `qa_ci_repro.sh` 的清理函数中使用了 `pkill -f "serve_skill_service.py --port 8106"`。`unshare -rn` 提供**独立 network namespace，但不提供 PID namespace**，因此该 `pkill` **匹配到了宿主机上外部 dkws 实例**（`/home/szf/dev/deepseek_harness/data_knowledge_ws/dkws`，原 pid 4553）。 | **未复用该实例、未以其作为任何证据**；但**确实终止了它的进程**一次，与"不得触碰 8106 上 dkws 实例"的字面要求**不符**。 |
| **恢复情况** | 该实例由 `systemd --user`（pid 4234，启动于 18:43）托管并**自动重启**：新 pid **416155**，启动于 **21:07:20**，当前 `GET /api/skill/health = 200`，pidfile 已更新为 416155。 | 停服窗口约数秒级，**已自愈**；服务为无状态 dev 实例，无数据损坏。 |
| **对本次验收有效性的影响** | **无**。理由：① 我全部 8106 相关证据取自 **netns 内独立 loopback**（netns 内预检 `8106 → 000`，且能自行启动并占用 8106，见 AC-1/§4.1），与宿主机 8106 在网络层**完全隔离**；② 六组本地取证走宿主 **8210**（探活前 `8210 → conn-fail`），宿主 8106 从未进入任何一次判定；③ 事件时点（21:07）晚于交付方全部证据生成时点，且不改变任何用例结果。 | 判定**不影响任何 AC 结论**，但**如实披露**，并请 Owner 决定是否需要进一步追责或复测。 |
| **后续处置建议** | 该实例已被 systemd 恢复，无需我另行操作（我也不应再对其做任何动作）。同类操作若再次进行，应改用 `unshare --fork --pid`（带 PID namespace）或仅按 pidfile 精确 `kill`。 | — |

除该偏差外，本会话**未**修改仓内任何被测文件、**未**配置凭据、**未**执行 `git add`/merge/force push/`--no-verify`。取证期间临时创建的 2 个 `git worktree` 已 `git worktree remove` + `prune` 清理；`8210` 端口已释放，无残留进程。

---

## 9. 可复现命令（逐条重跑）

```bash
REPO=/home/szf/dev/Leibniz-KERT; PY=$REPO/.venv/bin/python

# 0) 环境与受测版本
cd $REPO && git rev-parse HEAD && sha256sum tests/e2e/conftest.py .github/workflows/ci.yml

# 1) 独立复算分组（仓外插件，不引用实现常量）
QA_DUMP=/tmp/qa-e2e-c/e2e_items.json PYTHONPATH=/tmp/qa-e2e-c \
  $PY -m pytest tests/e2e/ --collect-only -q -p qa_collect
$PY /tmp/qa-e2e-c/recompute.py

# 2) 六组账本（干净端口 8210）
bash /tmp/qa-e2e-c/qa_groups.sh

# 3) 账本 / 豁免 / 分组 三方比对
$PY /tmp/qa-e2e-c/verify_ledgers.py

# 4) CI job 逐字复现（真值端口 8106，netns 隔离）
$PY /tmp/qa-e2e-c/extract_steps.py            # 独立抽取并与交付脚本逐字节比对
unshare -rn bash -c 'ip link set lo up; bash /tmp/qa-e2e-c/qa_ci_repro.sh happy'
unshare -rn bash -c 'ip link set lo up; bash /tmp/qa-e2e-c/qa_ci_repro.sh kert-down'
unshare -rn bash -c 'ip link set lo up; bash /tmp/qa-e2e-c/qa_ci_repro.sh port-occupied'

# 5) AC-11 双向回归（worktree 保留 .git）
git worktree add --detach /tmp/qa-e2e-c/wt-before 73d0e03
git worktree add --detach /tmp/qa-e2e-c/wt-after  c865365
(cd /tmp/qa-e2e-c/wt-before && $PY -m pytest tests/unit/ tests/integration/ tests/contract/ tests/recovery/ \
   --cov=kert --cov-fail-under=80 --cov-report=term-missing)
(cd /tmp/qa-e2e-c/wt-after  && $PY -m pytest tests/unit/ tests/integration/ tests/contract/ tests/recovery/ \
   --cov=kert --cov-fail-under=80 --cov-report=term-missing)
git worktree remove --force /tmp/qa-e2e-c/wt-before
git worktree remove --force /tmp/qa-e2e-c/wt-after && git worktree prune

# 6) 对抗性桩（failed>0 分支）
$PY /tmp/qa-e2e-c/stub_kert.py &   # 仅健康检查 200，其余 503
KERT_BASE_URL=http://127.0.0.1:8210 E2E_REQUIRE_KERT=1 $PY -m pytest tests/e2e/ -rs
```

**QA 自产证据（原始日志/账本，位于 `/tmp/qa-e2e-c/`）sha256**

```text
c632c825767b1bcf4b95dbab8b022deaf62d568f47a415b98886303491242d53  g1-ledger.json
9b0b553de940177af5880953323a92a83f0ddc6cfe338ff518c754e3d23e0c3d  g2-ledger.json
00f1b8d31d1043a9b2c71429bc7bcef3cfa1eeedf22067a27b15e0c5760d941b  g3-ledger.json
cbebb59ac3dcce8515de0bc53593768a2ffe094db1de4ee48c5cba69697dec67  g4-ledger.json
6bd0ac3384343a3f2cdf630eddce1d8003cbbc2162a137a47e82ef5f56a183c6  g5-ledger.json
95f17014fe236a3841d96da7ad18101f0e9acbf1d47e9aa40eccdbb567a661db  g6-ledger.json
cd50b25f1de29a4f94221e61193691bdb6a41f33e4cea13ce4a0b6253f76f4dd  g7-ledger.json
6848a74f46461353a6b86f6e1f407ba03469368fc47e2eeedeaaa4621adbb304  stub-ledger.json
bfedcd53a85941cdb53420cf368d3c81536cd20b8a36d943680cd68aa3501ad9  g1_no_service.log
1e15bf57dedb215b292d2f604166f7e4f2b963045f7611b21b1244db7ff5808e  g2_kert_only.log
906e9a51c29c38cf2e7c1f475b6fdf47ee581d8878910e5f74c4e736590dfd12  g5_require_gits_nogits.log
1eaf44cbdda258360064cefade743414cf92af6e80ba1c2518d071589628b465  qa-ci-happy.log
838b6b7697018eb1102d1aff17f557b43460c667ee8d5238ec705f1e64d163f6  qa-ci-kert-down.log
5b710ae08b7abaf33432d571e8e2c5e2f30a5e92c27cd147699005fec2536d90  qa-ci-port-occupied.log
c3b1d1ad26b9a0c84fc8711b6e4ae3dfb3c650adb9f8b0592e208f9e66233dc2  qa-regress-before-wt.log
961395b694f2f797c830f0b0ae322f1f88a717097a06d6f799c9d9311cf7a19d  qa-regress-after-wt.log
7c36f8cbe851279c78c45d13244cabf0fa4a78d9f4b289d21fb4def912fe7c95  x1_qq.log
70e33503460fe2a64ce945ab54434fdb9bea03ad88d469dc7f9e515e2377f07c  x1_rs.log
134033cccbf30e550dae6f1461bcfee25b461c09f5887344f6118cd09dd475e3  stub-run.log
8eaf2ed9f5a95d19eddbda5feac9545527e88d2e7da82510759522ab25eeeed4  g7_frontend_require.log
```

> 注：`/tmp` 为临时目录。若 Owner 要求长期留档，可将上述文件复制进 `evidence/kert-e2e-ci/qa-independent/` 后提交（本 QA **未**代为入库，亦未执行 `git add`）。

---

## 10. 结论

### 10.1 判定

**`QA_PASS`**

| 范围 | 判定 |
|---|---|
| AC-1（job 逻辑）/ AC-2 / AC-3 / AC-4 / AC-5 / AC-6 / AC-7 / AC-8 / AC-9 / AC-11 | **PASS**（均有实跑命令与原始输出） |
| X-1 / X-2 / X-3 | **PASS** |
| AC-10 | **未验证**（R-1，环境不可得） |
| AC-1 的「在真实 CI 中」属性 | **未验证**（R-2；替代证据仅证明 job 逻辑） |
| 红线（§6） | **全部通过，无违反** |
| 独立复算（§3） | **8/8 与 TL 表相符**；WAIVER / 账本 / QA 独立集合三方 nodeid 级差异 **0** |
| 发现缺陷 | **无**（未发现需退回 Feature Pilot 的缺陷；仅 §8 为 QA 自身过程偏差、§7 R-5 为观察项） |

### 10.2 结论边界声明（QA 包 §7 口径，逐条适用）

- 本 `QA_PASS` **仅**代表：**AC-1~AC-9、AC-11 在本环境通过**，且 **AC-10 与「真实 CI」属性已显式标注为未验证**。
- 本 `QA_PASS` **不代表 CI 已全绿** —— `e2e` job 的修复**尚未在真实 CI 中运行过**（R-2）。
- 本 `QA_PASS` **不代表跨服务链路已被验证** —— **21/47 用例为登记未覆盖**（`F-E2E-01`）。
- 本 `QA_PASS` **不代表** `PRODUCTION_READY=YES` 或 `GITS_UAT_PASS=YES`。
- 本 QA **未**执行 merge、**未**代 Owner 授权、**未**修改实现或测试、**未**配置跨仓凭据。
- 本 QA 存在 §8 披露的**过程偏差**（终止过一次宿主机外部 8106 实例，已由 systemd 自愈），**不影响任何 AC 结论的成立**，但按要求如实记录并交由 Owner 裁定。

**报告落盘即停止**：本 QA 不合并任何 PR、不代 Owner 授权、不再修改任何文件。
