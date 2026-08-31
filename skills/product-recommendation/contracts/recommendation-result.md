# SP-15 输出合同：ProductRecommendationResult

与 GITS `specs/product-recommendation/recommendation-result.schema.json` 对齐。KERT 产出并装配证据；GITS 持久化业务快照与引用，不复制 KERT 整套知识为第二权威库。

## 最小结构

```json
{
  "schemaVersion": "1.0.0",
  "runId": "REC-XXX",
  "skillId": "SP-15",
  "skillVersion": "2.0.0-candidate",
  "productKnowledgeSnapshotRef": "PKS-XXX",
  "ruleExecutionRef": "RULE-RUN-XXX",
  "evidenceBundleId": "EVB-XXX",
  "contentHash": "sha256:...",
  "traceId": "TRACE-XXX",
  "eligibilityResults": [
    {
      "productId": "PROD-XXX",
      "productVersion": "2.2",
      "eligibility": "ELIGIBLE",
      "ruleResults": [
        { "ruleId": "PR-ELIG-001", "ruleVersion": "1.3", "result": "PASS",
          "reasonCode": "CUSTOMER_TYPE_ALLOWED", "inputFactRefs": ["FACT-001"], "evidenceRefs": ["EV-001"] }
      ],
      "unknowns": [],
      "reviewRequirements": []
    }
  ],
  "fitResults": [
    {
      "productId": "PROD-XXX",
      "productVersion": "2.2",
      "rank": 1,
      "fitScore": 0.82,
      "dimensionMatches": [
        { "dimension": "CORE_NEED_FIT", "result": "STRONG", "rationale": "...", "evidenceRefs": ["EV-001"] }
      ],
      "matchedNeeds": [ { "needId": "NEED-001", "needStatus": "VERIFIED_FACT", "evidenceRefs": ["EV-002"] } ],
      "recommendationReasons": [ { "text": "...", "evidenceRefs": ["EV-001"], "sourceType": "FACT" } ],
      "conditions": [], "materialGaps": [], "riskNotes": [], "salesBoundaries": []
    }
  ],
  "portfolioCandidates": [
    {
      "portfolioId": "PORT-001",
      "primaryProduct": { "productId": "PROD-XXX", "productVersion": "2.2", "role": "PRIMARY", "servedNeedId": "NEED-001" },
      "supportingProducts": [],
      "dependencies": [], "conflicts": [],
      "recommendationCategory": "IMMEDIATE_COMMUNICATE"
    }
  ],
  "needProfile": [ { "needId": "NEED-001", "needStatus": "VERIFIED_FACT", "evidenceRefs": ["EV-002"] } ],
  "unknowns": [], "conflicts": [],
  "generatedAt": "2026-08-31T09:00:00+08:00"
}
```

## 必填证据（EvidenceBundle 至少覆盖）

`customerFactSnapshotId / productKnowledgeSnapshotRef / ruleExecutionRef / skillId+skillVersion / model+promptVersion(如使用) / permissionDecisionId` + 每项理由的 `factRefs+knowledgeRefs` + 未知项/冲突项 + 内容哈希/traceId/生成时间。

"模型置信度 0.82"不能替代证据充分度，也不能作为对客户的推荐理由。

## 每候选必须能回答五问

1. 为什么考虑它（对应哪个需求与事实）；
2. 为什么允许推荐（通过哪些硬规则）；
3. 为什么排在这里（分维度结果）；
4. 还有什么不确定（缺失事实/冲突/专家判断）；
5. 依据在哪里（事实来源/产品版本/规则版本/制度条款）。
