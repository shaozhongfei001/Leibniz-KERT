"""激活计划（M7.3；依据独立评审 §4.7 的目标设计）。

职责
----
把 :class:`~kert.domain.route_policy.RouteResolver` 的路由结果固化为**不可变快照**：
资产 / Skill / 权限 / 版本，并给出**可重放 plan hash**。

可重放性（判据核心）
--------------------
``plan_hash`` 只覆盖**确定性字段**（schema、任务、策略键、地图键、资产序列、Skill 序列、
**本体版本**），**不含**生成时刻、进程、绝对路径等环境相关字段
⇒ 同一输入在任何机器上都得到同一 hash。
``plan_id`` 亦由 hash 派生（不引入随机数/时间），故同一输入的计划**逐字段可重放**。

fail-closed
-----------
任一门禁被拒即**不产出计划**，而是返回 :class:`PlanDenial`（携带拒绝码与原因）：

- 路由被拒：策略缺失 / 未映射 / 歧义 / 地图未注册 / 策略错配（见 :mod:`kert.domain.route_policy`）；
- **本体引用被拒**（M7.3 第三步 / D-4）：声明缺失 ⇒ ``ONTOLOGY_REFERENCE_ABSENT``；
  声明非法 ⇒ ``ONTOLOGY_REFERENCE_INVALID``。

调用方必须显式处理拒绝，**没有**第三态。

本体版本进入 plan hash（D-3；与 gits 侧 GK17 WP2.3 同口径）
--------------------------------------------------------
- 本体**版本**（``<contractId>@sha256:<哈希前16>``）**进入** ``canonical_content``
  ⇒ 本体一变，``plan_hash`` 必变（对应 gits 侧判据 V2"只改本体 ⇒ 计划必变"）；
- 本体**来源路径**（仓名 / 仓内相对路径）**不入** hash（环境相关，gits 侧同裁定）；
- ⚠ 依赖 **运维前提**：工作区必须经供给放入本体引用声明，否则计划构建被 fail-closed 全量拒绝。

与 gits 侧 CTR-PLAN-001 的口径对齐（只读参考，**不复制**其内容）
---------------------------------------------------------------
gits 的 ``ActivationPlan`` 有 ``versions{knowledgeMap, routePolicy, activationContract, ontology}``
与 ``trace.planHash``，其 ``versions.ontology`` 取
``<contractId>@sha256:<全量哈希前16>``。本实现采用**同名语义**与**同格式取值**
（``knowledgeMap`` / ``routePolicy`` / ``ontology``），并以**同一条 16 位 hex 前缀**计算版本。
``activationContract`` 仍为**预留槽位**（当前 ``None``）——**不留占位串、不虚构取值**。

本体引用**只以控制面声明钉值**消费：本模块不读另一仓文件、不调其接口、不内置跨仓路径
（见 :mod:`kert.domain.ontology_reference` 的 D-1/D-2）。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

from .ontology_reference import (
    CODE_ABSENT as ONTOLOGY_CODE_ABSENT,
    ReferenceResolution,
    resolve_reference,
)
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
    ontology_key: str = ""
    ontology_source: str = ""
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
    """计划拒绝（fail-closed；携带**首个**门禁的拒绝码）。

    可能的码来源：路由（``ROUTE_*``）与本体引用（``ONTOLOGY_REFERENCE_*``）。
    """

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
    ontology_key: str = "",
) -> str:
    """构造**确定性**内容串（plan hash 的输入）。

    刻意**不含**：生成时刻、planId、文件绝对路径、进程信息、**本体来源路径**。

    :param ontology_key: 本体**版本**引用（D-3：**进入** hash）。**不是**来源路径。
    """
    lines = [
        f"schema={SCHEMA}",
        f"task={task_type}",
        f"policy={policy_key}",
        f"map={map_key}",
        f"ontology={ontology_key}",
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
    """由路由解析器 + 本体引用声明构建激活计划（无副作用，纯计算）。

    门禁顺序（**首个被拒者决定计划拒绝码**）:

    1. **路由**（:class:`~kert.domain.route_policy.RouteResolver`）：策略缺失/未映射/歧义/
       地图未注册/策略错配；
    2. **本体引用**（D-4）：声明缺失 ⇒ ``ONTOLOGY_REFERENCE_ABSENT``；非法 ⇒
       ``ONTOLOGY_REFERENCE_INVALID``。

    本体引用**在路由放行之后**才被读取：本体声明属工作区**配置**问题，不应因一个未映射的任务
    而误报为配置错误（保持"默认拒绝"的归因正确）。
    """

    def __init__(self, resolver: RouteResolver, *, workspace: Path | None = None):
        """:param workspace: 工作区根（用于读取本体引用声明；``None`` ⇒ 无声明可用 ⇒ 拒绝）。"""
        self._resolver = resolver
        self._workspace = Path(workspace) if workspace is not None else None

    @classmethod
    def load(cls, workspace) -> "ActivationPlanBuilder":
        """从工作区加载路由解析器与本体引用声明并构造构建器。"""
        ws = Path(workspace)
        return cls(RouteResolver.load(ws), workspace=ws)

    @property
    def workspace(self) -> Path | None:
        """构建器绑定的工作区（未绑定时为 ``None``）。"""
        return self._workspace

    def ontology_resolution(self) -> ReferenceResolution:
        """本工作区的本体引用解析结果（未绑定工作区 ⇒ 视为声明缺失 ⇒ 拒绝）。"""
        if self._workspace is None:
            return ReferenceResolution(
                code=ONTOLOGY_CODE_ABSENT,
                reason="构建器未绑定工作区 ⇒ 无法读到本体引用声明 ⇒ 拒绝："
                       "'本体未被消费'不得静默通过",
            )
        return resolve_reference(self._workspace)

    def build(self, task_type: str, *, subject_id: str | None = None,
              permission_decision_id: str | None = None) -> PlanDecision:
        """构建激活计划；任一门禁被拒则不产出计划（fail-closed）。

        :param task_type: 任务类型（调用方输入）。
        :param subject_id: 主体标识（如 customerId）；仅记录，**不**入 hash。
        :param permission_decision_id: 权限决策 ID；仅记录，**不**入 hash。
        """
        res = self._resolver.resolve(task_type)
        if not res.allowed or res.map is None or res.rule is None:
            return PlanDenial(code=res.code,
                              reason=f"路由未放行 ⇒ 不产出计划: {res.reason}")

        # 门禁 2（D-4）：本体引用必须被**声明且合法**，否则拒绝 —— 不放行"本体未被消费"的计划。
        ont = self.ontology_resolution()
        if not ont.allowed or ont.reference is None:
            return PlanDenial(code=ont.code,
                              reason=f"本体引用未放行 ⇒ 不产出计划: {ont.reason}")

        m = res.map
        assets = tuple(PlanAsset(asset_id=r.asset_id, required=r.required, sequence=r.sequence)
                       for r in m.asset_refs)
        skills = tuple(sorted(m.skill_refs))

        ontology_key = ont.reference.version           # 进 hash（D-3）
        ontology_source = (f"{ont.reference.authority_repo}:"
                           f"{ont.reference.authority_source}")   # **不**进 hash（环境相关）

        h = compute_plan_hash(task_type=task_type, policy_key=res.policy_key,
                              map_key=f"{m.map_id}@{m.version}", assets=assets, skills=skills,
                              ontology_key=ontology_key)
        versions = {
            "knowledgeMap": f"{m.map_id}@{m.version}",
            "routePolicy": res.policy_key,
            "activationContract": None,   # 预留：本仓暂未引入激活合同
            "ontology": ontology_key,
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
            ontology_key=ontology_key,
            ontology_source=ontology_source,
            versions=versions,
        )


def replay_matches(plan: ActivationPlan, other: ActivationPlan) -> bool:
    """两个计划是否逐字段一致（可重放性判定的便捷谓词）。"""
    return plan.to_dict() == other.to_dict()
