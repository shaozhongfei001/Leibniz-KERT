# 证据：e2e 打通（用本仓编排拉起服务跑 `tests/e2e/`）

```text
TASK_ID   : M7-VERIFY-E2E-STACK-UP
角色       : 验证打通工程师（e2e-stack-up）
仓         : Leibniz-KERT（/home/szf/dev/Leibniz-KERT）
分支       : feature/m7-3-knowledge-map-route
开工 HEAD  : 8a9d8f1（开工时实测；收工期间 HEAD 已被并行队友推进到 62b967a）
时间       : 2026-09-16 00:45 ~ 00:53（+08:00）
环境       : docker 可用；docker compose v5.1.4；.venv python 3.12.8（pytest 9.1.1 / httpx 0.28.1）
覆盖口径   : 47 收集 = 26 真跑（KERT 侧）+ 21 skip（跨服务，GITS :8082 / :5173 不可用）
结论       : **打通**。一条命令可复现：`bash scripts/run_e2e_local.sh` → 退出码 0
```

## 0. 结论摘要（TL;DR）

| 项 | 结果 |
|---|---|
| 起栈（本仓 `deploy/docker-compose.yml` + 端口覆盖） | 成功，退出码 **0**（`/livez` 200、`/readyz` 200、`/v1/knowledge-maps` **count=3**） |
| `pytest tests/e2e/ -rs`（`E2E_REQUIRE_KERT=1`） | **26 passed, 21 skipped, 0 failed, 0 errors**，退出码 **0** |
| 与 CI 口径一致性 | 与 `.github/workflows/ci.yml` e2e job 声明的 **26/47 真跑、21/47 未覆盖** 逐条吻合（下限 26 = 无服务 1 + 仅 KERT 25；上限 21 = 跨服务 21） |
| 撤栈 | `down --remove-orphans` 退出码 **0**，残留 kert 容器 **0**，卷 `kert_workspace`/`kert_backups` 保留 |
| 途中发现并处置 | ①**镜像缓存层陈旧**致 provision exit 2（起栈失败）；②**e2e 无鉴权通道**致 21 条 401（本仓缺陷） |

## 0.5 证据绑定（可复现性边界，务必先读）

| 项 | 值 |
|---|---|
| 实际运行的镜像 | `kert-python-core:local` = `sha256:6ad0b85e092e8e8356f9fcc11d5f7968ea30500dff0c8b6ba070671e6798d9f3`（created 2026-09-16T00:35:32+08:00，重建后 tag 实测指向它） |
| 内容绑定判据 | 镜像内 `/app/src/kert/cli/main.py` md5 = `09eeb508e85bc059fb83e67763d2164c` **= 当时工作区** `src/kert/cli/main.py`；（陈旧镜像该值为 `45626eb1972f8239438ed783f21821dd`） |
| 镜像**不含** | 并行队友（M7-1 知识源）后加入的 `src/kert/domain/knowledge_source.py`、`examples/bank-front-knowledge-maps/90_control/schema/knowledge_sources.json`（镜像内 `ls` 实测无此文件） |
| 会话期仓内推进 | HEAD `8a9d8f1` → `62b967a`（并行队友提交），我的改动**全部未提交** |

两点推论（避免把本次结论读大）：

1. `COPY src ./src` 复制的是**工作区**（含未提交改动）⇒ "镜像内容 ≠ HEAD" 是常态；
   复现时请用 `docker run --rm --entrypoint sh kert-python-core:local -c 'md5sum /app/src/kert/cli/main.py'`
   与工作区比对来绑定，**不要**用"镜像已存在"判断可复用（这正是 §3 的坑）。
2. 本次 26 条通过是在"M7.3 收口"镜像上取得的，**不**包含 M7-1 知识源改动；
   ⇒ 该结论**不能**被援引为"M7-1 知识源链路已验证"，也**不因** M7-1 新增文件而失效。
   本证据失效条件：`deploy/docker-compose.yml`、`deploy/Dockerfile`、`tests/e2e/conftest.py`、
   `scripts/run_e2e_local.sh` 任一变动，或 M7-1 知识源改动进入运行镜像后重跑——**须重测**。

