# 试点产品资产包：FINANCING 流动资金融资

> 状态块：
> - **CANDIDATE**
> - **FROZEN=NO**
> - **IMPLEMENTED=NO**
>
> 本文档与同目录下全部资产均属 **WP2-1 交付物**，是 DKWS 五层工作区语义的**静态示例（样例）**，用于落地「1 个试点产品族 ≥3 个产品卡」的最小资产结构。**尚未通过 `dkws` CLI 链路正式落库**（Gate 0 限定项，见 §5），仅作结构与字段示范，不代表已进入生产推荐全集。

- 生成日期：2026-08-31
- 取证/依据：`skills/product-recommendation/product-cards/README.md`（产品卡最小结构）、`docs/governance/KERT_GATE0_EVIDENCE_PACK_CANDIDATE.md`（五层工作区机制与 Gate 0 限定项）、`src/dkws/domain/workspace.py`（`TOP_LEVEL_DIRS` 五层目录）。
- 试点产品族：**FINANCING（流动资金融资）**，共 **3 张产品卡**。
- 状态：全部产品卡 `status = CANDIDATE`、`version = 1.0.0-candidate`。

---

## 1. 资产结构（目录树）

```text
examples/product-recommendation-assets/
├── README.md                 # 本文件：结构 / 可追溯性 / 不可变版本语义
├── MANIFEST.md               # 五层语义映射 + 资产清单 + 内容哈希清单
├── 01_raw/                   # 层一：源文件引用（权威制度/监管材料的登记与条款定位）
│   ├── README.md
│   └── source-registry.md    # 权威源文件登记（含条款定位，材料待 Owner 上传）
├── 03_core/                  # 层三：权威产品卡（唯一权威源）
│   ├── README.md
│   └── financing/            # 产品族域 = financing（FINANCING）
│       ├── CURRENT.md        # 当前活动版本指针（试点为 CANDIDATE）
│       └── version=2026.08.31.1/   # 版本目录（不可变）
│           ├── RELEASE.md    # 发布清单（含资产 SHA-256）
│           └── product-cards/
│               ├── PROD-FIN-001.md   # 流动资金贷款
│               ├── PROD-FIN-002.md   # 应收账款质押融资
│               └── PROD-FIN-003.md   # 订单融资
└── 04_serve/                 # 层四：投影说明（实体/关系/规则/数据集/图谱）
    ├── README.md
    └── projection.md
```

五层工作区完整语义见 `MANIFEST.md`：本包落地 `01_raw → 03_core → 04_serve` 三层；`02_work`（工作/候选区）与 `90_control`（审核决定/门禁/血缘）属 `dkws` CLI 落库链路，本样例仅以 MANIFEST 表达、不在此物化。

---

## 2. 试点产品族与产品卡清单

| 产品ID | 名称 | 产品族 | 版本 | 状态 | 生效 | 失效 |
|---|---|---|---|---|---|---|
| PROD-FIN-001 | 流动资金贷款 | FINANCING | 1.0.0-candidate | CANDIDATE | 2026-09-01（拟） | 无（待退役） |
| PROD-FIN-002 | 应收账款质押融资 | FINANCING | 1.0.0-candidate | CANDIDATE | 2026-09-01（拟） | 无（待退役） |
| PROD-FIN-003 | 订单融资 | FINANCING | 1.0.0-candidate | CANDIDATE | 2026-09-01（拟） | 无（待退役） |

> 每张产品卡均包含产品卡最小结构（`product-cards/README.md`）全部必填字段：产品 ID/名称/产品族/版本/状态/生效失效时间、适用客户与场景、产品能力、准入条件、排除条件与禁止用途、前置与互斥（含替代/配套）产品、流程材料、价格边界、风险提示、销售边界、EvidenceRef（源文件与条款定位）、Owner/审核人/发布时间/内容哈希。

---

## 3. 可追溯性（每卡 → EvidenceRef）

