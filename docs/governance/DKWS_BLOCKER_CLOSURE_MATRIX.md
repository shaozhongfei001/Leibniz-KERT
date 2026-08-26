# DKWS Blocker 闭合矩阵（Phase 0 候选）

> 日期：2026-08-26
> 依据：独立评审报告 Blocker B-01 ~ B-06
> 状态说明：Phase 0 负责“设计与基线层面”闭合；机器证据闭合需后续 Phase/QA。

| ID | Blocker | Phase 0 要求 | 本包产出 | 闭合状态 |
|---|---|---|---|---|
| B-01 | 无鉴权、TLS、限流、大小限制 | 形成可实施安全基线、契约和验收标准 | ADR-013、OpenAPI v2 security、NFR、Phase 1 验收测试计划 | DESIGN_CLOSED；机器证据 OPEN |
| B-02 | 幂等/Evidence/Job/Gate 易失 | 形成 Runtime Store、状态机、恢复设计 | ADR-012、RUNTIME_CONTROL_PLANE、OpenAPI job/idempotency | DESIGN_CLOSED；实现/证据 OPEN |
| B-03 | 独立服务端边界未闭合 | 形成独立安装、配置、运行、验收设计 | ADR-014、INDEPENDENT_SERVER_BOUNDARY、A+B 交接 | DESIGN_CLOSED；干净环境验证 OPEN |
| B-04 | v1.3/v1.4 非机器契约唯一权威源 | 建立 OpenAPI/Schema 候选及兼容策略 | contracts/openapi + schemas + 哈希脚本 | DESIGN_CLOSED；双方合同 hash 对齐 OPEN |
| B-05 | 缺少源码/提交锚点/原始测试/安全证据 | 建立缺失证据清单，不得伪造闭合 | EVIDENCE_MANIFEST、状态基线、冲突登记 | OPEN（证据缺失） |
| B-06 | GITS 当前未实际调用 DKWS | 形成 A+B 交接；保持 UAT_PASS=NO | GITS_DKWS_A_PLUS_B_HANDOFF.md | OPEN（需 GITS commit/diff/UAT） |

## 关闭条件

- B-01: Phase 1 安全测试、DAST、真实 401/403/429/413 证据。
- B-02: 重启/并发/篡改/重放/断电测试。
- B-03: 干净主机/容器离线安装启动与功能验证。
- B-04: DKWS/GITS 双方同一 contract hash 与 consumer contract test 报告。
- B-05: 受控实现审计包 + 独立 QA 复跑。
- B-06: GITS→DKWS 真实 E2E + 故障空态 + Owner UAT。

## 当前未关闭 Major

M-01 至 M-16 已在独立评审报告中列出。Phase 0 在设计中覆盖了 M-01~M-15 的设计/基线部分；M-16 需要 GITS/DKWS 业务事实冲突优先级合同，仍待契约 v2 与 GITS 对齐。
