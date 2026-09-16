---
chapterId: CH07
name: 产品推荐与适配
requiredFactLabel: C
dataSources: [ASSET-KNOW-PROPOSAL-TEMPLATE, enterpriseData.creditFacility, productRecommendationProposalVersion, productInterpretationVersion]
---

# 任务：撰写章节 CH07 产品推荐与适配

消费 GITS 传入的已决定采用的 `ProductRecommendationProposalVersion`（产品适配/组合子方案）与 `ProductInterpretationVersion`（版本化产品解读快照）撰写本章。本章**不自行运行产品推荐/排序**；只把已决定产品映射到服务方案、补充非产品服务，并说明适用条件（推断标 C）。

## 输入（由 GITS 在 context 中传入）

- `productRecommendationProposalVersion`：已决定采用的产品推荐子方案版本（含候选、组合、理由、证据引用、人工决定）；
- `productInterpretationVersion`：所选产品的版本化解读（产品边界、准入、材料、风险、销售边界）；
- 若未传入，产品段落只能引用 SP-20 既有知识资产，并显式标注 `releaseBlockedUntil` 未满足。

## 纪律
- 只使用提供的上下文与知识资产；无依据处如实列入 unknowns，不得臆造。
- 每个断言必须给出事实标签：F 已核验事实 / C 推断结论 / B 行为事实 / H 假设 / P 计划承诺 / A 已批准。
- 每条断言必须引用来源（source + date；来自输入的用输入来源，来自知识资产的用资产名）。

## 输出 JSON（严格）
{
  "chapterId": "CH07",
  "content": "章节正文 Markdown",
  "claims": [
    { "claim": "断言文本", "factLabel": "F|C|B|H|P|A", "source": "来源", "date": "YYYY-MM-DD" }
  ],
  "unknowns": [ { "description": "未知项", "suggestedAction": "建议获取方式" } ]
}
