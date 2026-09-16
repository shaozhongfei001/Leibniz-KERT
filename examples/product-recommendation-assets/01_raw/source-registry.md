# 源文件登记（Source Registry）

> 状态块：
> - **CANDIDATE**
> - **FROZEN=NO**
> - **IMPLEMENTED=NO**
>
> Loop PI-0 · Gate G0-3 重构（2026-09-04）。
> 本次变更：由单族（FINANCING）扩展至 OQ-B 裁决的 6 族全覆盖；引入
> `_authoritative/` 与 `_public_reference/` 双区语义；权威分级对齐
> `CTR-PK-EVR-001`（`specs/product-knowledge/evidence-ref.schema.json`）的
> `authorityLevel` 枚举。

---

## 1. 双区语义（Owner 裁决 OQ-A 落地）

源材料按用途分入两个物理区，**区归属决定其证据能力上限**：

```
01_raw/
├── _authoritative/       usage: AUTHORITATIVE
│   │                     行内制度与监管法规，由 Owner 上传
│   │                     产品卡字段的唯一合法 EvidenceRef 来源
│   │                     可支撑产品卡转 ACTIVE + FROZEN=YES
│   └── snapshots/        网页类源的时点快照（配 bytes_sha256 构成可复现凭据）
│
└── _public_reference/    usage: VERIFICATION_ONLY
                          公开可得资料，仅用于验证解析器能否读取源材料
                          不验证内容正确性，不得作为产品卡字段的权威依据
                          引用它的产品卡永久停留 CANDIDATE
```

**门禁规则**：产品卡转 ACTIVE 的前置条件为「所有 HardRule 相关字段的 EvidenceRef
全部 `usage=AUTHORITATIVE` 且 `source_path` 落在 `_authoritative/` 下」。引用了
`VERIFICATION_ONLY` 证据的产品卡被自动阻断，无需人工判断。门禁实现在 PI-1 G1-5。

**为何要分区**：Owner 裁决明确「公开分类骨架仅为目前做演示和验证；不能否定 Owner
上传行内制度到 01_raw」。分区把这条约束从「靠人记住」变成「靠路径前缀机器可判」——
`evidence-ref.schema.json` 的 `source_path` 字段已用 pattern
`^01_raw/(_authoritative|_public_reference)/` 强制。

---

## 2. 权威分级

四级降序，与 `CTR-PK-EVR-001` 的 `authorityLevel` 枚举**严格一一对应**，不得另造名称：

| 级别 | 枚举值 | 典型材料 | 默认 usage | 默认区 |
|---|---|---|---|---|
| 1（最高） | `REGULATORY` | 监管法规、部门规章 | AUTHORITATIVE | `_authoritative/` |
| 2 | `INTERNAL_POLICY` | 行内产品管理办法、操作规程、风险政策 | AUTHORITATIVE | `_authoritative/` |
| 3 | `PUBLIC_PRICE_DISCLOSURE` | 监管强制公示的服务价格目录 | VERIFICATION_ONLY | `_public_reference/` |
| 4（最低） | `PUBLIC_MARKETING` | 官网产品介绍页 | VERIFICATION_ONLY | `_public_reference/` |

**冲突消解**：高等级覆盖低等级。同级冲突不得作确定性解读，须记入 `conflicts`（INV-10）。

**注意等级与 usage 是两个正交维度**：`PUBLIC_PRICE_DISCLOSURE` 虽属监管强制公示、
可信度不低，但因其只覆盖收费维度、无法提供准入/排除/前置规则，且我们引用的是他行公示
材料而非本机构制度，故一律标 `VERIFICATION_ONLY`。**公示价目可信 ≠ 可作为我们产品卡的
权威依据**。

---

## 3. 源 ID 命名约定

与 `evidence-ref.schema.json` 的 `sourceId` pattern `^[A-Z][A-Z0-9]*(-[A-Z0-9]+)+$` 兼容：

| 前缀 | 含义 | 区 | 示例 |
|---|---|---|---|
| `REG-*` | 监管法规 | `_authoritative/` | `REG-FIN-001` |
| `SRC-*` | 行内制度 | `_authoritative/` | `SRC-CM-001` |
| `PUB-*` | 公开资料 | `_public_reference/` | `PUB-PRICE-001` |

族段采用 taxonomy 族 id 缩写：`CM` 现金管理 · `SET` 结算 · `TF` 贸易金融 ·
`CB` 跨境金融 · `FIN` 融资 · `IB` 投资银行 · `XFAM` 跨族通用。

