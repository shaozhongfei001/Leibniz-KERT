# 输出结构定义（SK-FRONT-004 事实对账与冲突检测）

输出为 JSON：指标列表 + 冲突清单 + 数据缺口清单。

```json
{
  "schemaVersion": "1.0",
  "skillId": "SK-FRONT-004",
  "customerId": "<customerId>",
  "generatedAt": "<ISO-8601>",
  "indicators": [
    {
      "elementId": "KE-FRONT-003-01",
      "name": "近半年营收",
      "value": "<数值>", "unit": "万元", "changeRate": "<同比%>",
      "dataTimestamp": "<数据时点>", "source": "T-CORE-001",
      "status": "verified | pending | missing"
    }
  ],
  "conflicts": [
    {
      "issue": "<冲突描述>",
      "ruleId": "RUL-FRONT-001-xxx",
      "involvedSources": ["<数据源>"],
      "suggestion": "<建议的核实问题>"
    }
  ],
  "dataGaps": [
    { "indicator": "<缺失指标名>", "reason": "<缺失原因>", "action": "<补数动作>" }
  ],
  "warnings": []
}
```

## 重点字段说明

| 字段 | 说明 |
| --- | --- |
| `indicators` | 五类指标（营收/授信使用率/用电量/代发薪/结算量），含数值、口径、时点、来源、状态 |
| `conflicts` | 冲突清单：逻辑矛盾/信号背离/数据异常，每条含规则编号（RUL-FRONT-001-xxx）与核实问题 |
| `dataGaps` | 数据缺口清单：缺失指标显式列出 + 原因 + 补数动作 |

## 校验约定

- 缺失指标不得静默忽略，必须进入 `dataGaps`。
- 冲突项必须附核实问题（suggestion），不得只列冲突不列行动。
- 未经确认数据标注"待核实"，用电量标注"需客户授权"。
