# 输入结构定义（SK-FRONT-005 承诺话术生成）

推荐输入为 JSON 对象：

```json
{
  "customerId": "HZB0000001234",
  "optional": {
    "customerName": "杭州智造精密齿轮有限公司",
    "goal": "跟进客户承诺的报表提交",
    "communicationLog": [
      {
        "time": "2026-08-01",
        "channel": "上门拜访",
        "participants": ["客户经理张伟", "客户财务总监李总"],
        "summary": "客户承诺月底前提供财务报表",
        "quote": "李总：报表月底一定给你们"
      }
    ]
  }
}
```

## 最低可用输入

- `customerId`：客户编号（必填，T-CRM-001 主入参）

## 可选增强字段

| 字段 | 说明 |
| --- | --- |
| `customerName` | 客户名称 |
| `goal` | 拜访目标（话术生成导向） |
| `communicationLog` | 沟通记录片段（未提供时由 T-CRM-001 自动拉取历史记录） |

## 缺失处理

- 无 `customerId`：请求补充客户编号或客户名称；无法提供则终止。
- 无历史沟通记录：输出"无历史承诺"占位，不虚构承诺。
- 事实引用缺失：标注"待核实"。
