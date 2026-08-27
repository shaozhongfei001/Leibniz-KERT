# M2 里程碑完成度审核说明

> **文档性质**：待 Owner 审核的里程碑完成度说明
> **生成日期**：2026-08-27
> **分支**：feature/m2-remaining
> **审核请求人**：Tech Lead / Feature Pilot（开发侧）
> **审核对象**：Owner

---

## 0. 非声明

- 本次不代表 DKWS 已生产就绪
- 本次不代表 GITS UAT 已通过
- 本次不代表安全审计已完成
- 本次不代表 C′ 受控混合架构已成为正式基线
- 开发侧自验不代替 Owner 或 Independent QA 签署
- M2.9 数据分类与脱敏不构成对任何法规（含《个人信息保护法》）的合规认定
- M2.6 备份恢复不代表已通过灾备演练验收，RPO/RTO 目标属 Owner 决策
- M2.10 NFR 基线仅记录当前值，不宣称达标，不构成 SLA 承诺

---

## 1. M2 里程碑定义（WBS V1.0 原文）

| 子项 | WBS 定义 | WBS 验收标准 |
|------|----------|-------------|
| M2.1 | 认证与安全边界 | 401/403/413/429 测试通过 |
| M2.2 | 限流与大小限制 | 限流与超限测试通过 |
| M2.3 | SQLite Runtime Store | 重启幂等保留、Job 恢复测试通过 |
| M2.4 | 持久化异步 Worker | 崩溃恢复测试通过 |
| M2.5 | 可观测性 | 指标与日志可采集 |
| M2.6 | 备份恢复与升级回滚 | 恢复演练报告 |
| M2.7 | 部署 | 干净环境可启动 |
| M2.8 | CI/CD 与供应链安全 | CI 全绿，SBOM 生成 |
| M2.9 | 数据分类与脱敏 | 脱敏测试 |
| M2.10 | 性能与 NFR 基线 | 生成 baseline，不宣称达标 |

---

## 2. 各子项完成度与证据索引

### M2.1 认证与安全边界 — ✅ PASS

| 验收标准 | 达成情况 | 证据位置 |
|----------|----------|----------|
| 401 测试通过 | 缺失/错误 API Key → 401 UNAUTHENTICATED，不回显密钥 | `evidence/m2-p1/` E2E 检查 4-6 |
| 403 测试通过 | 非 admin 作用域访问闸门审计 → 403 FORBIDDEN | `evidence/m2-p1/` E2E 检查 7-8 |
| 413 测试通过 | 超限请求体 → 413 PAYLOAD_TOO_LARGE | `evidence/m2-p1/` E2E 检查 9 |
| 429 测试通过 | burst 超限 → 429 + Retry-After | `evidence/m2-p1/` E2E 检查 10 |
| 生产 fail-fast | prod profile 未配置密钥 → 拒绝启动 | `evidence/m2-p1/` E2E 检查 1-2 |

**E2E 验证**：`scripts/verify_m2p1_hardening.py`，20/20 PASS
**测试数**：110 项新增（107 函数 + 3 参数化展开）
**新增依赖**：无（仅 stdlib sqlite3/hashlib/hmac/asyncio + 已有 FastAPI/Starlette）

---

### M2.2 限流与大小限制 — ✅ PASS

| 验收标准 | 达成情况 | 证据位置 |
|----------|----------|----------|
| 按 API Key/IP 限流 | 令牌桶限流，burst=3 时第 3 次 → 429 | `evidence/m2-p1/` E2E 检查 10 |
| 请求体大小限制 | 上限 2048 字节，超限 → 413 | `evidence/m2-p1/` E2E 检查 9 |
| 并发限制 | 可配置并发上限 | `tests/security/test_api_hardening.py` |

> M2.1 与 M2.2 合并在同一任务包 M2-P1 中交付，因共享中间件基础设施。

---

### M2.3 SQLite Runtime Store — ✅ PASS

