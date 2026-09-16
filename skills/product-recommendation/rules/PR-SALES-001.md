---
ruleId: PR-SALES-001
ruleName: 销售边界规则
ruleVersion: 1.0.0-candidate
category: sales-boundary
owner: 公司金融产品管理部（+ 合规管理部）
ruleBundleRef: RB-PR-20260831-0001
enforcement: BLOCKING
executionOrder: 7
status: CANDIDATE
frozen: "NO"
implemented: "NO"
trigger: 涉及禁止承诺、必须专家介入、材料不可替代等高边界场景
conclusions:
  - result: PASS
    reasonCode: WITHIN_SALES_BOUNDARY
    effect: 继续后续规则
  - result: REVIEW_REQUIRED
    reasonCode: EXPERT_REVIEW_REQUIRED
    effect: REVIEW_REQUIRED，保留边界并强制 HumanGate
  - result: FAIL
    reasonCode: COMMITMENT_PROHIBITED
    effect: 不得以承诺性表述呈现，禁止进入可批准候选
evidenceRefs:
  - evidenceRefId: EV-BOUNDARY-POLICY
    sourceType: POLICY
    sourceId: SRC-FIN-005《流动资金贷款风险管理指引》（PENDING_SOURCE）
  - evidenceRefId: EV-PROD-CARD
    sourceType: PRODUCT_CARD
    sourceId: PROD-FIN-001/002/003（禁止承诺/人工复核要求，待上传）
---

# PR-SALES-001 销售边界规则

```text
DOC_STATUS=CANDIDATE
FROZEN=NO
IMPLEMENTED=NO
REAL_E2E_PASS=NO
```

## 1. 触发条件

评估是否涉及禁止承诺、必须专家介入、材料不可替代等高边界场景（规则 + HumanGate）。

## 2. 结论（result → reasonCode → 下游）

| result | reasonCode | 下游处理 |
|---|---|---|
| `PASS` | `WITHIN_SALES_BOUNDARY` | 继续后续规则 |
| `REVIEW_REQUIRED` | `EXPERT_REVIEW_REQUIRED` | `REVIEW_REQUIRED`，保留边界并强制 HumanGate |
| `FAIL` | `COMMITMENT_PROHIBITED` | 不得以承诺性表述呈现，禁止进入可批准候选 |

## 3. 证据引用（EvidenceRef）

| evidenceRefId | 来源类型 | 来源 | 状态 |
|---|---|---|---|
| `EV-BOUNDARY-POLICY` | 制度条款 | `SRC-FIN-005`《流动资金贷款风险管理指引》 | `PENDING_SOURCE` |
| `EV-PROD-CARD` | 产品卡 | `PROD-FIN-001/002/003`（禁止承诺事项/人工复核要求） | CANDIDATE / 待上传 |

## 4. 不变量

- 销售边界 → 保留边界并强制门禁（`rules/README.md` 硬约束顺序 7）。
- 所有对客文案必须另行经过销售边界与受控发送门禁。
- `INV-09`：AI 输出不得直接创建授信/定价/审批/写回动作。
