# 投影说明：FINANCING 流动资金融资

> 状态块：
> - **CANDIDATE**
> - **FROZEN=NO**
> - **IMPLEMENTED=NO**
>
> 本文件是投影**规格说明**，描述 `03_core` 产品卡到 `04_serve` 各投影形态的映射约定；实际投影数据（Kùzu 图、向量、数据集）由 `dkws` CLI 链路生成（Gate 0 限定项），本包不物化。

## 1. 投影形态总览

| 投影形态 | 说明 | 本包是否物化 |
|---|---|---|
| 实体（entity） | ProductFamily / Product / ProductVersion | 否（规格说明） |
| 关系（relation） | offersCapability / hasVersion / prerequisiteOf / mutuallyExclusiveWith / evidenceRef | 否（规格说明） |
| 声明（statement） | 产品能力、准入/排除/禁止用途、销售边界等结构化断言 | 否（规格说明） |
| 片段（segment） | 权威材料条款片段（源材料上传后切分） | 否（待源材料） |
| 向量（vector） | 能力/场景/准入的语义向量 | 否（CLI 生成） |
| 规则（rule） | PRODUCT_VERSION_ACTIVE 等 RuleBundle 规则引用 | 否（见 rules/README.md） |
| 数据集（dataset） | 有效产品全集 ProductUniverse 快照 | 否（CLI 生成） |
| 图谱（graph） | Kùzu 图（可重建投影层） | 否（CLI 生成） |

## 2. 实体映射约定

| 实体类型 | ID 约定 | 来源字段 |
|---|---|---|
| ProductFamily | `FAMILY-FINANCING` | 产品卡 `product_family` |
| Product | `PROD-FIN-001/002/003` | 产品卡 `product_id` |
| ProductVersion | `{product_id}@{version}` | 产品卡 `product_id + version` |

## 3. 关系映射约定

| 关系 | 方向 | 依据 |
|---|---|---|
| `hasVersion` | Product → ProductVersion | 产品卡 `version`（INV-01 不可变） |
| `offersCapability` | ProductVersion → 能力声明 | 产品卡「产品能力」节 |
| `prerequisiteOf` | 前置产品 → 目标产品 | 产品卡「前置产品」 |
| `mutuallyExclusiveWith` | 互斥产品对 | 产品卡「互斥产品」 |
| `evidenceRef` | ProductVersion → 源文件/条款 | 产品卡「EvidenceRef」节 → `01_raw/source-registry.md` |

## 4. 规则与有效性投影

- `PRODUCT_VERSION_ACTIVE`：由 `effective_from/effective_to/status` 判定有效版本（`Active(ProductVersion)=false → 不得进入正式候选`，INV-01）。
- 硬约束规则（准入/排除/禁止/互斥）以 `03_core` 产品卡断言为输入事实，RuleBundle 独立版本治理（见 `skills/product-recommendation/rules/README.md`），本包不重复定义。

## 5. 投影可重建性

投影可由 `03_core/financing/version=2026.08.31.1/product-cards/*.md` 全量重建；任一投影缺失仅致 `04_serve` DEGRADED（健康检查语义），不影响 `03_core` 权威源。
