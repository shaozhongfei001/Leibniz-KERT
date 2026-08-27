# M2-P6 证据目录 — 部署 / CI/CD / NFR 基线

> 任务包：M2-P6（M2 最后一公里）
> 分支：feature/m2-remaining
> 日期：2026-08-27
> 执行方式：长程无人值守多角色 SubAgent 协作

## 任务包范围

| 子项 | 内容 | 状态 |
|------|------|------|
| M2.7 | 部署完善（Dockerfile 验证、.dockerignore、Makefile、冒烟测试、部署文档） | ✅ PASS |
| M2.8 | CI/CD（GitHub Actions、依赖锁、SBOM、安全扫描） | ✅ PASS |
| M2.10 | NFR 基线（延迟/吞吐/并发基准测试 + 报告） | ✅ PASS |

## Gate 验收

### G1: M2.7 部署

| 检查项 | 结果 |
|--------|------|
| Dockerfile 多阶段构建、非 root、HEALTHCHECK | ✅ 已验证，无需修复 |
| .dockerignore 排除非必要文件 | ✅ 新增 |
| docker-compose.yml 含 backup 一次性服务 | ✅ 新增 profiles: [backup] |
| Makefile 部署目标（build/up/down/logs/backup/restore/smoke-test/verify） | ✅ 新增 8 个目标 |
| deploy/verify_deployment.py 健康端点验证 | ✅ 新增 |
| deploy/smoke_test.sh 冒烟测试 | ✅ 新增 |
| deploy/README.md 完整部署指南 | ✅ 新增 |

### G2: M2.8 CI/CD

| 检查项 | 结果 |
|--------|------|
| .github/workflows/ci.yml 4 个 job（lint/test/security/build） | ✅ 新增 |
| requirements-lock.txt 依赖锁 | ✅ 35 个精确版本 |
| scripts/generate_sbom.sh SBOM 生成 | ✅ CycloneDX 格式 |
| scripts/security_scan.sh 安全扫描 | ✅ pip-audit + bandit |
| scripts/ci_setup.sh CI 环境初始化 | ✅ 支持 --with-security/--with-lint/--full |
| 无密钥环境 CI 可通过 | ✅ DKWS_PROFILE=dev |

### G3: M2.10 NFR 基线

| 检查项 | 结果 |
|--------|------|
| scripts/nfr_benchmark.py 基准测试框架 | ✅ 延迟/吞吐/并发/资源 |
| scripts/load_generator.py 负载生成 | ✅ 8 种场景 |
| scripts/nfr_report.py 报告生成 | ✅ Markdown 格式 |
| scripts/run_nfr_baseline.sh 一键测试 | ✅ 无人值守 |
| evidence/m2-p6/nfr_baseline.md 基线指标 | ✅ 含实际测试值 |
| 报告标注"基线值，非 SLA 承诺" | ✅ |

### G4: 集成验证

| 检查项 | 结果 |
|--------|------|
| 全量测试 434 passed, 2 failed | ✅ 2 个 Kùzu 失败为既有问题（非 M2-P6 回归） |
| 无 src/ 源码修改 | ✅ |
| 新增脚本可执行权限 | ✅ |

## 交付物清单

### 新增文件

```
.dockerignore
.github/workflows/ci.yml
Makefile
requirements-lock.txt
deploy/README.md
deploy/verify_deployment.py
deploy/smoke_test.sh
scripts/ci_setup.sh
scripts/generate_sbom.sh
scripts/security_scan.sh
scripts/load_generator.py
scripts/nfr_benchmark.py
scripts/nfr_report.py
scripts/run_nfr_baseline.sh
evidence/m2-p6/nfr_baseline.md
evidence/m2-p6/nfr_baseline_report.md
evidence/m2-p6/nfr_benchmark_results.json
evidence/m2-p6/sbom/
evidence/m2-p6/security/
```

### 修改文件

```
deploy/docker-compose.yml  — 新增 backup 服务
```

## NFR 基线关键数据

| 指标 | 值 | 备注 |
|------|-----|------|
| /v1/health P50 | 1.94ms | 确定性模式 |
| /v1/health 10并发 RPS | 547.80 | |
| Skill 同步 P50 | ~5s | 确定性模式，含模拟延迟 |
| Skill 异步提交 P50 | 858ms | |
| 100并发错误率 | 0% | /v1/health |

## 已知限制

1. Kùzu 图数据库测试 2 个失败（既有问题，非 M2-P6 引入）
2. NFR 资源基线（内存/SQLite）需 root 权限或手动采集
3. /livez 和 /readyz 在当前运行版本不可用，NFR 脚本已做兼容回退
4. mypy 初次集成仅报告不阻塞，后续逐步收紧
5. 安全扫描（pip-audit/bandit）仅生成报告不阻塞 CI

## 结论

M2-P6 任务包全部 3 个子项 PASS。M2 里程碑 10/10 子项完成（7 个前期 + 3 个本任务包）。
