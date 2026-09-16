# 证据：D-31 本体侧 —— 真解析 OWL/SHACL 并物化（可跑 + 测试）

> Owner 2026-09-16 **推翻** D3-A（"KERT 不内置本体"）⇒ 本片**真解析** gits 本体并物化。
> 本文件只记口径、统计、命令与原始退出码（设计理由写在源码 docstring）。

**行号基准（D-8）**：本文件不引用既有文件行号；新增模块以**符号名**为准。
**环境（E-11）**：`.venv/bin/python` → Python 3.12.8；pytest 9.1.1；**新增** rdflib 7.6.0、pyshacl 0.40.1（传递：owlrl 7.6.2、prettytable 3.18.0、pyparsing 3.3.2、html5rdf 1.2.1、wcwidth 0.8.3）。

## 1. 依赖（最小集合）

- `pyproject.toml`：`dependencies` 追加 **`rdflib>=7.6`**、**`pyshacl>=0.40`**（各附理由注释）。
- **刻意不引入** `owlready2` / 推理机：当前需求是"可解析 / 可统计 / 可物化"，不是"可推理"；将来确需推理再按最小化原则追加并留痕。
- `requirements-lock.txt`：**定点插入** 7 行本体栈（**不重排既有行**，`+12/-0`，含 5 行说明）；
  本机 venv 里的 `coverage` / `pytest-cov`（dev 工具，未在 pyproject 声明）与陈旧 dist 名 `dkws` **均未并入**。

## 2. 内置本体（含 provenance）与漂移检测

- 落点：`examples/bank-front-knowledge-maps/90_control/ontology/`（受控源；运行时由
  `ensure_assets(ws, source=…)` **显式引入**到 `<ws>/90_control/ontology/`）。
- 4 件 gits 资产（**只读副本**）：

| 角色 | 文件 | gits 来源（仓内路径） | sha256(前16) |
|---|---|---|---|
| OWL | `gits-core.owl.ttl` | `specs/semantic/gits-core.owl.ttl` | `705578d6324abd0c…` |
| SHACL | `gits-core.shacl.ttl` | `generated/semantic/gits-core.shacl.ttl` | `53a3fba39a00aa20…` |
| INSTANCES | `products.ttl` | `specs/knowledge-architecture/instances/product/products.ttl` | `e70bbe45bebcca2e…` |
| R2RML | `customer-source-mapping.r2rml.ttl` | `specs/data/customer-source-mapping.r2rml.ttl` | `f873a85266b45c9e…` |

- **关键一致性（实测）**：内置 OWL 的 sha256 **逐字等于**控制面声明钉值
  `90_control/schema/ontology_reference.json` 的 `contentSha256`（`705578d6…8d00`），
  `contractId=CTR-SEM-002`、`version=CTR-SEM-002@sha256:705578d6324abd0c` ⇒ 声明所指就是这件本体。
- **漂移检测**：`ontology_assets.load_assets[_from_dir]` 逐件比对 provenance 记录的 `contentSha256`；
  不符 ⇒ **具名拒绝** `ONTOLOGY_ASSET_DRIFT`（含文件名 + 期望/实际）；provenance 结构非法 ⇒
  `ONTOLOGY_ASSETS_PROVENANCE_INVALID`；缺文件 ⇒ `ONTOLOGY_ASSETS_ABSENT`。
  `drift_against_source(assets, source_root)` 供人类/QA **显式**对 gits 源比对（运行期不读跨仓）。

## 3. 真解析统计（rdflib + pyshacl，来自真实图遍历）

```text
classes=32   objectProperties=34   datatypeProperties=1
shapes(NodeShape)=32   shapeProperties(sh:property 行)=169   subclassEdges=7   triples=255
SHACL 对 instances(products.ttl) 校验：conforms=True   violations=0     （pyshacl，inference=rdfs）
```

## 4. 物化产物（`04_serve/<svc>/version=<v>/`，与既有投影同形）

```text
ontology_classes.parquet  32 行      ontology_properties.parquet  35 行（34 对象 + 1 数据）
ontology_shapes.parquet  169 行      ONTOLOGY.md（统计 + provenance 表 + 查询示例）
ontology_graph/（Kùzu 单文件）        ontology_graph.PROJECTION.json（builder/指纹）
ONTOLOGY_LINEAGE.json（血缘；`ontology` 子块 = 既有 5 键：contractId/authorityRepo/authoritySource/contentSha256/version）
⇒ 图规模：节点 99（类 32 + 属性 35 + shape 32），边 100（SUBCLASS_OF / DOMAIN / RANGE / TARGETS / SHAPE_PROPERTY）
```

