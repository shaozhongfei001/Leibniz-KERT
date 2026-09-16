# 证据可采信性登记 ADMISSION-E2E-EVIDENCE —— 本轮 KERT E2E 证据的效力边界

```text
STATUS=LIFTED（2026-09-14；三条解除条件均已满足，依据与残留见 §6）
REGISTERED_BY=Tech Lead（会话角色）
REGISTERED_AT=2026-09-14
SCOPE=KERT-E2E-C 交付、及其独立 QA 所产出的 E2E 证据
RELATED=TASK_PACKAGE_D-E2E-01.md（缺陷修复）/ WAIVER-E2E-CROSS-SERVICE.md（T3 已成立）/ TECH_LEAD_DECISION.md
SELF_EXPIRING=是（解除条件见 §4，三条须同时满足）
```

---

## 1. 登记事项（两条）

### R-1 本地 E2E 绿 **不得**作为 CI 绿或生产可用的证据

| 来源 | 账本 |
|---|---|
| 交付本地 `evidence-runs/g2_kert_only.log` | `passed=26 / failed=0 / skipped=21` |
| **真实 CI** run `34845070952`（sha `c865365`） | `passed=16 / failed=10 / skipped=21` |

同一 revision、同 `collected=47`、同 `skipped=21`，**仅 passed/failed 不同**。

根因（已核）：技能包解析走 `Path(__file__).resolve().parents[3] / "examples" / "bank-front-skills"`，
**本地（editable 源码检出）是唯一能让该路径解析成功的情形**；CI 的 e2e job 用非 editable 安装（`pip install ".[api,dev]"`），
`parents[3]` 落在 site-packages 之上 → `is_dir()` 为假 → `pkgs=None` → 7 个 `bank-front-*` 技能**静默消失**。

⇒ **任何以本地 E2E 绿支撑的结论，在本轮范围内不成立。** 须以真实 CI 账本为准。

> 附带更正一个先前被误述的判据：CI **一直在跑**本分支 —— KERT 的 `on.pull_request.branches` **明确含 `develop`**
> （文件内有注释解释为何必须含），且存在开放 **PR #5** `feature/PI-ARCH-L10-L13 -> develop`；
> 最近 6 轮 run 全部 `ev=pull_request` 于该分支，含受测 sha `c865365`。
> 故"本分支 push 不触发 CI"**不等于**"CI 不触发"。

### R-2 E2E 门禁的红灯 **不可**解释为「仅跨服务未覆盖」

本轮真实 CI 的 10 条失败中：

- 7 条是 `bank-front-*` 技能因**产品缺陷**而缺失（**不在** `WAIVER-E2E-CROSS-SERVICE.md` 的 21 条豁免之列）
- 另 3 条（`test_skill_list_completeness`、`test_supply_chain_via_kert`、`test_customer_admission_r1`）同因

即红灯里混着一个**会影响容器部署**的真实缺陷：`deploy/Dockerfile` 只 `COPY src/scripts/skills`，
**未拷 `examples/`**；`deploy/docker-compose.yml` 亦**未挂载**它；而镜像设了 `PYTHONPATH=/app/src`，
`parents[3]` = `/app` → `/app/examples/bank-front-skills` 不存在 → 容器内同样丢失这 7 个技能。

⇒ 在本登记解除前，**不得**把该 job 的红灯归因为"豁免范围"，也不得引用其为「仅 GITS 缺失所致」。

---

## 2. 受影响、须一并降级的下游结论

| 结论 | 处置 |
|---|---|
| 交付自述「26 条真跑且通过」 | **在 CI 中不成立**（真实账本 `passed=16`） |
| 独立 QA `QA_PASS` 中依赖 E2E 的验收项（含 AC-1 的"真实 CI"属性） | **降级为未达成**（其"job 逻辑"维度的证据仍有效，见 §3） |
| `WAIVER-E2E-CROSS-SERVICE.md` | §5 **T3 已成立**（`failed>0` 且 `passed<下限`）→ 该豁免**须重新裁决**后方可再引用 |

---

## 3. 不受影响（仍然有效，不得一并否定）

- QA 的**仓外桩对抗性实验**（健康检查 200 / 其余 503 → `failed=24` → `exit 1`）：
  证明 D-8 的 `failed>0` 分支**不是死代码** —— 这是本轮最有价值的独立证据
