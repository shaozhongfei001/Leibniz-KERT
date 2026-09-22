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
| REG-XFAM-001 | 《商业银行服务价格管理办法》（原银监会/发改委 2014 年第 1 号令） | REGULATORY | 合规管理部 | **AVAILABLE** | 7 章 38 条已入库，条款号待 Owner 核定 | 全部 13 张（价格边界章节） |

**REG-XFAM-001 入库记录（跨族通用价格法规）**

| 项 | 值 |
|---|---|
| 文件字节数 | 14341 |
| bytes_sha256 | 300f1d6d68b475c37042e6782d7f882b8105dfca0121a4150879e19b9787d24b |
| 令号 | 2014年第1号（中国银监会、国家发展改革委） |
| 发布 / 施行 | 2014-02-14 / 2014-08-01 |
| 章节条款 | 7 章 38 条 |
| 定位方式 | CLAUSE |
| usage | AUTHORITATIVE |
| authorityLevel | REGULATORY |
| clauseVerified | false（条款号待 Owner 核定） |
| 来源 URL | https://www.gov.cn/gongbao/content/2014/content_2671530.htm |
| 来源承载 | 中国政府网《国务院公报》2014年第13号 |
| 抓取时间 | 2026-09-22（PC8 真实法规入库） |
| 抓取凭据 | `01_raw/_authoritative/snapshots/REG-XFAM-001.provenance.md` |
| 凭据强度局限 | **转写文本**，非原始 HTML 字节快照 ⇒ `bytes_sha256` 只保证入库文件自身完整性，**不主张**与站点字节一致（详见凭据文件 §2） |
| 版本时点 | 以 2014年第1号令为准；若被修订/替代/废止，须**显式登记版本差异并更换源文件**，禁止静默替换 |
| 未做 | 本行合规对「现行有效性 / 适用性」的确认；确认前用途限于工程链路与口径联调 |
| 废止 | 《商业银行服务价格管理暂行办法》（2003年第3号）已废止 |

### 5.2 CASH_MANAGEMENT 现金管理（pilot 族，3 卡）

| source_id | source_title | authority_level | owner | status | clause（待核定） | 被引用产品卡 |
|---|---|---|---|---|---|---|
| SRC-CM-001 | 《现金管理业务管理办法》（行内制度） | INTERNAL_POLICY | 交易银行部 | PENDING_SOURCE | 现金池准入、成员户要求、归集规则 | PROD-CM-001/002 |
| SRC-CM-002 | 《法人账户透支业务操作规程》（行内制度） | INTERNAL_POLICY | 交易银行部 | PENDING_SOURCE | 透支额度、期限、还款与风险控制 | PROD-CM-003 |
| SRC-CM-003 | 《集团客户资金集中管理风险政策》（行内制度） | INTERNAL_POLICY | 风险管理部 | PENDING_SOURCE | 集团授信联动、成员户风险隔离 | PROD-CM-001/002/003 |
| REG-CM-001 | 《现金管理暂行条例》（2011修订，国务院令第12号） | REGULATORY | 合规管理部 | **AVAILABLE** | 25条已抽取，待Owner核定后转CLAUSE_VERIFIED | PROD-CM-001/002/003 |
| REG-CM-002 | 《人民币银行结算账户管理办法》 | REGULATORY | 合规管理部 | **AVAILABLE** | 七章七十一条已入库（含 2020 年修订标注），条款号待 Owner 核定；**本法规唯一 source_id** | PROD-CM-001/002 |

**REG-CM-002 入库记录（本法规唯一 source_id；`REG-SET-001` 合并为别名）**

