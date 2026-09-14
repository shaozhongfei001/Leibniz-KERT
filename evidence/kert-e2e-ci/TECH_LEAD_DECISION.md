# Tech Lead 决策记录 —— KERT CI 的 E2E Tests job 跨服务依赖

- **决策日期**：2026-09-14
- **决策角色**：Tech Lead（仅裁决与派工，不写实现代码）
- **关联仓/分支**：`Leibniz-KERT` `feature/PI-ARCH-L10-L13` @ `2de820f`
- **关联单据**：`.github/workflows/ci.yml` L119–143（`e2e` job）
- **上游输入**：`gits-cbanking/HANDOFF-2026-09-14-KERT-E2E-CI.md`（三方向初版对比；其 §2.3 分组数据**已证伪**，见 §0）
- **体例参照**：`evidence/jr1/TECH_LEAD_DECISION.md`（D-1~D-4 与「非声明」段）、`evidence/jr1/TASK_PACKAGE_E2E_SKIP.md`、`evidence/waivers/WAIVER-2026-09-14-F-L00-07.md`

---

## 0. 基线订正（先立事实，再裁决）

### 0.1 用例数与服务依赖（实测，取代一切此前估计）

以 `item.fixturenames` 实测 47 个用例的**直接**服务依赖：

| 分组 | 用例数 |
|---|---|
| 无服务 | 1 |
| 仅 KERT | 25 |
| 仅 GITS（后端） | 17 |
| 三端（含 GITS 前端） | 4 |
| **合计** | **47** |

交叉校验（与实测运行结果自洽）：

```
三端全缺      → 1 passed, 46 errors   （1 + 25 + 17 + 4 - 1 = 46）
仅 KERT 可用  → 26 passed, 21 errors  （1 + 25 = 26 passed；17 + 4 = 21 errors）
```

### 0.2 两份历史材料的数据订正

| 材料 | 原数据 | 订正为 | 性质 |
|---|---|---|---|
| 本仓 `evidence/jr1/TASK_PACKAGE_E2E_SKIP.md` §1/§3 | 「34 个用例」 | **47** | 基线估计错误 |
| `gits-cbanking/HANDOFF-2026-09-14-KERT-E2E-CI.md` §2.3 | 1 / 15 / 27 / 4 | **1 / 25 / 17 / 4** | 按**文件**粗分导致漏判——散在 5 个 scenario 文件中的 10 个用例只声明 `kert_client`，被误归入"跨服务" |

**订正不改变问题性质，只改变规模与下限断言的具体数字。** 后续一切以 §0.1 为准。

### 0.3 已固化的环境事实（本决策据此裁决，不再重挖）

- KERT dev profile 起服（**无需 API Key**，无 LLM 密钥时自动走确定性适配器）：
  `KERT_PROFILE=dev python scripts/serve_skill_service.py --port 8106 --host 127.0.0.1 --workspace <可写目录>`
  - 空目录即可作 workspace，无需 `kert init`；`scripts/run_nfr_baseline.sh:80` 为既有范式
  - 复现 CI 的"无密钥"环境：`HOME=<空目录>`
  - `pyproject.toml` 的 `kert` CLI 入口在本机 venv **未安装** → 统一用上述脚本
  - 实测：`/api/skill/health`=200、`/readyz`=ready、13 个 skill 注册
- 前端仅被 **2** 个用例需要（`test_gits_frontend_reachable`、`test_all_services_simultaneously`）
- ⚠️ 本机 8106 上运行的实例属 **dkws 检出**（HEAD `12b5cce`，非本仓）→ **对它跑 e2e 会得到 `2 failed` 假象，不得作为证据**

---

## D-5 方向选择 —— **采纳 `c+b`**

**裁决**：采纳 `c+b`。即：**CI 中启动 KERT（本仓代码，dev/确定性）+ 真跑 26 个用例**，剩余 **21 个跨服务用例按 b 体例显式 skip 并登记**。

