# DKWS 生产演进计划 V2.1（候选）

> 状态：CANDIDATE
> 日期：2026-08-26
> 工作流：DKWS-C-MIXED-ARCH-REMEDIATION-01

## 阶段顺序

```text
Phase 0A：C′ 架构、ADR、内部契约、状态冲突收敛
Phase 1：Python Core 生产加固
并行：GITS B→A 公共 HTTP 联动
Gate C-RUNTIME-01：Java Runtime POC-2
Phase 2：Java Runtime 作为 DKWS 内部执行器接入
Gate C-SANDBOX-02：OS Sandbox 独立安全准入
Phase 3：受控启用 Tool、知识源和路由治理
Phase 4：按 Owner 决策扩展企业治理/多租户
Phase 5：按容量和 HA 触发条件扩展
```

## 关键原则

- GITS A+B 不等待 Java Runtime
- GITS 公共配置保持 `DKWS_BASE_URL` / `DKWS_API_KEY`
- 不向 GITS 暴露 `JAVA_SKILL_RUNTIME_BASE_URL`
- 方案 B 为正式回退路线

## Gate 定义

- C-RUNTIME-01：POC-2 十二项准入全部有证据
- C-SANDBOX-02：OS Sandbox 安全测试 + 独立安全 QA
