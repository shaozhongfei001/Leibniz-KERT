# 证据：⑤b-full 实施（技能按计划读资产；计划被拒即拒绝执行）

```text
PACKAGE   : M7-3-5b-FULL（用户裁决："同意" ⇒ 按 P1 → P2 → 实施 ⑤b-full，且只做 (A)）
BRANCH    : feature/m7-3-knowledge-map-route（base 8b5fa99）
DATE      : 2026-09-16
ENV       : python3 3.10.12；ruff 0.16.4；docker compose 可用
```

## 1. 范围（只做 (A)）

| 子决策 | 本轮 |
|---|---|
**(A) 资产来源**：硬编码字面量 → **计划 `assets`**（= 地图 `assetRefs`，按 sequence） | ✅ **已实施** |
**计划被拒 ⇒ 拒绝执行**（fail-closed） | ✅ **已实施** |
**(B) `required` 强制**（必需资产缺失即拒绝） | ❌ **未实施** —— 与 v1.3"evidence ok/skipped 不阻塞执行"纪律冲突，属独立议题 |

## 2. 实现（`src/kert/application/skills.py`）

| 变更 | 说明 |
|---|---|
`_route_plan(trace, expected_map_id, task)` | 取代 ⑤b-light 的 `_trace_knowledge_map`：解析计划 → 记录 trace（`mapId`/`planHash`/`versions`/`assets`）→ **返回计划**；工作区未配置 / 解析异常 / 计划被拒 ⇒ **`SkillError`**，**不回落**任何硬编码 |
`_plan_assets(decision)` | 计划给定的资产序列（按 sequence） |
`_ki_title(ki_id)` | 编号 → 稳定标题（取自 `customer_knowledge.KI_ITEMS`，未知回落编号） |
`_ki_context(ki, only=...)` / `_ki_sections(ki, only=...)` | 上下文与章节按**计划资产**取，不再按全量契约顺序 |
`_run_outreach` / `_run_meeting` / `_run_previsit` | 三处改为 `assets = self._plan_assets(plan)` 驱动（原分别是 3 / 4 条字面量与"遍历全部 `_KI_ITEMS`"） |

**失败语义**：`status="skill_error"`、`data={}`（不留残缺数据）、
`errors[0].code="KERT_PERMISSION_DENIED"`，**具体路由拒绝码**在 `detail.routeCode`
（`ROUTE_*` / `KNOWLEDGE_MAP_*` / `ONTOLOGY_REFERENCE_*`），trace 保留 `blocked` 条目。

**错误码纪律**：合同里的错误码列表是**说明文本**（非 enum），但我**未**为本次接线新增
`ROUTE_*` 错误码 —— 用既有的 `KERT_PERMISSION_DENIED`（"权限不允许"）承载，具体码放 `detail`，
避免单方面扩合同面。

## 3. 测试面更新（实跑驱动的清单，非猜测）

| 文件 | 处理 |
|---|---|
`tests/conftest.py` | 新增 `ws_provisioned` 夹具（= `ws` + 供给控制面） |
`tests/integration/test_skills.py` | 夹具 `svc` / `ws_seeded` / `client` 改用 `ws_provisioned`；注册表期望补 `SP-15` 并把版本断言改为**逐技能钉版本**（`SP-15=2.0.0-candidate` 已有专门用例覆盖） |
`test_persistent_jobs.py` / `test_prod_async_guard.py` / `test_redaction.py` / `test_runtime_store_api.py` | 各加**文件内遮蔽** `ws` 夹具（4 行）→ 该文件全部用例获得已供给工作区。这 4 个文件正是影响面分析里"用变量传 skillId、字面 grep 测不到"的那类 |
`test_skill_routing_trace.py` | 未供给 / 无工作区 / 本体引用非法三例改为**拒绝**语义；新增"被拒时不得读取任何 KI"断言 |
`test_control_plane_consistency.py` | 改用已供给工作区；**新增 `test_plan_drives_reads_not_source_literals`** |

### 3.1 为什么必须新增"改地图看跟随"的用例（(A) 的核心证明）

⑤b-full 之后，"地图 `assetRefs` == 技能读取集"在受控工作区上变成**结构必然**（技能读的就是
计划给的资产）⇒ 原有的**相等断言已无法证明"读取来源是计划"**。

变异 **M1**（把 `_plan_assets` 退回硬编码 3 条）实测：**受控工作区的相等用例仍然全绿**，
只有 `test_plan_drives_reads_not_source_literals`（改地图 assetRefs → 观察技能跟随）变红。
∴ 该用例是 (A) 的唯一有效证明，不是重复劳动。

## 4. 命令与结果（原始退出码）

| 命令 | 退出码 | 结果 |
|---|---|---|
| `pytest tests/unit tests/integration` | **0** | **1291 passed, 1 skipped, 1 xfailed** |
| `ruff check src/ tests/`（0.16.4） | **0** | `All checks passed!` |
| `pytest tests/integration/test_control_plane_consistency.py`（collect） | 0 | **8 例**（原 7 + (A) 证明） |
| `docker compose -f deploy/docker-compose.yml config --quiet` | **0** | `COMPOSE_CONFIG=OK` |

