---
activationContract: AC-PRODUCT-RECOMMEND-001
name: 产品推荐三段式决策
taskType: PRODUCT_RECOMMENDATION_DECISION
routeMode: ONTOLOGY_THEN_MAP
defaultPolicy: DENY
failurePolicy: FAIL_CLOSED
humanGate: HG-D01
---

# AC-PRODUCT-RECOMMEND-001 激活合同

一次面向特定客户、特定 Need、特定输入快照的产品推荐运行。产出为产品适配/组合子方案，供 G2 专家设计与建议书装配消费。

## 激活顺序

1. 客户事实、关系、交易与 Interaction 资产；
2. 产品卡、产品版本、产品能力与销售边界；
3. 产品准入、排除、前置、互斥与组合规则（RuleBundle）；
4. SP-02 上下文装配；
5. SP-07 证据充分度校验；
6. SP-15 产品适配与综合方案（三段式执行）；
7. KERT 输出技术结果，由 GITS 创建 HG-D01。

## 复用与新鲜度

- 若已有同一客户、同一 `asOf`、同一权限、同一数据与知识版本的 ContextPackage，可显式复用；
- 不得仅凭 ID 存在就跳过新鲜度与权限校验。

## 失败策略

- `defaultPolicy=DENY`、`failurePolicy=FAIL_CLOSED`；
- 输入不足 → `KERT_CONTEXT_INSUFFICIENT`，GITS 转为 `HELD` 并生成核实任务；
- 权限不足 → `KERT_PERMISSION_DENIED`，GITS 转为 `FAILED_CLOSED`，不重试。
