# DKWS 需求ID实施矩阵、风险与阶段计划

> 依据：`文件目录型数据知识服务模拟平台_详细需求与详细设计_V1.0.md`（DKWS-SPEC-001 V1.0，状态 `DRAFT_CANDIDATE`）。
> 本文不改变规格状态：OWNER_APPROVED=NO、BASELINED=NO、IMPLEMENTED=NO、ACCEPTED=NO。

## 1. 需求ID实施矩阵

| 需求组 | 覆盖需求 | 设计章节 | 实现模块 | 测试 | 状态 |
|---|---|---|---|---|---|
| FR-WS-* | WS-001..005 | 7、8、12 | `domain/workspace`、`infrastructure/fs` | `tests/unit/test_workspace.py` | 待实施 |
| FR-ING-* | ING-001..006 | 9.1、11.4 | `application/ingest`、`domain/assets/manifest` | `tests/integration/test_ingest.py` | 待实施 |
| FR-DATA-* | DATA-001..005 | 10.1、10.7、11.4 | `application/process_data`、`infrastructure/parquet` | `tests/integration/test_process_data.py` | 待实施 |
| FR-DOC-* | DOC-001..005 | 9.2-9.4、11.5 | `application/parse_doc`、`domain/assets/document` | `tests/integration/test_parse_doc.py` | 待实施 |
| FR-KNW-* | KNW-001..006 | 9.5-9.8、11.6-11.7 | `application/extract`、`domain/assets/knowledge`、`domain/rules/dsl` | `tests/integration/test_extract_review.py` | 待实施 |
| FR-PUB-* | PUB-001..005 | 9.16-9.18、11.8-11.9 | `application/publish`、`domain/assets/release`、`infrastructure/atomic` | `tests/integration/test_publish.py` | 待实施 |
| FR-SRV-* | SRV-001..008 | 10、12-15 | `application/services`（data/graph/search/rule/evidence/extraction） | `tests/e2e/test_services.py` | 待实施 |
| FR-CTL-* | CTL-001..006 | 9.9-9.20、17 | `application/jobs`、`infrastructure/logging`、`domain/quality` | `tests/integration/test_control.py` | 待实施 |
| NFR-001/012 | 可移植/兼容 | 8、20 | `infrastructure/fs`（无符号链接指针、原子重命名） | 跨平台单测 | 待实施 |
| NFR-002/003 | 确定性/可恢复 | 8.4、11、18.4 | 规范化哈希、重建命令 | `tests/recovery/test_rebuild.py` | 待实施 |
| NFR-004/010 | 审计/观测 | 9.11-9.20 | 任务、日志、报告 | `tests/integration/test_control.py` | 待实施 |
| NFR-005..007 | 性能/容量/并发 | 6、10、15 | Parquet 查询、内存邻接、锁 | `tests/performance/` | 待实施 |
| NFR-008/009 | 安全/隐私 | 16 | 路径安全、脱敏日志 | `tests/security/test_security.py` | 待实施 |
| NFR-011 | 可测试性 | 18 | 合法/非法/边界/回归样例 | `tests/contract/` | 待实施 |

## 2. 风险与对策

| 风险 | 等级 | 对策 |
|---|---|---|
| 规格规模大，单会话交付有限 | 高 | 按 P0→P9 分层，每阶段以测试为退出证据；核心链路优先 |
| Parquet 逻辑哈希一致性（列序/排序/时间） | 中 | 固定列序与排序键的规范化比较函数（§8.4） |
| 文档解析依赖外部库（PDF/DOCX） | 中 | 文本级解析器 + 可插拔适配器；无外部依赖时确定性样例适配器兜底（§1.6） |
| 模型适配器不可用 | 中 | 确定性抽取适配器完成 E2E（§6.3） |
| 状态机/门禁被绕过 | 高 | 状态转换校验、G0-G5 门禁集中在 application 层，CLI/HTTP 同层调用 |
| 路径穿越/符号链接逃逸 | 高 | 统一 `WorkspaceWriter` 路径规范化 + 允许根校验（§16.1） |
| 发布/回滚原子性 | 中 | 临时目录 + 原子重命名 + CURRENT 指针最后切换（§8.7、11.8） |

## 3. 阶段计划

| 阶段 | 内容 | 退出条件 |
|---|---|---|
| P0 | 项目骨架、需求追踪、工作区初始化 | `dkws init/inspect` 测试通过 | ✅ |
| P1 | Markdown 合同框架、Schema、通用校验 | 所有 MD 合法/非法样例通过 | ✅ |
| P2 | Raw 接入、Manifest、哈希、任务控制 | G0 测试通过 | ✅ |
| P3 | 结构化数据清洗与 Parquet | 对账、拒绝、血缘通过 | ✅ |
| P4 | 文档登记、规范化、稳定切片 | G1 文档测试通过 | ✅ |
| P5 | 知识候选、审核决定、冲突检测 | G2 测试通过 | ✅ |
| P6 | Core 发布、Release、Current、回滚 | G3 及故障注入通过 | ✅ |
| P7 | 实体/关系/声明/片段/向量/图谱/规则投影 | G4 及可重建性通过 | ✅ |
| P8 | CLI 服务命令、HTTP API | G5 关键服务通过 | ✅ |
| P9 | 安全、恢复、E2E 黄金场景、文档 | QA 候选包完整 | ✅ |
| P10 | DSH 动态插件：知识服务平台 Web 界面 | 插件可运行并操作工作区 |

## 4. 规格要求遵守声明

- 不引入数据库、消息队列、分布式平台；
- 权威源为契约化 MD；Parquet/JSON 仅为投影/交换；
- 模型输出强制 `CANDIDATE`；
- 每类文件同时交付 Schema、解析、校验、合法/非法样例、测试；
- 每个写命令实现路径安全、锁、临时写、原子提交、幂等、失败恢复；
- 保留需求—设计—测试追踪，用机器测试证据替代叙述。
