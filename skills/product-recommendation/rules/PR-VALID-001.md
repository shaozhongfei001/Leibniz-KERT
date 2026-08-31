---
ruleId: PR-VALID-001
ruleName: 产品有效性规则
ruleVersion: 1.0.0-candidate
category: validity
owner: 公司金融产品管理部
ruleBundleRef: RB-PR-20260831-0001
enforcement: BLOCKING
executionOrder: 2
status: CANDIDATE
frozen: "NO"
implemented: "NO"
trigger: 候选 ProductVersion 非 ACTIVE、或 asOf 超出 [effectiveFrom, effectiveTo]、或机构范围不含本轮调用机构
conclusions:
  - result: PASS
    reasonCode: PRODUCT_VERSION_ACTIVE
    effect: 继续后续规则
  - result: FAIL
    reasonCode: PRODUCT_VERSION_EXPIRED
    effect: 产品级 INELIGIBLE；若该产品无任何 ACTIVE 有效版本则整轮 run=FAIL_CLOSED
  - result: FAIL
    reasonCode: PRODUCT_VERSION_INACTIVE
    effect: 产品级 INELIGIBLE
  - result: FAIL
    reasonCode: INSTITUTION_OUT_OF_SCOPE
    effect: 产品级 INELIGIBLE
evidenceRefs:
  - evidenceRefId: EV-PROD-CARD
    sourceType: PRODUCT_CARD
    sourceId: PROD-FIN-001/002/003（product-cards/，待上传）
  - evidenceRefId: EV-SRC-FIN-001
    sourceType: POLICY
    sourceId: SRC-FIN-001《流动资金贷款管理办法》（PENDING_SOURCE）
---

# PR-VALID-001 产品有效性规则

```text
DOC_STATUS=CANDIDATE
FROZEN=NO
IMPLEMENTED=NO
REAL_E2E_PASS=NO
```

## 1. 触发条件

对每个候选 `ProductVersion` 依次判断（确定性规则）：

1. `productStatus == ACTIVE`；
2. `effectiveFrom <= asOf <= effectiveTo`；
3. `applicableInstitutions` 包含本轮调用机构。

## 2. 结论（result → reasonCode → 下游）

| result | reasonCode | 下游处理 |
|---|---|---|
| `PASS` | `PRODUCT_VERSION_ACTIVE` | 继续后续规则 |
| `FAIL` | `PRODUCT_VERSION_EXPIRED` | 该产品版本 `INELIGIBLE`；该产品无任何 ACTIVE 有效版本时整轮 run=`FAIL_CLOSED` |
| `FAIL` | `PRODUCT_VERSION_INACTIVE` | 该产品版本 `INELIGIBLE` |
| `FAIL` | `INSTITUTION_OUT_OF_SCOPE` | 该产品版本 `INELIGIBLE` |

## 3. 证据引用（EvidenceRef）

| evidenceRefId | 来源类型 | 来源 | 状态 |
|---|---|---|---|
| `EV-PROD-CARD` | 产品卡 | `PROD-FIN-001/002/003`（`03_core` 产品卡，含版本/生效失效时间） | CANDIDATE / 待上传 |
| `EV-SRC-FIN-001` | 制度条款 | `SRC-FIN-001`《流动资金贷款管理办法》 | `PENDING_SOURCE` |

## 4. 不变量

- `INV-01`：`Active(ProductVersion)=false` → 不得进入正式候选。
- `INV-08`：`ProductVersion`/`RuleVersion` 变化 → 下游 `STALE`。
- 产品版本过期或规则版本缺失 → 整轮不得产出可批准方案。

## 5. 对齐说明

对齐 `contracts/examples/valid-sp15-result.json` 中 `ruleId=PR-VALID-001, result=PASS, reasonCode=PRODUCT_VERSION_ACTIVE`（WP0 已验收样例，不改动）。
