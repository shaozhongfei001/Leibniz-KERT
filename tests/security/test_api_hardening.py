"""M2.1/M2.2 中间件安全测试：认证 401/403、限流 429、大小 413、并发 429。"""

from __future__ import annotations

import json
from typing import ClassVar

from fastapi.testclient import TestClient

from dkws.api.server import create_app
from dkws.infrastructure.runtime_config import (
    ApiKeyRecord,
    AuthConfig,
    ConcurrencyConfig,
    RateLimitConfig,
    RuntimeConfig,
    SizeLimitConfig,
    _digest,
)

VALID_KEY = "0123456789abcdef0123"
ADMIN_KEY = "adminadminadminadmin"
WRONG_KEY = "ffffffffffffffffffff"

EXECUTE_PATH = "/api/skill/execute"
GATE_PATH = "/api/skill/gates/audit"
HEALTH_PATH = "/v1/health"


def _auth_config(**overrides) -> AuthConfig:
    """构造启用认证的配置：一个普通密钥 + 一个 admin 密钥。"""
    base = {
        "enabled": True,
        "keys": (
            ApiKeyRecord(key_id="svc", digest=_digest(VALID_KEY),
                         scopes=frozenset({"read", "execute"})),
            ApiKeyRecord(key_id="ops", digest=_digest(ADMIN_KEY),
                         scopes=frozenset({"read", "execute", "admin"})),
        ),
    }
    base.update(overrides)
    return AuthConfig(**base)


def _client(tmp_path, cfg: RuntimeConfig) -> TestClient:
    """用给定运行时配置构造 TestClient。"""
    return TestClient(create_app(tmp_path, runtime_config=cfg), raise_server_exceptions=False)


def _execute_payload() -> dict:
    """最小 Skill 执行请求体。"""
    return {"requestId": "REQ-SEC-1", "skillId": "customer-360-brief",
            "input": {"customerId": "C001"}}


# ---------------------------------------------------------------- M2.1 认证

def test_auth_disabled_allows_anonymous(tmp_path):
    """dev 模式（认证关闭）允许匿名访问。"""
    client = _client(tmp_path, RuntimeConfig())
    assert client.get(HEALTH_PATH).status_code == 200


def test_missing_api_key_returns_401(tmp_path):
    """缺少 API Key 返回 401 且错误码为 UNAUTHENTICATED。"""
    client = _client(tmp_path, RuntimeConfig(auth=_auth_config()))
    resp = client.post(EXECUTE_PATH, json=_execute_payload())
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "UNAUTHENTICATED"


def test_401_includes_www_authenticate(tmp_path):
    """401 响应带 WWW-Authenticate 提示所需请求头。"""
    client = _client(tmp_path, RuntimeConfig(auth=_auth_config()))
    resp = client.post(EXECUTE_PATH, json=_execute_payload())
    assert "X-API-Key" in resp.headers.get("WWW-Authenticate", "")


def test_invalid_api_key_returns_401(tmp_path):
    """无效密钥返回 401。"""
    client = _client(tmp_path, RuntimeConfig(auth=_auth_config()))
    resp = client.post(EXECUTE_PATH, json=_execute_payload(),
                       headers={"X-API-Key": WRONG_KEY})
    assert resp.status_code == 401


def test_valid_api_key_passes_auth(tmp_path):
    """有效密钥通过认证（不再是 401/403）。"""
    client = _client(tmp_path, RuntimeConfig(auth=_auth_config()))
    resp = client.post(EXECUTE_PATH, json=_execute_payload(),
                       headers={"X-API-Key": VALID_KEY})
    assert resp.status_code not in (401, 403)


def test_bearer_token_accepted(tmp_path):
    """支持 Authorization: Bearer <key> 形式。"""
    client = _client(tmp_path, RuntimeConfig(auth=_auth_config()))
    resp = client.get("/v1/knowledge/version",
                      headers={"Authorization": f"Bearer {VALID_KEY}"})
    assert resp.status_code not in (401, 403)


def test_health_is_public_even_with_auth(tmp_path):
    """健康检查为白名单路径，探针无需凭据。"""
    client = _client(tmp_path, RuntimeConfig(auth=_auth_config()))
    assert client.get(HEALTH_PATH).status_code == 200
    assert client.get("/api/skill/health").status_code == 200


