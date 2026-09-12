"""SP-15 第三步骤 NeedProfile 解析器（确定性、无 LLM）。

状态块（CANDIDATE 交付）：
STATUS=CANDIDATE / FROZEN=NO / IMPLEMENTED=NO

依据：
- skills/product-recommendation/SP-15.md（§2 第二段输入「客户事实快照、已确认需求、互动记录」；
  §3 步骤 3 `NeedProfileResolver` 输出「带状态/证据的 NeedProfile」；需求状态闭集
  VERIFIED_FACT / HUMAN_CONFIRMED / INFERRED_NEED / UNKNOWN / CONFLICT）
- skills/product-recommendation/contracts/recommendation-result.md（needProfile 元素结构）
- gits-cbanking specs/product-recommendation/recommendation-result.schema.json
  （NeedProfileItem：needId/needType/needStatus/evidenceRefs/priority）
- gits-cbanking specs/product-recommendation/product-fit-result.schema.json（NeedStatus 闭集）
- gits-cbanking specs/knowledge-architecture/activations/AC-PRODUCT-RECOMMEND-001.json
  （context.priorityOrder：VERIFIED_FACT > HUMAN_CONFIRMED > CONFLICT > UNKNOWN > ...）
- gits-cbanking specs/openapi/gits-kno-api.openapi.json（Claim/ClaimType/ClaimStatus/Interaction/Extraction 数据形状）

职责（本模块 = 三段式步骤 3，纯确定性函数）：
1. 把三类输入（客户事实快照 facts / 断言 claims / 互动记录 interactions）归一为「需求候选」；
2. 逐候选推导需求状态（NeedStatus 五态闭集），并对同 needId 聚合为一条 NeedProfileItem；
3. 强约束（机器可测）：
   - INFERRED_NEED 不得冒充事实（notFact 断言 / 候选断言 / 未核实意图一律不升格为 VERIFIED_FACT）；
   - CONFLICT 不进入正式排序（priority=None，rankable 排除）；
   - UNKNOWN 生成待确认问题（questions），且不进入正式排序；
   - 每条 NeedProfileItem 携带证据引用（evidenceRefs）。

需求状态推导（确定性，优先级从高到低）：
    VERIFIED_FACT > HUMAN_CONFIRMED > INFERRED_NEED > UNKNOWN；CONFLICT 为独立态、不参与排序。
- ClaimStatus/ExtractionStatus → NeedStatus 缺省映射：
    VERIFIED_FACT→VERIFIED_FACT；CANDIDATE/DETECTED→INFERRED_NEED；
    REJECTED/SUPERSEDED→排除（不构成 need）。
- 额外旗标：
    humanConfirmed=True → 把 INFERRED_NEED/UNKNOWN 升为 HUMAN_CONFIRMED（仍不冒充 VERIFIED_FACT）；
    notFact=True → 把 VERIFIED_FACT/HUMAN_CONFIRMED 降为 INFERRED_NEED；
    requiresReconciliation=True → 无结论时落 UNKNOWN（生成待确认问题）；
    conflictWith 非空 / status=CONFLICT → CONFLICT。
- 同 needId 聚合：任一来源 CONFLICT，或「已证实来源」与「notFact 来源」并存 → CONFLICT；
  否则取最强状态。

本模块不调用 LLM，不产生任何网络/文件副作用，纯确定性函数。
"""
from __future__ import annotations

from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# 闭集枚举（对齐 product-fit-result.schema.json / recommendation-result.schema.json）
# ---------------------------------------------------------------------------
NEED_STATUS_CLOSED_SET = (
    "VERIFIED_FACT",
    "HUMAN_CONFIRMED",
    "INFERRED_NEED",
    "UNKNOWN",
    "CONFLICT",
)

# 可参与正式排序的状态（CONFLICT 与 UNKNOWN 排除）
RANKABLE_NEED_STATUSES = ("VERIFIED_FACT", "HUMAN_CONFIRMED", "INFERRED_NEED")

# 状态强度序（越小越强，用于聚合与排序）；CONFLICT 不在此列
_NEED_STATUS_ORDER = ("VERIFIED_FACT", "HUMAN_CONFIRMED", "INFERRED_NEED", "UNKNOWN")

