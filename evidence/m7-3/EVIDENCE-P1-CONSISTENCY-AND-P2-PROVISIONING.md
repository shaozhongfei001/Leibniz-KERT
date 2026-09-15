# 证据：P1 控制面一致性修正 + P2 供给编排落地（M7.3 第五步前置）

```text
PACKAGE   : M7-3-5-PRE（用户裁决：P1 现在修；⑤b-full 待 P1+P2 后再实施）
BRANCH    : feature/m7-3-knowledge-map-route（base ca1f7b6）
DATE      : 2026-09-15
ENV       : python3 3.10.12；.venv python（typer 0.27.1）；ruff 0.16.4；docker compose 可用
```

## 1. P1：修正 PREVISIT 地图与"被缺陷背书"的测试

| 变更 | 内容 |
|---|---|
`KM-CORP-RM-PREVISIT.json` | `assetRefs` 3 → **7 条**（对齐 `_run_previsit` 真实读取；原 3 条属 `_run_supply_chain`）；`version 1.0.0 → 1.0.1`（**受治理内容变更必须升版本**，否则两份不同内容共用一个版本号，plan hash 失去可追溯性）；`notes` 改正为如实说明 |
`test_activation_plan.py` | `REAL_TASKS` 增列 **mapVersion**；PREVISIT 资产数 3 → 7；`test_plan_to_dict_shape_is_stable` 由写死 `[1,2,3]` 改为断言**不变量**（sequence 必须 1..N 连续） |
`test_routing_api.py` | 参数化补 `map_version`（PREVISIT = 1.0.1） |
OUTREACH / MEETING 地图 | `notes` 增一句：一致性**不由自述背书**，由机械核对用例负责 |

**"被缺陷背书"的三处**（都断言过错误的 3 条）：`REAL_TASKS[PREVISIT]`、`test_plan_to_dict_shape_is_stable`
的 `[1,2,3]`、以及下面第 3 节的弱测试的 `checked == 10`。

## 2. 新增机械核对：`tests/integration/test_control_plane_consistency.py`（7 例）

把"一致"变成**可执行事实**：取**技能自己产出的 trace**（`kiId`）作为"技能实际读取集"，
与地图 `assetRefs` 做**双向相等**比对；另有 semver 检查与"三张地图全覆盖"防漏网。

含**反空转**断言：`assert read`（若 trace 机制失效导致读集为空，用例必须失败而不是"空集相等"空过）。

## 3. 删除一个**过弱且会腐烂**的既有测试

原 `tests/unit/test_knowledge_map.py::test_real_maps_reference_only_kis_that_skills_actually_read` 已移除，理由：

1. 只判 `asset_id` 是否作为**字符串**出现在 `skills.py` 源码里 —— 不区分**哪个技能**读取；
2. 只做**单向**检查（地图 ⊆ 源码文本）⇒ 对"技能读 7 条、地图只声明 3 条"的**漏声明完全不可见**；
3. 末尾硬编码 `checked == 10`，把错误计数**固定**下来。

三者叠加使它对本次真实事故零覆盖。逐技能一致性现为**单一权威位置**（第 2 节文件），原处留注释说明，禁止复建。

## 4. P2：供给并入部署链（**编排已落地；实际部署执行仍属部署侧**）

| 变更 | 内容 |
|---|---|
`deploy/docker-compose.yml` | 新增一次性服务 **`provision`**（`entrypoint: ["kert","provision"]`，`restart: "no"`，沿用只读根/丢能力/`no-new-privileges` 加固）；`api` 与 `worker` 均 `depends_on: provision: service_completed_successfully`（worker 与既有 `api: service_healthy` **合并**，非叠加键） |
`deploy/.env.example` | 新增**必填** `KERT_CONTROL_PLANE_SOURCE`（容器内路径，默认 `/app/examples/bank-front-knowledge-maps`）；未声明 ⇒ compose 直接失败（与 `KERT_API_KEYS` 同口径：宁可起不来，不要半配置起来） |
`deploy/README.md` | §2 说明该变量与 fail-closed 理由；§3 说明 `up -d` 的供给链与 `make deploy-provision`；§4 增"控制面是否真的供给成功"的验证命令 |
`Makefile` | 新增 `deploy-provision`（手动重跑，幂等） |

