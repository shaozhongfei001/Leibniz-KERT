"""M2.5 可观测性端点集成测试：/livez、/readyz、/metrics 与 trace 贯通。"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from dkws.api.server import create_app
from dkws.infrastructure.observability import get_metrics_registry
from dkws.infrastructure.runtime_config import (
    DEFAULT_EXEMPT_PATHS,
    ApiKeyRecord,
    AuthConfig,
    ObservabilityConfig,
    RateLimitConfig,
    RuntimeConfig,
    RuntimeStoreConfig,
    _digest,
)

VALID_KEY = "0123456789abcdef0123"
ADMIN_KEY = "adminadminadminadmin"
VALID_TRACE = "a" * 32
VALID_SPAN = "b" * 16


@pytest.fixture(autouse=True)
def _clean_registry():
    """每个用例前后清空进程级注册表，避免指标跨用例污染。"""
    get_metrics_registry().reset()
    yield
    get_metrics_registry().reset()


def _client(ws, cfg: RuntimeConfig | None = None) -> TestClient:
    """构造 TestClient。"""
    return TestClient(create_app(ws, runtime_config=cfg or RuntimeConfig()),
                      raise_server_exceptions=False)


def _store_cfg(**obs) -> RuntimeConfig:
    """启用 Runtime Store 的配置。"""
    return RuntimeConfig(runtime_store=RuntimeStoreConfig(enabled=True),
                         observability=ObservabilityConfig(**obs))


def _auth_cfg(**obs) -> RuntimeConfig:
    """启用认证的配置（含普通与 admin 两个密钥）。"""
    return RuntimeConfig(
        auth=AuthConfig(enabled=True, keys=(
            ApiKeyRecord(key_id="svc", digest=_digest(VALID_KEY),
                         scopes=frozenset({"read", "execute"})),
            ApiKeyRecord(key_id="ops", digest=_digest(ADMIN_KEY),
                         scopes=frozenset({"read", "execute", "admin"})))),
        observability=ObservabilityConfig(**obs))


# ---------------------------------------------------------------- /livez

class TestLiveness:
    """存活探针语义。"""

    def test_livez_returns_200(self, ws):
        """存活探针返回 200。"""
        resp = _client(ws).get("/livez")
        assert resp.status_code == 200
        assert resp.json()["status"] == "alive"

    def test_livez_reports_version_and_uptime(self, ws):
        """回报服务版本与运行时长，便于运维核对。"""
        data = _client(ws).get("/livez").json()
        assert data["service_version"]
        assert data["uptime_seconds"] >= 0

    def test_livez_is_public_under_auth(self, ws):
        """启用认证后探针仍匿名可访问（否则会被 401 拦截）。"""
        assert _client(ws, _auth_cfg()).get("/livez").status_code == 200

    def test_livez_ignores_dependency_failure(self, tmp_path):
        """存活探针不检查依赖：工作区不存在仍返回 200。

        存活失败通常触发重启，若把依赖故障计入存活会导致无谓重启。
        """
        assert _client(tmp_path / "nonexistent").get("/livez").status_code == 200

    def test_livez_not_rate_limited(self, ws):
        """探针不计入限流，避免高频探测被误拒。"""
        cfg = RuntimeConfig(rate_limit=RateLimitConfig(enabled=True,
                                                      requests_per_minute=60, burst=1))
        client = _client(ws, cfg)
        assert all(client.get("/livez").status_code == 200 for _ in range(5))

    def test_livez_in_exempt_paths(self):
        """/livez 已登记为限流豁免路径。"""
        assert "/livez" in DEFAULT_EXEMPT_PATHS


# ---------------------------------------------------------------- /readyz

class TestReadiness:
    """就绪探针语义。"""

    def test_readyz_ready_on_valid_workspace(self, ws):
        """工作区就绪时返回 200。"""
        resp = _client(ws).get("/readyz")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ready"

    def test_readyz_degraded_not_blocked_without_projection(self, ws):
        """无知识投影时标记 degraded 但仍就绪。

        全新部署尚未发布投影时若判为未就绪，实例将永远无法进服务状态；
        且只读能力此时仍可用，故降级而非阻断。
        """
        data = _client(ws).get("/readyz").json()
        assert data["status"] == "ready"
        assert "knowledge_projection" in data["degraded"]
        assert data["checks"]["knowledge_projection"]["blocking"] is False

    def test_readyz_503_when_workspace_unusable(self, tmp_path):
        """工作区不可用时返回 503（硬性条件未满足）。"""
        missing = tmp_path / "nonexistent"
        resp = _client(missing).get("/readyz")
        assert resp.status_code == 503
        assert resp.json()["status"] == "not_ready"
        assert resp.json()["checks"]["workspace"]["ok"] is False

    def test_readyz_reports_check_details(self, ws):
        """回报各检查项明细，便于定位未就绪原因。"""
        checks = _client(ws).get("/readyz").json()["checks"]
        assert checks["workspace"]["ok"] is True
        assert "knowledge_projection" in checks
        assert "runtime_store" in checks

    def test_readyz_reports_store_schema(self, ws):
        """启用 Store 时回报 schema 版本与日志模式。"""
        checks = _client(ws, _store_cfg()).get("/readyz").json()["checks"]
        assert checks["runtime_store"]["schema_version"] >= 2
        assert checks["runtime_store"]["journal_mode"] == "wal"

    def test_readyz_reports_queue_stats(self, ws):
        """启用 Store 时回报队列积压情况。"""
        checks = _client(ws, _store_cfg()).get("/readyz").json()["checks"]
        assert checks["job_queue"]["ok"] is True
        assert checks["job_queue"]["dead_letter"] == 0

    def test_readyz_store_disabled_is_ok_in_dev(self, ws):
        """未启用 Store 时不阻断就绪（dev 可接受）。"""
        data = _client(ws).get("/readyz").json()
        assert data["status"] == "ready"
        assert data["checks"]["runtime_store"]["enabled"] is False

    def test_readyz_is_public_under_auth(self, ws):
        """启用认证后就绪探针仍匿名可访问。"""
        assert _client(ws, _auth_cfg()).get("/readyz").status_code == 200

    def test_readyz_sets_readiness_gauge(self, ws):
        """就绪状态写入指标，便于告警。"""
        _client(ws).get("/readyz")
        assert get_metrics_registry().get("readiness") == 1.0

    def test_readyz_gauge_zero_when_not_ready(self, tmp_path):
        """未就绪时 gauge 为 0。"""
        _client(tmp_path / "nonexistent").get("/readyz")
        assert get_metrics_registry().get("readiness") == 0.0

    def test_readyz_not_rate_limited(self, ws):
        """就绪探针不计入限流。"""
        cfg = RuntimeConfig(rate_limit=RateLimitConfig(enabled=True,
                                                      requests_per_minute=60, burst=1))
        client = _client(ws, cfg)
        assert all(client.get("/readyz").status_code == 200 for _ in range(5))


# ---------------------------------------------------------------- /metrics

class TestMetricsEndpoint:
    """指标端点语义。"""

    def test_metrics_returns_prometheus_text(self, ws):
        """返回 Prometheus 文本曝光格式。"""
        resp = _client(ws).get("/metrics")
        assert resp.status_code == 200
        assert "text/plain" in resp.headers["content-type"]
        assert "version=0.0.4" in resp.headers["content-type"]

    def test_metrics_records_http_requests(self, ws):
        """HTTP 请求被计数，含 method/path/status 标签。"""
        client = _client(ws)
        client.get("/livez")
        body = client.get("/metrics").text
        assert 'dkws_http_requests_total{method="GET",path="/livez",status="200"}' in body

    def test_metrics_records_latency_histogram(self, ws):
        """延迟直方图含桶、计数与总和。"""
        client = _client(ws)
        client.get("/livez")
        body = client.get("/metrics").text
        assert "dkws_http_request_duration_seconds_bucket" in body
        assert "dkws_http_request_duration_seconds_count" in body
        assert "dkws_http_request_duration_seconds_sum" in body

    def test_metrics_uses_route_template_not_raw_path(self, ws):
        """路径标签使用路由模板，避免路径参数造成高基数。"""
        client = _client(ws)
        for oid in ("OBJ-1", "OBJ-2", "OBJ-3"):
            client.get(f"/v1/evidence/{oid}")
        body = client.get("/metrics").text
        assert "{object_id}" in body
        assert "OBJ-1" not in body

    def test_metrics_counts_client_errors(self, ws):
        """4xx 被单独计数。"""
        client = _client(ws, _auth_cfg())
        client.get("/v1/catalog")  # 无密钥 → 401
        body = client.get("/metrics").text
        assert "dkws_http_client_errors_total" in body

    def test_metrics_observable_for_rejected_requests(self, ws):
        """被认证拦截的请求同样产生指标（可观测性无盲区）。"""
        client = _client(ws, _auth_cfg())
        client.get("/v1/catalog")
        body = client.get("/metrics").text
        assert 'status="401"' in body

    def test_metrics_reports_queue_gauges(self, ws):
        """启用 Store 时暴露队列深度指标。"""
        body = _client(ws, _store_cfg()).get("/metrics").text
        assert "dkws_job_queue_claimable" in body
        assert "dkws_job_queue_dead_letter" in body
        assert "dkws_job_queue_expired_leases" in body

    def test_metrics_reports_job_status_counts(self, ws):
        """按状态暴露 Job 计数。"""
        cfg = _store_cfg()
        app = create_app(ws, runtime_config=cfg)
        app.state.runtime_store.create_job("J1", "SKILL")
        client = TestClient(app, raise_server_exceptions=False)
        body = client.get("/metrics").text
        assert 'dkws_job_status_count{status="PENDING"} 1' in body

    def test_metrics_reports_build_info(self, ws):
        """暴露构建信息，便于版本核对。"""
        body = _client(ws).get("/metrics").text
        assert "dkws_build_info" in body
        assert 'profile="dev"' in body

    def test_metrics_reports_uptime(self, ws):
        """暴露进程运行时长。"""
        assert "dkws_process_uptime_seconds" in _client(ws).get("/metrics").text

    def test_metrics_can_be_disabled(self, ws):
        """关闭后返回 404。"""
        cfg = RuntimeConfig(observability=ObservabilityConfig(metrics_enabled=False))
        assert _client(ws, cfg).get("/metrics").status_code == 404

    def test_metrics_admin_required_rejects_non_admin(self, ws):
        """要求 admin 时普通密钥被拒（指标含内部信息）。"""
        client = _client(ws, _auth_cfg(metrics_require_admin=True))
        resp = client.get("/metrics", headers={"X-API-Key": VALID_KEY})
        assert resp.status_code == 403

    def test_metrics_admin_required_allows_admin(self, ws):
        """要求 admin 时 admin 密钥可访问。"""
        client = _client(ws, _auth_cfg(metrics_require_admin=True))
        resp = client.get("/metrics", headers={"X-API-Key": ADMIN_KEY})
        assert resp.status_code == 200

    def test_metrics_public_when_admin_not_required(self, ws):
        """默认不要求 admin 时匿名可采集（依赖网络层限制来源）。"""
        assert _client(ws, _auth_cfg()).get("/metrics").status_code == 200

    def test_metrics_not_rate_limited(self, ws):
        """指标采集不计入限流。"""
        cfg = RuntimeConfig(rate_limit=RateLimitConfig(enabled=True,
                                                      requests_per_minute=60, burst=1))
        client = _client(ws, cfg)
        assert all(client.get("/metrics").status_code == 200 for _ in range(5))


# ---------------------------------------------------------------- Trace 贯通

class TestTraceContext:
    """W3C Trace Context 贯通。"""

    def test_request_id_returned_in_header(self, ws):
        """响应头回传 X-Request-Id。"""
        assert _client(ws).get("/livez").headers["X-Request-Id"].startswith("REQ-")

    def test_incoming_request_id_preserved(self, ws):
        """沿用调用方提供的 X-Request-Id，便于跨系统关联。"""
        resp = _client(ws).get("/livez", headers={"X-Request-Id": "CALLER-123"})
        assert resp.headers["X-Request-Id"] == "CALLER-123"

    def test_traceparent_returned(self, ws):
        """响应头回传 traceparent。"""
        header = _client(ws).get("/livez").headers["traceparent"]
        assert header.startswith("00-")
        assert len(header.split("-")) == 4

    def test_incoming_traceparent_continues_trace(self, ws):
        """沿用上游 trace id，实现链路串联。"""
        incoming = f"00-{VALID_TRACE}-{VALID_SPAN}-01"
        resp = _client(ws).get("/livez", headers={"traceparent": incoming})
        assert resp.headers["traceparent"].split("-")[1] == VALID_TRACE

    def test_malformed_traceparent_starts_new_trace(self, ws):
        """畸形 traceparent 不污染链路，改为新建 trace。"""
        resp = _client(ws).get("/livez", headers={"traceparent": "garbage"})
        returned = resp.headers["traceparent"].split("-")[1]
        assert len(returned) == 32
        assert returned != "garbage"

    def test_span_id_differs_from_parent(self, ws):
        """本服务生成新 span id，不复用上游 span。"""
        incoming = f"00-{VALID_TRACE}-{VALID_SPAN}-01"
        resp = _client(ws).get("/livez", headers={"traceparent": incoming})
        assert resp.headers["traceparent"].split("-")[2] != VALID_SPAN

    def test_trace_recorded_in_tracer(self, ws):
        """span 被记录到追踪器。"""
        app = create_app(ws, runtime_config=RuntimeConfig())
        app.state.tracer.reset()
        TestClient(app, raise_server_exceptions=False).get("/livez")
        spans = app.state.tracer.recent_spans()
        assert spans
        assert "/livez" in spans[-1].name

    def test_tracing_can_be_disabled(self, ws):
        """关闭追踪后不记录 span，但请求仍正常。"""
        cfg = RuntimeConfig(observability=ObservabilityConfig(tracing_enabled=False))
        app = create_app(ws, runtime_config=cfg)
        app.state.tracer.reset()
        assert TestClient(app).get("/livez").status_code == 200
        assert app.state.tracer.span_count() == 0

    def test_capabilities_exposed(self, ws):
        """可选依赖能力上报在 app.state，便于运维自检。"""
        app = create_app(ws, runtime_config=RuntimeConfig())
        caps = app.state.observability_capabilities
        assert set(caps) == {"otel_available", "otel_attached",
                             "prometheus_client_available"}
        assert all(isinstance(v, bool) for v in caps.values())


# ---------------------------------------------------------------- health 兼容

class TestHealthCompatibility:
    """既有 /v1/health 不被破坏。"""

    def test_health_still_works(self, ws):
        """既有健康检查端点保持可用。"""
        resp = _client(ws).get("/v1/health")
        assert resp.status_code == 200
        assert resp.json()["data"]["status"] in ("OK", "DEGRADED")

    def test_health_envelope_preserved(self, ws):
        """信封结构未变（request_id/data/meta）。"""
        payload = _client(ws).get("/v1/health").json()
        assert "data" in payload
        assert json.dumps(payload)  # 可序列化