# GITS Claim/Extraction 状态 → NeedStatus 缺省映射（REJECTED/SUPERSEDED → None 表示排除）
_CLAIM_STATUS_TO_NEED = {
    "VERIFIED_FACT": "VERIFIED_FACT",
    "HUMAN_CONFIRMED": "HUMAN_CONFIRMED",
    "CANDIDATE": "INFERRED_NEED",
    "DETECTED": "INFERRED_NEED",
    "UNKNOWN": "UNKNOWN",
    "CONFLICT": "CONFLICT",
    "REJECTED": None,
    "SUPERSEDED": None,
}

# GITS ClaimType → needType 缺省映射（仅作缺省，显式 needType 优先）
_CLAIM_TYPE_TO_NEED_TYPE = {
    "FINANCING_NEED": "FINANCING",
    "EXPANSION_INTENT": "EXPANSION",
    "MATERIAL_PROVIDE": "MATERIAL",
    "RM_COMMITMENT": "SERVICE_COMMITMENT",
    "CUSTOMER_STATEMENT": "STATEMENT",
    "FOLLOW_UP": "FOLLOW_UP",
    "RISK_SIGNAL": "RISK_SIGNAL",
    "CUSTOMER_JOURNEY": "JOURNEY",
}

# 无显式 needId/needType 时，只有这些 ClaimType 会被视为「需求候选」
_NEED_CLAIM_TYPES = {"FINANCING_NEED", "EXPANSION_INTENT", "MATERIAL_PROVIDE"}

# 互动抽取中视为「需求信号」的类型（INTENT/CLARIFIED_INTENT 默认 INFERRED_NEED）
_INTENT_EXTRACTION_TYPES = {"INTENT", "CLARIFIED_INTENT"}
_NEED_EXTRACTION_TYPES = {"CLAIM", "FACT_CLAIM", "INTENT", "CLARIFIED_INTENT"}


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------
def _as_list(value) -> list[str]:
    """把单值/列表证据引用规整为去重列表。"""
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        out = []
        for v in value:
            if isinstance(v, str) and v:
                out.append(v)
        return _dedupe(out)
    if isinstance(value, str) and value:
        return [value]
    return []


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for it in items:
        if it not in seen:
            seen.add(it)
            out.append(it)
    return out


def _status_rank(status: str) -> int:
    return _NEED_STATUS_ORDER.index(status) if status in _NEED_STATUS_ORDER else 99


# ---------------------------------------------------------------------------
# 结果对象
# ---------------------------------------------------------------------------
@dataclass
class NeedProfileItem:
    needId: str
    needType: str
    needStatus: str
    evidenceRefs: list[str] = field(default_factory=list)
    priority: int | None = None

    def to_dict(self) -> dict:
        return {
            "needId": self.needId,
            "needType": self.needType,
            "needStatus": self.needStatus,
            "evidenceRefs": list(self.evidenceRefs),
            "priority": self.priority,
        }


@dataclass
class NeedProfileResult:
    schemaVersion: str = "1.0.0"
    profile: list[NeedProfileItem] = field(default_factory=list)
    questions: list[dict] = field(default_factory=list)
    conflicts: list[dict] = field(default_factory=list)
    trace: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "schemaVersion": self.schemaVersion,
            "needProfile": [it.to_dict() for it in self.profile],
            "questions": list(self.questions),
            "conflicts": list(self.conflicts),
            "trace": list(self.trace),
        }

    def rankable(self) -> list[NeedProfileItem]:
        """正式排序集合：排除 CONFLICT 与 UNKNOWN，按 priority 升序。"""
        return rankable_needs(self.profile)

    def ranking_drivers(self) -> list[NeedProfileItem]:
        """可驱动推荐排序的需求（已证实：VERIFIED_FACT / HUMAN_CONFIRMED）。"""
        return ranking_drivers(self.profile)

    def conditional_suggestions(self) -> list[NeedProfileItem]:
        """仅条件化建议（INFERRED_NEED，不得作为强推介理由）。"""
        return conditional_suggestions(self.profile)