---

## 4. 状态机

```
PENDING_SOURCE  材料未上传，仅登记预期
      ↓  Owner 上传 / 下载入库
AVAILABLE       材料已入库，bytes_sha256 已记录
      ↓  条款号核定（仅 _authoritative/ 需要）
CLAUSE_VERIFIED 条款号已由 Owner 核定，可作确定性依据
```

`_authoritative/` 区的源在 `CLAUSE_VERIFIED` 之前**不得作为确定性依据**（INV-05/INV-10）。
`_public_reference/` 区的源无需 `CLAUSE_VERIFIED`——它本就不作依据，到 `AVAILABLE` 即可用于解析验证。

---

## 5. 权威区登记（`_authoritative/`）

### 5.1 跨族通用制度

| source_id | source_title | authority_level | owner | status | clause（待核定） | 被引用产品卡 |
|---|---|---|---|---|---|---|
| SRC-XFAM-001 | 《对公客户准入与评级管理办法》（行内制度） | INTERNAL_POLICY | 公司金融产品管理部 | PENDING_SOURCE | 客户类型/规模/评级准入条款 | 全部 13 张 |
| SRC-XFAM-002 | 《产品定价管理办法》（行内制度） | INTERNAL_POLICY | 公司金融产品管理部 | PENDING_SOURCE | 利率/费率定价区间与审批权限 | 全部 13 张 |
| SRC-XFAM-003 | 《对公业务销售适当性管理办法》（行内制度） | INTERNAL_POLICY | 合规管理部 | PENDING_SOURCE | 销售边界、适当性评估、禁止行为条款 | 全部 13 张 |
| REG-XFAM-001 | 《商业银行服务价格管理办法》（原银监会/发改委 2014 年第 1 号令） | REGULATORY | 合规管理部 | PENDING_SOURCE | 价格公示义务、政府指导价与市场调节价划分 | 全部 13 张（价格边界章节） |

### 5.2 CASH_MANAGEMENT 现金管理（pilot 族，3 卡）

| source_id | source_title | authority_level | owner | status | clause（待核定） | 被引用产品卡 |
|---|---|---|---|---|---|---|
| SRC-CM-001 | 《现金管理业务管理办法》（行内制度） | INTERNAL_POLICY | 交易银行部 | PENDING_SOURCE | 现金池准入、成员户要求、归集规则 | PROD-CM-001/002 |
| SRC-CM-002 | 《法人账户透支业务操作规程》（行内制度） | INTERNAL_POLICY | 交易银行部 | PENDING_SOURCE | 透支额度、期限、还款与风险控制 | PROD-CM-003 |
| SRC-CM-003 | 《集团客户资金集中管理风险政策》（行内制度） | INTERNAL_POLICY | 风险管理部 | PENDING_SOURCE | 集团授信联动、成员户风险隔离 | PROD-CM-001/002/003 |
| REG-CM-001 | 《现金管理暂行条例》（2011修订，国务院令第12号） | REGULATORY | 合规管理部 | **AVAILABLE** | 25条已抽取，待Owner核定后转CLAUSE_VERIFIED | PROD-CM-001/002/003 |
| REG-CM-002 | 《人民币银行结算账户管理办法》 | REGULATORY | 合规管理部 | PENDING_SOURCE | 账户开立、使用与资金归集合规要求 | PROD-CM-001/002 |

### 5.3 SETTLEMENT 结算（2 卡）

| source_id | source_title | authority_level | owner | status | clause（待核定） | 被引用产品卡 |
|---|---|---|---|---|---|---|
| SRC-SET-001 | 《单位结算账户管理实施细则》（行内制度） | INTERNAL_POLICY | 交易银行部 | PENDING_SOURCE | 开户准入、材料清单、账户分类 | PROD-SET-001 |
| SRC-SET-002 | 《国内保理业务管理办法》（行内制度） | INTERNAL_POLICY | 交易银行部 | PENDING_SOURCE | 应收账款转让、确权、追索权约定 | PROD-SET-002 |
| REG-SET-001 | 《人民币银行结算账户管理办法》 | REGULATORY | 合规管理部 | PENDING_SOURCE | 单位银行结算账户开立与管理 | PROD-SET-001 |

### 5.4 TRADE_FINANCE 贸易金融（2 卡）