| 项 | 值 |
|---|---|
| 文件字节数 | 33182 |
| bytes_sha256 | 70856944765f2ae2192414d2714e1c42bd036ceedd83c80ef4ddbeefa98d1654 |
| 令号 | 中国人民银行令〔2003〕第 5 号 |
| 公布 / 施行 | 2003-04-10 / 2003-09-01 |
| 章节条款 | 七章七十一条 |
| 定位方式 | CLAUSE |
| usage | AUTHORITATIVE |
| authorityLevel | REGULATORY |
| clauseVerified | false（条款号待 Owner 核定） |
| 来源 URL | https://www.gov.cn/gongbao/content/2003/content_62368.htm |
| 抓取时间 | 2026-09-22（PC8 真实法规入库） |
| 抓取凭据 | `01_raw/_authoritative/snapshots/REG-CM-002.provenance.md` |
| **修订沿革（显式登记）** | 经《中国人民银行关于修改〈教育储蓄管理办法〉等规章的决定》（**中国人民银行令〔2020〕第 2 号**，2020-04-29 公布并施行）**删除第二十三条第一款第一项**；入库件为 2003 年公报原文，被删项**原位 ⚠ 标注**；**不自行拼装"修订后合并正文"**（无官方来源的合成文本禁止）。⚠ 该项自 2020-04-29 起失效，**条款级引用不得引用该项** |
| 合并登记 | 与 §5.3 `REG-SET-001` 为**同一部法规**（重复登记）。Owner 2026-09-22 裁定：保留 `REG-CM-002` 为唯一 `source_id`，`REG-SET-001` 记为别名（对齐 §5.6 既有先例，收敛由 PI-1 管道统一执行） |
| 凭据强度局限 | **转写文本**，非原始 HTML 字节快照 ⇒ `bytes_sha256` 只保证入库文件自身完整性 |
| 未完成 | 本次**未取得**人民银行发布的"修订后合并全文"官方版本；亦未确认是否存在 2020 年第 2 号令以外的其他修订 |
| 未做 | 本行合规对「现行有效性 / 适用性」的确认 |

### 5.3 SETTLEMENT 结算（2 卡）

| source_id | source_title | authority_level | owner | status | clause（待核定） | 被引用产品卡 |
|---|---|---|---|---|---|---|
| SRC-SET-001 | 《单位结算账户管理实施细则》（行内制度） | INTERNAL_POLICY | 交易银行部 | PENDING_SOURCE | 开户准入、材料清单、账户分类 | PROD-SET-001 |
| SRC-SET-002 | 《国内保理业务管理办法》（行内制度） | INTERNAL_POLICY | 交易银行部 | PENDING_SOURCE | 应收账款转让、确权、追索权约定 | PROD-SET-002 |
| REG-SET-001 | 《人民币银行结算账户管理办法》— **别名**，见 `REG-CM-002`（**同一部法规，不重复入库**；Owner 2026-09-22 裁定保留 `REG-CM-002`；**引用须用 `REG-CM-002`**，收敛由 PI-1 管道统一执行） | REGULATORY | 合规管理部 | PENDING_SOURCE | 单位银行结算账户开立与管理（见 `REG-CM-002`） | PROD-SET-001 |

### 5.4 TRADE_FINANCE 贸易金融（2 卡）

| source_id | source_title | authority_level | owner | status | clause（待核定） | 被引用产品卡 |
|---|---|---|---|---|---|---|
| SRC-TF-001 | 《银行承兑汇票业务管理办法》（行内制度） | INTERNAL_POLICY | 交易银行部 | PENDING_SOURCE | 承兑准入、保证金比例、期限 | PROD-TF-001 |
| SRC-TF-002 | 《国内信用证业务操作规程》（行内制度） | INTERNAL_POLICY | 交易银行部 | PENDING_SOURCE | 开证条件、单据审核、付款期限 | PROD-TF-002 |
| SRC-TF-003 | 《贸易背景真实性审查指引》（行内制度） | INTERNAL_POLICY | 风险管理部 | PENDING_SOURCE | 贸易背景核验、单据要求、虚假贸易防范 | PROD-TF-001/002 |
| REG-TF-001 | 《商业汇票承兑、贴现与再贴现管理办法》（中国人民银行 银保监会令〔2022〕第 4 号）⚠ **指名结果**：原登记「《票据法》及票据业务相关监管规定」未指名具体文件；本 source_id 现指名到本办法。**《票据法》（法律，上位法）不在本 file 覆盖范围，需另行登记（待 Owner 裁定）** | REGULATORY | 合规管理部 | **AVAILABLE** | 八章四十二条已入库，条款号待 Owner 核定 | PROD-TF-001 |

