# M3 规划：GITS B→A 公共 HTTP 联动

> **版本**：1.0 DRAFT
> **日期**：2026-08-27
> **前置条件**：M2 已合并至 develop（commit 1d4c8eb），需 GITS 仓库授权
> **状态**：待 Owner 批准 + GITS 授权

---

## 0. M3 定位

M3 是 DKWS 从"独立可运行"走向"业务闭环"的关键里程碑。核心目标是让 GITS（前端业务系统）通过 HTTP 调用 DKWS 的 Skill 执行能力，形成完整的 B→A（Business→API）联动。

**硬阻塞**：M3 全部子项依赖 GITS 仓库授权。无授权则无法执行。

---

## 1. 子项拆分与验收标准

### M3.1 GITS 移除 Mock/H2 伪成功

| 属性 | 说明 |
|------|------|
| 目标 | 清除 GITS 中所有 Mock/H2 伪成功路径，确保 DKWS 不可用时 GITS 正确失败 |
| 依赖 | GITS 仓库读写权限 |
| 交付物 | GITS 代码变更 + 移除清单 |
| 验收标准 | 1) 无 Mock Skill 执行路径 2) 无 H2 内存数据库伪持久化 3) DKWS 不可用时 GITS 返回明确错误 |
| 风险 | GITS 代码量未知，Mock/H2 散布范围可能很广 |

### M3.2 fail-closed 空态

| 属性 | 说明 |
|------|------|
| 目标 | DKWS 服务未启动/空数据时，GITS 所有 Skill 调用必须 fail-closed（拒绝），不能静默降级到 Mock |
| 依赖 | M3.1 |
| 交付物 | fail-closed 测试 + 空态行为文档 |
| 验收标准 | 1) DKWS 未启动 → GITS 返回 503/连接拒绝 2) DKWS 启动但无 Skill → GITS 返回空列表 3) 无静默降级到 Mock |
| 风险 | GITS 可能有隐式降级逻辑 |

### M3.3 GITS→DKWS HTTP Adapter

| 属性 | 说明 |
|------|------|
| 目标 | 在 GITS 中实现 HTTP Adapter，调用 DKWS 公共 API（/v1/skills、/v1/jobs） |
| 依赖 | M3.1、M3.2 |
| 交付物 | GITS HTTP Adapter 代码 + 配置 + 集成测试 |
| 验收标准 | 1) GITS 可列出 DKWS Skill 2) GITS 可同步执行 Skill 3) GITS 可异步提交 Job 4) GITS 可查询 Job 状态 |
| 风险 | GITS 技术栈未知，Adapter 实现方式待确认 |

### M3.4 R1/供应链/SP-20/SP-21/Gate E2E

| 属性 | 说明 |
|------|------|
| 目标 | 端到端验证真实业务场景：R1 场景、供应链场景、SP-20 服务建议书、SP-21 交互记忆抽取 |
| 依赖 | M3.3 |
| 交付物 | E2E 测试脚本 + 执行报告 |
| 验收标准 | 1) R1 场景完整跑通 2) 供应链场景完整跑通 3) SP-20 生成服务建议书 4) SP-21 抽取交互记忆 5) Gate 检查全部 PASS |
| 风险 | 真实 LLM 调用可能不稳定，需确定性模式回退 |

### M3.5 故障注入与证据

| 属性 | 说明 |
|------|------|
| 目标 | 验证 GITS→DKWS 链路在故障场景下的行为：网络中断、DKWS 崩溃、超时、数据不一致 |
| 依赖 | M3.3 |
| 交付物 | 故障注入脚本 + 观测报告 |
| 验收标准 | 1) 网络中断 → GITS fail-closed 2) DKWS 崩溃 → GITS 检测到并重试 3) 超时 → GITS 超时处理 4) 数据不一致 → 检测到并告警 |
| 风险 | 故障注入可能影响共享环境 |

### M3.6 Owner UAT

| 属性 | 说明 |
|------|------|
| 目标 | Owner 在真实环境中执行用户验收测试 |
| 依赖 | M3.1~M3.5 全部完成 |
| 交付物 | UAT 检查清单 + Owner 签署 |
| 验收标准 | Owner 签署 UAT_PASS |
| 风险 | Owner 时间安排 |

