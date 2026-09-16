# 任务包：M7.3 第三步 —— 本体引用（只读消费 gits 本体）

```text
PACKAGE_ID : M7-3-3-ONTOLOGY-REFERENCE
WAVE       : M7.3（Skill/Route/ActivationPlan 治理）
ISSUED_BY  : Tech Lead（本会话）
ISSUED_AT  : 2026-09-15
BRANCH     : feature/m7-3-knowledge-map-route（HEAD = 5a95199，M7.3 第二步已交付）
AUTHORITY  : docs/governance/KERT_PENDING_OWNER_DECISION_M7_EVOLUTION_V1.0.md §0 → **D3-A**
             独立评审 §4.7（ActivationPlan 的版本快照）
PURPOSE    : 让"本体模型"与"语义层到数据源"两项在 KERT 侧**有落点**：
             以「契约引用 + 内容哈希版本」只读消费 gits 本体，并让本体版本进入可重放 plan hash。
```

---

## 0. TL 已定口径（**子代理不得自行改判**，有异议回报）

### D-1 引用如何取得：**声明的钉值（declared pin）**，不做运行期跨仓读

- KERT **不在运行期**读取 gits 仓库的任何文件、不调用 gits 接口、不硬编码任何跨仓路径；
- 引用以**控制面声明文件**形式存在：`<ws>/90_control/schema/ontology_reference.json`；
- 该文件是**信任锚**（declared trust anchor）：它声明"我们按此合同与内容哈希消费本体"。
- **理由**：KERT 与 gits 是两个仓。运行期文件系统耦合到另一仓的目录布局既脆弱又越过边界；
  而 D3-A 的要求是"只读消费 + 契约引用 + 内容哈希版本"，**声明钉值满足该要求且零耦合**。

### D-2 校验能力：提供**带外核验**入口，路径由调用方给出

- 允许提供一个**显式核验**函数/CLI 参数：给定一个**由调用方传入**的路径，计算其 sha256 并与钉值比对；
- **禁止**在实现对生产钉值做硬编码路径（如 `/home/.../gits-cbanking/specs/...`）；
- 目的：让人类/QA 能**独立复核**钉值是否仍与 gits 权威源一致（钉值本身在运行期不可自证）。

### D-3 入不入 plan hash：**入**（与 gits 侧 GK17 WP2.3 同口径）

- 本体**版本**（`<contractId>@sha256:<前16位>`）**进入** `canonical_content` ⇒ 本体一变，`plan_hash` 必变；
- **来源路径不得入 hash**（环境相关；gits 侧同裁定）；
- 目的：跨仓口径一致 —— gits 侧判据 V2 即"只改本体 ⇒ 计划必变"。

### D-4 fail-closed 语义（**新增拒绝码，不得复用既有码**）

| 情形 | 结果 |
|---|---|
| 声明文件缺失 | **Deny**，码 `ONTOLOGY_REFERENCE_ABSENT`（"本体未被消费"不得静默通过） |
| 声明文件非法（未知字段/schema 不符/合同 ID 不合法/哈希非 64 位小写 hex） | **Deny**，码 `ONTOLOGY_REFERENCE_INVALID` |
| 声明合法 | 放行，`versions.ontology = "<contractId>@sha256:<前16>"`，且该值**进** plan hash |

> ⚠ 与"未配置就该拒绝"配套的**运维前提**：受控 example 工作区**必须**随本步提供声明文件，
> 否则其 3 条真实路由会全部被拒。运行时工作区（如 `bank_front_ws`）的**供给（provisioning）**
> 属第五步接线范围，本步**不**处理，但**必须**在证据中写明该前提。

---

## 1. 权威取值（TL 已实测，直接采用，**不得自行另取**）

```text
合同 ID          : CTR-SEM-002
权威源（在 gits 仓）: specs/semantic/gits-core.owl.ttl
内容 sha256（全） : 705578d6324abd0c1bd2bd670e6f3c0ffd8e04c358d0134246c89a3acfc38d00
版本字符串（前16）: CTR-SEM-002@sha256:705578d6324abd0c
```

> 该取值与 **gits 侧黄金计划** `specs/knowledge-architecture/examples/AP-*-GOLDEN.json` 的
> `versions.ontology` **逐字一致** ⇒ 跨仓同口径（这是本步的对齐目标，不是巧合）。

## 2. 契约：`ontology_reference/v1`（新增控制面声明）

位置：`<ws>/90_control/schema/ontology_reference.json`

