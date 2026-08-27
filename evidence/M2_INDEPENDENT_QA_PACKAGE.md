# M2 Independent QA 执行包

> **版本**：1.0
> **日期**：2026-08-27
> **目标分支**：develop（commit 47fd7d6）
> **前置条件**：QA 环境需 Python 3.12+、pip、git

---

## 0. QA 角色声明

本执行包供 Independent QA 使用。QA 人员应：
- 独立于开发团队执行
- 不信任开发侧的"PASS"声明
- 在干净环境复现所有验证
- 记录实际观测结果，而非复制开发侧结论
- 发现问题记录为 FAIL-YYYY-MM-DD-NN 格式

---

## 1. 环境准备

```bash
# 1. 克隆仓库并切换到 develop
git clone <repo-url> && cd Leibniz-KERT
git checkout develop
git log --oneline -1  # 确认 commit 47fd7d6

# 2. 创建虚拟环境
python3 -m venv .venv
source .venv/bin/activate

# 3. 安装依赖（含全部可选组件）
pip install ".[api,dev,test,graph]"

# 4. 验证关键包可导入
python -c "import dkws; import kuzu; import fastapi; print('OK')"
```

---

## 2. 全量单元/集成测试

```bash
# 运行全量测试
DKWS_PROFILE=dev python -m pytest tests -v --tb=short

# 预期：813 passed, 0 failed
# 记录实际结果
```

**验收标准**：0 failed

---

## 3. E2E 验证脚本（6 个任务包）

按顺序执行，每个脚本独立验证一个 M2 子项：

### 3.1 M2-P1：认证 + 限流 + Runtime Store

```bash
DKWS_PROFILE=dev python scripts/verify_m2p1_hardening.py
# 预期：20/20 PASS
# 关键检查：401/403/413/429、重启幂等、Store schema
```

### 3.2 M2-P2：持久化异步 Worker

```bash
DKWS_PROFILE=dev python scripts/verify_m2p2_worker.py
# 预期：27/27 PASS
# 关键检查：kill -9 崩溃恢复、原子领取、dead-letter、生产强制 Store
```

### 3.3 M2-P3：可观测性

```bash
DKWS_PROFILE=dev python scripts/verify_m2p3_observability.py
# 预期：25/25 PASS
# 关键检查：/livez、/readyz、/metrics、结构化日志、Trace Context
```

### 3.4 M2-P4：数据分类与脱敏

```bash
DKWS_PROFILE=dev python scripts/verify_m2p4_redaction.py
# 预期：22/22 PASS
# 关键检查：4 级分类、31 条字段规则、日志/响应/LLM 三层脱敏
```

### 3.5 M2-P5：备份恢复与升级回滚

```bash
DKWS_PROFILE=dev python scripts/verify_m2p5_backup_restore.py
# 预期：25/25 PASS
# 关键检查：备份→校验→恢复→一致性、灾难恢复、升级回滚
```

### 3.6 M2-P6：部署 + CI + NFR

```bash
# Docker 构建验证
docker build -f deploy/Dockerfile -t dkws-m2-qa .

# Docker Compose 语法验证
DKWS_API_KEYS="qa-test-key:qa_test_key_at_least_16_chars:read|execute" \
  docker compose -f deploy/docker-compose.yml config --quiet

# NFR 基准测试（可选，需启动服务）
# bash scripts/run_nfr_baseline.sh --quick
```

---

## 4. 安全专项验证

### 4.1 认证绕过测试

```bash
# 启动服务
DKWS_PROFILE=dev DKWS_API_KEYS="test-key:test_key_at_least_16_chars:read|execute" \
  python scripts/serve_skill_service.py &
SERVER_PID=$!
sleep 3

# 测试无 Key 访问 → 期望 401
curl -s -o /dev/null -w "%{http_code}" http://localhost:8106/v1/health

# 测试错误 Key → 期望 401
curl -s -o /dev/null -w "%{http_code}" -H "X-API-Key: wrong" http://localhost:8106/v1/health

# 测试正确 Key → 期望 200
curl -s -o /dev/null -w "%{http_code}" -H "X-API-Key: test-key" http://localhost:8106/v1/health

# 清理
kill $SERVER_PID
```

### 4.2 脱敏验证

```bash
# 检查日志中是否泄漏敏感字段
# 启动服务并执行 Skill，检查日志输出
# 期望：phone/id_card/bank_account 等字段被脱敏
```

### 4.3 安全扫描

```bash
bash scripts/security_scan.sh
# 查看报告：evidence/m2-p6/security/
```

---

## 5. 部署验证

### 5.1 干净环境 Docker 部署

```bash
# 构建并启动
docker compose -f deploy/docker-compose.yml build
DKWS_API_KEYS="qa-key:qa_key_at_least_16_chars:read|execute" \
  docker compose -f deploy/docker-compose.yml up -d

# 等待启动
sleep 10

# 健康检查
curl -s http://localhost:8106/v1/health | python -m json.tool

# 停止
docker compose -f deploy/docker-compose.yml down
```

### 5.2 Makefile 目标验证

```bash
make deploy-build
make deploy-verify
make deploy-down
```

---

## 6. NFR 基线确认

```bash
# 快速 NFR 测试
bash scripts/run_nfr_baseline.sh --quick

# 查看报告
cat evidence/m2-p6/nfr_baseline_report.md

# 确认报告标注"基线值，非 SLA 承诺"
```

---

## 7. QA 结果记录模板

```markdown
# M2 Independent QA 报告

## QA 信息
- QA 人员：[姓名/ID]
- 日期：YYYY-MM-DD
- 环境：[OS / Python / Docker 版本]
- 分支：develop (commit 47fd7d6)

## 测试结果

| 验证项 | 预期 | 实际 | 判定 |
|--------|------|------|------|
| 全量测试 | 813 passed | ? | ? |
| M2-P1 E2E | 20/20 PASS | ? | ? |
| M2-P2 E2E | 27/27 PASS | ? | ? |
| M2-P3 E2E | 25/25 PASS | ? | ? |
| M2-P4 E2E | 22/22 PASS | ? | ? |
| M2-P5 E2E | 25/25 PASS | ? | ? |
| Docker 构建 | 成功 | ? | ? |
| 安全扫描 | 报告生成 | ? | ? |

## 失败记录

| ID | 验证项 | 失败详情 | 严重度 |
|----|--------|----------|--------|

## 结论

[QA_PASS / QA_FAIL / QA_PASS_WITH_CONDITIONS]
```

---

## 8. 已知问题清单（QA 需确认）

| # | 开发侧声明 | QA 需确认 |
|---|-----------|-----------|
| 1 | Kùzu 测试失败因包未安装，安装后 813 passed | 在 QA 环境复现 |
| 2 | 安全扫描仅报告不阻塞 CI | 确认是否可接受 |
| 3 | mypy 仅报告不阻塞 | 确认是否可接受 |
| 4 | NFR 资源基线不完整 | 确认是否阻塞 |
| 5 | 响应脱敏默认关闭 | 确认是否可接受 |
| 6 | /livez /readyz 在 dev profile 下可能不可用 | 确认行为 |
