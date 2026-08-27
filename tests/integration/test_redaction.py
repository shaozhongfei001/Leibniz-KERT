"""M2.9 脱敏出站点集成测试：API 响应脱敏与 LLM 提示词脱敏。"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from dkws.api.server import create_app
from dkws.application.skills import SkillExecutionService, _is_external_adapter
from dkws.infrastructure.adapters import llm as llm_mod
from dkws.infrastructure.classification import Classification
from dkws.infrastructure.observability import get_metrics_registry
from dkws.infrastructure.runtime_config import (
    RedactionConfig,
    RuntimeConfig,
    load_runtime_config,
)

MOBILE = "13812348000"
ID_CARD = "110101199001011234"
CREDIT_CODE = "91310000MA1K35Q12X"
SKILL_ID = "skill-customer-outreach-script"


@pytest.fixture(autouse=True)
def _clean_registry():
    """清理进程级指标注册表，避免跨用例污染。"""
    get_metrics_registry().reset()
    yield
    get_metrics_registry().reset()


def _client(ws, cfg: RuntimeConfig | None = None) -> TestClient:
    """构造 TestClient。"""
    return TestClient(create_app(ws, runtime_config=cfg or RuntimeConfig()),
                      raise_server_exceptions=False)


# ---------------------------------------------------------------- 配置

class TestRedactionConfig:
    """脱敏配置解析。"""

    def test_response_redaction_disabled_by_default(self):
        """响应脱敏默认关闭——既有响应契约与测试依赖原文。"""
        assert load_runtime_config(env={}).redaction.response_enabled is False

    def test_llm_redaction_enabled_by_default(self):
        """LLM 出站脱敏默认开启——客户数据进外部模型属重大合规风险。"""
        assert load_runtime_config(env={}).redaction.llm_enabled is True

    def test_log_redaction_enabled_by_default(self):
        """日志脱敏默认开启。"""
        assert load_runtime_config(env={}).redaction.log_enabled is True

    def test_env_overrides(self):
        """环境变量可覆盖各开关。"""
        cfg = load_runtime_config(env={
            "DKWS_REDACT_RESPONSE": "true",
            "DKWS_REDACT_THRESHOLD": "CONFIDENTIAL",
            "DKWS_REDACT_RESPONSE_TEXT": "true",
            "DKWS_LLM_REDACTION": "false",
        }).redaction
        assert cfg.response_enabled is True
        assert cfg.response_threshold == "CONFIDENTIAL"
        assert cfg.response_mask_text is True
        assert cfg.llm_enabled is False

    def test_threshold_parsed_to_classification(self):
        """阈值字符串可解析为分类等级。"""
        cfg = load_runtime_config(env={"DKWS_REDACT_THRESHOLD": "CONFIDENTIAL"})
        assert Classification.parse(cfg.redaction.response_threshold) == \
            Classification.CONFIDENTIAL


# ---------------------------------------------------------------- 响应脱敏

class TestResponseRedaction:
    """API 响应脱敏中间件。"""

    def test_disabled_by_default_preserves_response(self, ws):
        """默认关闭时响应原样返回（不破坏既有契约）。"""
        resp = _client(ws).get("/v1/health")
        assert resp.status_code == 200
        assert "data" in resp.json()

    def test_enabled_middleware_keeps_envelope(self, ws):
        """启用后信封结构不变。"""
        cfg = RuntimeConfig(redaction=RedactionConfig(response_enabled=True))
        payload = _client(ws, cfg).get("/v1/health").json()
        assert {"request_id", "status", "data", "errors", "meta"} <= set(payload)

    def test_non_json_response_passes_through(self, ws):
        """非 JSON 响应原样透传（Prometheus 文本不应被 JSON 处理）。"""
        cfg = RuntimeConfig(redaction=RedactionConfig(response_enabled=True))
        resp = _client(ws, cfg).get("/metrics")
        assert resp.status_code == 200
        assert "text/plain" in resp.headers["content-type"]
        assert "dkws_" in resp.text

    def test_livez_still_works_with_redaction(self, ws):
        """探针在脱敏启用下仍正常。"""
        cfg = RuntimeConfig(redaction=RedactionConfig(response_enabled=True))
        assert _client(ws, cfg).get("/livez").json()["status"] == "alive"

    def test_content_length_updated(self, ws):
        """脱敏后 content-length 被正确更新，避免响应截断。"""
        cfg = RuntimeConfig(redaction=RedactionConfig(response_enabled=True))
        resp = _client(ws, cfg).get("/v1/health")
        declared = int(resp.headers["content-length"])
        assert declared == len(resp.content)

    def test_error_response_still_json(self, ws):
        """4xx 错误响应仍为合法 JSON。"""
        cfg = RuntimeConfig(redaction=RedactionConfig(response_enabled=True))
        resp = _client(ws, cfg).get("/v1/evidence/NOT-EXIST")
        assert resp.status_code >= 400
        assert json.loads(resp.content)

    def test_annotation_absent_when_nothing_masked(self, ws):
        """无字段被掩码时不附加脱敏说明，避免噪声。"""
        cfg = RuntimeConfig(redaction=RedactionConfig(response_enabled=True,
                                                     annotate=True))
        meta = _client(ws, cfg).get("/v1/health").json().get("meta") or {}
        assert "redaction" not in meta


# ---------------------------------------------------------------- LLM 出站脱敏

class TestLlmEgressRedaction:
    """LLM 提示词出站脱敏（独立评审 L659）。"""

    def test_deterministic_adapter_is_not_external(self):
        """本地确定性适配器不出网，不应触发脱敏（否则降低结果质量）。"""
        adapter = llm_mod.create_llm_adapter("outreach")
        assert _is_external_adapter(adapter) is False

    def test_openai_adapter_is_external(self):
        """OpenAI 兼容适配器出网，需脱敏。"""
        adapter = llm_mod.OpenAiCompatibleLlmAdapter("https://x", "k", "m")
        assert _is_external_adapter(adapter) is True

    def test_redaction_enabled_by_default(self, ws):
        """服务默认启用 LLM 出站脱敏。"""
        svc = SkillExecutionService(ws)
        assert svc._llm_redaction_enabled is True

    def test_redaction_can_be_disabled_explicitly(self, ws):
        """可显式关闭（用于内网自建模型场景）。"""
        assert SkillExecutionService(ws, llm_redaction=False)._llm_redaction_enabled \
            is False

    @pytest.mark.parametrize("raw", ["0", "false", "no", "off", "FALSE"])
    def test_env_can_disable(self, ws, monkeypatch, raw):
        """环境变量可关闭。"""
        monkeypatch.setenv("DKWS_LLM_REDACTION", raw)
        assert SkillExecutionService(ws)._llm_redaction_enabled is False

    def test_env_unknown_value_keeps_enabled(self, ws, monkeypatch):
        """未识别值按安全默认保持开启。"""
        monkeypatch.setenv("DKWS_LLM_REDACTION", "maybe")
        assert SkillExecutionService(ws)._llm_redaction_enabled is True

    def test_external_adapter_prompt_is_redacted(self, ws, monkeypatch):
        """外部适配器收到的提示词已脱敏，且 trace 留痕。"""
        captured: dict[str, str] = {}

        class _Recorder:
            """捕获出站提示词的假适配器。"""

            def complete(self, system: str, user: str):
                """记录并返回固定结果。"""
                captured["system"] = system
                captured["user"] = user
                return llm_mod.LlmResult(text="{}", model_id="fake",
                                         input_tokens=1, output_tokens=1,
                                         latency_ms=1)

        recorder = _Recorder()
        monkeypatch.setattr(llm_mod, "create_llm_adapter", lambda kind: recorder)
        monkeypatch.setattr("dkws.application.skills._is_external_adapter",
                            lambda adapter: True)

        svc = SkillExecutionService(ws)
        trace: list[dict] = []
        svc._call_model("outreach", f"系统提示 身份证 {ID_CARD}",
                        f"用户内容 手机 {MOBILE}", trace)

        assert ID_CARD not in captured["system"]
        assert MOBILE not in captured["user"]
        assert any(t.get("phase") == "llm_redaction" for t in trace)

    def test_internal_adapter_prompt_not_redacted(self, ws, monkeypatch):
        """本地适配器收到原文（不出网，脱敏无必要且有害）。"""
        captured: dict[str, str] = {}

        class _Recorder:
            """捕获出站提示词的假适配器。"""

            def complete(self, system: str, user: str):
                """记录并返回固定结果。"""
                captured["user"] = user
                return llm_mod.LlmResult(text="{}", model_id="fake",
                                         input_tokens=1, output_tokens=1,
                                         latency_ms=1)

        monkeypatch.setattr(llm_mod, "create_llm_adapter", lambda kind: _Recorder())
        monkeypatch.setattr("dkws.application.skills._is_external_adapter",
                            lambda adapter: False)

        svc = SkillExecutionService(ws)
        svc._call_model("outreach", "系统", f"手机 {MOBILE}", [])
        assert MOBILE in captured["user"]

    def test_no_trace_entry_when_nothing_sensitive(self, ws, monkeypatch):
        """无敏感内容时不产生脱敏 trace，避免噪声。"""
        class _Recorder:
            """假适配器。"""

            def complete(self, system: str, user: str):
                """返回固定结果。"""
                return llm_mod.LlmResult(text="{}", model_id="fake",
                                         input_tokens=1, output_tokens=1,
                                         latency_ms=1)

        monkeypatch.setattr(llm_mod, "create_llm_adapter", lambda kind: _Recorder())
        monkeypatch.setattr("dkws.application.skills._is_external_adapter",
                            lambda adapter: True)
        trace: list[dict] = []
        SkillExecutionService(ws)._call_model("outreach", "系统", "无敏感内容", trace)
        assert not any(t.get("phase") == "llm_redaction" for t in trace)

    def test_redaction_disabled_sends_original(self, ws, monkeypatch):
        """关闭脱敏后原文出站（配置生效验证）。"""
        captured: dict[str, str] = {}

        class _Recorder:
            """假适配器。"""

            def complete(self, system: str, user: str):
                """记录出站内容。"""
                captured["user"] = user
                return llm_mod.LlmResult(text="{}", model_id="fake",
                                         input_tokens=1, output_tokens=1,
                                         latency_ms=1)

        monkeypatch.setattr(llm_mod, "create_llm_adapter", lambda kind: _Recorder())
        monkeypatch.setattr("dkws.application.skills._is_external_adapter",
                            lambda adapter: True)
        svc = SkillExecutionService(ws, llm_redaction=False)
        svc._call_model("outreach", "系统", f"手机 {MOBILE}", [])
        assert MOBILE in captured["user"]


# ---------------------------------------------------------------- 既有行为不破坏

class TestBackwardCompatibility:
    """确认 M2.9 未破坏既有契约。"""

    def test_skill_execution_result_keeps_plaintext(self, ws):
        """Skill 执行结果保持原文（脱敏只作用于出站通道，不改内部产物）。"""
        svc = SkillExecutionService(ws)
        result = svc.execute(SKILL_ID, "REQ-M29-1", {"customerId": "CUST-CORP-0001"})
        assert result.status == "ok"

    def test_app_wires_redaction_config(self, ws):
        """create_app 正确装配脱敏配置到 Service。"""
        cfg = RuntimeConfig(redaction=RedactionConfig(llm_enabled=False))
        app = create_app(ws, runtime_config=cfg)
        assert app.state.skill_service._llm_redaction_enabled is False

    def test_health_endpoint_unaffected(self, ws):
        """健康检查不受影响。"""
        assert _client(ws).get("/v1/health").json()["data"]["status"] in ("OK",
                                                                        "DEGRADED")
