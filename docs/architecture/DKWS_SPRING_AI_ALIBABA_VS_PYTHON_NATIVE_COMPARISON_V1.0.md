# DKWS 生产级方案对比：Spring AI Alibaba vs Python 原生

> 版本：V1.0
> 日期：2026-08-26
> 状态：CANDIDATE
> 依据：独立架构评审、Spring AI Alibaba 调研、POC 实测结果、GITS A+B 联动需求
> 关联文档：
> - `DKWS_ADAPTER_FIRST_TECH_STACK_V1.1.md`
> - `DKWS_SPRING_AI_ALIBABA_SKILL_RUNTIME_POC_V1.0.md`
> - `DKWS_SPRING_AI_ALIBABA_SKILL_RUNTIME_POC_V1.0.md` 同目录 POC_RESULT.md

---

## 1. 背景与目标

DKWS 需要演进为独立、可生产、可审计的知识工程服务端，并支持：

- Skill 动态导入、热加载、热更新
- Tool_call 与 Skill 深度绑定
- Python / Shell 沙箱执行
- 多数据源适配（图、JDBC/OLAP、Parquet、RAG、非结构化）
- GITS 作为普通 API 客户端完成 A+B 联动
- 企业级稳定性、成熟项目引用、高性能、国产化

本文件对比两条技术路线：

- **方案 A：Spring AI Alibaba 技术栈**
- **方案 B：Python 原生技术栈**
- **方案 C：混合架构（推荐候选）**

---

## 2. 评估输入

### 2.1 POC 实测结果（Spring AI Alibaba 1.1.2.0）

| 验证项 | 结果 |
|---|---|
| 服务启动 | ✅ PASS |
| Skill 自动发现 | ✅ PASS |
| Skill 列表 API | ✅ PASS |
| 热加载触发 | ✅ PASS |
| DeepSeek 普通对话 | ✅ PASS |
| read_skill 调用 | ✅ PASS |
| groupedTools 深度绑定 | ✅ PASS |
| PythonTool 沙箱执行 | ❌ 环境配置未完成（GraalVM Python CoreHome/StdLibHome 缺失） |
| ShellTool 执行 | ❌ ShellSession 未初始化 |

结论：**Spring AI Alibaba 的 Skills + read_skill + groupedTools 主链路可用；沙箱执行属于环境配置问题，可修复。**

### 2.2 独立评审结论

- 当前 DKWS Python 工程是原型/联调底座，生产就绪度不足
- 不建议推翻重构，建议增量演进
- 独立服务端边界必须闭合
- GITS 采用 A+B，B 先 fail-closed，A 再恢复真实 HTTP

### 2.3 GITS 联动需求

- GITS 是 Java/Spring Boot 工作台
- 需要调用 DKWS 的 R1、供应链图谱、SP-20、SP-21、Gate、assemblyTrace
- 需要真实 HTTP 调用、超时/重试/鉴权/契约错误处理
- 需要避免本地 Mock/H2 冒充 DKWS 结果

---

## 3. 方案 A：Spring AI Alibaba 技术栈

### 3.1 架构形态

```text
DKWS（Java/Spring Boot）
├── Spring AI Alibaba Agent Framework
│   ├── FileSystemSkillRegistry
│   ├── SkillsAgentHook(autoReload)
│   ├── groupedTools
│   ├── PythonTool(GraalVM)
│   └── ShellTool2
├── KnowledgeSource Adapters（Java 实现）
├── SQLite Runtime Store
├── REST API
└── GITS 直接消费
```

### 3.2 能力映射

| 需求 | Spring AI Alibaba 支持度 |
|---|---|
| Skill 导入 | ✅ FileSystemSkillRegistry / ClasspathSkillRegistry |
| 热加载 | ✅ autoReload(true) |
| Skill 优化热更新 | ✅ 修改文件后 reload 生效 |
| Tool_call 绑定 | ✅ SkillsAgentHook + groupedTools |
| Python 沙箱 | ⚠️ PythonTool，但 GraalVM 环境需配置 |
| Shell 沙箱 | ⚠️ ShellTool2，需初始化 ShellSessionManager |
| 多数据源适配 | 需要自研 Java Adapter，生态较 Python 弱 |
| GITS 联动 | ✅ 同 Java 技术栈，可共享 DTO/契约/工具链 |

