# 证据：运行时控制面供给（M7.3 第五步 a —— 先供给、后接线）

```text
PACKAGE   : M7-3-5a-RUNTIME-PROVISIONING（授权 D1-A）
AUTHORITY : docs/governance/KERT_PENDING_OWNER_DECISION_M7_EVOLUTION_V1.0.md §0
BRANCH    : feature/m7-3-knowledge-map-route（base ac441e3）
DATE      : 2026-09-15
ENV       : python3 3.10.12（无 typer）；.venv typer 0.27.1（= requirements-lock.txt:43）
            ruff 0.16.4（= ci.yml:49）
```

## 1. 为什么先做供给（顺序是安全决定，不是偏好）

第五步原本是"把 `skills.py` 三处硬编码 mapId 接到注册表"。但严格 fail-closed 下，
未供给的运行时工作区会让既有技能**直接拒绝** ⇒ 接线即打断服务。故拆为：

- **⑤a 供给（本轮）**：让工作区能被正确配置，**不改变任何既有行为**；
- **⑤b 接线（未做）**：改 `skills.py` 的运行时行为 —— 届时需先确认供给已在部署中落地。

## 2. 交付

| 文件 | sha256（前 16） | 说明 |
|---|---|---|
| `src/kert/application/provision.py` | `42b905d4cea0732c` | `provision_control_plane()`；供给 5 份控制面文件 + 留痕 |
| `src/kert/cli/main.py` | — | 新增 `kert provision` 子命令（`--dry-run` / `--output json`） |
| `tests/unit/test_provision.py` | — | **15 例**（供给核心） |
| `tests/unit/test_provision_cli.py` | — | **4 例**（CLI 面；须 `.venv`） |
| `src/kert/domain/ontology_reference.py` | — | 修正因本步**过时**的"供给属后续范围"声明 |

**供给内容**（仅控制面元数据，绝不触碰 `03_core`）：

| 目标 | 来源 |
|---|---|
| `90_control/catalog/KM-*.json`（3 份） | 源工作区 `catalog/` |
| `90_control/schema/route_policy.json` | 源工作区 `schema/` |
| `90_control/schema/ontology_reference.json` | 源工作区 `schema/` |
| `90_control/catalog/provision_manifest.json` | 留痕（哈希/时刻/来源/逐项 action） |

## 3. 六条纪律 ↔ 测试（一条纪律至少一个测试）

| # | 纪律 | 对应测试 |
|---|---|---|
| 1 | **先全量校验、后写入**（源非法 ⇒ 一份都不写） | `test_invalid_map_writes_nothing[3 份参数化]`、`test_invalid_policy_writes_nothing` |
| 2 | **幂等**（内容未变不重写） | `test_idempotent_second_run_rewrites_nothing` |
| 3 | **路径来自加载器**（写侧/读侧同源） | 由 `catalog_dir()/policy_path()/reference_path()` 唯一来源保证 |
| 4 | **不删既有文件** | `test_does_not_delete_or_touch_other_files` |
| 5 | **原子替换** | `_write_atomic`（temp + `os.replace`） |
| 6 | **源须为合法工作区** | `test_source_must_be_workspace`、`test_source_without_policy_is_rejected` |

## 4. 命令与结果（原始退出码）

| 命令 | 退出码 | 结果 |
|---|---|---|
| `pytest tests/unit/test_provision.py` | **0** | **15 passed**（`--collect-only` 计数 = 15） |
| `pytest tests/unit tests/integration` | **0** | **1274 passed, 1 skipped, 1 xfailed** |
| `ruff check src/ tests/` | **0** | `All checks passed!` |
| `.venv/bin/python -m pytest tests/unit/test_provision.py tests/unit/test_provision_cli.py` | **0** | 19 passed（15 + 4，CLI 面真跑） |

**唯一 skip**：系统 python3 无 `typer` ⇒ `test_provision_cli.py` 整模块跳过。
CLI 面测试**单独成文件**正是为此：`importorskip` 若放在 `test_provision.py` 顶部，
会连**核心供给测试一起跳过**并使退出码变 5（"看起来跑了其实没跑"，已实测踩到）。

### CLI 真实冒烟（`.venv`，非测试替身）

```text
init                       → 目录 13 / 文件 2
provision --dry-run        → 新建 5 / 覆盖 0 / 未变 0  + "（--dry-run：未落盘）"
provision（实）            → 新建 5 / 覆盖 0 / 未变 0
provision（复跑）          → 新建 0 / 覆盖 0 / 未变 5     ← 幂等
落盘                       → catalog/KM-*.json ×3 + schema/*.json ×2 + provision_manifest.json
源非法                     → SchemaValidationError；目标 catalog 内容 = []   ← fail-closed
```

## 5. 变异自证（三项，基线 PASS → 变异 FAIL → 恢复 PASS）

日志：`evidence/m7-3/provision-mutation-*.log`；恢复后 `provision.py=42b905d4cea0732c`。

| 变异 | 施加方式 | 变异后 FAIL 的用例 |
|---|---|---|
| **M1** 只校验第一份地图就开写 | `KnowledgeMapRegistry.load(src)` → 只装载 `map_files(src)[0]` | `test_invalid_map_writes_nothing[KM-CORP-RM-OUTREACH.json]`、`[KM-CORP-RM-PREVISIT.json]`、`test_creates_all_control_plane_files` |
| **M2** 去掉哈希比较（总是覆盖） | `elif sha256_file(d_path) == digest:` → `elif False:` | `test_idempotent_second_run_rewrites_nothing`、`test_source_change_yields_updated_only_for_that_file` |
| **M3** 跳过"目标须为工作区" | `if not is_workspace(ws):` → `if False:` | `test_target_must_be_initialized_workspace` |

**本轮自查发现并修复的测试漏洞**（M1 的设计即由此而来）：fail-closed 最初只破坏**第一张**
地图 —— 若实现"只校验第一份就开写"，测试仍会全绿。已改为**逐份参数化**（3 张地图 + 策略），
M1 因此恰好命中第 2、3 张地图的用例。

## 6. 未做（本步边界）

1. **⑤b 接线未做**：`skills.py` 第 651/683/717 行仍为硬编码 mapId（仅写 trace，未做运行时解析）；
2. **部署侧未执行**：`bank_front_ws` 的实际供给属运维动作，本仓**不代理**（未改任何部署脚本/环境）；
3. **`90_control/decisions/` 未留决策记录**：仅 `provision_manifest.json` 留痕（未写 append-only 审计日志）；
4. **策略/本体引用的多版本共存与回滚未做**（当前为整份覆盖）。

## 7. 非声明

- 本证据**不是** `QA_PASS`、**不是** Contract Owner 批准；**不**声明生产就绪、**不**声明 GITS UAT 通过；
- **不**声明第五步完成（仅完成 ⑤a）；**不**声称运行时工作区已被供给（那是部署动作）；
- 未改 `03_core` 权威资产；未改 GITS 仓；未 push（`AGENTS.md` 规则 #10）。
