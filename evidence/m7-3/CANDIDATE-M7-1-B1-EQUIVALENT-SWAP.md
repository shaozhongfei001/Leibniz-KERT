# CANDIDATE：M7.1-B1 等价替换实现方案（真实能力适配器 **不改变语义**）

```text
DOC_ID   : CANDIDATE-M7-1-B1-EQUIVALENT-SWAP
VERSION  : v1.5（2026-09-16：TL 加固 R-A…R-F + 冻结**改判** —— ① A 组取**两跑交集**（R-A）
           ② 冻结态**以原版探针为准**、精简版仅交叉验证并写明差异机制（R-E）
           ③ 报数清单补 **(g) 探针完整命令行 / (h) 版本口径**（R-F）
           ④ 新增 **§9 预跑记录（非冻结态）**：预跑不写入 §6 作为冻结证据；含四项归因前置、
           四目录原始计数、3 条失败归因（第三方在途，正是改判实证）、44 条枚举与 (γ) 复核
           ⑤ 修正 §6 引用编号（§10 → §9））
           v1.4（并入 TL 四点补充 —— ① `inspect.signature` 等式守卫（守卫 5 / 变异 V14）
           ② 具名依赖 **D-B1-1**（scope 决策建立在地图并集==绑定集之上，该用例改动须重审）
           ③ **语义噪声**写明（并集 vs 单任务子集；禁暗示为"计划资产"；资产 ID 不入 message）
           ④ plan-scoped 留痕登记为 **B-2 候选**；另加 §6 的**冻结归因前置**）
           v1.3：并入 TL 的 Q1-Q5 定稿（`_load_ki_from_declaration`、签名一致、逐资产留痕 T6、
           Q4 守卫白名单精确 + fail-closed、Q5 先冻结态复测；变异 V12/V13 与 R-1 停机条件）
           v1.2：对齐 DECISION_SHEET C-3（两字段须同期追加 canonical schema；禁用"只靠 additionalProperties 兜底"）
           v1.1：新增**等价前提硬规则 E0**、回落用例 §2.7、变异 V11、白名单改为"新文件 only"
TASK_ID  : M7-1-B1-PLAN (前置件；**非实施授权**)
REPO     : Leibniz-KERT
性质     : 只读设计方案（**不改任何代码**）；供 TL 决定是否派工实施
依据     : evidence/m7-3/TL_DECISION_M7-1-FIRST-SLICE.md（2-A 授权与边界）
           evidence/m7-3/IMPACT-ANALYSIS-M7-1-B.md（实跑影响面 + R-1/R-2/R-6 裁定输入）
           evidence/m7-3/CANDIDATE-M7-1-KNOWLEDGE-SOURCE.md（能力模型与解析链）
TL 裁定  : **R-1 不授权**（A 组 29 条属已声明业务语义 ⇒ 登记待 Owner；B-1 严禁触碰）
           **R-2 驳回**升格（`required` 不参与运行时判定）
           **R-3 本阶段不授权**改 e2e（登记为 B-2 交付项；牵动 CI 供给 ⇒ 流水线决策）
           **R-6 采纳**（拆 B-1/B-2），**且按硬规则 E0 收紧后成立**
落盘指针 : evidence/m7-3/DECISION_SHEET_M7_CLOSURE.md —— **C-1a**（B-1 等价替换 + 硬规则 E0 + 回落用例要求）、
           **C-1b**（B-2 两处语义升级，待 Owner）、**C-2**（`required` 不升格 + 机械核对要求）、
           **C-3**（两个新 trace 字段须**同期**追加 canonical schema，待 Contract Owner 追认）、
           **D-5**（供给面 5→6 口径）、**D-6**（e2e 假绿归 B-2）、**D-7**（`_run_supply_chain` 一致性债）、
           **D-8**（`server.py` 引用须"函数名 + 行号"双锚）
行号基准 : 2026-09-16 工作区快照（含 c20 在途改动 `server.py` +29 行）；本文件一律用「函数名 + 行号」双锚
```

**非声明**：本文件不是实施授权、不是 Owner 裁决、不是合同修订、不代表 `PRODUCTION_RELEASE_GATE` 变化。
**边界**：只新增本文件；未改 `application/skills.py`、`api/**`、合同、`deploy/**`、任何测试；未 commit、未 push。

---

## 0. 目标与成功判据

**目标**：把三个已接线技能（`skill-customer-outreach-script` / `-meeting-script` / `-previsit-report`）的**取数实现**从"`CustomerKnowledgeProvider.ki_map` 直接读投影"替换为"**经控制面声明的能力**（`KS-CUSTOMER-KI-PARQUET`）读取"，且**可观测行为完全不变**。

**成功判据（唯一）**：`tests/unit + tests/integration + tests/contract + tests/recovery` 全量**无新增失败**；特别是《影响面分析》A 组 **29 条一条都不改**（B 组 9 条、C 组 3 条同样不改）。

> ### ⛔ 等价前提**硬规则 E0**（TL 收紧，B-1 成立的必要条件）
>
> **B-1 中「声明缺失 ⇒ 拒绝」不得生效：声明缺失必须回落今日的字面量读取路径，行为与接线前逐字一致，不拒绝、不报错。**
> 若 B-1 的实现做不到这条，则它**不是 B-1**，须**整体退回 B-2 待裁**。
> 理由（TL）："44 条里没有'计划放行 + 声明缺失'"只说明**今天没人测**，不等于改了没关系；而 2-A 之前供给过的工作区（或手工配置的工作区）**没有**该声明，这种组合**在真实部署里可达**。
> ⇒ "缺失即拒绝"与"未绑定即拒绝"**整体归 B-2**；B-1 只换**读取实现**。

把该判据拆成三条可独立验证的子命题——**这正是 B-1 能做到"0 变化"的原因**：

| 子命题 | 含义 | 覆盖用例 |
|---|---|---|
| **(α) 有声明 + 有投影** | 新旧两条路径读出的 KI 映射**逐键逐值等价** | B 组 9 条（`svc_ck` → `ws_seeded`） |
| **(β) 有声明 + 无投影** | 行为与今天**逐项相同**：技能 `ok`、`phase="kert"/"skipped"` 仍在、逐条 KI 仍 `skipped`、**不出现任何 KI 级拒绝**；仅"多一条留痕条目" | A 组 29 条（`svc` → `ws_provisioned`） |
| **(γ) 声明缺失 + 任意投影** | **回落**字面量读取路径；技能照常完成，**无任何拒绝**；仅"多一条具名留痕条目" | **今天完全没测** ⇒ §2.7 **新增**用例钉住（TL 明确要求） |

> 三条子命题的夹具来源已核实：`tests/integration/test_skills.py:34`（`svc` = 已供给控制面、**未**种客户知识）与 `:52`（`svc_ck` = 已供给 + 已种客户知识，`:41-49`）。A/B 分组不是估计，是该两个夹具的必然结果；(γ) 由"供给后删除声明文件"构造（§2.7）。

---

## 1. 设计

### 1.1 接线点：**新增**方法，**不动** `_load_ki`

`SkillExecutionService._load_ki`（`skills.py:504-521`）被 **4 处**调用：

```text
skills.py:720  _run_outreach        ← 已接线技能（B-1 目标）
skills.py:753  _run_meeting         ← 已接线技能（B-1 目标）
skills.py:786  _run_previsit        ← 已接线技能（B-1 目标）
skills.py:820  _run_supply_chain    ← **未接线**（技能包 bank-front-supply-chain-graph，O-6 范围）
```

⇒ **若改 `_load_ki` 本体，`_run_supply_chain` 会被一并接线**，直接威胁 D 组 3 条用例（§5.1）。故：

- **新增** `SkillExecutionService._load_ki_from_declaration(customer_id: str, trace: list[dict]) -> dict`
  —— **命名已定稿（Q1）**；**签名与 `_load_ki` 完全一致（同参同返回）**，使替换是**机械的**、等价性可判（Q1-i）；
- 由 `_run_outreach` / `_run_meeting` / `_run_previsit` 三处**显式调用**（把各自第 720/753/786 行的 `self._load_ki(...)` 机械替换为 `self._load_ki_from_declaration(...)`）；
- `_load_ki`（`:504-521`）与其唯一剩余调用方 `_run_supply_chain`（`:818-823`）**保持一字不改**；
- **前缀 `_load_ki` 是刻意的（Q1-ii）**：使"所有 KI 读取点"可用**一个前缀 grep 枚举**，并由 §4.1 的守卫**钉住集合恰为 {`_load_ki`, `_load_ki_from_declaration`}**。

#### 1.1.1 Q1-i（签名一致）的**必然推论**：方法**不接计划参数**，留痕范围 = **声明中的绑定集合**

签名必须与 `_load_ki` 一致 ⇒ **不能**把 `plan` 传进来（否则签名不同）。因此：

