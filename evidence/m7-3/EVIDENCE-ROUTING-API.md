# 证据：知识路由 API（M7.3 第四步 —— 合同先行）

```text
PACKAGE     : M7-3-4-CONTRACT-ROUTING-API（合同变更提案 evidence/m7-3/CONTRACT_CHANGE_PROPOSAL_ROUTING_API.md）
AUTHORITY   : docs/governance/KERT_PENDING_OWNER_DECISION_M7_EVOLUTION_V1.0.md §0（D1-A）
              独立评审 §4.7（版本合同 + 可重放计划）
BRANCH      : feature/m7-3-knowledge-map-route（base = 559c317）
DATE        : 2026-09-15
ENV         : python3 3.10.12；ruff 0.16.4（= ci.yml:49）；pydantic 2.13.4；fastapi 0.141.1
```

## 1. 顺序（合同先行，未颠倒）

1. 出**变更提案** → 2. 改**合同** `specs/kert-openapi-v1.yaml`（`1.4.0 → 1.5.0`，**纯新增**）
→ 3. 自检合同可解析/引用完整 → 4. 改**实现** `src/kert/api/server.py` → 5. 加**集成测试** → 6. 变异自证。

## 2. 交付文件

| 文件 | sha256（前 16） | 说明 |
|---|---|---|
| `specs/kert-openapi-v1.yaml` | — | `version 1.5.0`；新 tag `Routing`；3 条新路径；8 个新 schema |
| `src/kert/api/server.py` | `430a918edd8bd698` | 3 个端点 + `RoutingPlanRequest`（`extra="forbid"`） |
| `tests/integration/test_routing_api.py` | — | **14 例** |
| `evidence/m7-3/CONTRACT_CHANGE_PROPOSAL_ROUTING_API.md` | — | 变更提案（含 7 项设计决定与理由） |

**新增端点**（全部 additive，既有端点/字段/错误码**零改动**）：

| 方法 | 路径 | 语义 |
|---|---|---|
| GET | `/v1/knowledge-maps` | 列出注册地图 + 策略版本；未注册 ⇒ **空列表**（不报错） |
| GET | `/v1/knowledge-maps/{mapId}` | 单张详情；未注册 ⇒ **404**（协议级资源不存在） |
| POST | `/v1/routing/plan` | 路由裁决 + 激活计划；**拒绝也是 200**（`allowed=false` + `denial`），无第三态 |

## 3. 命令与结果（原始退出码）

| # | 命令 | 退出码 | 结果 |
|---|---|---|---|
| 1 | `python3 -m pytest tests/integration/test_routing_api.py -q` | **0** | `14 passed` |
| 2 | `python3 -m pytest tests/unit tests/integration` | **0** | **1259 passed, 1 xfailed**（无回归） |
| 3 | `python3 -m ruff check src/ tests/` | **0** | `All checks passed!` |
| 4 | 合同自检（`yaml.safe_load` + `$ref` 完整性 + 字段集） | 0 | `version 1.5.0`；3 新路径；未定义引用 **无** |

## 4. 变异自证（三项，均为"基线 PASS → 变异 FAIL → 恢复 PASS"）

日志：`evidence/m7-3/routing-api-mutation-*.log`

| 变异 | 施加方式 | 变异后 FAIL 的用例 |
|---|---|---|
| **M1** 路由忽略拒绝 | `if isinstance(decision, PlanDenial):` → `if False:` | `test_unmapped_task_is_denied_with_200`、`test_unprovisioned_workspace_lists_empty_and_denies` |
| **M2** 取消严格字段 | 删除 `model_config = ConfigDict(extra="forbid")` | `test_unknown_request_field_is_rejected` |
| **M3** 实现多发未声明字段 | `to_dict()` 增 `undeclaredField` | `test_activation_plan_contract_matches_implementation_field_for_field` |

恢复后两文件 sha256 与变异前一致（`server.py=430a918edd8bd698`、`activation_plan.py=d0947461328da319`）。

**M3 是"合同先行"的兑现检查**：合同与实现任一侧改字段而另一侧未跟 ⇒ 该用例变红。

## 5. 关键设计决定（细节与理由见提案 §2）

- **改运行中权威**（v1，`1.4.0→1.5.0`）而非 v2 候选（v2 自述"未批准"）；
- **路径前缀 `/v1/*`**（与既有知识服务面一致）、**复用 `_response()` 信封**；
- **拒绝 = 200 + `denial`**：拒绝是**预期业务结果**，与基础设施错误区分；`allowed` 无第三态；
- **未知 mapId = 404**：协议级资源不存在，与被拒计划语义不同；
- **合同字段集 ↔ `to_dict()` 逐字段相等**（机械核对，防空转）。

## 6. 未做（后续）

1. **v1 ↔ v2 归并**（双权威风险；需 Contract Owner 立项，建议列入 W8/Phase 0 收口）；
2. **`/api/skill/*` 面未接线**：第五步（把 `skills.py` 三处硬编码 mapId 接注册表）**未做**；
3. 运行时工作区**供给**（`bank_front_ws`）未做 ⇒ 该工作区目前 `count=0` 且路由**默认拒绝**（预期行为）；
4. 鉴权作用域未细分（沿用全局 `ApiKeyAuth`，未新增 scope 语义）；
5. 合同的 `openapi` 校验仅做**结构级**（无第三方 validator 引入）。

## 7. 非声明

- 本证据**不是** `QA_PASS`、**不是** Contract Owner 批准；**不**声明合同已追认；
- **不**声明生产就绪、**不**声明 GITS UAT 通过；**不**声称跨仓集成已验收；
- 未引入 LightRAG（D2-A）、未内置 KERT 自有本体（D3-A）；未改 `03_core` 权威资产；
- 未修改 GITS 仓；未 push（`AGENTS.md` 规则 #10）。
