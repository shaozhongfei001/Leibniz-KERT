# MANIFEST：试点产品资产包（FINANCING 流动资金融资）

> 状态块：
> - **CANDIDATE**
> - **FROZEN=NO**
> - **IMPLEMENTED=NO**

## 1. 五层工作区语义映射

依据 `src/dkws/domain/workspace.py` `TOP_LEVEL_DIRS = ("01_raw","02_work","03_core","04_serve","90_control")`，本包落地其中三层，其余两层由 `dkws` CLI 落库链路负责（Gate 0 限定项）。

| 层 | 目录 | 语义 | 本包落地 |
|---|---|---|---|
| 01_raw | `01_raw/` | 源文件引用（权威制度/监管材料登记与条款定位） | ✅ `source-registry.md`（材料待 Owner 上传） |
| 02_work | （未物化） | 工作/候选区（候选资产、审核流转） | ❌ 属 CLI 落库链路，本包不物化 |
| 03_core | `03_core/` | 权威产品卡（唯一权威源，版本目录不可变） | ✅ `financing/version=2026.08.31.1/product-cards/*.md` |
| 04_serve | `04_serve/` | 投影说明（实体/关系/规则/数据集/图谱） | ✅ `projection.md`（仅投影规格说明） |
| 90_control | （未物化） | 审核决定/门禁/血缘/质量 | ❌ 属 CLI 落库链路，本包不物化 |

> **待 dkws CLI 链路正式落库（Gate 0 限定项）**：上表 `❌` 项由 `dkws init / publish` 生成；本包为静态样例，仅以目录 + 本 MANIFEST 表达五层语义，未生成 `.dkws_workspace` 标记、审核决定与图谱投影。

## 2. 资产清单与内容哈希

哈希规则：
- **内容哈希（content_hash）**：`SHA-256(去除该文件 front matter 中 `content_hash` 行后的完整文件字节)`，用于产品卡自身的可追溯校验；
- **清单哈希（sha256）**：`SHA-256(完整文件字节)`，用于 RELEASE 清单与本文档的完整性校验。

### 2.1 产品卡（03_core）

| 资产ID | 路径 | 版本 | 状态 | content_hash | 清单 sha256 |
|---|---|---|---|---|---|
| PROD-FIN-001 | `03_core/financing/version=2026.08.31.1/product-cards/PROD-FIN-001.md` | 1.0.0-candidate | CANDIDATE | sha256:e9738c56547c94dd7c797dc57e14c63082bc1f07f241a3780ef3c9bbcf6fecca | 64d98edecd7708c1b01d3fdd0ca0188055a21556b9d1e942b96f60f29e6d94bb |
| PROD-FIN-002 | `03_core/financing/version=2026.08.31.1/product-cards/PROD-FIN-002.md` | 1.0.0-candidate | CANDIDATE | sha256:27a46c30f430764d2d0bea1c62541b35009189e4226270ca89501523092865f0 | be991644bd6df7dfe8e1acc21247a1c4cc1a9f678c2ff5859ccd040ef182f518 |
| PROD-FIN-003 | `03_core/financing/version=2026.08.31.1/product-cards/PROD-FIN-003.md` | 1.0.0-candidate | CANDIDATE | sha256:f24d57c847ad25bb5f45512de0455c3df12354292232ed766293165ccd451942 | 196f57a66ffba586f510f7eb6844003117c90a39a1bd4ba09a3952929d50bd73 |

### 2.2 源文件引用（01_raw）

| 源ID | 路径 | 类型 | 状态 |
|---|---|---|---|
| SRC-FIN-001 | `01_raw/source-registry.md`（登记条目） | 行内制度 | 待上传 |
| SRC-FIN-002 | 同上 | 行内制度 | 待上传 |
| SRC-FIN-003 | 同上 | 行内制度 | 待上传 |
| SRC-FIN-004 | 同上 | 行内制度 | 待上传 |
| SRC-FIN-005 | 同上 | 行内制度 | 待上传 |
| REG-FIN-001 | 同上 | 监管法规 | 待对齐 |
| REG-FIN-002 | 同上 | 监管法规 | 待对齐 |

## 3. 发布记录与当前指针（候选示例）

- `03_core/financing/version=2026.08.31.1/RELEASE.md`：候选发布清单（`status=CANDIDATE`，非 CLI 正式 PUBLISHED）。
- `03_core/financing/CURRENT.md`：候选当前版本指针（`status=CANDIDATE`，指向 `2026.08.31.1`；正式发布后由 CLI 原子切换并保留旧指针）。

## 4. 状态

- 全部资产：`CANDIDATE / FROZEN=NO / IMPLEMENTED=NO`。
- 未落地项（如实）：源材料未上传、条款号待 Owner 核定、`dkws` CLI 未落库、无审核决定与图谱投影。
