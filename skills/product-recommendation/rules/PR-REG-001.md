---
ruleId: PR-REG-001
ruleName: 监管/政策禁止规则
ruleVersion: 1.0.0-candidate
category: regulatory
owner: 合规管理部
ruleBundleRef: RB-PR-20260831-0001
enforcement: BLOCKING
executionOrder: 3
status: CANDIDATE
frozen: "NO"
implemented: "NO"
trigger: 客户行业/资金用途/地域命中监管或行内政策禁止清单
conclusions:
  - result: PASS
    reasonCode: INDUSTRY_NOT_PROHIBITED
    effect: 继续后续规则
  - result: FAIL
    reasonCode: FORBIDDEN_INDUSTRY
    effect: INELIGIBLE（FAIL_CLOSED），不得进入排序
  - result: FAIL
    reasonCode: FORBIDDEN_USE
    effect: INELIGIBLE（FAIL_CLOSED）
  - result: FAIL
    reasonCode: FORBIDDEN_REGION
    effect: INELIGIBLE（FAIL_CLOSED）
  - result: UNKNOWN
    reasonCode: FACT_CONFLICT_NO_DETERMINISTIC_RESULT
    effect: 禁止确定性解读（INV-10），不进入排序，先事实对账
evidenceRefs:
  - evidenceRefId: EV-REG-POLICY
    sourceType: REGULATION
    sourceId: REG-FIN-001《流动资金贷款管理暂行办法》（PENDING_SOURCE）
  - evidenceRefId: EV-CUST-IND
    sourceType: CUSTOMER_FACT
    sourceId: customerFactSnapshot.industry
---

# PR-REG-001 监管/政策禁止规则

```text
DOC_STATUS=CANDIDATE
FROZEN=NO
IMPLEMENTED=NO
REAL_E2E_PASS=NO
```

## 1. 触发条件

客户行业 / 资金用途 / 地域命中监管或行内政策禁止清单（确定性规则，`FAIL_CLOSED`）。权威事实冲突（同一客户事实存在两个冲突来源）时，禁止确定性解读（`INV-10`）。

## 2. 结论（result → reasonCode → 下游）

| result | reasonCode | 下游处理 |
|---|---|---|
| `PASS` | `INDUSTRY_NOT_PROHIBITED` | 继续后续规则 |
| `FAIL` | `FORBIDDEN_INDUSTRY` | `INELIGIBLE`（`FAIL_CLOSED`），不得进入排序 |
| `FAIL` | `FORBIDDEN_USE` | `INELIGIBLE`（`FAIL_CLOSED`） |
| `FAIL` | `FORBIDDEN_REGION` | `INELIGIBLE`（`FAIL_CLOSED`） |
| `UNKNOWN` | `FACT_CONFLICT_NO_DETERMINISTIC_RESULT` | 禁止确定性解读（`INV-10`），不进入排序，先事实对账 |

## 3. 证据引用（EvidenceRef）

| evidenceRefId | 来源类型 | 来源 | 状态 |
|---|---|---|---|
| `EV-REG-POLICY` | 监管法规 | `REG-FIN-001`《流动资金贷款管理暂行办法》（禁止行业/用途/受托支付条款） | `PENDING_SOURCE` |
| `EV-CUST-IND` | 客户事实 | `customerFactSnapshot.industry` | 受控事实快照 |

## 4. 不变量

- `INV-02`：`Eligibility=INELIGIBLE` → `rankScore/fitScore` 为 null（高分不可覆盖）。
- `INV-10`：权威证据冲突 → 禁止确定性解读。
- 监管禁止为硬约束：`INELIGIBLE` 不能通过提高匹配分数重新进入候选。

## 5. 对齐说明

WP0 反例 `contracts/examples/invalid-sp15-ineligible-with-score.json` 以 `PR-REG-002` 表达监管禁止 FAIL（`reasonCode=FORBIDDEN_INDUSTRY`）；本包将监管禁止收敛为权威规则 `PR-REG-001`（FAIL 分支 `reasonCode=FORBIDDEN_INDUSTRY`），执行粒度可按 `reasonCode` 拆分，与既有样例语义一致、不冲突。
