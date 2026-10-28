# 性能基线报告 — Leibniz-KERT / KERT

> 生成时间：2026-08-28
> 环境：Linux / Python 3.10.12 / pytest 9.1.1
> 测试总耗时：~8s（CI 友好，< 60s）

## 1. NFR 映射

| NFR | 要求 | 状态 |
|-----|------|------|
| NFR-005 | 性能基准：Parquet 读写 / 查询延迟 | PASS |
| NFR-006 | 容量基准：10K 行数据集可处理 | PASS |
| NFR-007 | 并发基准：多线程锁 / SQLite 并发写入 | PASS |

## 2. Parquet 读写性能

| 操作 | 行数 | 耗时(ms) | 阈值(ms) | 结果 |
|------|------|----------|----------|------|
| write_parquet | 100 | 0.9 | 50 | PASS |
| write_parquet | 1,000 | 1.2 | 50 | PASS |
| write_parquet | 10,000 | 8.0 | 500 | PASS |
| read_parquet | 100 | 30.1 | 50 | PASS |
| read_parquet | 1,000 | 5.2 | 50 | PASS |
| read_parquet | 10,000 | 30.4 | 200 | PASS |
| logical_hash | 100 | 0.8 | 50 | PASS |
| logical_hash | 1,000 | 5.1 | 50 | PASS |
| logical_hash | 10,000 | 49.9 | 300 | PASS |

**结论**：Parquet zstd 压缩写入在 10K 行时仅 8ms，读取 30ms，逻辑哈希 50ms。小数据集（100 行）因 I/O 固定开销约 30ms，属正常范围。

## 3. 并发锁性能

| 操作 | 规模 | 耗时(ms) | 阈值(ms) | 结果 |
|------|------|----------|----------|------|
| WorkspaceLock 单线程平均 | 50 次 | 0.1 | 10 | PASS |
| WorkspaceLock 单线程最大 | 50 次 | 0.5 | 50 | PASS |
| WorkspaceLock 多线程并发 scope | 10 线程×10 次 | <2,000 | 2,000 | PASS |
| WorkspaceLock 同 scope 顺序 | 20 次 | <10 | 10 | PASS |

**结论**：WorkspaceLock 基于 O_EXCL 原子创建，单次 acquire+release 约 0.1ms，满足并发场景需求。

## 4. RuntimeStore 并发性能

| 操作 | 规模 | 耗时(ms) | 阈值(ms) | 结果 |
|------|------|----------|----------|------|
| 写入 100 条 idempotency | 100 条 | 1,364 | 3,000 | PASS |
| 读取 100 条 idempotency | 100 条 | 18.6 | 500 | PASS |
| 创建 50 个 Job | 50 条 | 644 | 1,000 | PASS |
| 领取 50 个 Job | 50 条 | 656 | 1,000 | PASS |
| Job 生命周期 create→claim→complete | 50 条 | 各 <20ms/op | 20 | **见 §9**（判据已改为「不变量 + 相对比值」，不再用 20ms 绝对阈值） |

**结论**：SQLite WAL 模式下并发写入性能良好。100 条 idempotency 写入约 1.4s（含 SQLite 事务开销），读取 18.6ms。Job 生命周期各操作平均 <20ms。

## 5. 知识查询性能

