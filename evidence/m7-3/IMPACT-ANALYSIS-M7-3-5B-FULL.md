# ⑤b-full 影响面分析（技能按计划读资产 / 计划拒绝即拒绝执行）

```text
STATUS      : ANALYSIS_ONLY —— **只读分析，未改任何代码/合同/工作区**
DATE        : 2026-09-15
SCOPE       : M7.3 第五步 b-full（⑤b-light 已完成：仅 trace 可观测性）
BRANCH      : feature/m7-3-knowledge-map-route @ 4612e08
AUTHORITY   : 用户指令"给 ⑤b-full 影响面分析"
```

## 0. 结论摘要

1. ⑤b-full **不是**"无副作用接线"：它同时改动 ①资产来源 ②拒绝语义；其中 **PREVISIT 存在地图定义缺陷**，
   直接接线会让访前报告**从 7 个知识章节掉到 3 个** ⇒ **必须先修地图**（§6 P1）。
2. 受影响测试面**结构性上界**：**至少 35 个执行点**（`test_skills.py` 21 + `test_skill_routing_trace.py` 7 +
   e2e 7），横跨 7+ 个文件；**精确清单只能在实现后由一次全量跑给出**（§4 不提供伪精确数）。
3. 生产面**本仓无从验证**：部署工作区未供给时三技能**全部拒绝**；GITS 调用面受影响（§5）。

## 1. ⑤b-full 的确切语义（**两个必须分开的子决策**）

| 子决策 | 内容 | 性质 |
|---|---|---|
| **(A) 资产来源** | 硬编码 KI 列表 → 计划 `assets`（= 地图 `assetRefs`） | **来源替换**（可做等价性证明） |
| **(B) `required` 强制** | `required: true` 的资产在知识库缺失时，是否**拒绝执行** | **权限升级**（语义扩大） |

⚠ **B 与既有纪律冲突**：v1.3 明示"evidence 的 ok/skipped 只反映知识库对该客户+KI 是否取到数，
**不阻塞**执行"（`docs/skill-execute-api-contract-v1.4.md`）。若 B 一并实施，**未知客户**的
outreach/meeting 会从"带 skipped 证据出报告"变成**拒绝** —— 这是产品行为变更，不是实现细节。

> **建议：⑤b-full v1 只做 (A) + "计划被拒 ⇒ 拒绝执行"**（fail-closed 落在**路由/权限**层），
> (B) 单独立项、由域 Owner 决定。

## 2. 逐技能一致性核对（**实测**，非推测）

| 技能 | 代码实际读取（`src/kert/application/skills.py`） | 地图声明 `assetRefs` | 结论 |
|---|---|---|---|
| `skill-customer-outreach-script` | KI-009 / KI-FRONT-004 / KI-FRONT-006（`:696-700`） | 同 3 条 | ✅ **逐条等价** |
| `skill-customer-meeting-script` | KI-009 / KI-FRONT-004 / KI-FRONT-005 / KI-FRONT-006（`:728-733`） | 同 4 条 | ✅ **逐条等价** |
| `skill-customer-previsit-report` | **全部 `_KI_ITEMS` = 7 条**（`:762-765` 遍历） | **仅 3 条**（KI-FRONT-001/002/003） | ❌ **不一致（7 vs 3）** |

## 3. 发现的真实缺陷（我在步骤①引入）：`KM-CORP-RM-PREVISIT` 地图

**证据链**：

- `src/kert/application/customer_knowledge.py:20-28` → `KI_ITEMS` = **7 条**（KI-009、KI-FRONT-001…006）；
- `src/kert/application/skills.py:764` → `for kid, name in self._KI_ITEMS:` ⇒ `_run_previsit` **遍历全部 7 条**；
- `examples/bank-front-knowledge-maps/90_control/catalog/KM-CORP-RM-PREVISIT.json` → 只声明 **3 条**；
- 该地图 `notes` **自称**："assetRefs 与 skills.py 中 `_run_previsit` 实际读取的 KI 条目一致
  （KI-FRONT-001 / 002 / 003）" —— **该自述为假**；
- 这 3 条恰是 `_run_supply_chain`（`skills.py:795` 起，产出 `bank-front-supply-chain-graph`）读取的集合
  ⇒ 疑似**抄错来源**。

**若先做 ⑤b-full 再修地图的后果**：访前报告丢掉 4 个知识章节 —— KI-009（企业客户基本信息）、
KI-FRONT-004（事实承诺/沟通话术）、KI-FRONT-005（KYC 信息缺口）、KI-FRONT-006（产品候选组合）；
并直接打破 `test_previsit_sections_per_ki`（断言 7 章节）、`test_previsit_ki_all_ok_from_library`（断言 7 条命中）。

