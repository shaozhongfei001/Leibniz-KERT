"""可观测性基础设施（M2.5）：请求上下文、结构化日志、指标注册表、追踪。

设计原则
--------
- **零新增必需依赖**：Prometheus 文本格式与 JSON 日志均自研实现；
  ``prometheus_client`` / ``opentelemetry`` 仅作**可选增强**，缺失时自动降级
  （与既有 ``kuzu`` 的 fail-open 风格一致）。
- **不改动 §9.20 文件日志**：``JobLogger`` 的行格式与 ``log_sha256`` 是受门禁
  约束的审计契约，本模块**新增** stdout JSON 通道，不替换文件通道。
- **脱敏复用**：直接复用 :mod:`dkws.infrastructure.logging` 的
  ``mask_sensitive`` / ``_sanitize_message``，避免两套规则漂移。
"""

from __future__ import annotations

import contextvars
import json
import logging
import re
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field

from .logging import SENSITIVE_KEYS, _sanitize_message

# ---------------------------------------------------------------- 请求上下文

#: 当前请求上下文（跨中间件与业务代码传播，协程安全）
_request_ctx: contextvars.ContextVar[dict | None] = contextvars.ContextVar(
    "dkws_request_ctx", default=None)

#: W3C traceparent 格式：version-traceid(32)-spanid(16)-flags(2)
_TRACEPARENT_RE = re.compile(
    r"^(?P<version>[0-9a-f]{2})-(?P<trace_id>[0-9a-f]{32})-"
    r"(?P<span_id>[0-9a-f]{16})-(?P<flags>[0-9a-f]{2})$")


def new_trace_id() -> str:
    """生成 32 位十六进制 trace id（W3C Trace Context 规范）。"""
    return uuid.uuid4().hex


def new_span_id() -> str:
    """生成 16 位十六进制 span id。"""
    return uuid.uuid4().hex[:16]


def new_request_id() -> str:
    """生成请求标识（便于人工检索，带 REQ- 前缀）。"""
    return f"REQ-{uuid.uuid4().hex[:16]}"


def parse_traceparent(header: str | None) -> tuple[str, str] | None:
    """解析 W3C ``traceparent`` 头，返回 ``(trace_id, parent_span_id)``。

    仅接受严格合规且非全零的值；不合规时返回 ``None`` 由调用方新建 trace，
    避免上游伪造的畸形头污染链路。
    """
    if not header:
        return None
    m = _TRACEPARENT_RE.match(header.strip().lower())
    if m is None:
        return None
    trace_id, span_id = m.group("trace_id"), m.group("span_id")
    if trace_id == "0" * 32 or span_id == "0" * 16:
        return None
    return trace_id, span_id


def format_traceparent(trace_id: str, span_id: str, *, sampled: bool = True) -> str:
    """构造 W3C ``traceparent`` 头值。"""
    return f"00-{trace_id}-{span_id}-{'01' if sampled else '00'}"


def set_request_context(**fields) -> contextvars.Token:
    """设置当前请求上下文，返回可用于复原的 token。"""
    current = _request_ctx.get() or {}
    merged = {**current, **{k: v for k, v in fields.items() if v is not None}}
    return _request_ctx.set(merged)


def reset_request_context(token: contextvars.Token) -> None:
    """复原请求上下文（中间件退出时调用，防止跨请求泄漏）。"""
    _request_ctx.reset(token)


def get_request_context() -> dict:
    """读取当前请求上下文副本。"""
    return dict(_request_ctx.get() or {})


def current_request_id() -> str | None:
    """当前请求 ID（无上下文时返回 ``None``）。"""
    return (_request_ctx.get() or {}).get("request_id")


def current_trace_id() -> str | None:
    """当前 trace ID。"""
    return (_request_ctx.get() or {}).get("trace_id")


# ---------------------------------------------------------------- 结构化日志

#: 统一日志字段顺序（规格要求 requestId/traceId/tenantId/skillId 贯通）
LOG_FIELD_ORDER = ("timestamp", "level", "logger", "event_code", "message",
                   "request_id", "trace_id", "span_id", "tenant_id", "skill_id",
                   "job_id", "key_id", "component")