- 每张产品卡的 `## EvidenceRef` 节给出一组 `EV-*` 引用，每条含 `source_id + source_title + clause（条款定位）`，指向 `01_raw/source-registry.md` 登记的权威制度/监管材料。
- 引用不闭合、材料未落库的，一律标注 `status: PENDING_SOURCE`（源材料待 Owner 上传），**不臆造条款内容与条款号**。
- 依据 `SP-15.md` 不变量 INV-04「CandidateReason → 至少一条 EvidenceRef」、INV-05「HardRule → 一个已批准 Owner + 一个权威来源」：本样例产品卡尚处 CANDIDATE，源材料与 Owner 裁决（OQ-02）未完成，故**不得进入生产推荐全集**。

---

## 4. 不可变版本语义

- 与 `product-cards/README.md`「不可变版本语义」及 `SP-15.md` INV-01 对齐：
  - `ProductVersion` **发布后不可变，只可退役**（`hasVersion`，INV-01）；
  - 有效版本判定由规则 `PRODUCT_VERSION_ACTIVE` 执行：`Active(ProductVersion)=false → 不得进入正式候选`；
  - 内容变更 = 新版本目录 `version=<新版本号>`，旧版本**不修改、不删除**，仅通过 `CURRENT.md` 指针切换或 `RETIRED`（退役）标记下线。
- 本样例三卡均为 `1.0.0-candidate`、`status = CANDIDATE`，尚未形成「已发布 ACTIVE 版本」，因此本包无历史版本可退役；版本目录 `version=2026.08.31.1` 为**候选示例**，待 `dkws` CLI 正式发布后才会产生真实的 `RELEASE.md` 清单哈希与 `CURRENT.md` 指针切换。

---

## 5. Gate 0 限定项声明（如实）

- **待 dkws CLI 链路正式落库（Gate 0 限定项）**：本包是静态目录+MANIFEST 的**结构示例**，未经过 `dkws init / publish` 链路，未生成 `.dkws_workspace` 标记、G3 门禁、审核决定（`90_control/decisions`）与 Kùzu 图谱投影；`RELEASE.md`/`CURRENT.md`/内容哈希为**人工按同构规则预填**，正式落库时由 CLI 重算覆盖。
- 权威材料（产品制度/监管条款）当前**未提供**（对应 `KERT_GATE0_EVIDENCE_PACK_CANDIDATE.md` §7.3 OQ-02「试点产品族清单与权威材料由公司金融产品 Owner 裁决」），故 `01_raw` 仅登记引用、条款号标「待核定」。
- 本包**不**创建真实 DKWS 工作区、不注册进 `registry()`、不新增执行器，仅新增样例文件。

---

## 6. 自检（含 Tech Lead 打回意见闭环）

- **本任务（WP2-1）自身唯一新增 = `examples/product-recommendation-assets/` 目录下文件**；交付前复核 `git status -s`，工作区仅剩 `?? examples/product-recommendation-assets/`。
- **打回意见闭环（如实记录）**：首轮验收时工作区含非本任务的改动——2 个被修改的跟踪文件（`evidence/jr1/DISPATCH_E2E_SKIP.md`、`skills/service-proposal/templates/ch07-product-recommendation.md`）与 6 个其他 WP 的未跟踪路径（`docs/governance/KERT_GATE0_EVIDENCE_PACK_CANDIDATE.md`、`docs/integration/DKWS_GITS_STATE_MAPPING_CANDIDATE.md`、`docs/skill-execute-api-contract-vNext.md`、`skills/product-recommendation/`、`src/dkws/application/product_recommendation/`、`tests/integration/test_product_recommendation_eligibility.py`）。已按 Tech Lead 打回意见处置：`git checkout --` 回滚 2 个跟踪文件（回滚前已备份至 `/tmp/kert-wp2-1-prerollback-*`）；6 个其他 WP 未跟踪路径以独立提交 `0fab866`（非 WP2-1）移出本任务范围。首轮 §6「未改动任何既有文件」自述与当时工作树事实不符，**已作废并更正为本条如实记录**。
- 内容哈希：产品卡 `content_hash` 采用「SHA-256(去除 front matter 中 `content_hash` 行后的完整文件字节)」，清单哈希采用「SHA-256(完整文件字节)」，规则见 `MANIFEST.md`，已用 `python3` 复算校验一致（3 卡 `content_hash` 与清单 `sha256` 全部匹配）。
