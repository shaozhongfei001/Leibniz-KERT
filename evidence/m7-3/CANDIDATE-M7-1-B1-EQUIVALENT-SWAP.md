# CANDIDATE：M7.1-B1 等价替换实现方案（真实能力适配器 **不改变语义**）

```text
DOC_ID   : CANDIDATE-M7-1-B1-EQUIVALENT-SWAP
VERSION  : v1.1（2026-09-16：按 TL 收紧 —— 新增**等价前提硬规则 E0**、回落用例 §2.7、变异 V11、白名单改为"新文件 only"）
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

- **新增** `SkillExecutionService._load_ki_via_capability(customer_id, plan, trace) -> dict`（名可议）；
- 由 `_run_outreach` / `_run_meeting` / `_run_previsit` 三处**显式调用**（替换各自第 720/753/786 行的 `_load_ki` 调用）；
- `_load_ki`（`:504-521`）与其唯一剩余调用方 `_run_supply_chain`（`:818-823`）**保持一字不改**。

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

### 1.3 失败处置：B-1 **一律软失败 + 具名留痕**（不改拒绝语义）

B-1 中，能力侧四类解析失败**均不阻塞**、**均产出一条具名留痕**，且**不产生任何 KI 级拒绝**：

| 情形 | B-1 行为（本片） | 具名依据 | B-2 才会改为 |
|---|---|---|---|
| 声明缺失 | 沿用旧路径读取（等价 α），留 `KNOWLEDGE_SOURCE_DECLARATION_ABSENT` | `knowledge_source.py:CODE_DECLARATION_ABSENT` | 拒绝 |
| 声明非法 | 同上，留 `..._DECLARATION_INVALID` | `CODE_DECLARATION_INVALID` | 拒绝 |
| 能力不可用（投影缺失） | 沿用旧路径（＝返回空 dict，与今天逐项相同），留 `..._UNAVAILABLE` | `CODE_UNAVAILABLE` | 拒绝 |
| 某 assetRefId 未绑定 | 该条照常 `skipped`（今天行为），留 `..._UNBOUND` | `CODE_UNBOUND` | 拒绝（B-2，且受 R-2 约束） |

> **B-1 的收益**：读取机制真的换成"声明驱动"（可被 §3.4 的双向证据证明），而**拒绝语义一点没变** ⇒ 部署侧无需任何前置条件，可在 B-2 之前独立上线。

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
| T4 | `phase` / `status` 只能取 canonical 枚举值 | `docs/contracts/schemas/assembly-trace.schema.json:18-31`（phase）、`:35-44`（status）；该文件 `:107` `additionalProperties: true` ⇒ **新增字段合法**，但枚举值不可越界 |

⇒ 建议形态（示例，字段名待定稿）：`{"phase": "evidence", "status": "ok"|"degraded", "capabilityId": "KS-CUSTOMER-KI-PARQUET", "sourceCode": "KNOWLEDGE_SOURCE_UNBOUND", "message": "知识源能力解析结果…"}`（`message` 不含 `KI-`）。

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

# 2) 技能产出：除"新增留痕条目"外逐字段相同（最强形式）
def _strip_new(entries):  return [e for e in entries if e.get("capabilityId") is None]
assert _strip_new(r.assembly_trace) == _strip_new(r_ref.assembly_trace)
assert r.data == r_ref.data and r.status == r_ref.status

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
# 用同一工作区的三种声明形态分别断言，拒绝码/留痕码必须互不相同
assert codes(无声明) == {KNOWLEDGE_SOURCE_DECLARATION_ABSENT}
assert codes(声明含未声明字段) == {KNOWLEDGE_SOURCE_DECLARATION_INVALID}
assert codes(删除 04_serve/customer_knowledge/CURRENT.md) == {KNOWLEDGE_SOURCE_UNAVAILABLE}
```

---

## 3. (ii) 变异点清单（每项：变异 → 期望 FAIL → 捕获用例）

| ID | 变异（实现侧） | 期望结果 | 捕获用例 |
|---|---|---|---|
| **V1** | 接线后仍走旧的隐式路径（新方法内部直接调 `ki_map`，不过声明） | FAIL | §2.5 方向 A/B；§2.2-3 |
| **V2** | 声明缺失被**吞成 skipped**（无具名条目、无 `sourceCode`） | FAIL | §2.4 末行（`codes == {…ABSENT}`） |
| **V3** | 未绑定时**回落**（读全部资产 / 读字面量） | FAIL | 未绑定夹具：该条必须 `skipped`、其余条数不变、`ki` 与 `ref_ki` 仍等价 |
| **V4** | `required` **顺带升格**（true ⇒ 拒绝、false ⇒ skipped） | FAIL | §1.4 的"两侧结果必须相同"断言 |
| **V5** | 能力门禁**提前**到计划门禁之前 | FAIL | C 组 3 条既有用例（拒绝码须仍为 `ROUTE_UNRESOLVED` / `ROUTE_POLICY_ABSENT` / `ONTOLOGY_REFERENCE_INVALID`） |
| **V6** | 新条目带 `mapId` / `kiId` / `message` 含 `KI-` | FAIL | 新增守卫用例：`_route_entry(trace)` 仍须选到**路由**条目；`all("skipped" in m …)` 等价断言 |
| **V7** | 把 `UNAVAILABLE` 与 `ABSENT` 混为同一码 | FAIL | §2.6 三态可区分 |
| **V8** | 改 `_load_ki` 本体（波及 `_run_supply_chain`） | FAIL | D 组 3 条行为不变 + 新增"调用点集合 == {outreach, meeting, previsit}"机械断言 |
| **V9** | 读取内容被改写（strip/截断/去重/改 title） | FAIL | §2.2-1 逐字节断言 |
| **V10** | 留痕中的能力指纹写死（常量 / 与 `resolver.binding_sha256` 不符） | FAIL | 断言指纹 == `KnowledgeSourceResolver.load(ws).binding_sha256`，且**改声明后必变** |