- **校验先于产出**：资产漂移 / 与声明钉值不符 / 与**同版本目录既有 `PLAN_LINEAGE.json`** 的本体块不符
  ⇒ 抛具名错误且**不写任何产物**（实测：拒绝后目标 version 目录不存在）。
- 血缘 `ontology` 子块可被既有 `check_lineage_ontology(res, fm)` 放行（实测 `OK`）⇒ 与 B-1/B-2② 口径**同源**。

## 5. 测试与原始退出码

```text
新增：tests/unit/test_ontology_assets_and_parse.py（4 用例）
      tests/integration/test_ontology_materialization.py（3 用例）
  .venv/bin/python -m pytest 上述两文件 -o addopts="" -p no:warnings   ⇒ 7 passed, rc=0
四目录回归（未经管道直取 rc）:
  tests/unit        → 3 failed, 992 passed, rc=1   （红集 == 既有 3 条 test_provision_cli，非本片）
  tests/integration → 486 passed, 1 xfailed, rc=0
  tests/contract    → 53 passed, rc=0
  tests/recovery    → 18 passed, rc=0
ruff check src tests → All checks passed!
```

测试覆盖：正例（资产↔声明钉值一致 / 解析统计 / 物化→图可查→血缘与计划一致）；
反例（副本篡改 ⇒ `ONTOLOGY_ASSET_DRIFT` 且无产物；声明钉值不符 ⇒ `ONTOLOGY_ASSET_DECLARATION_MISMATCH`；
provenance 非法 ⇒ `ONTOLOGY_ASSETS_PROVENANCE_INVALID`）。

## 6. 未做与风险

1. **供给面未扩展**：`provision.py` 属他人在途 ⇒ `90_control/ontology/` 未纳入其白名单；
   本片以 `ensure_assets` **显式引入**（拷自受控源后按 provenance 校验）。→ 待其落定后可一行并入供给。
2. **不做推理**：未引入 owlready2/推理机；`rdfs:subClassOf` 已有 7 条边，但**未做**传递闭包/一致性推理。
3. **R2RML / INSTANCES 仅登记与校验**：R2RML 未映射执行；`products.ttl` 只用于 SHACL 校验（conforms 统计）。
4. 与本片无关但在途：`activation_contract.py` 及第三方 7 项 —— **未碰**；不 commit、不 push。

---

## 7. 推理评估（后续件）：实测**无收益** ⇒ **不引入**（判据 ②）

```text
底数：OWL 原始三元组 255
RDFS 闭包    : +200  （其中 rdf:type rdfs:Resource 类公理 193 ⇒ 噪声）
OWL-RL 闭包  : +570  （自反 sameAs 242、自反 subClassOf 34，其余为 datatype/annotation 记账）
① 真实类层次闭包（两侧皆**本域具名类**且非自反）：**+0**
② 实例级类型断言（13 个实例；ontology+instances 合并后闭包）：**+0**
③ SHACL 校验 inference = None / rdfs / owlrl / both ⇒ **conforms=True, violations=0（四档完全相同）**
⇒ 差异**非空但全为公理/自反噪声，无业务意义** ⇒ 判据 ② ⇒ **不引入推理、不入产物**
```

**口径明细（防"同一组数被读成互相矛盾"；TL 独立复算的值在此对齐）**

```text
subClassOf 新增 = 101，拆解（**四个量；其中两个数值相同，但**不是同一集合**）：
  A **全量自反**（s == o）= **34**
      = A1 **本域自反**（X ⊑ X，X 为 32 个本域类）= **32**   ← 这就是 TL 复算的「本域 32」
      + A2 非本域顶层自环（owl:Thing ⊑ owl:Thing、owl:Nothing ⊑ owl:Nothing）= **2**
  B **本域主语、非自反**（宾语**全部是 `owl:Thing`**）= **32**   ← 平凡顶层公理（噪声）
  C **两端皆本域、非自反** = **0**                            ← "有意义类层次闭包 = 0" 的**确切口径**
                                                               （即 TL 复算的「非自反 = 0」）

⚠ **A1 与 B 数值都是 32，但二者是**不同集合** —— 数值相同**纯属巧合**，不得互相顶替**：
    A1 = 本域**自环** `X ⊑ X`（自反）；
    B  = 本域类指向 **`owl:Thing`** 的平凡公理 `X ⊑ owl:Thing`（非自反）。
    **两者都不是"有意义的层次闭包"** ⇒ 一切判定只取 **C = 0**（**两端皆本域** + 非自反）。
⇒ 34 / 32 / 32 / 0 四个数**同源且各自成立**；差异只在**限定条件**（是否"两端皆本域"、是否含顶层公理）。
```