def test_admin_endpoint_forbidden_for_non_admin_key(tmp_path):
    """普通密钥访问闸门审计返回 403 FORBIDDEN。"""
    client = _client(tmp_path, RuntimeConfig(auth=_auth_config()))
    resp = client.post(GATE_PATH, json={"customerId": "C1", "gate": "G1",
                                        "decision": "APPROVED", "decidedBy": "u"},
                       headers={"X-API-Key": VALID_KEY})
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "FORBIDDEN"


def test_admin_endpoint_allows_admin_scope(tmp_path):
    """admin 作用域密钥可访问闸门审计。"""
    client = _client(tmp_path, RuntimeConfig(auth=_auth_config()))
    resp = client.post(GATE_PATH, json={"customerId": "C1", "gate": "G1",
                                        "decision": "APPROVED", "decidedBy": "u"},
                       headers={"X-API-Key": ADMIN_KEY})
    assert resp.status_code not in (401, 403)


def test_custom_header_name_respected(tmp_path):
    """可自定义认证请求头名称。"""
    cfg = RuntimeConfig(auth=_auth_config(header_name="X-DKWS-Token"))
    client = _client(tmp_path, cfg)
    assert client.get("/v1/knowledge/version",
                      headers={"X-API-Key": VALID_KEY}).status_code == 401
    assert client.get("/v1/knowledge/version",
                      headers={"X-DKWS-Token": VALID_KEY}).status_code != 401


def test_error_body_does_not_leak_key(tmp_path):
    """错误响应不回显密钥内容。"""
    client = _client(tmp_path, RuntimeConfig(auth=_auth_config()))
    resp = client.post(EXECUTE_PATH, json=_execute_payload(),
                       headers={"X-API-Key": WRONG_KEY})
    assert WRONG_KEY not in resp.text


def test_inactive_key_rejected(tmp_path):
    """已吊销密钥返回 401。"""
    cfg = RuntimeConfig(auth=AuthConfig(
        enabled=True,
        keys=(ApiKeyRecord(key_id="revoked", digest=_digest(VALID_KEY),
                           scopes=frozenset({"read"}), active=False),)))
    client = _client(tmp_path, cfg)
    assert client.get("/v1/knowledge/version",
                      headers={"X-API-Key": VALID_KEY}).status_code == 401


# ---------------------------------------------------------------- M2.2 限流

def test_rate_limit_returns_429_after_burst(tmp_path):
    """超出突发额度后返回 429 RATE_LIMITED。"""
    cfg = RuntimeConfig(rate_limit=RateLimitConfig(enabled=True,
                                                   requests_per_minute=60, burst=2))
    client = _client(tmp_path, cfg)
    codes = [client.get("/v1/knowledge/version").status_code for _ in range(4)]
    assert codes[0] != 429 and codes[1] != 429
    assert 429 in codes[2:]
    body = client.get("/v1/knowledge/version").json()
    assert body["error"]["code"] == "RATE_LIMITED"
    assert body["error"]["retryable"] is True


def test_rate_limit_sets_retry_after(tmp_path):
    """429 响应带 Retry-After 头。"""
    cfg = RuntimeConfig(rate_limit=RateLimitConfig(enabled=True,
                                                   requests_per_minute=60, burst=1))
    client = _client(tmp_path, cfg)
    client.get("/v1/knowledge/version")
    resp = client.get("/v1/knowledge/version")
    assert resp.status_code == 429
    assert int(resp.headers["Retry-After"]) >= 1


def test_rate_limit_health_exempt(tmp_path):
    """健康检查不计入限流，避免探针被拒。"""
    cfg = RuntimeConfig(rate_limit=RateLimitConfig(enabled=True,
                                                   requests_per_minute=60, burst=1))
    client = _client(tmp_path, cfg)
    for _ in range(5):
        assert client.get(HEALTH_PATH).status_code == 200


def test_rate_limit_disabled_by_default(tmp_path):
    """默认不限流。"""
    client = _client(tmp_path, RuntimeConfig())
    codes = {client.get("/v1/knowledge/version").status_code for _ in range(10)}
    assert 429 not in codes