## 1. 环境事实与边界遵守

| 事实 | 实测 |
|---|---|
| 8106 被**另一个** KERT 实例占用（非本仓、非本任务可停） | `curl :8106/` → 404 uvicorn；`:8106/api/skill/health` → 200，`{"service":"customer-engagement",...}`；本任务**全程未触碰** |
| 释放冲突的方式 | compose **覆盖文件** `/tmp/e2e-override.yml`（`ports: !override` → `127.0.0.1:8107:8106`），`deploy/docker-compose.yml` **一个字节未改** |
| 依赖链保留 | `config` 实测：`provision → 无`；`api → provision: service_completed_successfully`；`worker → provision + api: service_healthy` |
| `deploy/.env` | 已存在（含真实 Key），**未提交**、**未打印明文**；`PIP_INDEX_URL`/`APT_MIRROR` 保留未动 |
| 8107 在我起栈前 | 空闲（`curl` 000 / 连接拒绝） |

**硬性边界核对**：`deploy/docker-compose.yml` 未改（`git diff --stat` 中无此文件）；`src/**` 未改；未停/未干扰 8106 实例；未执行 `down -v`（卷保留，见 §9）；未 push。

## 2. 命令序列与**原始退出码**

| # | 命令 | 退出码 | 结果 | 日志 |
|---|---|---|---|---|
| 1 | `docker compose -f deploy/docker-compose.yml -f /tmp/e2e-override.yml --env-file deploy/.env config` | 0 | `published: "8107"` / `target: 8106`；依赖链完整 | — |
| 2 | （同参数）`up -d`（**首次**） | **1** | `Container kert-provision Error service "provision" didn't complete successfully: exit 2` | `e2e-stack-up-01-first-up-fail.log` |
| 3 | `docker logs kert-provision` | 0 | `No such option: --init`（Typer 用法错误） | 同上 |
| 4 | `docker run --rm --entrypoint sh kert-python-core:local -c 'grep -n init_if_needed /app/src/kert/cli/main.py'` | **1** | 0 命中 ⇒ 镜像内 CLI **缺** `--init`；镜像内 `main.py` 641 行 md5 `45626eb1…`，仓库 `src/kert/cli/main.py` 656 行 md5 `09eeb508…` | §3 |
| 5 | （同参数）`build` | 0 | 层重建完成，tag 指向的镜像 `main.py` md5 变为 `09eeb508…`（**与仓库一致**） | `e2e-stack-up-02-image-build.log` |
| 6 | （同参数）`down --remove-orphans` | 0 | 清掉失败容器 | — |
| 7 | （同参数）`up -d`（**重建后**） | **0** | `kert-provision Exited`(→ exit 0) → `kert-api Healthy` → `kert-worker Started` | `e2e-stack-up-03-up-ok.log` |
| 8 | `docker inspect kert-provision --format '{{.State.ExitCode}}'` | 0 | `0`；供给结果 `地图: 3`、`新建 0 / 覆盖 0 / 未变 5`（幂等） | 同上 |
| 9 | `curl /livez`、`/readyz`、`/v1/knowledge-maps`、`/api/skill/health` | 0 | 见 §4 | `e2e-stack-up-04-probes.log` |
| 10 | `KERT_BASE_URL=:8107 E2E_REQUIRE_KERT=1 pytest tests/e2e/ -rs`（**未带 Key**） | **1** | `21 failed, 5 passed, 21 skipped` —— 21 条全为 **401 UNAUTHENTICATED** | `e2e-stack-up-05-pytest-fail-no-apikey.log` |
| 11 | 修 `conftest.py` 后同命令（`KERT_API_KEY=<secret>`） | **0** | `26 passed, 21 skipped`，账本 `violations=[]` | `e2e-stack-up-06-pytest-pass-with-apikey.log` |
| 12 | `bash scripts/run_e2e_local.sh --ledger …`（一条命令：起栈→判据→e2e→撤栈） | **0** | 同上，且自动撤栈、残留 0 | `e2e-stack-up-07-one-command.log` |
| 13 | `bash scripts/run_e2e_local.sh --keep-up …`（复跑，验证幂等）+ 鉴权矩阵 | **0** | `26 passed, 21 skipped`；鉴权矩阵见 §5 | `e2e-stack-up-09-auth-matrix-and-rerun.log` |
| 14 | （同参数）`down --remove-orphans`（**最终撤栈**） | 0 | 残留 kert 容器 **0**；卷保留 | `e2e-stack-up-10-teardown.log` |

