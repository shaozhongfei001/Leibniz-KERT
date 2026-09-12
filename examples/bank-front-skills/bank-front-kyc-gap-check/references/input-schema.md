# 输入结构定义（SK-FRONT-006 KYC缺口核验）

推荐输入为 JSON 对象：

```json
{
  "customerId": "HZB0000001234",
  "upstreamStatus": "SUCCESS | PARTIAL | NOT_RUN | FAILED",
  "conflicts": [
    {
      "id": "CFL-001",
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
- **`upstreamStatus`**：**上游事实对账的执行状态**（强烈建议）—— 直接取自上游
  `bank-front-fact-reconciliation` 输出中的 `executionStatus` 字段，**不得改写**。
  见下节

### 为什么需要 `upstreamStatus`

> **问题**：`conflicts: []` 有两种完全不同的成因 ——
> **「上游查了，确实没有冲突」** 与 **「上游没查」**。
> **仅凭 `conflicts` 无法区分二者。**
>
> 若不区分，本能力会在"上游没查"时输出"无缺口"，
> 而这会被读作"确实没有缺口" —— **这是错误的结论**。
>
> `upstreamStatus` 就是为此存在的：
> · `SUCCESS` → 上游查了且覆盖完整 → "无缺口"可信
> · `PARTIAL` → 上游覆盖不完整 → 结果可能遗漏
> · `NOT_RUN` / `FAILED` → **上游没查** → 本能力**无从判断**，
>   须在输出 `coverageStatus` 中如实标为 `NOT_RUN`
>
> **未提供 `upstreamStatus` 时的处理**：不得假定为 `SUCCESS`。
> 应按"上游状态未知"处理，并在输出 `coverageStatus` 中反映（见 `output-schema.md`）。

## 可选增强字段

| 字段 | 说明 |
| --- | --- |
| `customerName` | 客户名称 |
| `industrySignals` | 行业信号（无冲突时的触发源） |
| `kycMissingFields` | 已知缺失的 KYC 要素 |
| `upstreamStatus` | 上游执行状态（见上节。**位于顶层，非 `optional`**） |

## 缺失处理

- 无 `conflicts` 且无行业信号：按 KYC 要素缺失识别；仍无触发源则输出"无缺口"占位，
  **且 `coverageStatus` 必须如实标注**（上游未执行 → `NOT_RUN`；覆盖不完整 → `PARTIAL`）。
- **不得**因 `conflicts` 为空就默认 `coverageStatus = "SUCCESS"`。
