"""WP3-1：SP-15 第三步骤 NeedProfile 解析器集成测试。

状态块（CANDIDATE 交付）：
STATUS=CANDIDATE / FROZEN=NO / IMPLEMENTED=NO

覆盖用例（对齐派工验收要点）：
- 闭集与排序谓词契约
- VERIFIED_FACT 可驱动排序
- INFERRED_NEED 仅条件化建议（不冒充事实）
- CONFLICT 不进入正式排序
- UNKNOWN 生成待确认问题
- notFact 断言不冒充事实 / humanConfirmed 升级（不升为 VERIFIED_FACT）
- REJECTED/SUPERSEDED 排除
- 互动记录 INTENT 抽取 → INFERRED_NEED
- 证据引用逐条装配 / 状态强度排序 / to_dict 形状
"""
from __future__ import annotations

from dkws.application.product_recommendation.need_profile import (
    NEED_STATUS_CLOSED_SET,
    RANKABLE_NEED_STATUSES,
    NeedProfileResolver,
)


def make_claim(**overrides) -> dict:
    base = {
        "claimId": "CLM-001",
        "claimType": "FINANCING_NEED",
        "content": "客户需要补充流动资金",
        "status": "VERIFIED_FACT",
        "evidenceRef": "EV-CLM-001",
        "sourceInteractionId": "INT-001",
        "notFact": False,
        "requiresReconciliation": False,
        "conflictWith": None,
        "humanConfirmed": False,
    }
    base.update(overrides)
    return base


