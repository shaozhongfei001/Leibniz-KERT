# 04_serve：投影层

> 状态块：
> - **CANDIDATE**
> - **FROZEN=NO**
> - **IMPLEMENTED=NO**

## 语义

`04_serve` 是 DKWS 五层工作区的**投影层**：把 `03_core` 权威产品卡投影为可查询/可计算的形态（实体/关系/声明/片段/向量/规则/数据集/图谱，见 `ADR.md` IMP-ADR-011）。投影为**可重建层**，权威源仍在 `03_core`，投影可随时由 `03_core` 重建。

## 本包内容

- `projection.md`：FINANCING 产品卡的投影规格说明（映射到实体/关系/规则/数据集/图谱的字段与 ID 约定），**非**实际投影数据文件。
- 实际 Kùzu 图谱/向量/数据集投影由 `dkws` CLI 链路生成（Gate 0 限定项），本包不物化。

## 与权威源的关系

投影层不新增权威事实；一切事实以 `03_core/financing/version=*/product-cards/*.md` 及 `01_raw/source-registry.md` 引用的源材料为准。投影仅改变形态（便于检索/推理），不改变内容。
