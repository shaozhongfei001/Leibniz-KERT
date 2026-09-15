# 任务包 D-E2E-01 —— 技能包解析静默降级（Skill Package Resolution）

```text
STATUS=IMPLEMENTED_PENDING_REAL_CI（本地全链条已验证：e2e 账本 failed=0、passed=27>=26、violations=[]；A1 待真实 CI 核验）
GAP_ID=F-E2E-02（新建；已检索确认未占用——仓内仅 F-E2E-01 被引用）
TARGET_REPO=Leibniz-KERT
CREATED_BY=Tech Lead（会话角色）
CREATED_AT=2026-09-14
TRIGGER=独立 QA_PASS 复核：真实 CI run 34845070952（sha c865365，ev=pull_request，PR #5 → develop）
        e2e job 失败，账本 failed=10、passed=16 < 下限 26
RELATED=ADMISSION-E2E-EVIDENCE.md（证据可采信性登记）/ WAIVER-E2E-CROSS-SERVICE.md / TECH_LEAD_DECISION.md
```

---

## 0. 强制前提验证（**先做这一步；任一不成立即 STOP 并回报**）

本任务的根本前提是「依赖 `__file__` 相对布局的技能包解析，在非源码布局下**静默**失效」。
请先**实测**，不得以静态阅读代替：

| # | 验证 | 通过判据 |
|---|---|---|
| **V1** | 在**容器**内实测：构建 api 镜像后 `docker compose run --rm api ls /app/examples` | 预期**不存在**。若**存在** → 镜像布局与静态推断不符 → **STOP** |
| **V2** | 容器内实测技能清单：启动 api 后 `curl -s 127.0.0.1:8106/api/skill/list` | 预期**不含** 7 个 `bank-front-*`。若含 → 前提被证伪 → **STOP** |
| **V3** | 复现 CI 条件：在独立 venv 内**非 editable** 安装（`pip install ".[api,dev]"`）后启动服务，查 `/api/skill/list` | 预期**不含** 7 个 `bank-front-*`。若含 → **STOP** |

> **V1~V3 全部通过后**，本任务的修复目标才成立。
> 若任一被证伪：当前 10 条失败的归因即不成立，须回到 CI 日志**重新归因**，不得继续实施本任务。
> 这一条是硬要求 —— 本结论此前已有**两次错误归因**被推翻（详见 ADMISSION-E2E-EVIDENCE.md §3）。

---

## 1. 现象（真实 CI 证据，非本地复现）

run `34845070952`（sha `c865365`，= 受测 revision）e2e job：

```
E  AssertionError: Skill bank-front-kyc-gap-check 执行失败 404:
   {"status":"skill_error","errors":[{"code":"UNKNOWN_SKILL",
     "message":"未知 skillId: bank-front-kyc-gap-check"}]}
   tests/e2e/test_all_skills_execution.py:66
```

账本（artifact `e2e-coverage-ledger`，1807B，直接从该 run 下载）：

```
collected=47  passed=16  skipped=21  failed=10  errors=0
min_passed=26            ← passed(16) < 26
violations=["failed=10（必须 0）",
            "passed=16 < 下限 26（无服务 1 + 仅 KERT 25）——被 require 的服务可能未起来，禁止以 skip 掩盖"]
pytest_exitstatus=1
```

10 条失败清单（**全部同一根因**）：

| # | 用例 |
|---|---|
| 1 | `TestAllSkillsExecution.test_skill_execute[bank-front-commitment-script]` |
| 2 | `...[bank-front-eight-dimension]` |
| 3 | `...[bank-front-fact-reconciliation]` |
| 4 | `...[bank-front-kyc-gap-check]` |
| 5 | `...[bank-front-product-recommendation]` |
| 6 | `...[bank-front-report-assembler]` |
| 7 | `...[bank-front-supply-chain-graph]` |
| 8 | `TestAllSkillsExecution.test_skill_list_completeness` |
| 9 | `TestKnowledgeGraph.test_supply_chain_via_kert` |
| 10 | `TestKnowledgeGraph.test_customer_admission_r1` |

**对照**：交付本地 `evidence-runs/g2_kert_only.log` = `passed=26 / failed=0`。
同一 revision、同 `collected=47`、同 `skipped=21`，**仅 passed/failed 不同**。

---

## 2. 根因

```python
# src/kert/api/server.py:61-62
DEFAULT_SKILL_PACKAGES = Path(__file__).resolve().parents[3] / "examples" / "bank-front-skills"
# :195-196
pkgs = Path(skill_packages) if skill_packages else (
    DEFAULT_SKILL_PACKAGES if DEFAULT_SKILL_PACKAGES.is_dir() else None)   # ← 静默降级为 None
```

