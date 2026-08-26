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
import threading
import time
from collections.abc import Awaitable, Callable

from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from ..domain.errors import ERROR_CODES
from ..infrastructure.runtime_config import (
    SCOPE_ADMIN,
    AuthConfig,
    ConcurrencyConfig,
    RateLimitConfig,
    SizeLimitConfig,
)

CallNext = Callable[[Request], Awaitable[Response]]

#: 认证通过后写入 ``request.state`` 的字段名
STATE_KEY_ID = "api_key_id"
STATE_SCOPES = "api_key_scopes"


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
        request.state.__dict__[STATE_KEY_ID] = record.key_id
        request.state.__dict__[STATE_SCOPES] = sorted(record.scopes)
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
        if cfg.enabled and request.url.path in ("/v1/health", "/api/skill/health"):
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
