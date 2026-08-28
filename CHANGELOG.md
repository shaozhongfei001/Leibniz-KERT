# Changelog

所有重要变更均记录在此文件中。格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)。

---

## [0.1.0] - 2026-08-28

### 首次发布 — DKWS-SPEC-001 V1.0 完整实现

#### 新增

**核心架构 (P0-P3)**
- 工作区（Workspace）生命周期管理：init / inspect / validate
- 数据接入（Ingest）：CSV/JSON/JSONL/Parquet 文件导入
- 文档解析（Parse）：PDF/DOCX/Markdown/纯文本解析
- 知识抽取（Extract）：基于 LLM 的实体/关系/声明抽取，支持确定性适配器
- 审核（Review）：抽取结果人工审核与确认
- 发布（Publish）：知识资产版本化发布与回滚

**知识服务 (P4-P6)**
- 实体查询：`GET /v1/entities/{id}`
- 证据溯源：`GET /v1/evidence/{id}`
- 数据查询：`POST /v1/data/query`
- 图谱查询：`POST /v1/graph/query`（BFS 遍历）
- 全文搜索：`POST /v1/search`
- 规则求值：`POST /v1/rules/evaluate`

**技能平台 (P7-P8)**
- 技能注册与发现：YAML 技能定义 + 自动扫描
- 技能执行引擎：参数校验 → 门禁检查 → LLM 调用 → 结果持久化
- 5 个内置技能：memory（客户记忆）、proposal（服务提案）、outreach（触达方案）、meeting（会议纪要）、previsit（拜访报告）
- 门禁（Gate）协作：客户级访问控制与审计

**运维与可观测性 (P9)**
- 健康检查：`/livez`、`/readyz`
- Prometheus 指标：`/metrics`
- OpenTelemetry 分布式追踪
- 结构化 JSON 日志（敏感字段脱敏）
- 任务队列：异步任务提交与状态查询

**DSH 动态插件 (P10)**
- Web 管理界面：`/dsh/` SPA（仪表盘/技能管理/知识浏览/任务监控）
- 7 个 DSH API 端点
- `dkws serve` 命令：一键启动 HTTP 服务

**安全**
- 路径穿越防护：规范化 + 工作区边界校验
- 日志脱敏：API Key / Token 自动遮蔽
- DSL 注入防护：eval/exec/import 等危险操作拦截
- API 输入校验与边界检查

**文档**
- `docs/API.md` — HTTP API + CLI 命令完整参考
- `docs/DEPLOYMENT.md` — 部署指南（venv/Docker/Systemd）
- `docs/architecture/` — 架构设计文档
- `docs/assets/` — 资产模型文档
- `README.md` — 项目概览与文档索引

#### 测试

- **1177 个测试**全部通过
  - 单元测试：~1089 个
  - E2E 集成测试：46 个（9 个场景）
  - 安全测试：8 个
  - 性能基准：44 个
- **86% 代码覆盖率**
- 性能基线：NFR-005/006/007 全部 PASS
  - Parquet 10K 行写入 8ms / 读取 30ms
  - 并发锁 10 线程 < 2s
  - 图谱查询 10K 行 56ms

#### 技术栈

- Python 3.11+ / FastAPI / uvicorn
- PyArrow (Parquet) / Kùzu (图数据库)
- OpenAI 兼容 LLM API
- 确定性适配器（测试/离线模式）