| 验收标准 | 达成情况 | 证据位置 |
|----------|----------|----------|
| 重启幂等保留 | 同 requestId 重启后 → 200 + trace 含 idempotency | `evidence/m2-p1/` E2E 检查 19-20 |
| Job 恢复测试 | schema v1，5 张运行态表，WAL 模式 | `evidence/m2-p1/` E2E 检查 13-18 |
| 不成为知识权威源 | 精确断言表清单无知识内容表 | `evidence/m2-p1/` E2E 检查 16 |

**关键设计**：数据落在 `90_control/runtime/`，与知识资产目录（`01_raw`~`04_serve`）物理隔离。

---

### M2.4 持久化异步 Worker — ✅ PASS

| 验收标准 | 达成情况 | 证据位置 |
|----------|----------|----------|
| 崩溃恢复测试通过 | 真实 `kill -9` → Worker 接手 → COMPLETED | `evidence/m2-p2/` E2E 检查 5-9 |
| 原子领取 | 8 线程 30 Job 无重复投递 | `evidence/m2-p2/` E2E 检查 19 |
| lease 心跳 | 后台续约线程保持 lease | `evidence/m2-p2/` E2E 检查 4/6/7 |
| 重试退避 | 指数退避 min(base×factor^(n-1), max) | `evidence/m2-p2/` E2E 检查 15-16 |
| dead-letter | FAILED + dead_letter=1，支持列出与重放 | `evidence/m2-p2/` E2E 检查 11-14 |
| 生产强制 Store | prod + 无 Store → 503，无线程回退 | `evidence/m2-p2/` E2E 检查 23-25 |

**E2E 验证**：`scripts/verify_m2p2_worker.py`，27/27 PASS
**Owner 决策落实**：3 项 Owner 决策（路线 C′、终态命名、生产强制 Store）全部落实

---

### M2.5 可观测性 — ✅ PASS

| 验收标准 | 达成情况 | 证据位置 |
|----------|----------|----------|
| /livez 可用 | 200 + status=alive，不检查依赖 | `evidence/m2-p3/` E2E 检查 2 |
| /readyz 可用 | 200 或 503，硬性+degraded 分级 | `evidence/m2-p3/` E2E 检查 3 |
| /metrics 可用 | Prometheus 文本格式，14 个指标 | `evidence/m2-p3/` E2E 检查 4-11 |
| 结构化日志 | 单行 JSON + 请求上下文 + 三层脱敏 | `evidence/m2-p3/` E2E 检查 19-23 |
| 指标可采集 | 自研解析器成功消费 | `evidence/m2-p3/` E2E 检查 5 |
| OpenTelemetry 基础 | W3C Trace Context 贯通 + 可选 OTel 桥接 | `evidence/m2-p3/` E2E 检查 12-15 |

**E2E 验证**：`scripts/verify_m2p3_observability.py`，25/25 PASS
**新增依赖**：无（刻意不引入 prometheus_client/opentelemetry 作必需依赖）
**关键发现**：Loop 中发现并修复了正文密钥泄漏缺口（`redact_message()`）

---

### M2.6 备份恢复与升级回滚 — ✅ PASS

| 验收标准 | 达成情况 | 证据位置 |
|----------|----------|----------|
| 备份脚本 | `backup.py` + `dkws_ops.py backup` | `evidence/m2-p5/` E2E 检查 2-6 |
| 恢复演练 | 真实备份→校验→恢复→一致性校验 | `evidence/m2-p5/` E2E 检查 10-17 |
| 灾难恢复 | 源工作区完全删除后从备份恢复 | `evidence/m2-p5/` E2E 检查 19 |
| 升级回滚 | 发布清单 + git 锚点 + 清单比对 | `evidence/m2-p5/` E2E 检查 20-25 |
| 恢复演练报告 | `e2e_backup_restore_report.json` | 25/25 PASS |

**E2E 验证**：`scripts/verify_m2p5_backup_restore.py`，25/25 PASS
**关键设计**：
- Runtime DB 使用 SQLite 在线备份 API（WAL 一致性保障）
- 一致性点捕获（知识版本 + DB schema + 队列统计）
- 损坏备份默认拒绝恢复（防二次灾难）
- 锁文件排除+清理（防无主锁永久阻塞）