| source_id | source_title | authority_level | owner | status | clause（待核定） | 被引用产品卡 |
|---|---|---|---|---|---|---|
| SRC-TF-001 | 《银行承兑汇票业务管理办法》（行内制度） | INTERNAL_POLICY | 交易银行部 | PENDING_SOURCE | 承兑准入、保证金比例、期限 | PROD-TF-001 |
| SRC-TF-002 | 《国内信用证业务操作规程》（行内制度） | INTERNAL_POLICY | 交易银行部 | PENDING_SOURCE | 开证条件、单据审核、付款期限 | PROD-TF-002 |
| SRC-TF-003 | 《贸易背景真实性审查指引》（行内制度） | INTERNAL_POLICY | 风险管理部 | PENDING_SOURCE | 贸易背景核验、单据要求、虚假贸易防范 | PROD-TF-001/002 |
| REG-TF-001 | 《票据法》及票据业务相关监管规定 | REGULATORY | 合规管理部 | PENDING_SOURCE | 票据承兑、贴现的法定要件 | PROD-TF-001 |
| REG-TF-002 | 《国内信用证结算办法》 | REGULATORY | 合规管理部 | PENDING_SOURCE | 国内信用证开立、议付、偿付规则 | PROD-TF-002 |

### 5.5 CROSS_BORDER 跨境金融（2 卡）

| source_id | source_title | authority_level | owner | status | clause（待核定） | 被引用产品卡 |
|---|---|---|---|---|---|---|
| SRC-CB-001 | 《跨境人民币业务管理办法》（行内制度） | INTERNAL_POLICY | 国际业务部 | PENDING_SOURCE | 跨境结算准入、真实性审核、报送要求 | PROD-CB-001 |
| SRC-CB-002 | 《内保外贷业务管理办法》（行内制度） | INTERNAL_POLICY | 国际业务部 | PENDING_SOURCE | 担保额度、境外主体资质、履约风险 | PROD-CB-002 |
| REG-CB-001 | 跨境人民币结算相关监管规定 | REGULATORY | 合规管理部 | PENDING_SOURCE | 跨境人民币结算的展业三原则与合规要求 | PROD-CB-001 |
| REG-CB-002 | 《跨境担保外汇管理规定》 | REGULATORY | 合规管理部 | PENDING_SOURCE | 内保外贷登记、额度与资金用途限制 | PROD-CB-002 |

### 5.6 FINANCING 融资（3 卡）

> 本节沿用重构前的原始登记条目，仅补 authority_level 与 source_path 两列，
> 未改动 source_id / title / owner，避免破坏已有产品卡的 EvidenceRef 引用。
> 原 SRC-FIN-002（客户准入）与 SRC-FIN-004（定价）因属跨族通用，已上移至 5.1 节
> 并改 ID 为 SRC-XFAM-001 / SRC-XFAM-002；此处保留原 ID 作为**别名**过渡，
> PI-1 解读管道落地时统一收敛。

| source_id | source_title | authority_level | owner | status | clause（待核定） | 被引用产品卡 |
|---|---|---|---|---|---|---|
| SRC-FIN-001 | 《流动资金贷款管理办法》（行内制度） | INTERNAL_POLICY | 公司金融产品管理部 | PENDING_SOURCE | 准入条件、资金用途、期限、受托/自主支付相关条款 | PROD-FIN-001/002/003 |
| SRC-FIN-002 | 《对公客户准入与评级管理办法》（行内制度）— 别名，见 SRC-XFAM-001 | INTERNAL_POLICY | 公司金融产品管理部 | PENDING_SOURCE | 客户类型/规模/评级准入条款 | PROD-FIN-001/002/003 |
| SRC-FIN-003 | 《供应链金融业务操作规程》（行内制度） | INTERNAL_POLICY | 公司金融产品管理部 | PENDING_SOURCE | 应收账款确权/登记、订单融资流程条款 | PROD-FIN-002/003 |
| SRC-FIN-004 | 《产品定价管理办法》（行内制度）— 别名，见 SRC-XFAM-002 | INTERNAL_POLICY | 公司金融产品管理部 | PENDING_SOURCE | 利率/费率定价区间与审批权限 | PROD-FIN-001/002/003 |
| SRC-FIN-005 | 《流动资金贷款风险管理指引》（行内制度） | INTERNAL_POLICY | 公司金融产品管理部 | PENDING_SOURCE | 风险提示、贷后管理、资金挪用防范条款 | PROD-FIN-001/002/003 |
| REG-FIN-001 | 《流动资金贷款管理暂行办法》（原银监会令〔2010〕第 1 号） | REGULATORY | 合规管理部 | PENDING_SOURCE | 流动资金贷款用途限制与受托支付标准 | PROD-FIN-001/003 |
| REG-FIN-002 | 《商业银行互联网贷款管理暂行办法》（如涉及线上化） | REGULATORY | 合规管理部 | PENDING_SOURCE | 线上放款/自主支付额度上限 | PROD-FIN-001（如线上化） |

