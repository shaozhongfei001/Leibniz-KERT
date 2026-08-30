# JR-1 失败记录

任务包：JR-1（内部契约双端测试）
分支：`feature/jr1-internal-contract-dual-tests`
记录纪律：先记录失败，再修复（`docs/development/RULES.md`）。

---

## FAIL-JR1-01：Python 契约测试误用 `IdempotencyHit.replayed`

- 发现时间：2026-08-30
- 阶段：JR-1 §6.2 Python 侧契约测试
- 命令：`.venv/bin/python -m pytest tests/contract/internal -q`
- 失败用例：
  `test_internal_contract_negative.py::TestIdempotencyConflictSemantics::test_runtime_store_rejects_same_key_different_payload`
- 报错：
  ```
  AttributeError: 'IdempotencyHit' object has no attribute 'replayed'
  ```
- 根因：测试假设 `RuntimeStore.remember()` 返回值带 `replayed` 布尔标记；
  实际 `IdempotencyHit` 字段为
  `scope / idem_key / request_hash / status / response / created_at`，
  「是否复放」由「记录是否已存在」体现，而非独立字段。
  属测试侧对既有实现的错误假设，**不是** Python Core 缺陷。
- 处置：修正测试，改用 `lookup()` 判定记录存在性 +
  `remember()` 返回记录一致性来表达复放语义；不修改 `runtime_store.py`。
- 状态：已修复，复测通过。

---

## FAIL-JR1-02：Java 侧内部契约 DTO 与契约 Schema 漂移

- 发现时间：2026-08-30
- 阶段：JR-1 §6.3 Java 侧契约测试
- 现象：`poc/spring-ai-alibaba-skill-runtime` 的
  `ExecutionResult` / `ToolCallReceipt` / `ModelCallReceipt` / `RuntimeCapabilities`
  为 POC2 阶段裁剪版，字段集小于
  `docs/contracts/internal/schemas/*.json` 的 `required` 集合，
  直接序列化无法通过契约校验。
- 根因：POC2 只验证「能跑通」，未做契约对齐；契约 Schema 后续独立演进，
  双方无自动校验闸门，形成静默漂移。
- 处置：新增 Java 侧契约测试（`contract/` 包）以 networknt
  `json-schema-validator` 直接加载 `docs/contracts/internal/schemas/`
  真实 Schema 校验；补齐 DTO 缺失字段使其可生成合规 JSON。
  DTO 补齐仅在内部 Runtime 边界内，不改对外公共 API。
- 状态：已修复，复测通过。