> 变异执行方式沿用前两片：临时改实现 → 期望非零退出码 → 恢复并校验 sha256 一致。**恢复后 sha256 与变异前逐字节相同**为本片证据的一部分。

---

## 4. (iv) D / E 两组如何处理

### 4.1 D 组：**不接线**，并加机械守卫

- `_run_supply_chain`（`skills.py:818-823`）与其调用的 `_load_ki`（`:820`）**不动** ⇒ 3 条 D 组用例（`TestSupplyChainFromLibrary::test_graph_complete_from_library`、`::test_graph_partial_unknown_customer`、`TestSecondCustomer::test_graph_complete_from_library`）行为不变。
- 新增机械守卫：**断言新方法（`_load_ki_via_capability`）的调用点集合恰为 `{_run_outreach, _run_meeting, _run_previsit}`**（源码扫描，同前两片的门禁风格）。若有人日后把它塞进 `_load_ki`，本用例变红。
- **一致性债照旧登记**：`bank-front-supply-chain-graph` 仍走"字面量 KI-FRONT-001/002/003"（`:821-823`）⇒ 本项目**不得**表述为"客户知识读取已全部接线"。

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
| 5 | **不改** `api/**`、`specs/**`、`docs/contracts/**`、`deploy/**` | 边界 |
| 6 | **不改** `application/provision.py`、`domain/knowledge_source.py` | 2-A 已完成供给；B-1 只**消费**该模块 |
| 7 | **不做**"按计划资产裁剪读取"、**不做**"未绑定/声明缺失 ⇒ 拒绝" | 都会改变行为（§1.2/§1.3），属 B-2 |
| 8 | **不升格** `required` | R-2 裁定；§1.4 |

**B-1 实施阶段（另需授权）预计触碰的文件（文件级白名单）**：

```text
src/kert/application/skills.py                 （新增 1 个方法 + 3 处调用替换）
tests/unit/test_skills_capability_swap.py      （新增：等价性/守卫/变异配套用例）
tests/integration/test_skills.py               （仅当新增用例需放在既有夹具旁；**不改既有断言**）
```

---

## 6. 冻结态复测要求（纪律，TL 明确要求）

**本方案的"0 条既有用例变化"结论尚未成立**，因为它依赖的实跑发生在**并发期**（c20 在途改 `src/kert/api/server.py`，+29 行）。并发期跑数不可归因。故：

1. 等 TL 告知 c20 批次落定；
2. 在 **HEAD 冻结态**重跑：`git status --short`（须干净或仅有本包改动）→ 记录 `git rev-parse HEAD`；
3. 重跑影响面枚举并留证：

```bash
.venv/bin/python /tmp/m71b_impact_probe.py            # 重建 44 条枚举与 A/B/C/E/D 分组
.venv/bin/python -m pytest tests/unit tests/integration tests/contract tests/recovery \
    -p no:warnings -o addopts="" -q                    # 全量原始计数与退出码
```

4. **只有冻结态复跑后**，才可在 B-1 验收材料中写"0 条既有用例变化"；此前该结论一律标注为**"待冻结态确认"**。

---

## 7. 风险与回滚

| 风险 | 缓解 |
|---|---|
| 新增 trace 条目撞既有断言 | §1.5 的 T1-T4 + V6 守卫用例（三条反推证据均已落到具体行号） |
| 误伤 D 组（改到 `_load_ki` 本体） | §1.1 只新增方法 + §4.1 调用点机械守卫 + V8 |
| `required` 顺带升格 | §1.4 两侧结果必须相同的断言 + V4 |
| 等价性只证了"看起来一样" | §2.2 给出逐字段/逐字节/去新条目后全等三种形式；§2.5 给双向证据 |
| 部署顺序 | B-1 **不需要**任何部署前置（不改变拒绝语义）；声明已随 2-A 供给，缺/非法在 B-1 下都不阻塞 |

**回滚**：单 commit revert（只涉及 `skills.py` + 新测试文件）⇒ 读取回到 `ki_map` 路径；声明留在卷里**完全惰性**（与《影响面分析》§4.3 一致）。

---

## 8. 待确认事项（供 TL 定稿）

| ID | 待定 | 建议 |
|---|---|---|
| Q1 | 新增方法的**命名**（`_load_ki_via_capability` / `_load_ki_planned` / `_load_ki_bound`） | 取 `_load_ki_via_capability`，并在 docstring 写明"经控制面声明的能力读取；B-1 阶段失败一律软失败" |
| Q2 | 新 trace 条目的**字段名**（`sourceCode` 是否合适；是否同时带 `capabilityId`） | 用 `capabilityId` + `sourceCode`；`message` 严格不含 `KI-`（T3） |
| Q3 | 未绑定留痕的**粒度**：每次执行一条汇总，还是每资产一条 | **每资产一条**（可定位到具体 assetRefId），但必须遵守 T1（无 `kiId`） |
| Q4 | B-1 是否**同时**新增"调用点集合"机械守卫文件 | 是（与既有 `ALLOWED_WIRING` 门禁同风格的源码扫描） |
| Q5 | 实施是否等冻结态复测完成后再开始 | 建议**先做冻结态复测**（§6），再派工实施，避免"以并发期数据为依据" |
