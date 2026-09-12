"""可插拔 LLM 适配器（规格 §6.3：适配器必须接口隔离、可替换；§1.6：无外部模型时确定性适配器端到端）。

- OpenAiCompatibleLlmAdapter：DeepSeek/OpenAI 兼容 `/chat/completions`（env: KERT_LLM_BASE_URL / KERT_LLM_API_KEY / KERT_LLM_MODEL）；
- DeterministicLlmAdapter：未配置模型时的确定性样例适配器（输出满足 skill JSON schema，标注 deterministic_fallback）；
- 凭据仅来自环境变量，不落盘、不打印。
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.request
from dataclasses import dataclass
from abc import ABC, abstractmethod

from ...domain.errors import UsageError

_log = logging.getLogger(__name__)


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
            _log.debug("确定性适配器：提取客户标识失败，使用默认值", exc_info=True)
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
                _log.debug("确定性适配器：解析 memory 输入失败，使用默认值", exc_info=True)
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
            return self._sample_proposal(customer, user)
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

    # ---------------- proposal 章节兜底（按章分化 + 引用真实上下文） ----------------

    # 每章的叙述焦点：(小节标题, 取用的 chapterContext 字段)
    _PROPOSAL_CHAPTER_FOCUS: dict[str, tuple[str, tuple[str, ...]]] = {
        "CH01": ("企业基本面", ("basicInfo", "transactionSummary")),
        "CH02": ("行业与竞争格局", ("industryFramework", "industryReports")),
        "CH03": ("财务与经营能力", ("financialFramework", "financialSummary")),
        "CH04": ("风险与预警", ("creditFacility", "regulatoryChanges")),
        "CH05": ("金融需求识别", ("interactionMemory", "interactionHistory")),
        "CH06": ("产品与方案设计", ("creditFacility", "transactionSummary")),
        "CH07": ("定价与收益测算", ("financialSummary", "creditFacility")),
        "CH08": ("实施路径与里程碑", ("interactionHistory", "previousVersion")),
        "CH09": ("合规与监管要求", ("regulatoryChanges", "newsEvents")),
        "CH10": ("后续跟进与复盘", ("interactionMemory", "previousVersion")),
    }

    @staticmethod
    def _brief(value: object, limit: int = 160) -> str:
        """把 chapterContext 字段压成一行可读摘要，避免正文塞入原始 JSON。"""
        if value in (None, "", [], {}):
            return ""
        if isinstance(value, str):
            return value.strip()[:limit]
        if isinstance(value, dict):
            parts = [f"{k}={v}" for k, v in list(value.items())[:6] if v not in (None, "", [], {})]
            return "；".join(parts)[:limit]
        if isinstance(value, list):
            heads: list[str] = []
            for item in value[:3]:
                if isinstance(item, dict):
                    label = item.get("title") or item.get("name") or item.get("content") or item.get("summary")
                    heads.append(str(label)[:60] if label else str(item)[:60])
                else:
                    heads.append(str(item)[:60])
            return "；".join(h for h in heads if h)[:limit]
        return str(value)[:limit]

    def _sample_proposal(self, customer: str, user: str) -> dict:
        """离线兜底：按 chapterId 分化叙述，并引用 chapterContext 真实字段。

        修复 FAIL-2026-09-08-02：原实现对 CH01~CH10 使用同一段模板，
        导致草稿各章正文逐字相同且丢弃全部企业数据。
        """
        try:
            payload = json.loads(user)
        except Exception:
            _log.debug("确定性适配器：解析 proposal 输入失败，使用默认值", exc_info=True)
            payload = {}

        cid = payload.get("chapterId") or "CH01"
        cname = payload.get("chapterName") or cid
        industry = payload.get("industry") or "制造业"
        ctx = payload.get("chapterContext") or {}
        focus, fields = self._PROPOSAL_CHAPTER_FOCUS.get(cid, ("综合分析", ("basicInfo",)))

        # 逐字段落地真实上下文，缺失字段进入 unknowns 而非编造
        evidence: list[str] = []
        missing: list[str] = []
        for field in fields:
            brief = self._brief(ctx.get(field))
            if brief:
                evidence.append(f"- **{field}**：{brief}")
            else:
                missing.append(field)

        lines = [
            f"## {cid} {cname}",
            "",
            f"本章聚焦 **{focus}**（客户：{customer}｜行业：{industry}）。",
            "",
        ]
        if evidence:
            lines += ["依据以下已装配事实：", "", *evidence, ""]
        else:
            lines += [
                f"当前上下文未提供 {focus} 所需字段，本章不作实质判断（离线兜底模式，不编造事实）。",
                "",
            ]
        lines.append(
            f"> 生成模式：确定性兜底（未配置 KERT_LLM_*，未调用大模型）。"
            f"正式草稿请配置 KERT_LLM_BASE_URL / KERT_LLM_API_KEY / KERT_LLM_MODEL。"
        )

        claims = [
            {"claim": f"{customer}{focus}相关事实已装配（{cid}）", "factLabel": "F",
             "source": f"ContextPackage.{fields[0]}", "date": "2026-09-08"},
        ]
        unknowns = [
            {"description": f"{cid} 缺少 {f} 字段，无法完成{focus}判断", "suggestedAction": f"补齐 {f} 后重新生成"}
            for f in missing
        ] or [{"description": f"{cid} 由兜底适配器生成，未经大模型推理",
               "suggestedAction": "配置 KERT_LLM_* 后重新生成"}]

        return {"chapterId": cid, "content": "\n".join(lines), "claims": claims, "unknowns": unknowns}


def create_llm_adapter(kind: str) -> LlmAdapter:
    """按环境配置选择适配器；未配置外部模型时返回确定性适配器（§1.6）。"""
    base = os.environ.get("KERT_LLM_BASE_URL")
    key = os.environ.get("KERT_LLM_API_KEY")
    model = os.environ.get("KERT_LLM_MODEL")
    if base and key and model:
        # 逐章生成时单次调用可能较慢，允许用 KERT_LLM_TIMEOUT 放宽（默认 60s）
        try:
            timeout = int(os.environ.get("KERT_LLM_TIMEOUT", "60"))
        except ValueError:
            _log.warning("KERT_LLM_TIMEOUT 非法，回退 60s")
            timeout = 60
        return OpenAiCompatibleLlmAdapter(base, key, model, timeout=timeout)
    return DeterministicLlmAdapter(kind)