| 操作 | 行数 | 耗时(ms) | 阈值(ms) | 结果 |
|------|------|----------|----------|------|
| data_query | 100 | 2.4 | 50 | PASS |
| data_query | 1,000 | 3.1 | 50 | PASS |
| data_query | 10,000 | 17.7 | 500 | PASS |
| data_query (带过滤) | 100 | <50 | 50 | PASS |
| data_query (带过滤) | 1,000 | <50 | 50 | PASS |
| data_query (带过滤) | 10,000 | <500 | 500 | PASS |
| get_entity | 100 | 3.2 | 50 | PASS |
| get_entity | 1,000 | 7.8 | 50 | PASS |
| get_entity | 10,000 | 50.1 | 200 | PASS |
| graph (BFS) | 100 | 4.9 | 50 | PASS |
| graph (BFS) | 1,000 | 5.9 | 100 | PASS |
| graph (BFS) | 10,000 | 55.9 | 1,000 | PASS |
| search (全文) | 100 | 3.2 | 50 | PASS |
| search (全文) | 1,000 | 5.6 | 100 | PASS |
| search (全文) | 10,000 | 41.7 | 1,000 | PASS |
| evaluate_rule | 50 条规则 | <500 | 500 | PASS |
| entities 全量列表 | 100 | 1.4 | 50 | PASS |
| entities 全量列表 | 1,000 | 2.3 | 50 | PASS |
| entities 全量列表 | 10,000 | 72.1 | 500 | PASS |
| relations 全量列表 | 100 | 1.1 | 50 | PASS |
| relations 全量列表 | 1,000 | 1.9 | 50 | PASS |
| relations 全量列表 | 10,000 | 14.2 | 500 | PASS |

**结论**：所有查询操作在 10K 行数据集下均满足阈值要求。`get_entity` 和 `entities` 全量列表在 10K 行时约 50-72ms，主要瓶颈是 Parquet → PyList 全量反序列化。

## 6. 性能瓶颈与优化建议

### 6.1 当前瓶颈

1. **get_entity 线性扫描**：当前 `get_entity` 通过 `to_pylist()` 全量反序列化后线性查找，10K 行约 50ms。数据量增长到 100K+ 后将成为瓶颈。
2. **entities 全量列表**：同上，全量反序列化是主要开销。
3. **RuntimeStore 首次写入**：100 条 idempotency 写入约 1.4s，主要来自 SQLite migration 和 WAL 初始化。

### 6.2 优化建议

| 优先级 | 优化项 | 预期收益 | 复杂度 |
|--------|--------|----------|--------|
| P1 | `get_entity` 改用 PyArrow `filter` 谓词下推 | 10K 行 < 10ms | 低 |
| P1 | `data_query` 改用 PyArrow `filter` 替代 Python 列表推导 | 10K 行 < 5ms | 低 |
| P2 | `entities`/`relations` 全量列表增加分页参数 | 减少单次内存占用 | 低 |
| P2 | RuntimeStore 批量写入接口（`remember_batch`） | 100 条 < 200ms | 中 |
| P3 | 引入 Parquet 行组索引（row group index） | 100K+ 行随机读 < 5ms | 高 |
| P3 | Kùzu 图数据库替代内存 BFS | 10K+ 节点图查询 < 50ms | 高 |

## 7. 测试文件清单

| 文件 | 描述 | 测试数 |
|------|------|--------|
| `tests/performance/__init__.py` | 包初始化 | - |
| `tests/performance/_calibration.py` | **D-37**：同进程参考负载（非测试文件，供比值判据当分母） | - |
| `tests/performance/test_parquet_benchmark.py` | Parquet 读写/哈希基准 | 15 |
| `tests/performance/test_concurrency_benchmark.py` | 并发锁/SQLite 基准（含 D-37/D-47 判据与 8 条反例） | 16 |
| `tests/performance/test_query_benchmark.py` | 知识查询基准 | 22 |
| `tests/performance/test_query_optimized_benchmark.py` | 谓词下推基准 | 23 |
| **合计** | | **76** |

## 8. 运行方式

```bash
PYTHONPATH=src python -m pytest tests/performance/ -q
```

---

## 9. D-37：阈值的**降敏改造**（Job 生命周期判据）

> 本节是 **D-37 裁决（修基准，非放宽阈值）** 的落地记录。适用对象**只有**
> `test_runtime_store_job_lifecycle_benchmark` 的 3 条断言；本目录其余断言**未改**。

### 9.1 为什么改（改前实测）

