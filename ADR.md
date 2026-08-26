# DKWS 实现架构决策记录（ADR）

> 规格 §20.1 第 12 条：发现规格冲突或需要裁决时记录 Architecture Decision，不得静默选择。
> 本记录补充规格 §22 的规格级 ADR，记录实现过程中对开放点的裁决。

| ADR | 决策 | 理由 | 影响 |
|---|---|---|---|
| `IMP-ADR-001` | CSV 空字段（`''` 或 null）统一按"缺失"处理（REJECT 策略生效） | PyArrow 对空字段的类型推断不稳定（string 列→''，其他→null），业务语义一致 | 清洗拒绝逻辑对 `''` 与 null 等价；§8.6 空串语义在加工层放宽为缺失 |
| `IMP-ADR-002` | `SERVICE` 类型 CURRENT 指针的 scope_id 允许小写 snake_case（服务目录名）或大写服务 ID | 规格 §21 样例目录为 `04_serve/product_knowledge/`（小写），而 §8.2 ID 规范为大写 | CURRENT_SPEC 校验同时接受两种形式 |
| `IMP-ADR-003` | 同名实体候选按"文档"维度保留（跨文档同名生成独立候选），重复检测与消歧在审核阶段进行 | 规格 §11.7 要求"重复实体、别名、业务键检查"在审核流程执行；抽取阶段合并会掩盖重复 | 抽取器不跨文档合并；Reviewer 通过 APPROVE/REJECT/MERGED 消歧 |
| `IMP-ADR-004` | 关系/规则候选的抽取上下文使用 `x_extraction` 扩展字段（§8.5.9），实体保留规格定义的 `extraction` 字段 | 规格 §9.6/9.8 字段表未定义 extraction，但 FR-KNW-002 要求记录抽取上下文 | 扩展字段以 `x_` 前缀合法，读取器忽略 |
| `IMP-ADR-005` | 否定声明（如"产品C不可申请"）表达为布尔谓词 `eligible=false`（value_type=BOOLEAN） | §9.7 强制 object_id/object_value 必须且只能一个非空，否定无对象值 | 语义以结构化布尔表达，正文保留自然语言 |
| `IMP-ADR-006` | 无外部模型时使用确定性哈希嵌入（`deterministic_hash_embedder`）生成向量投影 | §1.6/6.3 要求无模型配置时仍可完成端到端测试；向量仅为检索投影（§2.2 不变量 7） | vectors.parquet 可重建、可溯源；查询向量同构派生 |
| `IMP-ADR-007` | 发布默认自动更新 Core CURRENT.md（规格 §11.8 步骤 10"若策略要求"） | 演示与单工作区场景下无独立策略层 | 回滚仍仅切换指针，不删除版本 |
| `IMP-ADR-008` | 断言式门禁（G3/G4）在 application 层执行并写入任务质量摘要；门禁报告（GATE_REPORT.md）由验收阶段生成 | 规格 §17.4 Gate 报告为验收产物；实现门禁逻辑先行 | 每任务质量摘要记录门禁通过情况 |
| `IMP-ADR-009` | 规则 AUTOMATIC 模式默认禁止（§9.8 extra 校验） | OD-006 推荐默认全部 ADVISORY/HUMAN_CONFIRM_REQUIRED | 样例规则均使用 ADVISORY |
| `IMP-ADR-010` | 数据集投影在 Serve 构建时从最近一次数据 run 复制规范化 Parquet | §10.7 datasets 属于 Serve 投影；数据发布链路（Core 数据集）留待后续 | query-data 服务直接读取 Serve datasets/ |

## `IMP-ADR-011`（2026-08-21，受控变更，Owner 确认方案 B）

**决策**：在 DKWS 平台内引入 **Kùzu 嵌入式图数据库**作为**知识图谱查询加速层（投影）**，
非权威事实源。本决策是 DKWS-SPEC-001 §1.5/§2.2/§6.3/§15.4/ADR-002/§18.5 的**受控豁免**。

**理由**：业务方确认需要"供应链多级溯源/递归闭包/路径枚举/图+属性聚合"类查询，
现有文件化图谱（内存邻接 BFS，depth≤3 硬上限）不可/难表达；原型实测（`scripts/kuzu_prototype.py`）
证明 Kùzu Cypher 单条语句毫秒级完成 4 类查询（选型见 `docs/graph-db-selection.md`）。

**边界（强制）**：
1. 图库只从 `03_core` 活动投影构建，位置 `04_serve/<service>/version=*/graph/`（可重建层）；
2. **禁止**图库进入 `01_raw/02_work/03_core`；`03_core` 仍是唯一权威源；
3. 查询结果必须回传权威 ID + 证据引用（`relation_id/statement_id/effective_from/to`）；
4. 图库纳入 §18.4 可重建性测试（删除后仅凭 Core 重建，逻辑指纹一致）；
5. 图库不在"无持久化数据库文件"验收豁免之外——它在 `04_serve` 可重建投影内，验收口径更新为
   "无隐藏持久化数据库文件（图库为声明式可重建投影，见 PROJECTION.md）"；
6. 若 kuzu 不可用/构建失败，`services.graph()` 自动回退内存邻接实现（fail-open）。

**影响**：新增依赖 `kuzu`（MIT）；`04_serve` 新增 `graph/` 投影；`graph()` 能力扩展（不限深度/闭包/路径）。
