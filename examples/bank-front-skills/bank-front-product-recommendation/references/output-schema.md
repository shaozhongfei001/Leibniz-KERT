# 输出结构定义（SK-FRONT-007 产品组合推荐）

输出为 JSON：候选产品列表 + 主推/交叉组合建议 + 硬约束未通过清单。

```json
{
  "schemaVersion": "1.0",
  "skillId": "SK-FRONT-007",
  "customerId": "<customerId>",
  "generatedAt": "<ISO-8601>",
  "candidates": [
    {
      "productId": "<产品ID>",
      "name": "<产品名称>",
      "matchLevel": "high | combo | pending",
      "description": "<产品描述>",
      "matchBasis": [
        { "sourceType": "kycPain | communication | marketSignal", "detail": "<匹配依据>", "origin": "<原始出处>" }
      ],
      "verifyItems": ["<待核实条件1>", "<待核实条件2>"]
    }
  ],
  "recommendations": {
    "primary": ["<主推产品ID>"],
    "crossSell": ["<交叉组合产品ID>"]
  },
  "hardConstraintFailures": [
    { "productId": "<产品ID>", "constraint": "<不满足的硬约束>" }
  ],
  "warnings": []
}
```

## 重点字段说明

| 字段 | 说明 |
| --- | --- |
| `candidates[].matchLevel` | 匹配度标签：high（高匹配）/ combo（组合备选）/ pending（待核实） |
| `candidates[].matchBasis` | 匹配依据：来源类型（KYC痛点/沟通记录/市场信号）+ 详情 + 原始出处 |
| `candidates[].verifyItems` | 待核实条件清单 |
| `recommendations` | 主推（primary）与交叉组合（crossSell）建议 |
| `hardConstraintFailures` | 硬约束未通过产品 + 不满足的约束说明 |

## 校验约定

- 匹配依据可追溯（来源类型 + 原始出处），无虚构依据。
- 硬约束（准入/互斥/监管禁止项）校验结果显性呈现。
- 待核实产品标注待核实条件，不进入主推。
