---
chapterId: CH01
name: 企业概况与经营现状
requiredFactLabel: F
dataSources: [enterpriseData.basicInfo, publicData.newsEvents]
---

# 任务：撰写章节 CH01 企业概况与经营现状

撰写企业概况与经营现状：基本信息、股权结构、主营业务、经营现状。只使用企业数据与新闻事实，标签 F。

## 纪律
- 只使用提供的上下文与知识资产；无依据处如实列入 unknowns，不得臆造。
- 每个断言必须给出事实标签：F 已核验事实 / C 推断结论 / B 行为事实 / H 假设 / P 计划承诺 / A 已批准。
- 每条断言必须引用来源（source + date；来自输入的用输入来源，来自知识资产的用资产名）。

## 输出 JSON（严格）
{
  "chapterId": "CH01",
  "content": "章节正文 Markdown",
  "claims": [
    { "claim": "断言文本", "factLabel": "F|C|B|H|P|A", "source": "来源", "date": "YYYY-MM-DD" }
  ],
  "unknowns": [ { "description": "未知项", "suggestedAction": "建议获取方式" } ]
}
