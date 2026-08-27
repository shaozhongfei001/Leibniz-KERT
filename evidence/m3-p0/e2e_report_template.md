# M3-P0 端到端验收报告

> 本模板由 `scripts/verify_m3_e2e.py` 自动生成，也可手动填写。

## 基本信息

| 字段 | 值 |
|------|------|
| 任务包 | M3-P0 |
| 范围 | GITS ↔ DKWS 集成场景端到端验收 |
| 执行人 | |
| 执行时间 | |
| DKWS URL | http://127.0.0.1:8106 |
| 测试客户 | CUST-E2E-001 |
| 模式 | 确定性（无需 LLM 密钥） |

## 汇总

| 指标 | 值 |
|------|------|
| 通过/总计 | / |
| 结果 | |

## 场景 1：R1 基本访前

### 步骤

| # | 步骤 | 预期 | 实际 | 判定 |
|---|------|------|------|------|
| 1 | GET /api/skill/health | 200 + skill 列表含 customer-engagement 族 | | |
| 2 | 确认 outreach-script skill 可用 | skillId 包含 outreach | | |
| 3 | POST /api/skill/execute (outreach-script) | 200 + 外联话术 | | |
| 4 | 验证响应格式和内容完整性 | status=success/completed, data 非空 | | |

## 场景 2：SP-20 服务建议书

### 步骤

| # | 步骤 | 预期 | 实际 | 判定 |
|---|------|------|------|------|
| 1 | POST /api/skill/execute (SP-20, asyncRun=true) | 202 + jobId | | |
| 2 | 轮询 GET /v1/jobs/{jobId} | COMPLETED | | |
| 3 | GET /v1/extractions/{jobId}/result | 200 + 建议书结果 | | |
| 4 | 验证 8 章内容 + 6 规则校验 | chapters 非空 | | |

## 场景 3：SP-21 交互记忆抽取

### 步骤

| # | 步骤 | 预期 | 实际 | 判定 |
|---|------|------|------|------|
| 1 | POST /api/skill/execute (SP-21) | 200 + 候选记忆 | | |
| 2 | 验证记忆格式 | candidateMemories 列表非空 | | |
| 3 | 验证置信度 | 记忆含 confidence/score 字段 | | |

## 场景 4：供应链图谱

### 步骤

| # | 步骤 | 预期 | 实际 | 判定 |
|---|------|------|------|------|
| 1 | POST /api/skill/execute (bank-front-supply-chain-graph) | 200 + 图谱数据 | | |
| 2 | 验证图谱节点 | nodes 列表非空 | | |
| 3 | 验证图谱边 | edges 列表 | | |

## 场景 5：闸门协作

### 步骤

| # | 步骤 | 预期 | 实际 | 判定 |
|---|------|------|------|------|
| 1 | GET /api/skill/gates/{customerId} | 200 + 闸门清单 | | |
| 2 | POST /api/skill/gates/audit | 200/201 + 审计记录 | | |

## 备注

- 确定性模式：DKWS 使用预设响应，不调用 LLM，结果可复现
- LLM 模式：需要有效的 API Key，结果可能因 LLM 输出而变化
- 所有脚本仅使用 Python 标准库，无需额外依赖