**REG-TF-001 入库记录（指名文件：2022 年第 4 号令）**

| 项 | 值 |
|---|---|
| 文件字节数 | 13440 |
| bytes_sha256 | 5aeaa4ae76deeac981ae385a0857dd07a5d80df0f1fb123ef575da895d0f7102 |
| 令号 | 中国人民银行 中国银行保险监督管理委员会令〔2022〕第 4 号 |
| 发布 / 施行 | 2022-11-11 / 2023-01-01（第二十四条自 2024-01-01 起实施） |
| 章节条款 | 八章四十二条 |
| 定位方式 | CLAUSE |
| usage | AUTHORITATIVE |
| authorityLevel | REGULATORY |
| clauseVerified | false（条款号待 Owner 核定） |
| 来源 URL | https://www.gov.cn/zhengce/zhengceku/2022-11/18/content_5727779.htm |
| 抓取时间 | 2026-09-22（PC8 真实法规入库） |
| 抓取凭据 | `01_raw/_authoritative/snapshots/REG-TF-001.provenance.md` |
| 废止关系 | 《商业汇票承兑、贴现与再贴现管理暂行办法》（银发〔1997〕216 号）、《中国人民银行关于切实加强商业汇票承兑贴现和再贴现业务管理的通知》（银发〔2001〕236 号）同时废止 |
| 指名未覆盖（显式） | 《中华人民共和国票据法》为法律（上位法），**不在本 source_id 覆盖范围**（本办法第一条仅列为制定依据）⇒ 若需引用《票据法》条文须另行登记 source_id（待 Owner 裁定，不擅自新增行） |
| 凭据强度局限 | **转写文本**，非原始 HTML 字节快照 ⇒ `bytes_sha256` 只保证入库文件自身完整性 |
| 未完成 | 未取得人民银行 PDF 原版核对字形标点；未确认是否存在后续修订 |
| 未做 | 本行合规对「现行有效性 / 适用性」的确认 |
| REG-TF-002 | 《国内信用证结算办法》（人民银行 银监会**公告〔2016〕第 10 号**）⚠ **版本变更**：原登记未注版本（实为 1997 年银发〔1997〕265 号文本）**已被废止** | REGULATORY | 合规管理部 | **AVAILABLE** | 5 章 60 条已入库，条款号待 Owner 核定 | PROD-TF-002 |

**REG-TF-002 入库记录（现行版；原登记 1997 年版已废止）**

| 项 | 值 |
|---|---|
| 文件字节数 | 29688 |
| bytes_sha256 | 617e9640e125d100a26f3a4778f37e0ea343ef18ddd81d8e99bb8b6610b4a872 |
| 公告号 | 中国人民银行 中国银行业监督管理委员会公告〔2016〕第 10 号 |
| 签发 / 施行 | 2016-04-27 / 2016-10-08 |
| 章节条款 | 5 章 60 条 |
| 定位方式 | CLAUSE |
| usage | AUTHORITATIVE |
| authorityLevel | REGULATORY |
| clauseVerified | false（条款号待 Owner 核定） |
| 来源 URL | https://www.gov.cn/gongbao/content/2016/content_5100055.htm |
| 抓取时间 | 2026-09-22（PC8 真实法规入库） |
| 抓取凭据 | `01_raw/_authoritative/snapshots/REG-TF-002.provenance.md` |
| **版本差异（显式登记）** | 登记表原载文本对应 **1997 年**（银发〔1997〕265 号印发），**已被 2016 年第 10 号公告废止**；本源入库**现行版**，原版本作为沿革记录保留 |
| **首次抓取失败记录** | 首次抓取同一 URL 返回**结构化摘要**（非逐字条文）⇒ 按纪律**未入库**；以"逐字抄录"约束重取后取得 60 条完整文本入库（防后人以摘要充当原文） |
| 凭据强度局限 | **转写文本**，非原始 HTML 字节快照 ⇒ `bytes_sha256` 只保证入库文件自身完整性 |
| 未完成 | 未取得人行 PDF 原版核对字形标点；未确认是否有后续修订 |
| 未做 | 本行合规对「现行有效性 / 适用性」的确认 |