### 5.7 INVESTMENT_BANKING 投资银行（1 卡）

| source_id | source_title | authority_level | owner | status | clause（待核定） | 被引用产品卡 |
|---|---|---|---|---|---|---|
| SRC-IB-001 | 《并购贷款业务管理办法》（行内制度） | INTERNAL_POLICY | 投资银行部 | PENDING_SOURCE | 并购主体资质、贷款比例上限、期限 | PROD-IB-001 |
| REG-IB-001 | 《商业银行并购贷款风险管理指引》 | REGULATORY | 合规管理部 | PENDING_SOURCE | 并购贷款占比上限、风险评估要求 | PROD-IB-001 |

---

## 5.8 DEMO 演示轨登记（`_authoritative/` · `provenance_state: DEMO`）

> Owner 决议 **DECISION-20260906-01（演示路径 C）**：批准生成演示制度文本，明确标记为 DEMO 而非真实制度。
>
> **红线（L10 落地）**：
> 1. 本节 3 条**均为虚构演示文本**，不代表任何真实机构制度；
> 2. DEMO 源**不计入** §5 真实权威区基数（28），**不抵扣** 27/28 真实缺口 —— **F-L00-07 未解除**；
> 3. 依 DEMO 源编译的 Release 必须带 `provenance_state=DEMO`，**不得**进入 `RECOMMENDATION_READY`（INV-EVS-09/10/11）；
> 4. DEMO 证据**不得与** VERIFIED 证据混合支撑同一字段断言，禁止用演示材料补真实材料缺口。

| source_id | source_title | authority_level | provenance_state | status | 物理文件 | 被引用产品卡 |
|---|---|---|---|---|---|---|
| SRC-CM-001 | 《现金管理业务管理办法（演示文本）》 | INTERNAL_POLICY | DEMO | **AVAILABLE (DEMO)** | `01_raw/_authoritative/SRC-CM-001.DEMO.md` | 无（禁止沿用 13 张 legacy card） |
| SRC-CM-002 | 《法人账户透支业务操作规程（演示文本）》 | INTERNAL_POLICY | DEMO | **AVAILABLE (DEMO)** | `01_raw/_authoritative/SRC-CM-002.DEMO.md` | 无 |
| SRC-CM-003 | 《集团客户资金集中管理风险政策（演示文本）》 | INTERNAL_POLICY | DEMO | **AVAILABLE (DEMO)** | `01_raw/_authoritative/SRC-CM-003.DEMO.md` | 无 |

**物理隔离约定**：真实行内制度上传时落 `SRC-CM-001.pdf` / `SRC-CM-001.md`；演示文本固定带
`.DEMO.md` 后缀。§5.2 中 `SRC-CM-001/002/003` 三行**仍记 `PENDING_SOURCE`** —— 真实行内制度尚未上传，
演示文本不替代 Owner 上传义务。

**DEMO 源入库记录**

| source_id | 文件字节数 | bytes_sha256 | 条款数 | 入库时间 | 定位方式 |
|---|---|---|---|---|---|
| SRC-CM-001 | 4280 | `5879e81430538f75091805f2f3a2db23bd2cd98bbbb32f731c575221d058093f` | 19 | 2026-09-06 | CLAUSE（章条号） |
| SRC-CM-002 | 3509 | `984fe6cde0c2b17bfad0b1c05d0a6f80ae7701647c8155b85b3ec57c92f375a2` | 17 | 2026-09-06 | CLAUSE（章条号） |
| SRC-CM-003 | 3422 | `b4599dd141caa7d1934cd69de58fdc8245e6d631d0bec33477593b88e341fe29` | 15 | 2026-09-06 | CLAUSE（章条号） |

**内建已知冲突（演示数据，非缺陷）**：`SRC-CM-001` 第十条规定现金池主账户最低留存 **50 万元**，
`SRC-CM-003` 第六条规定集团现金池主账户最低留存 **100 万元**。该 VALUE_MISMATCH 由 L10 故意保留，
用于 L12 冲突检测与 ConflictCase 编译的实证样本；在 EVIDENCE 与 FAILURES 中显式登记，不得事后静默修正。

---

## 6. 公开参考区登记（`_public_reference/`）