## 3. 阻断 ①：镜像缓存层陈旧 ⇒ 起栈硬失败（已定位并修复，**无仓内改动**）

**现象**：首次 `up -d` 退出码 1，`provision` exit 2 —— 报 `No such option: --init`。
**排查链**（不是"环境问题"，有确定判据）：

1. 仓库源 `src/kert/cli/main.py:110-112` **有** `--init`（`init_if_needed: bool = typer.Option(False, "--init", …)`），
   `deploy/docker-compose.yml:47` 与 `deploy/README.md:107` 也是按"有 `--init`"写的；
2. 镜像 `kert-python-core:local` 内 `/app/src/kert/cli/main.py` **没有** `--init`（grep 0 命中，641 行 vs 仓库 656 行）；
3. 但镜像内 `/app/src/kert/application/provision.py` 与仓库**逐字节相同**（md5 `c01b55cf…`）⇒ 不是"整体旧提交"，
   而是 **`COPY src ./src` 层命中了陈旧构建缓存**（`docker compose build` 首次即报全 `CACHED`）；
4. tag 当时指向陈旧产物（`docker images` 中 4 分钟前构建的 `01490d7469e4`）。

**处置**：重新 `docker compose build`（**重建派生制品**，未改任何仓内文件），随后 tag 指向的镜像
`/app/src/kert/cli/main.py` md5 = `09eeb508…` = 仓库现状，`grep -c init_if_needed` = 2；起栈成功（退出码 0）。

> 这就是任务包"镜像可能已存在 ⇒ `up -d` 不会重建，可直接复用"前提下的**陷阱**：可复用与否不能靠"镜像存在"判断，
> 要靠"镜像内容与工作区一致"。已在 `scripts/run_e2e_local.sh` 里把它变成**可诊断**而非**难诊断**：
> `up` 失败时自动打印 provision 日志并提示 `E2E_REBUILD=1`。

## 4. 就绪判据实测（原始输出）

```text
GET /livez              -> HTTP=200  {"status":"alive","service":"kert-python-core","service_version":"1.0.0",...}
GET /readyz             -> HTTP=200  {"status":"ready","degraded":["knowledge_projection"],
                                       "checks":{"workspace":{"ok":true,"path":"/data/workspace"},
                                                 "knowledge_projection":{"ok":false,"blocking":false},
                                                 "runtime_store":{"ok":true,"schema_version":2,"journal_mode":"wal"},
                                                 "job_queue":{"ok":true,"claimable":0,"dead_letter":0,"expired_leases":0}}}
GET /v1/knowledge-maps  -> HTTP=401（无 Key）
GET /v1/knowledge-maps  -> HTTP=200  data.count=3
                            mapIds = KM-CORP-RM-MEETING / KM-CORP-RM-OUTREACH / KM-CORP-RM-PREVISIT
GET /api/skill/health   -> HTTP=200  skill_count=13
                            （含 7 个 bank-front-*：commitment-script / eight-dimension / fact-reconciliation /
                              kyc-gap-check / product-recommendation / report-assembler / supply-chain-graph）
```

- **控制面供给生效**：`count=3 > 0`（若为 0 表示 provision 未生效、路由将 fail-closed 全拒绝 —— 那时跑 e2e 等于验证空壳）。
- `provision` 日志显示 `新建 0 / 覆盖 0 / 未变 5`（3 张地图 + `route_policy.json` + `ontology_reference.json`）：
  卷此前已供给过，本次为**幂等 no-op**，符合设计。
- `/readyz` 的 `degraded:["knowledge_projection"]`（`blocking:false`）是**预期**：本工作区无 `product_knowledge` 活动投影，
  该依赖按设计非阻塞；与本次 e2e 结论无关。

