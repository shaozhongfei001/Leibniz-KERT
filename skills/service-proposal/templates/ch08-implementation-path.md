---
chapterId: CH08
name: 实施路径
requiredFactLabel: H
dataSources: [ASSET-KNOW-VISIT-SOP]
---

# 任务：撰写章节 CH08 实施路径

给出 30/90/180 天实施计划、里程碑、KPI（计划标 P/H）。

## 纪律
- 只使用提供的上下文与知识资产；无依据处如实列入 unknowns，不得臆造。
- 每个断言必须给出事实标签：F 已核验事实 / C 推断结论 / B 行为事实 / H 假设 / P 计划承诺 / A 已批准。
- 每条断言必须引用来源（source + date；来自输入的用输入来源，来自知识资产的用资产名）。

## 输出 JSON（严格）
{
  "chapterId": "CH08",
  "content": "章节正文 Markdown",
  "claims": [
    { "claim": "断言文本", "factLabel": "F|C|B|H|P|A", "source": "来源", "date": "YYYY-MM-DD" }
  ],
  "unknowns": [ { "description": "未知项", "suggestedAction": "建议获取方式" } ]
}