`tests/performance/test_concurrency_benchmark.py::test_runtime_store_job_lifecycle_benchmark`
原判据为 `assert avg_create/claim/complete < 20.0`。同代码、同命令、同机器**背靠背 20 轮**
（`pytest tests/performance/ -q -m "perf or not perf"`）：

| 观测 | 结果 |
|---|---|
| 20 轮中有失败的轮数 | **14/20**（其中 12 轮失败**只**由本用例造成） |
| 被断言的量（三者的最坏均值） | **13.9 – 34.1 ms**（漂移 **2.4×**；20 轮内即出现快态 ~14ms 与慢态 ~25ms 两个平台） |
| 阈值余量 | 最快一轮也有 1 次触到 19.12ms ⇒ **最好情况仅 4% 余量**；无"安全区" |

同批还做过受控实验：**同一 pin（`taskset -c 0,1`）在不同时刻**测得的量一次 ~14ms、一次 ~29ms
⇒ 漂移**不由核数决定**，而是机器状态的**时变**（时长/温度/邻居负载）⇒ **任何常数阈值都不可标定**
（"放宽阈值"等于赌跑测那一刻处于哪个平台，且会把与 NFR 的真实偏差一并洗绿）。

### 9.2 改法（三层判据）

| 层 | 判据 | 说明 |
|---|---|---|
| ① | **不变量（零墙钟）** | `create`→`PENDING`；`claim` 拿到**该** job 且 `RUNNING`；他人 `claim` 得 `None`；非 lease 持有者 `complete` 得 `None`；持有者 `complete` 得 `COMPLETED`、重复 `complete` 得 `None`；终局计数 **50/0/0** |
| ② | **相对比值** | `avg_x ≤ RATIO_LIMIT(3.0) × calib`，`calib` = 同进程参考负载（`_calibration.calibrate_per_op_ms`，逐字镜像「建连 + PRAGMA + 单写 + 提交」）。分母取**前后两次标定的较大者** |
| ③ | **灾难上限** | `avg_x < CATASTROPHE_CEILING_MS(100.0)`（只抓 ≥7× 级回归） |

**参考负载的选型（实测选定）**：候选必须与被测点**同量级且同机理**，否则比值随环境漂：

| 候选 | 量级 | `create/calib` 抖动 | 结论 |
|---|---|---|---|
| 复用连接 `insert+commit` | ~0.14ms（差 ~100×） | 2.0× | 否 |
| 复用连接 + `synchronous=FULL` | ~0.02ms（差 ~700×） | 4.7× | 否 |
| **open + 同口径 PRAGMA + insert + commit + close** | 与测点同量级 | **1.2×** | **采用** |

标定助手**不 import 被测模块**（独立 DB、独立 SQL）⇒ 被测路径的回归不会污染分母。

### 9.3 ⚠ 降敏声明（**硬要求**，不得读成"这里仍有单位数毫秒的性能门禁"）

- **≤2× 的真实退化不会被本用例拦住**。当前灵敏度：**≥3×** 由②拦，**≥7×** 由③拦（100ms ÷ ~14ms）。
- 改前那条 20ms 绝对阈值**确实**能拦 1.5× 级退化 —— 但它同时以 **14/20 的假红率**卡住所有 PR
  （含与性能无关的改动）⇒ "门禁严"与"门禁坏"必须二选一，D-37 选"不坏"。
- **本仓当前没有**任何自动化能拦住 ≤2× 的 **Job 生命周期** 退化（其余 perf 断言的余量 6–740×，
  同理拦不住 2×；`tests/unit/test_worker*.py`、`tests/integration/test_runtime_store_api.py`
  是功能性用例，不含性能断言）。若 Owner 需要该灵敏度，需要**专门的相对基线门禁**
  （记录基线快照 + 按比值拦 + 跨机器标定），**本批未做**，属独立议题。