#: 消息正文中的 "敏感键=值" / "敏感键: 值" 模式（M2.5 新增 stdout 通道后的泄漏面收口）
_INLINE_SECRET_RE = re.compile(
    r"(?i)\b(password|passwd|pwd|token|secret|credential|authorization|"
    r"api[_-]?key|private[_-]?key)\b(\s*[=:]\s*|\s+)"
    r"(?:bearer\s+)?"          # 吞掉 Bearer 前缀，避免只脱敏前缀而漏掉真实凭据
    r"([^\s,;\"'\]}]{4,})")

#: 常见密钥字面量前缀（sk-/ghp_ 等），即使无键名也应脱敏
_BARE_SECRET_RE = re.compile(
    r"\b(?:sk-|ghp_|gho_|github_pat_|xox[baprs]-)[A-Za-z0-9_\-]{8,}"
    r"|\bbearer\s+[A-Za-z0-9._\-]{8,}", re.IGNORECASE)


def redact_message(message: str) -> str:
    """脱敏消息正文中的内联密钥。

    :func:`~dkws.infrastructure.logging._sanitize_message` 仅折叠空白与截断，
    **不做内容脱敏**；字段级脱敏也只看键名。M2.5 新增 stdout 日志通道后，
    形如 ``token=abc123`` 的正文会成为新的泄漏面，故在此收口。

    不修改 §9.20 文件日志的既有行为，仅作用于本模块的 JSON 通道。
    """
    redacted = _INLINE_SECRET_RE.sub(lambda m: f"{m.group(1)}{m.group(2)}***", message)
    return _BARE_SECRET_RE.sub("***", redacted)


def _mask_value(key: str, value):
    """对单个字段值脱敏；保留非敏感值的原始类型便于机器解析。"""
    lowered = key.lower()
    if lowered in SENSITIVE_KEYS or any(s in lowered for s in ("secret", "token",
                                                              "password", "credential")):
        return "***"
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return redact_message(_sanitize_message(value))


class JsonLogFormatter(logging.Formatter):
    """把日志记录序列化为单行 JSON，并自动注入请求上下文。

    字段来源三处：``LogRecord`` 标准字段、``extra=`` 传入的业务字段、
    以及 :func:`get_request_context` 的请求上下文（后者不覆盖显式字段）。
    """

    #: LogRecord 的内建属性，不作为业务字段输出
    _RESERVED = frozenset((
        "args", "asctime", "created", "exc_info", "exc_text", "filename",
        "funcName", "levelname", "levelno", "lineno", "module", "msecs",
        "message", "msg", "name", "pathname", "process", "processName",
        "relativeCreated", "stack_info", "thread", "threadName", "taskName"))

    def __init__(self, *, service: str = "dkws-python-core",
                 include_context: bool = True):
        """记录服务名；``include_context=False`` 可用于纯单元测试。"""
        super().__init__()
        self._service = service
        self._include_context = include_context

    def format(self, record: logging.LogRecord) -> str:
        """序列化为 JSON 单行。"""
        payload: dict = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S",
                                       time.gmtime(record.created)) + "Z",
            "level": record.levelname,
            "logger": record.name,
            "service": self._service,
            "message": redact_message(_sanitize_message(record.getMessage())),
        }
        if self._include_context:
            for key, value in get_request_context().items():
                payload.setdefault(key, value)
        for key, value in record.__dict__.items():
            if key in self._RESERVED or key.startswith("_"):
                continue
            payload[key] = _mask_value(key, value)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)[:2000]

        ordered = {k: payload.pop(k) for k in LOG_FIELD_ORDER if k in payload}
        ordered.update(payload)
        return json.dumps(ordered, ensure_ascii=False, default=str)


