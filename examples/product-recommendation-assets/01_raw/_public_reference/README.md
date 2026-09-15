# `_public_reference/` 公开参考区

> Loop PI-0 G0-3 建立。`usage: VERIFICATION_ONLY`

## 用途

存放公开可得资料。**唯一合法用途是验证解析器能否读取源材料**——只验证「读得出来」，
不验证「内容对不对」。

## 证据能力上限

- **不得作为任何产品卡字段的权威依据**
- 引用本区证据的产品卡**永久停留 `CANDIDATE`**，门禁自动阻断，无需人工判断
- `authorityLevel` 取 `PUBLIC_PRICE_DISCLOSURE` 或 `PUBLIC_MARKETING`

## 为何公示价目可信却仍归此区

监管强制公示的服务价格目录可信度不低，但：
1. 只覆盖收费维度，无法提供准入/排除/前置产品等 HardRule 字段；
2. 我们引用的是他行公示材料，不是本机构制度。

**可信 ≠ 可作为我们产品卡的权威依据。**

## 合规约束（调研 C-2）

- 仅作内部研发的解析能力验证，不向外分发
- 不得将来源机构名称写入产品卡或 taxonomy 数据字段
- 产品卡 `institution` 统一标注 `DEMO-BANK`

## 当前状态

> L03 订正 2026-09-05：原表述「待 G0-5 入库」已过时，两份均已入库。

| sourceId | 状态 | bytes | SHA-256 | 抽出条目 | unknownFieldRate |
|---|---|---|---|---|---|
| PUB-PRICE-001 | `AVAILABLE` | 195967 | `fa276e30c4e3ae115920703d10cd89a143630ac298d4c1fdb1c885502170303e` | 24 | 0.119 |
| PUB-PRICE-002 | `AVAILABLE` | 285717 | `e84eaf2617308415663527ab871b99e4e6a49a159ed93b8c042e4e68acc01846` | 20 | 0.76 |

**红线复述**：本区 44 条证据 100% `usage=VERIFICATION_ONLY`，
永远不得支撑本机构字段、HardRule、`INTERPRETATION_READY` 或 `RECOMMENDATION_READY`。

**provenance 缺口（F-L00-10）**：两份文件的来源 URL、抓取方式、时点快照均
`UNVERIFIED`，来源可复现性标 `CONFLICTING_EVIDENCE`。在补齐前 AT-PI0-004 保持 PARTIAL。
