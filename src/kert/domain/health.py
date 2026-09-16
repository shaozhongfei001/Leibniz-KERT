"""健康状态值域（技能健康域）：合同 `enum` 的**单一命名源**（D-28 层 2「立源」）。

**为什么需要它**：合同两处健康 `enum`（`specs/kert-openapi-v1.yaml` 的
`SkillHealthResponse.status`、`HealthResponse.status`）与实现侧（`api/server.py` 的
``skill_health()`` 里手写的字面量 ``"ok"``）之间**没有可比对的命名源** ⇒ 值域漂移
只能靠人眼（D-28 清单第 1/2 项判定为「无仓内权威源」）。
本模块把该值域立为**唯一**命名源：实现只许用 :data:`HEALTH_OK` / :data:`HEALTH_DEGRADED`；
合同侧由 `tests/unit/test_contract_enum_single_source.py` 的 ``MAPPINGS``
（``SkillHealthResponse.status`` 行）**机械核对**，生产者侧由
`tests/unit/test_health_status_single_source.py` 机械核对。

⚠ **边界（不得外推，防止被顺手"合并"）**：

- 本值域是**小写**的**健康**词汇（``ok`` / ``degraded``），**不是** `assembly-trace.schema.json`
  里那套**轨迹条目**状态词汇（``ok`` / ``failed`` / ``blocked`` / ``skipped`` / ``degraded``，
  `src/kert/application/skills.py` 的留痕用）—— 两者值域**相交不等**，**禁止**为"看上去一致"而合并；
- ``/v1/health`` 响应里的 ``data.status`` 目前是**大写** ``OK`` / ``DEGRADED``，且响应形状与合同
  ``HealthResponse``（``required: [status, timestamp, skills]``）**不同** ⇒ 那属**另一处**发现
  （登记待裁），**不**由本模块吞并、本模块**不**代表它。
"""

from __future__ import annotations

#: 健康状态值域（顺序 = 恶化方向：正常 → 降级）。合同 `enum` 必须与本元组**等值**。
SKILL_HEALTH_STATES: tuple[str, ...] = ("ok", "degraded")
#: 具名常量：实现侧**不得**再散落字面量（改名 / 增删只动上面这一处）。
HEALTH_OK, HEALTH_DEGRADED = SKILL_HEALTH_STATES
