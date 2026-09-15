# TL 裁定：M7.1 第一片（M7.1-A）授权与边界

```text
DECISION_ID : M7-1-A-AUTHORIZATION
DECIDED_BY  : Tech Lead
DECIDED_AT  : 2026-09-16
依据        : docs/governance/KERT_PENDING_OWNER_DECISION_M7_EVOLUTION_V1.0.md §0（D1-A）
              WBS §M7.1；设计候选 evidence/m7-3/CANDIDATE-M7-1-KNOWLEDGE-SOURCE.md
受文        : m71-knowledge-source（设计候选作者）
```

## 1. 裁定 O-1（绑定指纹是否进计划/是否触碰 planHash）

**采纳 O-A：第一片不动 `planHash`。**

理由：`planHash` 是"可重放计划"的**锚**，其输入语义已由 Contract Owner 追认（v1.5）。
把"资产→能力绑定指纹"纳入 `plan.versions` 或 hash 输入，属**合同级语义变更**，
不得作为第一片的附带产物发生。

**若**后续确需（例如绑定关系影响读取结果的可重放性）⇒ 走 **O-B：单独合同提案**，
由 Contract Owner 追认后才能进 hash；提案须给出"hash 输入变更对既有计划的影响"分析。

## 2. 裁定 O-5（第一片是否在 D1-A 授权内）

**判为在内**，附 4 条硬边界（超出任一条即须停下来先提案）：

| # | 边界 |
|---|---|
1 | **只读、不接线**：`src/kert/application/skills.py`、`src/kert/api/server.py`、任何端点、任何合同文件**零改动**；第一片不得改变任何既有运行时行为（现有测试须行为零变化） |
2 | `KNOWLEDGE_SOURCE_*` 拒绝码第一片**只存在于内部对象**（`ReadResult | ReadDenial`），**不得**经 API/错误体暴露 —— 避免未经追认扩合同错误码面 |
3 | 能力清单放 `90_control/schema/knowledge_sources.json`（与 `route_policy.json`、`ontology_reference.json` 同址，有先例、无需规格修订）。**警告**：`90_control/catalog/` 已被两类东西占用（`KM-*.json` 与管道 `asset_catalog` 的 `*.md`），**不得**往该目录新增文件 |
4 | 若实施中发现需要改合同 / 端点 / 规格 / 新增依赖 ⇒ **停下报告**，不得自行扩面 |

## 3. 裁定 O-6（仓内技能包资源是否纳入）

**不纳入第一片。** `examples/bank-front-skills/**` **不在工作区内**，属另一权威域（技能包）；
纳入会破坏"控制面声明只绑定**工作区**权威"的口径。留作后续独立议题。

## 4. 附加要求（TL 从核实中得出，必须落实）

1. **命名歧义必须消除**：仓内 `asset_id` 已有**两套含义** ——
   ① 管道资产台账（`src/kert/domain/contracts/specs.py:392-399`、`application/publish.py:232-283`、
   `90_control/catalog/<asset_id>.md`）；② 计划资产引用（`ActivationPlan.assets`）。
   新模块**不得**复用裸名 `asset_id` 指代计划资产；须用可区分的词汇
   （如 `asset_ref_id` / `bound_asset_id`）并在模块 docstring 中显式写清与①的区别。
2. **隐式绑定必须显式化并留证据**：现状 assetId 与数据的关联靠
   `customer_knowledge.py:31,59-68` 的 `heading_path[0]` 正则 `^KI-([\w-]+)\s+(.+)$` 隐式约定。
   第一片须把该隐式约定**升级为可校验的显式绑定**，并给出反例（heading 不符 ⇒ 具名拒绝码）。
3. **失败分野按设计候选 O-2 执行**：能力解析失败（未绑定/歧义/声明非法/能力不可用）⇒ **fail-closed 拒绝**；
   数据未命中 ⇒ 维持 v1.3 `ok/skipped`（不扩义）。
4. **变异自证必交**：设计候选的 M1–M11 中至少覆盖 M7（"码恒置 OK"）与 M10（负例夹具缺失即 FAIL），
   并附**恢复后 sha256** 与"基线 PASS → 变异 FAIL → 恢复 PASS"原始退出码。

## 5. 授予的实施范围（仅此）

```text
可新增：90_control/schema/knowledge_sources.json（受控 example 工作区）
        src/kert/domain/knowledge_source.py
        tests/unit/test_knowledge_source.py（或等价命名）
不可改：src/kert/application/**  src/kert/api/**  specs/**  docs/contracts/**
        deploy/**  scripts/**（除本包明确允许）
```

## 6. 非声明

本裁定**不是** Contract Owner 批准、**不是**基线签署、**不是** ADR；
不代表 M7.1 完成（仅授权第一片：绑定解析链，**不含真实数据读取、不含接线**）；
未授权 O-2 之外的任何语义升级；`PRODUCTION_RELEASE_GATE=BLOCKED` 不变。
