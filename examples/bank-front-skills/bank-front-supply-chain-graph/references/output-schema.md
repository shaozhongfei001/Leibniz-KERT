# 输出结构定义（SK-FRONT-002 供应链图谱分析）

输出为供应链图谱 JSON：`nodes`（三段式节点）+ `edges`（有向关系边）+ `interpretation`（四类结构化解读）。

```json
{
  "schemaVersion": "1.0",
  "skillId": "SK-FRONT-002",
  "customerId": "<customerId>",
  "generatedAt": "<ISO-8601>",
  "buildStatus": "complete | partial",
  "nodes": [
    {
      "id": "<节点ID>", "name": "<企业名称>",
      "layer": "supplier | enterprise | customer",
      "type": "supplier | enterprise | customer",
      "creditCode": "<可空>", "industry": "<行业>",
      "annualAmount": 0, "share": 0, "trend": "up | flat | down | unknown",
      "dataSource": "T-CORE-001 | T-EXT-001 | MERGED",
      "verifyStatus": "VERIFIED | PENDING"
    }
  ],
  "edges": [
    {
      "source": "<本企业节点ID>", "target": "<对手节点ID>",
      "relation": "purchase | sale", "direction": "out | in",
      "annualAmount": 0, "share": 0, "settlement": "<结算方式/账期>",
      "trend": "up | flat | down | unknown",
      "dataSource": "T-CORE-001 | T-EXT-001",
      "verifyStatus": "VERIFIED | PENDING"
    }
  ],
  "interpretation": {
    "supplyChainPosition": "<上游/中游/下游 + 一句依据>",
    "bargainingPower": { "upstream": "<强/中/弱 + 依据>", "downstream": "<强/中/弱 + 依据>" },
    "concentrationRisk": [{ "type": "supplier | customer", "name": "<对手>", "share": 0, "level": "high | medium | low", "reason": "<触发原因>", "dataSource": "<来源>" }],
    "keyChanges": [{ "type": "added | removed | shareChanged", "name": "<对手>", "detail": "<变动>", "period": "<周期>", "dataSource": "<来源>" }],
    "overallAssessment": "<一段话综合判断>",
    "followUpQuestions": ["<访前核实问句>"],
    "confidence": { "position": "high | medium | low", "bargainingPower": "high | medium | low", "concentration": "high | medium | low", "changes": "high | medium | low" }
  }
}
```

## 重点字段说明

| 字段 | 说明 |
| --- | --- |
| `buildStatus` | `complete`（完整）/ `partial`（部分构建，节点不足时必须标注并附覆盖局限说明） |
| `nodes` | 至少 3 个供应商 + 1 个本企业 + 至少 3 个客户 |
| `edges` | 每条边含方向、金额、占比、趋势，同侧边 share 合计 ≤ 1 |
| `interpretation.concentrationRisk` | 单一占比 ≥ 30% 或 Top5 ≥ 70% 触发 high |
| `verifyStatus` | 不可核验内容标注 PENDING 并转化为 followUpQuestions |

## 校验约定

- 三段式结构齐全，本企业节点唯一。
- 所有解读覆盖四要素：位置、议价能力、集中度风险、关键变动。
- 数据来源（dataSource）与置信度（confidence）逐项标注。