- 该方法从**声明自身的 `bindings`** 取得 assetRefId 集合（"哪些资产可由声明驱动读取"），逐条解析并产出留痕；
- 在**受控工作区**上，声明绑定集恰为 `KI-009 + KI-FRONT-001…006`（7 条），**与三张地图 `assetRefs` 的并集完全相同**（该等式已由 `tests/unit/test_knowledge_source.py::test_declaration_covers_all_map_asset_refs` 机械核对）⇒ 与"按计划资产"在受控面上**逐条一致**；
- **副作用（正向）**：新方法完全不读计划 ⇒ `_route_plan` / `_plan_assets` 的行为**一寸不碰**，"计划相关 0 变化"成为结构性事实。
- ⚠ **如需改为"按计划资产"留痕，则必须传 `plan` ⇒ 签名与 `_load_ki` 不同 ⇒ 与 Q1-i 冲突**。此处按 Q1-i 优先执行（声明绑定集）；若你要求按计划资产，请指出，我改写并同步调整签名约束。

**TL 已于 2026-09-16 确认 Q1-i**，理由三条：① B-1 的全部价值在"**可证的等价**"，签名逐字一致 ⇒ 替换是**纯代入**，只需证行为、不需证依赖变化；② 传 `plan` 会把"计划读取"引入一个此前**完全不读计划**的方法 ⇒ 等价性论证 / Q4 守卫 / 变异点都要重做，风险与收益不成比例；③ 受控工作区上 scope=bindings 与 scope=map-union **相等**（TL 已独立核实该等式为**双向等式**，非单向包含）。

#### 1.1.2 **具名依赖 D-B1-1**（本 scope 决策的成立前提）

| 依赖 ID | 依赖对象 | 若被破坏的后果 |
|---|---|---|
| **D-B1-1** | `tests/unit/test_knowledge_source.py:228-240` 的 `test_declaration_covers_all_map_asset_refs`（断言 **声明 `bindings` 集合 == 三张地图 `assetRefs` 的并集**，双向等式 + 诊断信息） | **本 scope 决策必须重审**：scope=bindings 之所以等价于"按计划资产"，**完全**建立在该等式之上；一旦该用例被**放宽、改写或移除**，B-1 的"不读计划"就不再被证明等价，须重新评估签名约束（可能与 Q1-i 冲突） |

⇒ 因此该用例**不是普通单测**，而是 B-1 的**具名依赖**；改动它需与 B-1 的 scope 决策一并评审。

#### 1.1.3 **必须写明的语义噪声**（TL 核实后的推论，不是缺陷但是可被误读处）

scope=bindings 取的是**并集**，而**单个任务**的计划资产只是它的**子集** ⇒ 回落/留痕会列出**多于该任务所需**的资产。

**具体例子**：`KM-CORP-RM-OUTREACH` 只声明 **3 条**（`KI-009` / `KI-FRONT-004` / `KI-FRONT-006`），而 (γ) 回落留痕按声明绑定集会列出 **7 条** ⇒ 读 trace 的人**可能误读**为"该任务需要这 7 条"。

**三条强制要求（B-1 实现时必须满足）**：

1. **显式写明**：本节的例子必须出现在实现与该模块的 docstring 里（避免下一个人重新推理一遍）；
2. **措辞与字段不得暗示它们是"计划资产"** —— 禁止使用 `assets` / `plannedAssets` / `mapAssets` 之类命名；建议用 `declarationBindings` / `boundAssetRefIds` 语义的命名（**字段名定稿后再落**）；
3. **资产 ID 不得进 `message`**（§1.5 **T3** 对新增条目**同样生效**：`message` 不得含子串 `KI-`）。

> 说明：这不是等价性问题（新增条目不改既有行为），但它会让"**声明面**"与"**计划面**"在观测上混为一谈 —— 而二者的区分正是 B-1（不读计划）与 B-2（可能读计划）的分界。

#### 1.1.4 plan-scoped 留痕 ⇒ **B-2 候选**（不在 B-1 决定）

"按计划资产留痕"需要读计划 ⇒ 与 Q1-i 签名约束冲突 ⇒ **登记为 B-2 候选议题**（连同其签名/等价性重做成本）。B-1 **不留任何口子**（不预留参数、不预留开关）。

### 1.2 读取**范围**不变（关键取舍）

新方法返回的 dict 必须与 `CustomerKnowledgeProvider.ki_map(customer_id)` 的返回**等价**（同一客户的**全部** `KNOWLEDGE_ITEM_TEXT`），**不得**顺带裁剪为"只读计划里的资产"。

理由（实证）：`ki` 的全部消费点都已按**计划资产**过滤，裁剪只会引入未经验证的行为面：

```text
skills.py:523-532  _ki_context(ki, only=list(assets))                 ← only= 过滤
skills.py:534-541  _ki_sections(ki, only=assets)                      ← only= 过滤（:539 `ids = only or 契约顺序`）
skills.py:806-807  refs = … [ … for kid in assets if kid in ki]       ← 按 assets 过滤
skills.py:721-722 / :754-755 / :787-788                                ← 逐 asset 的 ok/skipped 轨迹
```

"按资产裁剪读取"是会**改变 `ki` 内容**的另一件事（属后续片），不得与 B-1 捆绑——否则"0 变化"无法成立。

### 1.3 失败处置：B-1 **一律回落 + 具名留痕**（**不改变任何拒绝语义**）

B-1 中，能力侧四类解析失败**均不阻塞**、**均回落**到今日的读取路径、**均产出一条具名留痕**，且**不产生任何 KI 级拒绝**（**硬规则 E0**）：

| 情形 | B-1 行为（本片） | 具名留痕 | B-2 才会改为 |
|---|---|---|---|
| **声明缺失** | **回落**字面量读取路径（行为与接线前**逐字一致**），技能照常完成 | `KNOWLEDGE_SOURCE_DECLARATION_ABSENT` | 拒绝（**B-2**；B-1 严禁） |
| 声明非法 | 同上（**回落**），技能照常完成 | `..._DECLARATION_INVALID` | 拒绝 |
| 能力不可用（投影缺失） | **回落**（结果与今天一致：返回空 dict ⇒ 逐条 `skipped`） | `..._UNAVAILABLE` | 拒绝 |
| 某 assetRefId 未绑定 | 该条照常 `skipped`（今天行为），**不回落读取也不拒绝** | `..._UNBOUND` | 拒绝（B-2，且受 R-2 约束） |

> **为什么"回落"是唯一正确选择**：B-1 的对外承诺是"**等价替换**"。一旦"声明缺失 ⇒ 拒绝"在 B-1 生效，它就已把语义升级**偷偷提前**进来 ⇒ R-6 的拆分当场作废、B-2 失去独立授权意义。
> **B-1 的收益**：读取机制真的换成"声明驱动"（可被 §2.5 的双向证据证明），而**拒绝语义一点没变** ⇒ 部署侧无需任何前置条件，可在 B-2 之前独立上线。

### 1.4 `required` **不升格**（R-2 的机械钉法）

今天 `required` **不参与运行时判定**（`skills.py:645-646` 明文 + 地图 notes 同载）。B-1 必须证明"未绑定 ⇒ 软失败"**对 `required: true` 与 `required: false` 一视同仁**——两者今天都只是 `skipped`，B-1 之后也必须都只是 `skipped`。

**机械核对用例形式**（新增，见 §3.3）：

```python
# 夹具：声明存在，但把某 assetRefId 从 bindings 中删除；两张地图分别标 required=True / False
# 断言：两种情形下 r.status == "ok"、该条 KI 轨迹为 skipped、且**不出现** READ_DENIED 类结果
assert (r_true.status, kind_true) == (r_false.status, kind_false) == ("ok", "skipped")
```

若实现把 `required: true` 判为拒绝、`required: false` 判为跳过 ⇒ **两侧结果不同 ⇒ 用例 FAIL**（这正是"顺带升格"最难被发现之处）。

### 1.5 trace 字段纪律（4 条，均由既有断言反推，**必须遵守**）

新条目一旦违反下列任一条，A/B 组既有用例即会变红（即违反"0 变化"）：

| # | 纪律 | 反推依据（既有断言） |
|---|---|---|
| T1 | 新条目**不得**携带 `kiId` 字段 | `test_control_plane_consistency.py:66`（`{t["kiId"] for t in … if t.get("kiId")}`）与 `test_skills.py:200-202` 等按 `kiId` 取集合 |
| T2 | 新条目**不得**含 `mapId` 字段，`errorCode` **不得**以 `ROUTE_` / `KNOWLEDGE_MAP_` / `ONTOLOGY_REFERENCE_` 开头 | `test_skill_routing_trace.py:_route_entry`（`:33-39`）取**第一个**满足该条件的条目作为"路由条目" |
| T3 | 新条目的 **`message` 值不得包含子串 `KI-`**（含能力 ID `KS-CUSTOMER-KI-PARQUET` 里的 `KI-`，**因此不得把 capabilityId 拼进 message**；应放独立字段） | `test_skills.py:130`：`all("skipped" in m for m in msgs if "KI-" in m)` |
| T4 | `phase` / `status` 只能取 canonical 枚举值 | `docs/contracts/schemas/assembly-trace.schema.json:18-31`（phase）、`:35-44`（status）；枚举值不可越界 |
| **T5** | 两个新字段（`capabilityId` / `sourceCode`）**必须同期追加进 canonical schema**（additive，**仅两字段**），**不得**只靠 `additionalProperties: true` 兜底 | **DECISION_SHEET C-3**：靠 `additionalProperties` 兜底＝上一轮刚被纠正的"**实现有字段、合同未声明**"失实模式；按 v1.5 先例走"additive 先行 + 提案 + 登记 §0.1 + 待 Contract Owner 追认"；**合同本体（`specs/**`、v2 候选）不动** |

