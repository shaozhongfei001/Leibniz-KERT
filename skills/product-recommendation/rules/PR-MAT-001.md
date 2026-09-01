---
ruleId: PR-MAT-001
ruleName: 材料规则
ruleVersion: 1.0.0-candidate
category: material
owner: 公司金融产品管理部
ruleBundleRef: RB-PR-20260831-0001
enforcement: NON_BLOCKING
executionOrder: []
executionOrderNote: 材料规则不在 rules/README.md「硬约束执行顺序」(1-7) 内；执行方式为「规则+缺口生成」，不硬阻断 ELIGIBLE
status: CANDIDATE
frozen: "NO"
implemented: "NO"
trigger: 必供材料（合同/订单/报表）缺失或状态未知
conclusions:
  - result: PASS
    reasonCode: MATERIAL_COMPLETE
    effect: 继续后续规则
  - result: FAIL
    reasonCode: MATERIAL_GAP
    effect: 生成材料缺口（不硬阻断 ELIGIBLE，记入 fitResults[].materialGaps / 待办）
  - result: UNKNOWN
    reasonCode: MATERIAL_STATUS_UNKNOWN
    effect: 生成待确认问题，不按满足处理
evidenceRefs:
  - evidenceRefId: EV-MAT-CHECKLIST
    sourceType: PRODUCT_CARD
    sourceId: PROD-FIN-001/002/003（requiredMaterials，待上传）
  - evidenceRefId: EV-SRC-FIN-001
    sourceType: POLICY
    sourceId: SRC-FIN-001《流动资金贷款管理办法》（PENDING_SOURCE）
---

# PR-MAT-001 材料规则

```text
DOC_STATUS=CANDIDATE
FROZEN=NO
IMPLEMENTED=NO
REAL_E2E_PASS=NO
```

## 1. 触发条件

检查必供材料（合同 / 订单 / 报表）是否齐备（规则 + 缺口生成）。

> 本规则为**非阻断**规则（`enforcement: NON_BLOCKING`），**不在** `rules/README.md`「硬约束执行顺序」(1-7) 内；材料缺口不硬阻断 `ELIGIBLE`，仅记入 `fitResults[].materialGaps` / 待办。

## 2. 结论（result → reasonCode → 下游）

| result | reasonCode | 下游处理 |
|---|---|---|
| `PASS` | `MATERIAL_COMPLETE` | 继续后续规则 |
| `FAIL` | `MATERIAL_GAP` | 生成材料缺口；不硬阻断 `ELIGIBLE`，记入 `fitResults[].materialGaps` / 待办 |
| `UNKNOWN` | `MATERIAL_STATUS_UNKNOWN` | 生成待确认问题，不按满足处理 |

## 3. 证据引用（EvidenceRef）

| evidenceRefId | 来源类型 | 来源 | 状态 |
|---|---|---|---|
| `EV-MAT-CHECKLIST` | 产品卡 | `PROD-FIN-001/002/003`（`requiredMaterials`） | CANDIDATE / 待上传 |
| `EV-SRC-FIN-001` | 制度条款 | `SRC-FIN-001`《流动资金贷款管理办法》 | `PENDING_SOURCE` |

## 4. 不变量

- 材料缺口不硬阻断 `ELIGIBLE`，但不得作为「已可批准」的充分依据（进入 `fitResults[].materialGaps`）。
- `INV-04`：CandidateReason → 至少一条 EvidenceRef（材料缺口同样需证据引用）。