- QA 的夹具闭包复算与账本推导自洽性（47 = 1+25+16+5；下限 26 = 1+25；上限 21 = 16+5）
- **21 条跨服务 skip 机制正确**：`skipped=21` 恰等于上限、与 `WAIVER` §2 清单逐条一致、`errors=0`
- 红线检查（`src/kert` 与 47 个 `test_*.py` 零差异；`on:` 未动；e2e job 内无 `continue-on-error`/`|| true`）
- 本登记**明确记录**：Tech Lead 的根因结论此前**两次错误并被推翻**
  （先归因"CI 传空 workspace"、再归因"依赖 git-ignored 的 `bank_front_ws`"）。
  故 `TASK_PACKAGE_D-E2E-01.md` §0 已把「前提被证伪即 STOP」设为硬性第一步。

---

## 4. 解除条件（**三条须同时满足**）

1. `TASK_PACKAGE_D-E2E-01.md` 的 **A1** 达成：真实 CI 账本 `passed>=26`、`failed==0`、`errors==0`、`skipped<=21`
2. 技能就绪断言（同任务 §3.3）已在 CI 生效，并通过 **A2** 的负向验证（指向不存在路径时数秒内失败）
3. `WAIVER-E2E-CROSS-SERVICE.md` 已按 **T3** 重新裁决

---

## 5. 非声明

- 本登记**不是** `QA_FAIL`。QA 对「job 逻辑」的独立裁决**成立**；失效的是「验收达成」维度。
  两者被混在同一条 `QA_PASS` 里，本登记的作用是**把它们分开**。
- 本登记**不构成缺陷归责**：D-E2E-01 §0 已设 STOP 条件，前提若被证伪则该任务作废。
- 本登记**不**代表 `PRODUCTION_READY`；**不**解除 `F-E2E-01`（跨服务 21 条仍未覆盖）；
  **不**构成任何 `PASS`。
- 本登记**不**免除 §3 所列已成立证据的价值，尤其不等于"本轮 E2E 工作无产出"。

---

## 6. 解除记录（2026-09-14）

`STATUS=LIFTED` —— 三条解除条件均已满足：

| 条件 | 证据 |
|---|---|
| **1. D-E2E-01 的 A1 达成** | 真实 CI run `34858121012`（sha `4bca750`）：账本 `collected=47 passed=26 skipped=21 failed=0 errors=0`、`violations=[]`、`pytest_exitstatus=0`（修复前同一 job 为 `passed=16 failed=10`） |
| **2. 技能就绪断言在 CI 生效且负向有效** | CI 日志 `✓ 技能就绪：7 个 bank-front-* 全部存在`（可用技能 13 个）；负向：对「无外部技能包」的服务运行 CI 中**同一段**断言代码 → `::error::…缺少 7 个` 且 `exit=1` |
| **3. `WAIVER-E2E-CROSS-SERVICE` 已按 T3 重新裁决** | 见该文件 §10，裁决结果 = **豁免维持不变**。依据：新账本 `uncovered_by_file` 与 §2 清单**逐文件计数完全一致**（3/2/4/2/3/3/4 = 21），T2 未触发；T3 的触发根因（`failed>0` 且 `passed<下限`）已消除 |

**残留（不随本解除而消失）**：

- **容器实测（V1/V2、A3）已完成**，见 `TASK_PACKAGE_D-E2E-01.md` §8.6：
  镜像内 `/app/examples/bank-front-skills` 存在且 7 个技能齐；镜像内注册技能
  **13 个**；prod profile 下容器 `Up (healthy)`、`GET /api/skill/health` → **200**、
  `bank-front=7`。（本机直连 pypi 不可用，构建时仅额外加了一行 `PIP_INDEX_URL`，
  被测的 `COPY`/`ENV` 行未改，差异已 `diff` 留证。）
- **A4（systemd 部署核实）仍未完成**：本地无该部署环境（同文件 §8.7）。
  故本解除**仍不**构成 `PRODUCTION_READY`；**systemd 路径下的技能可用性未被验证**，
  不得据此推断。
- `F-E2E-01`（跨服务 21 条未覆盖）**未解除**，仍按原登记口径引用。
- §3 所列 QA 已成立证据的价值不受影响。