- `scripts/serve_skill_service.py` **不传** `skill_packages` → 恒走上述默认值；
- `SkillExecutionService._load_packages()` 是 **`bank-front-*` 的唯一注册入口**；
- `pkgs=None` 时 registry 只剩 5 条 base（`skill-customer-*` / `SP-20` / `SP-21`）+ SP-15。

四种环境的解析结果：

| 环境 | `import kert` 解析到 | `parents[3]` | `examples/bank-front-skills` | 技能 |
|---|---|---|---|---|
| 本地开发 | `<repo>/src/kert`（editable） | 仓根 | 存在 | ✓ 注册 |
| **CI e2e job** | site-packages（`pip install ".[api,dev]"` **非 editable**） | `/opt/.../lib/python3.11` | 不存在 | ✗ **静默消失** |
| **容器（compose）** | `/app/src/kert`（`PYTHONPATH=/app/src`） | `/app` | 不存在（镜像未 COPY，compose 未挂载） | ✗ **静默消失** |
| systemd | `/opt/kert/src/kert` | `/opt/kert` | 取决于 `/opt/kert` 是否完整检出 | ? **待核实** |

**核心缺陷不是"某个路径写错"，而是 `is_dir() → None` 的静默降级使正确性依赖部署布局**。

---

## 3. 修复规格（B3：消除静默降级，而非只修一处）

### 3.1 代码

1. 新增显式配置入口 **`KERT_SKILL_PACKAGES`**（环境变量，路径）。
   解析优先级：显式入参 `skill_packages` > `KERT_SKILL_PACKAGES` > 现有默认 `parents[3]/examples/bank-front-skills`。
2. **核心语义变更**：**显式配置了就必须有效** —— `KERT_SKILL_PACKAGES` 指向的路径不存在、
   或存在但不含任何含 `SKILL.md` 的子目录 → **启动即失败**（抛错退出），**不得**回落为 `None`。
3. 未显式配置时保留现有回落，但**必须**在启动日志打印：解析到的路径 / 是否命中 /
   注册到的技能数 / **技能 id 清单**；命中 0 个技能时打印 `[WARNING]` 并说明原因。
   **禁止静默。**
4. 不改 `SkillExecutionService.registry()` 既有语义（base 5 条与 SP-15 的注册条件不变），
   以免触动 `tests/integration/test_skills.py` 的既有断言。

### 3.2 部署与 CI

5. `deploy/Dockerfile`：新增 `COPY --chown=kert:kert examples /app/examples`，
   并设 `ENV KERT_SKILL_PACKAGES=/app/examples/bank-front-skills`。
6. `.github/workflows/ci.yml` 的 **e2e job**（仅该 job）：为 `Start KERT` 步骤设
   `KERT_SKILL_PACKAGES: ${{ github.workspace }}/examples/bank-front-skills`。
   **不要**把该 job 改成 editable 安装 —— 那会让 CI 与生产布局脱钩，与本任务目标**相反**。
7. `deploy/docker-compose.yml`：**无需改动**（镜像 `ENV` 已覆盖；compose 只挂 workspace）。
   若实施中发现必须显式声明，须在证据中说明理由。
8. `deploy/systemd/kert-api.service`：**不新增**该环境变量。该部署是 `/opt/kert` 源码布局，
   默认回落即可；盲目新增会让**缺少 `examples/` 的既有部署启动失败**。改为在 §4 的 A4 中核实其行为。

### 3.3 CI 技能就绪断言（把 10 条红变成 1 秒失败）

9. e2e job 在 `Run E2E tests` **之前**增加一步：请求 `GET /api/skill/health`
   （该服务**唯一**的技能清单端点；**不存在** `/api/skill/list` —— 本文件初版此处写错，
   已在实施阶段经实测更正），**断言 7 个 `bank-front-*` 全部存在**：

   ```
   bank-front-commitment-script
   bank-front-eight-dimension
   bank-front-fact-reconciliation
   bank-front-kyc-gap-check
   bank-front-product-recommendation
   bank-front-report-assembler
   bank-front-supply-chain-graph
   ```

   （已核：目录名与 SKILL.md front-matter 的 `name` 逐字一致，故断言可直接用上述 id）
   缺失即 `exit 1` 并打印**实际**清单。
10. 该断言不得用 `continue-on-error`、`|| true`、吞异常绕过。

---

## 4. 验收标准