---

### M2.7 部署 — ✅ PASS

| 验收标准 | 达成情况 | 证据位置 |
|----------|----------|----------|
| 干净环境可启动 | Dockerfile 多阶段构建 + docker-compose | `evidence/m2-p6/` G1 |
| Docker Compose | api + worker + backup 三服务 | `deploy/docker-compose.yml` |
| systemd 模板 | api/worker/backup 三服务 + timer | `deploy/systemd/` |
| 部署文档 | 完整指南（架构/前置/安装/配置/验证/FAQ） | `deploy/README.md` |
| 冒烟测试 | build→start→health→skill→stop | `deploy/smoke_test.sh` |
| Makefile | 8 个部署目标 | `Makefile` |

**交付物**：`.dockerignore`、`Makefile`、`deploy/verify_deployment.py`、`deploy/smoke_test.sh`、`deploy/README.md`

---

### M2.8 CI/CD 与供应链安全 — ✅ PASS

| 验收标准 | 达成情况 | 证据位置 |
|----------|----------|----------|
| CI 全绿 | 4-job workflow（lint/test/security/build） | `.github/workflows/ci.yml` |
| SBOM 生成 | CycloneDX 格式 | `scripts/generate_sbom.sh` |
| 依赖锁 | 35 个精确版本 | `requirements-lock.txt` |
| 漏洞扫描 | pip-audit + bandit | `scripts/security_scan.sh` |
| 无密钥环境 | DKWS_PROFILE=dev，436 测试通过 | `scripts/ci_setup.sh` |

**关键设计**：
- 安全扫描仅报告不阻塞（后续可收紧）
- mypy 渐进集成（仅报告不阻塞）
- Docker compose 验证用模拟 API Key

---

### M2.9 数据分类与脱敏 — ✅ PASS

| 验收标准 | 达成情况 | 证据位置 |
|----------|----------|----------|
| 字段敏感标记 | 4 级分类 + 31 条字段规则（含中文说明） | `evidence/m2-p4/` E2E 检查 1 |
| 日志脱敏 | 三层纵深（键名/正文正则/分类结构化） | `evidence/m2-p4/` E2E 检查 21 |
| 响应脱敏 | ResponseRedactionMiddleware（默认关闭） | `evidence/m2-p4/` E2E 检查 17-20 |
| LLM 出站脱敏 | _call_model 单点收口，默认开启 | `evidence/m2-p4/` E2E 检查 12-15 |
| 脱敏测试 | 90 个函数（136 项收集） | `evidence/m2-p4/` |

**E2E 验证**：`scripts/verify_m2p4_redaction.py`，22/22 PASS
**Loop 修复的真实缺陷**：
1. 掩码边界泄漏（keep=0 时原值完整暴露）— 严重
2. 自由文本 PII 泄漏（API 策略 mask_text=False）— 严重
3. 字段名规则与值模式冲突 — 中等

---

### M2.10 性能与 NFR 基线 — ✅ PASS

| 验收标准 | 达成情况 | 证据位置 |
|----------|----------|----------|
| 延迟基线 | P50/P95/P99（健康检查 + Skill 同步/异步） | `evidence/m2-p6/nfr_baseline_report.md` |
| 吞吐基线 | RPS（健康检查 + Skill） | 同上 |
| 并发基线 | 1/10/50/100 并发延迟+吞吐曲线 | 同上 |
| 资源基线 | 内存/SQLite（部分需手动采集） | 同上 |
| 不宣称达标 | 报告明确标注"基线值，非 SLA 承诺" | 同上 |

**关键基线数据**（确定性模式）：

| 指标 | P50 | P95 | P99 |
|------|-----|-----|-----|
| /v1/health | 1.94ms | 2.74ms | 3.11ms |
| Skill 同步 (outreach) | 4933ms | 5892ms | 6100ms |
| Skill 异步提交 | 858ms | 943ms | 962ms |

