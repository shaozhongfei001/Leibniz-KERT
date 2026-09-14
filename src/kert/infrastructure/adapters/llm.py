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
    # **实际生效**的采样参数（非请求值）。供调用方与审计**回读**——
    # 判定"输出是否可复现"必须以生效值为准，不能以请求值为准
    # （请求 0 而实际 0.3 的情况下，可复现性结论会完全错误）。
    temperature: float | None = None
    seed: int | None = None


class LlmAdapter(ABC):
    model_id: str = "base"

    @abstractmethod
    def complete(self, system: str, user: str, *,
                 temperature: float | None = None,
                 seed: int | None = None) -> LlmResult:
        """同步单轮补全；失败抛异常（调用方 fail-closed）。

        ``temperature`` / ``seed`` 为**请求级采样参数**（可选）。
        传入时覆盖适配器默认值；返回的 ``LlmResult`` 携带**实际生效值**。
        """


class OpenAiCompatibleLlmAdapter(LlmAdapter):
    def __init__(self, base_url: str, api_key: str, model: str, timeout: int = 60,
                 default_temperature: float = 0.3):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.model_id = model
        # 默认值不再写死在请求体里：可由构造参数或环境变量给定，
        # 并**可被请求级的 temperature 覆盖**。
        self.default_temperature = default_temperature

    def complete(self, system: str, user: str, *,
                 temperature: float | None = None,
                 seed: int | None = None) -> LlmResult:
        eff_temperature = (self.default_temperature
                           if temperature is None else temperature)
        effective_seed = seed
        body: dict = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": eff_temperature,
            "max_tokens": 8192,
        }
        # ``seed`` 仅在显式给出时下发：多数 OpenAI 兼容端点不接受该字段，
        # 无条件下发会使其拒绝请求。
        if effective_seed is not None:
            body["seed"] = int(effective_seed)
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
            temperature=eff_temperature,
            seed=effective_seed,
        )


