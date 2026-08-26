# DKWS Python Core — Java Skill Runtime 内部契约

> 状态：CANDIDATE
> 日期：2026-08-26
> 工作流：DKWS-C-MIXED-ARCH-REMEDIATION-01
> 原则：内部 API 不对外公开；GITS 不得直接访问。

## 文件

- `openapi/dkws-skill-runtime-internal-v1.yaml`
- `schemas/*.schema.json`

## 校验

```bash
cd dkws
python3 scripts/validate_contract_bundle.py
python3 scripts/contract_bundle_hash.py
```

## 语义

- 服务到服务认证：`X-Internal-Token`
- 防重放：`X-Nonce` + timestamp + HMAC
- 同 key 不同 payload：拒绝
- deadline/timeout/cancel/retryable 明确
- Java Runtime 不可达、重启、Sandbox 不可用、模型不可用均需显式错误
