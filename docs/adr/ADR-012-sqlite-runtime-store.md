# ADR-012：引入 SQLite Runtime Store（候选）

> 状态：CANDIDATE_AWAITING_OWNER
> 日期：2026-08-26
> 替代/变更：对 DKWS-SPEC-001 中“不引入数据库”约束的受控变更

## 背景

当前幂等、evidence、异步任务、Gate 审计等可变运行态依赖进程内存或散落文件，重启易失、不可恢复。
独立评审确认需要持久化运行控制面。

## 决策

引入 SQLite 作为第一阶段 Runtime Store，仅保存可变运行态，不保存知识权威源。

## 边界

- 知识权威源仍为 03_core 文件资产
- 04_serve 仍为可重建投影
- SQLite 不进入 01_raw/02_work/03_core/04_serve 知识数据目录
- 单机单实例首选 SQLite；PostgreSQL 仅在未来触发条件下评估

## 影响

- 需要更新规格验收口径和测试
- 需要 Schema migration、备份恢复、权限、WAL 配置
- 需要 Owner 批准

## 关闭条件

- Owner 批准本 ADR
- 规格/验收口径更新
- SQLite 工程基线测试通过
