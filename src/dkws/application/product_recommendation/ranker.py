"""SP-15 第二段 CandidateRanker（可配置权重排序，确定性核心，无 LLM）。

状态块（CANDIDATE 交付）：
STATUS=CANDIDATE / FROZEN=NO / IMPLEMENTED=NO

依据：
- skills/product-recommendation/SP-15.md §2（FitScore=Σ(wi×mi)，权重由产品域 Owner
  按版本配置，只用于已合格候选内部排序）
- skills/product-recommendation/rules/README.md（排序策略：分数只用于已合格候选内部
  排序，不代表审批通过概率）
- gits-cbanking specs/product-recommendation/product-fit-result.schema.json
  （fitScore 允许 null；INELIGIBLE/UNKNOWN/REVIEW_REQUIRED 必须为 null，INV-02）

职责：
1. FitScore = Σ(wi × mi)，权重表可外部传入覆盖（默认权重表之和 = 1.0）。
2. 只对 ELIGIBLE 候选做内部排序并赋 rank（1..n，fitScore 降序，并列保持输入顺序稳定）。
3. INELIGIBLE / UNKNOWN / REVIEW_REQUIRED 候选：fitScore=None、rank=None，不参与排序。

不变量（本模块机器可测）：
- INV-02 Eligibility ∈ {INELIGIBLE, UNKNOWN, REVIEW_REQUIRED} → fitScore 必须为 None；
- 权重必须非负；未知维度键 → 拒绝（ValueError），不静默忽略。

本模块不调用 LLM，不产生任何网络/文件副作用，纯确定性函数。
"""
from __future__ import annotations

from dataclasses import replace

from dkws.application.product_recommendation.matcher import (
    DIMENSION_CLOSED_SET,
    DIMENSION_RESULT_CLOSED_SET,
    FitResult,
)

# 维度结果 → 归一化分值 mi（确定性；STRONG=1.0 / MODERATE=0.5 / WEAK=0.0 / UNKNOWN=0.0）
DIMENSION_RESULT_SCORE = {
    "STRONG": 1.0,
    "MODERATE": 0.5,
    "WEAK": 0.0,
    "UNKNOWN": 0.0,
}

# 默认权重表（候选默认值，和 = 1.0；产品域 Owner 按版本配置后覆盖）
DEFAULT_WEIGHTS = {
    "CORE_NEED_FIT": 0.35,
    "SCENARIO_FIT": 0.15,
    "EXECUTABILITY": 0.15,
    "RELATIONSHIP_INCREMENT": 0.10,
    "PORTFOLIO_SYNERGY": 0.10,
    "EVIDENCE_SUFFICIENCY": 0.15,
}

_NON_ELIGIBLE = {"INELIGIBLE", "UNKNOWN", "REVIEW_REQUIRED"}


class CandidateRanker:
    """对已合格（ELIGIBLE）候选做内部排序；非 ELIGIBLE 候选 fitScore=None（INV-02）。"""

    def __init__(self, weights: dict | None = None):
        self.weights = self._resolve_weights(weights)

    def rank(self, fit_results: list[FitResult]) -> list[FitResult]:
        """返回排序后的 FitResult 列表：ELIGIBLE 在前（rank 1..n），非 ELIGIBLE 随后
        （fitScore=None、rank=None，保持原相对顺序）。"""
        eligible: list[tuple[int, FitResult]] = []
        non_eligible: list[FitResult] = []
        for idx, fr in enumerate(fit_results):
            if fr.eligibility == "ELIGIBLE":
                score = self._fit_score(fr)
                eligible.append((idx, replace(fr, fitScore=score)))
            else:
                non_eligible.append(replace(fr, fitScore=None, rank=None))

        ranked: list[FitResult] = []
        # 稳定排序：fitScore 降序；并列按输入顺序（idx 升序）
        for position, (idx, fr) in enumerate(
                sorted(eligible, key=lambda t: (-(t[1].fitScore or 0.0), t[0])), start=1):
            ranked.append(replace(fr, rank=position))
        ranked.extend(non_eligible)
        return ranked

    def fit_score(self, fit_result: FitResult) -> float | None:
        if fit_result.eligibility != "ELIGIBLE":
            return None
        return self._fit_score(fit_result)

    def _fit_score(self, fr: FitResult) -> float:
        total = 0.0
        for dm in fr.dimensionMatches:
            mi = DIMENSION_RESULT_SCORE.get(dm.result)
            if mi is None:
                raise ValueError(
                    f"未知维度结果 {dm.result!r}（{dm.dimension}），"
                    f"闭集为 {DIMENSION_RESULT_CLOSED_SET}")
            total += self.weights.get(dm.dimension, 0.0) * mi
        return round(total, 6)

    @staticmethod
    def _resolve_weights(weights: dict | None) -> dict:
        resolved = dict(DEFAULT_WEIGHTS)
        if weights is None:
            return resolved
        for dim, w in (weights or {}).items():
            if dim not in DIMENSION_CLOSED_SET:
                raise ValueError(
                    f"未知权重维度 {dim!r}，闭集为 {DIMENSION_CLOSED_SET}")
            if not isinstance(w, (int, float)) or isinstance(w, bool):
                raise ValueError(f"权重 {dim!r} 必须为数值，收到 {w!r}")
            if w < 0:
                raise ValueError(f"权重 {dim!r} 不得为负，收到 {w!r}")
            resolved[dim] = float(w)
        return resolved