class DeterministicLlmAdapter(LlmAdapter):
    """无外部模型时的确定性样例适配器：按 skill 类型返回满足 JSON schema 的结构化输出。"""

    model_id = "deterministic_fallback"

    def __init__(self, kind: str):
        self.kind = kind

    def complete(self, system: str, user: str, *,
                 temperature: float | None = None,
                 seed: int | None = None) -> LlmResult:
        # 回显请求中客户标识，使输出可溯源（机器事实优先）
        customer = "示例客户"
        try:
            payload = json.loads(user)
            profile = (payload.get("structuredFacts") or {}).get("profile") or {}
            customer = profile.get("name") or payload.get("customerId") or customer
        except Exception:
            _log.debug("确定性适配器：提取客户标识失败，使用默认值", exc_info=True)
        t0 = time.monotonic()
        # system 一并传入：外部技能包需要从中读取该技能的 output-schema 以生成符合结构
        data = self._sample(customer, user, system)
        return LlmResult(
            text=json.dumps(data, ensure_ascii=False),
            input_tokens=0, output_tokens=0,
            latency_ms=round((time.monotonic() - t0) * 1000, 1),
            model_id=self.model_id,
            temperature=temperature, seed=seed,
        )

    @staticmethod
    def _schema_keys_from_system(system: str) -> list[str]:
        """从 system 提示的【输出 JSON 结构参考】中解析顶层键。

        技能包的 output-schema.md 已由 _load_packages 抽取为 JSON 片段注入 system。
        本方法将其解析为顶层键列表，供确定性适配器生成**符合该技能结构**的输出。
        """
        import re as _re
        m = _re.search(r"【输出 JSON 结构参考】\n([\s\S]*?)(?:\n【|\Z)", system or "")
        if not m:
            return []
        snippet = m.group(1).strip()
        # 优先整体解析
        try:
            obj = json.loads(snippet)
            if isinstance(obj, dict):
                return list(obj.keys())
        except Exception:
            _log.debug("确定性适配器：schema 片段非完整 JSON，改用键名抽取", exc_info=True)
        # 退路：抽取形如 "key": 的顶层键
        keys = _re.findall(r'^\s{0,4}"([A-Za-z_][\w]*)"\s*:', snippet, _re.M)
        out: list[str] = []
        for k in keys:
            if k not in out:
                out.append(k)
        return out

    def _sample_package(self, customer: str, system: str, user: str = "") -> dict:
        """技能包确定性输出：结构取自该技能自身 output-schema 的顶层键。

        诚实性约束：本输出为**确定性占位**，无分析依据。
        故在 warnings 中显式声明，避免被误读为真实分析结论。
        """
        keys = self._schema_keys_from_system(system)
        if not keys:
            # 无 schema 可用时不得臆造结构
            return {
                "schemaVersion": "deterministic/1.0",
                "status": "SCHEMA_UNAVAILABLE",
                "warnings": [
                    "该技能包未提供可解析的 output-schema，确定性适配器不臆造输出结构。"
                ],
            }

        # 该技能自身的 skillId：由调用方在【技能标识】中显式给出。
        # 不从指令正文猜测 —— 正文未必含技能名，猜测会得到 "unknown"。
        import re as _re2
        skill_id = ""
        _m = _re2.search(r"【技能标识】\s*([A-Za-z0-9._-]+)", system or "")
        if _m:
            skill_id = _m.group(1)

        # **仿真内容优先**（2026-09-13 加入）。
        # 原先本函数对**所有技能**一律返回空占位（集合 `[]`、结构 `{}`、
        # 状态 `DETERMINISTIC_PLACEHOLDER`）—— 技能自身的 `output-schema.md`
        # 声明了完整结构与**判定规则**（如 `dataGaps` 非空 ⇒ `PARTIAL`），
        # 但内容为空 ⇒ 下游 §9.3 语义消费检验**无对象可验**。
        # 委托方明确授权构造仿真数据；取值参照银行同业公开的访前准备实践，
        # **不声称与任何特定机构一致**，且每份输出带 `simulationOnly` 声明。
        try:
            from kert.infrastructure.adapters.sim_bank_front import simulate
            # **上游状态透传**（再入式取值）：下游能力的受控枚举
            # （如 `coverageStatus`）须依上游 `executionStatus` 的**判定表**映射，
            # 而非随手取。上游状态随 `user` 载荷进入本适配器，
            # 故在此提取并传给仿真器。
            _up = None
            if user:
                try:
                    _p = json.loads(user)
                except Exception as exc:                    # noqa: BLE001
                    # **不得静默降级**（GK16 硬约束 #5）：载荷由 skills.py 以
                    # `json.dumps` 生成，解析失败属**异常**，而非"上游未提供状态"。
                    # 此前这里 `except Exception` + debug 吞掉了 NameError，
                    # 使"上游状态从未送达"长期不可见（见 T-28）。
                    _log.warning("仿真器：载荷非合法 JSON，上游状态按未知处理：%s", exc)
                else:
                    if isinstance(_p, dict):
                        _up = {
                            "executionStatus": _p.get("reconciliationStatus")
                                               or _p.get("upstreamStatus"),
                            "conflicts": _p.get("conflictCases") or _p.get("conflicts"),
                        }
            sim = simulate(skill_id, customer, upstream=_up)
        except Exception:                                   # noqa: BLE001
            # 仿真器缺失属预期的降级路径；但**降级必须可见**，不得只写 debug。
            _log.warning("仿真器不可用，回退确定性占位", exc_info=True)
            sim = None
        if sim is not None:
            return sim

        out: dict = {}
        for k in keys:
            if k == "schemaVersion":
                out[k] = "deterministic/1.0"
            elif k == "skillId":
                out[k] = skill_id or "unknown"
            elif k in ("customerId", "entityId"):
                out[k] = customer if customer != "示例客户" else "SIM-UNKNOWN"
            elif k in ("generatedAt", "asOf"):
                out[k] = time.strftime("%Y-%m-%d", time.gmtime())
            elif k == "status":
                out[k] = "DETERMINISTIC_PLACEHOLDER"
            elif k == "warnings":
                out[k] = [
                    "确定性适配器输出：结构符合本技能 output-schema，"
                    "但内容为占位，**不构成分析结论**，不得据此作业务判断。"
                ]
            elif k.endswith("s") or k.endswith("Refs") or k.endswith("Gaps"):
                out[k] = []          # 集合类：空集合，并在 warnings 中声明
            else:
                out[k] = {}          # 结构化字段：空对象占位
        if "warnings" in out:
            out["warnings"].append(
                "集合字段为空表示『确定性适配器未生成条目』，不代表『无此事项』。"
            )
        return out

    def _sample(self, customer: str, user: str = "", system: str = "") -> dict:
        # 外部技能包：按该技能自身的 output-schema 生成符合结构的确定性输出
        if self.kind.startswith("pkg:"):
            # `user` 必须一并传入：再入式取值（下游受控枚举依上游状态映射）
            # 只能从载荷中取得上游状态。此前此处丢参 ⇒ `_sample_package` 内
            # 引用 `user` 抛 NameError ⇒ 被静默吞掉 ⇒ 上游状态恒为 None
            # ⇒ 下游 `coverageStatus` 恒取默认值。详见 GK16 FAILURES.md T-28。
            return self._sample_package(customer, system, user)
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
            "> 生成模式：确定性兜底（未配置 KERT_LLM_*，未调用大模型）。"
            "正式草稿请配置 KERT_LLM_BASE_URL / KERT_LLM_API_KEY / KERT_LLM_MODEL。"
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
        # 默认采样温度可由环境变量给定；请求级 temperature 仍可覆盖它。
        try:
            default_temp = float(os.environ.get("KERT_LLM_TEMPERATURE", "0.3"))
        except ValueError:
            _log.warning("KERT_LLM_TEMPERATURE 非法，回退 0.3")
            default_temp = 0.3
        return OpenAiCompatibleLlmAdapter(base, key, model, timeout=timeout,
                                          default_temperature=default_temp)
    return DeterministicLlmAdapter(kind)