| **T6** | 新增条目**只追加在既有序列末尾**（append-only），**不得**插入中间、**不得**改动既有条目的顺序与内容 | **Q3 定稿**：这样"剔除新增条目后可还原"才是**机械可判**的（§2.2 的**前缀相等**断言形式即由 T6 保证可判） |

⇒ 形态（**字段名已定稿**，见 C-3）：`{"phase": "evidence", "status": "ok"|"degraded", "capabilityId": "KS-CUSTOMER-KI-PARQUET", "sourceCode": "KNOWLEDGE_SOURCE_UNBOUND", "message": "知识源能力解析结果…"}`（`message` 不含 `KI-`）。

> **T6 表述修正（TL 2026-09-16 采纳，**取代原表述**）**：T6 原文"新增条目只追加在既有序列**末尾**"
> **物理不可满足** —— 取数段之后还有 `model` / `parse` 条目，留痕必然落在序列中间。故 T6 由下式**取代**：
> **「剔除留痕后与接线前逐字全等（含顺序）」+「留痕是紧接既有 `kert` 条目之后的连续块」**。
> 该式**等价且更强**（顺序敏感 + 位置约束），且原表述的目标（"剔除后可还原"可机械判定）由前者保证。
> **不得**改为"trace 末尾追加"：那会把留痕移出取数段，削弱**回落可见性**，而可见性正是留痕存在的理由。
> **位置约束已在交付测试中被断言**（不是只写在文档里）：
> `tests/unit/test_skills_capability_swap_guards.py::test_trace_field_discipline_and_append_only`
> 的 `r.assembly_trace[idx[0] - 1].get("phase") == "kert"`（= 变异 **V13** 的打击点，实测可捕获）。

### 1.6 既有 fail-open 文案**不动**

A 组两条断言要求既有条目**原样保留**：

```text
test_skills.py:188-189  any(t.phase == "kert" and t.status == "skipped")      ← 无投影时必须仍在
test_skills.py:204-205  any(t.phase == "kert" and t.status == "ok")           ← 有投影时必须仍在
test_skills.py:247-248  any("知识地图" in m) 且 any("KI-009" in m and "知识库命中" in m)
```

⇒ B-1 **只新增**条目，**不修改** `_load_ki`（`:509-521`）与 `_trace_ki`（`:700-711`）的任何现有文案与字段。

---

## 2. (i) 逐条等价性证据设计（断言形式，不是"看起来一样"）

### 2.1 参照实现（无需新增死代码）

`customer_knowledge.py` 在 B-1 中**不改**，因此 `CustomerKnowledgeProvider(ws).ki_map(cid)` **天然就是参照实现**，可直接在测试里调用——不需要保留"旧路径副本"。

### 2.2 等价性断言形式（α）

```python
# 1) 读取映射：逐键逐值相等（含 title / content 逐字节）
new_ki = <技能实际使用的 ki 映射>              # 经能力读取
ref_ki = CustomerKnowledgeProvider(ws).ki_map(cid)   # 参照实现
assert set(new_ki) == set(ref_ki)
assert all(new_ki[k]["title"] == ref_ki[k]["title"]
           and new_ki[k]["content"] == ref_ki[k]["content"] for k in ref_ki)

# 2) **前缀相等（T6 保证可判，最强形式）**：既有序列必须是被测序列的**逐字前缀**
n = len(r_ref.assembly_trace)
assert r.assembly_trace[:n] == r_ref.assembly_trace      # 既有条目顺序与内容一字不改
assert all(e.get("capabilityId") for e in r.assembly_trace[n:])   # 新增条目**只**在末尾
assert r.data == r_ref.data and r.status == r_ref.status

# 2b) 等价形式（便于排障）：剔除新增条目后全等
def _strip_new(entries):  return [e for e in entries if e.get("capabilityId") is None]
assert _strip_new(r.assembly_trace) == _strip_new(r_ref.assembly_trace)

# 3) 逐 asset 轨迹：顺序与 ok/skipped 判定一致
assert [(t.get("kiId"), t.get("status")) for t in r.assembly_trace if t.get("kiId")] \
       == [(k, "ok") for k in KI_IDS]
```

> 说明：(2) 里的 `r_ref` 由"同一工作区 + 同参照实现路径"构造（例如直接调用 `_ki_context` / `_ki_sections` 的输入来自 `ref_ki`），使"前/后对比"在同一次运行内完成，**不依赖跨 commit 快照**。

### 2.3 B 组 9 条**逐条**的等价判据（实跑清单见影响面分析 §2.3）

| 用例 | 等价判据（断言形式） |
|---|---|
| `TestAssemblyTraceKi::test_previsit_ki_all_ok_from_library` | `{t["kiId"] for phase=evidence & status=ok} == set(KI_IDS)` **且** `ki 映射 == ref_ki`（§2.2-1） |
| `TestAssemblyTraceKi::test_previsit_sections_per_ki` | `len(sections) == len(KI_IDS)`、`sections[0].heading` 以 `KI-009` 开头、`sections[1].content` 含 `华鑫轴承材料集团`（原文逐字节） |
| `TestAssemblyTraceKi::test_previsit_evidence_independent_of_request_fields` | 同第一条（请求带旧字段时 `ki_ok == set(KI_IDS)`） |
| `TestAssemblyTraceKi::test_outreach_meeting_evidence_from_library` | 两条技能：`any("知识地图" in m)`、`any("KI-009" in m and "知识库命中" in m)`、`evidenceRefs[0].id == "KI-009"` |
| `TestAssemblyTraceKi::test_previsit_ki_all_skipped_unknown_customer` | **这是 (D) 类（数据未命中）**：`status == "ok"`、逐 KI `skipped`、`sections == []`、**且不得出现任何 `KNOWLEDGE_SOURCE_*` 拒绝** |
| `TestNoNewEvidencePolicy::test_other_skills_ignore_policy` | `status == "ok"` + §2.2-1/2 |
| `TestNoNewEvidencePolicy::test_r1_newer_timestamp_ok` | `status == "ok"` + §2.2-2 |
| `TestNoNewEvidencePolicy::test_r1_stale_timestamp_blocked` | 早退策略先于路由 ⇒ **不进入**新读取路径（断言 `status == "exit_policy_no_new_evidence"` 且无新增条目） |
| `TestSecondCustomer::test_r1_ki_all_ok` | 第二客户 `CUST-CORP-0002`：`ki_ok == set(KI_IDS)` + §2.2-1 |

### 2.4 (β) 的机械断言（无投影分支）

```python
# 夹具 = ws_provisioned（有声明、无 customer_knowledge 投影）
assert r.status == "ok"
assert any(t.phase == "kert" and t.status == "skipped" for t in r.assembly_trace)
assert all("skipped" in m for m in (t.get("message","") for t in r.assembly_trace) if "KI-" in m)
assert not [t for t in r.assembly_trace if t.get("kiId")]        # 无命中，逐条不产出 ok
assert [t.get("sourceCode") for t in r.assembly_trace if t.get("capabilityId")] \
       == ["KNOWLEDGE_SOURCE_UNAVAILABLE"]                        # 具名留痕（唯一新增）
```

### 2.5 "真的走声明"的双向证据（反"接线后仍读字面量"）

```python
# 方向 A：改声明使其不匹配 ⇒ 读取集必须随之变为空
写 ws/90_control/schema/knowledge_sources.json：assetMatch.pattern 改为 ``^(?P<assetRefId>KI-XXX)\s+(?P<title>.+)$``
r = 执行 outreach
assert r.status == "ok" 且 逐条 KI 轨迹为 skipped 且 无任何 ok 的 kiId
# 方向 B：恢复声明 ⇒ 必须恢复为 7 条命中
assert {t["kiId"] for t in trace if t["kiId"]} == set(KI_IDS)
```

若实现仍走旧的隐式正则/字面量路径，方向 A 的断言**必然 FAIL**（仍命中 7 条）。

### 2.6 不可用分支的**可区分性**

```python
# 用同一工作区的三种声明形态分别断言：三者的**留痕码**必须互不相同
# （B-1 中三者都是"回落 + 留痕"，**都不是拒绝**；B-2 才会成为拒绝码 —— 见硬规则 E0）
assert codes(无声明) == {KNOWLEDGE_SOURCE_DECLARATION_ABSENT}
assert codes(声明含未声明字段) == {KNOWLEDGE_SOURCE_DECLARATION_INVALID}
assert codes(删除 04_serve/customer_knowledge/CURRENT.md) == {KNOWLEDGE_SOURCE_UNAVAILABLE}
# 且三者在 B-1 中都必须 **同时** 满足：status == "ok" 且 errors == []
```

### 2.7 (γ) **回落规则**用例（**新增**，钉住"今天完全没测"的组合；TL 明确要求）

**组合**：计划门禁放行 + **声明缺失** + 客户知识库**可用**（这正是 2-A 之前供给过的工作区 / 手工配置工作区的真实形态）。