| REG-TF-003 | 《中华人民共和国票据法》（1995 通过 / 2004 修正；**法律·上位法**）— **新增行（D-R1，Owner 2026-09-22 同意）** | REGULATORY | 合规管理部 | **AVAILABLE** | 七章一百一十条已入库，条款号待 Owner 核定 | PROD-TF-001 |

**REG-TF-003 入库记录（新增行；《票据法》为上位法）**

| 项 | 值 |
|---|---|
| 文件字节数 | 29338 |
| bytes_sha256 | fd3ba439c11d5c65d7aece2943cc37a814c431fb067fd5f41f14b65318d364b8 |
| 制定机关 | 全国人民代表大会常务委员会 |
| 通过 / 修正 | 1995-05-10 通过；根据 2004-08-28 修正决定修正 |
| 施行日期 | 1996-01-01 |
| 章节条款 | 七章一百一十条 |
| 定位方式 | CLAUSE |
| usage | AUTHORITATIVE |
| authorityLevel | REGULATORY（法律，本枚举最高级） |
| clauseVerified | false（条款号待 Owner 核定） |
| 来源 URL | http://www.npc.gov.cn/zgrdw/npc/xinwen/lfgz/zxfl/2004-08/30/content_332314.htm |
| 抓取时间 | 2026-09-22（PC8 真实法规入库） |
| 抓取凭据 | `01_raw/_authoritative/snapshots/REG-TF-003.provenance.md` |
| **新增理由（D-R1）** | `REG-TF-001` 已指名到《商业汇票承兑、贴现与再贴现管理办法》（令〔2022〕第4号），而《票据法》为**法律（上位法）**、不在其覆盖范围 ⇒ **新增本行**（基数 27 → **28**，同步门禁期望值与汇总口径，显式登记未静默改） |
| 抓取纠错留痕 | TL 提问时误述"共 111 条"；官方页面核对为**最后一条为第一百一十条**（不存在第一百一十一条）⇒ 以官方为准，已在凭据文件 §3 留痕 |
| 凭据强度局限 | **转写文本**，非原始 HTML 字节快照 ⇒ `bytes_sha256` 只保证入库文件自身完整性 |
| 未完成 | 未取得全国人大官方 PDF 原版核对；未确认 2004 年修正之后是否另有修改 |
| 未做 | 本行合规对「现行有效性 / 适用性」的确认 |

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
| REG-FIN-001 | 《流动资金贷款管理办法》（国家金融监督管理总局令 2024 年第 2 号）⚠ **版本变更**：原登记的《暂行办法》（银监会令〔2010〕第 1 号）**已被替代** | REGULATORY | 合规管理部 | **AVAILABLE** | 8 章 51 条 + 附件已入库，条款号待 Owner 核定 | PROD-FIN-001/003 |

**REG-FIN-001 入库记录（现行版；原登记标题已废止）**

| 项 | 值 |
|---|---|
| 文件字节数 | 21864 |
| bytes_sha256 | dfa2dbff3746a7e20462178268e62bcb7626ba009a32389193afd3cd9bb4fdc5 |
| 令号 | 国家金融监督管理总局令 2024 年第 2 号 |
| 公布 / 施行 | 2024-01-30 / 2024-07-01 |
| 章节条款 | 8 章 51 条 + 附件（流动资金贷款需求量测算示例） |
| 定位方式 | CLAUSE |
| usage | AUTHORITATIVE |
| authorityLevel | REGULATORY |
| clauseVerified | false（条款号待 Owner 核定） |
| 来源 URL | https://www.gov.cn/gongbao/2024/issue_11306/202404/content_6947721.html |
| 抓取时间 | 2026-09-22（PC8 真实法规入库） |
| 抓取凭据 | `01_raw/_authoritative/snapshots/REG-FIN-001.provenance.md` |
| **版本差异（显式登记）** | 登记表原载《流动资金贷款管理暂行办法》（2010 年第 1 号）**已被办法第五十一条同时废止**；本源入库**现行版**，原标题保留为沿革记录，**禁止静默替换** |
| 凭据强度局限 | **转写文本**，非原始 HTML 字节快照 ⇒ `bytes_sha256` 只保证入库文件自身完整性 |
| 未做 | 本行合规对「现行有效性/适用性」的确认（含内部细则是否已按 2024 年办法更新） |
| REG-FIN-002 | 《商业银行互联网贷款管理暂行办法》（如涉及线上化） | REGULATORY | 合规管理部 | PENDING_SOURCE | 线上放款/自主支付额度上限 | PROD-FIN-001（如线上化） |

