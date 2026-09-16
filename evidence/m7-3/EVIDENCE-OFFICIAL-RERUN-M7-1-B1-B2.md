# 官方复跑证据 —— M7.1 B-1 / B-2②（窗口：`1.6.0` 落地后，2026-09-16）

> **用途**：TL 指定的**最终证据**（§11.4 + E-9）。本文件为**新增文件**；本片**未改任何既有文件**
> （`skills.py` 未动、测试文件未动、`specs/**` 未动、`evidence/m7-3/**` 下他人文件未动）。

---

## 1. 窗口、守卫与归因前置

```text
复跑时刻（跑前守卫）: 2026-09-16T15:55:17+08:00
HEAD（跑前）        : 1bc5972a19b221a7cf7fa3f2baa4cb5db722c913
HEAD（收工）        : 4d85b4b3cd9743dc08126ec9da49df5e0a606918   ← 窗口内前移（见下）
环境口径            : .venv = Python 3.12.8 / pytest 9.1.1
                      pyproject `addopts = ["-q", "-m", "not perf"]` ⇒ **不得再显式加 `-q`**（-qq 会抑制汇总行）
```

**D-13 守卫（跑前/跑后 `skills.py` sha256）—— PASS（无回写）**

```text
跑前: bcb1ecc4194c27944958125d013733875334bbf7f154515f3a8cea0465e11e9b  src/kert/application/skills.py
跑后: bcb1ecc4194c27944958125d013733875334bbf7f154515f3a8cea0465e11e9b  src/kert/application/skills.py
⇒ 两次一致 ⇒ 本次跑数**有效**（未因外部写入者作废）
另: src/kert/domain/knowledge_source.py = 01ee53d825585e2d2dba6d6e02255387151fceb6598d71ab1df49bb69436d955（未动）
```

**窗口内 HEAD 前移归因（5 个提交，**全 docs**）**

```text
1bc5972..4d85b4b3:
  4d85b4b docs(m7): E-5 补 HEAD 记法消歧（HEAD 值 = blob sha256 / HEAD commit = 提交 id…）
  77a55c9 docs(m7): D-16 补 ③ 类核验（TL 两处预期落空自我更正 + 机制证据）+ 修复轮口径；登记 D-20
  85539ff docs(m7): 新增 E-10（数字必须可复现：wc/计数禁止净增量反推）+ D-8 指向 E-10
  60c4fff docs(m7): D-16 记 §3 交付（含 2 处跨度变更）+ 新增「行号只在清单维护」规则；D-8 补数字纪律
  79958d7 docs(m7): 撤回 D-16 的「N−5」修法（改按 §3 行级映射）+ 补第三类（指向已删内容 ⇒ 结案标注）

变更面: 仅 evidence/m7-3/DECISION_SHEET_M7_CLOSURE.md（5 insertions / 3 deletions）
        git diff --numstat 1bc5972 4d85b4b3 -- src tests specs  ⇒ **空**
skills.py 内容三处一致: 1bc5972 = 4d85b4b3 = 工作区 = bcb1ecc4…
⇒ **窗口内前移为纯 docs，不影响本次跑数**
```

**完整 `git status --porcelain`（跑前原文，8 行，逐字）**

```text
 M .understandignore
 M evidence/m7-3/INVENTORY_V1_LINE_REFERENCES.md
 M src/kert/application/provision.py
 M src/kert/cli/main.py
 M tests/unit/test_provision.py
?? examples/bank-front-knowledge-maps/90_control/schema/activations/
?? src/kert/domain/activation_contract.py
?? tests/unit/test_activation_contract.py
```

**声明（第三方在途，均非本方产物）**：`src/kert/application/provision.py`、`src/kert/cli/main.py`、
`tests/unit/test_provision.py`（第三方批次，**未提交**）、`src/kert/domain/activation_contract.py`、
`tests/unit/test_activation_contract.py`、`examples/.../schema/activations/`（第三方，**未跟踪**）、
`.understandignore`、`evidence/m7-3/INVENTORY_V1_LINE_REFERENCES.md`（c20 侧，M）。

---

## 2. 四目录原始计数与退出码（**分行**，未经管道取 rc）

**命令形态（本片口径，≥ E-8）**：

```bash
cd /home/szf/dev/Leibniz-KERT
.venv/bin/python -m pytest tests/unit        > /tmp/m71b2_off_unit.txt        2>&1; rc_unit=$?
.venv/bin/python -m pytest tests/integration > /tmp/m71b2_off_integration.txt 2>&1; rc_integration=$?
.venv/bin/python -m pytest tests/contract    > /tmp/m71b2_off_contract.txt    2>&1; rc_contract=$?
.venv/bin/python -m pytest tests/recovery    > /tmp/m71b2_off_recovery.txt    2>&1; rc_recovery=$?
```