def configure_structured_logging(*, level: str = "INFO",
                                 service: str = "dkws-python-core",
                                 stream=None, force: bool = True) -> logging.Handler:
    """把根 logger 配置为单行 JSON 输出到 stdout（容器友好）。

    Args:
        level: 日志级别名。
        service: 服务标识，写入每条日志。
        stream: 输出流，缺省 ``sys.stdout``。
        force: 是否移除既有 handler（避免重复输出）。

    Returns:
        新安装的 handler，便于测试断言或后续移除。
    """
    handler = logging.StreamHandler(stream or sys.stdout)
    handler.setFormatter(JsonLogFormatter(service=service))
    root = logging.getLogger()
    if force:
        for existing in list(root.handlers):
            root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    return handler


def log_event(logger: logging.Logger, level: str, event_code: str, message: str,
              **fields) -> None:
    """记录带事件码的结构化日志（字段自动脱敏）。"""
    numeric = getattr(logging, level.upper(), logging.INFO)
    safe = {k: _mask_value(k, v) for k, v in fields.items() if v is not None}
    logger.log(numeric, message, extra={"event_code": event_code, **safe})


# ---------------------------------------------------------------- 指标注册表

#: Prometheus 指标名合法字符
_METRIC_NAME_RE = re.compile(r"^[a-zA-Z_:][a-zA-Z0-9_:]*$")

#: 默认延迟直方图分桶（秒），覆盖 5ms~10s
DEFAULT_LATENCY_BUCKETS: tuple[float, ...] = (
    0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)


def _escape_label(value: str) -> str:
    """转义标签值中的反斜杠、引号与换行（Prometheus 文本格式要求）。"""
    return (str(value).replace("\\", "\\\\").replace('"', '\\"')
            .replace("\n", "\\n"))


def _render_labels(labels: tuple[tuple[str, str], ...]) -> str:
    """渲染标签集合为 Prometheus 文本片段。"""
    if not labels:
        return ""
    inner = ",".join(f'{k}="{_escape_label(v)}"' for k, v in labels)
    return "{" + inner + "}"


@dataclass
class _Metric:
    """单个指标的元数据与样本集合。"""

    name: str
    kind: str
    help_text: str
    buckets: tuple[float, ...] = ()
    #: 标签组合 → 值（counter/gauge）
    values: dict[tuple[tuple[str, str], ...], float] = field(default_factory=dict)
    #: 标签组合 → (各桶累计计数, 总数, 总和)（histogram）
    hist: dict[tuple[tuple[str, str], ...], list] = field(default_factory=dict)