### 3.3 优点

- Skill 运行态能力开箱即用，社区/官方已有成熟模式
- 与 GITS 同为 Java/Spring，联动成本低
- 企业级 Java 生态成熟，适合银行现有技术栈
- 国产化友好：Spring AI Alibaba 为阿里开源
- 热加载、ToolCall、渐进式披露已被官方验证

### 3.4 缺点

- 与现有 DKWS Python 代码不兼容，需重写或新增 Java 服务
- Python 数据生态（PyArrow、DuckDB、Kùzu、Pandas）在 Java 侧需要重新选型
- 双运行时/双语言运维复杂度高
- GraalVM Python 对第三方库支持有限
- 当前 POC 沙箱执行未完全通过
- 若整个 DKWS 重写为 Java，工作量大、风险高

---

## 4. 方案 B：Python 原生技术栈

### 4.1 架构形态

```text
DKWS（Python/FastAPI）
├── SkillRegistry（自研）
│   ├── importlib 动态加载
│   ├── 版本目录热切换
│   └── watchdog（开发态）
├── ToolRegistry（自研 Tool ABI）
├── Sandbox
│   ├── nsjail / bubblewrap
│   └── subprocess + seccomp
├── KnowledgeSource SPI
│   ├── PyArrow / DuckDB / Kùzu
│   ├── SQLAlchemy / JDBC bridge
│   └── HTTP SDK（Milvus / 图数据库 / RAG）
├── SQLite Runtime Store
└── REST API
```

### 4.2 能力映射

| 需求 | Python 原生支持度 |
|---|---|
| Skill 导入 | ✅ 自研 `importlib` + 版本目录 |
| 热加载 | ✅ 自研版本切换；开发态 watchdog |
| Skill 优化热更新 | ✅ 版本化原子切换 |
| Tool_call 绑定 | ✅ 自研 Tool ABI，可深度绑定 |
| Python 沙箱 | ✅ nsjail/bubblewrap + 系统 Python |
| Shell 沙箱 | ✅ nsjail/bubblewrap + 命令白名单 |
| 多数据源适配 | ✅ 数据生态最丰富 |
| GITS 联动 | ⚠️ 纯 HTTP，需要维护跨语言契约 |

### 4.3 优点

- 与现有 DKWS 完全一致，无需重写
- 数据/知识生态最强：PyArrow、DuckDB、Kùzu、Pandas、PaddleOCR
- 单语言、单运行时，运维简单
- 适配器优先原则更自然
- 沙箱可控性强，可用 OS 级隔离
- 增量演进风险低

### 4.4 缺点

- Skill 运行态（热加载、ToolCall、沙箱）需要自研，工程量大
- 没有 Spring AI Alibaba 那样现成的 Skills 体系
- 与 GITS 跨语言，需要更严格的契约与测试
- 热加载/沙箱要做到企业级稳定需要较多打磨
- Python 企业级治理（如统一 Agent 框架）相对分散

---

## 5. 方案 C：混合架构（推荐候选）

### 5.1 架构形态

```text
┌────────────────────────────────────────────┐
│                DKWS Python Core            │
│  - 知识资产 / 五层工作区                    │
│  - KnowledgeSource SPI                     │
│  - 数据适配（Parquet/Kùzu/图/JDBC/RAG）    │
│  - REST API / OpenAPI                      │
│  - SQLite Runtime Store                    │
│  - 审计 / 可观测                           │
└───────────────┬────────────────────────────┘
                │ HTTP / gRPC
┌───────────────▼────────────────────────────┐
│        Spring AI Alibaba Skill Runtime     │
│  - FileSystemSkillRegistry                 │
│  - SkillsAgentHook / groupedTools          │
│  - PythonTool / ShellTool2                 │
│  - Skill 热加载 / ToolCall                 │
└────────────────────────────────────────────┘
```

