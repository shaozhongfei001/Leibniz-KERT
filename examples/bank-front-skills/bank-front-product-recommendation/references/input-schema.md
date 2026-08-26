# 输入结构定义（SK-FRONT-007 产品组合推荐）

推荐输入为 JSON 对象：

```json
{
  "customerId": "HZB0000001234",
  "needs": "客户扩产项目需要流动资金支持，且应收账款周转偏慢",
  "optional": {
    "customerName": "杭州智造精密齿轮有限公司",
    "kycPains": ["应收账款高企", "现金流季节性紧张"],
    "communicationNeeds": ["扩产项目资金需求", "希望加快回款"],
    "marketSignals": ["新能源汽车零部件行业景气上行", "设备更新补贴政策"]
  }
}
```

## 最低可用输入

- `customerId`：客户编号（必填）

## 建议输入

- `needs`：需求摘要（客户表达的需求）

## 可选增强字段

| 字段 | 说明 |
| --- | --- |
| `customerName` | 客户名称 |
| `kycPains` | KYC 痛点（来自 KYC 画像） |
| `communicationNeeds` | 沟通记录需求表达 |
| `marketSignals` | 市场慧眼信号 |

## 缺失处理

- 三源输入均缺失：输出"输入不足"说明，不凭空推荐。
- 部分源缺失：仅基于可得源匹配，缺失源在匹配依据中标注"数据不可得"。