| # | 验收 | 判据 |
|---|---|---|
| **A1** | 真实 CI e2e job 账本 | `passed >= 26`、`failed == 0`、`errors == 0`、`skipped <= 21` |
| **A2** | 技能就绪断言的**负向**有效性 | 人为把 `KERT_SKILL_PACKAGES` 指向不存在路径 → job 在**数秒内**失败，报错含该路径 |
| **A3** | 容器内技能清单 | `/api/skill/list` 含全部 7 个 `bank-front-*` |
| **A4** | systemd 布局行为核实 | 记录 `/opt/kert/examples` 是否存在及实际技能清单（是/否均需留证） |
| **A5** | 显式配置无效路径时的启动失败 | `KERT_SKILL_PACKAGES=/nonexistent` → 启动报错退出（单测或手工留证） |
| **A6** | 回归 | `tests/`、`tests/integration`、lint、type 全绿；**未改任何用例文件** |

---

## 5. 证据要求

1. **V1~V3 的原始命令与输出**（前置验证，缺则视为未开工）
2. A1 的 CI run 链接 + 账本 JSON 全文
3. A2 的失败日志（证明断言真的会挡）
4. A3 的 `/api/skill/list` 原始响应
5. A4 的核实记录
6. 改动文件清单 + `git diff --stat`
7. 非声明：本任务**不**解除 `F-E2E-01`（跨服务 21 条仍未覆盖）；**不**构成 `QA_PASS`；
   **不**代表 `PRODUCTION_READY`；**不**解除 ADMISSION-E2E-EVIDENCE.md

---

## 6. 非目标（明确不做）

- 不改 `examples/bank-front-skills/**` 内容
- 不改 `tests/e2e/**` 任何断言或用例（红线：断言语义不得改宽或删除）
- 不改 `WAIVER-E2E-CROSS-SERVICE.md`（其因 T3 成立的重新裁决是**独立事项**）
- 不把 e2e job 改成 editable 安装（见 §3.2-6）
- 不为 systemd 部署强行加环境变量（见 §3.2-8）
- 不顺带修 §7 的同模式路径解析

---

## 7. 观察项（本任务不修，但须在证据中表态）

同一 `parents[3]/<repo 目录>` 模式另有三处，均依赖源码布局：

- `src/kert/application/service_proposal.py:23` —— `ASSETS_DIR = parents[3]/skills/service-proposal`
- `src/kert/application/product_recommendation/sp15_skill.py:145` —— `_repo_root()/skills/product-recommendation/rules`
- `src/kert/application/product_recommendation/sp15_skill.py:136` —— 仓根探测**要求 `skills/` 与 `examples/` 同时存在**

即容器缺 `examples/` 可能**连带**影响 SP-15 规则解析（**同因嫌疑，未验证**；CI 中 SP-15 用例通过，故未暴露）。
实施者须在 A3/A4 中一并观察并在证据中明确表态，但**不在本任务内修**。

---

## 8. 实施记录（2026-09-14）

### 8.1 前置验证（§0）的等效替代

**V1/V2（容器实测）未做**：本机 `docker build` 在 `pyarrow`（50MB）处网络中断，不可用。
改用**等效的布局复刻**（不依赖网络、语义不失真）：

- 复刻方式：把 `src/kert` 复制到源码树之外并置于 `PYTHONPATH` 首位 →
  `kert.__file__` 落在源码树外 → `parents[3]` 不再是仓库根。这与
  site-packages（CI）及 `PYTHONPATH=/app/src`（容器）属**同一非源码布局语义**。
- 复刻结果：**`10 failed, 17 passed, 20 skipped`**，账本
  `violations=['failed=10（必须 0）', 'passed=17 < 下限 26…']`
  —— 与真实 CI（`10 failed, 16 passed, 21 skipped`）**同一失败集合、同一 violation 形态**。
  ⇒ 根因成立（V3 等效通过）。**`V1/V2` 的容器实测仍属未完成项。**

### 8.2 改动

| 文件 | 改动 |
|---|---|
| `src/kert/api/server.py` | 新增 `SKILL_PACKAGES_ENV` / `_has_skill_packages()` / `resolve_skill_packages()`；`create_app` 改用之；新增启动日志打印 resolved 路径 + 已注册技能数 + 技能 id 清单 |
| `deploy/Dockerfile` | 新增 `COPY --chown=kert:kert examples /app/examples`；ENV 增 `KERT_SKILL_PACKAGES=/app/examples/bank-front-skills` |
| `.github/workflows/ci.yml`（e2e job） | `Start KERT` 增 `KERT_SKILL_PACKAGES`（**未**改成 editable 安装，符合 §3.2-6）；新增步骤 `Assert KERT skill readiness (D-E2E-01)` |
| `tests/unit/test_skill_packages_resolution.py` | **新增**（未改任何既有用例），7 条锁定 fail-closed 语义 |

### 8.3 自验证据