class MetricsRegistry:
    """线程安全的进程内指标注册表，输出 Prometheus 文本格式。

    自研而非直接依赖 ``prometheus_client``：本项目为单机单实例（ADR-015），
    指标规模小，自研可保持零必需依赖且完全掌控输出格式。
    """

    def __init__(self, *, namespace: str = "dkws"):
        """初始化注册表；``namespace`` 作为所有指标名前缀。"""
        self._namespace = namespace.rstrip("_")
        self._metrics: dict[str, _Metric] = {}
        self._lock = threading.Lock()
        self._start_time = time.time()

    def _full_name(self, name: str) -> str:
        """补全命名空间前缀并校验合法性。"""
        full = name if name.startswith(f"{self._namespace}_") else f"{self._namespace}_{name}"
        if not _METRIC_NAME_RE.match(full):
            raise ValueError(f"非法指标名：{full!r}")
        return full

    def _ensure(self, name: str, kind: str, help_text: str,
                buckets: tuple[float, ...] = ()) -> _Metric:
        """获取或创建指标定义；同名不同类型时报错以防误用。"""
        full = self._full_name(name)
        metric = self._metrics.get(full)
        if metric is None:
            metric = _Metric(name=full, kind=kind, help_text=help_text,
                             buckets=buckets)
            self._metrics[full] = metric
        elif metric.kind != kind:
            raise ValueError(f"指标 {full} 已注册为 {metric.kind}，不可改为 {kind}")
        return metric

    @staticmethod
    def _key(labels: dict | None) -> tuple[tuple[str, str], ...]:
        """把标签字典规范化为可哈希且有序的键。"""
        if not labels:
            return ()
        return tuple(sorted((str(k), str(v)) for k, v in labels.items()))

    def counter(self, name: str, help_text: str = "", *, value: float = 1.0,
                labels: dict | None = None) -> None:
        """累加计数器（单调递增）。"""
        with self._lock:
            metric = self._ensure(name, "counter", help_text)
            key = self._key(labels)
            metric.values[key] = metric.values.get(key, 0.0) + float(value)

    def gauge(self, name: str, value: float, help_text: str = "", *,
              labels: dict | None = None) -> None:
        """设置瞬时值。"""
        with self._lock:
            metric = self._ensure(name, "gauge", help_text)
            metric.values[self._key(labels)] = float(value)

    def observe(self, name: str, value: float, help_text: str = "", *,
                labels: dict | None = None,
                buckets: tuple[float, ...] = DEFAULT_LATENCY_BUCKETS) -> None:
        """记录一次观测值到直方图。"""
        with self._lock:
            metric = self._ensure(name, "histogram", help_text, buckets)
            key = self._key(labels)
            entry = metric.hist.get(key)
            if entry is None:
                entry = [[0] * len(metric.buckets), 0, 0.0]
                metric.hist[key] = entry
            for idx, bound in enumerate(metric.buckets):
                if value <= bound:
                    entry[0][idx] += 1
            entry[1] += 1
            entry[2] += float(value)

    def get(self, name: str, labels: dict | None = None) -> float | None:
        """读取 counter/gauge 当前值（测试与自检用）。"""
        with self._lock:
            metric = self._metrics.get(self._full_name(name))
            if metric is None:
                return None
            return metric.values.get(self._key(labels))

    def histogram_count(self, name: str, labels: dict | None = None) -> int:
        """读取直方图样本数。"""
        with self._lock:
            metric = self._metrics.get(self._full_name(name))
            if metric is None:
                return 0
            entry = metric.hist.get(self._key(labels))
            return int(entry[1]) if entry else 0

    def names(self) -> tuple[str, ...]:
        """已注册的指标名。"""
        with self._lock:
            return tuple(sorted(self._metrics))

    def reset(self) -> None:
        """清空全部指标（仅供测试隔离使用）。"""
        with self._lock:
            self._metrics.clear()

    def uptime_seconds(self) -> float:
        """注册表存活时长，作为进程运行时长的近似。"""
        return time.time() - self._start_time

    def render(self) -> str:
        """渲染为 Prometheus 文本曝光格式（``text/plain; version=0.0.4``）。"""
        with self._lock:
            metrics = list(self._metrics.values())
        lines: list[str] = []
        for metric in sorted(metrics, key=lambda m: m.name):
            if metric.help_text:
                lines.append(f"# HELP {metric.name} {metric.help_text}")
            lines.append(f"# TYPE {metric.name} {metric.kind}")
            if metric.kind == "histogram":
                for key, (counts, total, summed) in sorted(metric.hist.items()):
                    for idx, bound in enumerate(metric.buckets):
                        label = _render_labels((*key, ("le", _format_float(bound))))
                        lines.append(f"{metric.name}_bucket{label} {counts[idx]}")
                    inf_label = _render_labels((*key, ("le", "+Inf")))
                    lines.append(f"{metric.name}_bucket{inf_label} {total}")
                    plain = _render_labels(key)
                    lines.append(f"{metric.name}_count{plain} {total}")
                    lines.append(f"{metric.name}_sum{plain} {_format_float(summed)}")
            else:
                for key, value in sorted(metric.values.items()):
                    lines.append(f"{metric.name}{_render_labels(key)} "
                                 f"{_format_float(value)}")
        return "\n".join(lines) + "\n"


def _format_float(value: float) -> str:
    """按 Prometheus 约定格式化数值（整数不带小数点）。"""
    if value == int(value) and abs(value) < 1e15:
        return str(int(value))
    return repr(float(value))


#: 进程级默认注册表
_default_registry = MetricsRegistry()


def get_metrics_registry() -> MetricsRegistry:
    """返回进程级默认指标注册表。"""
    return _default_registry


# ---------------------------------------------------------------- 追踪（可选降级）