**理由**（按权重排序）：

1. **覆盖/成本比最高**：增量 <1 min（KERT 冷启 <10s）、无前置依赖，把本仓本可跑的 26 个用例真跑起来。对比纯 `b`（0 真跑）是净增；对比 `a`（47/47）则省掉跨仓凭据与 8~15 min。
2. **不引入跨仓耦合**：`a`/`a-lite` 会让 **KERT 的 CI 因 GITS 的任何改动而变红**——一个仓的流水线被另一个仓的提交支配，且违反本仓既有约束（不得修改 GITS 仓库）的精神。
3. **不引入新的安全面**：`a`/`a-lite` 需要跨仓 PAT 或 deploy key，属安全敏感配置，须 Owner 授权。
4. **与既有治理方向一致**：D-3 已确立「外部服务缺失时可控跳过」的方向，`JR1-E2E-SKIP` 正为此批准。`c+b` 是该方向的收敛形态（把"能跑的跑起来"补齐，而非停留在纯跳过）。

**边界（强制）**：

1. 26 个真跑用例**必须**有下限断言防假绿（见 D-8）；否则"KERT 未起来 → 全 skip → job 变绿"，与 `continue-on-error` 同类有害。
2. 21 个跨服务用例**必须显式 skip + 有登记**，禁止以任何静默手段变绿。
3. CI 真实覆盖口径必须写进证据与 PR：**26/47 真跑，21/47 未覆盖**。
4. `a` / `a-lite` **不否决、只暂缓**：留待出现"CI 级联调需求"时另行裁决（届时须先解决 D-9 的凭据授权）。

---

## D-6 对冻结任务包 `JR1-E2E-SKIP` 的差异决议 —— **三处逐一裁决**

`JR1-E2E-SKIP` 处于 `ready_for_dev`，但其三条内容与 `c` 直接冲突。逐条裁决：

| # | 冲突点 | 裁决 |
|---|---|---|
| ① | AC-1 写「34 skipped」，实际 47 个用例 | **数字作废，以 47 为基数重述**。属**基线数据订正**（§0.2），非范围扩大。 |
| ② | §7 非目标「不在 CI 中启动 GITS Backend 或 KERT 服务」 | **对 KERT 条目解禁，对 GITS 条目保留**。新任务包允许"在 CI 中启动 KERT（本仓代码，dev/确定性）"；仍**禁止启动 GITS**。 |
| ③ | §4.1「只改 `conftest.py`」 | **解禁对 `.github/workflows/ci.yml` 的修改**，作用域**严格限定在该 `e2e` job 内**（不得动其它 job、不得动 `on:` 触发段）。理由：`c` 的本质是「CI 编排 + 测试夹具」两处协同，只改一处无法达成。 |

**形式**：**不开新任务包号覆盖它，而是出修订版任务包** `KERT-E2E-C`（见 `TASK_PACKAGE_E2E_C_KERT_ONLY.md`）。
`JR1-E2E-SKIP` 状态改为 `superseded_by=KERT-E2E-C`，**不删除**——保留其 AC/约束的历史可追溯性。

---

## D-7 `require` 语义 —— **拆成服务维度**

**问题**：AC-3 的 `E2E_REQUIRE_SERVICES=1` 是**全局**开关。在"只起 KERT"的 CI 中不可用——置 1 会把合法缺失的 GITS 判失败；不置 1 则 D-8 的防假绿失去正向开关。

**裁决**：**拆成服务维度**，新增 `E2E_REQUIRE_KERT` / `E2E_REQUIRE_GITS` / `E2E_REQUIRE_GITS_FRONTEND`；`E2E_REQUIRE_SERVICES=1` **保留并向后兼容**，语义等价于三者全开。

**理由**：

