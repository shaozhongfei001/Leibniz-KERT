---
chapterId: CH07
name: 产品推荐与适配
requiredFactLabel: C
dataSources: [ASSET-KNOW-PROPOSAL-TEMPLATE, enterpriseData.creditFacility]
---

# 任务：撰写章节 CH07 产品推荐与适配

基于授信结构与模板给出产品适配矩阵、推荐理由、适用条件（推断标 C）。

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
