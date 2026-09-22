# Owner 追认记录：`signed-pc8-r4.json`（append-only）

| 项 | 内容 |
|---|---|
| 追认时间 | 2026-09-22 |
| 追认人 | Owner |
| 被追认件 | `90_control/decisions/signed-pc8-r4.json`（25 项决策；`supersedes signed-pc8-r3.json`） |
| 追认内容 | **「r4 签署（沿用 r3 口径，只新增新解锁的 3 卡）」** —— 即确认：<br>① 采纳口径沿用 r3（**本产品族专属监管源**、按 `(sourceId, 条款号)` 最小者）；<br>② 本次仅新增 3 张**新解锁**卡的采纳（`PROD-CM-002` / `PROD-CM-003` ← `REG-CM-001` 第一条；`PROD-FIN-003` ← `REG-FIN-001` 第三条）；<br>③ 其余 4 卡（`PROD-CB-001` / `PROD-FIN-002` / `PROD-SET-001` / `PROD-SET-002`）**不采纳**、保留 `CANDIDATE`（解读页不呈现）。 |
| 口径边界（不变） | 裁决**不构成合规结论**；仅供 DEMO 轨呈现。以具体条款作为合规依据，须由合规 Owner **逐条复核**后重裁（原 `attestation` 已载明，本次追认不放宽该边界）。 |
| 追认前状态 | r4 于 2026-09-22 由 TL 依 Owner「接着做」指示落盘，`attestation` 中已明示「未逐条再请确认具体条款」；本条为该事项的 **Owner 事后确认（append-only，不改原签署件）**。 |

## 生效范围（追认时的实测事实）

- 13 卡投影：**9 张 `regulatoryBasis = SUPPORTED` + 证据 1 条**；4 张 `UNKNOWN`（未采纳，如实不呈现）；
- 五道门禁：`L10 384/384` · `L11 7469/7469` · `L12 153/153` · `L13 1176/1176` · `registry 167/167`；
- 追溯链：`signed-pc8.json`（r1，29 项）→ `signed-pc8-r2.json`（撤销 13 条 N/A）→ `signed-pc8-r3.json`（采纳 6）→ `signed-pc8-r4.json`（+3）；**各件均原样留存，未回改**。