```text
tests/unit         → 3 failed, 976 passed, 1 warning in 16.23s              rc=1
tests/integration  → 479 passed, 1 xfailed, 1 warning in 138.02s (0:02:18)  rc=0
tests/contract     → 53 passed in 0.13s                                     rc=0
tests/recovery     → 18 passed in 7.35s                                     rc=0
```

> 未经管道 ⇒ `rc` 为 pytest 进程**直接退出码**（非 `tail` 的 0）；命令中**未**显式加 `-q`
> （`addopts` 已含 `-q`，叠加成 `-qq` 会连汇总行一起抑制）。

---

## 3. 与 TL/c20 预期对账（预期值**不是**要我凑的目标）

| 目录 | 本次实测（权威） | TL 给的预期 | 一致 |
|---|---|---|---|
| unit | **3 failed, 976 passed, rc=1** | 972 passed + 1 skipped, EXIT=0 | **✗** |
| integration | **479 passed, 1 xfailed, rc=0** | 479 passed + 1 xfailed, EXIT=0 | ✓ |
| contract | **53 passed, rc=0** | 53 passed, EXIT=0 | ✓ |
| recovery | **18 passed, rc=0** | 18 passed, EXIT=0 | ✓ |

**⇒ 按规则「以我的为准」。差异只在 unit，归因分三层（均为实测，不猜）：**

**(a) 那 3 条 `test_provision_cli` 红灯在本树**仍然存在**（未消失）**

```text
HEAD 基线红集（§10.2/§10.7）: test_provision_cli.py::test_apply_then_idempotent_rerun
                              test_provision_cli.py::test_json_output_follows_standard_envelope
                              test_provision_cli.py::test_init_flag_initializes_fresh_volume_then_provisions
本次实测红集（逐条 node id）: 同上 3 条，**逐条一致**
```

- `tests/unit/test_provision_cli.py` 是**提交态**（`git status` 对该文件为空），sha256 = `8c77d7f70497ff706531143b770c27bed458b0b4fa59d012512e6d8b4342ccf9`；
- 它仍断言 **6**（`:53 assert "新建 6 / 覆盖 0 / 未变 0"`、`:66 counts["CREATED"] == 6`、`:68 len(items) == 6`），
  而 `src/kert/application/provision.py`（**第三方未提交批**）已把供给面扩到 **8 条目** ⇒ `assert 8 == 6`；
- ⇒ 归因 = **"改实现未同步断言"**，**baseline/第三方**，**非 B-2② 变化**（本包未触碰该文件与该实现）。
- ⇒ 与 TL 消息中"那 3 条红灯**现已不存在**"**不符**：在本工作树里**仍红**；若 c20 测得 EXIT=0，
  其树必为该批**已同步断言**（或另一棵树）。

**(b) 采集规模差 6（本树 979 vs 记 973）—— 本树**结构上不可能**出现 "1 skipped"**

```text
本树采集总数：979 tests collected   （= 3 failed + 976 passed，逐项对得上）
其中来自**未跟踪**文件 `tests/unit/test_activation_contract.py` 的 = 44 条（该文件 clean HEAD 检出时不存在）
tests/unit 内 `skipif` / `pytest.mark.skip` 命中数 = 0
⇒ 本树 `tests/unit` **没有任何可跳过的用例** ⇒ 记数中的 "1 skipped" **在本树无来源**
```

⇒ 结论：c20/TL 的 `972 passed + 1 skipped`（合计 973）来自**另一棵树或另一条命令**，
**本树无法复现**。我不会反向凑数。**闭环所需**：c20 的 **unit 跑精确命令 + 该次树 sha**；
或授权我另开**干净 worktree** 复算（属写操作，须 TL 批准，我不擅自执行）。

**(c) 若做"干净 HEAD 复算"，必须扣掉 44**：未跟踪的 `test_activation_contract.py` 贡献 44 条
（且它按 RULES.md 用真实文件、含 fail-closed 全覆盖）；不声明这一点，"干净树 vs 本树"的比较会直接错位。

---

## 4. 红集三分类（基线 vs 本次）

