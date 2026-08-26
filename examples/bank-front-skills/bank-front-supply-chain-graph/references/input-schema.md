# 输入结构定义（SK-FRONT-002 供应链图谱分析）

推荐输入为 JSON 对象：

```json
{
  "customerId": "HZB0000001234",
  "optional": {
    "customerName": "杭州智造精密齿轮有限公司",
    "creditCode": "91330100MA27XXXXXX",
    "industry": "C34",
    "analysisPeriodMonths": 12
  }
}
```

## 最低可用输入

- `customerId`：客户编号（必填，T-CORE-001 主入参）

## 可选增强字段

| 字段 | 说明 |
| --- | --- |
| `customerName` | 客户名称（提升外部匹配精度） |
| `creditCode` | 统一社会信用代码（提升 T-EXT-001 匹配精度） |
| `industry` | 行业代码（产业链位置标注） |
| `analysisPeriodMonths` | 分析周期月数（默认 12） |

## 缺失处理

- 无 `customerId`：请求补充客户编号或客户名称 + 统一社会信用代码；无法提供则终止。
- 行内交易数据不足 / 外部数据不可用：按 SKILL.md 第 10 节降级处理，不得虚构节点。