## 5. 鉴权口径（实测矩阵，非转述）

| 请求头 | HTTP |
|---|---|
| 无 `X-API-Key` | **401** |
| `X-API-Key: gits-caller:<secret>`（即 `key_id:secret`） | **401** |
| `X-API-Key: <secret>`（**密钥本身**） | **200** |
| `X-API-Key: <48 位错误值>` | **401** |

⇒ 口径确认：**值必须是密钥本身（secret 段），不是 `key_id:secret`**；其余表单都 401。
这正是 §6 的 21 条失败的直接原因。

## 6. 阻断 ②：e2e 无鉴权通道 ⇒ 21 条 401（**本仓缺陷**，最小修复）

**现象**：`pytest tests/e2e/ -rs` → `21 failed, 5 passed, 21 skipped`，退出码 1；账本 `violations = ["failed=21（必须 0）", "passed=5 < 下限 26…"]`。
**归因**（逐条核过，无一条是"环境问题"）：21 条失败**全部**是同一个 401 ——

| 失败形态 | 条数 | 原始消息 |
|---|---|---|
| `POST /api/skill/execute` 401 | 18 | `Skill <id> 执行失败 401: {"error":{"code":"UNAUTHENTICATED","message":"缺少 API Key，请提供 X-API-Key 请求头","retryable":false}}` |
| `GET /api/skill/gates/...` 401 | 2 | `Gates 查询失败 401: …` |
| 其它 KERT 端点 401 | 1 | `KERT gates 端点返回 401: …` |

**根因**：`tests/e2e/conftest.py` 的 `kert_client` 夹具**从不携带任何凭据**。CI 之所以能过，是因为 CI 用
`KERT_PROFILE=dev` 起服务（`.github/workflows/ci.yml` e2e job），**无需鉴权**；而本仓编排
（`deploy/docker-compose.yml`）固定 `KERT_PROFILE=prod`（强制鉴权）。⇒ **"CI 能过"与"本仓编排能跑"本来就不是同一条路径**，
本任务正是要消掉这个缝。

**最小修复**（`tests/e2e/conftest.py`，行为向后兼容）：

```python
# 新增（模块级）
KERT_API_KEY = os.getenv("KERT_API_KEY", "").strip()

# kert_client 夹具
headers = {"X-API-Key": KERT_API_KEY} if KERT_API_KEY else {}
with httpx.Client(base_url=kert_ready, timeout=120, headers=headers) as client:
    yield client
```

- **未设置 `KERT_API_KEY` 时 `headers={}`，与既有行为逐字一致** ⇒ CI dev 口径不受影响
  （已用 `env -u KERT_API_KEY pytest tests/e2e/ --collect-only` 验证无副作用）；
- 只加"能带凭据"的能力，**不发明**任何新端点/字段语义；同步在模块 docstring 里登记该变量与"值须是 secret"。

**修复后**：`26 passed, 21 skipped`，退出码 **0**，账本 `violations=[]`。

## 7. 逐条失败归因（外部依赖缺失 vs 本仓缺陷）

### 7.1 本仓缺陷：0 条（修复后）

修复后 `failed=0, errors=0`。修复前那 21 条 401 **已归因为本仓缺陷**（§6，测试夹具无鉴权通道），**已修复**，不是环境问题。

### 7.2 外部依赖缺失：21 条（全部为 `skip`，逐条登记在覆盖账本）

**依赖 A：GITS Backend `http://127.0.0.1:8082/actuator/health` 不可达**（当前实测连接拒绝；GITS 属另一仓，起它需其自身 MySQL/依赖，**超出本任务范围**）—— 共 **20 条**：

