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

---

## FAIL-JR1-03：`create_jr1_prs.sh` 谎报成功（base 未改却打印完成）

- 发现时间：2026-08-31
- 阶段：JR-1 收尾，修正 PR base
- 现象：脚本输出「两个 PR 处理完成」，但 `check_pr_base.sh` 复核为
  EXIT=1，两个 PR 的 base 仍是 `main`。
- 报错（被脚本忽略）：
  ```
  GraphQL: Projects (classic) is being deprecated in favor of the new Projects
  experience ... (repository.pullRequest.projectCards)
  ```
- 根因：本机 `gh` 为 2.4.0，其 `pr edit` / `pr view` 子命令走 GraphQL 并请求
  已被 GitHub 废弃的 Projects classic 字段而失败；脚本仅依赖命令退出码，
  未回读实际 `base.ref`，因此把失败当成了成功。
- 危害等级：**高**。静默假成功会诱导 Owner 合并一个仍指向 `main` 的 PR，
  从而把 19 个未评审的存量提交（含 `v0.1.0` 发布）推入 `main`。
- 处置：
  1. 全部改用 `gh api`（REST），绕开旧版 gh 的 GraphQL 缺陷；
  2. 改 base 后**回读 `base.ref` 比对**，不以退出码判定成功；
  3. 失败置 `FAILED=1` 并以退出码 1 结束，提示改用网页操作；
  4. 幂等复跑已实测（base 正确时输出「无需改动」，EXIT=0）。
- 状态：已修复。实际 base 已改为 `develop`，`check_pr_base.sh` EXIT=0。

---

## FAIL-JR1-04：CI 未覆盖 `develop` 的 PR，且 `develop` 上 CI 为红

- 发现时间：2026-08-31
- 阶段：JR-1 收尾，编写合并脚本前的前置核查
- 现象（两个独立问题）：

  **(a) CI 触发条件漏掉 `develop`。**
  `.github/workflows/ci.yml` 原为 `pull_request: branches: [main]`。
  按流程 feature 分支 PR 到 `develop`，因此 **PR #1 / #2 上没有任何
  check-run**（已核实 `check-runs` 为空），合并前无自动验证。
  这是治理缺口：base 从 `main` 改为 `develop` 后反而失去了 CI 把关。

  **(b) `develop` 分支 CI 结论为 failure。**
  `Lint` / `Test` / `Security Tests` / `E2E Tests` 均 failure
  （run 33328453465，2026-08-30T18:34Z，即 PR #3 创建时刻），
  仅 `Performance Benchmarks` success。

- 根因：
  - (a) 工作流触发分支未随分支策略更新。
  - (b) `httpx` 仅存在于 `requirements-lock.txt`，**未在 `pyproject.toml`
    的 `[project.optional-dependencies]` 中声明**（现仅
    `api = [fastapi, uvicorn]`、`dev = [pytest]`）。CI 在 lock 文件不可用的
    分支走 `pip install ".[api,dev]"`，于是缺 `httpx`，导致
    `ModuleNotFoundError: No module named 'httpx'` 与
    `starlette.testclient requires the httpx package`，
    进而 `tests/e2e`、`tests/integration/*` 收集失败。

- 与 JR-1 的关系：**无关**。失败时刻早于 JR-1 收尾工作，
  且 JR-1 本地全量回归 1317 项通过、端到端验证 8/8 PASS。
  属既有 CI 环境/依赖声明问题。

- 处置：
  - (a) 已修：`pull_request.branches` 改为 `[main, develop]`，
    使 feature → develop 的 PR 能被 CI 验证。
  - (b) **未修，交由 Tech Lead 决策**。修 `pyproject.toml` 依赖声明属
    构建配置变更，超出 JR-1「内部契约双端测试」范围；
    擅自改动会使本 PR 夹带无关变更，违反原子提交原则。
    建议以独立任务包处理（把 `httpx` 加入 `api` 或新增 `test` extra）。

- 附带发现：**CI 完全不含 Java**（`java|maven|jdk` 匹配 0 行），
  故 Java 侧 73 项契约测试在 CI 中不会运行，Java 契约漂移无法被 CI 拦截。
  JR-1 的四方哈希闸门在本地有效，但**尚未进入 CI 防线**。
  是否新增 Java job 属 Tech Lead 决策，此处仅如实记录。

- 状态：(a) 已修；(b) 与 Java CI 覆盖待 Owner / Tech Lead 决策。
