# Agent 角色定义

| 角色 | 职责 | 权限边界 |
|---|---|---|
| Owner | 最终决策、批准基线、批准 UAT | 最高权限 |
| Tech Lead | 架构、ADR、复杂设计、整改执行 | 可改 DKWS，不可改 GITS，不可自行签署 QA |
| Feature Pilot | 日常功能开发、测试、文档 | 按任务单开发 |
| Independent QA | 独立复跑测试、签署 QA | 不参与实现 |
| Security QA | 安全测试、沙箱审查 | 独立于开发 |
| Contract Owner | OpenAPI/JSON Schema/契约 hash | 维护契约 |