@dataclass
class SpanRecord:
    """一个已结束的 span（内置轻量追踪的记录单元）。"""

    name: str
    trace_id: str
    span_id: str
    parent_span_id: str | None
    start_time: float
    end_time: float
    attributes: dict = field(default_factory=dict)
    status: str = "OK"

    @property
    def duration_seconds(self) -> float:
        """span 耗时。"""
        return self.end_time - self.start_time


class Tracer:
    """轻量追踪器：贯通 W3C Trace Context，可选桥接 OpenTelemetry。

    未安装 ``opentelemetry`` 时使用内置实现（仅在进程内保留最近 span 供
    自检与测试断言）；安装后可通过 :meth:`attach_otel` 桥接真实导出器。
    内置实现**不做网络导出**，因此不引入外部依赖与故障面。
    """

    def __init__(self, *, service: str = "dkws-python-core", max_spans: int = 256,
                 enabled: bool = True, sample_ratio: float = 1.0):
        """初始化追踪器；``max_spans`` 限制内存占用。"""
        self._service = service
        self._max_spans = max(1, int(max_spans))
        self._enabled = enabled
        self._sample_ratio = min(1.0, max(0.0, float(sample_ratio)))
        self._spans: list[SpanRecord] = []
        self._lock = threading.Lock()
        self._otel_tracer = None
        self._counter = 0

    @property
    def enabled(self) -> bool:
        """是否启用追踪。"""
        return self._enabled

    @property
    def otel_attached(self) -> bool:
        """是否已桥接 OpenTelemetry。"""
        return self._otel_tracer is not None

    def attach_otel(self) -> bool:
        """尝试桥接 OpenTelemetry SDK；未安装时返回 ``False`` 并保持内置实现。"""
        try:
            from opentelemetry import trace as otel_trace

            self._otel_tracer = otel_trace.get_tracer(self._service)
            return True
        except Exception:  # noqa: BLE001 - 可选依赖降级：任何失败都回落内置实现
            self._otel_tracer = None
            return False

    def should_sample(self) -> bool:
        """按采样率判定是否记录（确定性采样，避免依赖随机源）。"""
        if not self._enabled or self._sample_ratio <= 0.0:
            return False
        if self._sample_ratio >= 1.0:
            return True
        with self._lock:
            self._counter += 1
            counter = self._counter
        return (counter * self._sample_ratio) % 1.0 < self._sample_ratio

    def record_span(self, name: str, trace_id: str, span_id: str,
                    parent_span_id: str | None, start_time: float,
                    end_time: float, *, status: str = "OK", **attributes) -> SpanRecord:
        """记录一个已结束的 span。"""
        span = SpanRecord(name=name, trace_id=trace_id, span_id=span_id,
                          parent_span_id=parent_span_id, start_time=start_time,
                          end_time=end_time, status=status,
                          attributes={k: _mask_value(k, v)
                                      for k, v in attributes.items()})
        with self._lock:
            self._spans.append(span)
            if len(self._spans) > self._max_spans:
                del self._spans[:-self._max_spans]
        return span

    def recent_spans(self, limit: int = 20) -> list[SpanRecord]:
        """最近的 span（自检与测试用）。"""
        with self._lock:
            return list(self._spans[-limit:])

    def span_count(self) -> int:
        """已记录 span 总数（受 ``max_spans`` 截断）。"""
        with self._lock:
            return len(self._spans)

    def reset(self) -> None:
        """清空已记录 span（测试隔离用）。"""
        with self._lock:
            self._spans.clear()
            self._counter = 0


#: 进程级默认追踪器
_default_tracer = Tracer()


def get_tracer() -> Tracer:
    """返回进程级默认追踪器。"""
    return _default_tracer


def otel_available() -> bool:
    """检测 OpenTelemetry 是否可用（用于健康检查与降级说明）。"""
    try:
        import opentelemetry  # noqa: F401

        return True
    except Exception:  # noqa: BLE001 - 能力探测：任何导入失败均视为不可用
        return False


def prometheus_client_available() -> bool:
    """检测 prometheus_client 是否可用（本项目不依赖，仅作能力上报）。"""
    try:
        import prometheus_client  # noqa: F401

        return True
    except Exception:  # noqa: BLE001 - 能力探测：任何导入失败均视为不可用
        return False