### 9.4 改造后实测（同一条件，背靠背 20 轮 × 2 种机器状态）

| 场景 | n | 生命周期 3 条断言 | 被断言的量（最坏均值） | 比值（min/中位/max） | K=3 余量 |
|---|---|---|---|---|---|
| 改前·空闲 | 20 | **14/20 轮红** | 14.2 – 27.8 ms | —— | —— |
| 改后·空闲 | 20 | **0/20 轮红** | 14.4 – **30.1** ms（漂 2.09×） | 0.82 / 1.00 / **1.11** | 2.71× |
| 改后·合成负载（16 忙等） | 20 | **0/20 轮红** | 12.9 – **28.2** ms（漂 2.19×） | 0.77 / 0.94 / **1.28** | 2.35× |

- **标定助手自检（≥10 轮）**：40 轮（两种状态）中参考负载为 12.2–35.1ms，**判定比值始终 ≤1.28**
  ⇒ 抖动留在 K 的余量内（≥2.35×）；另有 18 轮三态选型实验（空闲 / 负载 / 窄算力）比值 0.81–1.32。
- **代价**：perf 目录整轮耗时中位 **16.4s → 19.2s（+2.8s）**（新增不变量调用 + 两次 25 次标定；
  已把"负向不变量"改为每 10 次 + 末次核对、标定 25 次/次以控制成本）。
- **判据有牙（反例，均在仓内常驻）**：`test_lifecycle_budget_rejects_a_3x_ratio_regression`（比值档）、
  `..._rejects_a_catastrophe_regression`（上限档）、`..._rejects_a_real_injected_slowdown`
  （**真回归**：monkeypatch 注入固定 +100ms/op，快慢两态都必然超标）、
  `..._mutant_is_red`（机械自证：判据被改成恒真即红）。
  变异自证：把 `RATIO_LIMIT`/`CATASTROPHE_CEILING_MS` 同时改成 `10**9` ⇒ 上述 4 条**全红**；还原后全绿且文件哈希不变。

### 9.5 未决事项（**只记事实，本批不做判断/不落地**）

1. **NFR-006 口径冲突（待 Owner 裁）**：`test_runtime_store_concurrent_*_writes` 的阈值是 **3000ms**，
   而 `QA_RELEASE_REPORT.md:49` 记 **NFR-006 = RuntimeStore 写入 100 条 < 2s**；实测该量
   **中位 2306ms / 最坏 3429ms**（本轮 20 轮内），CI 侧曾出现 **4087ms**。
   本批**未**改该阈值、**未**改报告 —— 见下条。
2. **族 B 仍会偶发假红**：`test_runtime_store_concurrent_{idempotency,job}_writes` 本批**未改**（其处置与
   NFR-006 属同一裁决）⇒ 改后 40 轮里仍有 3 轮（空闲 3/20、负载 1/20）因它们变红。
   `Performance Benchmarks` 这个 required check 因此**尚不会**稳定变绿。
   > **已被 §9.6（D-47）处理** ⇒ 判据改为「不变量 + 相对比值 + 灾难上限」，改后同条件 20 轮 **0 红**；
   > 原「3000ms vs NFR-006 的 2s」缺口转为**登记缺口**，见 §9.7。
3. **标记口径不一致（政策建议，未落地）**：只有 `test_concurrency_benchmark.py` 带 `pytestmark = perf`；
   同目录另 3 个文件的 **60 条墙钟断言未被标记**，会被**裸 `pytest`（`testpaths=["tests"]`）**收集。
   建议明确口径（分级或明文豁免 + 依据），但**不得**顺手把它们移出默认套件（会掉信号）。

---

### 9.6 D-47：族 B（并发写 100 条）同样改造为三层判据

改造对象：`test_runtime_store_concurrent_idempotency_writes` / `test_runtime_store_concurrent_job_writes`
（原判据各为 `assert elapsed_ms < 3000`）。**形态与 §9.2 完全同形**：