```text
SAME              = 3
ONLY_IN_BASELINE  = 0     （TL 曾预期"消失的 3 条"归此类 —— 实测**未消失**）
ONLY_IN_CURRENT   = 0
⇒ 红集**逐条一致**：既无新增红灯，也无消失红灯。"不得新增红灯"不变量 **成立**。
```

---

## 5. node-id 级三分类 diff（枚举域；基线 = 预跑探针 `/tmp/m71b_probe_run1.txt`）

**提取口径**：取探针输出的**分析段**（`第二片-B 影响面实跑测量结果` 起），
`grep -oE "tests/[^ ]+"` → `sort -u`；基线与现行同一口径。

```text
去重 node id 数      : 基线 68 / A 69 / B 70
去重「用例函数」数    : 基线 62 / A 63 / B 64     （忽略参数化）
SAME(交集)           = 61
ONLY_IN_BASELINE     = 7
ONLY_IN_CURRENT      = 8
```

**ONLY_IN_BASELINE（7）—— 全部可归因，无用例"消失"**

```text
6 条 = B-2② **重命名的旧名**（旧名今日零命中：grep 全仓 = 0）:
  tests/unit/test_skills_capability_swap_guards.py::test_declaration_absent_is_visible_but_never_refused
  tests/unit/test_skills_capability_swap_guards.py::test_declaration_invalid_is_visible_but_never_refused
  tests/unit/test_skills_capability_swap_guards.py::test_unavailable_code_differs_from_absent
  tests/integration/test_skills_capability_swap.py::test_gamma_declaration_absent_falls_back_to_literal
  tests/integration/test_skills_capability_swap.py::test_gamma_prime_absent_and_unavailable
  tests/integration/test_skills_capability_swap.py::test_three_declaration_forms_have_distinct_codes_and_no_refusal
1 条 = **两跑归属竞态**（A 跑缺席、B 跑出现）⇒ 按 **R-A** 归 **E**（不得计入 A）:
  tests/integration/test_persistent_jobs.py::TestPersistentAsyncExecution::test_queue_stats_reflects_enqueued
```

**ONLY_IN_CURRENT（8）—— 同样全部可归因**

```text
6 条 = 上述 6 条的**新名**（B-2② 的六条翻转用例，与 §11.3「实际 6」逐条对应）。
1 条 = **B-1 期新增**用例，晚于基线探针（引入提交 c073c93，"B-1 技能读取切换到声明驱动"）:
  tests/unit/test_skills_capability_swap_guards.py::test_legacy_reader_contract_is_unchanged
1 条 = **用例在两棵树都在**，差异**纯属探针归属**（非用例增删）:
  tests/integration/test_prod_async_guard.py::TestProductionRequiresRuntimeStore::test_profile_read_from_env
  （`git show 43b02fa9:tests/integration/test_prod_async_guard.py | grep -c "def test_profile_read_from_env"` = 1
    ⇒ 基线树同样存在该用例）
```

⇒ 三分类**无未归因项**；B-2② 的净效应 = **6 条重命名**（旧 6 消失 / 新 6 出现），
外加 B-1 期 1 条新增与 1 条探针归属差、1 条竞态归 E。

---

## 6. 44 条枚举两跑（R-A / R-B / R-E）

```text
探针（原版，报数基准）: /tmp/m71b_impact_probe.py   sha256 d73ce3c61f0f61e7a7f3a0379ca694040b2d8e733fd98aa8324e0ee9b776639b
完整命令行（可原样重跑）: cd /home/szf/dev/Leibniz-KERT && .venv/bin/python /tmp/m71b_impact_probe.py
两跑输出: /tmp/m71b2_probe_A.txt 、/tmp/m71b2_probe_B.txt
合并进程汇总行: A = 3 failed, 1526 passed, 1 xfailed in 157.03s
                B = 3 failed, 1526 passed, 1 xfailed in 158.93s
[a] 执行了将被接线技能（_route_plan）的用例数 = 63（两跑一致）
[b] 执行**未接线**读取路径（_run_supply_chain）的用例数 = 3（不变 ⇒ D 组未接线）
```

**两跑逐字 `diff` —— 仅两处**

```text
1) 耗时行（157.03s vs 158.93s，无意义）
2) 异步/线程 group 的 node id **归属互换**:
   A: …test_thread_mode_without_store      取数结果=['HITS=0']  投影存在={False}
   B: …test_queue_stats_reflects_enqueued  取数结果=['HITS=0']  投影存在={False}
```

**R-A 交集口径（本次裁定）**

```text
A∩B = 69 ；仅 A = ∅ ；仅 B = 1（test_queue_stats_reflects_enqueued）
⇒ A 组成员必须**两跑都命中**；该条仅 B 命中 ⇒ 归 **E**（"需复跑确认"），**不计入 A**。
```