**处置**：列为**前置修正项 P1**（§6）。修正时**不要**再写"与代码一致"这类**会腐烂的断言式 notes**，
改为机械核对用例（§6 P1）——文档写的"一致"没人会去验，测试写的"一致"会自己变红。

## 4. 受影响测试面（结构性上界）

| 文件 | 执行点 | 用例数 | 说明 |
|---|---|---|---|
| `tests/integration/test_skills.py` | **21** | 28 | 主战场（技能 3 个 + KI 级 trace 断言） |
| `tests/integration/test_skill_routing_trace.py` | **7** | 10 | ⑤b-light 新增；已有"未供给⇒blocked"用例，口径需随 ⑤b-full 调整 |
| `tests/e2e/test_all_skills_execution.py` | **3**（parametrize 13 skills） | 3 | **CI 内跑**（`ci.yml:225`，`KERT_PROFILE=dev`，服务维度 require ⇒ 缺服务即 fail） |
| `tests/e2e/kert_api_validation.py` | **4** | 7 | CI 内 e2e |
| `test_redaction.py` / `test_runtime_store_api.py` / `test_prod_async_guard.py` / `test_persistent_jobs.py` / `security/test_api_hardening.py` | 字面命中 0，但**调用服务/端点** | 25/20/20/19/— | 用变量传 `skillId` ⇒ 字面 grep **测不到**，须以实跑为准 |

> ⚠ **上界 ≠ 精确**：精确受影响清单**只能在实现后由一次全量 `pytest` 给出**。
> 本分析**不提供**伪精确数字 —— 那会制造"已验证"的错觉。

## 5. 生产 / 跨仓影响（**本仓无从验证，须部署侧确认**）

- 部署工作区（如 `bank_front_ws`）**不在本仓**；未执行 `kert provision` 时 **3 个技能全部拒绝**；
- GITS 侧调用面（既有"P05/P38 须走 KERT Skill"口径，见冲突登记 **C-12**）会受影响；
  **我未访问、未修改 GITS 仓**，无法在此验证其调用清单与 UAT 用例覆盖；
- 因此：**⑤b-full 的发布前置是部署侧先供给**，不是代码先合。

## 6. 前置条件清单（未满足则**不得**开工）

| ID | 前置条件 | 验收方式 |
|---|---|---|
| **P1** | 修正 `KM-CORP-RM-PREVISIT.assetRefs` → 与 `_run_previsit` 真实读取（7 条）对齐；改正/删除错误 `notes` | 新增**机械核对用例**：逐技能断言「地图 assetRefs == 技能实际读取集」 |
| **P2** | 部署侧对所有运行时工作区执行 `kert provision`（⑤a 已提供入口） | 留存 `90_control/catalog/provision_manifest.json`（含逐项 sha256） |
| **P3** | 明确 (B) `required` 口径（域 Owner 决策）；建议**不在 v1 实施** | 决策登记 |
| **P4** | 受控工作区上的**等价性证明**：同一 `customerId` 下新旧路径产出同一资产集/context | OUTREACH、MEETING 现在即可证；PREVISIT 须 P1 完成后才可证 |

## 7. 实施与回滚方案

- **实施面**：仅 `skills.py` 三处资产来源 + "计划被拒 ⇒ 拒绝执行"分支；trace 继续携带
  `planHash`/`versions` 作为可核验证据（⑤b-light 已铺好）。
- **等价性证明**：新增用例断言「计划 `assets` == 技能原硬编码读取集」，失败信息指向**地图定义**而非技能。
- **回滚**：`git revert <单 commit>` 单点回退；**无迁移、无数据变更**；回滚后 trace 仍留历史 `planHash`。
- **推荐节奏**：P1 → P2 → ⑤b-full → 观察一个发布周期 → 再议 (B)。

## 8. 三个口径对比

| 口径 | 内容 | 代价 |
|---|---|---|
| **纯 fail-closed（推荐）** | 只做 (A) + 计划被拒⇒拒绝执行；`required` 不升级 | 未供给工作区三技能拒绝 ⇒ **必须先 P2** |
| 分阶段 | 先 (A)，观察后再议 (B) | 无额外代价；(B) 延后 |
| 过渡开关（env 允许回落硬编码） | 保留旧读取路径 | ⚠ 违反"**没有第三态**"纪律：会把拒绝**掩盖成正常路径** ⇒ **不建议** |

## 9. 非声明

- 本分析**不是**实施授权、**不是** QA 结论、**不是** Contract Owner 批准；**未改任何代码/合同/工作区**；
- 未访问或修改 GITS 仓；受影响测试面为**结构性上界**，精确值须实跑；
- (B) `required` 口径**未决策**；**P1 缺陷尚未修复**（当前仍在受控 example 中）；
- `PRODUCTION_RELEASE_GATE=BLOCKED` 不变；不代表 GITS UAT 通过。
