# 证据：路由策略 + 激活计划（M7.3 第二步）

```text
TASK        : M7.3 Skill/Route/ActivationPlan 治理 —— 第二步：RoutePolicy + ActivationPlan
AUTHORITY   : docs/dd/KERT_independent_architecture_review_2026-08-26_V1.0.md §4.7
              docs/governance/KERT_PENDING_OWNER_DECISION_M7_EVOLUTION_V1.0.md §0（D1-A）
BRANCH      : feature/m7-3-knowledge-map-route
DATE        : 2026-09-15
ENV         : python3 3.10.12；ruff 0.16.4（= ci.yml:49 锁定版本）
```

## 1. 交付文件

| 文件 | 说明 |
|---|---|
| `src/kert/domain/route_policy.py` | 路由策略模型 + 严格解析 + `RouteResolver`（默认拒绝 / 歧义拒绝 / 跨引用校验） |
| `src/kert/domain/activation_plan.py` | `ActivationPlan` 快照 + **可重放 plan hash** + `ActivationPlanBuilder`（拒绝即不产出计划） |
| `examples/bank-front-knowledge-maps/90_control/schema/route_policy.json` | 真实策略 `RP-KERT-BANKFRONT-001`（3 条规则，`defaultDecision=DENY`） |
| `.../90_control/catalog/KM-CORP-RM-*.json` | 三张地图**回填** `routePolicyRef=RP-KERT-BANKFRONT-001`（策略已存在，非虚构绑定） |
| `tests/unit/test_route_policy.py` | 26 用例 |
| `tests/unit/test_activation_plan.py` | 9 用例 |

### 分工（避免双权威）

- **RoutePolicy** 持有「任务 → 地图」的**路由**（输入、优先级、理由）；
- **KnowledgeMap** 持有「地图 → 资产/Skill」的**激活面**（`assetRefs` / `skillRefs`）。

策略**不**复述资产与 Skill；地图**不**复述路由规则。二者通过 `knowledgeMapId` / `routePolicyRef` **双向校验**。

## 2. 命令与结果（原始退出码）

| # | 命令 | 退出码 | 结果 |
|---|---|---|---|
| 1 | `python3 -m pytest tests/unit/test_route_policy.py tests/unit/test_activation_plan.py -q` | **0** | `35 passed` |
| 2 | `python3 -m pytest tests/unit -q` | **0** | 单元测试全量通过（含前一步 28 例，无回归） |
| 3 | `python3 -m ruff check src/ tests/` | **0** | `All checks passed!` |

## 3. 变异自证（证明断言非空转）

原始日志：`evidence/m7-3/route-policy-plan-mutation-*.log`

| 变异 | 施加方式 | 变异后 | 恢复后 |
|---|---|---|---|
| **M3** 默认拒绝未强制 | 删除「`defaultDecision` 必须为 `DENY`」校验 | **FAIL**：`test_policy_contract_violations[...只允许 'DENY']` | PASS |
| **M4** 跨引用错配未校验 | 删除「地图 `routePolicyRef` 与策略不一致 ⇒ 拒绝」 | **FAIL**：`test_map_declaring_other_policy_is_denied` | PASS |
| **M5** `plan_hash` 忽略资产 | 从 canonical content 移除 asset 行 | **FAIL**：`test_plan_hash_is_sensitive_to_every_deterministic_field` | PASS |

恢复后 sha256 与变异前一致：
`route_policy.py=fede756a1cdca5dd…`、`activation_plan.py=eae6eb913cbd263f…`。

## 4. 关键语义（写入代码与用例）

- **默认拒绝**：策略缺失（`ROUTE_POLICY_ABSENT`）、任务未映射（`ROUTE_NOT_MAPPED`）、
  地图未注册（`ROUTE_MAP_UNKNOWN`）、策略错配（`ROUTE_MAP_POLICY_MISMATCH`）—— 一律**不产出计划**；
  注册表仍可单独查询（`resolve_via_registry_only`）仅供诊断，**不用于放行**。
- **歧义拒绝且爆炸半径最小**：同任务同优先级规则 ⇒ 该任务拒绝（`ROUTE_AMBIGUOUS`，附 candidates），
  **其余任务照常路由**。刻意**不**在解析期拒绝整份策略（否则一条歧义规则会让全部任务不可用）。
  另有 `RoutePolicy.ambiguous_task_types` 供运维诊断。
- **双侧一致性**：策略把任务路由到某地图时，该地图必须**也**声明该任务，否则拒绝。
- **可重放**：`plan_hash` = sha256(canonical content)[:16]，输入仅含
  schema/任务/策略键/地图键/资产序列/Skill 集合（Skill 排序后入 hash）；
  **不含**主体、权限、时刻、planId、绝对路径。`plan_id` 由 hash 派生 ⇒ 同输入逐字段可重放
  （用例跨构建器实例比对 `to_dict()`）。
- **预留槽位不虚构**：`versions.activationContract` 与 `versions.ontology` 当前为 `None`，
  待后续切片按 D3-A 以「契约引用 + 内容哈希版本」填入，**不留占位串**。

## 5. 实施中发现并纠正的设计矛盾

初版在**解析期**就拒绝"同任务同优先级规则重复"，这会使 `RouteResolver.resolve` 的歧义分支成为
**死代码**，且与评审"歧义**拒绝**"的运行期语义不符、爆炸半径过大（一条坏规则令整份策略不可用）。
已改为：解析期放行 + 运行期按任务拒绝，并把重复检测做成诊断属性
`RoutePolicy.ambiguous_task_types`（有对应用例覆盖）。

## 6. 本步**未**做（后续切片）

1. **接线** `skills.py` 的三处硬编码 mapId → 注册表/策略（并处理"运行时工作区未配置地图"的
   供给问题，避免默认拒绝直接影响既有服务）；
2. HTTP 端点（`/api/knowledge-maps*`、路由/计划端点）与版本合同；
3. 本体引用（D3-A：只读消费 gits 本体 + 内容哈希版本）填入 `versions.ontology`；
4. 权限/工具快照（评审 §4.7 的"资产/Skill/**工具**/权限/版本快照"中，工具与权限尚为最小面）；
5. gits 侧 CTR-PLAN-001 的字段级对照（当前仅语义对齐，**未**做逐字段映射核对）。

## 7. 非声明

- 本证据**不是** `QA_PASS`、**不是**独立验证结论；**不**声明生产就绪、**不**声明 GITS UAT 通过；
- **不**引入 LightRAG（D2-A）、**不**内置 KERT 自有本体（D3-A）；既有 Kùzu / Parquet 形态未改动；
- 未改 `03_core` 权威资产、未改任何既有文件内容（仅新增 + 对新增地图文件回填一个字段）；
- 未 push（`AGENTS.md` 规则 #10）。
