# 证据：知识地图注册表（M7.3 第一步）

```text
TASK        : M7.3 Skill/Route/ActivationPlan 治理 —— 第一步：KnowledgeMapRegistry
AUTHORITY   : docs/dd/KERT_independent_architecture_review_2026-08-26_V1.0.md §4.7（KERT 自定的目标设计）
              docs/governance/KERT_PENDING_OWNER_DECISION_M7_EVOLUTION_V1.0.md §0（D1-A 授权实施该子集）
BRANCH      : feature/m7-3-knowledge-map-route
DATE        : 2026-09-15
ENV         : python3 3.10.12（本机）；ruff 0.16.4（与 .github/workflows/ci.yml:49 锁定版本一致）
```

## 1. 交付文件

| 文件 | 说明 |
|---|---|
| `src/kert/domain/knowledge_map.py` | 知识地图定义模型 + 严格解析 + `KnowledgeMapRegistry`（fail-closed） |
| `examples/bank-front-knowledge-maps/`（受控工作区实例） | `kert init` 生成的合法工作区（含 `.kert_workspace`）；本机实例 `check_workspace` findings = **NONE**。⚠ git **不跟踪空目录**，故全新 clone 后实际检出的是 `.kert_workspace`、`90_control/README.md` 与 `90_control/catalog/KM-*.json`；其余空层目录需 `kert init` 重建。测试只断言 `is_workspace`（marker 在 ⇒ 该断言在全新 clone 下同样成立） |
| `examples/bank-front-knowledge-maps/90_control/catalog/KM-CORP-RM-OUTREACH.json` | 外联准备地图（`assetRefs` = `_run_outreach` 真实读取的 KI） |
| `.../KM-CORP-RM-MEETING.json` | 会面准备地图（= `_run_meeting` 的 KI） |
| `.../KM-CORP-RM-PREVISIT.json` | 访前准备地图（= `_run_previsit` 的 KI） |
| `tests/unit/test_knowledge_map.py` | 28 个用例（反空转 / 反虚构 / fail-closed 全覆盖） |

**位置依据**：`src/kert/domain/workspace.py:14-17` 定义
`90_control/{catalog,schema,lineage,quality,jobs,decisions,locks,logs}`，其中 `catalog` = 资产目录、
`schema` = "词表/映射/策略" ⇒ 地图定义（控制面元数据）落 `90_control/catalog/`，文件名满足
`ID_FILENAME_RE`（`KM-*.json`）。**未触碰 `03_core` 权威资产**（`RULES.md` 禁止项）。

### 1.1 ⚠ 归属纠正（本次实施中发现并已改正）

初版把三张地图定义写在 `bank_front_ws/90_control/catalog/`（服务默认工作区），但发现：

```
$ grep -n "bank_front_ws" .gitignore
49:bank_front_ws/
$ git check-ignore -v examples/bank-front-knowledge-maps/90_control/catalog/KM-CORP-RM-PREVISIT.json
（无输出 ⇒ 未被忽略）
```

`bank_front_ws/` 是**被 `.gitignore` 忽略的运行时数据**，放在那里等于**不入库的"影子权威"**。
故改为受控位置 `examples/bank-front-knowledge-maps/`（与既有
`examples/product-recommendation-assets/` 同构——后者被 `src/.../sp15_skill.py:149` 引用），
并**从 `bank_front_ws` 撤出**该目录，避免出现两份定义。
`bank_front_ws` 属运行时工作区，未配置地图时注册表为空 ⇒ 解析按 fail-closed **默认拒绝**（预期行为）。

## 2. 命令与结果（原始退出码）

| # | 命令 | 退出码 | 结果 |
|---|---|---|---|
| 1 | `python3 -m pytest tests/unit/test_knowledge_map.py -q` | **0** | `28 passed` |
| 2 | `python3 -m pytest tests/unit -q` | **0** | 单元测试全量通过（无回归） |
| 3 | `python3 -m ruff check src/ tests/`（ruff 0.16.4 = CI 锁定版本） | **0** | `All checks passed!` |
| 4 | `PYTHONPATH=src python3 -c "... check_workspace(...)"` | **0** | 受控工作区 findings = `NONE` |
| 5 | `make lint` | **2** | **该目标不存在**（Makefile 无 lint 目标）⇒ 以 CI 的 ruff 命令替代并如实记录 |