def make_interaction(**overrides) -> dict:
    base = {
        "interactionId": "INT-001",
        "summary": "客户提出流动资金需求",
        "extractions": [
            {
                "objectId": "EXT-001",
                "type": "INTENT",
                "claimType": "FINANCING_NEED",
                "content": "希望补充流动资金",
                "speaker": "CUSTOMER",
                "evidenceRef": "EV-INT-001",
                "status": "",
                "notFact": False,
                "requiresReconciliation": False,
                "conflictWith": None,
                "humanConfirmed": False,
            }
        ],
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# 闭集契约
# ---------------------------------------------------------------------------
def test_closed_sets_match_contract():
    assert set(NEED_STATUS_CLOSED_SET) == {
        "VERIFIED_FACT", "HUMAN_CONFIRMED", "INFERRED_NEED", "UNKNOWN", "CONFLICT"}
    assert set(RANKABLE_NEED_STATUSES) == {"VERIFIED_FACT", "HUMAN_CONFIRMED", "INFERRED_NEED"}


# ---------------------------------------------------------------------------
# VERIFIED_FACT 可驱动排序
# ---------------------------------------------------------------------------
def test_verified_fact_drives_ranking():
    facts = {"needs": [{
        "needId": "NEED-001", "needType": "FINANCING",
        "status": "VERIFIED_FACT", "evidenceRefs": ["EV-NEED-001"],
    }]}
    result = NeedProfileResolver().resolve(facts=facts)

    assert len(result.profile) == 1
    item = result.profile[0]
    assert item.needId == "NEED-001"
    assert item.needStatus == "VERIFIED_FACT"
    assert item.priority == 1

    # VERIFIED_FACT 进入正式排序，且是排名驱动项
    assert result.rankable() == [item]
    assert result.ranking_drivers() == [item]
    assert result.conditional_suggestions() == []


# ---------------------------------------------------------------------------
# INFERRED_NEED 仅条件化建议（不冒充事实）
# ---------------------------------------------------------------------------
def test_inferred_need_is_conditional_only():
    claim = make_claim(status="CANDIDATE", claimId="CLM-002")
    result = NeedProfileResolver().resolve(claims=[claim])

    assert len(result.profile) == 1
    item = result.profile[0]
    assert item.needStatus == "INFERRED_NEED"
    # 不冒充事实
    assert item.needStatus != "VERIFIED_FACT"
    # 可排序（条件化建议），但不是排名驱动项
    assert item in result.rankable()
    assert result.ranking_drivers() == []
    assert result.conditional_suggestions() == [item]


# ---------------------------------------------------------------------------
# CONFLICT 不进入正式排序
# ---------------------------------------------------------------------------
def test_conflict_excluded_from_ranking():
    # 同一 needId：一条 VERIFIED_FACT 与一条 notFact 断言并存 → CONFLICT
    verified = make_claim(claimId="CLM-010", needId="NEED-001", needType="FINANCING",
                          status="VERIFIED_FACT", evidenceRef="EV-010", notFact=False)
    contrad = make_claim(claimId="CLM-011", needId="NEED-001", needType="FINANCING",
                         claimType="CUSTOMER_STATEMENT", status="CANDIDATE",
                         evidenceRef="EV-011", notFact=True)
    result = NeedProfileResolver().resolve(claims=[verified, contrad])

    assert len(result.profile) == 1
    item = result.profile[0]
    assert item.needStatus == "CONFLICT"
    assert item.priority is None
    # 不进入正式排序
    assert result.rankable() == []
    assert result.ranking_drivers() == []
    assert result.conditional_suggestions() == []
    # 冲突被如实记录
    assert any(c["needId"] == "NEED-001" for c in result.conflicts)


def test_explicit_conflict_flag_is_conflict():
    claim = make_claim(claimId="CLM-012", needId="NEED-002", status="VERIFIED_FACT",
                       conflictWith="CLM-013")
    result = NeedProfileResolver().resolve(claims=[claim])

    assert len(result.profile) == 1
    assert result.profile[0].needStatus == "CONFLICT"
    assert result.rankable() == []
    assert any(c["needId"] == "NEED-002" for c in result.conflicts)


# ---------------------------------------------------------------------------
# UNKNOWN 生成待确认问题
# ---------------------------------------------------------------------------
def test_unknown_generates_question():
    # 已核验需求版本被引用，但无任何事实/断言支撑 → UNKNOWN
    result = NeedProfileResolver().resolve(facts={}, need_version_ids=["NEEDV-001"])

    assert len(result.profile) == 1
    item = result.profile[0]
    assert item.needStatus == "UNKNOWN"
    assert item.priority is None
    assert result.rankable() == []

    assert len(result.questions) == 1
    q = result.questions[0]
    assert q["needId"] == item.needId
    assert q["question"]
    assert q["suggestedAction"]


# ---------------------------------------------------------------------------
# notFact 断言不冒充事实
# ---------------------------------------------------------------------------
def test_not_fact_cannot_masquerade_as_verified():
    claim = make_claim(status="VERIFIED_FACT", notFact=True)
    result = NeedProfileResolver().resolve(claims=[claim])

    item = result.profile[0]
    assert item.needStatus == "INFERRED_NEED"
    assert item.needStatus != "VERIFIED_FACT"


# ---------------------------------------------------------------------------
# humanConfirmed 升级（仍不冒充 VERIFIED_FACT）
# ---------------------------------------------------------------------------
def test_human_confirmed_upgrades_inferred_not_to_verified():
    claim = make_claim(status="CANDIDATE", humanConfirmed=True)
    result = NeedProfileResolver().resolve(claims=[claim])

    item = result.profile[0]
    assert item.needStatus == "HUMAN_CONFIRMED"
    assert item.needStatus != "VERIFIED_FACT"
    # HUMAN_CONFIRMED 属已证实，可驱动排序
    assert result.ranking_drivers() == [item]


# ---------------------------------------------------------------------------
# REJECTED / SUPERSEDED 排除
# ---------------------------------------------------------------------------
def test_rejected_and_superseded_claims_are_excluded():
    claims = [
        make_claim(claimId="CLM-100", status="REJECTED"),
        make_claim(claimId="CLM-101", status="SUPERSEDED"),
    ]
    result = NeedProfileResolver().resolve(claims=claims)
    assert result.profile == []


# ---------------------------------------------------------------------------
# 互动记录 INTENT 抽取 → INFERRED_NEED
# ---------------------------------------------------------------------------
def test_interaction_intent_becomes_inferred():
    result = NeedProfileResolver().resolve(interactions=[make_interaction()])

    assert len(result.profile) == 1
    item = result.profile[0]
    assert item.needStatus == "INFERRED_NEED"
    assert item.needType == "FINANCING"
    assert "EV-INT-001" in item.evidenceRefs


# ---------------------------------------------------------------------------
# 证据引用逐条装配（跨来源去重）
# ---------------------------------------------------------------------------
def test_evidence_refs_attached_per_item_and_deduped():
    facts = {"needs": [{
        "needId": "NEED-001", "needType": "FINANCING",
        "status": "VERIFIED_FACT", "evidenceRefs": ["EV-NEED-001"],
    }]}
    claim = make_claim(claimId="CLM-020", needId="NEED-001", needType="FINANCING",
                       evidenceRef="EV-NEED-001")
    result = NeedProfileResolver().resolve(facts=facts, claims=[claim])

    item = result.profile[0]
    assert item.needStatus == "VERIFIED_FACT"
    # 去重后仍保留一条证据引用
    assert item.evidenceRefs == ["EV-NEED-001"]


# ---------------------------------------------------------------------------
# 状态强度排序
# ---------------------------------------------------------------------------
def test_priority_orders_by_status_strength():
    facts = {"needs": [
        {"needId": "NEED-B", "needType": "EXPANSION", "status": "INFERRED_NEED",
         "evidenceRefs": ["EV-B"]},
        {"needId": "NEED-A", "needType": "FINANCING", "status": "VERIFIED_FACT",
         "evidenceRefs": ["EV-A"]},
    ]}
    result = NeedProfileResolver().resolve(facts=facts)

    ranked = result.rankable()
    assert [it.needId for it in ranked] == ["NEED-A", "NEED-B"]
    assert [it.priority for it in ranked] == [1, 2]


# ---------------------------------------------------------------------------
# to_dict 形状
# ---------------------------------------------------------------------------
def test_result_to_dict_shape():
    facts = {"needs": [{
        "needId": "NEED-001", "needType": "FINANCING",
        "status": "VERIFIED_FACT", "evidenceRefs": ["EV-NEED-001"],
    }]}
    result = NeedProfileResolver().resolve(facts=facts)
    d = result.to_dict()

    assert d["schemaVersion"] == "1.0.0"
    assert set(d.keys()) == {"schemaVersion", "needProfile", "questions", "conflicts", "trace"}
    assert len(d["needProfile"]) == 1
    item = d["needProfile"][0]
    assert set(item.keys()) == {"needId", "needType", "needStatus", "evidenceRefs", "priority"}
    assert item["needStatus"] == "VERIFIED_FACT"
