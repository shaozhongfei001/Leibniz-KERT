"""D-37：perf 判据的**同进程参考负载**（把绝对墙钟阈值换成"相对比值"）。

为什么需要它
------------
绝对毫秒阈值在多变/共享机器上**不可标定**：同一代码、同一命令、同一机器，背靠背 20 轮里
同一被测量出现 **1.4–2.4× 的双态漂移**（逐轮实测见 ``BASELINE.md`` §9）。任何常数阈值都等于
"赌跑测那一刻处于哪个态"⇒ 门禁会周期性假红（实测改前 14/20 轮红，且与任何代码改动无关）。

参考负载的**选型依据（实测，非拍脑袋）**
--------------------------------------
``RuntimeStore`` 的每次写操作 = **新建连接 + 应用 PRAGMA + 单条写 + 提交 + 关闭**。
故参考负载**逐字镜像这一形状**（自己的临时 DB、自己的 SQL，**不 import 被测模块**）：

| 候选参考负载 | 量级 | `create/calib` 抖动 |
|---|---|---|
| 复用连接 insert+commit | ~0.14ms（差 ~100×） | 2.0× |
| 复用连接 + ``synchronous=FULL`` | ~0.02ms（差 ~700×） | 4.7× |
| **open + 同口径 PRAGMA + insert + commit + close** | 与测点**同量级** | **1.2×** |

只有第三种既同量级又同机理 ⇒ 比值在三态（空闲 / 合成负载 / 窄算力）下稳定在
``0.81–1.32``（20 轮自检见 ``BASELINE.md`` §9），而同期绝对量从 13.9ms 漂到 34.1ms。

设计约束
--------
- **不得 import 被测模块**：否则被测路径的回归会同时污染分子与分母（比值恒≈1，判据空转）。
- **必须与测点同机理**：只跟踪 CPU 的参考负载（如纯计算循环）不跟踪 SQLite 连接/提交成本，
  比值会随环境在 2–5× 内漂（上表实测）。
- 只读、无副作用：只写自己的临时 DB。
"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path

CALIBRATION_OPS = 25
"""参考负载的操作数。

取 25（而非与测点相同的 50）：测点每次操作的抖动仅 ~1.1–1.3×，其**均值**的抽样误差约
``jitter/√n`` ⇒ 25 次已足够（~0.25× 量级），而本用例要做**前后两次**标定 ⇒ 25+25 次
与"一次 50 次"同价，perf job 不因加判据而显著变慢。
"""

RATIO_LIMIT = 3.0
"""比值档上限：``avg_x ≤ RATIO_LIMIT × calib``。

取值依据：实测比值带宽 ``0.81–1.32``（三态 20 轮）⇒ 3.0 留 **2.3×** 余量，
同时仍能拦住 ≥3× 的回归（见 ``test_lifecycle_budget_*`` 的反例用例）。
"""

CATASTROPHE_CEILING_MS = 100.0
"""灾难上限：``avg_x < 100ms``。

只作"兜底"，拦 ≥7× 级回归（当前实测 13.9–34.1ms）；**不是**原来的 20ms 门禁。
"""


def calibrate_per_op_ms(db_path: Path, ops: int = CALIBRATION_OPS) -> float:
    """跑参考负载，返回**每次操作的平均毫秒**。

    每次操作 = 新建连接 → 应用同口径 PRAGMA（``busy_timeout`` / ``foreign_keys`` /
    ``journal_mode=WAL`` / ``synchronous=NORMAL``）→ 单条 INSERT → commit → close。

    :param db_path: 参考负载自己的 DB 文件（调用方给临时路径；本函数不做清理）。
    :raises AssertionError: 参考负载退化到不可用（< 1µs/op ⇒ 不可能是真实写盘），
        防止"分母≈0 ⇒ 比值爆炸"把判据变成随机红。
    """
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS calib (id INTEGER PRIMARY KEY, v TEXT)")
        conn.commit()
    finally:
        conn.close()

    times: list[float] = []
    for i in range(ops):
        t0 = time.perf_counter()
        conn = sqlite3.connect(str(db_path))
        try:
            conn.execute("PRAGMA busy_timeout = 5000")
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA synchronous = NORMAL")
            conn.execute("INSERT INTO calib (v) VALUES (?)", (f"c{i}",))
            conn.commit()
        finally:
            conn.close()
        times.append((time.perf_counter() - t0) * 1000)

    per_op = sum(times) / len(times)
    assert per_op > 1e-3, (
        f"参考负载异常：{per_op:.6f}ms/op 不可能是真实的建连+写盘成本 ⇒ 判据不可用（不得当分母）")
    return per_op
