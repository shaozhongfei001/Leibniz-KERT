"""技能执行状态值域（`/api/skill/*` 响应体的 ``status``）：合同 `enum` 的**单一命名源**
（D-28 层 2 第三片）。

**为什么这处该立源**（先答"是不是外部结论 / 推模式入参的如实镜像"）：**不是**。
该词汇由 **KERT 执行器自己判定** —— `SkillExecutionService.execute` 的三个分支
（未知技能 ⇒ `skill_error`、无新证据策略 ⇒ `exit_policy_no_new_evidence`、正常完成 ⇒ `ok`），
且 `api/server.py` 有**按名比较**的分支（`result.status == "skill_error"` 决定 404/200）
⇒ 实现侧**拥有**该词汇、改名会静默改变分支行为。此前同域字面量散布 ≥8 处。

三处分工（**不重复钉同一条**）：

- **源** = 本模块（`SKILL_EXECUTION_STATES` + 具名常量）—— 生产者的唯一取值出处；
- **生产者** = `application/skills.py` / `application/product_recommendation/sp15_skill.py` /
  `api/server.py`（含上面那个按名比较分支）—— 由
  `tests/unit/test_skill_status_single_source.py` 走**真实执行路径**钉三态（`ok` / `skill_error` /
  `exit_policy_no_new_evidence`）并禁止字面量复发；
- **合同** = OpenAPI `SkillExecuteResponse.status`（等值）+ `SkillExecuteErrorResponse.status`
  与 `ErrorResponse.status`（**具名登记的真子集**，理由见
  `tests/unit/test_contract_enum_single_source.py` 的 ``SUBSET_DECLARATIONS``）。

⚠ **边界（不得外推、禁止合并）**：`assemblyTrace` **条目**状态域（`ok` / `failed` / `blocked` /
`skipped` / `degraded`，见 `docs/contracts/schemas/assembly-trace.schema.json`）**不是**本域
（值域相交**不相等**）：两处都出现的字面量 `"ok"` 语义不同，**不得**互相替换。
"""

from __future__ import annotations

#: 技能执行状态值域（顺序 = 合同 `enum` 顺序）。合同侧必须与本元组**等值**或登记为真子集。
SKILL_EXECUTION_STATES: tuple[str, ...] = ("ok", "skill_error", "exit_policy_no_new_evidence")
#: 具名常量：生产者**不得**再散落字面量（改名 / 增删只动上面这一处）。
SKILL_OK, SKILL_ERROR, EXIT_POLICY_NO_NEW_EVIDENCE = SKILL_EXECUTION_STATES
