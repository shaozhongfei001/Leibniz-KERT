# DKWS × GITS v1.4 联调准备（环境 + 用例清单 + 实测结果）

> 日期：2026-08-23 ｜ 状态：**DKWS 侧就绪，可联调**（以下用例全部在 8106 真实通过）

---

## 1. 环境信息（重要：地址已变更）

| 项 | 值 |
|---|---|
| DKWS 服务 | `http://127.0.0.1:8106`（同机）／ `http://192.168.31.220:8106`（WiFi LAN） |
| **地址变更警示** | 旧文档中的 `172.22.90.134` **已失效**（本机 IP 变更）。GITS 启动时设 `DSH_BASE_URL=http://192.168.31.220:8106`（或同机 `127.0.0.1:8106`） |
| 服务方式 | systemd 用户服务 `dkws-skill`（Restart=always），最新代码（SP-20/SP-21/闸门端点）已加载 |
| 技能清单（12） | 外联 / 会面 / R1 / **SP-20** / **SP-21** + 7 个 bank-front 包 |
| 模型 | 真实 DeepSeek（`deepseek-chat`，密钥由服务启动时从凭据注入，不落盘）；离线自动回退确定性适配器 |
| 联调数据 | `CUST-CORP-0001` 华东精工（7 KI + 图谱 complete）、`CUST-CORP-0002` 华东新能源（下游链）；CRM 夹具 `docs/dd/gits-crm-customer-master.json` |
| 认证 | 无（演示环境网络层控制）；如启用鉴权由 GITS 网关加 X-API-KEY，DKWS 透传不校验 |

## 2. 用例清单与实测结果（8106 真实运行）

| 用例 | 操作 | 预期 | 实测 |
|---|---|---|---|
| L-01 健康/技能清单 | `GET /api/skill/health` | 200，12 技能含 SP-20/SP-21 | ✅ |
| L-02 SP-20 异步全流程 | `POST execute {"async":true}` → 202 jobId → 轮询 `/v1/jobs/{id}` | COMPLETED；result.status=SUCCESS；引用≥8 章；对客版 `releaseBlockedUntil=[G1,G2,G3]`；reportUrl | ✅ 36s，SUCCESS，66 引用，0 违规，blockedUntil=[G1,G2,G3] |
| L-03 SP-21 抽取 | `POST execute` SP-21（纪要+旧记忆） | candidateMemories[]（类别/置信度/衰减规则/原文引用）；REINFORCE/SUPERSEDE；0 违规 | ✅ 候选 + 更新 + 0 违规 |
| L-04 闸门清单 | `GET /api/skill/gates/{id}` | GATE-BIZ-G0..G5（must/forbidden） | ✅ 6 项 |
| L-05 闸门审计镜像 | `POST /api/skill/gates/audit` | `{recorded:true}` | ✅ |
| L-06 报告页 | `GET /api/skill/report/{requestId}` | SP-20 模板（内部版/对客版 Tab、断言表）200 | ✅ |
| L-07 幂等 | 同 requestId 重发 | trace 含 `idempotency/ok` | ✅ |
| L-08 未知技能 | `POST execute skillId=SP-999` | 404 + `status=skill_error` | ✅ 404 |
| L-09 非法 JSON | `POST execute` 坏 body | 422 | ✅ 422 |
| L-10 SP-20 UPDATE 放行 | `proposalType=UPDATE` + `gateState.passed=[G0..G3]` + interactionMemory | route=MAP_FIRST；`releaseBlockedUntil=[]`；记忆进入引用 | ✅ 33s，MAP_FIRST，blockedUntil=[]，记忆引用 6 条，gate=G4 |

## 3. GITS 侧联调检查项（按契约 v1.4）

- [ ] `DSH_BASE_URL` 设为当前地址（见 §1，勿用旧 172.22.90.134）
- [ ] 契约 DTO（ContextPackage / ProposalServiceResult / CandidateMemory）字段与 v1.4 变更说明一致，`ignoreUnknown=true`
- [ ] SP-20 走异步：202 → 轮询 `/v1/jobs/{id}`（3s 间隔，3min 上限），读 `data.skill_result`
- [ ] 错误处理：404（未知技能）/ 422（参数）/ `result.status=PARTIAL`（规则违规 → 展示 ruleViolations）/ job FAILED
- [ ] 对客版放行：仅 `releaseBlockedUntil==[]` 展示；展示前 factLabels 复核仅 F/A
- [ ] 记忆：SP-21 候选 → 人工确认 → GITS 记忆库；UPDATE 时注入 `context.interactionMemory`
- [ ] 闸门：GATE_SEQUENCING 顺序校验；推进后可选调 audit 镜像
- [ ] 超时：SP-21 同步 ≤60s；勿对 SP-20 用长连接硬等

## 4. 注意事项

- **H2 内存库**：GITS 重启后需重灌 `gits-crm-customer-master.json` 或重新 upsert（造数脚本幂等）。
- **幂等 TTL**：execute 同 requestId 10 分钟内返回首次结果；异步同 requestId 复用同一 job。
- **报告页非契约**：`reportUrl` 仅调试跳转；GITS 只消费 execute JSON（`data.result` / `data.skill_result`）。
- **LLM 慢**：SP-20 逐章 8 次调用约 30-40s（3 路并行）；联调时给足轮询时间，勿提前判超时。
- **网关超时**：若 GITS 走网关，/v1/jobs 轮询路径与 /api/skill/* 路径都需放行（无鉴权）。
