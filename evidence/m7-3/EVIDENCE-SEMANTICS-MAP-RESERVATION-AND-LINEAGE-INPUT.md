# 证据：本体输入面 / 语义载体 / 预留判定（T1 · T2 · T3）

> Owner 指令：**要看得见的落地**（可跑代码 + 断言 + 测试），不要长方案。
> 本文件只记**口径、判定、可复现命令与原始退出码**；设计理由写在源码 docstring 里。

**行号基准（D-8）**：本文件引用的行号基准——
`route_policy.py` / `knowledge_map.py` = **我本轮修改前**的 HEAD 版；`activation_contract.py` = **工作区未提交版**
（该文件为**他人在途**，我**未碰**）；`customer_knowledge.py` = 当前 HEAD 版。

---

## T1 本体引用 → 物化血缘的「输入面」

**字段口径（键名全部取自既有对象，不新造）** —— `src/kert/domain/ontology_reference.py`：

| 血缘字段 | 来源 | 是否强制比对 |
|---|---|---|
| `contractId` | 本体引用声明 | **是** |
| `contentSha256` | 本体引用声明（64 位小写 hex） | **是** |
| `version` | 计划的 `ActivationPlan.ontology_key`（`<contractId>@sha256:<前16>`） | **是** |
| `authorityRepo` | 本体引用声明 | 否（**必须记录**，但不据以拒绝） |
| `authoritySource` | 本体引用声明 | 否（同上） |

- 容器键 = `ontology`（取自计划既有键名 `ActivationPlan.versions["ontology"]`）。
- **不比对来源路径的理由**：既有 **D-3** 裁定把本体来源路径排除在 `plan_hash` 之外（环境相关）
  ⇒ 血缘必须记录它（可追溯），但跨环境复算不应因此被拒。

**校验入口（新增）**：`check_lineage_ontology(resolution, lineage) -> LineageOntologyCheck`
（码：`OK` / `LINEAGE_ONTOLOGY_REF_ABSENT` / `LINEAGE_ONTOLOGY_REF_MISMATCH`）。
配套 `lineage_ontology_fields(resolution)` 给出**该记的 5 字段**（未放行 ⇒ 返回 `None`，**不写占位串**）。

**判定：拒绝（fail-closed），非告警。理由**：血缘是下游唯一的可追溯凭证；不一致 ⇒
"物化产物与计划同源"**不可证明**（会被静默读成同一本体版本）。本仓对"无法证明一致"一律 fail-closed
（D-4 / 路由 / 计划门禁同口径），且**无消费方核对时告警等于无效**。

**测试**：`tests/unit/test_ontology_lineage_consistency.py`（6 passed）
正例 1（逐字一致 ⇒ 放行）+ 反例 2（强制项被改 ⇒ `MISMATCH`；缺必记字段 / 缺块 ⇒ `ABSENT`，参数化 ×3）
+ 口径反例 1（`authoritySource` 变化 ⇒ **仍放行**）。

**现状缺口（写入侧待 c20 落）**：`ingest.py:199-233 _write_lineage` 目前写
`schema/lineage_id/process_id/job_id/inputs/outputs/transformation_id/...`，**尚无** `ontology` 块。
⇒ 校验入口已就绪，c20 在血缘 Front Matter 加 `"ontology": {...}`（上表 5 键）即可对接。

---

## T2 业务语义：载体断言 + 判定

**① 载体是谁（可执行断言）** —— `tests/unit/test_semantics_carriers_and_reservations.py`：

- 载体 = **KI 标题（语义键）+ 正文（语义载荷）**，在**真实投影**上验证（`CustomerKnowledgeProvider.ki_map`：
  7 条 KI 的 `title` 与 `customer_knowledge.KI_ITEMS` 逐字一致、`content` 非空）；
- 读取绑定 = **声明驱动**：`knowledge_sources.json` 的 `readContract.assetMatch.pattern`（命名分组
  `assetRefId`/`title`）去掉命名后必须与既有隐式约定 `customer_knowledge.py:31` 的 `^(KI-[\w-]+)\s+(.+)$`
  **逐字等价**（防两套语义口径漂移）。

**② `semanticQueries` / `ruleChecks` 判定 = 预留（不为接线而接线）**

- **已解析**：真实合同 `examples/.../activations/AC-*.json` 二者**非空**（`activation_contract.py:288-289` 载入）；
- **无消费者**：`src/kert/**` 内**零**处访问 `semantic_queries` / `rule_checks`（除定义文件）；
- **不接线的理由**：既无求值语义（谁判定、判定失败如何影响执行？R1/R2 策略里**没有**这两组引用的位置），
  也无数据源；接上只能"收下不消费" ⇒ 属于**为接线而接线**。
- **落地形式**：本判定写成本文件的正式记录 + 两条**漂移守卫**（出现消费者 ⇒ 测试变红）。
  ⚠ `activation_contract.py` 属**他人在途**，故"源码注释标注预留"一项**未落**（见"未做"）。

---

## T3 知识地图遍历判定 = 预留

- `knowledge_map.py:291 resolve_for_task`：src 侧唯一调用者是
  `route_policy.py:311 resolve_via_registry_only` → 后者**生产代码零调用点**（唯一调用者为单测）；
- 地图参与路由的正规路径是 `RouteResolver.load/resolve`（策略规则 → `registry.get(map_id)` + 双侧一致性校验）；
- **不接线的理由**：用它放行 = **跳过 route_policy 治理面**；而"按任务取候选地图"目前**没有**真实消费场景
  （计划/执行期都已有策略+规则给出的地图）。⇒ 预留。
- **落地形式**：两处 docstring **已写入** `判定：预留（未接线）` 及理由；配套漂移守卫：
  `test_map_task_traversal_has_no_production_call_site`（白名单外出现调用点即红，并逐字钉住
  `route_policy.py` 内那处调用**只在预留包装器体内**）+ `test_reserved_apis_carry_the_reservation_marker_in_source`。

---

## 原始退出码与命令（E-11：含环境身份）

```text
环境: .venv/bin/python → Python 3.12.8 ; pytest 9.1.1 ; addopts=["-q","-m","not perf"]（不得再显式加 -q）
新增两文件:
  .venv/bin/python -m pytest tests/unit/test_ontology_lineage_consistency.py \
      tests/unit/test_semantics_carriers_and_reservations.py -o addopts="" -p no:warnings
  ⇒ 12 passed, rc=0
四目录（未经管道直取 rc）:
  tests/unit        → 3 failed, 988 passed, rc=1   （红集 == 既有 3 条 test_provision_cli，非本片）
  tests/integration → 481 passed, 1 xfailed, rc=0
  tests/contract    → 53 passed, rc=0
  tests/recovery    → 18 passed, rc=0
ruff check（5 个文件）→ All checks passed!
```

---

## 未做与风险

1. **`activation_contract.py` 的"预留"源码注释未落**（该文件他人在途）⇒ 请 Owner/TL 指派归属，
   或授权我加一行注释；本文件 + 两条守卫测试已提供等效的可执行钉住。
2. **血缘写入侧未落**（`ingest.py` 由 c20 负责）⇒ T1 目前只交付**口径 + 校验入口 + 测试**；
   端到端"产物带本体字段"待 c20 接线后由其对拍（我已把 5 个键名与判定口径发给 c20）。
3. **风险**：T2②/T3 的守卫是**白名单式**断言 —— 日后真接线时它们会变红，这是**设计意图**
   （强制同步更新判定与证据），不是缺陷；接线方须同时更新本文件。