## 3. 变异自证（证明断言非空转）

原始日志：`evidence/m7-3/knowledge-map-mutation-*.log`

| 变异 | 施加方式 | 变异前 | 变异后 | 恢复后 |
|---|---|---|---|---|
| **M1** 控制面"无地图" | 移走 `examples/bank-front-knowledge-maps/90_control/catalog` | PASS（28） | **FAIL**：`test_real_workspace_registers_three_maps_with_nonzero_refs`、`test_real_maps_reference_only_kis_that_skills_actually_read` 变红 | PASS（28） |
| **M2** 歧义拒绝被移除 | 把"同优先级歧义 ⇒ 拒绝"分支改为"任取第一个" | PASS（28） | **FAIL**：`test_same_priority_ambiguity_is_denied` 变红 | PASS（28）；`knowledge_map.py` sha256 复原 `c6d322f90222a4a4…` |

## 4. 关键断言设计（防空转 / 防虚构）

- **反空转**：先断言受控工作区**加载到 3 张地图**、每张 `assetRefs`/`skillRefs` 非空、
  `sequence` 连续从 1 开始、且该目录**确是合法工作区**（`is_workspace` 为真），再断言行为。
- **反虚构**：`test_real_maps_reference_only_kis_that_skills_actually_read` 交叉核对地图 `assetRefs` 的每个
  `assetId` **必须出现在 `src/kert/application/skills.py` 中**（技能真的读取过该 KI），并断言核对条数恰为
  **10**（3+4+3）—— 防止地图引用不存在的知识条目。
- **fail-closed 全覆盖**：未知字段 / 非法 schema / 非法 ID / 前缀不符 / 非法版本 / 非法域 / 空 tasks /
  重复 tasks / 非法 priority / 重复资产 / 重复 sequence / 重复 skillRef / 资产子字段未声明 /
  空任务 / 未注册 mapId / 非对象 / 坏 JSON / 文件缺失 / 非 `KM-*.json` 文件不纳入，各有独立用例。
- **设计缺陷修正（由测试暴露）**：初版对 `skillRefs` 误用全大写 `ids.ID_RE`，而 KERT 真实 Skill ID 为
  混合大小写（`skill-customer-*` 与 `SP-*`）⇒ 已引入 `SKILL_ID_RE`（只放宽大小写，长度与字符集仍受限）；
  同时把定义文件里的取值非法由 `UsageError` 改为 `SchemaValidationError`（**契约**错误 vs 调用方参数错误）。

## 5. 本步**未**做（后续切片）

1. `RoutePolicy`（输入、优先级、歧义拒绝、默认拒绝）与 `ActivationPlan`（资产/Skill/权限/版本快照 + **可重放 plan hash**）；
2. 把 `skills.py` 中**硬编码的 mapId 字面量**改为从注册表解析（定义已就位，技能仍用硬编码串）；
3. `routePolicyRef` / `activationContractRef` 回填（当前**刻意留空** —— 不虚构跨仓绑定）；
4. HTTP 端点（`/api/knowledge-maps*`）与版本合同；
5. 本体引用（D3-A：只读消费 gits 本体 + 内容哈希版本）；
6. 地图定义在**运行时工作区**的供给（provisioning）：`bank_front_ws` 等实际工作区目前无地图 ⇒ 默认拒绝。

## 6. 非声明

- 本证据**不是** `QA_PASS`、**不是**独立验证结论；**不**声明生产就绪，**不**声明 GITS UAT 通过；
- 本步**不**引入 LightRAG（D2-A），**不**内置 KERT 自有本体（D3-A）；既有 Kùzu / Parquet 形态未改动；
- 仅新增受控工作区实例与其控制面元数据；**未改**任何既有文件内容、**未改** `03_core` 权威资产；
- 未 push（`AGENTS.md` 规则 #10：无 Owner 授权不得自动 push/merge）。
