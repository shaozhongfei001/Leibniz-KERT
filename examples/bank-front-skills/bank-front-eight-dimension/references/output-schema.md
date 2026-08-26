# 输出结构定义（SK-FRONT-003 八维研判）

输出为 JSON：八个维度的评分 + 综合结论。

```json
{
  "schemaVersion": "1.0",
  "skillId": "SK-FRONT-003",
  "industryCode": "<行业代码>",
  "generatedAt": "<ISO-8601>",
  "status": "complete | insufficient",
  "dimensions": {
    "policy":       { "score": 1-5, "label": "<支持/限制方向>", "basis": "<判断要点+政策原文引用>", "evidenceLevel": "明确依据 | 部分依据 | 证据不足-待核实" },
    "market":       { "score": 1-5, "label": "<供需格局>", "basis": "<景气信号>", "evidenceLevel": "..." },
    "technology":   { "score": 1-5, "label": "<技术路线>", "basis": "<迭代/替代风险>", "evidenceLevel": "..." },
    "supplyChain":  { "score": 1-5, "label": "<上下游稳定性>", "basis": "<断链风险>", "evidenceLevel": "..." },
    "region":       { "score": 1-5, "label": "<集聚度>", "basis": "<区域政策>", "evidenceLevel": "..." },
    "risk":         { "score": 1-5, "label": "<信用/合规风险>", "basis": "<风险信号>", "evidenceLevel": "..." },
    "index":        { "score": 1-5, "label": "<指数走势>", "basis": "<相对大盘>", "evidenceLevel": "..." },
    "competitiveness": { "score": 1-5, "label": "<竞争地位>", "basis": "<依据>", "evidenceLevel": "..." }
  },
  "overallConclusion": "<平衡多维矛盾信号后的综合经营判断>",
  "uncertainty": "<不确定之处与影响方向>",
  "verifyItems": ["<待核实事项1>", "<待核实事项2>"],
  "dataSource": "T-MARKET-001"
}
```

## 重点字段说明

| 字段 | 说明 |
| --- | --- |
| `dimensions[].score` | 1-5 整数评分，**必填**；供 SK-FRONT-001 组装时携带逐维评分与依据 |
| `dimensions[].evidenceLevel` | 明确依据 / 部分依据 / 证据不足-待核实 |
| `status` | `complete`（≥6 维有明确依据）/ `insufficient`（不足时降级） |
| `overallConclusion` | 综合结论必须平衡多维矛盾信号，不得凭单一维度下结论 |
| `verifyItems` | 待核实事项清单，不确定性必须标注 |

## 校验约定

- 八个维度均有评分（1-5 整数），证据不足维度标注"证据不足-待核实"并按 3 分中性处理。
- 政策维度引用政策原文时注明发文机关、文号与年份。
- 输出符合 references/output-schema.md 结构，无虚构数据。