**依赖链（`docker compose config` 实测）**：

```text
provision -> None
api       -> provision: service_completed_successfully
worker    -> api: service_healthy + provision: service_completed_successfully
provision.command -> ['-w', '/data/workspace', '-s', '/app/examples/bank-front-knowledge-maps']
```

## 5. 命令与结果（原始退出码）

| 命令 | 退出码 | 结果 |
|---|---|---|
| `pytest tests/unit tests/integration` | **0** | **1290 passed, 1 skipped, 1 xfailed** |
| `ruff check src/ tests/`（0.16.4） | **0** | `All checks passed!` |
| `scripts/validate_contract_bundle.py` | 0 | `schemas=11` / `kert-openapi-v2.yaml` |
| `docker compose -f deploy/docker-compose.yml config --quiet` | **0** | `COMPOSE_CONFIG=OK` |
| CLI 在 `KERT_PROFILE=prod` 且**无** API Key 下执行供给 | **0** | `CREATED`（实测确认 CLI 不依赖 API Key，故 provision 服务无需注入凭据） |

## 6. 变异自证（三项，基线 PASS → 变异 FAIL → 恢复 PASS）

日志：`evidence/m7-3/p1-consistency-mutation-*.log`；恢复后 `map=637bb28d2eb0727c`、`skills.py=cb9ccd804314545d`。

| 变异 | 施加方式 | 变异后 FAIL 的用例 |
|---|---|---|
| **M1**（**原缺陷原样退回**） | PREVISIT 只留 3 条资产 | `test_map_assets_equal_skill_reads[skill-customer-previsit-report]` |
| **M2** 技能侧多读一条 | `_run_outreach` 增读 `KI-FRONT-005` | `test_map_assets_equal_skill_reads[skill-customer-outreach-script]` |
| **M3** trace 机制失效 | 删 `_trace_ki` 的 `kiId` 字段 | 三个参数化用例全红（由反空转断言拦截） |

**M1 是本轮最有价值的一条**：它证明新核对用例**确实能抓住真实发生过的缺陷**，而不是"写了个看起来对的测试"。

## 7. 过程中另外抓到并修掉的两个问题

1. **compose 重复键**：`worker` 原本已有 `depends_on: api`，我误加第二个 ⇒ `docker compose` 报
   `mapping key "depends_on" already defined`。**注意 PyYAML `safe_load` 静默容忍重复键**，
   是 compose 的解析器拦住的 ⇒ 结论：YAML 类交付物**必须用真实消费方**校验，不能只 `yaml.safe_load`。
2. **弱测试**（第 3 节）：若不删，它会以 `checked == 10` 一直"绿"着掩盖漏声明。

## 8. ⑤b-full 当前状态（**未实施**）

- **P1 已完成**（本节 1-3）；**P2 编排已落地**，但**实际部署执行**（在真实工作区跑 provision）
  仍属**部署侧动作**，本仓不代理、我**未**执行 `docker build/up`；
- ⇒ 按用户裁决顺序（P1 + P2 → 再实施），**⑤b-full 代码尚未开工**；仅做 **(A)**，(B) 另立。

## 9. 非声明

- 本证据**不是** `QA_PASS`、**不是**部署验收；**未**执行镜像构建与容器启动；
- **未**声明 P2 已在任何环境生效（仅编排与文档落地）；**未**声明 ⑤b-full 已实施；
- 未改合同、未改 `03_core`、未改 GITS 仓；未 push（规则 #10）；
- `PRODUCTION_RELEASE_GATE=BLOCKED` 不变；不代表 GITS UAT 通过。