- **依赖面不变**：**不**新增直接依赖（`owlrl` 本来就是 `pyshacl` 的传递依赖，lock 已钉 `owlrl==7.6.2`）；
  本件只**实测**，不扩依赖。
- **现有 `inference="rdfs"`**：实测与 `None` 结果相同 ⇒ **中性参数**，保留（不引入新依赖、不改校验语义）。
- **落地形式（防"漏做"误解）**：① 产物 `ONTOLOGY.md` 增「推理（已评估，未启用）」段；
  ② 数值钉在 `tests/unit/test_ontology_reasoning_is_neutral.py`（4 用例）——将来若出现**有意义的**差异，
  该测试变红 ⇒ 强制重新评估并同步证据与 lock。
- **命令与退出码（E-11）**：`.venv/bin/python -m pytest tests/unit/test_ontology_reasoning_is_neutral.py
  tests/unit/test_ontology_assets_and_parse.py tests/integration/test_ontology_materialization.py
  -o addopts="" -p no:warnings` ⇒ **11 passed, rc=0**；
  四目录：unit `3 failed, 996 passed / rc=1`（红集仍=既有 3 条 `test_provision_cli`，非本片）、
  integration `490 passed, 1 xfailed / rc=0`、contract `53 passed / rc=0`、recovery `18 passed / rc=0`；
  `ruff check src tests` → All checks passed。

- **报数三要素（范围 + 凭据态 + 计数来源；与 c20 对齐，2026-09-16）**：本节的每个数字都按此三注读：
  · **范围**：各数字的**选择集不同、不可横比** —— 「四目录」行 = `tests/<dir>` **全目录**（如 integration `499 passed + 1 xfailed`）；
    **定向选择**行 = 显式列出少数文件（如 §7 的 `11 passed`、下文的 `16 passed`）或单文件，**不得**与全目录数并排比较；
  · **凭据态**：见下条（本节**全部为不带凭据**）；
  · **计数来源**：**pytest 汇总行**（`-q` 模式）。其中 integration 的 **`1 xfailed`** =
    `tests/integration/test_product_recommendation_sp15_chain.py::test_product_loader_from_assets`
    （Owner 豁免 `WAIVER-2026-09-14-F-L00-07`，**`strict=True`** ⇒ 一旦 XPASS 即判失败、强制移除豁免），
    **在 junit 中计为 `skipped=1`** ⇒ 与"真实 skip"不同、但与 junit 的 skipped 是**同一条**
    （我实测 `-rxX` ⇒ `16 passed, 1 xfailed`，XFAIL 行即点名该用例）。**真实 skip = 0**。

- **凭据状态（TL 2026-09-16 新纪律：报跑数必须注明"带凭据 / 不带凭据"）**：本节**全部跑数均为
  不带凭据** —— 实测 `env | grep KERT_LIGHTRAG` 命中数 = **0**（`KERT_LIGHTRAG_*` 未设置）；
  且该时点套件内**尚无** lightRAG 用例（`tests/integration/test_lightrag_publication.py` 由第三方后加）。
  ⇒ 引用本段数字时须**连同"不带凭据"一并引用**（否则会把"环境差异"读成"回归"）。

  **后续更正（2026-09-16，第三方修复后）**：当时那条"无凭据 ⇒ 红"的**根因是第三方测试写法**（`_pre_clean`
  置于受保护 `try` 之外 ⇒ 无凭据时未捕获 401），**已修复** ⇒ **同一用例不再因凭据而翻转**。
  修复后三环境**各自断言对应分支**：**无凭据 = 7 passed / rc=0（我实测）**、无实例（= CI）= 12、
  带凭据 = 12（后两者：**c20 自测**；**TL 已用其本机凭据"代验"** —— **我仍未复核，故本件不为其背书**）；
  **不加 marker、不从默认套件排除、不 `skip`**。
  ⇒ "**必须注明凭据状态**"这条**纪律不变**（数值仍随环境变），但**不得**再引"该用例带 / 不带凭据结论相反"这一**旧描述**。

---

## 8. 外部调用者独立复现（**最强形态证据**）：P-1 调用 + 我的独立复算，逐项相同

