"""SP-21 交互记忆抽取（Phase 3）。

- 输入：request.context = {interactionId, interactionContent, existingMemories[]}（GITS 传入）；
- LLM 从纪要抽取候选记忆（类别/置信度/建议衰减规则/原文引用）；
- 确定性比对：与已有记忆做重复检测（相似度）、强化（REINFORCE）、取代（SUPERSEDE，含否定语义）；
- 规则校验：CONFIDENCE_CALIBRATION / DECAY_RULE_APPLICATION / DUPLICATE_DETECTION；
- **DKWS 不存记忆**：candidateMemories/updates/supersessions 交 GITS InteractionMemoryPort 持久化。
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass

from ..infrastructure.adapters import llm as llm_mod

MEMORY_SKILL_ID = "SP-21"
MEMORY_CATEGORIES = ["PREFERENCE", "DECISION_PATTERN", "RELATIONSHIP",
                     "BUSINESS_SIGNAL", "EMOTIONAL_STATE"]
DECAY_RULES = ["NONE", "LINEAR", "STEP"]
NEGATION_MARKERS = ["不再", "取消", "终止", "改为", "反对", "不是", "拒绝", "停止", "撤回"]
SIM_THRESHOLD = 0.5

SYSTEM_PROMPT = """你是银行客户经理的交互记忆抽取助手。从客户交互纪要中抽取结构化洞察（交互记忆）。
纪律：只基于纪要内容，不臆造；每条记忆给出类别、置信度、建议衰减规则与原文引用。

记忆类别：
- PREFERENCE 客户偏好（如"偏好面对面沟通"）
- DECISION_PATTERN 决策模式（如"采购决策需3个月"）
- RELATIONSHIP 关系网络（如"CFO与CEO是大学同学"）
- BUSINESS_SIGNAL 业务信号（如"Q4有采购计划"）
- EMOTIONAL_STATE 情感状态（如"对现有银行服务不满意"）

