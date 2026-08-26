# 输出结构定义（SK-FRONT-001 访前报告组装）

输出为完整 H5 作战单 JSON（一页移动端版式，可 PDF 导出，对应 KI-FRONT-007 输出渲染模板）。

```json
{
  "schemaVersion": "1.0",
  "skillId": "SK-FRONT-001",
  "requestId": "<请求ID>",
  "battleOrder": {
    "meta": {
      "id": "BO-<YYYYMMDD>-<customerId>",
      "customerId": "<客户ID>",
      "customerName": "<客户名称>",
      "goal": "<拜访目标>",
      "generatedAt": "<ISO时间>",
      "generatedBy": "<userId>",
      "version": "1.0"
    },
    "summary": {
      "visitPurpose": "<一句话拜访目的>",
      "keyFindings": ["<关键发现1>", "<关键发现2>"],
      "recommendedActions": ["<建议行动1>", "<建议行动2>"]
    },
    "sections": {
      "customerBasic": { "<KI-009八要素字段>": "<值>", "missingFields": ["<缺失要素>"] },
      "supplyChainGraph": { "nodes": [], "edges": [], "interpretation": {}, "buildStatus": "complete|partial" },
      "eightDimension": { "<维度>": { "score": 1-5, "basis": "<依据>", "evidenceLevel": "明确依据|部分依据|证据不足-待核实" } },
      "factReconciliation": { "indicators": [], "conflicts": [], "dataGaps": [] },
      "commitmentScript": "<承诺话术文本>",
      "kycGapList": [{ "item": "<缺口要素>", "trigger": "<触发源>", "priority": "高|中|一般", "verifyScript": "<核实话术>", "action": "<核实路径>" }],
      "productPortfolio": [{ "productId": "<产品ID>", "name": "<产品名称>", "matchLevel": "高匹配|组合备选|待核实", "reason": "<推荐理由>", "verifyItems": ["<待核实条件>"] }]
    },
    "riskAndAction": {
      "conflicts": [{ "issue": "<冲突描述>", "action": "<建议处理动作>" }],
      "kycGaps": [{ "item": "<缺口要素>", "priority": "高|中|低", "action": "<补全动作>" }],
      "hardConstraints": [{ "productId": "<产品ID>", "constraint": "<不满足的硬约束>" }]
    },
    "assemblyMaterials": {
      "steps": [{ "taskId": "TASK-FRONT-001~007", "taskName": "<任务名>", "status": "success|degraded|failed", "outputKeys": [], "knowledgeItems": [], "warnings": [] }],
      "warnings": []
    },
    "disclaimer": "本作战单仅用于拜访准备，不构成授信承诺或投资建议；最终业务决策须经行内合规与风险审查。"
  }
}
```

## 重点字段说明

| 字段 | 说明 |
| --- | --- |
| `sections.customerBasic` | 按 KI-009 八要素（客户全称/编号/所属行业/企业规模/年营收/注册地址/主要产品/合作年限）输出，必须携带 `missingFields` |
| `sections.supplyChainGraph` | 三段式图谱（nodes + edges + interpretation），节点不足时必须 `buildStatus: "partial"` 并附覆盖局限说明 |
| `sections.eightDimension` | 八维逐维评分（1-5 整数）+ 依据，禁止仅定性描述无评分 |
| `sections.factReconciliation` | 指标列表 + 冲突清单 + 数据缺口清单（缺失指标必须显式列出） |
| `sections.kycGapList` | 每个缺口含 `trigger`（触发源）+ `verifyScript`（核实话术）+ `action`（核实路径） |
| `sections.productPortfolio` | 候选产品含 `matchLevel`（高匹配/组合备选/待核实）+ `reason`（匹配依据）+ `verifyItems`（待核实条件） |
| `riskAndAction` | 冲突、KYC 缺口、产品硬约束显性呈现区（作战单置顶区域），逐条含行动项 |

## 校验约定

- 七模块（customerBasic / supplyChainGraph / eightDimension / factReconciliation / commitmentScript / kycGapList / productPortfolio）必须齐全且非空占位。
- 所有冲突、缺口、硬约束不得被删除/隐藏/弱化。
- 话术事实引用必须带来源标签，未核验数据标注"待核验"。