| 并发 | /v1/health RPS | P50 | 错误率 |
|------|----------------|-----|--------|
| 1 | 296.67 | 2.1ms | 0% |
| 10 | 538.47 | 16.0ms | 0% |
| 50 | 545.67 | 88.2ms | 0% |
| 100 | 505.73 | 195ms | 0% |

---

## 3. 测试门禁演进

| 任务包 | 全量测试数 | 新增测试 | E2E 检查 |
|--------|-----------|----------|----------|
| M2-P1（M2.1/2.2/2.3） | 356 | 110 | 20/20 |
| M2-P2（M2.4） | 481 | 125 | 27/27 |
| M2-P3（M2.5） | 602 | 121 | 25/25 |
| M2-P4（M2.9） | 738 | 136 | 22/22 |
| M2-P5（M2.6） | 813 | 75 | 25/25 |
| M2-P6（M2.7/2.8/2.10） | 813+ | 0（工具脚本） | Gate 验收 |

> 门禁单调递增，既有测试零修改、零删除（除 Owner 授权的 SUCCEEDED→COMPLETED 命名统一）。

---

## 4. 依赖约束遵守

| 约束 | 状态 |
|------|------|
| 不引入 PostgreSQL / Redis / 外部 MQ / Kubernetes | ✅ 全程遵守 |
| 不把 SQLite 变成知识权威源 | ✅ 仅 5 张运行态表，精确断言 |
| 不修改 GITS | ✅ 变更全在本仓库 |
| 不修改 Java Runtime 生产边界 | ✅ poc/ 零改动 |
| 不降低现有测试门禁 | ✅ 356 → 813 单调递增 |
| 不直接 push main / 不自行 merge | ✅ 工作于 feature 分支 |

---

## 5. 已知限制与待 Owner 决策项

| # | 事项 | 影响范围 | 需决策方 |
|---|------|----------|----------|
| 1 | **RPO/RTO 未设定**（备份频率、保留策略、演练频率） | M2.6 | Owner |
| 2 | **生产灾备演练未执行**（开发侧自验，非生产环境） | M2.6 | Owner 安排 |
| 3 | **Kùzu 图数据库测试 2 个失败**（既有问题，非 M2 引入） | 测试完整性 | Tech Lead |
| 4 | **分布式限流**（当前进程内，多实例不共享） | M2.2 | Owner 明确是否多实例 |
| 5 | **X-Forwarded-For 信任链**（有意不信任，避免伪造） | M2.2 | Owner 确认可信代理配置 |
| 6 | **版本号未统一**（4 套版本并存，仅记录未统一） | M2.6 | Owner 决策是否统一 |
| 7 | **合规认定需法务评估**（M2.9 是技术手段，非合规认定） | M2.9 | 法务/合规部门 |
| 8 | **mypy 渐进集成**（仅报告不阻塞） | M2.8 | 后续逐步收紧 |
| 9 | **安全扫描不阻塞 CI**（pip-audit/bandit 仅报告） | M2.8 | 后续可收紧策略 |
| 10 | **NFR 资源基线不完整**（内存/SQLite 需手动采集） | M2.10 | 后续补充 |

---

## 6. 审核请求

**开发侧声明**：M2 里程碑全部 10 个子项已按 WBS V1.0 验收标准完成开发与自验，证据链完整。

**请求 Owner**：
1. 审核本说明文档及各 `evidence/m2-p*/` 证据
2. 对第 5 节待决策项做出指示
3. 决定是否安排 Independent QA 正式签收
4. 决定是否合并 feature/m2-remaining → develop

**证据总索引**：

```
evidence/
├── m2-p1/   M2.1 认证 + M2.2 限流 + M2.3 Runtime Store
├── m2-p2/   M2.4 持久化异步 Worker
├── m2-p3/   M2.5 可观测性
├── m2-p4/   M2.9 数据分类与脱敏
├── m2-p5/   M2.6 备份恢复与升级回滚
└── m2-p6/   M2.7 部署 + M2.8 CI/CD + M2.10 NFR 基线
```