**R-E 机制说明（与 §9.4 记录一致，本次复现）**：漂移**只**发生在异步/线程路径的**node id 归属**
（同一 `_route_plan` 命中数 63、同一 `HITS=0`、同一 `投影存在=False`），
**不是**树状态或行为差异；故冻结态**以原版探针为准**（R-E），且 A 组取**两跑交集**（R-A）。

---

## 7. 复现命令清单（可原样重跑）

```bash
cd /home/szf/dev/Leibniz-KERT
date -Is
git rev-parse HEAD
sha256sum src/kert/application/skills.py src/kert/domain/knowledge_source.py
git status --porcelain

.venv/bin/python -V                       # Python 3.12.8
.venv/bin/python -m pytest --version      # pytest 9.1.1

.venv/bin/python -m pytest tests/unit        > /tmp/m71b2_off_unit.txt        2>&1; echo "rc=$?"
.venv/bin/python -m pytest tests/integration > /tmp/m71b2_off_integration.txt 2>&1; echo "rc=$?"
.venv/bin/python -m pytest tests/contract    > /tmp/m71b2_off_contract.txt    2>&1; echo "rc=$?"
.venv/bin/python -m pytest tests/recovery    > /tmp/m71b2_off_recovery.txt    2>&1; echo "rc=$?"

.venv/bin/python /tmp/m71b_impact_probe.py   > /tmp/m71b2_probe_A.txt 2>&1
.venv/bin/python /tmp/m71b_impact_probe.py   > /tmp/m71b2_probe_B.txt 2>&1
diff /tmp/m71b2_probe_A.txt /tmp/m71b2_probe_B.txt

# 三分类（基线/现行）
for f in /tmp/m71b_probe_run1 /tmp/m71b2_probe_A /tmp/m71b2_probe_B; do
  sed -n '31,$p' $f.txt | grep -oE "tests/[^ ]+" | sed "s/[,)]*\$//" | sort -u > $f.nodes
done
comm -12 /tmp/m71b_probe_run1.nodes /tmp/m71b2_probe_A.nodes | wc -l    # SAME = 61
comm -23 /tmp/m71b_probe_run1.nodes /tmp/m71b2_probe_A.nodes            # ONLY_IN_BASELINE = 7
comm -13 /tmp/m71b_probe_run1.nodes /tmp/m71b2_probe_A.nodes            # ONLY_IN_CURRENT = 8
comm -12 /tmp/m71b2_probe_A.nodes   /tmp/m71b2_probe_B.nodes | wc -l    # A∩B = 69
```

**行号基准声明（D-8）**：本文件引用的 `skills.py` 行号基准 = `bcb1ecc4…`（1227 行，入库 `470adfb`）；
`knowledge_source.py` 基准 = `01ee53d8…`（992 行）；**符号名 / node id 为权威锚点，行号仅定位辅助**。
本文件**不含** `specs:NNN` / `v1:NNN` 引用。

---

## 8. 结论与待办

1. **不变量成立**：四目录中 integration/contract/recovery 全绿；unit 红集 = **恰好 3 条**且 node id 与基线**逐条一致**
   ⇒ **"不得新增红灯"成立**（`ONLY_IN_CURRENT = 0`）。
2. **B-2② 净效应 = 6 条重命名**（三分类两侧各 6 条、逐条对应；旧名零命中）—— 无行为性新增红灯。
3. **与 TL 预期的两处不一致已归因**：(a) 3 条 `test_provision_cli` 红灯**仍在**（第三方未同步断言，非我方）；
   (b) unit 采集规模差 6 且本树**无任何 skip 标记** ⇒ 记录值来自另一树/另一命令，**本树不可复现**，
   闭环需 c20 的精确命令与树 sha（或 TL 授权的干净 worktree 复算）。
4. **待办（本文件可直接进 §11 体系）**：等 TL 对第 2/3 点的裁定；如需我再跑，
   仍按 E-9（跑前/跑后 `skills.py` sha 守卫）。

---

## 9. 干净树复算（worktree，TL 授权）与三口径**算术闭合**

> **性质**：本节是 TL 批准的 **append（证据落盘）** —— 增加的是**本轮实测事实**，
> 不是"为追 sha 而改文本"（防回环约定的判据）。

### 9.1 E-11 环境身份（缺一即标"未验证"）

