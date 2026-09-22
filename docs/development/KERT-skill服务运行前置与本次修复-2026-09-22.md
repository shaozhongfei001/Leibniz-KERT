# KERT skill 服务运行前置与本次修复记录（2026-09-22）

> 触发：GITS 侧 4 个演示功能「都无效」。本文只记**实测事实**与**修复动作**，不写推测。

## 1. 根因（第 0 层：服务与控制面）

| 现象 | 实测证据 |
|---|---|
| GITS 调 KERT 全部失败 | GITS `dsh.base-url` 默认 `http://127.0.0.1:8107`（`apps/api/src/main/resources/application.yaml:59`），但 **8107 无人监听** |
| 起了服务后仍**全部被拒** | `POST /api/skill/execute` 对 SP-15 / SP-20 / 访前报告一致返回 `KERT_PERMISSION_DENIED / ROUTE_POLICY_ABSENT`：「控制面未配置路由策略（route_policy.json 缺失）⇒ 默认拒绝」 |
| 为何缺失 | 服务所用工作区 `bank_front_ws` **有数据但无工作区标记**（根目录缺 `.kert_workspace`），且 `90_control/schema/` 整个不存在 ⇒ 从未被 `provision` 过 |

**关键认知**：`RouteResolver` 对缺策略**默认 DENY**（fail-closed，非 bug）⇒ skill 服务「起来了」不等于「能干活」，
**控制面必须供给到被服务的工作区**。

## 2. 修复动作（零代码改动）

```bash
# ① 初始化工作区（纯增量：只 mkdir + 写标记，不删任何文件）
python -c "
from pathlib import Path
from kert.domain.workspace import init_workspace
init_workspace(Path('/home/szf/dev/Leibniz-KERT/bank_front_ws'), force=True)"

# ② 把控制面供给进该工作区（幂等；官方范式见 scripts/run_human_walkthrough.sh 第 ③ 步）
python -c "
from pathlib import Path
from kert.application.provision import provision_control_plane
provision_control_plane(Path('/home/szf/dev/Leibniz-KERT/bank_front_ws'),
                        Path('/home/szf/dev/Leibniz-KERT/examples/bank-front-knowledge-maps'))"

# ③ 起服务（GITS 默认指向 8107）
KERT_PROFILE=dev KERT_REPO_ROOT=$PWD KERT_SKILL_PACKAGES=$PWD/examples/bank-front-skills \
  .venv/bin/python scripts/serve_skill_service.py --port 8107 --host 127.0.0.1 \
  --workspace /home/szf/dev/Leibniz-KERT/bank_front_ws
```

供给结果（实测）：`policy=RP-KERT-BANKFRONT-001@1.1.0 maps=7 contracts=2`、`CREATED=12`
（7 张 `KM-CORP-RM-*.json` + `route_policy.json` + `ontology_reference.json` + `knowledge_sources.json`
+ `activations/AC-FACT-RECONCILIATION-001.json` + `AC-PRODUCT-RECOMMEND-001.json`）。

> ⚠ `bank_front_ws/`、`demo_workspace/` 均在 `.gitignore`（运行时工作区，非仓库内容）⇒ 本修复**不改仓库文件**；
> 但**重建工作区后必须重跑供给**，否则 skill 会再次全部被拒。

## 3. 修复后的实测结果（GITS 端到端）

| 功能 | 结果 |
|---|---|
| 建议书草稿（SP-20） | `POST /api/v14/proposals` → **200 SUCCESS**；真实 8 章草稿（「第一章 企业概况与经营现状…」）+ **86 引文** + 46 未知项 + 1 限制 |
| 产品推荐三段式（SP-15） | `POST /api/v1/product-recommendation-runs` → **200**，`status=AWAITING_HUMAN`；`/stages` → `eligibilityResults=13`、`fitResults=13`、`portfolioCandidates=1`、`needProfile=3`、`conflicts=1` |
| 访前报告（3 skill 并行） | `POST /api/v1/engagement/journey/{id}/prepare-previsit` → **200**；`outreachScript=13`、`meetingScript=13`、`previsitReport=11`、`battleCard=9`、`assemblyTrace=14`、`skillSections=7`、真实 `skillExecutiveSummary` |

## 4. 调用方（GITS）必须满足的入参（实测）

| skill | 必需入参 | 依据 |
|---|---|---|
| `SP-20` | `context.customerName` + `context.industry`（**中文行业标签**，非 `MANUFACTURING` 码） | `src/kert/application/service_proposal.py:166,170-174` |
| `SP-15` | `context.needVersionIds`（非空）；run 还需 `journeyId` 或 `operatingCaseId` | `src/kert/application/product_recommendation/sp15_skill.py:80-88,248-264` |
| `skill-customer-previsit-report` | `request.evidenceTimestamp`（且**大于本进程上次值**，否则按策略退出 `exit_policy_no_new_evidence`） | `src/kert/application/skills.py:337-354` |

> `KERT_CONTEXT_INSUFFICIENT` / `SKILL_EXECUTION_FAILED` 等返回属**契约层面的入参不齐**，不是 KERT 数据缺口。

## 5. 未解决（交接 GITS 侧）

1. `SP-20` 失败被 GITS **静默降级**为 `200 + SUCCESS 空壳`（`ServiceProposalService.java:166-180`），
   违反其自身端口契约「失败必须抛异常（不静默降级）」；
2. 产品中心 8 章中 7 章由 GITS 侧**硬编码返回空数组**（`ProductCenterCatalogService.java:209-219`），
   且 KERT 侧**尚无 8 章结构化产物**（`03_core` 产品卡为散文 11 节、FAQ 全仓无来源、价格仅「待核定」）。

## 6. 分域口径（本次据此判定"该谁改"）

| 域 | 拥有 | 本次判定 |
|---|---|---|
| 公共域（L1） | `Party/Organization/CustomerRole/ProductOffering/SourceIdentifier` | 产品身份归公共域；两侧只存授权投影，不重新定义真相 |
| KERT（L2） | 产品知识（卡/条款/边界/流程/材料/价格/比较/FAQ）、解读与三视图投影、Skill 平台 | 8 章数据**应由 KERT 产出**；skill 入参不齐属**调用方**问题 |
| GITS（L3） | 经营过程（案件/建议/人工决定/动作/回执） | 只读消费 + fail-closed；**不得本地兜底生成结论** |
| 检索（LightRAG） | KERT 的**可关派生层**，非权威 | 两仓均无实现；架构明文「**不得成为基础闭环新增前置**」⇒ 8 章缺数据**不是**检索问题 |