1. 服务维度语义精确：CI 设 `E2E_REQUIRE_KERT=1` 即表达「KERT 必须可用，否则 job 失败」，而 GITS 保持「缺失即 skip」——这正是 `c` 需要的语义。
2. 全局开关在「只起 KERT」场景下正交性不足：它把"应该有"与"本来就没有"混为一谈。
3. 向后兼容：已有联调/UAT 环境若已设 `E2E_REQUIRE_SERVICES=1`，行为不变。

**边界（强制）**：

1. `E2E_REQUIRE_SERVICES=1` 的**既有语义不得削弱**——仍必须使三端缺失全部判失败。
2. 联调/UAT 环境仍应显式设 `E2E_REQUIRE_SERVICES=1`（覆盖三端），**不得**只设 KERT，否则 GITS 侧回归会被 skip 掩盖。
3. 服务维度开关与全局开关同时存在时，取**并集**（任一要求即要求）。

---

## D-8 防假绿强制项 —— **强制**

**裁决**：**强制**。`e2e` job 在 pytest 执行后，**必须**断言：

1. `errors == 0`
2. `failed == 0`
3. `passed >= 26`（下限；数字来源见 §0.1：无服务 1 + 仅 KERT 25）

**理由**：若不设下限，**KERT 启动失败会导致 47 个用例全部 skip、job 变绿**——这与 `continue-on-error: true` 同类有害，正是本仓最忌讳的"假绿"（参见 GK16 信任加固中确立的"断言不得空转"原则）。下限断言是把"KERT 真的起来了"从假设变成**门禁**的唯一手段。

**边界（强制）**：

1. 实现方式不限定（session 级钩子 / 独立断言步骤均可），但**必须使"KERT 未起来"表现为 job 失败**，而非 warning。
2. 下限数字必须**标注来源**（引用本决策 §0.1 的实测分布），且必须是**可随用例增删重算的表达式**，不得成为脱离实际的魔数。用例数变化时，下限须同步重算——这也是 D-10 的失效触发条件之一。
3. 断言必须输出**覆盖账本**（见 D-10），使"未覆盖"在日志中显式可见。
4. 禁止用 `continue-on-error`、`|| true`、吞异常等任何手段绕过本断言。

---

## D-9 跨仓 PAT —— **只出清单并 STOP（本决策未触发该分支）**

**裁决**：本决策采纳 `c+b`，**不需要任何跨仓凭据**。但为使 `a`/`a-lite` 日后可裁决，现将授权口径立此存照：

**若**未来裁决走 `a`/`a-lite`，**Tech Lead 只提交"需 Owner 授权事项"清单并 STOP，禁止自行配置任何凭据 / token / deploy key**（TL 无凭据配置权）。

清单要素（授权时必须逐项确认）：

| 项 | 建议 |
|---|---|
| 读取范围 | **仅** `gits-cbanking` 单仓；**read-only**（不得给 write） |
| 凭据形态 | 优先 **Deploy Key（read-only）**；或 Fine-grained PAT（仅 `contents: read`、仅限该仓）。**不建议** Classic PAT（权限过大） |
| 存放 | GitHub Actions **Secrets**（仓库级），建议名 `GITS_REPO_READ_TOKEN`；**禁止**写入文件、日志或提交 |
| 有效期 | ≤90 天并登记到期日 |
| 必须一并接受的副作用 | 引入后 **KERT 的 CI 会因 GITS 改动而变红**（跨仓耦合），需 Owner 明示接受 |
| 最小权限复核 | 授权前须确认该凭据无法访问其它仓、无 write 能力 |

---

## D-10 豁免登记口径 —— **定路径、定缺口号、定失效触发**

**裁决**：

| 项 | 裁定 |
|---|---|
| 登记文件路径 | `evidence/kert-e2e-ci/WAIVER-E2E-CROSS-SERVICE.md` |
| 关联缺口编号 | **`F-E2E-01`**（由本决策新立）。实施者须先在仓内检索确认编号未被占用；若已占用则顺延并在文件中注明。 |
| 被豁免对象 | **恰好 21 个**跨服务用例（仅 GITS 17 + 三端 4）；**明确豁免清单**（文件+用例名）必须逐条列出，不得用"等"字概括 |
| **不**豁免范围 | KERT 侧 26 个用例**必须真跑**，不得豁免；`tests/unit|integration|contract|recovery` 不受影响 |

