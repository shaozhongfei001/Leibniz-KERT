# 任务包：M7.1 KnowledgeSource typed capability **设计候选**

```text
TASK_ID    : M7-1-KNOWLEDGE-SOURCE-TYPED-CAPABILITY-DESIGN
派发人     : Tech Lead
授权依据   : 用户指令"尽快进化完成 KERT 体系内的…语义层到数据源连接的完整实现"经 Owner 裁定为
             **D1-A**（可实施 M7 零冲突子集）；WBS §M7.1；状态基线
             `docs/governance/KERT_STATUS_BASELINE_CANDIDATE.yaml` → `multi_knowledge_source_framework: DESIGNED_NOT_IMPLEMENTED`
性质       : **只读设计**（不实施、不改代码）
约束       : **不引入 LightRAG 具名技术**（裁定 **D2-A**）；**不内置本体**（裁定 **D3-A**）
```

## 1. 目标

`evidence/m7-3/CANDIDATE-M7-1-KNOWLEDGE-SOURCE.md`，须含：

1. **现状事实清单（带证据行号）**：KERT 今天"取数"实际走哪些通道 ——
   文件目录权威源（`03_core`/`04_serve`）、Parquet 投影、Kùzu 图（`infrastructure/graph/kuzu_builder.py`）、
   SQLite Runtime Store（`infrastructure/stage_store.py`、ADR-012）、客户知识库
   （`application/customer_knowledge.py`）；各自**读取入口与权威级别**。
2. **typed capability 模型**：KnowledgeSource 的类型化能力面（例如
   `capability_id` / `declared_types` / `read(query) -> EvidenceRef[]` / `version` /
   `freshness` / `fail_closed 语义`），说明**为什么是类型化能力而不是插件**；
3. **与 M7.3 的衔接**：计划（`ActivationPlan.assets`）如何经 KnowledgeSource 落到真实数据源，
   即"资产 id → 数据源能力"的解析链；失败时如何保持既有 fail-closed 口径
   （默认拒绝、无第三态、拒绝码可区分）；
4. **契约面影响**：是否需要新端点或新 schema（若需要，只给**提案**，不改合同）；
5. **验证计划**：可执行的验收用例清单（含反空转与变异自证要求）；
6. **分期建议**：最小可交付第一片（≤1 个可审查原子）。

## 2. 硬性边界

- **只写设计文档**，不得改 `src/**`、`tests/**`、`specs/**`、`docs/contracts/**`；
- 不得引入 LightRAG 或任何"具名检索引擎"作为实现路径（D2-A）；
- 不得建立第二份本体权威（D3-A）；不得修改 GITS 仓；不得 push；
- 每个"现状"结论必须有**代码/文档证据行号**，禁止凭印象断言。

## 3. 非声明

不是实施授权、不是 ADR、不是 Contract Owner 批准；不代表 `PRODUCTION_RELEASE_GATE` 变化。