### 5.2 边界

- **DKWS Python Core**：知识权威源、数据访问、知识服务、审计、对外 OpenAPI
- **Spring AI Alibaba Skill Runtime**：Skill 仓库、热加载、ToolCall、Python/Shell 沙箱执行
- GITS 作为客户端，优先调用 DKWS Python Core 的统一 API；Skill Runtime 可作为 DKWS 的内部组件或独立部署服务
- 若 GITS 需要更深度集成，也可将 Spring AI Alibaba Skill Runtime 部署在 GITS 侧，但需保持与 DKWS 契约一致

### 5.3 优点

- 保留 Python 数据/知识生态
- 获得 Spring AI Alibaba 成熟的 Skill 运行态
- 与 GITS Java 技术栈可共享 Spring AI 生态
- 各自在擅长领域深耕，避免“全栈重写”
- 可逐步落地：先 Python Core + HTTP，再接入 Java Skill Runtime

### 5.4 缺点

- 双语言、双运行时，运维和部署复杂度上升
- 需要定义 Python Core 与 Java Skill Runtime 之间的稳定内部契约
- 需要两套 CI/CD、监控、日志体系
- 人员技能要求更高

---

## 6. 详细对比表

| 维度 | Spring AI Alibaba | Python 原生 | 混合 |
|---|---|---|---|
| 与现有 DKWS 兼容 | 低，需重写/新增 | 高 | 中高 |
| Skill 热加载 | 高（官方） | 中（自研） | 高 |
| ToolCall 绑定 | 高（官方） | 中（自研） | 高 |
| Python/Shell 沙箱 | 中（GraalVM 需配置） | 高（nsjail 可控） | 高（可选用 Python 沙箱） |
| 数据/知识生态 | 中 | 高 | 高 |
| GITS 联动 | 高（同 Java） | 中（HTTP） | 高（可 Java 直连 Skill Runtime） |
| 企业级成熟度 | 高（Java/Spring + 阿里） | 中高（Python 生态成熟但自研多） | 高 |
| 国产化 | 高（阿里开源） | 中（组件可选国产） | 高 |
| 运维复杂度 | 中 | 低 | 高 |
| 交付风险 | 高（重写） | 中（自研 Skill 体系） | 中（分期落地） |
| 长期可维护性 | 中高 | 高 | 高（边界清晰时） |

---

## 7. GITS 联动分析

### 7.1 如果采用 Spring AI Alibaba 全栈

- GITS 与 DKWS Skill Runtime 同为 Java/Spring，可直接复用 Spring AI 的 ToolCallback、ChatClient、DTO
- 联动成本最低
- 但 DKWS 数据层若也用 Java，需要放弃现有 Python 数据栈

### 7.2 如果采用 Python 原生

- GITS 通过 HTTP 调用 DKWS
- 需要维护 OpenAPI/JSON Schema 契约
- 跨语言团队协作成本略高
- 但 DKWS 数据能力最强

### 7.3 如果采用混合

- GITS 优先调用 DKWS Python Core 的 OpenAPI
- 若需要 Skill 深度联动，可让 GITS 直连 Spring AI Alibaba Skill Runtime 的内部 API
- 两边都可发挥优势
- 需要定义清晰的内部契约与鉴权

---

## 8. 生产级考量

### 8.1 企业级稳定性

- Spring AI Alibaba：Java/Spring 生态成熟，阿里持续维护；但版本较新，需观察
- Python 原生：FastAPI/SQLite/nsjail 均成熟；自研 Skill 体系需加强测试
- 混合：各自使用成熟组件，稳定性取决于集成质量

### 8.2 技术栈成熟项目引用

