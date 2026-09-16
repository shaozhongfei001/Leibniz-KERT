# 证据：本体引用（M7.3 第三步 —— 只读消费 gits 本体）

```text
TASK        : M7-3-3-ONTOLOGY-REFERENCE（任务包 evidence/m7-3/TASK_PACKAGE_M7-3-3-ONTOLOGY-REFERENCE.md）
AUTHORITY   : docs/governance/KERT_PENDING_OWNER_DECISION_M7_EVOLUTION_V1.0.md §0 → **D3-A**
             独立评审 §4.7（ActivationPlan 版本快照 + 可重放 plan hash）
实施者      : 子代理 `m7-3-ontology-ref`（TL 派工）
收工与验证  : Tech Lead（见 §0 说明）
BRANCH      : feature/m7-3-knowledge-map-route（base = c597dda）
DATE        : 2026-09-15
ENV         : python3 3.10.12；ruff 0.16.4（= .github/workflows/ci.yml:49 锁定版本）
```

## 0. 分工说明（如实记录，含一次接管）

- **实现与自证由子代理完成**：`ontology_reference.py`、声明文件、用例更新，以及 **N1–N4 四项变异自证**
  （其原始日志 `evidence/m7-3/ontology-reference-mutation-20260915T082238Z.log`）。
- **子代理在收工前停住**：未写本证据文件、未做本地提交（约 15 分钟无进展）。TL **接管收工**：
  完成本证据文件、本地提交，并**独立复跑**验证（§4，**不采信其日志自述**）。

## 1. 交付文件

| 文件 | sha256（前 20） | 说明 |
|---|---|---|
| `src/kert/domain/ontology_reference.py` | `0cd9ebcdac2d4f7a8ba7…` | `ontology_reference/v1` 契约 + 严格解析 + 加载 + **带外核验** + 解析裁决 |
| `src/kert/domain/activation_plan.py` | `d0947461328da3196f30…` | D-3：本体**版本**入 `canonical_content`；`versions.ontology` 取真实值；D-4：本体门禁拒绝 |
| `examples/bank-front-knowledge-maps/90_control/schema/ontology_reference.json` | `653f3ac8050f66e45c73…` | 声明的钉值（真实取值，见 §2） |
| `tests/unit/test_ontology_reference.py` | — | **37 例** |
| `tests/unit/test_activation_plan.py`（更新） | — | 增本体相关断言；**既有断言未被放宽**（TL 复核，见 §5） |

**未越界**：`git status` 显示改动全部落在任务包 §3 允许路径内；未改 gits 仓、`03_core`、
`skills.py`、`route_policy.py`、`knowledge_map.py`、OpenAPI 合同。

## 2. 权威取值（与 gits 侧黄金计划逐字一致）

```text
contractId       : CTR-SEM-002
authorityRepo    : gits-cbanking
authoritySource  : specs/semantic/gits-core.owl.ttl
contentSha256    : 705578d6324abd0c1bd2bd670e6f3c0ffd8e04c358d0134246c89a3acfc38d00
→ version        : CTR-SEM-002@sha256:705578d6324abd0c
```

该 `version` 与 gits 侧 `specs/knowledge-architecture/examples/AP-*-GOLDEN.json` 的 `versions.ontology`
**逐字一致** ⇒ 跨仓同口径达成。

## 3. 命令与结果（原始退出码）

| # | 命令 | 退出码 | 结果 |
|---|---|---|---|
| 1 | `python3 -m pytest tests/unit` | **0** | **832 passed** |
| 2 | `python3 -m pytest tests/unit/test_ontology_reference.py --collect-only -q` | 0 | `37` |
| 3 | `python3 -m ruff check src/ tests/` | **0** | `All checks passed!` |
| 4 | 变异残留检查 `grep -n "UNUSED\|if False\|downgraded" src/kert/domain/*.py` | 1（无命中） | **无残留 ✓**；声明文件 `contentSha256` 完好 |

## 4. 变异自证

### 4.1 子代理执行（N1–N4，原始日志见其 log；各含 基线 PASS → 变异 FAIL → 恢复 PASS）

| 变异 | 施加方式 | 变异后 FAIL 的用例 |
|---|---|---|
| **N1** 本体版本不进 hash | `activation_plan.py` canonical content 中 `ontology={ontology_key}` → `ontology=UNUSED` | `test_ontology_version_enters_plan_hash`、`test_ontology_key_participates_in_canonical_content`、`test_plan_hash_is_sensitive_to_ontology_key` |
| **N2** 本体门禁被禁用 | 拒绝分支改为 `if False:` | `test_denied_when_ontology_declaration_absent`、`..._invalid`、`test_ontology_denial_codes_are_distinct_from_route_codes`、`test_denied_when_builder_has_no_workspace` |
| **N3** INVALID 降级为 ABSENT | `resolve_reference` 非法分支改返回 `CODE_ABSENT` | `test_bad_json_declaration_is_invalid`、`test_invalid_declaration_is_invalid_code`、`test_denied_when_ontology_declaration_invalid` |
| **N4** 声明值改变不传导 | 声明文件 `contentSha256` 前 16 位改为 `aaaaaaaaaaaaaaaa` | 版本引用断言 FAIL（期望 `…705578d6324abd0c`，实际 `…aaaaaaaaaaaaaaaa`） |