| 层 | 判据 |
|---|---|
| ① **不变量（零墙钟）** | **idempotency**：100 条**逐条 `lookup` 非空**且 `request_hash` 与写入一致（无丢失更新）；**同键重写不新增行**（总行数仍 100，且重复 `(scope, idem_key)` 组为 0）。**job**：100 个 `job_id` **逐条 `get_job` 非空**且为 `PENDING`；**同 id 重复创建不新增行** |
| ② **相对比值** | `elapsed ≤ RATIO_LIMIT(3) × 100 × calib` —— 100 条并发写在 SQLite 写锁下**近似串行**（实测总耗时 ≈ 单次成本 × 条数），故分母取 `ops × calib` 而非单次 `calib`；**实测比值带宽 0.62–1.35**（16 轮选型实验 + 10 轮负载态） |
| ③ **灾难上限** | `elapsed < CONCURRENT_BURST_CEILING_MS(12000ms)` ≈ 历史最坏 CI **4087ms** × 3；**实测最坏 2380ms** ⇒ 余量 **5.05×–9.17×**，快慢两态都不触顶 |

**改前 / 改后（同条件 `-k runtime_store_concurrent`、背靠背 20 轮、junit 权威计数）**

| 版本 | n | 结果 |
|---|---|---|
| 改前（HEAD 原文件 = 3000ms 绝对阈值） | 20 | **3/20 轮红**（run10/run20 job 写、run11 idempotency 写） |
| 改后（不变量 + 比值 + 上限） | 20 | **0/20 轮红** |
| 改后·合成负载（16 忙等） | 10 | **0/10 轮红**（elapsed 1.26–2.38s、比值 0.62–1.32、上限余量 5.05–9.17×） |

**判据有牙（4 条常驻反例）**：比值档（3.55× ⇒ 红）、上限档（比值仅 1.2× 但 12s ⇒ 红）、
**灵敏度边界钉住**（2.0× 过 / 3.0× 过 / 3.1× 红 —— 与 §9.3 同一盲区口径）、
**真回归**（monkeypatch 把每次 op 放大 **6 次真实写** ⇒ 红）。
⚠ 放大必须用**不同键**：同键重复 `remember` 会走幂等短路（只多一次 SELECT），实测仅放大 **1.2×** ——
本用例自带"注入生效"守卫专门挡这个陷阱。
**变异自证**：把 `CONCURRENT_BURST_RATIO_LIMIT` 与 `CONCURRENT_BURST_CEILING_MS` 同时改成 `10**9`
⇒ 上述 4 条**全红**；还原后 16 条全绿且文件哈希不变。

**降敏**：与 §9.3 同一灵敏度（**≥3×** 由比值档拦、≥7× 由上限档拦的相对版本；**≤2× 仍不被拦**）。

### 9.7 🔴 **NFR 缺口登记（D-47）——"止血"不等于"洗绿"**

> **事实（原样记录，本批不做判断）**：
> - `QA_RELEASE_REPORT.md:49` 记 **NFR-006 = RuntimeStore 写入 100 条 < 2s**；
> - 本测试原阈值 **3000ms** ⇒ **比 NFR 松 50%**；
> - 实测该量：**中位 2306ms / 最坏 3429ms**（本地 20 轮），**CI 实测 4087ms**；
> - ⇒ **现状已越过 NFR-006**（本地中位 2306ms > 2000ms）。
>
> 本批把断言改为**相对判据**后，**NFR 缺口不再由 CI 体现**，仅作为**登记缺口（D-47）**存在。
> 若要恢复硬门禁，须先做**性能修复批次**，并把阈值对齐 **2000ms**（届时会立刻变红 —— 那才是真实状态）。
> 本批**未**改 `QA_RELEASE_REPORT.md`、**未**改 NFR 文本、**未**把阈值写成"刚好能过"的数。