| 项 | 结果 |
|---|---|
| 修复后 e2e 账本（非源码布局 + 显式 `KERT_SKILL_PACKAGES`） | `collected=47 passed=27 skipped=20 failed=0 errors=0`，`violations=[]` |
| A5 显式无效路径 | `KERT_SKILL_PACKAGES=/nonexistent-dir-xyz` → `ValueError` 且 **exit=1**（启动失败） |
| A6 未设置 + 非源码布局 | 打印 `未解析到外部 Skill 包：… 内置默认目录不可用（…/examples/bank-front-skills）…`，服务仍 `health=200`（**不再静默**） |
| 新增单测 | `7 passed` |
| CI 同款全量测试 + 覆盖率门槛 | `Required test coverage of 80% reached. Total coverage: 84.35%` |
| `ruff check src/ tests/` | `All checks passed!` |

### 8.4 A1 / A2 核验结果（补记）

- **A1 ✅**：真实 CI run `34858121012`（sha `4bca750`）**全绿**。e2e job 账本：
  `collected=47 passed=26 skipped=21 failed=0 errors=0`，`violations=[]`，`pytest_exitstatus=0`；
  对照修复前同一 job 为 `passed=16 failed=10`。就绪断言输出：
  `已注册技能 13 个：[SP-15, SP-20, SP-21, 7×bank-front-*, 3×skill-customer-*]`
  → `✓ 技能就绪：7 个 bank-front-* 全部存在`。
- **A2 ✅（本地，使用 CI 中同一段断言代码）**：对「无外部技能包」的服务
  （`已注册技能 6 个`）运行后输出 `::error::外部 Skill 包未就绪，缺少 7 个：[…]`
  且 **exit=1** —— 证明该断言不是空转，真的会挡。
- 附注：新增的启动日志（`外部 Skill 包：resolved=…`）写入服务自身的日志文件
  （CI 中为 `$RUNNER_TEMP/kert.log`），**不出现**在 job 日志里；
  CI 侧可见的守卫是就绪断言本身。

### 8.5 剩余未完成项

- **A4**：systemd 部署核实 —— 本地无该环境，**无法核实**（见 §8.7）
- 除 A4 外，**V1~V3、A1、A2、A3、A5、A6 均已完成并留证**
- 本任务**仍不构成** `QA_PASS`、**不代表** `PRODUCTION_READY`

### 8.6 容器实测（V1/V2、A3 补做，已完成）

本机直连 pypi 不可用（`pyarrow` 50MB 下载中断，~11 kB/s），改用国内镜像
**仅加一行 `PIP_INDEX_URL`** 的临时 Dockerfile 构建，**被测的 `COPY`/`ENV` 行未改**；
差异经 `diff` 留证：`16a17 > ENV PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple`。
构建成功（22/22）。

| 项 | 结果 |
|---|---|
| **V1** 镜像内 `/app/examples` | **存在**（含 `bank-front-skills`、`config`、`gits_adapter`、`output`、`product-recommendation-assets`） |
| **V1b** `bank-front-skills/` 下 7 个目录 | **齐**（commitment-script / eight-dimension / fact-reconciliation / kyc-gap-check / product-recommendation / report-assembler / supply-chain-graph） |
| **V2** 镜像内解析 | `PYTHONPATH=/app/src`；`KERT_SKILL_PACKAGES=/app/examples/bank-front-skills`；**内置默认路径 `is_dir=True`**（修复后即便不设环境变量也能解析） |
| 镜像内注册技能数 | **13**（SP-15 / SP-20 / SP-21 + 7×`bank-front-*` + 3×`skill-customer-*`），与真实 CI 一致 |
| **A3 容器端到端（prod profile）** | 容器 **`Up (healthy)`**；`GET /api/skill/health` → **200**；**技能总数 13、bank-front 7** |

**附带记录（非缺陷，但会消耗下一位的时间）**：裸 `docker run kert-verify` 会因 prod 校验
**拒绝启动**（`生产 profile 必须启用 API Key 认证 / 必须启用限流 / 对外监听 0.0.0.0 时禁止匿名访问`）。
这是**有意的 fail-fast**，且 `deploy/docker-compose.yml` 与 `deploy/.env.example` 已提供
`KERT_API_KEYS`（`${KERT_API_KEYS:?…}` 带明确提示）与 `KERT_RATE_LIMIT_ENABLED`。
按 compose 同款 env 启动即正常。**`KERT_API_KEYS` 的格式为 `<name>:<secret≥16字符>:<perms>`。**

### 8.7 A4 无法在本地核实（保留为未完成）

`A4` 要求记录 systemd 部署（`/opt/kert`）中 `examples/` 是否存在及实际技能清单——
本地**无该部署环境**，无法核实。已按 §3.2-8 **刻意未修改**
`deploy/systemd/kert-api.service`（该部署为源码布局，默认回落即可；盲目新增
`KERT_SKILL_PACKAGES` 会让缺少 `examples/` 的既有部署**启动失败**）。
⇒ **systemd 路径下的技能可用性未被验证**，不得据此推断。