def test_rate_limit_refills_over_time():
    """令牌随时间补充后恢复放行（直接驱动中间件，注入可控时间源）。"""
    import asyncio

    from dkws.api.middleware import RateLimitMiddleware, error_response

    clock = {"t": 1000.0}
    mw = RateLimitMiddleware(app=None,
                             config=RateLimitConfig(enabled=True, requests_per_minute=60,
                                                    burst=1),
                             time_source=lambda: clock["t"])

    class FakeRequest:
        """最小请求替身（固定来源 IP）。"""

        class _URL:
            path = "/v1/knowledge/version"

        class _Client:
            host = "10.0.0.1"

        url = _URL()
        client = _Client()
        headers: ClassVar[dict[str, str]] = {}

        def __init__(self):
            """初始化空 state。"""
            self.state = type("S", (), {"__dict__": {}})()

    async def call_next(_request):
        """模拟下游成功响应。"""
        return error_response(200, "OK", "done")

    async def scenario() -> list[int]:
        """连续两次请求后推进时钟再请求。"""
        codes = [(await mw.dispatch(FakeRequest(), call_next)).status_code for _ in range(2)]
        clock["t"] += 5.0
        codes.append((await mw.dispatch(FakeRequest(), call_next)).status_code)
        return codes

    codes = asyncio.run(scenario())
    assert codes == [200, 429, 200]


def test_rate_limit_buckets_per_api_key(tmp_path):
    """不同 API Key 各自独立分桶，互不影响。"""
    cfg = RuntimeConfig(auth=_auth_config(),
                        rate_limit=RateLimitConfig(enabled=True,
                                                   requests_per_minute=60, burst=1))
    client = _client(tmp_path, cfg)
    path = "/v1/knowledge/version"
    assert client.get(path, headers={"X-API-Key": VALID_KEY}).status_code != 429
    assert client.get(path, headers={"X-API-Key": VALID_KEY}).status_code == 429
    assert client.get(path, headers={"X-API-Key": ADMIN_KEY}).status_code != 429


# ---------------------------------------------------------------- M2.2 大小限制

def test_request_body_too_large_returns_413(tmp_path):
    """超过请求体上限返回 413 PAYLOAD_TOO_LARGE。"""
    cfg = RuntimeConfig(size_limit=SizeLimitConfig(enabled=True, max_request_bytes=256))
    client = _client(tmp_path, cfg)
    payload = {"requestId": "R", "skillId": "s", "input": {"blob": "x" * 1000}}
    resp = client.post(EXECUTE_PATH, json=payload)
    assert resp.status_code == 413
    assert resp.json()["error"]["code"] == "PAYLOAD_TOO_LARGE"


def test_request_within_limit_passes(tmp_path):
    """未超限的请求正常通过大小检查。"""
    cfg = RuntimeConfig(size_limit=SizeLimitConfig(enabled=True,
                                                   max_request_bytes=64 * 1024))
    client = _client(tmp_path, cfg)
    assert client.post(EXECUTE_PATH, json=_execute_payload()).status_code != 413


def test_chunked_request_without_content_length_limited(tmp_path):
    """无 Content-Length 的分块请求也受限（流式累计校验）。"""
    cfg = RuntimeConfig(size_limit=SizeLimitConfig(enabled=True, max_request_bytes=128))
    client = _client(tmp_path, cfg)

    def chunks():
        """生成分块请求体，触发 chunked 传输。"""
        for _ in range(10):
            yield b"x" * 64

    resp = client.post(EXECUTE_PATH, content=chunks(),
                       headers={"Content-Type": "application/json"})
    assert resp.status_code == 413


def test_response_body_too_large_returns_413(tmp_path):
    """响应体超限返回 413。"""
    cfg = RuntimeConfig(size_limit=SizeLimitConfig(enabled=True, max_request_bytes=1 << 20,
                                                   max_response_bytes=8))
    client = _client(tmp_path, cfg)
    resp = client.get(HEALTH_PATH)
    assert resp.status_code == 413
    assert resp.json()["error"]["code"] == "PAYLOAD_TOO_LARGE"


def test_size_limit_disabled_allows_large_request(tmp_path):
    """关闭大小限制后不再拦截。"""
    cfg = RuntimeConfig(size_limit=SizeLimitConfig(enabled=False, max_request_bytes=16))
    client = _client(tmp_path, cfg)
    payload = {"requestId": "R", "skillId": "s", "input": {"blob": "x" * 500}}
    assert client.post(EXECUTE_PATH, json=payload).status_code != 413


def test_invalid_content_length_rejected(tmp_path):
    """非法 Content-Length 返回 400。"""
    cfg = RuntimeConfig(size_limit=SizeLimitConfig(enabled=True, max_request_bytes=256))
    client = _client(tmp_path, cfg)
    resp = client.request("POST", EXECUTE_PATH, content=b"{}",
                          headers={"Content-Length": "abc",
                                   "Content-Type": "application/json"})
    assert resp.status_code in (400, 413)