```python
# ── 夹具（新文件内自建，不改既有测试文件）──
ws = provisioned_and_seeded_ws()                     # 用 tests/conftest.py:28-40 的 ws_provisioned + 自建 seed
(ws / "90_control" / "schema" / "knowledge_sources.json").unlink()   # 声明缺失

# ── 前提断言：声明不是计划门禁的输入 ⇒ 计划仍放行（防"夹具其实没进到分支"）──
plan = ActivationPlanBuilder.load(ws).build("PRE_VISIT_PREPARATION")
assert not isinstance(plan, PlanDenial), plan.reason

# ── 断言 1：技能照常完成，走**字面量回落路径** ⇒ 与参照实现逐字节等价（§2.2-1）──
r = SkillExecutionService(ws).execute("skill-customer-outreach-script", "b1-g1", {"customerId": CID})
assert r.status == "ok"
ref_ki = CustomerKnowledgeProvider(ws).ki_map(CID)
assert set(t["kiId"] for t in r.assembly_trace if t.get("kiId")) == set(ref_ki) & set(ASSETS)

# ── 断言 2：具名留痕存在（回落是"可见的"，不是静默）──
assert [t.get("sourceCode") for t in r.assembly_trace if t.get("capabilityId")] \
       == ["KNOWLEDGE_SOURCE_DECLARATION_ABSENT"]

# ── 断言 3：**未出现任何拒绝**（硬规则 E0 的核心）──
assert r.errors == []
assert not any(str(t.get("sourceCode","")).startswith("KNOWLEDGE_SOURCE_")
               and t.get("status") in {"failed", "blocked"} for t in r.assembly_trace)

# ── 断言 4：与"接线前"逐字一致（除新增留痕外 trace/data 全等，§2.2-2）──
assert _strip_new(r.assembly_trace) == _strip_new(baseline_trace)
```

**变体 (γ)′（声明缺失 + 库不可用）**：断言 `status == "ok"`、既有 `phase="kert"/"skipped"` 条目仍在、逐条 KI `skipped`、**无拒绝** —— 即 A 组行为在"声明缺失"下同样成立。

**为什么必须新增**：这三条既有断言都不覆盖"声明缺失"：`test_unprovisioned_workspace_refuses_and_records_why`（`test_skill_routing_trace.py:46-65`）在**计划门禁**就已被拒，走不到读取层；`test_skills.py` 的 A/B 组夹具**都带声明**。⇒ 该组合此前**零覆盖**，本用例是**补洞**（新增，不改任何既有断言）。

---

## 3. (ii) 变异点清单（每项：变异 → 期望 FAIL → 捕获用例）

| ID | 变异（实现侧） | 期望结果 | 捕获用例 |
|---|---|---|---|
| **V1** | 接线后仍走旧的隐式路径（新方法内部直接调 `ki_map`，不过声明） | FAIL | §2.5 方向 A/B；§2.2-3 |
| **V2** | 声明缺失被**静默吞掉**（回落了但**无具名条目 / 无 `sourceCode`**） | FAIL | §2.4 末行 + §2.7 断言 2 |
| **V11** | **声明缺失时拒绝**（把 B-2 语义提前进 B-1） | FAIL | §2.7 全部四条断言（尤其断言 1/3）；并要求该变异**必须**被捕获——否则硬规则 E0 只是注释承诺 |
| **V3** | 未绑定时**回落**（读全部资产 / 读字面量） | FAIL | 未绑定夹具：该条必须 `skipped`、其余条数不变、`ki` 与 `ref_ki` 仍等价 |
| **V4** | `required` **顺带升格**（true ⇒ 拒绝、false ⇒ skipped） | FAIL | §1.4 的"两侧结果必须相同"断言 |
| **V5** | 能力门禁**提前**到计划门禁之前 | FAIL | C 组 3 条既有用例（拒绝码须仍为 `ROUTE_UNRESOLVED` / `ROUTE_POLICY_ABSENT` / `ONTOLOGY_REFERENCE_INVALID`） |
| **V6** | 新条目带 `mapId` / `kiId` / `message` 含 `KI-` | FAIL | 新增守卫用例：`_route_entry(trace)` 仍须选到**路由**条目；`all("skipped" in m …)` 等价断言 |
| **V7** | 把 `UNAVAILABLE` 与 `ABSENT` 混为同一码 | FAIL | §2.6 三态可区分 |
| **V8** | 改 `_load_ki` 本体（波及 `_run_supply_chain`） | FAIL | D 组 3 条行为不变 + 新增"调用点集合 == {outreach, meeting, previsit}"机械断言 |
| **V9** | 读取内容被改写（strip/截断/去重/改 title） | FAIL | §2.2-1 逐字节断言 |
| **V10** | 留痕中的能力指纹写死（常量 / 与 `resolver.binding_sha256` 不符） | FAIL | 断言指纹 == `KnowledgeSourceResolver.load(ws).binding_sha256`，且**改声明后必变** |
| **V12** | **出现第 4 个调用点**（例如把新方法也塞进 `_run_supply_chain`，或新增一个 `_load_ki*` 方法） | FAIL | §4.1 守卫：前缀枚举集合必须恰为 `{_load_ki, _load_ki_from_declaration}`，且新方法调用点集合必须恰为 `{_run_outreach, _run_meeting, _run_previsit}`；并**显式**断言 `_run_supply_chain` **不**在其中 |
| **V13** | 新增条目**插入到序列中间**（而非末尾） | FAIL | §2.2 的**前缀相等**断言（`r.assembly_trace[:n] == r_ref.assembly_trace`） |
| **V14** | **签名漂移**：给新方法加 `plan` 参数（或改返回类型） | FAIL | §4.1 守卫 **5**（`inspect.signature` 等式）；并**必然**同时触发 V12（若把 plan 传进来则调用点也要改） |

> 变异执行方式沿用前两片：临时改实现 → 期望非零退出码 → 恢复并校验 sha256 一致。**恢复后 sha256 与变异前逐字节相同**为本片证据的一部分。

---

## 4. (iv) D / E 两组如何处理

### 4.1 D 组：**不接线**，并加机械守卫

- `_run_supply_chain`（`skills.py:818-823`）与其调用的 `_load_ki`（`:820`）**不动** ⇒ 3 条 D 组用例（`TestSupplyChainFromLibrary::test_graph_complete_from_library`、`::test_graph_partial_unknown_customer`、`TestSecondCustomer::test_graph_complete_from_library`）行为不变。
- **新增机械守卫（Q4 定稿，白名单精确 + fail-closed）**，用 **`_load_ki` 前缀 grep** 实现（借 Q1-ii 的命名约定）：
  1. **前缀枚举集合必须恰为** `{_load_ki, _load_ki_from_declaration}` —— 多出任何 `_load_ki*` 方法即 FAIL（防新增读取点绕过守卫）；
  2. **新方法的调用点集合必须恰为** `{_run_outreach, _run_meeting, _run_previsit}` —— 出现第 4 个调用点即 FAIL；
  3. **显式断言** `_run_supply_chain` **不**调用新方法（防 D 组被顺手接线）；
  4. **守卫本身 fail-closed**：源码不可读 / 解析不到调用点 / 夹具缺失 ⇒ **FAIL，不得 skip**（沿用前两片"负例夹具缺失即 FAIL"的风格）；
  5. **签名等式守卫（TL 补充，直接保护 Q1-i）**：
     ```python
     import inspect
     assert (inspect.signature(SkillExecutionService._load_ki_from_declaration)
             == inspect.signature(SkillExecutionService._load_ki))
     ```
     —— 日后若有人为传 `plan` 而**改签名/加参数**，本守卫**立即 FAIL**；**源码扫描抓不到"参数变了"，这条能**。
- **一致性债照旧登记**（`DECISION_SHEET` **D-7**）：`bank-front-supply-chain-graph` 仍走"字面量 KI-FRONT-001/002/003"（`:821-823`）⇒ 本项目**不得**表述为"客户知识读取已全部接线"。

### 4.2 E 组：**必须显式复跑**（不得默认不受影响）

| 用例 | 为何可能受影响 | 复跑判据 |
|---|---|---|
| `test_persistent_jobs.py::TestPersistentAsyncExecution::test_thread_mode_without_store` | 异步/线程路径执行同一技能；仪器本次未观察到取数调用 | 与 §2.4 同等断言 + `status` 不变 |
| `test_prod_async_guard.py::TestProductionRequiresRuntimeStore::test_dev_without_store_still_allowed` | 同上（profile 分支，可能触发技能执行） | 同上 |
| `test_prod_async_guard.py::TestProductionRequiresRuntimeStore::test_explicit_profile_overrides_env` | 同上 | 同上 |

复跑要求：**在 HEAD 冻结态**逐条运行并附原始退出码；任何一条状态变化 ⇒ 视为"0 变化"不成立，先定位再决定。

---

## 5. (iii) 明确的"不做"清单

