"""路由策略（M7.3；依据独立评审 §4.7 的目标设计）。

职责
----
把**调用方输入**（任务类型）解析为唯一合法的**知识地图**，并给出理由与优先级。
与 :mod:`kert.domain.knowledge_map` 的分工（避免双权威）：

- **RoutePolicy** 持有"任务 → 地图"的**路由**规则（输入、优先级、理由）；
- **KnowledgeMap** 持有"地图 → 资产/Skill"的**激活面**（`assetRefs` / `skillRefs`）。

即：策略**不**复述资产与 Skill，地图**不**复述路由规则。

位置与契约
----------
策略定义放 ``<ws>/90_control/schema/route_policy.json``（控制面 ``schema`` = "词表/映射/策略"）。

fail-closed 规则
----------------
1. **未知字段**、非法 schema/ID/版本、空 rules、非法 priority ⇒ :class:`SchemaValidationError`；
2. **歧义拒绝**：同一任务被**同优先级**的多个规则声明 ⇒ 拒绝；
3. **默认拒绝**：``defaultDecision`` 非 ``DENY`` ⇒ 定义非法（本实现只接受 fail-closed 默认）；
   任务无任何规则命中、或策略文件缺失 ⇒ 解析结果拒绝；
4. **跨引用校验**：规则指向的 ``knowledgeMapId`` 必须在 :class:`KnowledgeMapRegistry` 中存在；
   地图若声明了 ``routePolicyRef``，必须与本策略 ID 一致（不一致 ⇒ 拒绝，防错配）。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from . import ids
from .errors import SchemaValidationError
from .knowledge_map import KnowledgeMap, KnowledgeMapRegistry, MapResolution

SCHEMA = "route_policy/v1"
"""路由策略定义 schema。"""

POLICY_FILENAME = "route_policy.json"
"""策略文件名（``<ws>/90_control/schema/route_policy.json``）。"""

POLICY_ID_PREFIX = "RP-"
"""路由策略 ID 前缀。"""

DECISION_DENY = "DENY"
"""唯一允许的默认决策（fail-closed）。"""

_TOP_FIELDS = {"schema", "policyId", "version", "title", "defaultDecision", "rules"}
_RULE_FIELDS = {"priority", "taskType", "knowledgeMapId", "reason"}

CODE_OK = "OK"
CODE_NO_POLICY = "ROUTE_POLICY_ABSENT"
CODE_NOT_MAPPED = "ROUTE_NOT_MAPPED"
CODE_AMBIGUOUS = "ROUTE_AMBIGUOUS"
CODE_MAP_UNKNOWN = "ROUTE_MAP_UNKNOWN"
CODE_MAP_POLICY_MISMATCH = "ROUTE_MAP_POLICY_MISMATCH"


@dataclass(frozen=True)
class RouteRule:
    """一条路由规则：任务类型 → 知识地图。"""

    priority: int
    task_type: str
    knowledge_map_id: str
    reason: str


@dataclass(frozen=True)
class RoutePolicy:
    """路由策略定义（不可变）。"""

    policy_id: str
    version: str
    title: str
    default_decision: str
    rules: tuple[RouteRule, ...]
    source_path: str

    @property
    def key(self) -> str:
        """策略引用键：``<policyId>@<version>``（供 ActivationPlan 版本快照使用）。"""
        return f"{self.policy_id}@{self.version}"

    def rules_for(self, task_type: str) -> tuple[RouteRule, ...]:
        """返回声明该任务的规则（按 priority 升序）。"""
        return tuple(sorted((r for r in self.rules if r.task_type == task_type),
                            key=lambda r: r.priority))

    @property
    def ambiguous_task_types(self) -> tuple[str, ...]:
        """存在"同优先级多规则"的任务类型（这些任务在解析时会被拒绝）。

        仅作**诊断**用途：解析期不拒绝它们（避免整份策略不可用），
        由 :meth:`RouteResolver.resolve` 在解析具体任务时 fail-closed 拒绝。
        """
        counts: dict[tuple[str, int], int] = {}
        for r in self.rules:
            key = (r.task_type, r.priority)
            counts[key] = counts.get(key, 0) + 1
        return tuple(sorted({t for (t, _), n in counts.items() if n > 1}))


@dataclass(frozen=True)
class RouteResolution:
    """任务 → 地图的路由结果（fail-closed；``allowed`` 为真时 ``map`` 非空）。"""

    code: str
    reason: str
    policy: RoutePolicy | None = None
    rule: RouteRule | None = None
    map: KnowledgeMap | None = None
    candidates: tuple[str, ...] = ()

    @property
    def allowed(self) -> bool:
        return self.code == CODE_OK and self.rule is not None and self.map is not None

    @property
    def policy_key(self) -> str:
        """策略版本引用（未命中策略时为空串）。"""
        return self.policy.key if self.policy else ""


def schema_dir(workspace: Path) -> Path:
    """返回控制面 ``schema`` 目录（``<ws>/90_control/schema``）。"""
    return Path(workspace) / "90_control" / "schema"


def policy_path(workspace: Path) -> Path:
    """返回策略文件路径。"""
    return schema_dir(workspace) / POLICY_FILENAME


def parse_route_policy(doc: object, *, source: str = "<memory>") -> RoutePolicy:
    """解析并严格校验路由策略定义。"""
    if not isinstance(doc, dict):
        raise SchemaValidationError(f"[{source}] 策略定义必须是 JSON 对象，实际为 {type(doc).__name__}")

    unknown = sorted(set(doc) - _TOP_FIELDS)
    if unknown:
        raise SchemaValidationError(f"[{source}] 含未声明字段（拒绝静默忽略）: {unknown}")

    schema = _require_str(doc, "schema", source)
    if schema != SCHEMA:
        raise SchemaValidationError(f"[{source}] schema 不支持: {schema!r}（本实现只接受 {SCHEMA!r}）")

    policy_id = _require_str(doc, "policyId", source)
    _validate(ids.ID_RE, policy_id, "路由策略 ID", source)
    if not policy_id.startswith(POLICY_ID_PREFIX):
        raise SchemaValidationError(
            f"[{source}] 路由策略 ID 必须以 {POLICY_ID_PREFIX!r} 开头: {policy_id!r}")

    version = _require_str(doc, "version", source)
    _validate(ids.SEMVER_RE, version, "version", source)

    title = _require_str(doc, "title", source)

    default_decision = _require_str(doc, "defaultDecision", source).upper()
    if default_decision != DECISION_DENY:
        raise SchemaValidationError(
            f"[{source}] defaultDecision 只允许 {DECISION_DENY!r}（fail-closed），"
            f"实际为 {default_decision!r}")

    rules_raw = doc.get("rules")
    if not isinstance(rules_raw, list) or not rules_raw:
        raise SchemaValidationError(f"[{source}] rules 必须是非空数组")

    rules: list[RouteRule] = []
    for item in rules_raw:
        if not isinstance(item, dict):
            raise SchemaValidationError(f"[{source}] rules 元素必须是对象: {item!r}")
        unknown_rule = sorted(set(item) - _RULE_FIELDS)
        if unknown_rule:
            raise SchemaValidationError(f"[{source}] 规则含未声明字段: {unknown_rule}")
        priority = item.get("priority")
        if not isinstance(priority, int) or isinstance(priority, bool) or priority < 0:
            raise SchemaValidationError(f"[{source}] 规则 priority 必须是非负整数: {priority!r}")
        task_type = item.get("taskType")
        if not isinstance(task_type, str) or not task_type.strip():
            raise SchemaValidationError(f"[{source}] 规则 taskType 必须是非空字符串")
        map_id = item.get("knowledgeMapId")
        if not isinstance(map_id, str) or not map_id.strip():
            raise SchemaValidationError(f"[{source}] 规则 knowledgeMapId 必须是非空字符串")
        _validate(ids.ID_RE, map_id.strip(), "知识地图 ID", source)
        reason = item.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            raise SchemaValidationError(f"[{source}] 规则 reason 必须是非空字符串（需可解释）")
        rules.append(RouteRule(priority=priority, task_type=task_type.strip(),
                               knowledge_map_id=map_id.strip(), reason=reason.strip()))

    # 刻意**不**在解析期拒绝"同任务同优先级"：歧义在**解析任务时**被拒绝
    # （见 RouteResolver.resolve），这样一条歧义规则只影响它自己那个任务，其余任务仍可正常路由
    # （fail-closed 的爆炸半径最小化）；定义期直接失败会让整份策略不可用。
    return RoutePolicy(policy_id=policy_id, version=version, title=title,
                       default_decision=default_decision, rules=tuple(rules), source_path=source)


def load_route_policy(workspace: Path) -> RoutePolicy | None:
    """加载工作区策略；文件不存在返回 ``None``（由调用方按"默认拒绝"处理）。"""
    p = policy_path(workspace)
    if not p.is_file():
        return None
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SchemaValidationError(f"[{POLICY_FILENAME}] 策略定义无法解析: {exc}") from exc
    return parse_route_policy(doc, source=POLICY_FILENAME)


class RouteResolver:
    """路由解析器：策略 + 注册表 → 唯一合法地图（fail-closed）。"""

    def __init__(self, registry: KnowledgeMapRegistry, policy: RoutePolicy | None):
        self._registry = registry
        self._policy = policy
        self._validate_cross_references()

    @classmethod
    def load(cls, workspace: Path) -> "RouteResolver":
        """从工作区加载注册表与策略并构造解析器。"""
        return cls(KnowledgeMapRegistry.load(workspace), load_route_policy(workspace))

    @property
    def policy(self) -> RoutePolicy | None:
        return self._policy

    @property
    def registry(self) -> KnowledgeMapRegistry:
        return self._registry

    def _validate_cross_references(self) -> None:
        """策略规则指向的地图必须存在；地图若声明 routePolicyRef 必须与本策略一致。"""
        if self._policy is None:
            return
        for rule in self._policy.rules:
            if rule.knowledge_map_id not in self._registry:
                raise SchemaValidationError(
                    f"[{self._policy.source_path}] 规则指向未注册的知识地图: "
                    f"{rule.knowledge_map_id}（taskType={rule.task_type}）")
        for m in self._registry.maps:
            if m.route_policy_ref and m.route_policy_ref != self._policy.policy_id:
                raise SchemaValidationError(
                    f"[{m.source_path}] 地图声明的 routePolicyRef="
                    f"{m.route_policy_ref!r} 与策略 {self._policy.policy_id!r} 不一致（防错配）")

    def resolve(self, task_type: str) -> RouteResolution:
        """把任务类型解析为唯一合法地图。

        默认拒绝：策略缺失 / 任务未映射 / 同优先级歧义 均返回拒绝，**不回落**。
        """
        if not isinstance(task_type, str) or not task_type.strip():
            raise SchemaValidationError(f"任务类型必须是非空字符串: {task_type!r}")
        task = task_type.strip()

        if self._policy is None:
            return RouteResolution(
                code=CODE_NO_POLICY,
                reason=f"控制面未配置路由策略（{POLICY_FILENAME} 缺失）⇒ 默认拒绝")
        if not self._policy.rules:
            return RouteResolution(
                code=CODE_NOT_MAPPED, reason="策略未声明任何规则 ⇒ 默认拒绝",
                policy=self._policy)

        matched = self._policy.rules_for(task)
        if not matched:
            declared = sorted({r.task_type for r in self._policy.rules})
            return RouteResolution(
                code=CODE_NOT_MAPPED,
                reason=f"任务未映射到任何路由规则: {task}（已声明任务: {declared}）",
                policy=self._policy)

        top_priority = matched[0].priority
        top = [r for r in matched if r.priority == top_priority]
        if len(top) > 1:
            return RouteResolution(
                code=CODE_AMBIGUOUS,
                reason=(f"任务 {task} 被 {len(top)} 条**同优先级**（{top_priority}）规则声明，"
                        f"歧义不可裁决（fail-closed）"),
                policy=self._policy,
                candidates=tuple(sorted(r.knowledge_map_id for r in top)))

        rule = top[0]
        if rule.knowledge_map_id not in self._registry:
            return RouteResolution(
                code=CODE_MAP_UNKNOWN,
                reason=f"规则指向未注册的知识地图: {rule.knowledge_map_id}",
                policy=self._policy, rule=rule)

        m = self._registry.get(rule.knowledge_map_id)
        if m.route_policy_ref and m.route_policy_ref != self._policy.policy_id:
            return RouteResolution(
                code=CODE_MAP_POLICY_MISMATCH,
                reason=(f"地图 {m.map_id} 声明 routePolicyRef={m.route_policy_ref!r}，"
                        f"与策略 {self._policy.policy_id!r} 不一致"),
                policy=self._policy, rule=rule)

        # 地图自身的任务声明必须包含该任务（地图与策略双侧一致性）
        if task not in m.tasks:
            return RouteResolution(
                code=CODE_NOT_MAPPED,
                reason=f"规则把任务 {task} 路由到 {m.map_id}，但该地图未声明此任务 "
                       f"（地图声明: {list(m.tasks)}）",
                policy=self._policy, rule=rule)

        return RouteResolution(code=CODE_OK, reason=rule.reason, policy=self._policy,
                               rule=rule, map=m)

    def resolve_via_registry_only(self, task_type: str) -> MapResolution:
        """仅按注册表解析（无策略时的降级查询；**不由本类用于放行**）。"""
        return self._registry.resolve_for_task(task_type)


# --------------------------------------------------------------------------- #
# 内部助手
# --------------------------------------------------------------------------- #

def _validate(pattern: "re.Pattern[str]", value: str, label: str, source: str) -> str:
    if not pattern.match(value):
        raise SchemaValidationError(f"[{source}] 非法{label}: {value!r}（须匹配 {pattern.pattern}）")
    return value


def _require_str(doc: dict, key: str, source: str) -> str:
    value = doc.get(key)
    if not isinstance(value, str) or not value.strip():
        raise SchemaValidationError(f"[{source}] 缺少必填字段或类型错误: {key}（须为非空字符串）")
    return value.strip()
