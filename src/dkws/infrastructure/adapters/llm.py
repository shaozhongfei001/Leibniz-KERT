"""可插拔 LLM 适配器（规格 §6.3：适配器必须接口隔离、可替换；§1.6：无外部模型时确定性适配器端到端）。

- OpenAiCompatibleLlmAdapter：DeepSeek/OpenAI 兼容 `/chat/completions`（env: DKWS_LLM_BASE_URL / DKWS_LLM_API_KEY / DKWS_LLM_MODEL）；
- DeterministicLlmAdapter：未配置模型时的确定性样例适配器（输出满足 skill JSON schema，标注 deterministic_fallback）；
- 凭据仅来自环境变量，不落盘、不打印。
"""

from __future__ import annotations

import json
import os
import time
import urllib.request
from dataclasses import dataclass
from abc import ABC, abstractmethod

from ...domain.errors import UsageError


@dataclass
class LlmResult:
    text: str
    input_tokens: int
    output_tokens: int
    latency_ms: float
    model_id: str


class LlmAdapter(ABC):
    model_id: str = "base"

    @abstractmethod
    def complete(self, system: str, user: str) -> LlmResult:
        """同步单轮补全；失败抛异常（调用方 fail-closed）。"""


class OpenAiCompatibleLlmAdapter(LlmAdapter):
    def __init__(self, base_url: str, api_key: str, model: str, timeout: int = 60):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.model_id = model

    def complete(self, system: str, user: str) -> LlmResult:
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.3,
            "max_tokens": 8192,
        }
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(body).encode("utf-8"),
            headers={"Authorization": f"Bearer {self.api_key}",
                     "Content-Type": "application/json"},
        )
        t0 = time.monotonic()
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            raise UsageError(f"LLM 调用失败: {exc}") from exc
        latency_ms = (time.monotonic() - t0) * 1000
        try:
            text = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise UsageError("LLM 响应结构非法（fail-closed）") from exc
        usage = payload.get("usage") or {}
        return LlmResult(
            text=text,
            input_tokens=int(usage.get("prompt_tokens", 0) or 0),
            output_tokens=int(usage.get("completion_tokens", 0) or 0),
            latency_ms=round(latency_ms, 1),
            model_id=self.model,
        )