| # | 不做 | 原因 |
|---|---|---|
| 1 | **不改** A 组 29 条断言（也不改 B 组 9 条、C 组 3 条） | R-1：属已声明业务语义；B-2 才动，且需 Owner |
| 2 | **不动** `tests/e2e/**` | e2e 假绿修补与 CI 供给耦合，登记为 **B-2 交付项** |
| 3 | **不接线** `_run_supply_chain` / `bank-front-supply-chain-graph` | O-6 范围；§4.1 |
| 4 | **不改** `application/customer_knowledge.py` | 它是 B-1 的**参照实现**（§2.1）；改它就没法证等价 |
| 5 | **不改** `api/**`、`specs/**`、`deploy/**`，以及**除 C-3 明确纳入者之外**的任何 `docs/contracts/**` | 边界；唯一例外见下方白名单（additive 两字段） |
| 6 | **不改** `application/provision.py`、`domain/knowledge_source.py` | 2-A 已完成供给；B-1 只**消费**该模块 |
| 7 | **不做**"按计划资产裁剪读取" | 会改变 `ki` 内容（§1.2），属后续片 |
| 8 | **不升格** `required` | R-2 裁定；§1.4 |
| 9 | **任何让「声明缺失 ⇒ 拒绝」在 B-1 生效的写法**（含在读取层、技能层、API 层、或"顺手把 `ReadDenial` 当 `SkillError` 抛"的间接写法） | **硬规则 E0**；R-6 拆分的前提 |
| 10 | **既有测试文件一字不改**（含 `tests/integration/test_skills.py`、`test_skill_routing_trace.py`、`test_control_plane_consistency.py`） | 只冻结那 29 条既有断言；TL 允许**新增**测试（补洞），不允许就地改 |

**B-1 实施阶段（另需授权）的文件级白名单（**TL 已定稿，共 4 组**；除此四组外一律不动）**：

```text
src/kert/application/skills.py                        （新增 1 个 `_load_ki_from_declaration` + 3 处机械调用替换；不动 `_load_ki`）
tests/unit/test_skills_capability_swap_guards.py      （新增：Q4 调用点守卫 + trace 字段纪律 T1-T6 守卫）
tests/integration/test_skills_capability_swap.py      （新增：α/β/γ 等价性 + 回落 + 可区分性）
docs/contracts/schemas/assembly-trace.schema.json     （**仅追加 `capabilityId` / `sourceCode` 两字段**；additive，
                                                      按 v1.5 先例走提案 + 登记 §0.1，**待 Contract Owner 追认** — C-3）
evidence/m7-3/**                                      （实施期证据与登记；不含改写历史证据）
```

> C-3 的**实施时序**：additive 增量可**先行**（与 v1.5 先例一致），但必须①同步改该 schema、②附变更提案、③登记到追认清单；**合同本体（`specs/kert-openapi-v1.yaml`、v2 候选）一律不动**。

### 5.1 **R-1 停机条件**（TL 明确要求）

> **若实施中发现"不改那 29 条（A 组）就无法做到 0 变化" ⇒ 立即停下报告 TL，不得自行改测试去对齐实现。**

这条与硬规则 E0 是同一件事的两面：B-1 的存在意义就是"**不动既有断言**的前提下换实现"；一旦越线，B-1 就不再是 B-1，而应退回 B-2（待 Owner）。

> 新增集成测试**自带夹具**、不依赖既有测试文件的改动：`ws_provisioned` 直接取自 `tests/conftest.py:28-40`；"已种客户知识"的等价物在新文件内自建（沿用 `tests/integration/test_skills.py:41-49` 的既有写法 `seed_customer_knowledge(ws, quiet=True)`），但**不修改** `test_skills.py` 本身。

---

## 6. 冻结态复测要求（纪律，TL 明确要求）

**本方案的"0 条既有用例变化"结论尚未成立**，因为它依赖的实跑发生在**并发期**（c20 在途改 `src/kert/api/server.py`，+29 行）。并发期跑数不可归因。故：

0. **Q5 已定稿：先冻结态复测，再派工实施**。c20 批次**仍在途**（本轮未收到落定信号）⇒ **在收到 TL 的"冻结"信号前，不动 `skills.py`**（本文档为唯一产出）。
1. 等 TL 告知 c20 批次落定；
2. 在 **HEAD 冻结态**重跑：`git status --short`（须干净或仅有本包改动）→ 记录 `git rev-parse HEAD`；
3. 重跑影响面枚举并留证：

```bash
.venv/bin/python /tmp/m71b_impact_probe.py            # 重建 44 条枚举与 A/B/C/E/D 分组
.venv/bin/python -m pytest tests/unit tests/integration tests/contract tests/recovery \
    -p no:warnings -o addopts="" -q                    # 全量原始计数与退出码
```

4. **只有冻结态复跑后**，才可在 B-1 验收材料中写"0 条既有用例变化"；此前该结论一律标注为**"待冻结态确认"**。
5. 同一冻结态下还须确认：(γ) 回落组合（§2.7）在**接线前**的基线**确实没被任何既有用例覆盖**（即"今天完全没测"这一前提），否则该组合与本方案的"新增补洞"定位需重估。

6. **探针脚本落盘（防 `/tmp` 被清理导致"方法不可复现"）**：此前用于实跑的脚本位于 `/tmp/m71b_impact_probe.py`（仓外、一次性）。下面是**等价的精简可复现版**，与 §6 第 3 步命令配套使用；分组口径与本文《影响面分析》A/B/C/D/E 完全一致：

```python
#!/usr/bin/env python3
"""M7.1 影响面实跑探针（精简可复现版）。用法：.venv/bin/python <本文件>"""
# 实测：本脚本已从本文档抽出后直接运行，exit 0，输出合法 JSON（见第 7 项的测量学 caveat）
from __future__ import annotations
import json, sys
from collections import defaultdict
from pathlib import Path
import pytest

REPO = Path("<repo 绝对路径>"); sys.path.insert(0, str(REPO / "src"))
DECL = Path("90_control") / "schema" / "knowledge_sources.json"
REC, CUR = [], {"n": ""}

def install() -> None:
    from kert.application import skills as sk
    rp = sk.SkillExecutionService._route_plan
    lk = sk.SkillExecutionService._load_ki
    sc = sk.SkillExecutionService._run_supply_chain

    def route(self, trace, expected_map_id, task):
        ws = Path(self.workspace) if self.workspace else None
        rec = {"node": CUR["n"], "kind": "route_plan", "task": task,
               "decl": bool(ws and (ws / DECL).is_file()), "out": ""}
        REC.append(rec)
        try:
            res = rp(self, trace, expected_map_id, task)
        except Exception as exc:                      # 只记录，不改行为
            rec["out"] = f"RAISED:{type(exc).__name__}"; raise
        rec["out"] = "ALLOWED"; return res

    def load(self, cid, trace):
        ws = Path(self.workspace) if self.workspace else None
        REC.append({"node": CUR["n"], "kind": "load_ki",
                    "ckp": bool(getattr(self._ckp, "available", False)),
                    "proj": bool(ws and (ws / "04_serve" / "customer_knowledge" / "CURRENT.md").is_file())})
        return lk(self, cid, trace)

    def supply(self, req, trace):
        REC.append({"node": CUR["n"], "kind": "supply_chain"})
        return sc(self, req, trace)

    sk.SkillExecutionService._route_plan = route
    sk.SkillExecutionService._load_ki = load
    sk.SkillExecutionService._run_supply_chain = supply

class Tracker:
    def pytest_runtest_setup(self, item): CUR["n"] = item.nodeid
    def pytest_runtest_teardown(self, item, nextitem):
        CUR["n"] = nextitem.nodeid if nextitem is not None else ""

if __name__ == "__main__":
    install()
    pytest.main(["tests/unit", "tests/integration", "tests/contract", "tests/recovery",
                 "-p", "no:warnings", "-o", "addopts=", "-q", "--tb=no"], plugins=[Tracker()])
    route, ki, sup = defaultdict(list), defaultdict(list), set()
    for r in REC:
        if r["kind"] == "route_plan": route[r["node"]].append(r)
        elif r["kind"] == "load_ki": ki[r["node"]].append(r)
        else: sup.add(r["node"])
    ok = lambda n: any(r["out"] == "ALLOWED" for r in route[n])            # noqa: E731
    ckp = lambda n: any(r["ckp"] for r in ki.get(n, []))                   # noqa: E731
    A = sorted(n for n in route if ok(n) and n in ki and not ckp(n))
    B = sorted(n for n in route if ok(n) and n in ki and ckp(n))
    C = sorted(n for n in route if not ok(n))
    E = sorted(n for n in route if n not in set(A) | set(B) | set(C))
    print(json.dumps({"route_plan_calls": sum(len(v) for v in route.values()),
                      "route_plan_items": len(route), "load_ki_items": len(ki),
                      "A": A, "B": B, "C": C, "E": E,
                      "supply_chain_unwired": sorted(sup)},
                     ensure_ascii=False, indent=2))
```

7. **⚠ 已实测的测量学caveat：异步/线程用例的归属存在竞态（必须在冻结态报数时按规则处理）**

实测事实（同一天、同一棵树、仅探针实现细节不同）：

| 观测 | 结果 |
|---|---|
| **同一个探针连跑两次**（`/tmp/m71b_impact_probe.py`，run1 vs run2，逐条集合比对） | **完全一致**：A/B/C/E = **29/9/3/3**，`load_ki` 观测用例 = **44**，漂移集合为空 |
| **结构等价的精简版探针**（§6 第 6 项那份）跑一次 | A/B/C/E = **30/9/3/2**，`load_ki` 观测用例 = **43**（少 1；且少掉的是**异步/技能包**类条目） |

⇒ 结论：**漂移不来自树状态，而来自 `_load_ki` 调用在异步/线程路径上的归属竞态**（nodeid 由 `pytest_runtest_setup/teardown` 提供，worker 线程可能在主线程已推进后被记录，或未被记录）。

**冻结态报数必须遵守的规则（否则会把抖动当事实写进证据）**：