**口径（按 c20 给的声明式口径）**：下列数字是 **API 实测值**，**目标工作区为 `/tmp`**（**未写** `examples/**/90_control/**`），
**调用者为 c20**（其 P-1「数据出口」轮），**不是**我的复跑窗口；本节由我**独立复算**后记录，按 D-8 带 sha。另：**c20 未编辑我的任何文件**。

```text
调用（c20） : materialize_ontology(tmp, version="2026.09.16.1",
             assets_source=<repo>/examples/bank-front-knowledge-maps/90_control/ontology)
我的独立复算: 同签名、另一 /tmp 工作区:
  files = 5（ontology_classes/properties/shapes.parquet + ONTOLOGY.md + ONTOLOGY_LINEAGE.json）
  graph = {dir: ontology_graph, node_count: 99, edge_count: 100,
           fingerprint: 190593d7bdd516ffe3b275081a35a34192e1e4fa06de28029e5ad68a2fbd3cc4}
  ONTOLOGY.md = 1939 B ; sha256 9d2ebc4c22ef715f505ce9fbb0312c24…（复算时的值）
⇒ **c20 报数与我复算逐项相同**（files 5 / 99 / 100 / **同一 fingerprint** / 1939 B）
```

> **`files = 5` 的指代必须写明（与 §7「两个 32」同族）**：指**产物目录内被声明的 5 个文件** ——
> 即 `FILES` 元组 = `ontology_classes/properties/shapes.parquet` + `ONTOLOGY.md` + `ONTOLOGY_LINEAGE.json`，
> **不含图**（图另计：`ontology_graph`（Kùzu 单文件）、`ontology_graph.PROJECTION.json`）。
> ⇒ 该 `version=` 目录**实际 7 项**（5 + 图两项），图规模见返回值的 `graph` 字段（99/100）。
> ⚠ **另一处同值不同集合**：**内置资产目录** `<ws>/90_control/ontology/` 恰也是 **5 件**
> （4 个 ttl + `PROVENANCE.json`）—— 与上面的 `files = 5` **数值相同、集合不同**，引用时须写明是哪一个。

- **确定性旁证**：同一 fingerprint 现由**五方独立**得到 —— ① 我 18:0x 自产件、② c20 的 P-1 调用、
  ③ 我本次复算、④ **TL 的独立复算**（TL 报其 `counts` 与 `ONTOLOGY.md = 1939 B` 与本节点逐项相同；
  **该次由 TL 自测，我未复核其运行**，此处仅据其报告登记）、
  ⑤ **c20 在"清空—重建语料"之后的三次调用**（其报告：语料清空/重建**不改变**该结构稳定量；
  **该三次由 c20 自测，我未复核其运行**，仅据其报告登记）
  ⇒ 支持"物化可复现"（c20 已将其登记为后续抓手，**不属本件**）。
- **预登记预测已证实（本件方法学最强形态）**：本人在 c20 清库**之前**给出**可证伪**预测 ——
  "清空重建后再物化，`graph.fingerprint` **必须仍是** `190593d7…`；若变，说明本件'确定性'结论有问题，请报回"。
  c20 **清空—重建后三次调用**均返回同一 fingerprint ⇒ **预测成立**（且此为"若变即告警"的**主动**判据，
  与 §7 的"会报警的测试"同族）。

  **自变量 / 因变量（防过度解读，范围按 c20 的界定）**：
  - **已证实**：自变量 = 目标工作区/目录与语料清空—重建（**本体资产不变**）⇒ 因变量 `fingerprint` **不变**（五方交叉）；
  - **不覆盖**"本体资产变" —— 那种情形**本就应变为另一指纹**；本件把它钉成**正向测试**：
    `tests/integration/test_ontology_materialization.py::test_fingerprint_is_target_invariant_and_content_sensitive`
    （① 换工作区 ⇒ **同**指纹；② 内容变 + 声明同步改钉 = **合法换版** ⇒ **指纹必变**，实测 classes 32 → 33）。
  ⇒ 本判据**不是**"任何条件下恒定"，而是「**目标侧不变性 + 内容侧敏感性**」两个方向的主动判据。
- **外部可调用性**：目标工作区**可任意指定**（c20 落在 `/tmp`）；复算后仓库侧**无新增写入**
  （实测 `git status` 仅见既有第三方未跟踪项）。
- **用途（c20 侧，非本件结论）**：该产物被用作外部检索的**出处载体**
  （`file_source = 04_serve__product_knowledge__version=2026.09.16.1__ONTOLOGY.md`），检索命中的 `file_path` 实测回指该路径 + 版本。
