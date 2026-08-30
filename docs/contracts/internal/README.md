# DKWS Python Core — Java Skill Runtime 内部契约

> 状态：CANDIDATE
> 日期：2026-08-26（JR-1 双端测试补充：2026-08-30）
> 工作流：DKWS-C-MIXED-ARCH-REMEDIATION-01
> 原则：内部 API 不对外公开；GITS 不得直接访问。

## 文件

受控契约资产（**参与 bundle hash**，共 7 份）：

- `openapi/dkws-skill-runtime-internal-v1.yaml`
- `schemas/execution-plan.schema.json`
- `schemas/execution-result.schema.json`
- `schemas/tool-call-receipt.schema.json`
- `schemas/model-call-receipt.schema.json`
- `schemas/runtime-error.schema.json`
- `schemas/runtime-capabilities.schema.json`

测试资产（**不参与** bundle hash）：

- `examples/*.json` — 每类对象一份完整示例 + 一份边界示例（最小必填 /
  降级 / 拦截 / 错误），共 12 份，供 Python 与 Java 双端测试共用。

## 契约 hash

```bash
python3 scripts/internal_contract_hash.py
```

当前 bundle hash（契约版本 `1.0.0-candidate`）：

```text
64b9b432d6ee9fc9e017436171f05e1198ab920121202266c835c471ff2c4550
```

算法：按相对路径排序，逐文件取 sha256，再对
`"<相对路径>\0<sha256>\0"` 拼接串取 sha256。

该值在四处必须一致，任一处漂移都会导致双端测试失败：

1. `scripts/internal_contract_hash.py` 输出
2. Java `InternalContractHashTest` 独立重算值
3. `InternalRuntimeController.CONTRACT_HASH` 内置常量
4. `evidence/jr1/internal-contract-hash.txt` 记录值

> 注：`docs/contracts/openapi/dkws-openapi-v2.yaml`（**对外**公共契约）
> 仍存在 `x-contract-bundle-hash: PENDING_COMPUTE`，属已登记冲突项 C-19
> （见 `docs/governance/DKWS_DOCUMENT_CONFLICT_REGISTER.md`）。
> 该占位符位于对外契约，**不在** JR-1 内部契约范围内，需 Tech Lead 决策后处理。

## 校验

```bash
# 契约 bundle 结构与 hash
python3 scripts/validate_contract_bundle.py
python3 scripts/internal_contract_hash.py

# 双端契约测试 + hash 三方比对，一条命令
python3 scripts/verify_jr1_internal_contract.py
```

分侧执行：

```bash
# Python 侧（consumer/provider contract tests）
.venv/bin/python -m pytest tests/contract/internal

# Java 侧（Skill Runtime POC）
cd poc/spring-ai-alibaba-skill-runtime && mvn -o -B test
```

## 语义

- 服务到服务认证：`X-Internal-Token`
- 防重放：`X-Nonce` + timestamp + HMAC
- 同 key 不同 payload：拒绝（`IDEMPOTENCY_CONFLICT`，`retryable=false`，HTTP 409）
- deadline/timeout/cancel/retryable 明确（超时 → `DEADLINE_EXCEEDED`，HTTP 408）
- Java Runtime 不可达、重启、Sandbox 不可用、模型不可用均需显式错误
- 降级结果（`status=DEGRADED`）必须携带 `degradationReason` 且
  `releaseAllowed=false`
- 契约信封为**封闭对象**（`additionalProperties: false`）；
  业务自由字段只能置于开放容器：`result` / `contextPackage` /
  `customerScope` / `details` / `sideEffectReceipt`

## 双端测试覆盖

| 侧 | 位置 | 用例数 |
|----|------|--------|
| Python | `tests/contract/internal/` | 117 |
| Java | `poc/spring-ai-alibaba-skill-runtime/src/test/java/com/dkws/skillruntime/contract/` | 73 |

证据：`evidence/jr1/`（含日志、hash、端到端报告、失败记录）。

## 边界

- 本契约仅用于 Python Core ↔ Java Skill Runtime 的**内部**调用。
- 路径全部限定 `/internal/` 前缀，服务器地址限回环，由测试断言守护。
- GITS 只能通过 Python Core 的**公共** HTTP 接口间接触达 Runtime 能力。