class DeterministicLlmAdapter(LlmAdapter):
    """无外部模型时的确定性样例适配器：按 skill 类型返回满足 JSON schema 的结构化输出。"""

    model_id = "deterministic_fallback"

    def __init__(self, kind: str):
        self.kind = kind

    def complete(self, system: str, user: str) -> LlmResult:
        # 回显请求中客户标识，使输出可溯源（机器事实优先）
        customer = "示例客户"
        try:
            payload = json.loads(user)
            profile = (payload.get("structuredFacts") or {}).get("profile") or {}
            customer = profile.get("name") or payload.get("customerId") or customer
        except Exception:
            pass
        t0 = time.monotonic()
        data = self._sample(customer, user)
        return LlmResult(
            text=json.dumps(data, ensure_ascii=False),
            input_tokens=0, output_tokens=0,
            latency_ms=round((time.monotonic() - t0) * 1000, 1),
            model_id=self.model_id,
        )

    def _sample(self, customer: str, user: str = "") -> dict:
        if self.kind == "memory":
            try:
                payload = json.loads(user)
                content = payload.get("interactionContent") or ""
                existing = payload.get("existingMemories") or []
            except Exception:
                content, existing = "", []
            # 取纪要前 40 字作为候选内容，便于与 existingMemories 相似度比对
            snippet = (content or "客户希望调整合作方式")[:40]
            memories = [
                {"memoryId": "MEM-DET-001", "category": "BUSINESS_SIGNAL",
                 "content": f"{snippet}（确定性样例）", "confidence": 0.8,
                 "suggestedDecayRule": "LINEAR", "evidenceQuote": snippet},
                {"memoryId": "MEM-DET-002", "category": "PREFERENCE",
                 "content": "客户偏好面对面沟通", "confidence": 0.7,
                 "suggestedDecayRule": "NONE", "evidenceQuote": snippet},
            ]
            # 与既有记忆比对（去空格后 10 字公共片段）→ 匹配则生成同内容候选：
            # 纪要含否定语义 → 候选带否定后缀（触发 SUPERSEDE）；否则原样（触发 REINFORCE）
            plain = (content or "").replace(" ", "")
            negated = any(mk in plain for mk in ("取消", "不再", "终止", "撤回", "拒绝"))
            for m in existing:
                mc = (m.get("content") or "").replace(" ", "")
                if mc and any(mc[i:i + 10] in plain for i in range(max(1, len(mc) - 9))):
                    candidate_content = (m.get("content") or "") if not negated else \
                        f"{m.get('content')}（客户已取消/不再坚持该事项）"
                    memories.append({"memoryId": "MEM-DET-003", "category": m.get("category") or "BUSINESS_SIGNAL",
                                     "content": candidate_content, "confidence": 0.9,
                                     "suggestedDecayRule": "LINEAR", "evidenceQuote": snippet})
            return {"candidateMemories": memories}
        if self.kind == "proposal":
            try:
                payload = json.loads(user)
                cid = payload.get("chapterId") or "CH01"
                cname = payload.get("chapterName") or cid
                industry = payload.get("industry") or "制造业"
            except Exception:
                cid, cname, industry = "CH01", "企业概况", "制造业"
            return {
                "chapterId": cid,
                "content": f"## {cid} {cname}\n\n{customer}为{industry}客户，经营基本正常，存在金融需求"
                           f"（确定性样例，供离线端到端）。\n\n{customer}为制造业客户，主营稳定。\n\n"
                           f"{customer}存在综合金融服务需求。",
                "claims": [
                    {"claim": f"{customer}为制造业客户，主营稳定", "factLabel": "F",
                     "source": "ContextPackage.enterpriseData.basicInfo", "date": "2026-08-23"},
                    {"claim": f"{customer}存在综合金融服务需求", "factLabel": "C",
                     "source": "ContextPackage.interactionMemory", "date": "2026-08-23"},
                ],
                "unknowns": [{"description": "最新财务数据待核实", "suggestedAction": "索取最近一期报表"}],
            }
        if self.kind == "outreach":
            return {
                "scriptTitle": f"{customer}外联脚本",
                "sections": [{"heading": "开场", "content": f"您好，我是客户经理，希望与{customer}建立联系。"},
                             {"heading": "价值主张", "content": "介绍本行综合金融服务方案。"}],
                "callObjectives": ["建立联系", "约定后续会面"],
                "keyMessages": ["综合金融服务", "定制化方案"],
            }
        if self.kind == "meeting":
            return {
                "agenda": [{"time": "10:00", "topic": "开场与背景"}, {"time": "10:20", "topic": "产品方案"}],
                "talkingPoints": [{"title": "服务介绍", "detail": f"面向{customer}的综合服务方案。"}],
                "sensitivePoints": ["担保额度接近上限"],
                "actionItems": ["提供产品资料", "约定下次会面"],
            }
        return {
            "reportTitle": f"{customer}R1 拜访报告",
            "executiveSummary": f"{customer}为本地重点客户，本次拜访旨在了解经营与金融需求。",
            "sections": [{"heading": "客户概况", "content": "基于输入的结构化事实。"},
                         {"heading": "供应链", "content": "基于输入供应链图谱。"}],
            "evidenceRefs": [{"id": "SEG-INPUT-001", "summary": "输入知识上下文片段"}],
        }


def create_llm_adapter(kind: str) -> LlmAdapter:
    """按环境配置选择适配器；未配置外部模型时返回确定性适配器（§1.6）。"""
    base = os.environ.get("DKWS_LLM_BASE_URL")
    key = os.environ.get("DKWS_LLM_API_KEY")
    model = os.environ.get("DKWS_LLM_MODEL")
    if base and key and model:
        return OpenAiCompatibleLlmAdapter(base, key, model)
    return DeterministicLlmAdapter(kind)
