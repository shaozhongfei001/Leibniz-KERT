"""激活计划（M7.3；依据独立评审 §4.7 的目标设计）。

职责
----
把 :class:`~kert.domain.route_policy.RouteResolver` 的路由结果固化为**不可变快照**：
资产 / Skill / 权限 / 版本，并给出**可重放 plan hash**。

可重放性（判据核心）
--------------------
``plan_hash`` 只覆盖**确定性字段**（schema、任务、策略键、地图键、资产序列、Skill 序列），
**不含**生成时刻、进程、绝对路径等环境相关字段 ⇒ 同一输入在任何机器上都得到同一 hash。
``plan_id`` 亦由 hash 派生（不引入随机数/时间），故同一输入的计划**逐字段可重放**。

fail-closed
-----------
路由被拒（策略缺失 / 未映射 / 歧义 / 地图未注册 / 策略错配）时，``build`` **不产出计划**，
而是返回 :class:`PlanDenial`（携带路由拒绝码与原因）；调用方必须显式处理。

与 gits 侧 CTR-PLAN-001 的口径对齐（只读参考，**不复制**其内容）
---------------------------------------------------------------
gits 的 ``ActivationPlan`` 有 ``versions{knowledgeMap, routePolicy, activationContract, ontology}``
与 ``trace.planHash``。本实现采用**同名语义**（``knowledgeMap`` / ``routePolicy``），
``activationContract`` 与 ``ontology`` 作为**预留槽位**（当前为 ``None``，待后续切片按 D3-A
以"契约引用 + 内容哈希版本"填入）——**不留占位串、不虚构取值**。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Callable

from .route_policy import RouteResolver

SCHEMA = "activation_plan/v1"
"""激活计划 schema。"""

_HASH_HEX_LEN = 16
"""plan hash 取 sha256 前 16 位十六进制（与 gits 侧口径一致）。"""


@dataclass(frozen=True)
class PlanAsset:
    """计划中被激活的资产（顺序即激活顺序）。"""

    asset_id: str
    required: bool
    sequence: int


@dataclass(frozen=True)
class ActivationPlan:
    """激活计划快照（不可变；同输入可逐字段重放）。"""

    schema: str
    plan_id: str
    task_type: str
    subject_id: str | None
    policy_key: str
    map_key: str
    assets: tuple[PlanAsset, ...]
    skills: tuple[str, ...]
    route_reason: str
    plan_hash: str
    versions: dict[str, str | None] = field(default_factory=dict)

    @property
    def allowed(self) -> bool:
        return True

    def to_dict(self) -> dict:
        """稳定序列化（键序固定，供落盘与跨仓对照）。"""
        return {
            "schema": self.schema,
            "planId": self.plan_id,
            "taskType": self.task_type,
            "subjectId": self.subject_id,
            "routeReason": self.route_reason,
            "versions": dict(self.versions),
            "assets": [
                {"assetId": a.asset_id, "required": a.required, "sequence": a.sequence}
                for a in self.assets
            ],
            "skills": list(self.skills),
            "planHash": self.plan_hash,
        }


@dataclass(frozen=True)
class PlanDenial:
    """计划拒绝（fail-closed；携带路由拒绝码）。"""

    code: str
    reason: str

    @property
    def allowed(self) -> bool:
        return False


PlanDecision = ActivationPlan | PlanDenial
"""计划裁决：要么是完整快照，要么是显式拒绝（**没有**第三态）。"""


def canonical_content(
    *,
    task_type: str,
    policy_key: str,
    map_key: str,
    assets: tuple[PlanAsset, ...],
    skills: tuple[str, ...],
) -> str:
    """构造**确定性**内容串（plan hash 的输入）。

    刻意**不含**：生成时刻、planId、文件绝对路径、进程信息。
    """
    lines = [
        f"schema={SCHEMA}",
        f"task={task_type}",
        f"policy={policy_key}",
        f"map={map_key}",
    ]
    lines += [f"asset={a.sequence}:{a.asset_id}:{'R' if a.required else 'O'}" for a in assets]
    lines += [f"skill={s}" for s in sorted(skills)]
    return "\n".join(lines)


def compute_plan_hash(**kwargs) -> str:
    """按 :func:`canonical_content` 计算 plan hash（sha256 前 16 位）。"""
    return hashlib.sha256(canonical_content(**kwargs).encode("utf-8")).hexdigest()[:_HASH_HEX_LEN]


def plan_id_for(task_type: str, plan_hash: str) -> str:
    """由任务与 hash 派生计划 ID（确定性，含可控版本段）。"""
    return f"AP-KERT-{task_type}-{plan_hash[:8]}"


class ActivationPlanBuilder:
    """由路由解析器构建激活计划（无副作用，纯计算）。"""

    def __init__(self, resolver: RouteResolver,
                 *, ontology_ref: Callable[[], str | None] | None = None):
        """:param ontology_ref: 预留钩子（D3-A：只读消费 gits 本体时返回其"引用@哈希版本"）。"""
        self._resolver = resolver
        self._ontology_ref = ontology_ref

    @classmethod
    def load(cls, workspace) -> "ActivationPlanBuilder":
        """从工作区加载路由解析器并构造构建器。"""
        return cls(RouteResolver.load(workspace))

    def build(self, task_type: str, *, subject_id: str | None = None,
              permission_decision_id: str | None = None) -> PlanDecision:
        """构建激活计划；路由被拒则不产出计划（fail-closed）。

        :param task_type: 任务类型（调用方输入）。
        :param subject_id: 主体标识（如 customerId）；仅记录，**不**入 hash。
        :param permission_decision_id: 权限决策 ID；仅记录，**不**入 hash。
        """
        res = self._resolver.resolve(task_type)
        if not res.allowed or res.map is None or res.rule is None:
            return PlanDenial(code=res.code,
                              reason=f"路由未放行 ⇒ 不产出计划: {res.reason}")

        m = res.map
        assets = tuple(PlanAsset(asset_id=r.asset_id, required=r.required, sequence=r.sequence)
                       for r in m.asset_refs)
        skills = tuple(sorted(m.skill_refs))

        h = compute_plan_hash(task_type=task_type, policy_key=res.policy_key,
                              map_key=f"{m.map_id}@{m.version}", assets=assets, skills=skills)
        versions = {
            "knowledgeMap": f"{m.map_id}@{m.version}",
            "routePolicy": res.policy_key,
            "activationContract": None,   # 预留：本仓暂未引入激活合同
            "ontology": self._ontology_ref() if self._ontology_ref else None,  # 预留：D3-A 只读引用
        }
        return ActivationPlan(
            schema=SCHEMA,
            plan_id=plan_id_for(task_type, h),
            task_type=task_type,
            subject_id=subject_id,
            policy_key=res.policy_key,
            map_key=f"{m.map_id}@{m.version}",
            assets=assets,
            skills=skills,
            route_reason=res.reason,
            plan_hash=h,
            versions=versions,
        )


def replay_matches(plan: ActivationPlan, other: ActivationPlan) -> bool:
    """两个计划是否逐字段一致（可重放性判定的便捷谓词）。"""
    return plan.to_dict() == other.to_dict()
