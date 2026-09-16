# `_authoritative/` 权威区

> Loop PI-0 G0-3 建立。`usage: AUTHORITATIVE`

## 用途

存放行内制度与监管法规，由 Owner 上传。**这是产品卡字段的唯一合法 EvidenceRef 来源。**

## 证据能力

- 可支撑产品卡转 `ACTIVE` + `FROZEN=YES`
- `authorityLevel` 取 `REGULATORY` 或 `INTERNAL_POLICY`
- 需经 `CLAUSE_VERIFIED`（条款号由 Owner 核定）后才能作确定性依据（INV-05/INV-10）

## 约定

- 文件命名与 `source-registry.md` 的 `source_id` 一致，如 `SRC-CM-001.pdf`
- 入库后须在登记表回填 `bytes_sha256`
- 网页类源的时点快照放 `snapshots/`，快照 + `bytes_sha256` 才构成可复现凭据
- 含 front matter 的 Markdown 源可填 `sourceContentHash`（`sha256:` 前缀）；
  PDF/HTML 只能填 `sourceBytesHash`（纯 hex）

## 当前状态

> L03 订正 2026-09-05（F-L00-03）：原表述「空。27 条已登记源全部 `PENDING_SOURCE`」
> 已过时，与 `source-registry.md` 明细行冲突。

**1 份已入库**：

| sourceId | 状态 | bytes | SHA-256 | 备注 |
|---|---|---|---|---|
| REG-CM-001 | `AVAILABLE` | 92460 | `105df242da87f50587208351c6abb07ddde2d689ab13e0d0619f420875290024` | 抽出 25 条款，`clauseVerified=false`，条款号待 Owner 核定 |

**27 条仍为 `PENDING_SOURCE`**，等待 Owner 上传（Gate G0-6）。
`CLAUSE_VERIFIED` 状态目前 **0 条**。

优先级：CASH_MANAGEMENT pilot 族剩余 3 份（SRC-CM-001/002/003）。
