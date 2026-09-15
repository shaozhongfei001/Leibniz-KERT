# 独立 QA 执行包 —— `KERT-E2E-C` 交付验收

- **QA 对象**：`.github/workflows/ci.yml` 的 `e2e` job 修复 + `tests/e2e/conftest.py`
- **交付提交**：`d90e48e`（实现）、`8131c7a`（EVIDENCE 补记）、`7b3d5cb`（TL 核验记录）
- **基线提交**：`73d0e03`
- **分支**：`feature/PI-ARCH-L10-L13`
- **批准角色**：Tech Lead（2026-09-14）
- **来源决策**：`evidence/kert-e2e-ci/TECH_LEAD_DECISION.md`（D-5~D-10 + 交付后核验记录）
- **任务包**：`evidence/kert-e2e-ci/TASK_PACKAGE_E2E_C_KERT_ONLY.md`（AC-1~AC-11）
- **体例参照**：`evidence/M2_INDEPENDENT_QA_PACKAGE.md`

---

## 0. QA 角色声明（**独立性硬要求**）

| 要求 | 说明 |
|---|---|
| **必须独立于实现者** | 不得是 `d90e48e` / `8131c7a` 的作者或参与会话 |
| **必须独立于 TL 核验** | 不得复用 `7b3d5cb` 的核验结论作为验收依据（该核验**不是** `QA_PASS`） |
| **不得修改实现** | 发现缺陷 → **退回 Feature Pilot**，QA 不得自行改代码；这与"改实现以通过"同属红线 |
| **记录权** | 仅本角色可记录 `QA_PASS`；`DEV_SELF_CHECK_PASS` 不构成验收 |
| **环境指纹** | 证据中必须记录 `python -V`、`node -v`（若涉及）、`git rev-parse HEAD`、OS |

⚠️ **不得触碰**：机器上 8106 端口可能已有 **dkws 检出**的实例（HEAD `12b5cce`，非本仓）。
对它跑 e2e 会产出 `2 failed` **假象**（决策 §0.3 已警示）。QA 必须用干净端口（见 §1.3）。

---

## 1. 环境准备

### 1.1 取代码与依赖

```bash
cd /home/szf/dev/Leibniz-KERT
git fetch origin && git checkout feature/PI-ARCH-L10-L13 && git pull --ff-only
git rev-parse HEAD          # 期望 >= 7b3d5cb
git status --porcelain      # 期望为空（干净）
python3 -m venv .venv-qa && . .venv-qa/bin/activate
pip install -e ".[api,dev]"
```

### 1.2 基线回归（对应 AC-11）

```bash
python3 -m pytest tests/unit/ tests/integration/ tests/contract/ tests/recovery/ \
  -q --cov=kert --cov-fail-under=80
# 期望（交付报告口径）：1198 passed, 1 xfailed；coverage 84.35%
# 须与「改动前」对照（可用 73d0e03 另开 worktree 复跑）
```

### 1.3 取得干净的 8106（**禁止复用外部实例**）

交付所用的隔离手段是 `unshare -rn`（网络命名空间隔离 + 干净 localhost）。QA 可选其一：

```bash
# 方案 A：网络命名空间隔离（与交付一致）
unshare -rn bash -lc '...在此启动 KERT 并跑 pytest...'

# 方案 B：显式确认 8106 无外部实例后再启动
curl -fsS --max-time 2 http://127.0.0.1:8106/api/skill/health && echo "已被占用 → 不得复用" || echo "空闲，可启动"
```

KERT dev 启动命令（决策 §0.3，dev profile **无需 API Key**，无 LLM 密钥自动走确定性适配器）：

```bash
KERT_PROFILE=dev python scripts/serve_skill_service.py \
  --port 8106 --host 127.0.0.1 --workspace <可写目录>
# 空目录即可作 workspace，无需 kert init
# 复现 CI「无密钥」环境：HOME=<空目录>
```

---

## 2. 逐 AC 验证矩阵