---

## 2. 任务包拆分

### M3-P1：GITS 清理与 fail-closed（M3.1 + M3.2）

```
任务包：M3-P1
范围：M3.1 移除 Mock/H2、M3.2 fail-closed 空态
分支：feature/m3-p1-gits-cleanup（需在 GITS 仓库）
验收：无 Mock 路径、DKWS 不可用时 fail-closed
证据：evidence/m3-p1/
```

### M3-P2：HTTP Adapter 与集成（M3.3）

```
任务包：M3-P2
范围：M3.3 GITS→DKWS HTTP Adapter
分支：feature/m3-p2-http-adapter（需在 GITS 仓库）
验收：GITS 可调用 DKWS 全部公共 API
证据：evidence/m3-p2/
```

### M3-P3：E2E 业务验证（M3.4）

```
任务包：M3-P3
范围：M3.4 R1/供应链/SP-20/SP-21/Gate E2E
分支：feature/m3-p3-e2e（DKWS 仓库）
验收：4 个业务场景端到端跑通
证据：evidence/m3-p3/
```

### M3-P4：故障注入与 UAT（M3.5 + M3.6）

```
任务包：M3-P4
范围：M3.5 故障注入、M3.6 Owner UAT
分支：feature/m3-p4-resilience（DKWS 仓库）
验收：故障场景行为正确、Owner 签署 UAT
证据：evidence/m3-p4/
```

---

## 3. DKWS 侧预置工作（无需 GITS 授权）

以下工作可在 DKWS 仓库独立推进，为 M3 做准备：

### 3.1 公共 API 契约确认

- 确认 `/v1/skills`、`/v1/jobs`、`/v1/health` 接口稳定
- 生成 OpenAPI spec 供 GITS Adapter 参考
- 添加 API 版本头（`X-API-Version`）

### 3.2 GITS Adapter 参考实现

- 在 DKWS 仓库创建 `examples/gits_adapter/` 参考实现
- Python 版 + curl 版，供 GITS 团队参考
- 包含错误处理、重试、超时最佳实践

### 3.3 故障注入框架

- 扩展 M2-P5 的备份恢复测试框架
- 添加网络故障、进程崩溃、超时注入能力
- 创建 `scripts/chaos_test.py`

### 3.4 E2E 测试准备

- 创建 `scripts/verify_m3_e2e.py` 框架
- 定义 4 个业务场景的验证步骤
- 支持确定性模式（无需 LLM 密钥）

---

## 4. 风险与缓解

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| GITS 仓库未授权 | 高 | 阻塞 M3 全部 | 先做 §3 预置工作，推动 Owner 授权 |
| GITS 技术栈不兼容 | 中 | 延迟 | 提供多语言参考实现 |
| Mock/H2 散布广泛 | 中 | M3.1 工作量膨胀 | 先做代码审计，评估范围 |
| 真实 LLM 不稳定 | 中 | E2E 失败 | 确定性模式回退 + 重试 |
| Owner 时间不足 | 中 | M3.6 延迟 | 提前预约，准备自助 UAT 检查清单 |

---

## 5. 建议执行顺序

```
Phase 0（现在，无需 GITS）：
  ├── 3.1 公共 API 契约确认
  ├── 3.2 GITS Adapter 参考实现
  ├── 3.3 故障注入框架
  └── 3.4 E2E 测试准备

Phase 1（GITS 授权后）：
  ├── M3-P1 GITS 清理与 fail-closed
  └── M3-P2 HTTP Adapter 与集成

Phase 2（M3-P2 完成后）：
  └── M3-P3 E2E 业务验证

Phase 3（M3-P3 完成后）：
  ├── M3-P4 故障注入
  └── M3.6 Owner UAT
```

---

## 6. Owner 决策请求

1. **GITS 仓库授权**：是否授权 CodeBuddy 读写 GITS 仓库？
2. **GITS 技术栈确认**：GITS 使用什么语言/框架？
3. **M3 优先级**：是否先做 Phase 0 预置工作？
4. **业务场景确认**：R1/供应链/SP-20/SP-21 是否为 M3 必须验证的场景？