**自我过期机制**（因无法像 `xfail(strict=True)` 自动过期，采用「**失效触发条件 + 每轮覆盖账本**」双轨）：

三条**并列**触发条件，**任一成立即须重新裁决**：

1. **CI 引入 GITS 服务编排**（`a`/`a-lite` 落地）→ 本豁免**自动作废**，21 个用例须转为真跑。
2. **跨服务用例集合发生变化**（新增/删除/移动/重命名）→ 账本与登记清单不一致即失效。
3. **每轮 CI 覆盖账本越界** → job 中打印的账本若出现 `passed < 26` 或 `skipped > 21` 或 `errors > 0`，由 D-8 下限断言直接判 job 失败。

**覆盖账本（每轮 CI 必须打印）**：

```
E2E 覆盖账本：
  passed  = <n>   (下限 26)
  skipped = <n>   (上限 21)
  failed  = <n>   (必须 0)
  errors  = <n>   (必须 0)
  未覆盖用例清单：<逐条列出，按文件分组>
```

**边界**：本豁免是**"未覆盖"的显式登记，不是"通过"**。任何报告/PR 不得把"CI 绿"表述为"跨服务链路已验证"。

---

## 决策记录落盘位置选择（说明理由）

**裁定**：**新建 `evidence/kert-e2e-ci/`**，不在 `evidence/jr1/TECH_LEAD_DECISION.md` 追加。

**理由**：

1. **关联对象不同**：`evidence/jr1/` 的决策关联 `fix/ci-httpx-test-dependency` → `develop` 的 PR 与 JR-1 交付范围；本决策关联 `feature/PI-ARCH-L10-L13` 分支上的 `e2e` job。
2. **前置条件不成立**：`JR1-E2E-SKIP` 明写「前置条件：CI 修复 PR 已合入 `develop`」——该前置在本分支**不成立**。把新决策塞进 jr1 目录会让该前置条件语义混乱。
3. **保持 jr1 目录的历史独立性**，便于回溯与审计。

---

## 非声明

- 本决策**仅**裁决 D-5~D-10 六项，**不代表 CI 已全绿**——`e2e` job 的修复尚未实施；`Performance Benchmarks` 的计时不稳定问题（`22.36ms > 20.0ms` 阈值）亦不在本决策范围内。
- 本决策**不代表** KERT `PRODUCTION_READY=YES` 或 `GITS_UAT_PASS=YES`；CI 绿不等于联调通过。
- 本决策**不构成** Independent QA 的 `QA_PASS`。Tech Lead 未记 `DEV_SELF_CHECK_PASS`。
- 本决策**未**授权或配置任何跨仓凭据（D-9 仅在"未来走 `a`/`a-lite`"时生效，且须 Owner 授权）。
- Tech Lead **未**执行 merge、未代 Owner 授权、未修改任何业务代码。
- 采纳 `c+b` 意味着**接受 21/47 用例长期无 CI 自动验证**（此前它们同样从未被验证），该覆盖缺口已登记为 `F-E2E-01`。

## 覆盖口径（明确回答"哪些被 CI 真实覆盖、哪些不覆盖"）

| 分组 | 用例数 | `c+b` 之后的 CI 状态 |
|---|---|---|
| 无服务 | 1 | ✅ **真跑** |
| 仅 KERT | 25 | ✅ **真跑**（需 CI 先起 KERT dev） |
| 仅 GITS | 17 | ⚪ **显式 skip + 登记**（不覆盖） |
| 三端 | 4 | ⚪ **显式 skip + 登记**（不覆盖） |
| **合计** | **47** | **26 真跑 / 21 登记未覆盖** |
