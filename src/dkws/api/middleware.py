"""API 安全与流量控制中间件（M2.1/M2.2，ADR-013）。

包含四个中间件，注册顺序（外 → 内）：

1. :class:`SizeLimitMiddleware`  —— 请求体/响应体大小上限（413）
2. :class:`ConcurrencyLimitMiddleware` —— 在途请求并发上限（429）
3. :class:`RateLimitMiddleware`  —— 按 API Key/IP 的令牌桶限流（429）
4. :class:`ApiKeyAuthMiddleware` —— API Key 认证与作用域校验（401/403）

统一错误响应体与既有 HTTP 错误保持同构：
``{"error": {"code": ..., "message": ..., "retryable": ...}}``。

密钥明文不写日志、不进响应；仅使用 ``key_id`` 做标识与限流分桶。
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from collections.abc import Awaitable, Callable

from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from ..domain.errors import ERROR_CODES
from ..infrastructure.classification import (
    Classification,
    RedactionPolicy,
    RedactionReport,
    redact_structure,
)
from ..infrastructure.observability import (
    MetricsRegistry,
    Tracer,
    format_traceparent,
    get_metrics_registry,
    get_tracer,
    log_event,
    new_request_id,
    new_span_id,
    new_trace_id,
    parse_traceparent,
    reset_request_context,
    set_request_context,
)
from ..infrastructure.runtime_config import (
    DEFAULT_EXEMPT_PATHS,
    SCOPE_ADMIN,
    AuthConfig,
    ConcurrencyConfig,
    ObservabilityConfig,
    RateLimitConfig,
    RedactionConfig,
    SizeLimitConfig,
)

CallNext = Callable[[Request], Awaitable[Response]]

#: 指标端点路径（访问控制由 ObservabilityConfig 决定，见认证中间件说明）
METRICS_PATH = "/metrics"

#: 认证通过后写入 ``request.state`` 的字段名
STATE_KEY_ID = "api_key_id"
STATE_SCOPES = "api_key_scopes"
#: 可观测性中间件写入 ``request.state`` 的字段名
STATE_REQUEST_ID = "request_id"
STATE_TRACE_ID = "trace_id"


def error_response(status_code: int, code: str, message: str,
                   headers: dict[str, str] | None = None) -> JSONResponse:
    """构造与领域错误同构的 JSON 错误响应。

    Args:
        status_code: HTTP 状态码。
        code: 领域错误码（见 ``domain.errors.ERROR_CODES``）。
        message: 面向调用方的可读信息，不含机密。
        headers: 附加响应头，如 ``Retry-After``。

    Returns:
        JSONResponse 实例。
    """
    spec = ERROR_CODES.get(code)
    retryable = spec.retryable if spec else False
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message, "retryable": retryable}},
        headers=headers or {},
    )


def _client_ip(request: Request) -> str:
    """取客户端 IP；无法识别时返回 ``unknown``。

    不信任 ``X-Forwarded-For``：TLS/代理边界由可信网关负责（ADR-013），
    在此直接采用连接对端地址，避免调用方伪造分桶键绕过限流。
    """
    client = request.client
    return client.host if client and client.host else "unknown"


def _publish_identity(request: Request, key_id: str, scopes: list[str]) -> None:
    """把认证身份同时写入 ``request.state`` 与 ASGI ``scope``。

    ``BaseHTTPMiddleware`` 为每一层中间件构造**独立的** ``Request`` 对象，
    因此仅写 ``request.state`` 无法传递到路由处理函数；ASGI ``scope`` 字典
    在整个请求生命周期内共享，故一并写入以便端点读取。
    """
    request.state.__dict__[STATE_KEY_ID] = key_id
    request.state.__dict__[STATE_SCOPES] = scopes
    request.scope[STATE_KEY_ID] = key_id
    request.scope[STATE_SCOPES] = scopes


class ApiKeyAuthMiddleware(BaseHTTPMiddleware):
    """API Key 认证中间件（401/403）。

    行为：
    - ``auth.enabled=False``：全部放行（dev 便利模式）。
    - 白名单路径（默认健康检查）：放行，便于探针无凭据访问。
    - 缺失/无效密钥：401 ``UNAUTHENTICATED``，并带 ``WWW-Authenticate``。
    - 密钥有效但访问管理端点且缺少 ``admin`` 作用域：403 ``FORBIDDEN``。
    """

    def __init__(self, app, config: AuthConfig):
        """记录认证配置。"""
        super().__init__(app)
        self._config = config

    async def dispatch(self, request: Request, call_next: CallNext) -> Response:
        """执行认证与作用域校验。"""
        cfg = self._config
        if not cfg.enabled:
            return await call_next(request)
        path = request.url.path
        if cfg.is_public(path):
            return await call_next(request)

        presented = request.headers.get(cfg.header_name, "")
        if path == METRICS_PATH:
            # /metrics 的访问控制由 ObservabilityConfig.metrics_require_admin
            # 单一决定：若在此按普通端点强制 401，该开关将永无机会生效。
            # 采集器通常无法携带密钥，故此处放行并尽力识别身份，
            # 由端点自身校验 admin 作用域（需强控时置 metrics_require_admin=true）。
            if not presented:
                header = request.headers.get("Authorization", "")
                if header.lower().startswith("bearer "):
                    presented = header[7:].strip()
            found = cfg.verify(presented) if presented else None
            if found is not None:
                _publish_identity(request, found.key_id, sorted(found.scopes))
            return await call_next(request)
        if not presented:
            auth_header = request.headers.get("Authorization", "")
            if auth_header.lower().startswith("bearer "):
                presented = auth_header[7:].strip()
        if not presented:
            return error_response(401, "UNAUTHENTICATED",
                                  f"缺少 API Key，请提供 {cfg.header_name} 请求头",
                                  {"WWW-Authenticate": f"ApiKey realm=\"dkws\", "
                                                       f"header=\"{cfg.header_name}\""})
        record = cfg.verify(presented)
        if record is None:
            return error_response(401, "UNAUTHENTICATED", "API Key 无效或已吊销",
                                  {"WWW-Authenticate": f"ApiKey realm=\"dkws\", "
                                                       f"header=\"{cfg.header_name}\""})
        if cfg.requires_admin(path) and not record.has_scope(SCOPE_ADMIN):
            return error_response(403, "FORBIDDEN",
                                  f"作用域不足：端点 {path} 需要 {SCOPE_ADMIN} 作用域")
        _publish_identity(request, record.key_id, sorted(record.scopes))
        return await call_next(request)


class _TokenBucket:
    """线程安全令牌桶。"""

    __slots__ = ("_tokens", "_updated", "capacity", "refill_rate")

    def __init__(self, capacity: int, refill_rate: float, now: float):
        """初始化为满桶。"""
        self.capacity = capacity
        self.refill_rate = refill_rate
        self._tokens = float(capacity)
        self._updated = now

    def consume(self, now: float) -> float:
        """尝试消耗一个令牌。

        Returns:
            0.0 表示放行；正数表示需等待的秒数（已拒绝）。
        """
        elapsed = max(0.0, now - self._updated)
        self._updated = now
        self._tokens = min(float(self.capacity), self._tokens + elapsed * self.refill_rate)
        if self._tokens >= 1.0:
            self._tokens -= 1.0
            return 0.0
        if self.refill_rate <= 0:
            return 60.0
        return (1.0 - self._tokens) / self.refill_rate


class RateLimitMiddleware(BaseHTTPMiddleware):
    """按 API Key（优先）或客户端 IP 的令牌桶限流中间件（429）。

    本中间件位于认证**之前**，以便未通过认证的洪水请求同样受限（DoS 防护）。
    为仍能按 Key 分桶，这里自行做一次轻量密钥识别（仅摘要比较取 ``key_id``，
    不做作用域判定，也不代替认证决策）；识别失败则退回按客户端 IP 分桶。

    单机单实例场景采用进程内计数（ADR-015）；不引入 Redis。
    """

    def __init__(self, app, config: RateLimitConfig,
                 auth_config: AuthConfig | None = None,
                 time_source: Callable[[], float] | None = None):
        """初始化桶表、密钥识别配置与时间源（时间源便于测试注入）。"""
        super().__init__(app)
        self._config = config
        self._auth = auth_config
        self._now = time_source or time.monotonic
        self._buckets: dict[str, _TokenBucket] = {}
        self._lock = threading.Lock()

    def _bucket_key(self, request: Request) -> str:
        """限流分桶键：优先 API Key ID，其次客户端 IP。"""
        key_id = request.state.__dict__.get(STATE_KEY_ID)
        if key_id:
            return f"key:{key_id}"
        if self._auth is not None and self._auth.enabled:
            presented = request.headers.get(self._auth.header_name, "")
            if not presented:
                header = request.headers.get("Authorization", "")
                if header.lower().startswith("bearer "):
                    presented = header[7:].strip()
            record = self._auth.verify(presented) if presented else None
            if record is not None:
                return f"key:{record.key_id}"
        return f"ip:{_client_ip(request)}"

    async def dispatch(self, request: Request, call_next: CallNext) -> Response:
        """检查配额，超限返回 429。"""
        cfg = self._config
        if not cfg.enabled:
            return await call_next(request)
        # 探针与指标采集为高频周期性访问，被限流会导致误判服务异常
        if request.url.path in DEFAULT_EXEMPT_PATHS:
            return await call_next(request)
        now = self._now()
        key = self._bucket_key(request)
        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                bucket = _TokenBucket(cfg.capacity(), cfg.refill_per_second(), now)
                self._buckets[key] = bucket
            wait = bucket.consume(now)
        if wait > 0:
            retry_after = max(1, int(wait + 0.999))
            return error_response(
                429, "RATE_LIMITED",
                f"请求超过限流额度（{cfg.requests_per_minute} 次/分钟），请稍后重试",
                {"Retry-After": str(retry_after)})
        return await call_next(request)


class ConcurrencyLimitMiddleware(BaseHTTPMiddleware):
    """在途请求并发上限中间件（429）。

    使用 ``asyncio.Semaphore`` 限制同时处理的请求数；配置
    ``acquire_timeout_seconds<=0`` 时超限立即拒绝，否则等待该时长再拒绝。
    """

    def __init__(self, app, config: ConcurrencyConfig):
        """记录并发配置，信号量在首次使用时按事件循环创建。"""
        super().__init__(app)
        self._config = config
        self._semaphore: asyncio.Semaphore | None = None

    def _get_semaphore(self) -> asyncio.Semaphore:
        """惰性创建信号量（绑定当前事件循环）。"""
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(self._config.max_in_flight)
        return self._semaphore

    async def dispatch(self, request: Request, call_next: CallNext) -> Response:
        """获取许可后转发；获取失败返回 429。"""
        cfg = self._config
        if not cfg.enabled:
            return await call_next(request)
        sem = self._get_semaphore()
        timeout = cfg.acquire_timeout_seconds
        try:
            if timeout and timeout > 0:
                await asyncio.wait_for(sem.acquire(), timeout=timeout)
            else:
                if sem.locked():
                    raise TimeoutError
                await sem.acquire()
        except TimeoutError:
            return error_response(
                429, "CONCURRENCY_LIMITED",
                f"并发请求数超过上限（{cfg.max_in_flight}），请稍后重试",
                {"Retry-After": "1"})
        try:
            return await call_next(request)
        finally:
            sem.release()


class SizeLimitMiddleware(BaseHTTPMiddleware):
    """请求体/响应体大小上限中间件（413）。

    请求侧：优先按 ``Content-Length`` 预检；无该头时流式累计校验，
    避免读取超大 chunked 请求体。
    响应侧：按 ``Content-Length`` 或已缓冲字节数校验，超限替换为 413。
    """

    def __init__(self, app, config: SizeLimitConfig):
        """记录大小限制配置。"""
        super().__init__(app)
        self._config = config

    async def dispatch(self, request: Request, call_next: CallNext) -> Response:
        """先校验请求体，再校验响应体。"""
        cfg = self._config
        if not cfg.enabled:
            return await call_next(request)
        limit = cfg.max_request_bytes
        declared = request.headers.get("content-length")
        if declared:
            try:
                if int(declared) > limit:
                    return self._too_large("请求体", int(declared), limit)
            except ValueError:
                return error_response(400, "INVALID_REQUEST", "Content-Length 非法")
        else:
            oversize = await self._buffer_body(request, limit)
            if oversize is not None:
                return oversize

        response = await call_next(request)
        return await self._check_response(response, cfg.max_response_bytes)

    async def _buffer_body(self, request: Request, limit: int) -> Response | None:
        """在无 Content-Length 时流式累计请求体并重放。

        Returns:
            超限时返回 413 响应；否则 None（并已重置 receive 通道）。
        """
        chunks: list[bytes] = []
        total = 0
        more_body = True
        receive = request.receive
        while more_body:
            message = await receive()
            if message["type"] != "http.request":
                chunks.append(b"")
                break
            body = message.get("body", b"") or b""
            total += len(body)
            if total > limit:
                return self._too_large("请求体", total, limit)
            chunks.append(body)
            more_body = bool(message.get("more_body", False))
        buffered = b"".join(chunks)
        sent = False

        async def replay() -> dict:
            """重放已缓冲的请求体，供下游解析。"""
            nonlocal sent
            if not sent:
                sent = True
                return {"type": "http.request", "body": buffered, "more_body": False}
            return {"type": "http.disconnect"}

        # Starlette 官方重放方式：替换 receive 通道供下游重新读取请求体
        request._receive = replay
        return None

    async def _check_response(self, response: Response, limit: int) -> Response:
        """校验响应体大小，超限替换为 413。"""
        declared = response.headers.get("content-length")
        if declared:
            try:
                if declared and int(declared) > limit:
                    return self._too_large("响应体", int(declared), limit)
            except ValueError:
                return response
            return response
        body_iter = getattr(response, "body_iterator", None)
        if body_iter is None:
            body = getattr(response, "body", b"") or b""
            if len(body) > limit:
                return self._too_large("响应体", len(body), limit)
            return response
        chunks: list[bytes] = []
        total = 0
        async for chunk in body_iter:
            data = chunk if isinstance(chunk, bytes) else str(chunk).encode("utf-8")
            total += len(data)
            if total > limit:
                return self._too_large("响应体", total, limit)
            chunks.append(data)
        return Response(content=b"".join(chunks), status_code=response.status_code,
                        headers=dict(response.headers),
                        media_type=response.media_type)

    @staticmethod
    def _too_large(what: str, actual: int, limit: int) -> JSONResponse:
        """构造 413 响应。"""
        return error_response(413, "PAYLOAD_TOO_LARGE",
                              f"{what}大小 {actual} 字节超过上限 {limit} 字节")


class ObservabilityMiddleware(BaseHTTPMiddleware):
    """请求可观测性中间件（M2.5）：贯通 trace context、记录指标与访问日志。

    位于中间件栈**最外层**，因此能覆盖被限流/认证拦截的请求，
    使 4xx 拒绝同样产生指标与日志（可观测性不应有盲区）。

    职责：
    1. 解析或新建 W3C Trace Context（``traceparent``），写入请求上下文；
    2. 生成/沿用 ``X-Request-Id``，并在响应头回传，便于端到端排障；
    3. 记录 HTTP 请求计数与延迟直方图；
    4. 输出结构化访问日志（字段含 request_id/trace_id/status/duration）。

    路径标签使用**路由模板**（如 ``/v1/evidence/{object_id}``）而非原始路径，
    避免高基数标签把指标存储打爆。
    """

    def __init__(self, app, config: ObservabilityConfig,
                 *, registry: MetricsRegistry | None = None,
                 tracer: Tracer | None = None,
                 time_source: Callable[[], float] | None = None):
        """绑定配置与注册表；``time_source`` 便于测试注入。"""
        super().__init__(app)
        self._config = config
        self._registry = registry or get_metrics_registry()
        self._tracer = tracer or get_tracer()
        self._now = time_source or time.perf_counter
        self._logger = logging.getLogger("dkws.access")

    @staticmethod
    def _route_template(request: Request) -> str:
        """返回路由模板，未匹配到路由时回落为 ``__unmatched__``。

        直接用原始路径会因路径参数（如 job_id）产生无界标签基数，
        故优先取 Starlette 解析出的 ``route.path``。
        """
        route = request.scope.get("route")
        template = getattr(route, "path", None)
        if template:
            return str(template)
        return request.url.path if request.url.path in DEFAULT_EXEMPT_PATHS else "__unmatched__"

    async def dispatch(self, request: Request, call_next: CallNext) -> Response:
        """包裹请求处理，记录 trace / 指标 / 访问日志。"""
        cfg = self._config
        incoming = parse_traceparent(request.headers.get("traceparent"))
        if incoming is not None:
            trace_id, parent_span_id = incoming
        else:
            trace_id, parent_span_id = new_trace_id(), None
        span_id = new_span_id()
        request_id = (request.headers.get("X-Request-Id") or "").strip() or new_request_id()

        token = set_request_context(request_id=request_id, trace_id=trace_id,
                                   span_id=span_id, method=request.method,
                                   path=request.url.path)
        request.state.__dict__[STATE_REQUEST_ID] = request_id
        request.state.__dict__[STATE_TRACE_ID] = trace_id

        started = self._now()
        wall_start = time.time()
        status_code = 500
        response: Response | None = None
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        except Exception:
            # 未捕获异常也要留下指标与日志，再交由上层异常处理
            self._registry.counter(
                "http_errors_total", "未捕获异常导致的请求失败数",
                labels={"method": request.method,
                        "path": self._route_template(request)})
            raise
        finally:
            duration = max(0.0, self._now() - started)
            path_label = self._route_template(request)
            labels = {"method": request.method, "path": path_label,
                      "status": str(status_code)}
            self._registry.counter("http_requests_total", "HTTP 请求总数",
                                   labels=labels)
            self._registry.observe("http_request_duration_seconds",
                                   duration, "HTTP 请求处理耗时（秒）",
                                   labels={"method": request.method,
                                           "path": path_label})
            if status_code >= 500:
                self._registry.counter("http_server_errors_total",
                                       "5xx 响应数", labels=labels)
            elif status_code >= 400:
                self._registry.counter("http_client_errors_total",
                                       "4xx 响应数", labels=labels)

            if cfg.tracing_enabled and self._tracer.should_sample():
                self._tracer.record_span(
                    f"{request.method} {path_label}", trace_id, span_id,
                    parent_span_id, wall_start, time.time(),
                    status="OK" if status_code < 500 else "ERROR",
                    http_status=status_code, http_method=request.method)

            # 响应头回传（异常路径下 response 为 None，跳过）
            if response is not None:
                response.headers["X-Request-Id"] = request_id
                response.headers["traceparent"] = format_traceparent(trace_id, span_id)

            log_event(self._logger,
                      "WARNING" if status_code >= 400 else "INFO",
                      "HTTP_ACCESS",
                      f"{request.method} {request.url.path} -> {status_code}",
                      status=status_code,
                      duration_ms=round(duration * 1000, 3),
                      key_id=request.state.__dict__.get(STATE_KEY_ID),
                      client_ip=_client_ip(request))
            reset_request_context(token)


class ResponseRedactionMiddleware(BaseHTTPMiddleware):
    """响应脱敏中间件（M2.9）：按数据分类掩码出站 JSON 字段。

    **默认关闭**：既有响应契约与测试依赖原文（例如报告正文含企业名），
    贸然全局脱敏会破坏门禁。生产环境可显式开启，或由调用方按
    ``X-DKWS-Redact`` 请求头选择性启用（仅当配置允许时）。

    仅处理 ``application/json`` 响应；其他类型（Prometheus 文本、
    Markdown 报告、二进制）原样透传——报告类产物的脱敏应在生成阶段
    按分类处理，而非在传输层粗暴替换。
    """

    def __init__(self, app, config: RedactionConfig):
        """绑定脱敏配置。"""
        super().__init__(app)
        self._config = config
        self._logger = logging.getLogger("dkws.redaction")

    def _policy(self) -> RedactionPolicy:
        """按配置构造脱敏策略。"""
        return RedactionPolicy(
            threshold=Classification.parse(self._config.response_threshold),
            mask_text=self._config.response_mask_text,
            annotate=self._config.annotate)

    async def dispatch(self, request: Request, call_next: CallNext) -> Response:
        """脱敏 JSON 响应体。"""
        response = await call_next(request)
        if not self._config.response_enabled:
            return response
        content_type = response.headers.get("content-type", "")
        if "application/json" not in content_type:
            return response
        if response.status_code >= 500:
            # 5xx 响应体可能非 JSON 信封，避免二次处理掩盖原始错误
            return response

        body = b""
        async for chunk in response.body_iterator:
            body += chunk if isinstance(chunk, bytes) else str(chunk).encode()
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            # 声明 JSON 但内容不可解析：原样返回，不做猜测
            return Response(content=body, status_code=response.status_code,
                            headers=dict(response.headers),
                            media_type=response.media_type)

        report = RedactionReport()
        redacted = redact_structure(payload, self._policy(), report=report)
        if report.count and self._config.annotate and isinstance(redacted, dict):
            meta = redacted.get("meta")
            if isinstance(meta, dict):
                meta["redaction"] = report.as_dict()
        if report.count:
            log_event(self._logger, "INFO", "RESPONSE_REDACTED",
                      f"响应脱敏 {report.count} 个字段",
                      path=request.url.path, masked=report.count)

        new_body = json.dumps(redacted, ensure_ascii=False).encode("utf-8")
        headers = dict(response.headers)
        headers["content-length"] = str(len(new_body))
        return Response(content=new_body, status_code=response.status_code,
                        headers=headers, media_type="application/json")
