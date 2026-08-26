---
chapterId: CH02
name: 行业与竞争分析
requiredFactLabel: H
dataSources: [publicData.industryReports, ASSET-KNOW-INDUSTRY-ANALYSIS]
---

# 任务：撰写章节 CH02 行业与竞争分析

基于行业框架资产与行业报告撰写行业趋势、竞争格局、客户行业地位。行业判断为假设类，标签 H；有明确来源的景气数据可标 F。

## 纪律
- 只使用提供的上下文与知识资产；无依据处如实列入 unknowns，不得臆造。
- 每个断言必须给出事实标签：F 已核验事实 / C 推断结论 / B 行为事实 / H 假设 / P 计划承诺 / A 已批准。
- 每条断言必须引用来源（source + date；来自输入的用输入来源，来自知识资产的用资产名）。

## 输出 JSON（严格）
{
  "chapterId": "CH02",
  "content": "章节正文 Markdown",
  "claims": [
    { "claim": "断言文本", "factLabel": "F|C|B|H|P|A", "source": "来源", "date": "YYYY-MM-DD" }
  ],
  "unknowns": [ { "description": "未知项", "suggestedAction": "建议获取方式" } ]
}
