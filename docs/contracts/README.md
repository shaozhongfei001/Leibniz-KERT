# DKWS 契约唯一权威源（Phase 0 候选）

> 状态：CANDIDATE
> 日期：2026-08-26

## 权威文件

- OpenAPI：`openapi/dkws-openapi-v2.yaml`
- JSON Schema：`schemas/*.json`

## 校验命令

```bash
cd dkws
.venv/bin/python scripts/validate_contract_bundle.py
.venv/bin/python scripts/contract_bundle_hash.py
```

## 兼容策略

- v1.3/v1.4 保留为兼容/历史说明，不作为生产合同唯一权威源
- 本 v2 候选为生产合同候选
- 新增 `/api/v2/*`，v1 保留兼容层
- v2 默认拒绝未知字段（或显式 warning）

## 缺失

- GITS 权威 ContextPackage 附录尚未纳入，需 Contract Owner 对齐。
