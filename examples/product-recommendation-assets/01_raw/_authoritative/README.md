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

**9 份已入库**：

| sourceId | 状态 | bytes | SHA-256 | 备注 |
|---|---|---|---|---|
| REG-CM-001 | `AVAILABLE` | 92460 | `105df242da87f50587208351c6abb07ddde2d689ab13e0d0619f420875290024` | 抽出 25 条款，`clauseVerified=false`，条款号待 Owner 核定 |
| REG-XFAM-001 | `AVAILABLE` | 14341 | `300f1d6d68b475c37042e6782d7f882b8105dfca0121a4150879e19b9787d24b` | 《商业银行服务价格管理办法》全文 7 章 38 条，`clauseVerified=false` |
| REG-FIN-001 | `AVAILABLE` | 21864 | `dfa2dbff3746a7e20462178268e62bcb7626ba009a32389193afd3cd9bb4fdc5` | 《流动资金贷款管理办法》现行版（2024 年第 2 号令）8 章 51 条 + 附件；⚠ 原登记 2010 年暂行办法已废止，**版本变更已显式登记** |
| REG-IB-001 | `AVAILABLE` | 16042 | `c9f87041941540d6c65794e3f812b9255cb852e793159f070eba0fec96cf61e5` | 《商业银行并购贷款管理办法》现行版（金规〔2025〕27 号）34 条；⚠ 原登记 2015 年指引已废止，**版本变更已显式登记** |
| REG-CB-002 | `AVAILABLE` | 12512 | `e2e87a3c0fcc3294de04c72e923439cec32d60a5bac6add4c7f0f5716d439b8d` | 《跨境担保外汇管理规定》（汇发〔2014〕29号）5 章 33 条；**双源**：条文取政府网站 HTML 承载、文号/日期取外汇局官网通知 |
| REG-TF-003 | `AVAILABLE` | 29338 | `fd3ba439c11d5c65d7aece2943cc37a814c431fb067fd5f41f14b65318d364b8` | 《票据法》（法律）七章一百一十条；**新增行（D-R1）**，基数 27→28 |
| REG-TF-002 | `AVAILABLE` | 29688 | `617e9640e125d100a26f3a4778f37e0ea343ef18ddd81d8e99bb8b6610b4a872` | 《国内信用证结算办法》现行版（公告〔2016〕第10号）5 章 60 条；⚠ 原登记 1997 年版已废止，**版本变更已显式登记** |
| REG-TF-001 | `AVAILABLE` | 13440 | `5aeaa4ae76deeac981ae385a0857dd07a5d80df0f1fb123ef575da895d0f7102` | 《商业汇票承兑、贴现与再贴现管理办法》（令〔2022〕第 4 号）八章四十二条；⚠ 原登记未指名，**指名结果已登记**（《票据法》不在覆盖范围） |
| REG-CM-002 | `AVAILABLE` | 33182 | `70856944765f2ae2192414d2714e1c42bd036ceedd83c80ef4ddbeefa98d1654` | 《人民币银行结算账户管理办法》七章七十一条；⚠ **2020 年第 2 号令删除第二十三条第一款第一项**已原位标注；**`REG-SET-001` 合并为别名** |

**19 条仍为 `PENDING_SOURCE`**，等待 Owner 上传（Gate G0-6）。
`CLAUSE_VERIFIED` 状态目前 **0 条**。

优先级：CASH_MANAGEMENT pilot 族剩余 3 份（SRC-CM-001/002/003）。

> **PC8 补充（2026-09-22）**：本区另有**演示文本**（`.DEMO.md`，`provenance_state: DEMO`）
> 14 份 —— `SRC-CM-001/002/003`、`SRC-XFAM-001/002/003`、`SRC-FIN-001/003/005`、`SRC-SET-001/002` 与 `SRC-TF-001/002/003`；它们**不是**真实制度、
> **不计入**上述已入库份数、**不抵扣**真实缺口。真实 `SRC-*` 材料的 Owner 上传义务不变。
