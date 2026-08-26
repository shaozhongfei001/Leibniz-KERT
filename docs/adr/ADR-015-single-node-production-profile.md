# ADR-015：单机单实例单租户生产 profile（候选）

> 状态：CANDIDATE_AWAITING_OWNER
> 日期：2026-08-26

## 背景

为避免过早引入分布式复杂度，首个生产候选限定单机。

## 决策

- 单机、单实例、单租户
- 文件系统知识权威源
- SQLite Runtime Store
- 独立 Worker 进程
- 不引入 PostgreSQL、外部消息队列、Kubernetes、多实例
- 多实例/多租户仅在未来触发条件下评估

## 影响

- 多租户正式方案采用目录级命名空间，不在 Phase 1 实施
- NFR/容量/备份恢复按单机设计
- 未来扩展需重新评估文件系统原子 rename、Kùzu 并发、SQLite 写竞争

## 关闭条件

- Owner 批准
- Phase 1 单机验收通过