### 4.2 TL **独立复核**（N5，自己跑，不采信日志）

日志：`evidence/m7-3/ontology-reference-TL-independent-20260915T084309Z.log`

```
[基线]       plan_hash=97f2933073121ccd  versions.ontology=CTR-SEM-002@sha256:705578d6324abd0c
[只改来源]   plan_hash=97f2933073121ccd  ← 只改 authorityRepo + authoritySource
  ⇒ PASS：来源改变**不**影响 plan_hash ✓（来源路径不入 hash）
[改内容哈希] plan_hash=0bad46e875abf2a6  ← contentSha256 换为另一合法值
  ⇒ PASS：内容哈希改变**必**使 plan_hash 变 ✓
[恢复]       plan_hash=97f2933073121ccd  AND to_dict() 与基线逐字段相同
  ⇒ PASS：可重放 ✓
[声明缺失]   PlanDenial code=ONTOLOGY_REFERENCE_ABSENT    ⇒ PASS：缺失即拒绝 ✓
[声明非法]   PlanDenial code=ONTOLOGY_REFERENCE_INVALID   ⇒ PASS：非法即拒绝且码与缺失区分 ✓
```

**这一条是本次最关键的反空转对照**：若实现把来源路径也塞进 hash，"内容敏感"会**假通过**；
N5 用"只改来源"证明 hash 只对**内容哈希**敏感。

## 5. TL 复核：既有断言是否被放宽

`git diff tests/unit/test_activation_plan.py` 的删除行**仅两处**：一条 import（被拆成两条）、
以及 `assert plan.versions["ontology"] is None` —— 后者正是 D-3 要求变更的语义，
且被替换为**更强**断言 `assert plan.versions["ontology"] == "CTR-SEM-002@sha256:705578d6324abd0c"`。
落盘形状断言 `test_plan_to_dict_shape_is_stable`（键集合固定）**未被改动**。
⇒ **未放宽、未删除**有效断言。

## 6. 关键语义

- **D-1 声明的钉值**：运行期零跨仓耦合；不读 gits 文件、不调其接口、**无硬编码跨仓路径**。
  声明文件是"信任锚"，证明"曾按此值声明消费"，**不**证明权威源当下仍等于该哈希。
- **D-2 带外核验**：`OntologyReference.verify_external(path)`，路径**由调用方传入**，运行期不使用；
  供人类/独立 QA 复核钉值与权威源是否仍一致。
- **D-3 入 hash**：本体版本进 `canonical_content`；`authorityRepo:authoritySource` 作为
  `ontology_source` **仅记录、不入 hash**（代码注释显式标注）。
- **D-4 fail-closed**：缺失 ⇒ `ONTOLOGY_REFERENCE_ABSENT`；非法 ⇒ `ONTOLOGY_REFERENCE_INVALID`
  （**新增码，不复用既有路由码**）；两者可区分（N3/N5 覆盖）。

## 7. ⚠ 运维前提（必须随部署满足）

fail-closed 意味着**工作区必须经供给（provisioning）放入本体引用声明**，否则该工作区的
**计划构建会被全量拒绝**。受控 example 工作区已随本步提供声明文件；
**运行时工作区（如 `bank_front_ws`）的供给属第五步接线范围，本步未处理**。
⇒ 在接线（第五步）与供给落地**之前**，不得把本步当作"已可用于运行时"。

## 8. 未做（后续）

1. 运行时工作区的**供给**（把声明与地图/策略装入 `bank_front_ws` 等）；
2. `skills.py` 接线（第五步）；
3. HTTP 端点与 OpenAPI 合同（第四步，需 Contract Owner）；
4. `versions.activationContract` 仍为 `None`（本仓暂未引入激活合同）；
5. 钉值**未被独立复核过**：带外核验入口已提供，但本步**未**对 gits 权威源实跑核验
   （跨仓动作，需显式授权与路径）。

## 9. 非声明

- 本证据**不是** `QA_PASS`、**不是**独立验证结论；**不**声明生产就绪、**不**声明 GITS UAT 通过；
- **不**声称 KERT 拥有本体权威（本体权威仍在 gits）；**不**声称跨仓集成已验收；
- **不**引入 LightRAG（D2-A）、**不**内置 KERT 自有本体（D3-A）；既有 Kùzu/Parquet 形态未改动；
- 未改 `03_core` 权威资产；未 push（`AGENTS.md` 规则 #10）。
