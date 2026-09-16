# DKWS Java Runtime（Spring AI Alibaba）正式接入计划 V1.0

> 日期：2026-08-28
> 决策：Owner 选择 **选项 A：继续推进 C′ 混合架构**
> 状态：CANDIDATE
> 目标：将 Spring AI Alibaba Skill Runtime 从 `poc/` 提升为 DKWS 产品内部正式组件，并完成与 Python Core 的双运行时集成。

---

## 1. 目标架构

```text
GITS / 客户端
   │ HTTP
   ▼
DKWS Python Core（唯一公共入口、控制面、知识/数据权威源）
   │ 内部 ExecutionPlan
   ▼
Java Skill Runtime（Spring AI Alibaba，内部可替换执行器）
   │ 受控调用
   ▼
OS Sandbox Runner（bwrap/nsjail）
```

强制边界：

- Java Runtime 不对外
- Java Runtime 不直接写 SQLite
- Java Runtime 不直接访问五层工作区
- GITS 仍只走 Python Core
- 生产禁用 autoReload
- 未通过 Sandbox Gate 前 Tool 默认关闭

---

## 2. 工作分解

### WP1：内部契约双端化

- Python consumer/provider contract tests
- Java consumer/provider contract tests
- 契约 hash 双端一致
- 未知字段、版本不兼容、同 key 不同 payload 测试

交付物：

- `docs/contracts/internal/` 双端测试
- 契约 hash 更新

### WP2：Java Runtime 产品化改造

- 从 `poc/spring-ai-alibaba-skill-runtime` 迁移为正式模块，例如 `runtime/java-skill-runtime/`
- Maven 多模块或独立工程
- 固定 Spring Boot / Spring AI / Spring AI Alibaba / JDK / GraalVM 版本
- 生成 SBOM、依赖锁、漏洞扫描
- 明确无状态、可替换执行器边界

### WP3：Python Core → Java Runtime 调用链

- Python Core 实现 `ExecutionPlan` 生成
- 实现内部 HTTP 客户端（loopback + 服务认证）
- 实现超时、重试、熔断、取消
- 实现 Java Runtime 不可达时 Skill 级 fail-closed

### WP4：Java Runtime ExecutionResult / Receipts

- 实现 `ExecutionResult` 返回
- 实现 `ToolCallReceipt`
- 实现 `ModelCallReceipt`
- 实现 Trace 贯通
- 实现输出大小限制

### WP5：Sandbox 生产化

- bwrap/nsjail Runner 正式化
- 安全负向用例：路径穿越、命令注入、网络、资源、超时、输出超限
- Sandbox profile hash
- 独立 Security QA

### WP6：部署拓扑

- docker-compose 增加 `java-runtime` 服务
- systemd 增加 `dkws-java-runtime.service`
- 统一启动顺序、readiness 依赖
- 统一发布 manifest

### WP7：统一可观测性

- Python Core 与 Java Runtime 统一日志字段
- W3C Trace 贯通
- Metrics 统一命名
- 告警覆盖 Java Runtime down / Sandbox 失败

### WP8：双栈 CI/CD

- GitHub Actions 增加 Java build/test
- 双栈 SBOM 汇总
- 一个发布 Gate
- 镜像构建包含 Java Runtime

### WP9：GITS A+B

- 仍只走 Python Core 公共 HTTP
- 不暴露 Java Runtime
- 完成 R1、供应链、SP-20、SP-21、Gate E2E

### WP10：端到端验收

- Python Core → Java Runtime → Sandbox 全链路
- 故障注入：Java 不可达、Sandbox 不可用、模型失败
- 性能与资源基线
- 独立 QA 复跑

---

## 3. 依赖关系

```text
WP1（契约）→ WP2（Java 产品化）→ WP3/WP4（调用链）
WP5（Sandbox）可与 WP2 并行
WP6/WP7/WP8 依赖 WP2/WP3/WP4
WP9 可并行，不依赖 Java Runtime
WP10 依赖 WP3-WP8
```

---

## 4. 建议任务包

| 任务包 | 内容 | 预计 |
|---|---|---|
| JR-1 | 内部契约双端测试 | 1-2 周 |
| JR-2 | Java Runtime 产品化 + Docker 化 | 2-3 周 |
| JR-3 | Python Core ExecutionPlan 客户端 | 1-2 周 |
| JR-4 | ExecutionResult / Receipts 回传 | 1-2 周 |
| JR-5 | Sandbox 安全 Gate | 2-3 周 |
| JR-6 | 统一部署/可观测/CI | 2-3 周 |
| JR-7 | 端到端验收 + QA | 2 周 |

---

## 5. 退出标准

- Python/Java 双端契约测试通过
- Java Runtime 进入 docker-compose 并随产品启动
- Python Core 可下发 ExecutionPlan 并接收 Receipts
- Sandbox 安全 Gate 通过
- 统一日志/Trace/Metrics 贯通
- GITS 仍只走 Python Core
- 独立 QA 复跑通过
- Owner 批准进入内网试点

---

## 6. 风险

| 风险 | 缓解 |
|---|---|
| 双栈运维复杂 | 统一发布 manifest、统一 OTel、统一告警 |
| GraalVM Python 兼容性 | 默认使用 bwrap/nsjail + 系统 Python |
| Java Runtime 版本漂移 | 固定版本、SBOM、依赖锁 |
| Sandbox 未过 Gate | 生产保持 Tool 禁用，不影响 Python Core |
| 分支冲突 | CodeBuddy 与 DeepSeek-Harness 使用独立分支 + PR |

---

## 7. 下一步

1. 创建 `feature/dkws-java-runtime-integration` 分支
2. 从 JR-1 开始：内部契约双端测试
3. 同步更新 `DKWS_SPRING_AI_ALIBABA_INTEGRATION_STATUS_V1.0.md` 为“决策 A，推进中”