def rankable_needs(items: list[NeedProfileItem]) -> list[NeedProfileItem]:
    return sorted(
        [it for it in items if it.needStatus in RANKABLE_NEED_STATUSES],
        key=lambda it: (it.priority if it.priority is not None else 9999, it.needId),
    )


def ranking_drivers(items: list[NeedProfileItem]) -> list[NeedProfileItem]:
    return [it for it in rankable_needs(items)
            if it.needStatus in ("VERIFIED_FACT", "HUMAN_CONFIRMED")]


def conditional_suggestions(items: list[NeedProfileItem]) -> list[NeedProfileItem]:
    return [it for it in rankable_needs(items) if it.needStatus == "INFERRED_NEED"]


# ---------------------------------------------------------------------------
# NeedProfileResolver
# ---------------------------------------------------------------------------
class NeedProfileResolver:
    """从客户事实/claims/interactions 解析带状态的 NeedProfile（确定性，无 LLM）。"""

    def resolve(self, facts=None, claims=None, interactions=None, *,
                need_version_ids=None) -> NeedProfileResult:
        facts = facts or {}
        claims = claims or []
        interactions = interactions or []
        need_version_ids = _as_list(need_version_ids) or _as_list(facts.get("needVersionIds"))

        result = NeedProfileResult()
        # needId -> {statuses, needType, evidenceRefs, conflict, priorityHint, notFact, sources}
        groups: dict[str, dict] = {}

        # 1) 客户事实快照中已解析的需求
        for idx, need in enumerate(facts.get("needs") or []):
            if not isinstance(need, dict):
                continue
            cand = self._normalize_need_entry(need, idx)
            if cand is None:
                continue
            self._add_candidate(groups, result, cand)

        # 2) 断言 claims
        for claim in claims:
            if not isinstance(claim, dict):
                continue
            cand = self._normalize_claim(claim)
            if cand is None:
                continue
            self._add_candidate(groups, result, cand)

        # 3) 互动记录 interactions（经抽取 extractions）
        for interaction in interactions:
            if not isinstance(interaction, dict):
                continue
            for ext in interaction.get("extractions") or []:
                if not isinstance(ext, dict):
                    continue
                cand = self._normalize_extraction(ext, interaction)
                if cand is None:
                    continue
                self._add_candidate(groups, result, cand)

        # 4) 已核验需求版本被引用但无任何事实/断言支撑 → UNKNOWN（生成待确认问题）
        for nvid in need_version_ids:
            if nvid not in groups:
                need_id = f"NEED-{nvid}"
                groups[need_id] = {
                    "statuses": ["UNKNOWN"],
                    "needType": "UNSPECIFIED",
                    "evidenceRefs": [],
                    "conflict": False,
                    "notFact": False,
                    "sources": [{"sourceType": "REFERENCE", "sourceId": nvid}],
                }
                result.trace.append({
                    "step": "REFERENCE_WITHOUT_EVIDENCE",
                    "needId": need_id,
                    "message": f"已核验需求版本 {nvid} 无对应事实/断言支撑，落 UNKNOWN",
                })

        # 5) 聚合为 NeedProfileItem
        for need_id, g in groups.items():
            statuses = g["statuses"]
            if g["conflict"] or "CONFLICT" in statuses or (
                    any(s in ("VERIFIED_FACT", "HUMAN_CONFIRMED") for s in statuses)
                    and g["notFact"]):
                final_status = "CONFLICT"
            else:
                final_status = min(statuses, key=_status_rank)

            item = NeedProfileItem(
                needId=need_id,
                needType=g["needType"],
                needStatus=final_status,
                evidenceRefs=g["evidenceRefs"],
            )
            result.profile.append(item)
            result.trace.append({
                "step": "AGGREGATE",
                "needId": need_id,
                "needStatus": final_status,
                "sources": g["sources"],
            })

            if final_status == "CONFLICT":
                result.conflicts.append({
                    "needId": need_id,
                    "needType": g["needType"],
                    "message": "权威证据冲突或相互矛盾，禁止确定性解读",
                    "sources": list(g["sources"]),
                })
            elif final_status == "UNKNOWN":
                result.questions.append({
                    "needId": need_id,
                    "needType": g["needType"],
                    "question": f"需求 {need_id} 缺少可证实依据，请客户经理核实",
                    "suggestedAction": "核实客户需求并补充事实/断言证据后重跑",
                    "relatedEvidenceRefs": list(g["evidenceRefs"]),
                })

        # 6) 正式排序优先级：仅 rankable 状态，按状态强度 → needId（稳定）
        ranked = sorted(
            [it for it in result.profile if it.needStatus in RANKABLE_NEED_STATUSES],
            key=lambda it: (_status_rank(it.needStatus), it.needId),
        )
        for pos, it in enumerate(ranked, 1):
            it.priority = pos

        return result

    # ---- 归一化入口 ----

    @staticmethod
    def _normalize_need_entry(need: dict, idx: int) -> dict | None:
        need_id = need.get("needId") or need.get("needVersionId") or f"NEED-{idx + 1}"
        status = _derive_status(
            need.get("needStatus") or need.get("status") or "UNKNOWN",
            human_confirmed=bool(need.get("humanConfirmed")),
            not_fact=bool(need.get("notFact")),
            requires_reconciliation=bool(need.get("requiresReconciliation")),
            conflict_with=need.get("conflictWith"),
        )
        if status is None:
            return None
        return {
            "needId": need_id,
            "needType": need.get("needType") or "UNSPECIFIED",
            "status": status,
            "evidenceRefs": _as_list(need.get("evidenceRefs") or need.get("evidenceRef")),
            "conflictWith": need.get("conflictWith"),
            "notFact": bool(need.get("notFact")),
            "sourceType": "FACT_SNAPSHOT",
            "sourceId": need_id,
        }

    @staticmethod
    def _normalize_claim(claim: dict) -> dict | None:
        claim_type = claim.get("claimType") or ""
        need_id = claim.get("needId") or (
            f"NEED-{claim.get('claimId')}" if claim.get("claimId") else None)
        need_type = claim.get("needType") or _CLAIM_TYPE_TO_NEED_TYPE.get(claim_type)
        # 无显式 needId/needType 且 claimType 非需求类 → 不构成需求
        if need_id is None and need_type is None:
            if claim_type not in _NEED_CLAIM_TYPES:
                return None
            need_id = f"NEED-{claim.get('claimId') or claim_type}"
            need_type = _CLAIM_TYPE_TO_NEED_TYPE.get(claim_type, "UNSPECIFIED")
        if need_id is None:
            need_id = f"NEED-{claim.get('claimId') or 'CLAIM'}"
        if not need_type:
            need_type = _CLAIM_TYPE_TO_NEED_TYPE.get(claim_type, "UNSPECIFIED")

        status = _derive_status(
            claim.get("needStatus") or claim.get("status") or "",
            human_confirmed=bool(claim.get("humanConfirmed")),
            not_fact=bool(claim.get("notFact")),
            requires_reconciliation=bool(claim.get("requiresReconciliation")),
            conflict_with=claim.get("conflictWith"),
        )
        if status is None:
            return None
        return {
            "needId": need_id,
            "needType": need_type,
            "status": status,
            "evidenceRefs": _as_list(claim.get("evidenceRefs") or claim.get("evidenceRef")),
            "conflictWith": claim.get("conflictWith"),
            "notFact": bool(claim.get("notFact")),
            "sourceType": "CLAIM",
            "sourceId": claim.get("claimId") or need_id,
        }

    @staticmethod
    def _normalize_extraction(ext: dict, interaction: dict) -> dict | None:
        ext_type = ext.get("type") or ""
        claim_type = ext.get("claimType") or ""
        need_id = ext.get("needId") or (
            f"NEED-{ext.get('objectId')}" if ext.get("objectId") else None)
        need_type = ext.get("needType") or _CLAIM_TYPE_TO_NEED_TYPE.get(claim_type)
        if need_id is None and need_type is None:
            if claim_type not in _NEED_CLAIM_TYPES:
                return None
            need_id = f"NEED-{ext.get('objectId') or claim_type}"
            need_type = _CLAIM_TYPE_TO_NEED_TYPE.get(claim_type, "UNSPECIFIED")
        if need_id is None:
            need_id = f"NEED-{ext.get('objectId') or 'EXT'}"
        if not need_type:
            need_type = _CLAIM_TYPE_TO_NEED_TYPE.get(claim_type, "UNSPECIFIED")

        raw_status = ext.get("needStatus") or ext.get("status") or ""
        # 意图/澄清意图且无状态 → 默认 INFERRED_NEED（信号，不是事实）
        default = "INFERRED_NEED" if ext_type in _INTENT_EXTRACTION_TYPES else "UNKNOWN"
        status = _derive_status(
            raw_status,
            human_confirmed=bool(ext.get("humanConfirmed")),
            not_fact=bool(ext.get("notFact")),
            requires_reconciliation=bool(ext.get("requiresReconciliation")),
            conflict_with=ext.get("conflictWith"),
            default=default,
        )
        if status is None:
            return None
        return {
            "needId": need_id,
            "needType": need_type,
            "status": status,
            "evidenceRefs": _as_list(ext.get("evidenceRefs") or ext.get("evidenceRef")),
            "conflictWith": ext.get("conflictWith"),
            "notFact": bool(ext.get("notFact")),
            "sourceType": "INTERACTION",
            "sourceId": ext.get("objectId") or interaction.get("interactionId") or need_id,
        }

    # ---- 聚合 ----

    @staticmethod
    def _add_candidate(groups: dict, result: NeedProfileResult, cand: dict) -> None:
        need_id = cand["needId"]
        g = groups.setdefault(need_id, {
            "statuses": [],
            "needType": cand["needType"],
            "evidenceRefs": [],
            "conflict": False,
            "notFact": False,
            "sources": [],
        })
        if not g["needType"] or g["needType"] == "UNSPECIFIED":
            g["needType"] = cand["needType"]
        g["statuses"].append(cand["status"])
        g["evidenceRefs"] = _dedupe(g["evidenceRefs"] + cand["evidenceRefs"])
        g["sources"].append({"sourceType": cand["sourceType"], "sourceId": cand["sourceId"]})
        g["notFact"] = g["notFact"] or cand["notFact"]
        if cand["conflictWith"] or cand["status"] == "CONFLICT":
            g["conflict"] = True
            result.trace.append({
                "step": "CONFLICT_DETECTED",
                "needId": need_id,
                "message": f"来源 {cand['sourceId']} 标记冲突（conflictWith={cand['conflictWith']}）",
            })