| AC | 验证方法 | 期望 | 备注 |
|---|---|---|---|
| **AC-1** | 检查 `ci.yml` 的 `Start KERT` 步：就绪等待 + 未就绪 `exit 1`；并**独立判定**其"在真实 CI 中"是否已验证 | 步骤存在且逻辑为 fail-closed | ⚠️ 见 §3 R-2：真实 CI **未验证**（`on:` 仅 main/develop） |
| **AC-2** | 起 KERT，跑 `pytest tests/e2e/` | **`26 passed, 21 skipped, 0 failed, 0 error`** | 主判定项 |
| **AC-3** | 无任何服务，跑 `pytest tests/e2e/` | **`1 passed, 46 skipped, 0 failed, 0 error`**；**进程退出码非 0 属设计**（由 D-8 钩子把 `pytest_exitstatus=0` 升级为失败）；须在账本中核对 `pytest_exitstatus=0` 且 `violations` 非空 | 交付已声明 |
| **AC-4** | 检查 21 条 skip reason | 含**缺失服务名 + 探活地址** | 逐条抽样 |
| **AC-5** | KERT 缺失 + `E2E_REQUIRE_KERT=1` → 跑 `pytest tests/e2e/` | **`1 passed, 17 skipped, 29 errors`**，且**需要 KERT 的用例 0 skip** | 独立复算 `29 = 25 + 4`，见 §4 |
| **AC-6** | 同上场景，观察 job/Run 步的退出码 | **Run 步 `exit 1`** + **独立 Assert 步 `exit 1`**（双重防线） | 防假绿关键项 |
| **AC-7** | 检查账本输出 | 含 `passed/skipped/failed/errors` 计数 **+ 未覆盖用例逐条清单（21 条）** | 见 §4 |
| **AC-8** | 检查 `WAIVER-E2E-CROSS-SERVICE.md` | `F-E2E-01`、**21 条逐项清单**（不得用"等"字）、**三条失效触发条件** | 已抽样核对通过（TL），QA 需独立复核 |
| **AC-9** | 仅起 KERT（无 GITS），检查 25 个仅 KERT 用例 | 全部 **passed**（不因 GITS 缺失而 skip） | 与 AC-2 同场景 |
| **AC-10** | 起三端（KERT + GITS 后端 + 前端），跑全量 | 47 全跑，断言强度与改动前逐条一致 | ⚠️ **本机与 CI 均无 GITS → 见 §3 R-1** |
| **AC-11** | §1.2 回归对照 | 与改动前逐项一致（1198 passed / 1 xfailed / 84.35%） | 须改动前后双向对照 |

### 2.1 附加验证项（TL 追加，须 QA 独立判定）

| # | 项 | 期望 |
|---|---|---|
| **X-1** | `addopts` 已含 `-q`，CI 曾再传 `-q` 成 `-qq` **吞掉计数行**；交付改为 `-rs`。验证日志中**确实出现** `N passed, M skipped` 计数行 | 计数行可见（**这是"结论可核对"的前提**） |
| **X-2** | `require` 是否**逐用例**判定（而非全局先检） | 构造 `E2E_REQUIRE_GITS=1` 且 GITS 缺失：**25 个仅 KERT 用例必须仍 passed**，不得被连带判错 |
| **X-3** | 实现是否**拒绝复用** 8106 上已运行的外部实例 | 步骤中存在显式检查且失败即 `exit 1` |

---

## 3. 三个「**不得默认通过**」项（交付已如实披露）

| # | 项 | 交付状态 | QA 必须做 |
|---|---|---|---|
| **R-1** | **AC-10** 服务齐备环境 | **未验证**（无 GITS 后端/前端） | 若 QA 环境同样不可得 → **在 QA 结论中显式标注"AC-10 未验证"**，**不得**因"其余全通过"而推定其通过 |
| **R-2** | **AC-1 的「在真实 CI 中」属性** | **未验证**。`on:` 仅监听 `main`/`develop`，push 本分支不触发工作流；向 `develop` 开 PR 超出派工授权。替代证据为在真值端口 8106 上**逐字执行 job 步骤**（`unshare -rn`） | 明确判定该替代证据的**证明边界**：证明 **job 逻辑**，**不覆盖** GitHub runner 特有条件（`$RUNNER_TEMP`、`actions/checkout`、runner 镜像）。QA 结论须把它列为残留项 |
| **R-3** | `Performance Benchmarks` 计时不稳定（`22.36ms > 20.0ms`） | 独立问题 | 不在本 QA 范围；**不得**因它红而判本交付失败，也**不得**因此忽略它 |

