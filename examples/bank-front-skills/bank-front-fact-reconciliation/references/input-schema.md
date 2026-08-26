# 输入结构定义（SK-FRONT-004 事实对账与冲突检测）

推荐输入为 JSON 对象：

```json
{
  "customerId": "HZB0000001234",
  "optional": {
    "customerName": "杭州智造精密齿轮有限公司",
    "industryCode": "C34",
    "creditCode": "91330100MA27XXXXXX"
  }
}
```

## 最低可用输入

- `customerId`：客户编号（必填，T-CORE-001 主入参）

## 可选增强字段

| 字段 | 说明 |
| --- | --- |
| `customerName` | 客户名称（提升外部匹配精度） |
| `industryCode` | 行业代码（行业对照基准） |
| `creditCode` | 统一社会信用代码（提升 T-EXT-001 匹配精度） |

## 缺失处理

- 无 `customerId`：请求补充客户编号或客户名称 + 统一社会信用代码；无法提供则终止。
- 某项指标缺失：列入 `dataGaps` 显式标注，不静默忽略。
