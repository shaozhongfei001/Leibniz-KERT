# DKWS Spring AI Alibaba 引入现状与差距梳理

> 日期：2026-08-28
> 角色：Architect
> 状态：CANDIDATE
> 结论：**Spring AI Alibaba 尚未真正引入 DKWS 产品主干，原定 C′ 混合架构目标未实现。**
> 2026-08-28 Owner 决策：**继续推进 C′ 混合架构（选项 A）**，正式接入计划见 `DKWS_JAVA_RUNTIME_INTEGRATION_PLAN_V1.0.md`。

## 1. 原始目标（C′ 混合架构）

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
OS Sandbox Runner（Python/Shell）
```

关键要求：

- Java Skill Runtime 是 DKWS 产品内部独立进程
- 不对 GITS 开放
- 不直接写 SQLite
- 不直接访问五层工作区
- 生产禁用 autoReload
- 未通过 Sandbox Gate 前 Tool 默认关闭

## 2. 当前实际状态

### 2.1 产品主干

- 当前 `develop` / `main` / `feature/m2-remaining` 均为 **Python-only 生产加固路线**。
- M2 里程碑主要完成：
  - Python Core 认证、限流、大小限制
  - SQLite Runtime Store
  - 持久化 Worker
  - 可观测性
  - 数据分类与脱敏
  - 备份恢复
  - 部署 / CI / NFR（部分未提交）
- 没有 Java Runtime 服务进入部署拓扑。

### 2.2 Spring AI Alibaba 存在位置

- 仅存在于：

```text
poc/spring-ai-alibaba-skill-runtime/
```

- 属于 POC 实验代码。
- 当前 `deploy/docker-compose.yml` 只有：

```text
api
worker
backup
```

- 没有 `java-runtime` 服务。
- `Makefile` 没有 Java/Maven 构建目标。
- Python Core 没有调用 Java Runtime 的 HTTP 客户端或 ExecutionPlan 下发逻辑。

### 2.3 POC-2 状态

- POC-2 实现了：
  - 两个 Skill 动态注册
  - Skill→Tool 动态绑定
  - Skill 版本化安装/激活/回滚
  - 内部 API 认证
  - bwrap Sandbox smoke
- 但：
  - 真实 ToolCall Receipt 未闭合
  - Sandbox 安全负向用例未完成
  - Python Core→Java Runtime E2E 未实现
  - 未进入产品部署
  - 未通过独立安全 QA

## 3. 差距清单

| 原始目标 | 当前状态 | 差距 |
|---|---|---|
| Java Runtime 作为内部执行器 | 仅 POC | 未接入产品 |
| Python Core 下发 ExecutionPlan | 无 | 未实现 |
| Java Runtime 返回 ExecutionResult + Receipts | 无 | 未实现 |
| Java Runtime 部署 | 无 | docker-compose 无该服务 |
| Java Runtime 不直接写 SQLite | 是（POC） | 但未进入产品 |
| Sandbox Gate | 未通过 | 仅 smoke |
| GITS 公共 HTTP 联动 | 未完成 | A+B 未实现 |
| 统一双栈运维 | 未开始 | 无 Java 部署/监控 |

## 4. 结论

- 当前项目实质是 **Python-native（方案 B）生产加固**。
- Spring AI Alibaba 仍是 **POC 候选**，不是产品能力。
- 原定的 C′ 混合架构目标 **尚未实现**。

## 5. 后续决策

### 选项 A：继续推进 C′ 混合架构

需要启动 Phase 2：

- 将 Java Runtime 纳入部署拓扑
- Python Core 实现 ExecutionPlan 下发
- Java Runtime 实现 ExecutionResult/Receipts 回传
- 完成 Sandbox Gate
- 完成双栈 CI/CD/运维

### 选项 B：正式切换为 Python-native（方案 B）

- 将 Spring AI Alibaba POC 保留为参考/实验
- 产品主线继续 Python 自研 Skill/Tool 运行态
- 不再承诺 Java Runtime 作为生产组件

### 建议

如果当前团队和资源以 Python 为主，建议 **先明确选择 B 或 A**，避免“文档写了 C′，实际在做 B”的架构漂移。

若选择 A，下一步应先完成：

1. Python Core→Java Runtime 内部契约双端测试
2. Java Runtime 部署进 docker-compose
3. POC-2 真实 ToolCall Receipt
4. Sandbox 安全 Gate
5. GITS A+B 仍走 Python Core