| 字段 | 必填 | 规则 |
|---|---|---|
| `schema` | 是 | 必须等于 `ontology_reference/v1` |
| `contractId` | 是 | 满足 `ids.ID_RE`，且以 `CTR-` 开头 |
| `authorityRepo` | 是 | 权威源所属**仓名**（非路径），如 `gits-cbanking` |
| `authoritySource` | 是 | 权威源在**所属仓内**的相对路径，如 `specs/semantic/gits-core.owl.ttl`；须为相对路径（**不得**以 `/` 开头） |
| `contentSha256` | 是 | **64 位小写 hex**（全量哈希，不是前 16 位） |
| `pinnedAt` | 否 | 声明日期（`YYYY-MM-DD`） |
| `notes` | 否 | 说明 |

**严格校验（沿用本仓既有风格，全部 fail-closed）**：未知字段 / 类型错 / schema 不符 /
`contractId` 非法或前缀不符 / `authoritySource` 为绝对路径或含 `..` / `contentSha256` 非 64 位小写 hex
⇒ `SchemaValidationError`（定义**文件**取值非法属契约错误，不抛 `UsageError`）。
`version` 属性 = `f"{contractId}@sha256:{contentSha256[:16]}"`。

## 3. 交付物与**写者独占路径**（越界即返工）

| 允许写 | 内容 |
|---|---|
| `src/kert/domain/ontology_reference.py`（新增） | 契约模型 + 严格解析 + 加载 + 带外核验 |
| `src/kert/domain/activation_plan.py`（**仅**为 D-3 改动） | 本体版本进 `canonical_content`；`versions.ontology` 取真实值；按 D-4 产出 Deny |
| `examples/bank-front-knowledge-maps/90_control/schema/ontology_reference.json`（新增） | 用 §1 权威取值 |
| `tests/unit/test_ontology_reference.py`（新增） | 契约与核验用例 |
| `tests/unit/test_activation_plan.py`（更新） | 增本体相关断言；**不得删除既有断言** |
| `evidence/m7-3/` | 证据与变异日志 |

**禁止**：改 gits 仓任何文件；改 `03_core`；改 `src/kert/application/skills.py`（属第五步）；
改 `route_policy.py` / `knowledge_map.py`；改 `specs/kert-openapi-v1.yaml`（属第四步，且需 Contract Owner）；
引入新依赖；引入 LightRAG；在代码中硬编码跨仓绝对路径。

## 4. 必须的负例（本仓硬约束：不做负例视为未完成）

≥2 条，每条自证「变异前 PASS / 变异后 FAIL / 恢复 PASS」，并记录命令、退出码、原始输出：

1. **缺失即拒绝**：移走声明文件 ⇒ 计划构建必须 **Deny**（码 `ONTOLOGY_REFERENCE_ABSENT`），
   而不是"照常出计划"；
2. **哈希敏感性**：把声明里的 `contentSha256` 换成另一个合法哈希 ⇒ `plan_hash` **必须变**；
   换回 ⇒ 必须回到原值（可重放）。
   - 反向对照（防空转）：**只改来源路径/仓名，不改哈希** ⇒ `plan_hash` **必须不变**（路径不入哈希）。

另需覆盖：未知字段、`contentSha256` 长度/大小写非法、`authoritySource` 绝对路径或含 `..`、
`contractId` 前缀不符；**带外核验**：给定实际文件（测试用临时文件）⇒ 比对通过/不一致时报错。

## 5. 验收命令（**串行**执行，逐条记录退出码）

```bash
cd /home/szf/dev/Leibniz-KERT
python3 -m pytest tests/unit/test_ontology_reference.py tests/unit/test_activation_plan.py -q
python3 -m pytest tests/unit -q                    # 全量，不得回归
python3 -m ruff check src/ tests/                  # 必须用 ruff==0.16.4（= ci.yml:49 锁定版本）
```

## 6. 证据要求

写入 `evidence/m7-3/EVIDENCE-ONTOLOGY-REFERENCE.md`：交付文件表、命令与退出码、变异自证表
（含恢复后 sha256 一致性）、关键语义、未做项、非声明。
**禁止**在证据中写"已实现 LightRAG""已内置本体""生产就绪""QA_PASS"。

## 7. 停止条件（仅这 5 种回报给 TL）

缺凭据 / 需求冲突 / 方向性变更 / 同一门禁 5 次仍红 / 安全隐患。其余自愈处理。

## 8. 非声明

本任务包**不是** Owner 决议、**不是**规格修订；`PENDING_OWNER_DECISION` 项不得当作已批准；
"引用 gits 本体"**不**等于 KERT 拥有本体权威，也**不**代表跨仓集成已验收。
