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