| 文件 | 用例（行号） |
|---|---|
| `tests/e2e/test_cross_service_health.py` | `test_gits_backend_health`(21)、`test_all_services_simultaneously`(40) |
| `tests/e2e/test_gits_to_kert_integration.py` | `test_gits_calls_kert_skill_execute`(36)、`test_gits_kert_connectivity`(107) |
| `tests/e2e/test_scenario_1_continuous_operation.py` | `test_start_journey`(21)、`test_operating_view`(40)、`test_gate_state_via_gits`(60)、`test_full_engagement_loop`(95) |
| `tests/e2e/test_scenario_2_previsit_report.py` | `test_memory_extraction`(21)、`test_full_previsit_flow`(69) |
| `tests/e2e/test_scenario_3_service_proposal.py` | `test_generate_proposal_via_gits`(21)、`test_proposal_different_industry`(55)、`test_proposal_fact_labels`(102) |
| `tests/e2e/test_scenario_4_knowledge_graph.py` | `test_supply_chain_edges`(19)、`test_supply_chain_graph_via_gits`(47)、`test_supply_chain_node_types`(65) |
| `tests/e2e/test_scenario_5_customer_insight.py` | `test_customer_operating_view`(21)、`test_kyc_gap_analysis`(39)、`test_insight_gate_correlation`(57)、`test_full_insight_flow`(94) |

**依赖 B：GITS Frontend `http://127.0.0.1:5173` 不可达** —— 共 **1 条**：
`tests/e2e/test_cross_service_health.py::test_gits_frontend_reachable`(33)。

形态核对（账本）：`gits_only 16 + multi_end 5 = 21`；`skipped=21` 恰好等于上限，**无计划外跳过**。

### 7.3 "真实 LLM 凭据"依赖：**实测不构成任何 e2e 用例的前置**（推翻任务包里的悬置假设）

逐条核过的三条证据：

1. 容器内**无任何** LLM 凭据：`docker exec kert-api env | grep -iE 'llm|openai|deepseek|api_key'` 只命中
   `KERT_API_KEYS`（KERT 自身鉴权）与 `KERT_LLM_REDACTION=true`，**无模型 API Key**；
2. 技能返回体自带确定性标记：`POST /api/skill/execute`（`bank-front-eight-dimension`）→
   `"schemaVersion": "deterministic/1.0"`、`"status": "DETERMINISTIC_PLACEHOLDER"`，
   与 `src/kert/application/skills.py:9`「未配置外部模型时确定性适配器端到端（§1.6）」一致；
3. `grep -rn 'llm\|LLM' tests/e2e/*.py` → **0 命中** ⇒ e2e 用例没有任何显式模型断言/前置。

⇒ 26 条真跑用例**全部**走确定性适配器路径，**无需**真实 LLM 凭据；本任务**未**因模型凭据丢任何覆盖。

**如实登记的覆盖边界**（不是失败，是口径）：确定性占位意味着这 26 条验证的是"**可调用 / 结构 / 鉴权 / 路由**"，
**不**验证"模型输出内容正确性"。若要覆盖内容质量，需另立"带真实模型凭据的 e2e"，本任务不做、也不声称。

## 8. 一条命令的入口

新增 `scripts/run_e2e_local.sh`（可执行，`bash -n` 通过）：

```bash
bash scripts/run_e2e_local.sh                 # 起栈(8107) → 判据 → pytest → 撤栈，退出码透出
```

行为要点：

1. **不改编排语义**：端口冲突一律用**临时覆盖文件**（`mktemp` 目录内生成，`ports: !override`），
   `deploy/docker-compose.yml` 不动；起栈前做 **TCP 层**占用检查（端口有人监听即拒跑，避免踩他人实例）；
2. 等 `/livez`、`/readyz` 均 **200**，非 200 直接 fail（不继续、不用 skip 掩盖）；
3. **断言控制面 `count > 0`**（`/v1/knowledge-maps`），=0 即 fail —— 把"provision 没生效"从业务故障提前到打通阶段；
4. 跑 `pytest tests/e2e/ -rs`，环境为 `KERT_BASE_URL` + **`E2E_REQUIRE_KERT=1`** + `KERT_API_KEY` + `E2E_LEDGER_PATH`，
   **退出码原样透出**；
5. **`trap` 保证撤栈**（`down --remove-orphans`，**绝不 `-v`**），并打印残留 kert 容器清单；
6. `KERT_API_KEY` 优先取环境变量，否则从 `deploy/.env` 的 `KERT_API_KEYS` **首个 key 的 secret 段**解析
   （绝不回显明文）；`--no-stack --base-url` 可打已存在服务、`--keep-up` 可保留栈排查、`--` 之后参数原样传 pytest。

