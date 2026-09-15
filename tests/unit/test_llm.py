"""LLM 适配器单元测试：确定性适配器、create_llm_adapter 工厂。"""

from __future__ import annotations

import json

import pytest

from kert.domain.errors import UsageError
from kert.infrastructure.adapters.llm import (
    DeterministicLlmAdapter,
    LlmResult,
    OpenAiCompatibleLlmAdapter,
    create_llm_adapter,
)


# ---------- LlmResult ----------

class TestLlmResult:
    def test_fields(self):
        r = LlmResult(text="hi", input_tokens=1, output_tokens=2,
                       latency_ms=10.0, model_id="test")
        assert r.text == "hi"
        assert r.input_tokens == 1


# ---------- DeterministicLlmAdapter ----------

class TestDeterministicLlmAdapter:
    def test_memory_kind(self):
        a = DeterministicLlmAdapter("memory")
        r = a.complete("sys", json.dumps({"structuredFacts": {"profile": {"name": "张三"}}}))
        data = json.loads(r.text)
        assert "candidateMemories" in data
        assert r.model_id == "deterministic_fallback"

    def test_memory_with_existing(self):
        a = DeterministicLlmAdapter("memory")
        user = json.dumps({
            "interactionContent": "客户希望调整合作方式",
            "existingMemories": [{"content": "客户希望调整合作方式", "category": "BUSINESS_SIGNAL"}],
        })
        r = a.complete("sys", user)
        data = json.loads(r.text)
        mem_ids = [m["memoryId"] for m in data["candidateMemories"]]
        assert "MEM-DET-003" in mem_ids

    def test_memory_negation(self):
        a = DeterministicLlmAdapter("memory")
        # 需要交互内容与已有记忆有 ≥10 字公共子串，且含否定关键词
        # "调整合作方式" (6字) 不够 10 字，需要更长的公共子串
        # 让已有记忆和交互内容共享 "调整合作方式以适应新市场" (12字)
        user = json.dumps({
            "interactionContent": "客户取消调整合作方式以适应新市场的计划",
            "existingMemories": [{"content": "客户希望调整合作方式以适应新市场", "category": "BUSINESS_SIGNAL"}],
        })
        r = a.complete("sys", user)
        data = json.loads(r.text)
        m003 = [m for m in data["candidateMemories"] if m["memoryId"] == "MEM-DET-003"]
        assert len(m003) == 1
        assert "取消" in m003[0]["content"] or "不再" in m003[0]["content"]

    def test_memory_invalid_json(self):
        a = DeterministicLlmAdapter("memory")
        r = a.complete("sys", "not json")
        data = json.loads(r.text)
        assert "candidateMemories" in data

    def test_proposal_kind(self):
        a = DeterministicLlmAdapter("proposal")
        r = a.complete("sys", json.dumps({"chapterId": "CH02", "chapterName": "风险", "industry": "金融"}))
        data = json.loads(r.text)
        assert data["chapterId"] == "CH02"
        assert "claims" in data

    def test_proposal_invalid_json(self):
        a = DeterministicLlmAdapter("proposal")
        r = a.complete("sys", "bad json")
        data = json.loads(r.text)
        assert data["chapterId"] == "CH01"

    def test_outreach_kind(self):
        a = DeterministicLlmAdapter("outreach")
        r = a.complete("sys", json.dumps({"customerId": "C001"}))
        data = json.loads(r.text)
        assert "scriptTitle" in data
        assert "sections" in data

    def test_meeting_kind(self):
        a = DeterministicLlmAdapter("meeting")
        r = a.complete("sys", "{}")
        data = json.loads(r.text)
        assert "agenda" in data
        assert "talkingPoints" in data

    def test_default_kind(self):
        a = DeterministicLlmAdapter("previsit")
        r = a.complete("sys", "{}")
        data = json.loads(r.text)
        assert "reportTitle" in data

    def test_latency_positive(self):
        a = DeterministicLlmAdapter("meeting")
        r = a.complete("sys", "{}")
        assert r.latency_ms >= 0


# ---------- OpenAiCompatibleLlmAdapter ----------

class TestOpenAiCompatibleLlmAdapter:
    def test_init(self):
        a = OpenAiCompatibleLlmAdapter("http://api.test.com/", "key123", "gpt-4")
        assert a.base_url == "http://api.test.com"  # trailing slash stripped
        assert a.api_key == "key123"
        assert a.model == "gpt-4"
        assert a.model_id == "gpt-4"

    def test_complete_network_error(self):
        a = OpenAiCompatibleLlmAdapter("http://localhost:1", "key", "m")
        with pytest.raises(UsageError, match="LLM 调用失败"):
            a.complete("sys", "usr")