- **R-A（TL 加固版）**：`A` 组的成员**必须在两次运行中都命中**（取两跑**交集**）；任一次缺席 ⇒ **归 E**。不得只凭一次观测，也不得取并集 —— A 是"语义变更载体"的论据，**宁可少不许虚增**；
- **R-B**：探针**连跑两次**，报**两次的集合与差异**（不报单次结果）；
- **R-C**：无法稳定归属的条目**一律保守归入 E**（"需复跑确认"），**不得**计入 A 组；
- **R-D**：报数时同时给出**探针脚本的 sha256**（区分"原版 / 精简版"两种实现）；
- **R-E（TL 加固版）**：冻结态**一律以原版探针**（`/tmp/m71b_impact_probe.py`，sha256 `d73ce3c6…6639b`）为准报数；**精简版（`6a80fdfb…b35a4`）仅作交叉验证**，且报告须写明两者差异及其**机制原因**（异步/线程 nodeid 归属竞态）。**严禁**"哪个探针结果好看就用哪个"；
- **R-F**：报告须含**探针完整命令行**（可原样重跑）与 **python/venv 与 pytest 版本**；
- **R-G（TL 定稿 2026-09-16；R-E 家族的下一条 —— 探针口径缺口）**：
  `/tmp/m71b_impact_probe.py` **只包装 `_load_ki`** ⇒ B-1 之后三个**已接线技能的生产路径不再经过它**，
  该探针对这三个技能的 `load_ki` 计数**结构性失效**（表现为"计数下降"，**不是**"读取变少"）。
  ⇒ 凡用该探针核对"**读取路径**"（含**正式确认跑**要做的 A 组集合比对），**必须同时计数**
  `_load_ki_from_declaration`；**禁止**仅凭该探针的 `load_ki` 计数论证"读取未被改动"。
  实测依据见 §10.3。

8. **报数清单（TL 明确要求；不接受"全绿/通过"式转述）** —— 冻结态复测后逐项给出**原文**：

```text
(a) git rev-parse HEAD  与  git status --short 的原文（证"冻结/干净"）
(b) 四个目录各自的原始计数与退出码（逐目录一行，不得合并为一句"全量通过"）：
      tests/unit           → <N passed in …s>   exit <0>
      tests/integration    → <N passed, M xfailed in …s>  exit <0>
      tests/contract       → <…>  exit <…>
      tests/recovery       → <…>  exit <…>
(c) 44 条枚举原文：_route_plan 调用数、去重用例数、load_ki 去重用例数，以及 A/B/C/D/E 五组各自计数与用例名
(d) (γ) 前提复核结论：接线前"计划放行 + 声明缺失"组合是否**零覆盖**（含检索命令）
(e) 环境声明：venv 路径与 python 版本（避免"系统 python3 vs .venv"两口径混淆）
(f) 探针两次运行的集合差异（见第 7 项 R-A…R-D），以及探针脚本自身 sha256
(g) 探针的**完整命令行**（可原样重跑），例如：
      cd /home/szf/dev/Leibniz-KERT && .venv/bin/python /tmp/m71b_impact_probe.py
(h) python/venv 与 pytest 版本（本包实测口径：.venv = Python 3.12.8 / pytest 9.1.1）
```

> **预跑 vs 冻结跑（必须区分）**：凡在第三方在途批未落定前所跑的，一律标注为**"预跑/非冻结态"**，
> **不得**写入本节作为冻结证据（本包已发生的预跑记录见 **§9**）。

9. **冻结归因前置（TL 冻结信号附带要求；冻结基准 `e3bcefe`）** —— 复测报告**开头**必须附：

```text
(1) git rev-parse HEAD                        （应为 e3bcefe）
(2) git status --porcelain                    （**完整**原文；本轮**非全树冻结**，须逐条列出）
(3) 并发文件 sha256(16) 快照（至少）：
      src/kert/application/provision.py
      src/kert/cli/main.py
      tests/unit/test_provision.py
      src/kert/domain/activation_contract.py
      tests/unit/test_activation_contract.py
      examples/bank-front-knowledge-maps/90_control/schema/activations/**（目录内文件逐个）
      .understandignore
(4) 复测**期间**上述任一项若发生变化 ⇒ **该次复测作废、重跑**（并发编辑期跑数不可归因 —— 本仓既有规则）
(5) provisioning 相关命中**单独列出**（把"B-1 造成的变化"与"供给面漂移造成的变化"分开归因）
```

背景（TL 提示）：`provision.py` / `cli/main.py` / `test_provision.py` 正被第三方改动（把**第 5 类** `activations/AC-*.json` 纳入供给）⇒ **供给面口径可能再变**（现行 6 类）⇒ 44 条枚举的基线可能随之偏移；`examples/bank-front-knowledge-maps/90_control/schema/activations/` 是受控工作区**新增子目录**（正是夹具源），须一并纳入快照。

---

## 7. 风险与回滚

| 风险 | 缓解 |
|---|---|
| 新增 trace 条目撞既有断言 | §1.5 的 T1-T4 + V6 守卫用例（三条反推证据均已落到具体行号） |
| 误伤 D 组（改到 `_load_ki` 本体） | §1.1 只新增方法 + §4.1 调用点机械守卫 + V8 |
| `required` 顺带升格 | §1.4 两侧结果必须相同的断言 + V4 |
| **B-1 顺手让"声明缺失 ⇒ 拒绝"生效**（把 B-2 提前，作废 R-6 拆分） | **硬规则 E0** + §2.7 四条断言 + **V11**（该变异必须被捕获） |
| **"实现有字段、合同未声明"**（C-3 指出的失实模式，上一轮刚被纠正） | **T5**：两字段**同期**追加 canonical schema（仅 additive）＋变更提案＋登记待追认；**禁止**只靠 `additionalProperties` 兜底 |
| 等价性只证了"看起来一样" | §2.2 给出**前缀相等（T6）**/逐字段/逐字节/去新条目后全等四种形式；§2.5 给双向证据 |
| **Q4 守卫被"可跳过"化**（加 `skip`/`xfail`/条件短路后形同虚设） | 守卫须 **fail-closed**：源码不可读、枚举不到调用点、夹具缺失 ⇒ **FAIL 而非 skip**；并用 **V12**（加第 4 个调用点）实证守卫有效 |
| 部署顺序 | B-1 **不需要**任何部署前置（不改变拒绝语义；声明缺失亦回落）；声明已随 2-A 供给，缺/非法在 B-1 下都不阻塞 |

**回滚**：单 commit revert（只涉及 `skills.py` + 新测试文件）⇒ 读取回到 `ki_map` 路径；声明留在卷里**完全惰性**（与《影响面分析》§4.3 一致）。

---

## 8. 待确认事项（供 TL 定稿）

**Q1–Q5 全部已由 TL 定稿**，本文件已按其改写（下表为回执与落点索引）：

| ID | 定稿结论 | 在本文件的落点 |
|---|---|---|
| **Q1** | 方法名 **`_load_ki_from_declaration`**；签名与 `_load_ki` **完全一致**（同参同返回）；前缀 `_load_ki` **刻意保留**（可一个前缀 grep 枚举全部 KI 读取点） | §1.1（含 §1.1.1 的签名推论：留痕范围 = 声明绑定集） |
| **Q2** | 字段名 **`capabilityId` + `sourceCode`**；并**同步追加进 canonical schema**（additive、待 Contract Owner 追认） | §1.5 **T5** + §5 白名单第 4 组 |
| **Q3** | **每资产一条**留痕；三条硬约束（无 `kiId` / `message` 不含 `KI-` / **只追加在序列末尾**） | §1.5 **T1/T3/T6** + §2.2 **前缀相等**断言 |
| **Q4** | **加**调用点守卫：白名单精确（第 4 个调用点即 FAIL）、显式断言 `_run_supply_chain` **不**调用、守卫**不得可静默跳过** | §4.1 四条 + §3 **V12** + §7 风险行 |
| **Q5** | **先冻结态复测，再派工实施**；等 TL 的"冻结"信号 | §6 第 0 条 |
| Q6（我方提出） | (γ) 回落用例落在**新文件** `tests/integration/test_skills_capability_swap.py`（不碰 `test_skills.py`） | §5 白名单第 3 组 |

> **唯一仍未获得的是"实施授权 + 冻结信号"**；在收到之前本文档是唯一产出，`skills.py` 不动（Q5）。
> **R-1 提醒照旧**：A 组 29 条仍登记为**待 Owner**（C-1b），B-1 内严禁触碰；触碰即触发 §5.1 停机条件。

---

## 9. 预跑记录（**非冻结态**；不得作为冻结证据）

> TL 采纳批注（2026-09-16）：本次预跑**已被 TL 采纳为 B-1 实施基准** —— 理由：① 9 个并发文件 sha before==after ⇒ 可归因 ② 3 条红灯归因明确且与 44 条枚举不相交 ③ 以『不得新增红灯』替代『全绿』作为验收不变量。正式冻结跑在第三方批次落定后**补做一次**。

> ⛔ **抬头声明**：本节记录的是 **预跑（pre-run）**，发生在**第三方在途批次未落定**期间。
> 按 TL 规则：**预跑不得写入 §6 作为冻结证据**；其唯一用途是**提前发现本包自己的问题**（探针、快照流程、报数模板）。
> **正式冻结跑待 TL 的新冻结信号**（该信号将在第三方批次落定后发出）。

