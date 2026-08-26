# DKWS Runtime Control Plane V1.0（候选）

> 状态：CANDIDATE
> 日期：2026-08-26
> 依据：独立评审报告 B-02 / 4.4 / M-03~M-05
> 关联 ADR：ADR-012

## 1. 定位

Runtime Control Plane 是独立于知识权威源的可变运行态层。首期使用 SQLite。
SQLite **不是**知识权威源；知识权威源仍为 03_core 文件资产。

## 2. SQLite 保存内容

| 数据 | 说明 |
|---|---|
| idempotency_records | 请求幂等 |
| evidence_state | Evidence 元数据/索引 |
| jobs | 异步 Job 与状态 |
| tool_call_receipts | 工具调用回执 |
| gate_audit | 闸门审计镜像 |
| tenant_identity | 租户/身份映射（单租户固定值） |
| rate_limit_counters | 限流计数 |
| prompt_model_policy_refs | Prompt/模型/策略版本引用 |
| cost_token_usage | Token 与成本 |
| operation_audit | 操作审计 |

## 3. SQLite 工程基线

- WAL 模式
- `busy_timeout` 建议 5000ms
- 同步级别：`NORMAL`（配合 WAL）；关键审计可 `FULL`
- 文件权限：仅服务账户可读写（`0600`）
- Schema migration：版本表 + 顺序迁移脚本 + 回滚脚本
- 备份：`sqlite3 .backup` 或等价在线备份；不得直接拷贝热文件
- 恢复：恢复 Runtime DB 后需与 Core/CURRENT 一致性点校验

## 4. 幂等设计

### 4.1 唯一键

```text
tenant_id + operation + idempotency_key
```

### 4.2 表结构（候选）

```sql
CREATE TABLE idempotency_records (
    tenant_id       TEXT NOT NULL,
    operation       TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    state           TEXT NOT NULL,
    payload_hash    TEXT NOT NULL,
    result_reference TEXT,
    created_at      TEXT NOT NULL,
    expires_at      TEXT NOT NULL,
    PRIMARY KEY (tenant_id, operation, idempotency_key)
);
```

### 4.3 语义

- 首次请求：保存 `payload_hash` 与 `IN_PROGRESS` 状态
- 同 key 同 payload：等待完成或返回已保存结果
- 同 key 不同 payload：拒绝，返回 `409 IDEMPOTENCY_CONFLICT`
- 过期后允许新请求

## 5. Job 状态机

```text
PENDING -> RUNNING -> SUCCESS
   |          |
   v          v
 FAILED -> DEAD
   ^
   | retry
```

支持 `CANCELLED`（若实现取消）。

### 5.1 原子领取

```sql
UPDATE jobs
SET status='RUNNING', worker_id=:w, lease_until=:lease, attempt=attempt+1
WHERE job_id=:id AND status='PENDING' AND (lease_until IS NULL OR lease_until < now)
```

### 5.2 租约与心跳

- Worker 启动时注册 heartbeat
- 任务处理中续租
- 租约过期后任务可被其他 Worker 重新领取（at-least-once）
- 外部副作用需幂等键

### 5.3 超时与重试

- 每次尝试有 deadline
- 失败按指数退避重试
- 超过 max_retries 进入 DEAD
- DEAD 可人工重放或归档

### 5.4 崩溃恢复

- 启动时扫描 RUNNING 且 lease 过期 → 重新入队
- 启动时扫描 RUNNING 且 worker 心跳存活 → 不重复执行
- 结果写入 `result_reference` 与文件/DB 后标记 SUCCESS

## 6. Evidence 状态设计

- 不使用客户端自由时间戳作为唯一依据
- 应记录 `tenant_id + customer_id + skill/domain + knowledge_version/hash`
- 字段至少：`last_seen_release_id`、`last_seen_content_hash`、`updated_at`

## 7. Gate 审计

- `gate_audit` 记录客户、闸门、决策、主体、请求 ID、时间
- 必须经过认证；`decidedBy` 不能由未认证调用方自报
- 权威闸门状态仍由 GITS 管理；DKWS 只保留可审计镜像

## 8. 事务边界

- 领取 Job 必须在一个事务内
- 更新 Job 状态 + 写入审计必须在一个事务内（或补偿）
- 幂等记录与业务副作用不能跨越不可回滚外部副作用，需使用副作用键

## 9. 数据保留与删除

- 幂等记录：默认 10 分钟，可配置
- Job：默认 30 天，可配置
- 审计：按银行制度，默认候选 180 天
- 删除需支持软删除/归档与法律保全
- 具体数值 `PENDING_OWNER_DECISION`

## 10. 失败行为

- Runtime DB 不可写：服务应 fail-closed，拒绝需要持久化的请求
- 知识资产只读失败：不影响 Runtime DB，但应标记 degraded
- 磁盘满：健康检查降级，拒绝写操作
