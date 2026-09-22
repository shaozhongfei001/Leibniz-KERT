# `_sim/` 造数区（SIMULATED）

> 状态块：
> - **CANDIDATE**
> - **FROZEN=NO**
> - **IMPLEMENTED=NO** —— ⚠ **本区当前不可被引用**，见「前提（未满足）」
> - 建立：TL 2026-09-22，依据 Owner 2026-09-22「按 L-A 落造数区」（`OD-PI-13` / `PC8`）

## 用途

存放**由 TL 派工智能体提前构造**的模拟原始产品文档（SIM 造数），用于在真实行内制度材料
（`_authoritative/`）到位之前，打通「**原始文档 → 结构化 → LightRAG 检索 → 产品解读**」全链路
（`PC8`）。

**本区文件不是权威材料，也不是公开资料**，是**为打通链路而构造的模拟件**。

## 与既有双区的关系（三区语义）

`01_raw/` 的区归属决定证据能力上限（`source-registry.md` §1）。`_sim/` 为**第三区**：

| 区 | `usage` | 证据能力上限 | 能否支撑产品卡转 `ACTIVE` |
|---|---|---|---|
| `_authoritative/` | `AUTHORITATIVE` | 产品卡字段唯一合法 EvidenceRef 来源 | ✅ 可（需 `CLAUSE_VERIFIED`） |
| `_public_reference/` | `VERIFICATION_ONLY` | 仅验证解析器能力，不作权威依据 | ❌ 永久 `CANDIDATE` |
| **`_sim/`（本区）** | **`SIMULATED`**（拟） | **仅供链路联调与演示**；不作任何字段的权威依据 | ❌ **永久 `CANDIDATE`**（拟） |

## ⚠ 前提（未满足 —— 必须写清，防止误以为已可用）

`specs/product-knowledge/evidence-ref.schema.json` 的 `sourcePath` **机器强制前缀当前只有两个**
（`^01_raw/(_authoritative|_public_reference)/`）⇒ **落在本区的文件，其 EvidenceRef 会被 schema 直接拒绝**。

本区生效的前提是变更申请 **`CR-1`/`CR-2`/`CR-3`** 获批（见
`gits-cbanking:docs/dispatch/PI-DESIGN-CONFIRM-LightRAG与单一文档源-V1.2.md` §3）：

1. `CR-1`：`sourcePath` 前缀增 `_sim`；`usage` 枚举增 `SIMULATED`；门禁「引用 `SIMULATED` ⇒ 永久 `CANDIDATE`」；
2. `CR-2`：PI-1 G1-5 门禁代码的 path↔usage 一致性映射同步；
3. `CR-3`：`source-registry.md` §1 由双区改三区并登记本区。

**在 `CR-1` 获批前**：本区文件可撰写与评审，**不得**被任何产品卡 `EvidenceRef` 引用，
**不得**进入 `03_core` HardRule 字段。

## 命名与登记约定

- 命名沿用 `<source_id>.SIM.md`（与既有 `_authoritative/SRC-CM-00X.DEMO.md` 的「`source_id` + 来源级别后缀」惯例一致）；
  例：`SRC-CM-003.SIM.md`。
- `source_id` 由 `source-registry.md` 分配，`sourcePath` 形如 `01_raw/_sim/SRC-CM-003.SIM.md`。
- **每份 SIM 文档必须在 front matter 声明**：`usage: SIMULATED`、`simulationOnly: true`、
  `isDemo: true`、`evidenceClass: SAMPLE_EVIDENCE`，并在正文顶部保留**可见警示块**。
- 入库后回填 `sourceContentHash`（`sha256:` 前缀，Markdown 源适用）。
- 模板见 `_TEMPLATE.SIM.md`。

## 纪律（硬约束，不得放宽）

1. **不得冒充权威**：正文与元数据都必须可机器识别为 SIM；不得省略警示块。
2. **不得写入受控面**：造数**绝不**写入 `03_core` 的 taxonomy、`CONTRACTS_INDEX`、
   产品卡 HardRule 字段，也不得改变 `02_work`/`04_serve` 既有产物的语义。
3. **不得作对客依据**：SIM 来源的解读**不得对客引用**；对客口径以受控解读与批复协议为准。
4. **演示用需确认**：SIM 造数内容用于演示前，须经**产品 Owner + 合规**确认（`S-1`/SIM-4），
   工程不得单方定稿。
5. **不扩张出口**：本区文件是否为 LightRAG 索引内容，取决于 `CR-4` 裁决
   （默认**不动** `EGRESS_ROOTS`，索引内容来自 `03_core`/`04_serve` 产物）。

## 当前状态

- **已落**：本 README + `_TEMPLATE.SIM.md`（骨架）
- **未落**：SIM 造数正文（待 `CR-1` 获批；否则造了也引用不了）
- **未改**：`01_raw/` 既有任何文件（`_authoritative/`、`_public_reference/`、`source-registry.md` 全部未动）
