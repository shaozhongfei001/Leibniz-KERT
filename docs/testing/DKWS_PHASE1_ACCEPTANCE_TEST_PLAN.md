# DKWS Phase 1 验收测试计划（候选）

> 日期：2026-08-26
> 状态：CANDIDATE
> 用途：Owner 批准 Phase 1 后执行的验收范围；不是当前已完成测试。

## 1. 范围

单机、单实例、单租户生产候选。验收覆盖安全、可靠性、可观测、运维、供应链和契约。

## 2. 安全验收

| 用例 | 预期 |
|---|---|
| 未带 API Key | 401 |
| 无效 API Key | 401/403 |
| 无权限 Skill | 403 |
| 超过限流 | 429 |
| 请求体超过上限 | 413 |
| 未配置 auth 但对外监听 | 生产 profile 拒绝启动 |
| TLS 终止 | 仅通过可信代理访问 |
| Gate audit 未认证 | 401/403 |
| SP-20 伪造 gateState | 服务端不信任，返回受控结果 |
| 敏感字段脱敏 | 日志/响应无明文密钥 |

## 3. 可靠性与恢复

| 用例 | 预期 |
|---|---|
| 同 requestId 同 payload 重放 | 返回首次结果 |
| 同 requestId 不同 payload | 409 IDEMPOTENCY_CONFLICT |
| 服务重启后幂等保留 | 命中持久化记录 |
| 异步 Job 重启恢复 | RUNNING 且 lease 过期重新入队 |
| Worker 重复领取 | 原子 claim 保证不重复 |
| Job 失败重试 | 按退避重试，超过进入 DEAD |
| 断电/磁盘满注入 | fail-closed，不损坏 Core/Runtime DB |
| 备份恢复 | 恢复后幂等/Job/审计可查 |
| 升级回滚 | 可回滚到前一版本 |

## 4. 可观测性

| 用例 | 预期 |
|---|---|
| `/livez` | 存活 200 |
| `/readyz` | 依赖正常 200，异常 503 |
| `/metrics` | Prometheus 文本，含基础 HTTP/Skill/LLM/队列/磁盘指标 |
| 结构化日志 | JSON 行，含 requestId/tenantId/skillId |
| 告警 | 磁盘、LLM、Job 失败、备份失败有告警规则 |
| Trace | OpenTelemetry 可导出，requestId 作为业务属性 |

## 5. 契约验收

| 用例 | 预期 |
|---|---|
| OpenAPI YAML 可解析 | PASS |
| JSON Schema 符合 meta-schema | PASS |
| 示例请求通过 Schema | PASS |
| 契约 hash 可重算 | 与归档一致 |
| v1 兼容 | 旧客户端可继续调用兼容层 |
| v2 未知字段 | 默认拒绝或显式 warning |

## 6. 供应链与部署

| 用例 | 预期 |
|---|---|
| 依赖锁 | 存在且可复现 |
| SBOM | 生成并可审 |
| 镜像扫描 | 无高危未修复 |
| 镜像签名 | 发布物可验签 |
| Docker Compose 启动 | 干净环境可启动 |
| systemd 启动 | 干净环境可启动 |
| 独立安装 | 不依赖外部智能体平台 |

## 7. 性能与容量（候选）

| 指标 | 目标 |
|---|---|
| API 读 P95 | ≤ 300ms（不含 LLM） |
| 最大并发 | 50 |
| 最大图谱 | 1000 节点 |
| SP-20 并发 | 2 |

具体数值以 Owner 批准的 NFR 为准。

## 8. 验收执行要求

- 使用真实命令，记录退出码与输出
- 外部不可用时标记 NOT_EXECUTED，不冒充 PASS
- 不得关闭门禁或吞掉失败
- 由独立 QA 在最终 commit 上复跑