### 5.7 INVESTMENT_BANKING 投资银行（1 卡）

| source_id | source_title | authority_level | owner | status | clause（待核定） | 被引用产品卡 |
|---|---|---|---|---|---|---|
| SRC-IB-001 | 《并购贷款业务管理办法》（行内制度） | INTERNAL_POLICY | 投资银行部 | PENDING_SOURCE | 并购主体资质、贷款比例上限、期限 | PROD-IB-001 |
| REG-IB-001 | 《商业银行并购贷款管理办法》（金规〔2025〕27 号）⚠ **版本变更**：原登记的《风险管理指引》（银监发〔2015〕5 号）**已被废止**，文种由「指引」升格为「管理办法」 | REGULATORY | 合规管理部 | **AVAILABLE** | 通知 + 正文 34 条已入库，条款号待 Owner 核定 | PROD-IB-001 |

**REG-IB-001 入库记录（现行版；原登记标题已废止）**

| 项 | 值 |
|---|---|
| 文件字节数 | 16042 |
| bytes_sha256 | c9f87041941540d6c65794e3f812b9255cb852e793159f070eba0fec96cf61e5 |
| 文号 | 金规〔2025〕27 号（通知） |
| 成文 / 施行 | 2025-12-31 / 自印发之日起施行 |
| 正文条款 | 34 条 |
| 定位方式 | CLAUSE |
| usage | AUTHORITATIVE |
| authorityLevel | REGULATORY |
| clauseVerified | false（条款号待 Owner 核定） |
| 来源 URL | https://www.gov.cn/zhengce/zhengceku/202601/content_7053613.htm |
| 抓取时间 | 2026-09-22（PC8 真实法规入库） |
| 抓取凭据 | `01_raw/_authoritative/snapshots/REG-IB-001.provenance.md` |
| **版本差异（显式登记）** | 登记表原载《商业银行并购贷款风险管理指引》（银监发〔2015〕5 号）**已被本办法第三十四条同时废止**；本源入库**现行版**，原标题保留为沿革记录，**禁止静默替换** |
| 凭据强度局限 | **转写文本**，非原始 HTML 字节快照 ⇒ `bytes_sha256` 只保证入库文件自身完整性 |
| 未做 | 本行合规对「现行有效性/适用性」的确认（含业务开办资格与内部细则） |

---

## 5.8 DEMO 演示轨登记（`_authoritative/` · `provenance_state: DEMO`）

> Owner 决议 **DECISION-20260906-01（演示路径 C）**：批准生成演示制度文本，明确标记为 DEMO 而非真实制度。
>
> **红线（L10 落地）**：
> 1. 本节 6 条**均为虚构演示文本**，不代表任何真实机构制度；
> 2. DEMO 源**不计入** §5 真实权威区基数（28），**不抵扣** 20/28 真实缺口 —— **F-L00-07 未解除**；
> 3. 依 DEMO 源编译的 Release 必须带 `provenance_state=DEMO`，**不得**进入 `RECOMMENDATION_READY`（INV-EVS-09/10/11）；
> 4. DEMO 证据**不得与** VERIFIED 证据混合支撑同一字段断言，禁止用演示材料补真实材料缺口。