输出 JSON（严格）：
{
  "candidateMemories": [
    { "memoryId": "MEM-xxx", "category": "PREFERENCE|DECISION_PATTERN|RELATIONSHIP|BUSINESS_SIGNAL|EMOTIONAL_STATE",
      "content": "记忆内容", "confidence": 0.0-1.0,
      "suggestedDecayRule": "NONE|LINEAR|STEP", "evidenceQuote": "纪要原文摘录" }
  ]
}"""


@dataclass
class _Token:
    pass


def _tokens(text: str) -> set[str]:
    """中文按 2-gram + 英文按词，简单归一用于相似度。"""
    toks = set()
    t = (text or "").strip()
    for i in range(len(t) - 1):
        toks.add(t[i:i + 2])
    toks.update(re.findall(r"[a-zA-Z0-9_]{2,}", t))
    return toks


def _similarity(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


class InteractionMemoryExecutor:
    def execute(self, request: dict, trace: list[dict]) -> tuple[dict, dict]:
        ctx = request.get("context") or request
        iid = ctx.get("interactionId") or ""
        content = ctx.get("interactionContent") or ""
        existing = ctx.get("existingMemories") or []
        trace.append({"phase": "resolve", "status": "ok",
                      "message": f"SP-21 启动 interactionId={iid}"})
        if not iid or not content:
            trace.append({"phase": "validate", "status": "failed",
                          "message": "interactionId / interactionContent 缺失"})
            raise ValueError("interactionId / interactionContent 缺失")
        trace.append({"phase": "validate", "status": "ok",
                      "message": f"输入校验通过（纪要 {len(content)} 字，已有记忆 {len(existing)} 条）"})

        # 1) LLM 抽取候选
        user = json.dumps({"interactionId": iid, "interactionContent": content,
                           "existingMemories": [{"memoryId": m.get("memoryId"),
                                                 "content": m.get("content"),
                                                 "category": m.get("category")} for m in existing]},
                          ensure_ascii=False)
        t0 = time.monotonic()
        adapter = llm_mod.create_llm_adapter("memory")
        res = adapter.complete(SYSTEM_PROMPT, user)
        model_call = {"model": res.model_id, "inputTokens": res.input_tokens,
                      "outputTokens": res.output_tokens,
                      "latencyMs": res.latency_ms}
        parsed = _parse_json(res.text) or {}
        candidates = [c for c in parsed.get("candidateMemories") or [] if isinstance(c, dict) and c.get("content")]
        trace.append({"phase": "model", "status": "ok",
                      "message": f"记忆抽取完成（候选 {len(candidates)} 条）"})

        # 2) 确定性比对（DUPLICATE_DETECTION / REINFORCE / SUPERSEDE）
        compared = self._compare(candidates, existing, trace)

        # 3) 规则校验
        rule_violations = self._check_rules(candidates)
        status = "SUCCESS" if not rule_violations else "PARTIAL"
        trace.append({"phase": "compose", "status": "ok" if status == "SUCCESS" else "failed",
                      "message": f"规则校验：违规 {len(rule_violations)} 条（{status}）"})

        result = {
            "schemaVersion": "1.0.0", "skillId": MEMORY_SKILL_ID,
            "interactionId": iid, "status": status,
            "candidateMemories": candidates,
            "memoryUpdates": compared["updates"],
            "memorySupersessions": compared["supersessions"],
            "ruleViolations": rule_violations,
        }
        return {"skillId": MEMORY_SKILL_ID, "result": result}, model_call

    def _compare(self, candidates: list[dict], existing: list[dict],
                 trace: list[dict]) -> dict:
        updates, supersessions = [], []
        # 候选间重复去重（DUPLICATE_DETECTION）
        dedup: list[dict] = []
        for c in candidates:
            if any(_similarity(c.get("content", ""), d.get("content", "")) > 0.85
                   for d in dedup):
                continue
            dedup.append(c)
        candidates[:] = dedup

        for c in candidates:
            ctext = c.get("content", "")
            best, best_sim = None, 0.0
            for m in existing:
                sim = _similarity(ctext, m.get("content", ""))
                if sim > best_sim:
                    best, best_sim = m, sim
            if best is not None and best_sim >= SIM_THRESHOLD:
                negated = any(marker in ctext for marker in NEGATION_MARKERS)
                if negated:
                    supersessions.append({
                        "memoryId": best.get("memoryId", ""),
                        "supersededBy": c.get("memoryId", ""),
                        "reason": f"新记忆否定/取代旧记忆（相似度 {best_sim:.2f}，含否定语义）",
                    })
                    trace.append({"phase": "evidence", "status": "ok",
                                  "message": f"SUPERSEDE: {best.get('memoryId')} ← {c.get('memoryId')}"})
                else:
                    delta = round(min(0.1, 1.0 - float(c.get("confidence", 0.8))), 2)
                    updates.append({
                        "memoryId": best.get("memoryId", ""),
                        "action": "REINFORCE",
                        "confidenceDelta": delta,
                        "reason": f"新交互强化既有记忆（相似度 {best_sim:.2f}）",
                    })
                    trace.append({"phase": "evidence", "status": "ok",
                                  "message": f"REINFORCE: {best.get('memoryId')} confidence+{delta}"})
        return {"updates": updates, "supersessions": supersessions}

    def _check_rules(self, candidates: list[dict]) -> list[dict]:
        violations = []
        for c in candidates:
            conf = c.get("confidence")
            try:
                conf_f = float(conf)
            except (TypeError, ValueError):
                conf_f = 0.0
            if not (0.0 <= conf_f <= 1.0):
                violations.append({"ruleId": "CONFIDENCE_CALIBRATION",
                                   "severity": "BLOCKING",
                                   "message": f"置信度越界（{c.get('memoryId')}）：{conf}"})
            else:
                c["confidence"] = round(conf_f, 2)
            if c.get("suggestedDecayRule") not in DECAY_RULES:
                violations.append({"ruleId": "DECAY_RULE_APPLICATION",
                                   "severity": "BLOCKING",
                                   "message": f"衰减规则非法（{c.get('memoryId')}）：{c.get('suggestedDecayRule')}"})
        # DUPLICATE_DETECTION：候选间重复（两两相似度 > 0.85）
        for i in range(len(candidates)):
            for j in range(i + 1, len(candidates)):
                a, b = candidates[i], candidates[j]
                if _similarity(a.get("content", ""), b.get("content", "")) > 0.85:
                    violations.append({"ruleId": "DUPLICATE_DETECTION",
                                       "severity": "BLOCKING",
                                       "message": f"候选重复：{a.get('memoryId')} ≈ {b.get('memoryId')}"})
        return violations


def _parse_json(text: str) -> dict | None:
    m = re.search(r"\{[\s\S]*\}", text or "")
    candidate = m.group(0) if m else (text or "").strip()
    try:
        obj = json.loads(candidate)
        return obj if isinstance(obj, dict) else None
    except (json.JSONDecodeError, ValueError):
        return None