## 5. 变异自证（三项，基线 PASS → 变异 FAIL → 恢复 PASS）

日志：`evidence/m7-3/5b-full-mutation-*.log`；恢复后 `skills.py=223a09592313ebbb`。

| 变异 | 施加方式 | 变异后 FAIL 的用例 |
|---|---|---|
| **M1** 资产来源退回硬编码 | `_plan_assets` → 返回固定 3 条字面量 | `test_plan_drives_reads_not_source_literals`（**唯一变红者**）+ meeting/previsit 相等用例 |
| **M2** 拒绝时不写 trace | 删拒绝分支的 `trace.append` | 未供给拒绝用例、本体引用拒绝用例、canonical schema 校验用例 |
| **M3** 拒绝码写错 | `KERT_PERMISSION_DENIED` → `SKILL_EXECUTION_FAILED` | 未供给拒绝用例、本体引用拒绝用例 |

恢复后 `18 passed`（两个文件合计）。

## 6. P2 运行时验证（**已在真实容器上完成**）与过程抓到的 5 个问题

### 6.1 端到端实测结果

```text
docker compose ... up -d
  kert-provision Exited(0) → kert-api Started → Healthy → kert-worker Started   ← 依赖链生效
  /livez 200 ； /readyz 200

GET /v1/knowledge-maps   → count=3，policy=RP-KERT-BANKFRONT-001
  maps = KM-CORP-RM-MEETING@1.0.0 / KM-CORP-RM-OUTREACH@1.0.0 / KM-CORP-RM-PREVISIT@1.0.1

POST /api/skill/execute（三个技能，真实 HTTP）
  skill-customer-outreach-script  ok  map=KM-CORP-RM-OUTREACH        assets=3  planHash=62f8b1b77cb756e2
  skill-customer-meeting-script   ok  map=KM-CORP-RM-MEETING         assets=4  planHash=63a4587256927d71
  skill-customer-previsit-report  ok  map=KM-CORP-RM-PREVISIT@1.0.1  assets=7  planHash=b2883f87d8119f85

provision 复跑 → 新建 0 / 覆盖 0 / 未变 5（幂等；工作区卷跨轮保留）
```

⇒ **P2**（供给并入启动链）与 **⑤b-full**（技能按**计划**资产读取，3/4/7 与地图逐条一致）均在
真实部署形态下得到验证。

⚠ **端口冲突的处置**：8106 被**另一个正在服务的 KERT 实例**（`deepseek_harness/data_knowledge_ws/dkws`，
非本仓、非我启动）占用。**未停它**；改用 compose 覆盖文件把发布端口映射到 8107 完成验证，
`deploy/docker-compose.yml` 未因此改动。验证后已 `down`，无残留容器。

### 6.2 抓到的 5 个问题（**均已修**）

| # | 问题 | 处理 |
|---|---|---|
| 1 | **`.gitignore` 漏了 `deploy/.env`**，而 `.env.example`/README 却声称"已在 .gitignore 中" —— 含**真实 API Key** 的文件对 git 可见 | 补 `.gitignore`；`git check-ignore` 验证；属**安全相关**的"声明与事实相反" |
| 2 | 容器内拉 `pyarrow` 失败（`from versions: none`）—— 宿主 pip 走清华源，容器内没有这份配置 | 加 `ARG PIP_INDEX_URL`（**默认空 ⇒ 行为不变**）；实测 340s 失败 → **13.3s 成功** |
| 3 | 容器内 apt 拉 deb 包极慢（541s 仅 ~500KB） | 加 `ARG APT_MIRROR`（默认空 ⇒ 行为不变） |
| 4 | `kert provision` 要求目标工作区**已初始化**，而容器首次部署是**空卷** ⇒ provision exit 1 | CLI 增 `--init`（未初始化则 init；已初始化 no-op；**非空且未初始化仍报错**）；编排改 `--init`；补 3 个 CLI 用例 |
| 5 | 我上一轮写进 `deploy/README.md` 的验证命令写 `X-API-Key: <key_id>:<secret>`，实际**只需 secret** | 修正 README 并注明依据 |

> 第 4 条同时暴露一个**既有部署缺口**：此前无 init 步骤，服务是在**未初始化**工作区上跑起来的
> （`/livez` 不检查工作区，故长期看不出来）。现已由 `provision --init` 补上。
> 第 2、3 条是**可选、默认不改行为**的构建期参数，动机是让本环境的构建可完成。

## 7. 非声明

- 本证据**不是** `QA_PASS`、**不是** Contract Owner 批准、**不是**部署验收；
- **不**声明 ⑤b-full 已可在未供给环境安全上线 —— 恰恰相反：**部署侧必须先完成供给**（P2），
  否则三个技能会 fail-closed 拒绝；这正是把供给并入启动链的原因；
- (B) `required` 强制**未实施**；未改合同、未改 `03_core`、未改 GITS 仓；未 push（规则 #10）；
- `PRODUCTION_RELEASE_GATE=BLOCKED` 不变；不代表 GITS UAT 通过。