| source_id | source_title | authority_level | provenance_state | status | 物理文件 | 被引用产品卡 |
|---|---|---|---|---|---|---|
| SRC-CM-001 | 《现金管理业务管理办法（演示文本）》 | INTERNAL_POLICY | DEMO | **AVAILABLE (DEMO)** | `01_raw/_authoritative/SRC-CM-001.DEMO.md` | 无（禁止沿用 13 张 legacy card） |
| SRC-CM-002 | 《法人账户透支业务操作规程（演示文本）》 | INTERNAL_POLICY | DEMO | **AVAILABLE (DEMO)** | `01_raw/_authoritative/SRC-CM-002.DEMO.md` | 无 |
| SRC-CM-003 | 《集团客户资金集中管理风险政策（演示文本）》 | INTERNAL_POLICY | DEMO | **AVAILABLE (DEMO)** | `01_raw/_authoritative/SRC-CM-003.DEMO.md` | 无 |
| SRC-XFAM-001 | 《对公客户准入与评级管理办法（演示文本）》 | INTERNAL_POLICY | DEMO | **AVAILABLE (DEMO)** | `01_raw/_authoritative/SRC-XFAM-001.DEMO.md` | 无 |
| SRC-XFAM-002 | 《产品定价管理办法（演示文本）》 | INTERNAL_POLICY | DEMO | **AVAILABLE (DEMO)** | `01_raw/_authoritative/SRC-XFAM-002.DEMO.md` | 无 |
| SRC-XFAM-003 | 《对公业务销售适当性管理办法（演示文本）》 | INTERNAL_POLICY | DEMO | **AVAILABLE (DEMO)** | `01_raw/_authoritative/SRC-XFAM-003.DEMO.md` | 无 |

**物理隔离约定**：真实行内制度上传时落 `SRC-CM-001.pdf` / `SRC-CM-001.md`；演示文本固定带
`.DEMO.md` 后缀。§5.2 中 `SRC-CM-001/002/003` 三行**仍记 `PENDING_SOURCE`** —— 真实行内制度尚未上传，
演示文本不替代 Owner 上传义务。

**DEMO 源入库记录**

| source_id | 文件字节数 | bytes_sha256 | 条款数 | 入库时间 | 定位方式 |
|---|---|---|---|---|---|
| SRC-CM-001 | 4280 | `5879e81430538f75091805f2f3a2db23bd2cd98bbbb32f731c575221d058093f` | 19 | 2026-09-06 | CLAUSE（章条号） |
| SRC-CM-002 | 3509 | `984fe6cde0c2b17bfad0b1c05d0a6f80ae7701647c8155b85b3ec57c92f375a2` | 17 | 2026-09-06 | CLAUSE（章条号） |
| SRC-CM-003 | 3422 | `b4599dd141caa7d1934cd69de58fdc8245e6d631d0bec33477593b88e341fe29` | 15 | 2026-09-06 | CLAUSE（章条号） |
| SRC-XFAM-001 | 4404 | `ae7e77d22770d0ea6712827bc04a2b7f9cc1fc1378ee2c06562c70f137917c23` | 待抽取 | 2026-09-22 | CLAUSE（章条号） |
| SRC-XFAM-002 | 3971 | `2f0760ccf0c600289947be4d7002ffbb0b6c6fdc566ce8753a3901774ba7337f` | 待抽取 | 2026-09-22 | CLAUSE（章条号） |
| SRC-XFAM-003 | 3822 | `4713b5e305a4deb802ca2619932635fd5f3c44400c5ccad991bca37f0bf910c6` | 待抽取 | 2026-09-22 | CLAUSE（章条号） |

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
| CASH_MANAGEMENT（pilot） | — SRC-CM-001 | — SRC-CM-002 | — SRC-CM-003 | ○ REG-CM-001 · ○ REG-CM-002 | 3 |
| SETTLEMENT | — SRC-SET-001 | — SRC-SET-002 | — 复用 SRC-XFAM-003 | → REG-CM-002（别名） | 2 |
| TRADE_FINANCE | — SRC-TF-001 | — SRC-TF-002 | — SRC-TF-003 | ○ REG-TF-001 · ○ REG-TF-002 · ○ REG-TF-003 | 3 |
| CROSS_BORDER | — SRC-CB-001 | — SRC-CB-002 | — 复用 SRC-XFAM-003 | — REG-CB-001/002 | 4 |
| FINANCING | — SRC-FIN-001 | — SRC-FIN-003 | — SRC-FIN-005 | ○ REG-FIN-001 · — REG-FIN-002 | 4 |
| INVESTMENT_BANKING | — SRC-IB-001 | — 复用 SRC-XFAM-003 | — 复用 SRC-XFAM-003 | ○ REG-IB-001 | 1 |
| 跨族通用 | — SRC-XFAM-001/002 | — | — SRC-XFAM-003 | ○ REG-XFAM-001 | 3 |