```text
解释器   : /home/szf/dev/Leibniz-KERT/.venv/bin/python   →  Python 3.12.8
pytest   : 9.1.1
typer    : 0.27.1（`import typer` 成功 ⇒ 模块级 `importorskip` **不触发**）
addopts  : ["-q", "-m", "not perf"]（pyproject:45）
命令形态 : PYTHONPATH=$WT/src .venv/bin/python -m pytest tests/<dir> > /tmp/m71b2_wt_<dir>.txt 2>&1 ; rc=$?
```

> ⚠ **复现注意（TL 本轮亲踩）**：`addopts` **已含 `-q`**；**再显式加 `-q` 会叠成 `-qq`，
> 把汇总行一起吞掉** ⇒ 报采集数时会得到空值。命令**照原样跑**即可。

### 9.2 worktree 创建 / 移除（只读主树；不触碰任何 uncommitted 内容）

```bash
git worktree add --detach /tmp/m71b2_clean_wt 4d85b4b3cd9743dc08126ec9da49df5e0a606918
cd /tmp/m71b2_clean_wt && git rev-parse HEAD && git status --porcelain    # 4d85b4b3… ；status **clean**
git worktree remove /tmp/m71b2_clean_wt && git worktree list              # 移除后仅剩主树
```

**硬前置 (i) 解释器口径**：`.venv/bin/python -V` = 3.12.8 且 `import typer` 成功
（**若失败 ⇒ `test_provision_cli.py` 会静默整模块 skip，产生"假干净数" ⇒ 应报「环境不可用」，不出数**）。

**硬前置 (ii) 导入源断言**（防 editable 安装 / PYTHONPATH 指向主树）：

```bash
PYTHONPATH=/tmp/m71b2_clean_wt/src .venv/bin/python -c \
  "import os,kert; p=os.path.abspath(kert.__file__); assert p.startswith('/tmp/m71b2_clean_wt/'); print(p)"
# → /tmp/m71b2_clean_wt/src/kert/__init__.py    ⇒ PASS
```

> **要点**：`pyproject` **未**配置 `pythonpath` ⇒ 必须**显式** `PYTHONPATH=<wt>/src`；
> 否则 pytest 会跑到 venv editable 安装指向的**主树**代码（跑的不是被测树）。

### 9.3 worktree 四目录（提交态 `4d85b4b3`；原始计数 + rc，分行）

```text
tests/unit         → 931 passed, 1 warning in 16.14s               rc=0   （0 failed / 0 skipped）
tests/integration  → 479 passed, 1 xfailed, 1 warning in 137.22s   rc=0
tests/contract     → 53 passed in 0.13s                            rc=0
tests/recovery     → 18 passed in 7.48s                            rc=0
```

⇒ 与 TL 预期一致：**那 3 条 `test_provision_cli` 红在提交态消失**（unit `rc=0`）。

### 9.4 三口径**算术闭合**（全部实测，无推断）

```text
主树（脏树：含未提交第三方批 + 未跟踪文件）   collected = 979（= 3 failed + 976 passed）
c20 口径（system python3，**无 typer**）      collected = 973（= 972 passed + 1 skipped）
worktree（提交态，干净）                      collected = 931（全绿）

(1) 主树 979 − worktree 931 = 48 = **44 + 4**
    44 = 未跟踪 `tests/unit/test_activation_contract.py`（仅主树存在）
     4 = **未提交**的 `tests/unit/test_provision.py` 比提交态多 4 条
         · def 级  ：工作区 **21** vs 提交态 **17**（TL 已独立复核）
         · 采集级  ：主树 `test_provision.py: 23` vs worktree `test_provision.py: 19`

(2) c20 的 973 = **979 − 7 + 1**
    7 = 提交态 `tests/unit/test_provision_cli.py` 的用例数
        （该文件 `:18` 为**模块级** `pytest.importorskip("typer")`）
        ⇒ typer 缺失时**整模块不采集**（−7），并记 **1** 条模块 skip 条目（+1）
    972 = 976 − 4（该模块内 4 条绿测随模块一起不再采集；模块内另 3 条即上述已知红测）
```

⇒ **三口径互相自洽、逐项闭合** —— 不再需要假设"谁数错了"。

### 9.5 卫生

```text
worktree ：已 `git worktree remove`；`git worktree list` 仅剩主树
主树      ：本节写作前 `git status` 与我跑前一致（无我侧新改动）；`skills.py` = bcb1ecc4… **未变**
```

**行号基准（D-8）**：本节引用的 `test_provision_cli.py:18` 基准 = 提交 `4d85b4b3` 版（该文件未被改）。