> **本区材料的唯一合法用途是验证解析器能否读取源材料**，不验证内容正确性，
> 不得作为任何产品卡字段的权威依据。引用本区证据的产品卡永久停留 CANDIDATE。
>
> 合规约束（调研 C-2）：仅作内部研发的解析能力验证，不向外分发；不得将来源机构
> 名称写入产品卡或 taxonomy 数据字段；产品卡 `institution` 统一标注 `DEMO-BANK`。

| source_id | source_title | authority_level | status | 用途 | 入库路径 |
|---|---|---|---|---|---|
| PUB-PRICE-001 | 对公客户市场调节价服务名录（结算业务类，公开公示 PDF） | PUBLIC_PRICE_DISCLOSURE | **AVAILABLE** | G0-5 解析验证：PDF→结构化条目+物理页码定位 | `01_raw/_public_reference/PUB-PRICE-001.pdf` |
| PUB-PRICE-002 | 对公及机构客户服务收费目录（公开公示 PDF） | PUBLIC_PRICE_DISCLOSURE | **AVAILABLE** | G0-5 跨版式对照（18列稀疏版式） | `01_raw/_public_reference/PUB-PRICE-002.pdf` |

**PUB-PRICE-001 入库记录（G0-5 已完成）**

| 项 | 值 |
|---|---|
| 文件字节数 | 195967 |
| `bytes_sha256` | `fa276e30c4e3ae115920703d10cd89a143630ac298d4c1fdb1c885502170303e` |
| 物理页数 | 2 |
| 入库时间 | 2026-09-04 |
| 解析器 | `pdfplumber@0.11.10` |


**G0-5 入库须知（源自 `CTR-PK-EVR-001` 约束）**：

1. **PDF 只能填 `sourceBytesHash`**（纯 hex 无前缀），不能填 `sourceContentHash`——
   PDF 无 front matter，`content_hash` 的定义在其上不适用。
2. **`page` 必须是物理页码**（PDF 文件第 N 页），非印刷页码。封面与目录导致的偏移是
   PDF 定位最常见错源。
3. **`bbox.origin` 必须显式声明**。PDF 原生坐标系原点在左下，多数解析库输出左上，
   不声明必然上下颠倒。
4. 抽取的每一条都必须带 `quote` 原文摘录（`minLength: 4`），占位文本视为无效。

---

## 7. 使用约定

1. 产品卡 EvidenceRef 的 `source_id` 必须命中本表；未命中视为引用不闭合（INV-04）。
2. 材料入库后，`status` 由 `PENDING_SOURCE → AVAILABLE`，并记录 `bytes_sha256`；
   `_authoritative/` 区还需回填真实条款号后转 `CLAUSE_VERIFIED`。
3. 监管法规条目 `REG-*` 为对外口径引用，最终以现行有效版本为准；行内制度 `SRC-*`
   以对应 owner 部门发布的最新版本为准。
4. 网页类源必须同时归档快照至 `_authoritative/snapshots/` 或
   `_public_reference/snapshots/`，快照 + `bytes_sha256` 才构成可复现凭据。
5. 抽不到的字段填 `UNKNOWN`，禁止编造（INV-03 + AI 输出边界红线）。

---

## 8. 缺口台账（G0-6，6 族 × 制度类型矩阵）

> 本节即 Gate G0-6 的交付物。等待 Owner 上传。
> 台账先行建立，使 G0-1~G0-5 不被 Owner 上传阻塞（裁决要求的「并行」）。
> **L03 订正 2026-09-05**：原表述「当前全部为缺失状态」已过时——REG-CM-001 已入库。

图例：`—` 缺失待上传 · `○` 已入库未核定条款 · `●` 已入库且条款已核定

| 产品族 | 产品管理办法 | 业务操作规程 | 风险政策 | 监管法规 | 缺口数 |
|---|---|---|---|---|---|
| CASH_MANAGEMENT（pilot） | — SRC-CM-001 | — SRC-CM-002 | — SRC-CM-003 | ○ REG-CM-001 · — REG-CM-002 | 4 |
| SETTLEMENT | — SRC-SET-001 | — SRC-SET-002 | — 复用 SRC-XFAM-003 | — REG-SET-001 | 3 |
| TRADE_FINANCE | — SRC-TF-001 | — SRC-TF-002 | — SRC-TF-003 | — REG-TF-001/002 | 5 |
| CROSS_BORDER | — SRC-CB-001 | — SRC-CB-002 | — 复用 SRC-XFAM-003 | — REG-CB-001/002 | 4 |
| FINANCING | — SRC-FIN-001 | — SRC-FIN-003 | — SRC-FIN-005 | — REG-FIN-001/002 | 5 |
| INVESTMENT_BANKING | — SRC-IB-001 | — 复用 SRC-XFAM-003 | — 复用 SRC-XFAM-003 | — REG-IB-001 | 2 |
| 跨族通用 | — SRC-XFAM-001/002 | — | — SRC-XFAM-003 | — REG-XFAM-001 | 4 |

