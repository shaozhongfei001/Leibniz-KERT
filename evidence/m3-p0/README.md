# M3 Phase 0 证据目录 — API 契约 / Adapter 参考 / 故障注入 / E2E 准备

> 任务包：M3-P0（Phase 0 预置工作）
> 分支：develop
> 日期：2026-08-28
> 执行方式：长程无人值守多角色 SubAgent 协作

## 任务包范围

| 子项 | 内容 | 状态 |
|------|------|------|
| 3.1 | 公共 API 契约确认 + OpenAPI spec | ✅ PASS |
| 3.2 | GITS Adapter 参考实现（Python + curl） | ✅ PASS |
| 3.3 | 故障注入框架（chaos_test.py + chaos_injector.py） | ✅ PASS |
| 3.4 | E2E 测试准备（verify_m3_e2e.py + 配置 + 模板） | ✅ PASS |

## Gate 验收

### G1: API 契约确认

| 检查项 | 结果 |
|--------|------|
| DKWS 端点提取完整 | ✅ 7 个已实现 + 5 个待实现 |
| GITS 适配器分析完整 | ✅ 4 个适配器 + 配置 + 超时参数 |
| OpenAPI 3.0.3 规范 | ✅ 11 paths, 28 schemas, YAML 语法验证通过 |
| 契约差异报告 | ✅ 高度兼容，5 项待协调 |

### G2: GITS Adapter 参考

| 检查项 | 结果 |
|--------|------|
| Python DkwsClient | ✅ 同步/异步/轮询/健康/闸门，仅标准库 |
| curl 参考脚本 | ✅ 5 个脚本（list/execute_sync/execute_async/poll/health） |
| 错误处理最佳实践 | ✅ fail-closed + 指数退避 + 超时配置 + 错误码映射 |

### G3: 故障注入框架

| 检查项 | 结果 |
|--------|------|
| chaos_injector.py | ✅ 10 种故障类型，安全机制（自动恢复/超时清理） |
| chaos_test.py | ✅ 4 层 11 项故障场景，仅标准库 |
| run_chaos_test.sh | ✅ 一键无人值守 |

### G4: E2E 测试准备

| 检查项 | 结果 |
|--------|------|
| verify_m3_e2e.py | ✅ 5 个场景（R1/SP-20/SP-21/供应链/闸门） |
| m3_e2e_config.yaml | ✅ URL/Key/超时配置 |
| e2e_report_template.md | ✅ 步骤/预期/实际/判定 |

### G5: 集成验证

| 检查项 | 结果 |
|--------|------|
| 全量测试 | ✅ 813 passed, 0 failed |
| OpenAPI YAML 语法 | ✅ 修复后通过 |
| Python 语法 | ✅ 全部通过 |
| 无 src/ 源码修改 | ✅ |
| 无 GITS 仓库修改 | ✅ |

## 交付物清单

```
specs/dkws-openapi-v1.yaml                           # OpenAPI 3.0.3 规范
docs/integration/DKWS_GITS_CONTRACT_DIFF.md           # 契约差异报告
examples/gits_adapter/python/dkws_client.py           # Python 客户端
examples/gits_adapter/curl/list_skills.sh             # curl: 列出 Skill
examples/gits_adapter/curl/execute_skill_sync.sh      # curl: 同步执行
examples/gits_adapter/curl/execute_skill_async.sh     # curl: 异步提交
examples/gits_adapter/curl/poll_job.sh                # curl: 轮询 Job
examples/gits_adapter/curl/health_check.sh            # curl: 健康检查
examples/gits_adapter/README.md                       # 错误处理最佳实践
scripts/chaos_injector.py                             # 故障注入工具
scripts/chaos_test.py                                 # 故障测试框架
scripts/run_chaos_test.sh                             # 一键故障测试
scripts/verify_m3_e2e.py                              # M3 E2E 测试
scripts/m3_e2e_config.yaml                            # E2E 配置
evidence/m3-p0/e2e_report_template.md                 # 报告模板
```

## GITS 仓库关键发现

| 维度 | 详情 |
|------|------|
| 技术栈 | Java 21 + Spring Boot 3.5.16 + MyBatis + H2(dev)/MySQL(prod) + Vue 3 |
| 已有适配器 | DshHttpSkillExecutionAdapter、DshHttpSkillGateAdapter、V14DkwsIntegrationController |
| fail-closed | FallbackSkillExecutionAdapter 已实现（DKWS 不可达时拒绝） |
| Mock 路径 | MockLlmClient（LLM）、LoggingCrmWritebackChannel（CRM）、H2 内存库 |
| DKWS 配置 | dkws.base-url、dkws.api-key、dkws.skill-execute-path |

## 契约差异核心结论

**高度兼容**：GITS 已调用端点与 DKWS 实现完全匹配。

| 优先级 | 待协调项 |
|--------|----------|
| P1 | GITS 处理 ruleViolations、releaseBlockedUntil 闸门放行、SP-21 记忆持久化 |
| P2 | DKWS 实现 /v1/skills、API Key 认证、/metrics；GITS 处理 ruleViolations |

## 下一步：M3 Phase 1

Phase 0 预置工作已全部完成，可进入 Phase 1（需 GITS 仓库授权）：
- M3-P1：GITS 清理与 fail-closed（移除 Mock/H2 伪成功）
- M3-P2：HTTP Adapter 与集成
