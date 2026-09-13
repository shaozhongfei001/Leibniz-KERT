# 输出结构定义（SK-FRONT-006 KYC缺口核验）

输出为 JSON：覆盖状态 + KYC 缺口卡片列表。

```json
{
  "schemaVersion": "1.0",
  "skillId": "SK-FRONT-006",
  "customerId": "<customerId>",
  "generatedAt": "<ISO-8601>",
  "coverageStatus": "SUCCESS | PARTIAL | NOT_RUN | FAILED",
  "coverageStatusReason": "<必填：说明 coverageStatus 的依据；SUCCESS 时亦须填写>",
  "kycGaps": [
    {
      "gapId": "KG-001",
      "description": "<精准、可回答的缺口描述>",
      "trigger": "<触发源原文，关联 RUL-FRONT-001-003>",
      "status": "OPEN | PENDING | CLOSED",
      "priority": "high | medium | general",
      "priorityCategory": "资金安全 | 合规风险 | 经营决策",
      "verifyScript": {
        "factBasis": "<引用的事实依据>",
        "question": "<具体提问内容>",
        "goal": "<核实目标>"
      },
      "actionPlan": {
        "verifyGoal": "<核实目标>",
        "timing": "<核实时机>",
        "path": ["<核实路径步骤1>", "<核实路径步骤2>"]
      }
    }
  ],
  "warnings": []
}
```

## 重点字段说明

| 字段 | 说明 |
| --- | --- |
| **`coverageStatus`** | **覆盖状态**（受控枚举，**必填**）。声明本次识别**在多大程度上可以代表实际缺口情况**。见下表 |
| `coverageStatusReason` | **必填**（**无条件**）。说明 `coverageStatus` 取值的依据：非 `SUCCESS` 时说明原因（上游未执行/触发源不完整/规则未落地），`SUCCESS` 时说明依据（如"触发源完整评估"）。**运行时会校验该顶层键存在**，缺则拒绝返回 |
| `kycGaps[].description` | 缺口描述：精准、具体、可回答，避免泛泛提问（KE-FRONT-005-01） |
| `kycGaps[].trigger` | 触发源：引用事实对账冲突原文，关联规则编号（KE-FRONT-005-02） |
| **`kycGaps[].status`** | **缺口状态**（受控枚举）。见下表 |
| `kycGaps[].priority` | 优先级：high/medium/general（RUL-FRONT-002：资金安全/合规风险/经营决策） |
| `kycGaps[].verifyScript` | 核实话术三要素：事实依据 + 提问内容 + 核实目标（KE-FRONT-005-03） |
| `kycGaps[].actionPlan` | 核实行动：目标 + 时机 + 路径（KE-FRONT-005-04） |

### `coverageStatus` 取值定义

| 取值 | 含义 | 判定依据 |
| --- | --- | --- |
| `SUCCESS` | 触发源已完整评估，本次识别结果可代表实际缺口情况 | 输入触发源完整（`conflicts` 非空，或 `upstreamStatus == "SUCCESS"`），且核验要素齐备 |
| `PARTIAL` | 触发源或核验规则**覆盖不完整**，结果可能遗漏缺口 | 上游 `upstreamStatus == "PARTIAL"`，或 `conflicts` 为空但有 `kycMissingFields`/行业信号 |
| `NOT_RUN` | **上游事实对账未执行**，本能力**无从判断**是否存在缺口 | `upstreamStatus ∈ {"NOT_RUN","FAILED"}`，或未提供 `upstreamStatus` 且无其他触发源 |
| `FAILED` | 执行失败，未产出有效结果 | — |

> **`NOT_RUN` 是本字段存在的根本理由。**
> **「没查」与「查了且没有缺口」在结论层必须可区分。**
> 二者都可能 `kycGaps: []`，但**含义完全不同**：
> · `coverageStatus = "SUCCESS"` 且 `kycGaps: []` → **确实没有缺口**
> · `coverageStatus = "NOT_RUN"` 且 `kycGaps: []` → **无从判断，不得读作"无缺口"**
>
> **禁止**把该区分只写在 `warnings` 里 —— `warnings` 是自由文本，不构成结论。

### `kycGaps[].status` 取值定义

| 取值 | 含义 |
| --- | --- |
| `OPEN` | 缺口已识别，尚未开始核实（**新建缺口的默认值**） |
| `PENDING` | 核实进行中，尚无结论 |
| `CLOSED` | **已核实并关闭**。须有核实证据支撑 |

> **纪律**：**未经证据支撑的假设不得标 `CLOSED`。**
> 若某项仅为推断/假设（无 `evidenceRefs` 类证据），必须保持 `OPEN` 或 `PENDING`。

## 校验约定

- 每条缺口必须含触发源与规则编号（可追溯）。
- 每条缺口必须含核实话术（verifyScript）。
- 每条缺口必须含 `status`。
- **`coverageStatus` 必填**，且**不得**在上游未执行时标为 `SUCCESS`。
- **无触发源时不强行制造缺口** —— 但此时 `coverageStatus` **必须**如实标为
  `NOT_RUN`（上游未执行）或 `PARTIAL`（覆盖不完整），**不得**标 `SUCCESS`。
- **`generatedAt` 必须为合法 ISO-8601**（不得为自由文本占位）。
