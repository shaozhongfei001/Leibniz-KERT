# 输入结构定义（SK-FRONT-003 八维研判）

推荐输入为 JSON 对象：

```json
{
  "industryCode": "C34",
  "optional": {
    "customerName": "杭州智造精密齿轮有限公司",
    "region": "浙江省杭州市",
    "mainProducts": "精密齿轮制造（新能源汽车变速箱）"
  }
}
```

## 最低可用输入

- `industryCode`：客户行业代码（必填，T-MARKET-001 主入参）

## 可选增强字段

| 字段 | 说明 |
| --- | --- |
| `customerName` | 客户名称（将行业分析结合客户实际） |
| `region` | 客户所在区域（区域维度细化） |
| `mainProducts` | 主营产品（竞争力维度细化） |

## 缺失处理

- 无 `industryCode` 或无法识别行业：先核实行业分类，不得直接评分。
- 明确依据的维度 < 6 个：返回 `status: insufficient`，不输出正式综合结论。
