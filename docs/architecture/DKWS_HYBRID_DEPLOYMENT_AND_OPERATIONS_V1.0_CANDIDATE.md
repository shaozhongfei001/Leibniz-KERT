# DKWS 混合部署与运维设计 V1.0（候选）

> 状态：CANDIDATE
> 日期：2026-08-26
> 工作流：DKWS-C-MIXED-ARCH-REMEDIATION-01

## 1. 进程拓扑

```text
DKWS 产品
├── Python Core :8106
├── Java Skill Runtime :18080（内部，仅 loopback/内网）
├── Sandbox Runner（bwrap 子进程）
└── Worker（Python 异步任务）
```

## 2. 网络与 TLS 边界

> 依据：ADR-013、ADR-015；Tech Lead 于 M2-P1 评审确认（2026-08-27）。
> 实现细节见 `DKWS_RUNTIME_HARDENING_M2P1.md`。

### 2.1 TLS 终止位置

**TLS 由外层反向代理（Nginx/网关）终止，DKWS 应用层不实现 TLS。**

```text
外部调用方（GITS 等）
   │  HTTPS
   ▼
Nginx / 网关  ← TLS 终止、证书管理、可选 mTLS
   │  HTTP（回环或内网）
   ▼
Python Core :8106  ← 唯一公共入口；API Key 认证、限流、大小/并发限制
   │  HTTP（仅 loopback/内网）
   ▼
Java Skill Runtime :18080  ← 内部可替换执行器，不对外
```

### 2.2 监听地址要求

| 组件 | 监听地址 | 说明 |
|---|---|---|
| Nginx / 网关 | `0.0.0.0:443` | 唯一对外暴露的端口 |
| Python Core | `127.0.0.1:8106` 或内网地址 | **不得**直接暴露到公网 |
| Java Skill Runtime | `127.0.0.1:18080` | 仅 loopback/内网，不对外 |
| Worker | 无监听端口 | — |

Python Core 的 `DKWS_BIND_HOST` 参与生产 profile 校验：
若绑定非回环地址且未启用 API Key 认证，**启动即被拒绝**（fail-fast）。

> 注意：`scripts/serve_skill_service.py` 的 `--host` 默认为 `0.0.0.0`（沿用既有行为）。
> 生产部署**必须**显式传入 `--host 127.0.0.1`，或确保防火墙/安全组只放通网关来源。

### 2.3 代理头信任策略

**当前默认不信任 `X-Forwarded-For`**，限流分桶键取连接对端 IP。

理由：若无条件信任该头，调用方可伪造其值获得无限分桶，从而绕过限流。
代价：当 DKWS 部署在反向代理之后时，所有请求的对端 IP 均为代理地址，
按 IP 分桶会退化为全局共享配额。

缓解：为已认证请求按 API Key 分桶（优先级高于 IP），故正常调用方不受此退化影响；
仅匿名/未认证流量共享按代理 IP 的配额——这对 DoS 防护而言是可接受的保守行为。

未来如需按真实客户端 IP 分桶，需引入显式配置（如 `DKWS_TRUSTED_PROXY`
或可信代理 IP 列表）后方可信任该头。**此项当前未实现。**

### 2.4 代理侧建议配置

反向代理应承担以下职责，避免与应用层重复或冲突：

- 终止 TLS，仅放通 TLS 1.2+
- 转发至 `127.0.0.1:8106`，保留 `X-API-Key` 请求头
- 代理层大小限制不小于应用层 `DKWS_MAX_REQUEST_BYTES`，避免应用层 413 被代理层提前遮蔽
- 可选 mTLS 校验调用方证书（应用层不实现，属网关职责）
- 不要剥离或改写认证请求头

## 3. 部署顺序

1. 启动 Python Core
2. 启动 Java Skill Runtime
3. Python Core readiness 检查 Java Runtime 可用性
4. 启动 Worker

## 4. 故障降级

| 故障 | 行为 |
|---|---|
| Java Runtime 不可达 | 依赖 Java Runtime 的 Skill fail-closed；知识只读能力继续 |
| Sandbox 不可用 | 工具类 Skill fail-closed |
| 模型不可用 | 按 Skill 策略返回 DEGRADED 或 fail-closed |
| Python Core 不可用 | 全部不可用 |
| 反向代理不可达 | 外部全部不可用；Python Core 仍可经回环自检 |

## 5. 资源预算

- Python Core：建议 1-2 CPU / 2-4GB
- Java Runtime：建议 1-2 CPU / 2-4GB JVM heap
- Sandbox 并发：建议 2-4
- 单机总预算：4-8 CPU / 8-16GB（待 Owner 批准）

## 6. 可观测

- 统一 JSON 日志字段：requestId, traceId, tenantId, skillId
- W3C Trace Context 贯通
- Metrics：HTTP、Skill、Tool、Model、Sandbox
- 告警：Java Runtime down、Sandbox 失败率、磁盘、JVM heap

## 7. 发布与版本

- 一个发布 manifest，包含 Python/Java/契约/Skill hash
- 两套构建，一个发布 Gate
- 双 SBOM
- 升级顺序：先 Java Runtime，再 Python Core，或按兼容矩阵

## 8. 备份

- 备份 Python Runtime Store、知识资产、受控 Skill 包
- Java Runtime 无状态，不备份

## 9. 回滚

- 保留上一版本发布 manifest
- 回滚顺序：Python Core → Java Runtime → Skill 版本
