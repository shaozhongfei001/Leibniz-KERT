# ADR-016：受控混合 Skill Runtime（候选）

> 状态：CANDIDATE_AWAITING_OWNER
> 日期：2026-08-26
> 工作流：DKWS-C-MIXED-ARCH-REMEDIATION-01

## Context

DKWS 需要 Skill 动态加载、热更新、ToolCall 与 Python/Shell 沙箱执行。
独立评审认为原方案 C 边界不清晰，要求修改为 C′。

## Decision

采用 C′ 受控混合架构：

- Python Core 是唯一公共入口和控制面
- Java Skill Runtime 是 DKWS 内部无状态可替换执行器
- GITS 只通过 Python Core 公共 HTTP 访问
- 通用 Python/Shell 使用 OS 级 Sandbox Runner
- 方案 B 作为正式回退路线

## Alternatives

- A：全量 Java：拒绝，重写成本高且无收益证据
- B：全量 Python：保留为回退/当前实施基线
- C：原始混合：拒绝直接批准，权威分裂

## 代价

- 双语言双运行时运维复杂度
- 需要内部契约、双栈 SBOM、统一可观测
- 需要 Java Runtime 准入 POC-2

## 风险

- 控制面分裂
- Sandbox 未通过前工具不可用
- 框架能力被误认为生产能力

## 回滚

- 若 POC-2/Sandbox 未通过，回退到 Python-only 方案 B

## Owner 待决策

- 批准 C′ 目标架构
- 批准 Java Runtime 部署形态
- 批准 GITS 仅走公共 HTTP
- 批准 bwrap/nsjail 沙箱路线
