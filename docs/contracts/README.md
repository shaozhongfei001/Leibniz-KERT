# KERT 契约目录（v2 候选 + 运行中权威说明）

> 状态：CANDIDATE（**本目录 v2 候选未批准**）
> 日期：2026-08-26
> **权威声明修正于 2026-09-15**（见下；原声明与服务实际不符，已登记为冲突 C-20）

## 权威文件（**修正于 2026-09-15**）

- **运行中权威（服务实际实现、向 GITS 提供）**：`specs/kert-openapi-v1.yaml`
  （`version 1.5.0`；其 v1.5 additive 增量与 `assemblyTrace` 类型修正已由 Contract Owner
  于 2026-09-15 追认，登记见 `docs/governance/KERT_PENDING_OWNER_DECISION_M7_EVOLUTION_V1.0.md` §0.1）
- **本目录的 v2 候选**：`openapi/kert-openapi-v2.yaml`（自述 `2.0.0-candidate`）——
  **未批准，不构成生产合同**
- JSON Schema：`schemas/*.json`；其中 `schemas/assembly-trace.schema.json` 是 trace 条目的
  **canonical 定义**，v1 规范以引用方式指向它、**不复写字段**

> ⚠ **原文修正说明**：原文称本目录为"契约唯一权威源"、v1.3/v1.4"不作为生产合同唯一权威源"，
> 与**服务实际实现**不符（实际运行的是 v1.5）。该双权威现状已登记为冲突 **C-20**
> （`docs/governance/KERT_DOCUMENT_CONFLICT_REGISTER.md`）：Contract Owner 2026-09-15
> 批准**列入 W8/Phase 0 收口**，**归并尚未执行**。归并完成前以 v1.5 为运行中权威。

## 校验命令

```bash
cd kert
.venv/bin/python scripts/validate_contract_bundle.py
.venv/bin/python scripts/contract_bundle_hash.py
```

## 兼容策略（按 2026-09-15 修正）

- v1.5（`specs/kert-openapi-v1.yaml`）为**运行中权威**；v1.3/v1.4 为历史说明
- v2 候选为**生产合同候选**（Phase 0），未经 Contract Owner 批准前不得据以实施
- 新增 `/api/v2/*`（候选），v1 保留兼容层
- v2 默认拒绝未知字段（或显式 warning）

## 缺失

- GITS 权威 ContextPackage 附录尚未纳入，需 Contract Owner 对齐。
- **v1 ↔ v2 归并未开工**（冲突 C-20，已列入 W8/Phase 0 收口）。
