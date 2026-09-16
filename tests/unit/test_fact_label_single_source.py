"""D-28 层 2 第五片：**断言事实标签域**（F/C/B/H/P/A）单源核对。

分工（**不重复钉同一条**）：

- **源** = ``kert.domain.fact_label``（`FACT_LABELS` + 具名常量 + 三个派生集合）—— 本文件 ①②；
- **消费者（真实路径）** = `proposal_rules.evaluate`（必填校验 / 对客版泄漏复核 / G3 前承诺拦截）、
  `ServiceProposalExecutor._filter_customer`（段落级过滤）、`report`（译名 + 上色）—— 本文件 ③④；
- **SP-20 端到端**：对客版 `includes`/`excludes` 的**字节钉子**（派生集合保序）—— 本文件 ⑤；
- **合同** = OpenAPI `Citation.factLabel` —— 由 `test_contract_enum_single_source.py` 的 `MAPPINGS` 核对。

⚠ 边界（不得合并）：`product_recommendation.eligibility._RATING_ORDER`（信用评级域）—— 本文件 ⑦。
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (str(REPO_ROOT / "src"), str(REPO_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from kert.application import proposal_rules, report  # noqa: E402
from kert.application.product_recommendation import eligibility  # noqa: E402
from kert.application.service_proposal import ServiceProposalExecutor  # noqa: E402
from kert.application.skills import SkillExecutionService  # noqa: E402
from kert.domain.fact_label import (  # noqa: E402
    CUSTOMER_SAFE_LABELS,
    FACT_LABELS,
    LABEL_ASSERTION,
    LABEL_BELIEF,
    LABEL_FACT,
    LABEL_HYPOTHESIS,
    LABEL_INFERENCE,
    LABEL_PREDICTION,
    NON_CUSTOMER_SAFE_LABELS,
    PENDING_LABEL,
    RISK_LABELS,
)

CONSUMER_SRCS = {
    "proposal_rules.py": REPO_ROOT / "src" / "kert" / "application" / "proposal_rules.py",
    "service_proposal.py": REPO_ROOT / "src" / "kert" / "application" / "service_proposal.py",
    "report.py": REPO_ROOT / "src" / "kert" / "application" / "report.py",
    "llm.py": REPO_ROOT / "src" / "kert" / "infrastructure" / "adapters" / "llm.py",
}

SP20_CTX = {
    "schemaVersion": "1.0.0", "customerId": "CUST-CORP-0001",
    "customerName": "华东精工装备集团有限公司", "industry": "制造业-装备制造",
    "engagementPhase": "FIRST_CONTACT", "journeyId": "J-1", "operatingCaseId": "OC-1",
    "roundNumber": 1,
    "proposalContext": {"proposalType": "INITIAL",
                        "gateState": {"passed": ["G0"], "current": "G1"}},
}


def _claim(label: str, text: str = "断言原文") -> dict:
    return {"claim": text, "factLabel": label, "source": "KI-001", "date": "2026-08-01"}


def _chapter(*claims: dict) -> list[dict]:
    return [{"chapterId": "CH01", "claims": list(claims)}]


def _rule_ids(violations: list[dict]) -> set[str]:
    return {v["ruleId"] for v in violations}


# --------------------------------------------------------------------------- #
# ① 源自身 + ② 派生集合
# --------------------------------------------------------------------------- #

def test_source_is_closed_ordered_and_named():
    assert FACT_LABELS == ("F", "C", "B", "H", "P", "A")
    assert (LABEL_FACT, LABEL_INFERENCE, LABEL_BELIEF,
            LABEL_HYPOTHESIS, LABEL_PREDICTION, LABEL_ASSERTION) == FACT_LABELS
    assert len(set(FACT_LABELS)) == len(FACT_LABELS), "值域必须互异"


def test_derived_collections_partition_the_source_in_order():
    """派生集合必须**由源派生**且**保序**（对客版 includes/excludes 是**有序**输出）。"""
    assert CUSTOMER_SAFE_LABELS == (LABEL_FACT, LABEL_ASSERTION) == ("F", "A")
    assert NON_CUSTOMER_SAFE_LABELS == ("C", "B", "H", "P"), "必须是源的**保序**补集"
    assert set(CUSTOMER_SAFE_LABELS) | set(NON_CUSTOMER_SAFE_LABELS) == set(FACT_LABELS)
    assert not (set(CUSTOMER_SAFE_LABELS) & set(NON_CUSTOMER_SAFE_LABELS)), "两集合必须互斥"
    assert RISK_LABELS == (LABEL_INFERENCE, LABEL_BELIEF) == ("C", "B")
    assert PENDING_LABEL == LABEL_PREDICTION == "P"


def test_display_maps_are_complete_over_the_source():
    """**机械**完备性：两张展示映射的键集合 == 源（缺键 / 多键 / 拼错都红）。"""
    assert set(report.LABEL_CN) == set(FACT_LABELS), sorted(set(report.LABEL_CN))
    assert set(report.LABEL_COLOR) == set(FACT_LABELS), sorted(set(report.LABEL_COLOR))
    assert len(set(report.LABEL_COLOR.values())) == len(FACT_LABELS), "颜色必须互异"
    assert all(report.LABEL_CN[k].strip() for k in FACT_LABELS), "译名不得为空"


# --------------------------------------------------------------------------- #
# ③ 规则校验：闭集必填 + 对客版泄漏 + G3 前承诺（真实函数）
# --------------------------------------------------------------------------- #

def test_unknown_label_is_rejected_by_the_closed_set():
    """未知标签 ⇒ `FACT_LABEL_MANDATORY`（**闭集是判据**：源若被放宽，本用例先红）。"""
    out = proposal_rules.evaluate(_chapter(_claim("Z")), None, {})
    assert _rule_ids(out["violations"]) == {"FACT_LABEL_MANDATORY"}, out
    assert out["blocking"] is True


def test_every_source_label_passes_the_mandatory_check():
    for lb in FACT_LABELS:
        out = proposal_rules.evaluate(_chapter(_claim(lb)), None, {})
        assert "FACT_LABEL_MANDATORY" not in _rule_ids(out["violations"]), lb


def test_customer_version_leak_uses_the_safe_set():
    """非 `CUSTOMER_SAFE_LABELS` 的断言进了对客版 ⇒ `DUAL_VERSION_PRINCIPLE`（按名比较）。"""
    c_claim = _claim(LABEL_INFERENCE, "C 类断言原文")
    leak = proposal_rules.evaluate(_chapter(c_claim), {"content": "C 类断言原文"}, {})
    assert "DUAL_VERSION_PRINCIPLE" in _rule_ids(leak["violations"]), leak

    f_claim = _claim(LABEL_FACT, "F 类断言原文")
    ok = proposal_rules.evaluate(_chapter(f_claim), {"content": "F 类断言原文"}, {})
    assert "DUAL_VERSION_PRINCIPLE" not in _rule_ids(ok["violations"]), ok


def test_pending_label_before_g3_is_blocked():
    """`PENDING_LABEL` 的断言在 G3 前进了对客版 ⇒ `NO_COMMITMENT_WITHOUT_APPROVAL`。"""
    p_claim = _claim(PENDING_LABEL, "P 类承诺原文")
    before = proposal_rules.evaluate(_chapter(p_claim), {"content": "P 类承诺原文"},
                                     {"passed": ["G0"], "current": "G1"})
    assert "NO_COMMITMENT_WITHOUT_APPROVAL" in _rule_ids(before["violations"]), before

    after = proposal_rules.evaluate(_chapter(p_claim), {"content": "P 类承诺原文"},
                                    {"passed": ["G0", "G3"], "current": "G4"})
    assert "NO_COMMITMENT_WITHOUT_APPROVAL" not in _rule_ids(after["violations"]), after


# --------------------------------------------------------------------------- #
# ④ 段落级过滤（真实方法）
# --------------------------------------------------------------------------- #

def test_filter_customer_keeps_only_safe_labels():
    draft = "甲段（F）\n\n乙段（C）\n\n丙段（A）"
    claims = [{"claim": "甲段（F）", "factLabel": LABEL_FACT},
              {"claim": "乙段（C）", "factLabel": LABEL_INFERENCE},
              {"claim": "丙段（A）", "factLabel": LABEL_ASSERTION}]
    out = ServiceProposalExecutor()._filter_customer(draft, claims)
    assert "甲段（F）" in out["content"] and "丙段（A）" in out["content"]
    assert "乙段（C）" not in out["content"], out["content"]
    assert out["notes"], "移除必须留痕（不得静默）"


# --------------------------------------------------------------------------- #
# ⑤ SP-20 端到端：对客版 includes/excludes 的**字节钉子**（派生集合保序）
# --------------------------------------------------------------------------- #

def test_sp20_customer_version_lists_are_byte_pinned(ws_provisioned):
    r = SkillExecutionService(ws_provisioned).execute(
        "SP-20", "fl-sp20-1", {"context": SP20_CTX})
    assert r.status == "ok", r.errors
    res = r.data["result"]
    custv = res["content"]["customerVersion"]
    assert custv["includes"] == ["F", "A"] == list(CUSTOMER_SAFE_LABELS)
    assert custv["excludes"] == ["C", "B", "H", "P"] == list(NON_CUSTOMER_SAFE_LABELS)
    labels = {c["factLabel"] for c in res["citations"]}
    assert labels and labels <= set(FACT_LABELS), labels


# --------------------------------------------------------------------------- #
# ⑥ 防复发：消费者不得再散落标签字面量
# --------------------------------------------------------------------------- #

def test_consumers_have_no_stray_label_literals():
    """只查**本域**的字面量形态（集合/映射/比较），且 `report` 的两张映射键必须是常量。"""
    patterns = ('("F", "A")', '("C", "B")', '== "P"', '"factLabel": "F"',
                '"F", "A"', '"C", "B", "H", "P"', "VALID_LABELS")
    for name, path in CONSUMER_SRCS.items():
        text = path.read_text(encoding="utf-8")
        hits = [p for p in patterns if p in text]
        assert hits == [], f"{name} 仍有标签字面量/旧常量：{hits}"
    assert "LABEL_COLOR = {LABEL_FACT:" in CONSUMER_SRCS["report.py"].read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# ⑦ 相邻域边界（禁止合并）
# --------------------------------------------------------------------------- #

def test_credit_rating_domain_is_not_merged():
    """信用评级域与本域**值重叠（A）、语义域不同** ⇒ 不得互相替换 / 合并取值域。"""
    rating = set(eligibility._RATING_ORDER)
    assert rating != set(FACT_LABELS), "两域取值集合相同 ⇒ 请重新裁定归属"
    assert rating - set(FACT_LABELS) == {"BBB", "AA", "AAA"}, sorted(rating)
    src = (REPO_ROOT / "src" / "kert" / "application" / "product_recommendation"
           / "eligibility.py").read_text(encoding="utf-8")
    assert "fact_label" not in src, "评级域不得依赖标签域（防误合并）"
