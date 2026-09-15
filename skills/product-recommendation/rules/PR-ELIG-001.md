---
ruleId: PR-ELIG-001
ruleName: 客户与机构准入规则
ruleVersion: 1.0.0-candidate
category: customer-eligibility
owner: 公司金融产品管理部
ruleBundleRef: RB-PR-20260831-0001
enforcement: BLOCKING
executionOrder: 4
status: CANDIDATE
frozen: "NO"
implemented: "NO"
trigger: 评估企业类型/规模/评级/开户关系等准入要素
conclusions:
  - result: PASS
    reasonCode: CUSTOMER_TYPE_ALLOWED
    effect: 继续后续规则
  - result: FAIL
    reasonCode: CUSTOMER_TYPE_NOT_ALLOWED
    effect: INELIGIBLE
  - result: FAIL
    reasonCode: RATING_BELOW_MINIMUM
    effect: INELIGIBLE
  - result: UNKNOWN
    reasonCode: CUSTOMER_TYPE_MISSING
    effect: UNKNOWN，生成核实问题，不按满足处理
  - result: UNKNOWN
    reasonCode: RATING_MISSING
    effect: UNKNOWN，生成核实问题，不按满足处理
evidenceRefs:
  - evidenceRefId: EV-SRC-FIN-002
    sourceType: POLICY
    sourceId: SRC-FIN-002《对公客户准入与评级管理办法》（PENDING_SOURCE）
  - evidenceRefId: EV-CUST-FACT
    sourceType: CUSTOMER_FACT
    sourceId: customerFactSnapshot（enterpriseType/scale/rating/hasAccount）
---

# PR-ELIG-001 客户与机构准入规则

```text
DOC_STATUS=CANDIDATE
FROZEN=NO
IMPLEMENTED=NO
REAL_E2E_PASS=NO
```

## 1. 触发条件

评估企业类型 / 规模 / 评级 / 开户关系等准入要素（DMN / 规则引擎）。FAIL → `INELIGIBLE`；必须事实缺失 → `UNKNOWN`（生成核实问题，不按满足处理）。

## 2. 结论（result → reasonCode → 下游）

| result | reasonCode | 下游处理 |
|---|---|---|
| `PASS` | `CUSTOMER_TYPE_ALLOWED` | 继续后续规则 |
| `FAIL` | `CUSTOMER_TYPE_NOT_ALLOWED` | `INELIGIBLE` |
| `FAIL` | `RATING_BELOW_MINIMUM` | `INELIGIBLE` |
| `UNKNOWN` | `CUSTOMER_TYPE_MISSING` | `UNKNOWN`，生成核实问题，不按满足处理 |
| `UNKNOWN` | `RATING_MISSING` | `UNKNOWN`，生成核实问题，不按满足处理 |

## 3. 证据引用（EvidenceRef）

| evidenceRefId | 来源类型 | 来源 | 状态 |
|---|---|---|---|
| `EV-SRC-FIN-002` | 制度条款 | `SRC-FIN-002`《对公客户准入与评级管理办法》 | `PENDING_SOURCE` |
| `EV-CUST-FACT` | 客户事实 | `customerFactSnapshot`（enterpriseType/scale/rating/hasAccount） | 受控事实快照 |

## 4. 不变量

- `INV-03`：`Eligibility=UNKNOWN` → 不得按 `ELIGIBLE` 处理。
- `UNKNOWN` 不能转换为「低置信度通过」。

## 5. 对齐说明

对齐 `contracts/examples/valid-sp15-result.json` 中 `ruleId=PR-ELIG-001, result=PASS, reasonCode=CUSTOMER_TYPE_ALLOWED`（WP0 已验收样例，不改动）。