- Spring AI Alibaba：已有阿里云生态、社区示例、Skills 官方能力
- Python 原生：FastAPI、PyArrow、DuckDB、Kùzu 等均有大量生产使用
- 混合：两套成熟生态叠加

### 8.3 高性能

- Spring AI Alibaba：Java 高并发能力强，GraalVM Python 执行性能一般
- Python 原生：数据/列式处理性能强；Skill 沙箱可用系统级子进程
- 混合：数据性能走 Python，Skill 编排走 Java，各取所长

### 8.4 国产化

- Spring AI Alibaba：阿里开源，国产化友好
- Python 原生：可通过国产组件（Paddle、Milvus、Doris、openGauss）实现国产化
- 混合：两者都支持国产化

### 8.5 安全与运维

- Spring AI Alibaba：需管理 JVM、GraalVM、Shell 会话安全
- Python 原生：需管理 nsjail/bubblewrap、Python 子进程安全
- 混合：两套安全基线都要建设

---

## 9. 选择建议

### 9.1 推荐：混合架构（方案 C）

理由：

1. **不推翻现有 DKWS Python 核心**，符合独立评审“增量演进”结论
2. **Skill 运行态采用 Spring AI Alibaba**，避免自研热加载/ToolCall 体系
3. **数据/知识层保留 Python**，最大化 PyArrow/DuckDB/Kùzu 等能力
4. **GITS 联动灵活**：可先走 Python Core HTTP，后续按需直连 Java Skill Runtime
5. **可分期落地**：Phase 1 先完成 Python Core 生产加固；Phase 2 再接入 Java Skill Runtime

### 9.2 备选：Python 原生（方案 B）

如果团队希望**单一语言、单一运行时**，且愿意投入自研 Skill 运行态，可以选择 Python 原生。
该方案更符合“适配器优先、轻量部署”，但 Skill 热加载/沙箱需要更多工程投入。

### 9.3 不推荐：全量 Spring AI Alibaba（方案 A）

除非 Owner 明确接受**重写 DKWS 数据/知识层为 Java**，否则不推荐。
当前 DKWS Python 数据资产和知识管道已经具备较高完成度，重写风险远大于收益。

---

## 10. 落地路线

| 阶段 | 内容 |
|---|---|
| Phase 0 | 完成本文档决策；确定 Python Core + Java Skill Runtime 边界 |
| Phase 1 | Python Core 生产加固（Auth/TLS/SQLite/可观测/备份） |
| Phase 2 | 接入 Spring AI Alibaba Skill Runtime，先跑通 Skill 热加载/ToolCall |
| Phase 3 | 修复 Python/Shell 沙箱执行（GraalVM 配置或 nsjail） |
| Phase 4 | GITS A+B 真实联动与 UAT |
| Phase 5 | 多数据源适配与多租户治理 |

---

## 11. 风险与决策点

| 风险/决策 | 说明 |
|---|---|
| 双运行时运维 | 需要两套 CI/CD、监控、日志；需 Owner 接受 |
| Java Skill Runtime 部署形态 | 独立服务 or GITS 内嵌，需 Owner 决策 |
| GraalVM Python 沙箱 | 若无法满足，则改用 nsjail + 系统 Python |
| 内部契约 | Python Core 与 Java Skill Runtime 之间需定义稳定 API |
| 团队技能 | 需要同时具备 Python 与 Java/Spring 能力 |

---

## 12. 结论

- **Spring AI Alibaba** 是优秀的 Java 侧 Skill 运行态方案，POC 已验证 read_skill + groupedTools 主链路
- **Python 原生** 更适合保留 DKWS 现有数据/知识能力，但 Skill 运行态需自研
- **混合架构** 是当前最平衡的生产级方案：
  - DKWS Python Core 负责知识与数据
  - Spring AI Alibaba Skill Runtime 负责 Skill 编排与 ToolCall
  - GITS 作为统一客户端

最终是否采用混合架构，需 Owner 确认双运行时运维成本和 Java Skill Runtime 部署边界。
