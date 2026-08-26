# 输入结构定义（SK-FRONT-006 KYC缺口核验）

推荐输入为 JSON 对象：

```json
{
  "customerId": "HZB0000001234",
  "conflicts": [
    {
      "issue": "用电量同比+30%，但近半年营收同比-5%",
      "ruleId": "RUL-FRONT-001-003"
    }
  ],
  "optional": {
    "customerName": "杭州智造精密齿轮有限公司",
    "industrySignals": ["新能源汽车零部件行业景气度波动"],
    "kycMissingFields": ["受益所有人信息"]
  }
}
```

## 最低可用输入

- `customerId`：客户编号（必填）

## 建议输入

- `conflicts`：事实对账冲突/异常清单（强烈建议，提升缺口识别针对性）

## 可选增强字段

| 字段 | 说明 |
| --- | --- |
| `customerName` | 客户名称 |
| `industrySignals` | 行业信号（无冲突时的触发源） |
| `kycMissingFields` | 已知缺失的 KYC 要素 |

## 缺失处理

- 无 `conflicts` 且无行业信号：按 KYC 要素缺失识别；仍无触发源则输出"无缺口"占位。
