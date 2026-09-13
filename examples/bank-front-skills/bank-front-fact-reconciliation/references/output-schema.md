# 输出结构定义（SK-FRONT-004 事实对账与冲突检测）

输出为 JSON：指标列表 + 冲突清单 + 数据缺口清单 + 执行状态。

```json
{
  "schemaVersion": "1.0",
  "skillId": "SK-FRONT-004",
  "customerId": "<customerId>",
  "taskId": "<本次任务标识>",
  "asOf": "<数据截止时点，ISO-8601>",
  "generatedAt": "<ISO-8601>",
  "executionStatus": "SUCCESS | PARTIAL | NOT_RUN | FAILED",
  "executionStatusReason": "<必填：说明 executionStatus 的依据；SUCCESS 时亦须填写>",
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
      "id": "<冲突实例唯一标识，如 CFL-001>",
      "issue": "<冲突描述>",
      "ruleId": "RUL-FRONT-001-003",
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
| `taskId` | 本次任务标识。用于跨能力追溯同一访前任务 |
| `asOf` | 数据截止时点。与 `indicators[].dataTimestamp` 的区别：`asOf` 为整份输出的口径时点 |
| `executionStatus` | **执行状态**（受控枚举）。见下表 —— **这是本能力对"我到底查到了什么程度"的唯一权威声明** |
| `executionStatusReason` | **必填**（**无条件**）。说明取值依据；非 `SUCCESS` 时说明是数据不足、规则未落地还是执行失败，`SUCCESS` 时说明依据。**运行时会校验该顶层键存在**，缺则拒绝返回 |
| `indicators` | 五类指标（营收/授信使用率/用电量/代发薪/结算量），含数值、口径、时点、来源、状态 |
| `conflicts` | 冲突清单：逻辑矛盾/信号背离/数据异常，每条含**实例标识**、规则编号与核实问题 |
| `conflicts[].id` | **冲突实例**唯一标识（与 `ruleId` 并列：`ruleId` 标识规则，`id` 标识本次冲突实例）。同一规则多次触发时用以区分 |
| `conflicts[].ruleId` | **规则编号。必须是具体子编号**（如 `RUL-FRONT-001-003`）|
| `dataGaps` | 数据缺口清单：缺失指标显式列出 + 原因 + 补数动作 |

### `executionStatus` 取值定义

| 取值 | 含义 | 判定依据 |
| --- | --- | --- |
| `SUCCESS` | 五类指标均取得且状态均为 `verified`，且交叉校验规则已全部落地执行 | — |
| `PARTIAL` | 部分指标缺失或状态非 `verified`，或部分交叉校验规则因数据不足未落地 | `dataGaps` 非空，或存在 `status != "verified"` 的指标 |
| `NOT_RUN` | **本能力未能取得任何可用指标**，交叉校验**实际未执行** | `indicators` 为空，或全部 `status == "missing"` |
| `FAILED` | 执行失败，无法产出有效结论 | — |

> **`NOT_RUN` 的含义必须是"没查"，不得用于"查了没发现"。**
> 「查了且无冲突」应记 `SUCCESS` 且 `conflicts: []`；
> 「没查」必须记 `NOT_RUN`。**二者绝不可混同** —— 下游据此决定是否输出"无缺口"。

## 校验约定

- 缺失指标不得静默忽略，必须进入 `dataGaps`。
- 冲突项必须附核实问题（suggestion），不得只列冲突不列行动。
- **`ruleId` 必须为具体子编号**（形如 `RUL-FRONT-001-003`）。
  **禁止占位符**（如 `RUL-FRONT-001-xxx`、含 `xxx`、空值）——
  占位符使下游无法追溯，也无法被机器校验。
  若规则确实无法映射到具体子编号，**置空 `ruleId` 并在此处标注**，不得以 `xxx` 占位。
- **`conflicts[].id` 必须唯一且稳定**（同一冲突在同一份输出内唯一；重复执行时同一冲突应得到同一 `id`）。
- **`executionStatus` 必填**，且**不得**在 `indicators` 为空或全为 `missing` 时标为 `SUCCESS`。
- 未经确认数据标注"待核实"，用电量标注"需客户授权"。
- **`generatedAt` / `asOf` 必须为合法 ISO-8601**（不得为自由文本占位）。