**汇总**：权威区登记源 **28** 条 = **27 `PENDING_SOURCE` + 1 `AVAILABLE`**（REG-CM-001，
已抽出 25 条款，`clauseVerified=false` 故记 `○` 而非 `●`），缺口 **27/28**，
`CLAUSE_VERIFIED` **0** 条。
公开参考区登记源 **2 条**，均已 `AVAILABLE`（PUB-PRICE-001 / PUB-PRICE-002）。

**DEMO 演示轨（Owner 决议 DECISION-20260906-01 路径 C）**：演示源 **3** 条（SRC-CM-001/002/003），
均为 `provenance_state: DEMO` 的**虚构文本**，**单列统计、不计入上列 28 条、不抵扣 27/28 真实缺口**，
F-L00-07 **仍未解除**。详见 §5.8。

> **L03 订正记录（F-L00-03）**：原汇总写「27 条全部 `PENDING_SOURCE`，缺口 27/27」，
> 与本表明细行 REG-CM-001 = `**AVAILABLE**` 直接冲突。
>
> **L03 追加订正（F-L03-02）**：进一步核算发现权威区明细行实为 **28** 条而非 27
> —— `REG-CM-002`（第 114 行，CASH_MANAGEMENT 族第二份监管法规）自 PI-0 起
> 从未被计入任何汇总，缺口台账 CASH_MANAGEMENT 行也漏列。故「27」这一数字
> 本身即为错误基数，现按明细行真值订正为 28。
>
> 本节数字由 `tools/check_registry_consistency.py` 自动校验，禁止手工维护脱节。

**风险 R-1 提示**：OQ-B 裁决 6 族全推进，需 Owner 上传的权威材料从单族 7 份增至
27 份，13 张产品卡 × 11 章 = 143 章节需逐项确认。缓解措施为 PI-1 G1-5 分族独立交付：
每族材料到位即可独立推进，不等 6 族全齐；CASH_MANAGEMENT 为 pilot 族，建议 Owner
优先上传该族剩余 **3** 份材料（SRC-CM-001/002/003），以便尽早跑通端到端样板。

**PUB-PRICE-002 入库记录（跨版式对照）**

| 项 | 值 |
|---|---|
| 文件字节数 | 285717 |
| bytes_sha256 | e84eaf2617308415663527ab871b99e4e6a49a159ed93b8c042e4e68acc01846 |
| 物理页数 | 7 |
| 版式 | 18 列稀疏矩阵 |
| 抽出条目 | 20 |
| 解析失败率 | 0% |
| 入库时间 | 2026-09-04 |
| 来源 URL | `UNVERIFIED`（未登记，见 F-L00-10） |
| 抓取方式 | `UNVERIFIED`（无抓取日志） |
| 抓取时点快照 | `UNVERIFIED`（无 WARC/截图） |
| 来源可复现性 | **CONFLICTING_EVIDENCE** — 文件与哈希真实存在，但无法证明其来自所声称的公开渠道 |

> **L03 订正（F-L00-04）**：原记字节数 `292840` 为笔误，实测 `285717`（`stat -c%s`），
> SHA-256 一致，文件本身无误。
> **L03 补录（F-L00-10）**：provenance 四项均无证据，一律标 `UNVERIFIED`，
> 不编造 URL 或时点。在 Owner 补充来源证明前，AT-PI0-004 不得升 PASS。

**REG-CM-001 入库记录（首份权威区监管法规）**

| 项 | 值 |
|---|---|
| 文件字节数 | 92460 |
| 物理页数 | 4 |
| 抽出条款 | 25 |
| bytes_sha256 | 105df242da87f50587208351c6abb07ddde2d689ab13e0d0619f420875290024 |
| 定位方式 | CLAUSE |
| usage | AUTHORITATIVE |
| authorityLevel | REGULATORY |
| clauseVerified | false（条款号待 Owner 核定） |
| 局限 | 国家法规非行内制度，给不出准入评级/前置产品等 HardRule，不能替代 SRC-CM-001~003 |