# ---------- 技能包：再入式取值（下游受控枚举依上游状态映射） ----------

# 适配器按 kind="pkg:<skillId>" 走到 `_sample_package`；
# 它从 system 的【技能标识】取 skillId，从【输出 JSON 结构参考】取顶层键。
_KYC_PKG_SYSTEM = (
    "【技能标识】bank-front-kyc-gap-check\n"
    "【输出 JSON 结构参考】\n"
    '{"customerId": "", "coverageStatus": "", "coverageStatusReason": "", "kycGaps": []}\n'
)


class TestPackageReentrantUpstreamStatus:
    """负例测试：证明「上游状态 → 下游结论」这条通道**真的通**。

    修复前（GK16 T-28）：`_sample_package` 形参里没有 `user`，函数体却引用它
    ⇒ 每次调用抛 `NameError` ⇒ 被 `except Exception` 静默吞掉
    ⇒ `simulate(..., upstream=None)` ⇒ `coverageStatus` **恒取默认值 PARTIAL**
    ⇒ 无论上游是什么状态，下游结论都一样（"字段送达但未被消费"）。

    因此本类中的前两个用例**在修复前必然失败** —— 这正是"注入确实发生"的自证。
    反向由第三个用例保证：上游状态**确实缺失**时，回退默认值是正确行为，
    不得被误判为消费失败。
    """

    def _coverage(self, payload: dict) -> str:
        a = DeterministicLlmAdapter("pkg:bank-front-kyc-gap-check")
        r = a.complete(_KYC_PKG_SYSTEM, json.dumps(payload))
        return json.loads(r.text)["coverageStatus"]

    def test_upstream_status_not_run_is_consumed(self):
        # 上游 NOT_RUN ⇒ 必须映射为 NOT_RUN，而不是落回默认 PARTIAL
        got = self._coverage({"customerId": "SIM-C001", "upstreamStatus": "NOT_RUN"})
        assert got == "NOT_RUN", f"上游状态未被消费（得到 {got!r}）"

    def test_alternate_enum_value_changes_downstream_conclusion(self):
        # **仅"移除字段"不足以证明消费**：当默认值恰与真实值同值时（都是 PARTIAL），
        # 移除与否下游输出都一样。故必须注入**同枚举的他值**。
        assert self._coverage({"customerId": "SIM-C001", "upstreamStatus": "SUCCESS"}) == "SUCCESS"
        assert self._coverage({"customerId": "SIM-C001", "upstreamStatus": "PARTIAL"}) == "PARTIAL"

    def test_missing_upstream_status_falls_back_to_default(self):
        # 上游确实未提供状态时，"未知"按判定表落 PARTIAL —— 这是预期行为
        assert self._coverage({"customerId": "SIM-C001"}) == "PARTIAL"


# ---------- create_llm_adapter ----------

class TestCreateLlmAdapter:
    def test_no_env_returns_deterministic(self, monkeypatch):
        monkeypatch.delenv("KERT_LLM_BASE_URL", raising=False)
        monkeypatch.delenv("KERT_LLM_API_KEY", raising=False)
        monkeypatch.delenv("KERT_LLM_MODEL", raising=False)
        a = create_llm_adapter("memory")
        assert isinstance(a, DeterministicLlmAdapter)

    def test_with_env_returns_openai(self, monkeypatch):
        monkeypatch.setenv("KERT_LLM_BASE_URL", "http://api.test.com")
        monkeypatch.setenv("KERT_LLM_API_KEY", "key123")
        monkeypatch.setenv("KERT_LLM_MODEL", "gpt-4")
        a = create_llm_adapter("memory")
        assert isinstance(a, OpenAiCompatibleLlmAdapter)

    def test_partial_env_returns_deterministic(self, monkeypatch):
        monkeypatch.setenv("KERT_LLM_BASE_URL", "http://api.test.com")
        monkeypatch.delenv("KERT_LLM_API_KEY", raising=False)
        monkeypatch.delenv("KERT_LLM_MODEL", raising=False)
        a = create_llm_adapter("memory")
        assert isinstance(a, DeterministicLlmAdapter)
