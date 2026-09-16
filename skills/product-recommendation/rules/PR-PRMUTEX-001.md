---
ruleId: PR-PRMUTEX-001
ruleName: 产品前置与互斥规则
ruleVersion: 1.0.0-candidate
category: prerequisite-mutex
owner: 公司金融产品管理部
ruleBundleRef: RB-PR-20260831-0001
enforcement: BLOCKING
executionOrder: [5, 6]
executionOrderNote: 覆盖 rules/README.md 硬约束顺序第 5 步（产品前置条件）与第 6 步（产品互斥与存量冲突）；本包将两步合并为单一规则文件，不对 README 序号作一对一宣称
status: CANDIDATE
frozen: "NO"
implemented: "NO"
trigger: 前置产品未持有、或互斥产品并存、或存量冲突
conclusions:
  - result: PASS
    reasonCode: PREREQUISITE_SATISFIED
    effect: 继续后续规则
  - result: PASS
    reasonCode: NO_MUTEX_CONFLICT
    effect: 继续后续规则
  - result: FAIL
    reasonCode: PREREQUISITE_MISSING
    effect: 排除或转组合依赖（形成有顺序的组合/待办）
  - result: FAIL
    reasonCode: MUTEX_CONFLICT
    effect: INELIGIBLE 或 REVIEW_REQUIRED，组合被拒绝并解释原因
  - result: REVIEW_REQUIRED
    reasonCode: MUTEX_REVIEW_REQUIRED
    effect: 进入专家复核区，不得作为可直接批准项
evidenceRefs:
  - evidenceRefId: EV-HOLDING
    sourceType: CUSTOMER_FACT
    sourceId: customerFactSnapshot.holdings（存量持有）
  - evidenceRefId: EV-SRC-FIN-003
    sourceType: POLICY
    sourceId: SRC-FIN-003《供应链金融业务操作规程》（PENDING_SOURCE）
---

# PR-PRMUTEX-001 产品前置与互斥规则

```text
DOC_STATUS=CANDIDATE
FROZEN=NO
IMPLEMENTED=NO
REAL_E2E_PASS=NO
```

## 1. 触发条件

检查前置产品是否已持有、互斥产品是否并存、存量是否冲突（图关系 + 规则）。

## 2. 结论（result → reasonCode → 下游）

| result | reasonCode | 下游处理 |
|---|---|---|
| `PASS` | `PREREQUISITE_SATISFIED` | 继续后续规则 |
| `PASS` | `NO_MUTEX_CONFLICT` | 继续后续规则 |
| `FAIL` | `PREREQUISITE_MISSING` | 排除或转组合依赖（形成有顺序的组合/待办） |
| `FAIL` | `MUTEX_CONFLICT` | `INELIGIBLE` 或 `REVIEW_REQUIRED`，组合被拒绝并解释原因 |
| `REVIEW_REQUIRED` | `MUTEX_REVIEW_REQUIRED` | 进入专家复核区，不得作为可直接批准项 |

## 3. 证据引用（EvidenceRef）

| evidenceRefId | 来源类型 | 来源 | 状态 |
|---|---|---|---|
| `EV-HOLDING` | 客户事实 | `customerFactSnapshot.holdings`（存量持有） | 受控事实快照 |
| `EV-SRC-FIN-003` | 制度条款 | `SRC-FIN-003`《供应链金融业务操作规程》（应收账款确权/订单融资） | `PENDING_SOURCE` |

## 4. 不变量

- 前置条件未满足 → 排除或转组合依赖（`rules/README.md` 硬约束顺序 5）。
- 互斥/存量冲突 → `INELIGIBLE` 或 `REVIEW_REQUIRED`（`rules/README.md` 硬约束顺序 6）。
- 组合中的任一硬失败产品必须移除，不能以整体分数掩盖。