脚本自身可用性证据：`e2e-stack-up-07-one-command.log`（首次，退出码 0）、
`e2e-stack-up-09-auth-matrix-and-rerun.log`（复跑幂等，退出码 0）。

## 9. 撤栈与残留

```text
$ docker compose -f deploy/docker-compose.yml -f /tmp/e2e-override.yml --env-file deploy/.env down --remove-orphans
EXIT_CODE=0
残留 kert 容器数 = 0
卷仍保留：kert_workspace / kert_backups（**未用 -v**）
:8107 -> 连接拒绝（已释放）
:8106 -> 404（**他人实例未受影响**，/api/skill/health 仍 200）
```

## 10. 本任务造成的仓库改动清单（仅两处，均为"打通所需"）

| 文件 | 类型 | 内容 |
|---|---|---|
| `tests/e2e/conftest.py` | 修改（`19 insertions / 2 deletions`，`git diff --numstat`） | 新增可选 `KERT_API_KEY` → 注入 `X-API-Key`；docstring 登记该变量与"值须是 secret"。未设置时行为不变 |
| `scripts/run_e2e_local.sh` | **新增**（chmod 755） | 一条命令：覆盖端口起栈 → 就绪/控制面判据 → e2e → 撤栈 |
| `evidence/m7-3/EVIDENCE-E2E-STACK-UP.md` | 新增 | 本文件 |
| `evidence/m7-3/e2e-stack-up-0*.log`、`…-08-coverage-ledger.json` | 新增（**10 个**） | §2 各行对应的**原始输出**归档 |

**未改动**：`deploy/docker-compose.yml`、`src/**`、`specs/**`、`generated/**`（`git diff --stat` 中亦无这些文件）。
> 注：工作区另有 `specs/kert-openapi-v1.yaml`、`tests/integration/test_routing_api.py`、`docs/governance/…`、
> `.understandignore` 处于已修改状态，**均属并行队友（C-20 合同归并）的在途改动，非本任务所为**，本任务未触碰。

回归自检（改动仅涉 `tests/`，仍做）：
`pytest tests/unit` → **853 passed**（退出码 0）；`pytest tests/integration` → **446 passed, 1 xfailed**（退出码 0）；
`ruff check tests/e2e/conftest.py` → `All checks passed!`。

## 11. 未做的事 / 非声明

- **不是** `QA_PASS`、**不是**部署验收、**不是**生产就绪声明；本任务只产出"打通路径 + 归因"。
- **未**改 `deploy/docker-compose.yml` 语义，**未**改 `src/**`（过程中未出现"必须改源码才能跑通"的情形）。
- **未**触碰 8106 上的他人实例；**未**执行 `down -v`；**未** push；**未**提交 `deploy/.env`。
- **未**起 GITS Backend/Frontend ⇒ 21 条跨服务用例**未验证**（显式 skip 并逐条登记在 §7.2），
  "CI 绿/本次 26 条绿"**不等于**跨服务链路已验证。
- **未**带真实 LLM 凭据跑 ⇒ 模型输出内容质量**未**验证（§7.3 覆盖边界）。
- **未**新增 CI job / 未改 CI 配置：CI 的 dev-profile 路径与本脚本的 prod-profile 路径**并存**，
  是否把本脚本接入流水线属 TL/Owner 决策，本任务不代为决定。

## 12. 给 TL 的一条建议（不代为决定）

`tests/e2e/conftest.py` 现在能带凭据，但**"本仓编排起的 prod 服务"能否被 e2e 直跑**这件事此前**没有任何自动化门禁**：
本机与 CI 走的是两条不同 profile 的路径，因此 §6 这类"只在 prod 才暴露"的缝不会被 CI 发现。
建议把 `scripts/run_e2e_local.sh` 纳入 M7.3 收口的可选验证手段（或至少在 README/dispatch 里指路），
并明确它**不替代** GITS 侧跨服务验证（F-E2E-01 缺口仍在）。
