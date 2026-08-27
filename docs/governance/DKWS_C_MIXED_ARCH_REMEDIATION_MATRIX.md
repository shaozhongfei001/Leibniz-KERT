# DKWS C′ 混合架构整改追踪矩阵

> 工作流：DKWS-C-MIXED-ARCH-REMEDIATION-01
> 日期：2026-08-26
> 依据：`docs/dd/DKWS_生产级混合架构独立评审报告_2026-08-26_V1.0.md`
> 状态语义：OPEN / IN_PROGRESS / DESIGN_CLOSED / POC_CLOSED / MACHINE_VERIFIED / PENDING_INDEPENDENT_QA / BLOCKED

## C-Blocker

| ID | 等级 | 评审发现 | 当前证据 | 影响文件 | 整改动作 | 验证方法 | 关闭证据 | 状态 | Owner |
|----|------|----------|----------|----------|----------|----------|----------|------|-------|
| C-B01 | Blocker | Java Runtime 部署形态、产品所有权和权威边界未决，且材料允许 GITS 直连 | 对比文档、POC 源码、HANDOVER | 新 C′ 架构候选、ADR-016、内部契约、GITS 交接 V1.1 | 形成 C′ 架构，唯一公共入口 Python Core，删除 GITS 直连 Java 路径 | 架构评审 + ADR Owner 批准 | ADR-016、边界矩阵、部署拓扑 | IN_PROGRESS | Owner/Tech Lead |
| C-B02 | Blocker | Python Core—Java Runtime 无机器内部契约 | 现有 contracts 无 internal | docs/contracts/internal/* | 建立内部 OpenAPI/Schema + 契约 hash + 双端 contract tests | JSON Schema 校验、OpenAPI 解析、contract tests | contract bundle manifest + 测试日志 | IN_PROGRESS | Contract Owners |
| C-B03 | Blocker | PythonTool/ShellTool 沙箱执行失败，安全配置未闭合 | POC_RESULT、源码 ShellCommandGuard 未接入 | Sandbox Runner POC、POC-2 | 生产默认关闭；用 bwrap/nsjail 做 OS Sandbox POC | 安全负向用例、资源限制、独立安全 QA | sandbox-security-tests.log + 独立 QA | IN_PROGRESS | Security Lead |

> **C-B03 状态高估更正（2026-08-27，Owner 授权）**：执行报告 V1.0 曾将 C-B03 标为 `MACHINE_TESTS_PASS_PENDING_INDEPENDENT_SECURITY_QA`，与本矩阵 `IN_PROGRESS` 自相矛盾，且引用日志不存在、20 项安全负向用例 0 项执行。现统一为 `IN_PROGRESS`，详见冲突登记册 C-20。C-B03 关闭前提不变：真实 OS Sandbox 执行 + 安全负向用例通过 + 资源限制通过 + **独立安全 QA 复核**（Tech Lead 不得自签）。
| C-B04 | Blocker | POC 未完成 DKWS 集成、真实 Tool receipt、生产热更新/回滚和故障恢复 | POC 无 tests、无 receipts | POC-2 | 实现 staging/activate/rollback、动态 Tool 绑定、receipts、自动化测试 | 自动化测试 + 原始日志 + 重放 | POC2_EVIDENCE_MANIFEST.json | IN_PROGRESS | Tech Lead |
| C-B05 | Blocker | 方案 C 未纳入独立服务边界、演进 V2、NFR、验收计划和 ADR | 多文档冲突 | 新候选文档 + supersession map | 统一 Phase 0 基线和 supersession map | 冲突登记、追溯矩阵 | 冲突清零、追溯矩阵 | IN_PROGRESS | Architecture Owner |

## C-Major

| ID | 等级 | 评审发现 | 当前证据 | 影响文件 | 整改动作 | 验证方法 | 关闭证据 | 状态 | Owner |
|----|------|----------|----------|----------|----------|----------|----------|------|-------|
| C-M01 | Major | POC README/HANDOVER/源码/POC_RESULT 状态不一致 | 多文件 | POC README、HANDOVER、POC_RESULT | 新 POC2_PLAN/RESULT 明确状态，旧 README 标记 superseded | 文档一致性检查 | supersession map + 状态文件 | IN_PROGRESS | Tech Lead |
| C-M02 | Major | groupedTools 只绑定 demo-skill，未形成动态 Tool Policy | AgentConfig.java | POC-2 | 从 Skill manifest 动态构建工具集合 | 两个 Skill 不同工具绑定测试 | 自动化测试 | IN_PROGRESS | Tech Lead |
| C-M03 | Major | Skill 上传先删旧目录、版本硬编码、无原子激活和回滚 | SkillUploadService.java | POC-2 | staging + version + hash + activate + rollback | 生命周期测试 | 测试日志 | IN_PROGRESS | Tech Lead |
| C-M04 | Major | toolCalls/trace 未真正解析和持久化 | SkillExecutionService.java | POC-2 | 输出结构化 Tool/Model Receipts | 响应含 receipts | 测试日志 | IN_PROGRESS | Tech Lead |
| C-M05 | Major | Python 与 Java 都存在 LLM/Agent 能力，职责可能重复 | 架构文档 | C′ 架构 | Core 拥有策略，Java 执行并回传 | 架构评审 | ADR | DESIGN_CLOSED_PENDING_OWNER | Architecture Owner |
| C-M06 | Major | 双运行时无统一发布、监控、日志、升级、回滚和资源预算 | 无部署文档 | Hybrid Deployment doc | 建立统一部署运维候选 | 文档评审 | 部署文档 | IN_PROGRESS | SRE/Tech Lead |
| C-M07 | Major | 成熟引用/性能/国产化缺少证据 | 无基准 | NFR/证据 | 补证据清单，不宣称达标 | 证据清单 | evidence manifest | OPEN | Owner/QA |
| C-M08 | Major | 核心对比文档 Phase 编号与 V2 冲突，且 GITS A+B 被推迟 | 多文档 | Evolution V2.1 | 以 V2 为主线，A+B 前移 | 文档一致性 | supersession map | IN_PROGRESS | Tech Lead |
| C-M09 | Major | Java 依赖版本组合、锁定、SBOM、漏洞/许可证缺失 | pom.xml | POC-2 证据 | 依赖树、SBOM、扫描 | 构建证据 | dependency-tree.txt, sbom | IN_PROGRESS | Build/Security |
| C-M10 | Major | 无 Java Runtime 故障降级矩阵 | 无 | Hybrid Deployment doc | 定义 Skill 级降级 | 文档评审 | 部署文档 | IN_PROGRESS | Tech Lead |
| C-M11 | Major | POC 无自动化测试、原始运行日志和受控 commit | 无 tests | POC-2 | 补测试与证据 | 自动化测试 | 测试日志 | IN_PROGRESS | Tech Lead |
| C-M12 | Major | Phase 0 证据清单 verified 状态矛盾 | Evidence manifest | Evidence manifest | 统一状态口径 | 审计 | 新 manifest | IN_PROGRESS | Tech Lead |

## C-ME 待补充材料

| ID | 待补充材料 | 责任方 | 状态 |
|----|-----------|--------|------|
| C-ME01 | DKWS Python Core 受控源码 commit/manifest | Tech Lead | OPEN（当前已 init Git，待 push） |
| C-ME02 | POC 受控 commit、完整原始日志、环境清单 | Tech Lead | IN_PROGRESS |
| C-ME03 | POC 自动化测试及覆盖率 | Tech Lead | IN_PROGRESS |
| C-ME04 | Python Core—Java Runtime 内部 OpenAPI/Schema | Contract Owners | IN_PROGRESS |
| C-ME05 | 混合架构 ADR、组件所有权和部署拓扑 | Architecture Owner | IN_PROGRESS |
| C-ME06 | Skill 包格式、签名、版本、激活、回滚合同 | Skill Runtime Lead | IN_PROGRESS |
| C-ME07 | nsjail/bubblewrap POC、威胁模型、逃逸/资源/命令注入测试 | Security Lead | IN_PROGRESS |
| C-ME08 | 双栈 SBOM、许可证、漏洞和支持周期 | Build/Security | OPEN |
| C-ME09 | Spring AI Alibaba/Spring AI/Spring Boot/JDK/GraalVM 兼容矩阵 | Java Platform Lead | OPEN |
| C-ME10 | 单机资源与性能基准 | Performance QA | OPEN |
| C-ME11 | 国产 OS/CPU/JDK/密码套件/依赖/LLM 兼容实测矩阵 | Infrastructure/Security | OPEN |
| C-ME12 | 统一日志、Metrics、Trace、告警与运行手册 | SRE | OPEN |
| C-ME13 | 备份、恢复、升级、回滚、Java Runtime 故障注入证据 | Reliability QA | OPEN |
| C-ME14 | GITS→DKWS 最终 HEAD HTTP trace、合同 hash、A+B UAT 原始报告 | GITS/DKWS/UAT Owner | OPEN |
| C-ME15 | 可核验的生产案例、维护策略和支持承诺 | Architecture/Procurement | OPEN |