### 9.1 预跑时间线与归因前置（TL 要求的 (a)–(d) 项）

```text
预跑编号      : PRE-1（收到"改判冻结"消息**之前**已启动，时间交叉；据此**降级**为预跑）
复测起点 HEAD : 43b02fa975d0ffcaea1670c1781dbce5416fd2e1
                （TL 原冻结基准为 e3bcefe；实测 HEAD 已前移 4 个**纯 docs** 提交：
                 git diff --stat e3bcefe 43b02fa = 仅 evidence/m7-3/DECISION_SHEET_M7_CLOSURE.md 7+/2-
                 ⇒ **代码面与 e3bcefe 相同**）
窗口内 HEAD  : 前移至 64f6f87；但 43b02fa..64f6f87 只改 **两份 evidence 文档**
                （含本文件 v1.4 入库 3280c59）+ DECISION_SHEET ⇒ **无代码/测试变化**
git status --porcelain（before，完整 8 行）:
   M .understandignore
   M evidence/m7-3/CANDIDATE-M7-1-B1-EQUIVALENT-SWAP.md
   M src/kert/application/provision.py
   M src/kert/cli/main.py
   M tests/unit/test_provision.py
  ?? examples/bank-front-knowledge-maps/90_control/schema/activations/
  ?? src/kert/domain/activation_contract.py
  ?? tests/unit/test_activation_contract.py
并发文件 sha256(16)（before == after，**9 项逐条一致** ⇒ 预跑期间无并发写）:
  e333648b1a79cea5  src/kert/application/provision.py
  e4847152145e3233  src/kert/cli/main.py
  8f4bd025463c2881  tests/unit/test_provision.py
  285f1c4f0e13aaa4  src/kert/domain/activation_contract.py
  7221a15a8d835ce5  tests/unit/test_activation_contract.py
  8ced89d5645c2e47  .understandignore
  9f7e46c563fb83c6  examples/.../schema/activations/AC-FACT-RECONCILIATION-001.json
  0b7545f80dd5697c  examples/.../schema/activations/AC-PRODUCT-RECOMMEND-001.json
  ac9fd6dd735b2070  examples/.../schema/activations/PROVENANCE.md
环境          : .venv = Python 3.12.8 / pytest 9.1.1
```

### 9.2 逐目录原始计数与退出码（预跑）

```text
tests/unit          → 3 failed, 963 passed in 19.03s      退出码 1
tests/integration   → 458 passed, 1 xfailed in 143.63s    退出码 0
tests/contract      → 53 passed in 0.13s                  退出码 0
tests/recovery      → 18 passed in 8.68s                  退出码 0
```

### 9.3 3 条失败的逐条归因（**非 B-1、非本包**）—— 正是 TL 改判冻结的实证

全部位于 `tests/unit/test_provision_cli.py`：

| 用例 | 断言 | 实际 |
|---|---|---|
| `:53 test_apply_then_idempotent_rerun` | `'新建 6 / 覆盖 0 / 未变 0' in output` | 输出为 `8` 条 → FAIL |
| `:66 test_json_output_follows_standard_envelope` | `counts["CREATED"] == 6` | **`assert 8 == 6`** |
| `:109 test_init_flag_initializes_fresh_volume_then_provisions` | `'新建 0 / 覆盖 0 / 未变 6' in output` | 输出为 `8` → FAIL |

根因：第三方在途批次把供给面扩为 **8 个条目**（3 地图 + `route_policy.json` + `ontology_reference.json` + `knowledge_sources.json` + `activations/AC-*.json` ×2），**已同步 `test_provision.py`（+88 行）但未同步 `test_provision_cli.py` 的计数断言** ⇒ 典型"改实现未同步断言"。本包**不触碰**该文件（白名单外）。

> ⇒ 这**恰好印证** TL 的改判理由：第三方半成品会污染"全量计数"，故**不能**作为冻结证据。

### 9.4 44 条枚举（**原版探针为准**；R-E）

```text
命令行（可原样重跑）: cd /home/szf/dev/Leibniz-KERT && .venv/bin/python /tmp/m71b_impact_probe.py
探针 sha256         : d73ce3c61f0f61e7a7f3a0379ca694040b2d8e733fd98aa8324e0ee9b776639b（原版，报数基准）
                      /tmp/m71b_probe_slim.py = 6a80fdfbd470750e79c19f59fd64ac32029da1dcc83f750dbedde8feac0b35a4（仅交叉验证）
_route_plan 调用数 = 49 ；去重用例 = 44 ；load_ki 观测用例 = 44 ；_run_supply_chain = 3
两跑（原版）分组 : A/B/C/E = 29 / 9 / 3 / 3     两次集合差：A=∅ B=∅ C=∅ E=∅
```

**精简版交叉验证差异（R-E 要求的机制说明）**：精简版单跑给 A/B/C/E = **30/9/3/2**、`load_ki` 观测 **43**（差 **1**）。
机制：**异步/线程路径的 nodeid 归属竞态** —— 同一原版探针连跑两次**逐条完全一致**，而两实现间差 1（缺的观测落在异步/技能包类条目）⇒ 漂移来自**观测归属**而非树状态 ⇒ 故冻结态**以原版为准**，且 A 组取**两跑交集**（R-A）。

### 9.5 (γ) 前提复核：**成立**（§6 第 5 点）

| 证据 | 命令 | 结果 |
|---|---|---|
| **决定性**：运行时读取路径**零消费者** | `grep -rn "KnowledgeSourceResolver\|plan_read\|match_heading" src/ --include=*.py \| grep -v domain/knowledge_source.py` | **零命中** ⇒ 接线前**任何**集成/e2e 用例都**不可能**走到"声明缺失的运行时判定"分支（`provision` 只调 `load_declaration`，属**供给期校验**） |
| 测试侧引用面 | `grep -rn "knowledge_sources" tests/ --include=*.py` | 9 处，**全部**在 `test_provision*.py`（供给面）与 `test_knowledge_source.py`（本包单元层）；**无技能执行用例** |
| 删除 schema 文件的用例 | `grep -rn "unlink()" tests/ --include=*.py` | 只有 `test_activation_plan.py:326/367/379`（删 ontology → 计划门禁被拒）与 `test_provision.py:222`（删**源**的声明 → 供给路径）；**无**"删运行时工作区声明 + 执行已接线技能"的用例 |

⇒ "该组合**今天完全没测**"这一前提**经复核成立** ⇒ §2.7（γ）用例的"**新增补洞**"定位正确。

### 9.6 供给面口径提示（供 TL 同步 D-5 时避免两口径打架）

实测供给**条目**数 = **8**（见 §9.3 的 `assert 8 == 6`）。若按"**类**"计（`activations/` 目录算 **1 类**）则为 **7 类**。
⇒ D-5 若记为"7 类"，建议同时注明"**CLI 条目数 = 8**"，以免与 `新建 N / 覆盖 N / 未变 N` 的**条目**口径冲突。

### 9.7 预跑结论

- 预跑**未改变** B-1 的任何设计结论；**未发现**本包自身的问题（探针、快照流程、报数模板均按 §6 要求产出）；
- 预跑**不构成**冻结证据；**正式冻结跑**待 TL 的新冻结信号，届时按 §6 的 (a)–(h) + R-A…R-F 全量重跑并原文报数；
- 预跑期间**未触碰**任何第三方文件（`provision.py` / `cli/main.py` / `activation_contract.py` / `test_provision*.py` / `activations/**` 均只读）。

---

## 10. B-1 **实施验证记录**（2026-09-16；本片实施交付）

### 10.1 落地清单（HEAD 开工前后一致：`9b79da67`）

```text
M src/kert/application/skills.py                    +249/-3   sha256 1677173cd1170fd6552a589d4e22f1d8ca97cfed47d91c9b9a041daa7fe9efc4
M docs/contracts/schemas/assembly-trace.schema.json  +10/-1   sha256 d8f9b6b6a71c9ed7bb569e755d04e2b3567ddf22d9f6c24d09b1dbb8fa1a434e
                                                              （= 2 个新字段 + assetVersion 双用途澄清一行）
?? tests/unit/test_skills_capability_swap_guards.py    470 行  sha256 648dee8d7e6455f7718bb1c8c6d1ba4ea140387a7f9a83380b113bbe619a5435
?? tests/integration/test_skills_capability_swap.py    401 行  sha256 b4b12bab88145dc6a32441315d7eabbd8c7f59929e0344b7b377445553e11abe
```

### 10.2 四目录原始计数与退出码（含红集逐条 node id）

```text
tests/unit         → 4 failed, 975 passed, exit 1
tests/integration  → 469 passed, 1 xfailed, exit 0      （基线 458 + 本片 11）
tests/contract     → 53 passed, exit 0
tests/recovery     → 18 passed, exit 0
红灯集（两跑一致）:
  tests/unit/test_knowledge_source.py::test_module_wiring_is_limited_to_explicit_whitelist   ← **新增**（2-A 的"尚未接线"门禁，非行为回归）
  tests/unit/test_provision_cli.py::test_apply_then_idempotent_rerun                          ← 基准已有（第三方在途）
  tests/unit/test_provision_cli.py::test_json_output_follows_standard_envelope               ← 基准已有
  tests/unit/test_provision_cli.py::test_init_flag_initializes_fresh_volume_then_provisions  ← 基准已有
```