# ---------------------------------------------------------------- M2.2 并发

def test_concurrency_limit_rejects_when_saturated(tmp_path):
    """在途请求达到上限时返回 429 CONCURRENCY_LIMITED。"""
    import asyncio

    from dkws.api.middleware import ConcurrencyLimitMiddleware, error_response

    cfg = ConcurrencyConfig(enabled=True, max_in_flight=1)

    async def scenario() -> tuple[int, int]:
        """并发发起两个请求，验证第二个被拒。"""
        started = asyncio.Event()
        release = asyncio.Event()
        mw = ConcurrencyLimitMiddleware(app=None, config=cfg)

        async def slow_call_next(_request):
            """模拟长耗时下游处理。"""
            started.set()
            await release.wait()
            return error_response(200, "OK", "done")

        async def fast_call_next(_request):
            """模拟快速下游处理（不应被调用）。"""
            return error_response(200, "OK", "done")

        class FakeRequest:
            """最小请求替身。"""

            class _URL:
                path = EXECUTE_PATH

            url = _URL()
            headers: ClassVar[dict[str, str]] = {}
            client = None

        first = asyncio.create_task(mw.dispatch(FakeRequest(), slow_call_next))
        await started.wait()
        second = await mw.dispatch(FakeRequest(), fast_call_next)
        release.set()
        first_resp = await first
        return first_resp.status_code, second.status_code

    first_code, second_code = asyncio.run(scenario())
    assert first_code == 200
    assert second_code == 429


def test_concurrency_limit_disabled_passes_through(tmp_path):
    """并发限制关闭时请求直通。"""
    client = _client(tmp_path, RuntimeConfig(concurrency=ConcurrencyConfig(enabled=False)))
    assert client.get(HEALTH_PATH).status_code == 200


def test_concurrency_limit_allows_sequential_requests(tmp_path):
    """串行请求不受并发上限影响（许可及时释放）。"""
    cfg = RuntimeConfig(concurrency=ConcurrencyConfig(enabled=True, max_in_flight=1))
    client = _client(tmp_path, cfg)
    for _ in range(5):
        assert client.get(HEALTH_PATH).status_code == 200


# ---------------------------------------------------------------- 组合行为

def test_health_reports_hardening_state(tmp_path):
    """健康检查回报加固开关状态，便于运维核验。"""
    cfg = RuntimeConfig(profile="dev", auth=_auth_config(),
                        rate_limit=RateLimitConfig(enabled=True),
                        concurrency=ConcurrencyConfig(enabled=True))
    client = _client(tmp_path, cfg)
    runtime = client.get(HEALTH_PATH).json()["data"]["runtime"]
    assert runtime["auth_enabled"] is True
    assert runtime["rate_limit_enabled"] is True
    assert runtime["size_limit_enabled"] is True
    assert runtime["concurrency_enabled"] is True


def test_rate_limit_applies_before_auth(tmp_path):
    """限流位于认证之前：未认证洪水请求同样被 429 拦截（DoS 防护）。

    这是有意的顺序设计——若认证先行，攻击者可用无效密钥无限消耗认证开销。
    """
    cfg = RuntimeConfig(auth=_auth_config(),
                        rate_limit=RateLimitConfig(enabled=True,
                                                   requests_per_minute=60, burst=1))
    client = _client(tmp_path, cfg)
    path = "/v1/knowledge/version"
    assert client.get(path).status_code == 401
    assert client.get(path).status_code == 429


def test_error_shape_is_consistent(tmp_path):
    """401/413 错误结构与既有领域错误同构。"""
    cfg = RuntimeConfig(auth=_auth_config(),
                        size_limit=SizeLimitConfig(enabled=True, max_request_bytes=64))
    client = _client(tmp_path, cfg)
    unauth = client.get("/v1/knowledge/version").json()
    assert set(unauth["error"]) == {"code", "message", "retryable"}
    oversize = client.post(EXECUTE_PATH,
                           json={"requestId": "R", "skillId": "s",
                                 "input": {"b": "x" * 500}}).json()
    assert set(oversize["error"]) == {"code", "message", "retryable"}
    assert json.loads(json.dumps(oversize))["error"]["retryable"] is False
