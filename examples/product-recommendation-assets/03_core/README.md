# 03_core：权威产品卡层

> 状态块：
> - **CANDIDATE**
> - **FROZEN=NO**
> - **IMPLEMENTED=NO**

## 语义

`03_core` 是 DKWS 五层工作区的**唯一权威源**。产品卡作为权威结构化投影落在此层，按 `<domain>/version=<版本号>/` 组织，版本目录**发布后不可变，只可退役**。

## 本包内容

- 产品族域：`financing/`（对应产品族 FINANCING 流动资金融资）。
- 版本目录：`financing/version=2026.08.31.1/`（候选示例，`status=CANDIDATE`）。
- 产品卡：`financing/version=2026.08.31.1/product-cards/{PROD-FIN-001,PROD-FIN-002,PROD-FIN-003}.md`。

## 与发布机制的关系（如实）

正式 DKWS 发布由 `src/dkws/application/publish.py` `Publisher.publish` 完成（收集 APPROVED 候选 → G3 门禁 → 写临时版本目录 + RELEASE.md（SHA-256 清单）→ 全量重读校验 → 原子提交 → 原子更新 CURRENT.md 指针）。本包为**静态示例**，`RELEASE.md`/`CURRENT.md` 为人工按同构规则预填（`status=CANDIDATE`），**待 dkws CLI 链路正式落库（Gate 0 限定项）**后由 CLI 重算覆盖。
