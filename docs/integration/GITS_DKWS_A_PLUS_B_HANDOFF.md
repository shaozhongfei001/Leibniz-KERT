# GITS × DKWS A+B 交接包（候选）

> 日期：2026-08-26
> 状态：CANDIDATE
> 结论：`GITS_UAT_PASS=NO`；下一步为 A+B，B 先落地、A 紧接完成。
> 范围：只生成 GITS 交接设计和验收清单，不修改 GITS 仓库。

## 1. 当前事实

- GITS 当前分支：`feature/P30-gits-bank-experience-shell`
- GITS 工作区存在未提交改动：
  - `DshHttpSkillExecutionAdapter.java`
  - `DshHttpSkillGateAdapter.java`
  - `DshJobPoller.java`
  - `V14DkwsIntegrationController.java`
  - `application.yaml` 含 `dsh.base-url: ${DSH_BASE_URL:http://127.0.0.1:8106}`
- 未提交、未独立验证，不能作为受控证据。
- 独立评审根因判断：`PLAUSIBLE_BUT_NOT_INDEPENDENTLY_VERIFIED`
- 缺失证据：GITS P24/P30 commit diff、application 配置快照、HTTP 调用日志、UAT 原始日志

## 2. 推荐顺序：B → A

### 2.1 B：先移除伪成功路径

对 DKWS 负责的能力：

- 未配置 DKWS、不可达、超时、鉴权失败、契约错误时，必须显示明确空态
- 禁止使用本地 Mock、H2、fallback 数据冒充 DKWS 返回
- 禁止解析本地 HTML 报告页冒充图谱
- 禁止把 G0-G5 写成可写阶段机
- 错误必须保留类型和 correlation ID（requestId/traceId）

### 2.2 A：恢复真实 HTTP 对接

- 建立 GITS → DKWS HTTP Adapter
- 配置名使用产品中性：
  - `DKWS_BASE_URL`
  - `DKWS_API_KEY`
- 不使用外部智能体平台命名作为产品配置
- 建立 consumer contract tests
- 建立真实 E2E：R1、供应链图谱、assemblyTrace、SP-20、SP-21、Gate
- 验证超时、重试、鉴权失败、契约错误、DKWS 不可用

## 3. 必须接入的 DKWS 能力

| 能力 | Skill/端点 | 行为要求 |
|---|---|---|
| R1 访前报告 | `skill-customer-previsit-report` | 只展示 DKWS `data.sections`；空则空态 |
| R2 速战卡 | 同一 Skill 的 `data.sections` | 空则空态 |
| 外联话术 | `skill-customer-outreach-script` | 空则空态 |
| 会面话术 | `skill-customer-meeting-script` | 空则空态 |
| 供应链图谱 | `bank-front-supply-chain-graph` | 消费 `data.result` nodes/edges/interpretation |
| 装配控制台 | `assemblyTrace[]` | 访前页 Debug 展示 |
| 产品推荐 | `bank-front-product-recommendation` | 只带 customerId；空则空态 |
| 服务建议书 | SP-20 | 异步 202 + 轮询 `/v1/jobs/{id}` |
| 交互记忆 | SP-21 | 消费候选记忆，不本地伪造 |
| 闸门 | GET/POST `/api/skill/gates/...` | 只读清单 + 认证审计镜像 |

## 4. 配置建议（GITS application.yaml 候选）

```yaml
dkws:
  base-url: "${DKWS_BASE_URL:http://127.0.0.1:8106}"
  api-key: "${DKWS_API_KEY:}"
  connect-timeout-ms: 5000
  read-timeout-ms: 180000
  skill-execute-path: /api/skill/execute
  health-path: /api/skill/health
  job-path-prefix: /v1/jobs
  async-poll-interval-ms: 3000
  async-poll-timeout-ms: 180000
```

注意：本候选建议 GITS 从 `dsh.*` 迁移到 `dkws.*`，但具体迁移需 GITS 侧决策。

## 5. Fail-closed 规则

| 场景 | GITS 展示 |
|---|---|
| DKWS 未配置 | “DKWS 未配置” |
| 连接超时 | “DKWS 未返回” |
| 401/403 | “DKWS 鉴权失败” |
| 404 未知技能 | “DKWS 未知技能” |
| 422 契约错误 | “DKWS 契约错误” |
| 429 限流 | “DKWS 繁忙，请稍后” |
| `status=skill_error` | “DKWS 执行失败” |
| SP-20 `result.status=PARTIAL` | 展示规则违规，不允许对客放行 |
| 图谱空 | “DKWS 未返回图谱” |

## 6. 验收清单

- [ ] GITS 不再使用 H2/Mock 拼装 DKWS-owned 能力
- [ ] 未配置/不可达时页面显示空态
- [ ] 真实 HTTP 调用 DKWS 成功
- [ ] R1、图谱、assemblyTrace、SP-20、SP-21、Gate 全链路 E2E
- [ ] 注入故障：超时/401/404/422/429/PARTIAL/Job FAILED 均 fail-closed
- [ ] 两侧保留同一 requestId/traceId 证据
- [ ] `UAT_PASS=NO` 保持，直到 Owner 独立签署

## 7. 缺失证据与关闭条件

| 证据 | 责任方 | 关闭条件 |
|---|---|---|
| GITS P24/P30 commit diff | GITS Tech Lead | 提供受控 diff |
| application 配置快照 | GITS Tech Lead | 提供脱敏配置 |
| HTTP 调用日志 | GITS/DKWS | 提供 requestId 两侧日志 |
| UAT 原始报告 | Owner | Owner 签署 |
