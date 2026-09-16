"""服务结果状态值域（`SUCCESS` / `PARTIAL`）：合同 `enum` 的**单一命名源**（D-28 层 2 第五片）。

**为什么这处该立源**（自问结论）：**是**该立源。
该词汇由 **KERT 自己算出**（规则校验无 `blocking` 违规 ⇒ `SUCCESS`，否则 `PARTIAL`），
**不是**外部结论、**不是**推模式入参；且**同一词汇同时是两个合同 enum**
（`ServiceResult.status`、`InteractionMemoryResult.status`）⇒ 典型**重复源**，
而字面量此前在 `service_proposal.py` 与 `interaction_memory.py` **各写一份**。

⚠ **跨域映射（本片重点）**：两处产生点随后把域值映射到**轨迹条目域**
（`assembly-trace.schema.json` 的 `ok` / `failed`）当作 compose 留痕：

    trace.append({"phase": "compose", "status": "ok" if status == SERVICE_SUCCESS else "failed", ...})

映射的**判据端**必须引用本模块常量（否则改名会让留痕静默变成 `failed`）；
而映射**目标端**（`ok` / `failed`）属**轨迹条目域**，与本域**相交不等**、**不得合并**
（两处同名字面量的语义不同）。由 `tests/unit/test_service_result_single_source.py` 成对钉住
（域值 + 映射结果）。

⚠ **边界（不得合并）**：`infrastructure/adapters/sim_bank_front.py` 的 `status_map`
（`SUCCESS/PARTIAL/NOT_RUN`，**coverageStatus 域**，模拟上游判定表）与本域**值重叠、域不同**。
"""

from __future__ import annotations

#: 服务结果状态值域（顺序 = 合同 `enum` 顺序）。两个合同 schema 共用本元组。
SERVICE_RESULT_STATES: tuple[str, ...] = ("SUCCESS", "PARTIAL")
#: 具名常量：生产者/消费者**不得**再散落字面量（改名只动上面这一处）。
SERVICE_SUCCESS, SERVICE_PARTIAL = SERVICE_RESULT_STATES