### 10.3 枚举两跑（原版探针 `/tmp/m71b_impact_probe.py`，sha `d73ce3c6…`）

两跑输出**逐字一致**（仅耗时行不同）⇒ 两跑**交集 == 并集**（R-A 口径成立）。

```text
_route_plan 命中用例数 = 63 = 基线 44（与 §9.4 的"去重用例 = 44"逐字一致） + 本片新增 19
_run_supply_chain     = 3  （不变 ⇒ D 组未接线）
```

> ⚠ **探针口径变更（B-1 结构性影响）**：探针只包 `_load_ki`；B-1 之后三个已接线技能的**生产路径不再经过** `_load_ki`
> ⇒ 其 `load_ki` 计数对这三个技能**结构性失效**（**已定稿为 R-G**，见 §6 第 7 项）。
> 若要用该探针核对"读取路径"，须**同时计数** `_load_ki_from_declaration`。

### 10.4 变异矩阵 V1–V14（全部捕获：基线 rc=0 → 变异 rc≠0 → 恢复 rc=0 + 恢复后 sha == golden）

| 变异 | 捕获用例 | 结果 |
|---|---|---|
| V1 接线后仍走旧隐式路径 | `test_declaration_pattern_is_the_read_driver` | PASS |
| V2 回落被静默吞掉 | `test_declaration_absent_is_visible_but_never_refused` | PASS |
| V3 解析失败不回落 | `test_unavailable_code_differs_from_absent` | PASS |
| V4 把"不可用"当必需并拒绝 | `test_required_flag_does_not_escalate` | PASS |
| V5 能力门禁提前到计划门禁之前 | `test_unprovisioned_workspace_refuses_and_records_why` | PASS |
| V6 新条目字段污染 | `test_trace_field_discipline_and_append_only` | PASS |
| V7 UNAVAILABLE/ABSENT 混码 | `test_unavailable_code_differs_from_absent` + 三态用例 | PASS |
| V8 改 `_load_ki` 本体（成功分支返回 `{}`） | `test_legacy_reader_contract_is_unchanged`（**本片新增**） | PASS |
| V9 读取内容被截断 | `test_alpha_ki_text_equals_reference_provider` | PASS |
| V10 留痕指纹写死 | `test_binding_fingerprint_is_not_hardcoded` | PASS |
| V11 声明缺失即拒绝（B-2 语义提前） | `test_declaration_absent_is_visible_but_never_refused` | PASS |
| V12 出现第 4 个调用点 | `test_new_reader_call_sites_are_exactly_the_three_wired_skills` | PASS |
| V13 新条目插到 `kert` 之前（非追加） | `test_trace_field_discipline_and_append_only` | PASS |
| V14 签名漂移（加 `plan`） | `test_signature_equality_guard` | PASS |

> **V8 的实现期修正**：设计里 V8 的捕获写的是"D 组 3 条行为不变"，**实测该假设不成立** ——
> D 组断言只依赖 `CustomerKnowledgeProvider.supply_chain/interpretation`，**不依赖** `_load_ki` 的返回
> ⇒ 仅靠 D 组**抓不到**"改本体"。故新增 `test_legacy_reader_contract_is_unchanged`：
> 直调本体、钉住三条分支（无投影 / 有投影 / 取数抛异常）的**逐字输出**。这条才是 V8 的真正捕获点。

### 10.5 三条**测量学陷阱**（本片实测踩到，务必写进后续片的测量纪律）

1. **pyc 复用会伪造"恢复后"的跑数**：变异体与目标版本**字节数相同**时（如 V13 的两行挪位），
   `(源文件 mtime 的整秒, 文件大小)` 与旧 pyc 记录相同 ⇒ Python **复用旧字节码**，
   于是"恢复后"实跑的是**变异行为**（本片实测命中一次，表现为恢复跑仍红）。
   对策（且不删任何文件）：每次写入后把 mtime **单调前移**（实测用 `+20s×序号`），使整秒必不同。
2. **外部写入者会回写文件**：`src/kert/application/skills.py` 曾两次在本片**两条命令之间**被写回
   **变异内容**（取证：mtime `02:20:31`，形态符合编辑器缓冲区回写）。
   对策：以 `/tmp` golden 快照为唯一真源 + 每次测量前后强校验 + 不一致即自动回写。
   ⇒ **提交前请用 `sha256sum` 复核该文件 = `1677173c…`**。
3. **量具自伤**：影响面探针在同一进程内把 `_load_ki` 换成**无注解**的计数包装器 ⇒
   纯 `inspect.signature` 互比会把**量具**误判成"签名漂移"（本片实测两次假红）。
   守卫已改为"**源码级(AST)签名相等** + 运行期未被包装"两条断言 ⇒ V14 仍必 FAIL，量具不再致红。

### 10.6 已知边界与"未做"

- `_run_supply_chain` **自身**的 trace 输出不在本片守卫范围（AST 守卫只证"**未接线**"；改该方法属 D 组/后续片议题）；
- `KNOWLEDGE_SOURCE_UNBOUND` 在 B-1 读取路径**不可达**（遍历声明绑定集；计划面判定归 **B-2**）；
- (γ) 夹具必须带 `evidenceTimestamp`，否则 R1 无新证据策略在**取数之前**拦截（走不到读取层）；
- **未做**：未改任何既有测试（唯一新增红 = 2-A 白名单门禁 ⇒ **已由 TL 裁定 (a) 并授权修改**，见 §10.7）；未动 `customer_knowledge.py` / `api/**` / `specs/**` / `deploy/**` / 2-A 声明文件；未 commit、未 push。

### 10.7 TL 裁定落实（A-10 与两项口径修正）与**红集不变量恢复**

| # | 裁定 | 落实内容 | 结果 |
|---|---|---|---|
| 1 | **(a) 授权加白名单一行**（A-10） | `tests/unit/test_knowledge_source.py` 的 `ALLOWED_WIRING` **仅加一条**（含授权引用）：`"src/kert/application/skills.py": "技能执行期读取：声明驱动 KI 读取（TL 授权 M7.1-B1；裁决记录 DECISION_SHEET A-10）"` ⇒ 白名单 4 组 → **5 组** | **红集回到恰好 3 条**（`test_provision_cli.py:53/66/109`，node id 与基准逐条一致）⇒ **不变量恢复** |
| 2 | **T6 表述修正** | §1.5 T6 原表述（"只追加在序列**末尾**"）**明记为由新式取代并写出原因**（取数段之后还有 `model`/`parse` 条目 ⇒ 物理不可满足）；位置约束**已在测试中被断言**（见 §1.5 的 T6 批注）；**未**改为"trace 末尾追加" | V13 实测可捕获 ✓ |
| 3 | **`assetVersion` 双用途澄清**（C-3 追认包） | canonical schema 的 `assetVersion` **补一行 description**："既有的资产/绑定版本槽位；自 M7.1-B1 起亦承载知识源读取的绑定指纹 `binding_sha256`" ⇒ 追认包 = **2 个新字段 + 1 处 description 澄清**（**不新增字段**） | V10 断言 `assetVersion == resolver.binding_sha256` **且改声明后必变** ✓ |

**红集不变量（A-10 后最终四目录，HEAD `88af470d`）**

```text
tests/unit        → 3 failed, 976 passed, exit 1   （红集 == 基准 3 条，逐条一致）
tests/integration → 469 passed, 1 xfailed, exit 0
tests/contract    → 53 passed, exit 0
tests/recovery    → 18 passed, exit 0
ruff check src tests → All checks passed!
```

**变异矩阵复跑（在你要求的"红集回到 3 条"状态上）—— 逐条报该次红集**

每条三段（基线 / 变异 / 恢复）均运行「**基准 3 条红灯 node id + 捕获用例**」：

```text
V1  基线红集=3(==基准) 变异红集=4(=基准3+捕获1) 恢复红集=3  sha==golden ✓
V2  基线红集=3          变异红集=4(=3+1)         恢复红集=3  ✓
V3  基线红集=3          变异红集=4(=3+1)         恢复红集=3  ✓
V4  基线红集=3          变异红集=4(=3+1)         恢复红集=3  ✓
V5  基线红集=3          变异红集=4(=3+1)         恢复红集=3  ✓
V6  基线红集=3          变异红集=6(=3+3，参数化展开)  恢复红集=3  ✓
V7  基线红集=3          变异红集=5(=3+2)         恢复红集=3  ✓
V8  基线红集=3          变异红集=4(=3+1)         恢复红集=3  ✓
V9  基线红集=3          变异红集=4(=3+1)         恢复红集=3  ✓
V10 基线红集=3          变异红集=4(=3+1)         恢复红集=3  ✓
V11 基线红集=3          变异红集=5(=3+2)         恢复红集=3  ✓
V12 基线红集=3          变异红集=4(=3+1)         恢复红集=3  ✓
V13 基线红集=3          变异红集=6(=3+3，参数化展开)  恢复红集=3  ✓
V14 基线红集=3          变异红集=4(=3+1)         恢复红集=3  ✓
```

⇒ **变异只增加其目标捕获用例，从未影响基准红灯集**（每一段的基线/恢复红集都恰为基准 3 条）；
E-1 三重比对基线：golden sha `1677173c…`、`wc -l = 1188`、`git diff --numstat = 249 3`；14 条恢复后 sha 均回原值。

