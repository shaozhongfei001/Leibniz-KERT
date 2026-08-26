# 输入结构定义（SK-FRONT-001 访前报告组装）

推荐输入为 JSON 对象，适配智能访前作战单组装场景：

```json
{
  "customerId": "HZB0000001234",
  "userId": "cm_zhangwei",
  "goal": "授信营销-流动资金贷款渗透",
  "optional": {
    "customerName": "杭州智造精密齿轮有限公司",
    "industryCode": "C34",
    "creditCode": "91330100MA27XXXXXX"
  }
}
```

## 最低可用输入

- `customerId`：客户编号（必填，行内唯一标识，格式 "HZB+10位数字"）
- `userId`：发起人 ID（必填，调用上下文注入的鉴权标识）

## 可选字段

| 字段 | 说明 |
| --- | --- |
| `goal` | 拜访目标（缺省按"全面拜访准备"处理） |
| `customerName` | 客户名称（增强外部数据匹配精度） |
| `industryCode` | 客户行业代码（增强八维研判精度） |
| `creditCode` | 统一社会信用代码（增强工商数据匹配精度） |

## 缺失处理

- 缺 `customerId`：请求补充客户编号或客户名称 + 统一社会信用代码；无法提供则中止。
- 缺 `userId` / 鉴权失败：流程在鉴权环节中止，不产出任何客户数据。
- 缺 `goal`：按"全面拜访准备"默认处理，并在输出 meta 中标注默认目标来源。