---

## 4. 数字自洽性独立复核（**TL 要求 QA 独立复算，不得引用本包结论**）

TL 已核算如下，QA 须用**自己的** `item.fixturenames` 数据独立复算并比对：

```
47 = 无服务 1 + 仅 KERT 25 + 仅 GITS 16 + 多端 5
需要 KERT 的用例 = 29 = 仅 KERT 25 + 多端【中含 KERT】4
不需 KERT 的用例 = 18 = 无服务 1 + 仅 GITS 16 + 多端【中不含 KERT】1
跨服务 = 21 = 仅 GITS 16 + 多端 5      （= g2 的 skipped）
需要前端的用例 = 2
g4 自洽：passed 1 + skipped 17 + errors 29 = 47
下限/上限推导：passed 下限 26 = 1 + 25 ；skipped 上限 21 = 16 + 5
```

**若 QA 复算结果与上表任一数字不符 → 必须退回 Feature Pilot**，因为 `WAIVER §2` 的 21 条清单与下限断言均建立在此分组上。

**另须核对**：`WAIVER §2` 的 21 条清单与账本 `uncovered` 清单**逐条一致**（数量、文件、用例名三点）。

---

## 5. 红线与禁止事项

1. **禁止**为通过验收而修改实现或测试（包含放宽断言、加 `continue-on-error`、`|| true`、吞异常）。
2. **禁止**触碰 `src/kert/**` 业务代码。
3. **禁止**为取证而配置任何跨仓凭据。
4. **禁止**复用或触碰机器上非本仓的 8106 实例（dkws 检出）。
5. **禁止**执行 merge；**禁止**把本 QA 结论表述为联调通过。
6. `git add` 必须显式指定文件；不得 `force push`、不得 `--no-verify`。
7. 发现缺陷 → 记入 QA 报告并**退回 Feature Pilot**，不得自行修复。

---

## 6. 证据要求

在 `evidence/kert-e2e-ci/` 下提交 **`INDEPENDENT_QA_REPORT.md`**，含：

1. **环境指纹**：`python -V`、`git rev-parse HEAD`、OS、8106 取得方式（隔离命令原文）
2. **逐 AC 判定表**（§2）——每项：命令原文 + 原始输出片段 + PASS/FAIL/未验证
3. **复算表**（§4）——QA 自己的分组统计与 TL 表逐项比对结果
4. **`g1`~`g6` 六组账本的独立复现**（与交付 `evidence-runs/` 对齐）：
   - `g1` 无服务 / `g2` 仅 KERT / `g3` 仅 KERT + `E2E_REQUIRE_KERT=1`
   - `g4` KERT 缺失 + `E2E_REQUIRE_KERT=1`（防假绿）
   - `g5` `E2E_REQUIRE_GITS=1` 且 GITS 缺失（X-2）
   - `g6` 无服务 + `E2E_REQUIRE_SERVICES=1`（全局开关语义）
5. **回归对照**（AC-11）改动前后双向
6. **残留项**（R-1 / R-2 / R-3）的显式标注
7. **结论**：`QA_PASS` / `RETURN_TO_PILOT`，并附 §7 的边界声明

---

## 7. 结论边界（写入 QA 报告）

- `QA_PASS` **仅**代表：AC-1~AC-9、AC-11 在本环境通过，且 AC-10 与「真实 CI」属性**已显式标注为未验证**。
- `QA_PASS` **不代表** CI 已全绿（`e2e` job 的修复**尚未在真实 CI 中运行过**）。
- `QA_PASS` **不代表** 跨服务链路已被验证——**21/47 用例为登记未覆盖**（`F-E2E-01`）。
- `QA_PASS` **不代表** `PRODUCTION_READY=YES` 或 `GITS_UAT_PASS=YES`。
- QA **未**执行 merge、**未**代 Owner 授权。