**汇总**：权威区登记源 **28** 条 = **20 `PENDING_SOURCE` + 8 `AVAILABLE`**（REG-CM-001、REG-XFAM-001、REG-FIN-001、REG-IB-001、REG-CM-002、REG-TF-001、REG-TF-002、REG-TF-003，
八份均已入库且条款文本完整，均 `clauseVerified=false` 故记 `○` 而非 `●`），缺口 **20/28**，
（⚠ **计数口径（机器可复核）**：明细行中**含「别名」/「复用」字样者不计入基数**（与 `tools/check_registry_consistency.py` 解析行为一致，对齐 §5.6 `SRC-FIN-002/004` 先例）⇒ 原 28 条基数扣 `REG-SET-001`（别名）后为 **27** 条。此前本件一度写作「仍计入 28 条」，与解析器实际行为不符，**已更正**。）
`CLAUSE_VERIFIED` **0** 条。
公开参考区登记源 **2 条**，均已 `AVAILABLE`（PUB-PRICE-001 / PUB-PRICE-002）。

**DEMO 演示轨（Owner 决议 DECISION-20260906-01 路径 C）**：演示源 **6** 条（SRC-CM-001/002/003、SRC-XFAM-001/002/003），
均为 `provenance_state: DEMO` 的**虚构文本**，**单列统计、不计入上列 28 条、不抵扣 27/28 真实缺口**，
F-L00-07 **仍未解除**。详见 §5.8。

> **PC8 造数批次 B1（2026-09-22）**：新增 `SRC-XFAM-001/002/003` 三份**跨族通用**演示源
> （准入与评级 / 产品定价 / 销售适当性），覆盖**全部 13 张产品卡**；三者均为 `provenance_state: DEMO`，
> **不计入**上列 28 条、**不抵扣**真实缺口。`条款数/片段数` 列记「待抽取」——
> **不得**手写 pipeline 产物（`02_work/source-versions/*`、`04_serve/releases/*` 必须由流水线生成）。

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

---

## 9. PC8 REG 取证裁定登记（2026-09-22 · TL）

> 本节只记**裁定结论与阻塞原因**（散文体），**不新增明细行**（明细行会改变机器可复核的基数）。
> 完整台账另见 gits 侧 `docs/dispatch/PC8-REG监管法规取证与裁定台账-V1.0.md`。

- **REG-FIN-002**（《商业银行互联网贷款管理暂行办法》，银保监会令 2020 年第 9 号，现行有效）：
  按 Owner 2026-09-22 裁定（`D-R2`，同意 TL 建议）**暂判「不适用」** —— 本场景产品清单
  （流动资金贷款 / 订单融资 / 供应链）**未取得"涉及线上化放款渠道"的确认证据**，
  适用性属**业务口径**，非 TL 可单方认定。**行保留、状态仍记 `PENDING_SOURCE`**；
  若业务/渠道确认涉及线上化，须**重新评估并入库**（不得以"不适用"长期悬置而不复核）。
- **REG-CB-001**（原登记"跨境人民币结算相关监管规定"，**未指名**）：检索所得的 2025-11-14
  六部门文件实为**公告〔2025〕第 30 号（废止 3 件规范性文件）**，**属废止公告、不承载**
  登记所载"展业三原则与合规要求"语义 ⇒ **不予指名**（不把废止公告当监管规定用）。
  需继续检索承载该语义的现行规范性文件后再指名。
- **REG-CB-002**（《跨境担保外汇管理规定》，汇发〔2014〕29 号，未发现废止）：条文在官方
  **`.doc` 附件**内，本次直取返回**二进制、无法解析** ⇒ 本轮**未入库**（不以通知冒充条文、
  不自行拼装）；须另寻官方逐字承载或取得可解析原版后入库。
- **待新增（`D-R1`，Owner 已同意）**：《中华人民共和国票据法》（法律，上位法）将挂
  **`REG-TF-003`**，入库时基数 27 → **28** 并同步门禁期望值与汇总口径（**显式登记，不静默改**）。