# ---------------------------------------------------------------------------
# 状态推导（确定性）
# ---------------------------------------------------------------------------
def _derive_status(raw_status: str, *, human_confirmed: bool, not_fact: bool,
                   requires_reconciliation: bool, conflict_with, default: str = "UNKNOWN") -> str | None:
    """把原始状态 + 旗标推导为 NeedStatus；REJECTED/SUPERSEDED 返回 None（排除）。"""
    raw = (raw_status or "").strip()
    if raw in ("REJECTED", "SUPERSEDED"):
        return None
    if raw in NEED_STATUS_CLOSED_SET:
        base: str | None = raw
    elif raw in _CLAIM_STATUS_TO_NEED:
        base = _CLAIM_STATUS_TO_NEED[raw]
    else:
        base = default

    if base is None:
        return None

    # 显式冲突（conflictWith 非空）优先于一切
    if conflict_with:
        return "CONFLICT"

    # notFact：非事实断言不得冒充 VERIFIED_FACT / HUMAN_CONFIRMED
    if not_fact and base in ("VERIFIED_FACT", "HUMAN_CONFIRMED"):
        base = "INFERRED_NEED"

    # 需对账但无结论 → UNKNOWN（生成待确认问题）
    if requires_reconciliation and base != "CONFLICT":
        base = "UNKNOWN"

    # 人类确认升级（不冒充事实：HUMAN_CONFIRMED ≠ VERIFIED_FACT）
    if human_confirmed and base in ("INFERRED_NEED", "UNKNOWN"):
        base = "HUMAN_CONFIRMED"

    return base
