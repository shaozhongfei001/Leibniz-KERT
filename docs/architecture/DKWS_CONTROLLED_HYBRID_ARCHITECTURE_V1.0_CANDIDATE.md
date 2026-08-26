# DKWS 受控混合架构 C′ V1.0（候选）

> 状态：CANDIDATE
> 日期：2026-08-26
> 工作流：DKWS-C-MIXED-ARCH-REMEDIATION-01
> 依据：`docs/dd/DKWS_生产级混合架构独立评审报告_2026-08-26_V1.0.md`

## 1. 目标

将 DKWS 建设为“一个产品、一个公共入口、一个控制面、一个可替换内部执行器”的受控混合架构。

## 2. 组件边界

| 组件 | 职责 | 是否对外 |
|---|---|---|
| DKWS Python Core | 唯一公共 HTTP/OpenAPI 入口；身份/授权/幂等/Job/Gate/审计/Runtime Store；五层知识资产与数据源控制面 | 是 |
| Java Skill Runtime | 内部无状态执行器；按 ExecutionPlan 执行 Skill/read_skill/groupedTools/模型调用；返回 Result+Receipts | 否 |
| Sandbox Runner | OS 级隔离执行 Python/Shell；bwrap/nsjail | 否 |
| GITS | DKWS 公共 API 客户端 | 是 |

## 3. 强制约束

1. GITS 只能访问 Python Core 公共 API。
2. Java Runtime 不直接写 SQLite，不直接访问五层工作区。
3. Java Runtime 不自行决定客户权限、Gate、Prompt、模型或预算。
4. 生产禁用 `autoReload` 扫描可写目录。
5. 通用 Python/Shell 默认走 OS Sandbox；未通过安全 Gate 前生产禁用。
6. Shell 不接受自由字符串，使用固定 executable + argv Schema。

## 4. 内部调用

```text
Python Core --ExecutionPlan--> Java Runtime --SandboxTask--> Sandbox Runner
Python Core <--ExecutionResult+Receipts-- Java Runtime
```

内部契约见 `docs/contracts/internal/`。

## 5. Skill 生命周期

```text
上传到 staging
→ 校验 manifest/hash/signature
→ 安全扫描
→ 版本化安装
→ 显式 activate
→ 原子切换 CURRENT
→ 可 rollback
→ 活动版本与旧版本并发隔离
```

## 6. 故障降级

- Java Runtime 不可达：依赖 Java Runtime 的 Skill 返回 fail-closed；Python Core 只读能力继续可用。
- Sandbox 不可用：涉及执行工具的 Skill 返回明确错误。
- 模型不可用：按 Skill 策略返回 DEGRADED 或 fail-closed。

## 7. 回退方案

若 POC-2 或 Sandbox Gate 未通过，DKWS 继续按 Python-only（方案 B）演进，不阻塞生产加固。

## 8. Owner 待决策

- 是否批准 C′ 为目标架构候选
- 是否批准 Java Runtime 作为 DKWS 内部独立进程
- 是否批准 GITS 仅走公共 HTTP
- 是否批准 bwrap/nsjail 作为默认 Sandbox
- 是否批准方案 B 作为正式回退路线
