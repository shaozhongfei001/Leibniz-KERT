# SP-15 契约样例（examples）

> 目录：`skills/product-recommendation/contracts/examples/`
> 用途：SP-15 `ProductRecommendationResult` 的正/反契约样例，供 `recommendation-result.schema.json` 校验与 INV 不变量测试。

```text
DOC_STATUS=CANDIDATE
FROZEN=NO
IMPLEMENTED=NO
REAL_E2E_PASS=NO
```

## 样例清单

| 文件 | 类型 | 说明 |
|---|---|---|
| `valid-sp15-result.json` | 正向 | 满足 `recommendation-result.schema.json` 必填 8 字段（schemaVersion/runId/productKnowledgeSnapshotRef/ruleExecutionRef/evidenceBundleId/contentHash/traceId/generatedAt），且 `eligibilityResults[]` 含一条 `eligibility=ELIGIBLE` 且 `ruleResults` 完整（ruleId/ruleVersion/result/reasonCode/inputFactRefs/evidenceRefs）。 |
| `invalid-sp15-ineligible-with-score.json` | 反例 | 故意违反 **INV-02**：产品 `PROD-FIN-DISALLOWED-001` 在 `eligibilityResults[]` 中 `eligibility=INELIGIBLE`（命中 `PR-REG-002` FAIL，`reasonCode=FORBIDDEN_INDUSTRY`），但 `fitResults[]` 对应条目 `fitScore=0.74`（非 null）。 |

## 校验方式

- 正向样例应通过 `recommendation-result.schema.json` 校验；
- 反例样例应被 INV-02 校验器拒绝（`INELIGIBLE → fitScore must be null`）。

两个样例均为**纯 ProductRecommendationResult 数据实例**（顶层无额外治理字段，避免污染 schema 校验）；本 README 承载状态块与违反说明。
