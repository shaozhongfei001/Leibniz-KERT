"""M2.5 可观测性单元测试：请求上下文、结构化日志、指标注册表、追踪。"""

from __future__ import annotations

import io
import json
import logging
import threading

import pytest

from dkws.infrastructure.observability import (
    DEFAULT_LATENCY_BUCKETS,
    JsonLogFormatter,
    MetricsRegistry,
    Tracer,
    configure_structured_logging,
    current_request_id,
    current_trace_id,
    format_traceparent,
    get_metrics_registry,
    get_request_context,
    get_tracer,
    log_event,
    new_request_id,
    new_span_id,
    new_trace_id,
    otel_available,
    parse_traceparent,
    prometheus_client_available,
    redact_message,
    reset_request_context,
    set_request_context,
)

VALID_TRACE = "a" * 32
VALID_SPAN = "b" * 16


# ---------------------------------------------------------------- ID 生成

def test_trace_id_is_32_hex():
    """trace id 为 32 位十六进制（W3C 规范）。"""
    tid = new_trace_id()
    assert len(tid) == 32
    int(tid, 16)


def test_span_id_is_16_hex():
    """span id 为 16 位十六进制。"""
    sid = new_span_id()
    assert len(sid) == 16
    int(sid, 16)


def test_ids_are_unique():
    """连续生成的 ID 不重复。"""
    assert len({new_trace_id() for _ in range(50)}) == 50
    assert len({new_request_id() for _ in range(50)}) == 50


def test_request_id_has_prefix():
    """请求 ID 带 REQ- 前缀便于人工检索。"""
    assert new_request_id().startswith("REQ-")


# ---------------------------------------------------------------- traceparent

def test_parse_valid_traceparent():
    """解析合规 traceparent。"""
    assert parse_traceparent(f"00-{VALID_TRACE}-{VALID_SPAN}-01") == (VALID_TRACE,
                                                                     VALID_SPAN)


def test_parse_traceparent_case_insensitive():
    """大写十六进制被规范化为小写。"""
    header = f"00-{'A' * 32}-{'B' * 16}-01"
    assert parse_traceparent(header) == ("a" * 32, "b" * 16)


@pytest.mark.parametrize("bad", [
    None, "", "garbage", "00-tooshort-abcd-01",
    f"00-{VALID_TRACE}-{VALID_SPAN}",
    f"00-{'0' * 32}-{VALID_SPAN}-01",
    f"00-{VALID_TRACE}-{'0' * 16}-01",
    f"00-{'z' * 32}-{VALID_SPAN}-01",
])
def test_parse_invalid_traceparent_returns_none(bad):
    """畸形或全零的 traceparent 一律拒绝，避免污染链路。"""
    assert parse_traceparent(bad) is None


def test_format_traceparent_roundtrip():
    """构造的 traceparent 可被自身解析。"""
    header = format_traceparent(VALID_TRACE, VALID_SPAN)
    assert header == f"00-{VALID_TRACE}-{VALID_SPAN}-01"
    assert parse_traceparent(header) == (VALID_TRACE, VALID_SPAN)


def test_format_traceparent_unsampled():
    """未采样标志位为 00。"""
    assert format_traceparent(VALID_TRACE, VALID_SPAN, sampled=False).endswith("-00")


# ---------------------------------------------------------------- 请求上下文

def test_context_empty_by_default():
    """无上下文时读取为空字典且不报错。"""
    assert get_request_context() == {}
    assert current_request_id() is None
    assert current_trace_id() is None


def test_set_and_read_context():
    """设置后可读取。"""
    token = set_request_context(request_id="R1", trace_id=VALID_TRACE)
    try:
        assert current_request_id() == "R1"
        assert current_trace_id() == VALID_TRACE
    finally:
        reset_request_context(token)


def test_context_reset_prevents_leak():
    """复原后不残留，防止跨请求泄漏。"""
    token = set_request_context(request_id="R2")
    reset_request_context(token)
    assert current_request_id() is None


def test_context_merges_and_skips_none():
    """多次设置合并，None 值被忽略。"""
    t1 = set_request_context(request_id="R3")
    t2 = set_request_context(trace_id=VALID_TRACE, tenant_id=None)
    try:
        ctx = get_request_context()
        assert ctx["request_id"] == "R3"
        assert ctx["trace_id"] == VALID_TRACE
        assert "tenant_id" not in ctx
    finally:
        reset_request_context(t2)
        reset_request_context(t1)


def test_context_isolated_across_threads():
    """线程间上下文互不干扰。"""
    seen: dict[str, str | None] = {}

    def worker():
        """子线程读取上下文。"""
        seen["child"] = current_request_id()

    token = set_request_context(request_id="MAIN")
    try:
        t = threading.Thread(target=worker)
        t.start()
        t.join()
        assert current_request_id() == "MAIN"
        assert seen["child"] is None
    finally:
        reset_request_context(token)


# ---------------------------------------------------------------- JSON 日志

def _capture(logger_name: str = "test.obs") -> tuple[logging.Logger, io.StringIO]:
    """构造带 JSON formatter 的独立 logger 与捕获流。"""
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonLogFormatter(service="svc-test"))
    logger = logging.getLogger(logger_name)
    logger.handlers = [handler]
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    return logger, stream


def test_log_is_single_line_json():
    """日志为单行合法 JSON。"""
    logger, stream = _capture()
    logger.info("测试消息")
    lines = stream.getvalue().strip().splitlines()
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["message"] == "测试消息"
    assert payload["level"] == "INFO"
    assert payload["service"] == "svc-test"


def test_log_includes_timestamp_utc():
    """时间戳为 UTC ISO8601 带 Z 后缀。"""
    logger, stream = _capture()
    logger.info("x")
    assert json.loads(stream.getvalue())["timestamp"].endswith("Z")


def test_log_injects_request_context():
    """请求上下文自动注入日志。"""
    logger, stream = _capture()
    token = set_request_context(request_id="R9", trace_id=VALID_TRACE)
    try:
        logger.info("带上下文")
    finally:
        reset_request_context(token)
    payload = json.loads(stream.getvalue())
    assert payload["request_id"] == "R9"
    assert payload["trace_id"] == VALID_TRACE


def test_log_extra_fields_present():
    """extra 业务字段被输出。"""
    logger, stream = _capture()
    logger.info("x", extra={"skill_id": "S1", "job_id": "J1"})
    payload = json.loads(stream.getvalue())
    assert payload["skill_id"] == "S1"
    assert payload["job_id"] == "J1"


def test_log_field_order_stable():
    """关键字段按约定顺序排列，便于人工阅读与工具解析。"""
    logger, stream = _capture()
    logger.info("x", extra={"event_code": "E1", "request_id": "R1"})
    keys = list(json.loads(stream.getvalue()).keys())
    assert keys.index("timestamp") < keys.index("level")
    assert keys.index("event_code") < keys.index("request_id")


def test_log_masks_sensitive_extra_keys():
    """敏感字段名的值被脱敏。"""
    logger, stream = _capture()
    logger.info("x", extra={"password": "hunter2", "api_token": "sk-abc",
                            "client_secret": "s3cr3t"})
    payload = json.loads(stream.getvalue())
    assert payload["password"] == "***"
    assert payload["api_token"] == "***"
    assert payload["client_secret"] == "***"
    assert "hunter2" not in stream.getvalue()


def test_log_preserves_numeric_types():
    """非敏感数值保留原类型，便于指标提取。"""
    logger, stream = _capture()
    logger.info("x", extra={"duration_ms": 12.5, "status": 200, "ok": True})
    payload = json.loads(stream.getvalue())
    assert payload["duration_ms"] == 12.5
    assert payload["status"] == 200
    assert payload["ok"] is True


def test_log_redacts_message_content():
    """消息正文中的内联密钥被脱敏（M2.5 新增，堵住 stdout 通道泄漏面）。"""
    logger, stream = _capture()
    logger.info("token=abcdefghijklmnop 请求失败")
    assert "abcdefghijklmnop" not in stream.getvalue()
    assert "token=***" in stream.getvalue()


@pytest.mark.parametrize(("raw", "must_not_contain"), [
    ("token=abcdefghijklmnop", "abcdefghijklmnop"),
    ("password: hunter2xyz", "hunter2xyz"),
    ("api_key=AKIA1234567890", "AKIA1234567890"),
    ("Authorization: Bearer xyz123456", "xyz123456"),
    ("bearer abc12345678", "abc12345678"),
    ("用 sk-abcd1234efgh 调用", "sk-abcd1234efgh"),
    ("ghp_abcdefgh12345678", "ghp_abcdefgh12345678"),
])
def test_redact_message_removes_secrets(raw, must_not_contain):
    """各类密钥形态均被脱敏。"""
    assert must_not_contain not in redact_message(raw)
    assert "***" in redact_message(raw)


@pytest.mark.parametrize("benign", [
    "正常消息 count=42",
    "GET /v1/health -> 200",
    "path=/api/skill/execute",
    "duration_ms=12.5",
    "job_id=JOB-SKILL-20260827-0001",
])
def test_redact_message_preserves_benign(benign):
    """正常内容不被误伤（避免脱敏过度损害可诊断性）。"""
    assert redact_message(benign) == benign


def test_redact_message_idempotent():
    """重复脱敏结果稳定。"""
    once = redact_message("token=abcdefghijklmnop")
    assert redact_message(once) == once


def test_log_includes_exception():
    """异常堆栈被记录。"""
    logger, stream = _capture()
    try:
        raise ValueError("boom")
    except ValueError:
        logger.exception("失败")
    payload = json.loads(stream.getvalue())
    assert "ValueError" in payload["exception"]


def test_log_event_helper():
    """log_event 写入事件码与业务字段。"""
    logger, stream = _capture()
    log_event(logger, "WARNING", "TEST_CODE", "测试事件", skill_id="S2", secret="x")
    payload = json.loads(stream.getvalue())
    assert payload["event_code"] == "TEST_CODE"
    assert payload["level"] == "WARNING"
    assert payload["skill_id"] == "S2"
    assert payload["secret"] == "***"


def test_configure_structured_logging_replaces_handlers():
    """配置结构化日志后根 logger 仅保留 JSON handler。"""
    root = logging.getLogger()
    original = list(root.handlers)
    original_level = root.level
    try:
        stream = io.StringIO()
        handler = configure_structured_logging(level="DEBUG", stream=stream)
        assert root.handlers == [handler]
        logging.getLogger("x.y").info("hello")
        assert json.loads(stream.getvalue())["message"] == "hello"
    finally:
        root.handlers = original
        root.setLevel(original_level)


# ---------------------------------------------------------------- 指标注册表

@pytest.fixture()
def registry() -> MetricsRegistry:
    """独立注册表，避免测试间互相污染。"""
    return MetricsRegistry(namespace="test")


def test_counter_accumulates(registry):
    """计数器累加。"""
    registry.counter("hits", "命中数")
    registry.counter("hits", value=2.0)
    assert registry.get("hits") == 3.0


def test_counter_labels_isolated(registry):
    """不同标签独立计数。"""
    registry.counter("hits", labels={"code": "200"})
    registry.counter("hits", labels={"code": "500"})
    assert registry.get("hits", {"code": "200"}) == 1.0
    assert registry.get("hits", {"code": "500"}) == 1.0


def test_label_order_normalized(registry):
    """标签顺序不同但语义相同时视为同一序列。"""
    registry.counter("hits", labels={"a": "1", "b": "2"})
    registry.counter("hits", labels={"b": "2", "a": "1"})
    assert registry.get("hits", {"a": "1", "b": "2"}) == 2.0


def test_gauge_overwrites(registry):
    """gauge 覆盖而非累加。"""
    registry.gauge("depth", 5)
    registry.gauge("depth", 2)
    assert registry.get("depth") == 2.0


def test_histogram_buckets_cumulative(registry):
    """直方图桶为累计计数。"""
    for value in (0.001, 0.03, 0.3, 7.0):
        registry.observe("latency", value)
    assert registry.histogram_count("latency") == 4
    text = registry.render()
    assert 'test_latency_bucket{le="0.005"} 1' in text
    assert 'test_latency_bucket{le="+Inf"} 4' in text
    assert "test_latency_count 4" in text


def test_histogram_sum(registry):
    """直方图记录总和。"""
    registry.observe("latency", 0.1)
    registry.observe("latency", 0.2)
    assert "test_latency_sum 0.30000000000000004" in registry.render() or \
           "test_latency_sum 0.3" in registry.render()


def test_render_has_help_and_type(registry):
    """曝光格式含 HELP 与 TYPE 行。"""
    registry.counter("hits", "命中数")
    text = registry.render()
    assert "# HELP test_hits 命中数" in text
    assert "# TYPE test_hits counter" in text


def test_render_ends_with_newline(registry):
    """曝光文本以换行结尾（Prometheus 要求）。"""
    registry.counter("hits")
    assert registry.render().endswith("\n")


def test_namespace_prefix_applied(registry):
    """指标名自动加命名空间前缀且不重复添加。"""
    registry.counter("hits")
    registry.counter("test_other")
    assert set(registry.names()) == {"test_hits", "test_other"}


def test_illegal_metric_name_rejected(registry):
    """非法指标名被拒绝。"""
    with pytest.raises(ValueError, match="非法指标名"):
        registry.counter("bad-name!")


def test_type_conflict_rejected(registry):
    """同名指标不可改变类型。"""
    registry.counter("x")
    with pytest.raises(ValueError, match="不可改为"):
        registry.gauge("x", 1)


def test_label_values_escaped(registry):
    """标签值中的引号与反斜杠被转义。"""
    registry.counter("hits", labels={"path": 'a"b\\c'})
    assert 'path="a\\"b\\\\c"' in registry.render()


def test_integers_render_without_decimal(registry):
    """整数值不带小数点。"""
    registry.gauge("depth", 3.0)
    assert "test_depth 3\n" in registry.render()


def test_missing_metric_returns_none(registry):
    """未注册指标读取返回 None。"""
    assert registry.get("absent") is None
    assert registry.histogram_count("absent") == 0


def test_reset_clears_all(registry):
    """reset 清空注册表。"""
    registry.counter("hits")
    registry.reset()
    assert registry.names() == ()


def test_uptime_is_positive(registry):
    """存活时长为正。"""
    assert registry.uptime_seconds() >= 0


def test_default_buckets_ascending():
    """默认分桶单调递增。"""
    assert list(DEFAULT_LATENCY_BUCKETS) == sorted(DEFAULT_LATENCY_BUCKETS)


def test_concurrent_counter_is_thread_safe(registry):
    """并发计数不丢样本。"""
    def bump():
        """并发累加。"""
        for _ in range(200):
            registry.counter("hits")

    threads = [threading.Thread(target=bump) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert registry.get("hits") == 1600.0


def test_default_registry_is_singleton():
    """进程级注册表为单例。"""
    assert get_metrics_registry() is get_metrics_registry()


# ---------------------------------------------------------------- 追踪

def test_tracer_records_span():
    """记录 span 并可读回。"""
    tracer = Tracer(max_spans=10)
    tracer.record_span("op", VALID_TRACE, VALID_SPAN, None, 1.0, 1.5,
                       http_status=200)
    spans = tracer.recent_spans()
    assert len(spans) == 1
    assert spans[0].name == "op"
    assert spans[0].duration_seconds == pytest.approx(0.5)
    assert spans[0].attributes["http_status"] == 200


def test_tracer_masks_span_attributes():
    """span 属性同样脱敏。"""
    tracer = Tracer()
    tracer.record_span("op", VALID_TRACE, VALID_SPAN, None, 1.0, 1.1,
                       password="hunter2")
    assert tracer.recent_spans()[0].attributes["password"] == "***"


def test_tracer_bounded_by_max_spans():
    """span 数量受上限约束，防止内存无界增长。"""
    tracer = Tracer(max_spans=5)
    for i in range(20):
        tracer.record_span(f"op{i}", VALID_TRACE, new_span_id(), None, 0.0, 0.1)
    assert tracer.span_count() == 5
    assert tracer.recent_spans()[-1].name == "op19"


def test_tracer_sampling_full():
    """采样率 1.0 时全部采样。"""
    tracer = Tracer(sample_ratio=1.0)
    assert all(tracer.should_sample() for _ in range(10))


def test_tracer_sampling_zero():
    """采样率 0.0 时不采样。"""
    tracer = Tracer(sample_ratio=0.0)
    assert not any(tracer.should_sample() for _ in range(10))


def test_tracer_disabled_never_samples():
    """禁用追踪时不采样。"""
    assert Tracer(enabled=False).should_sample() is False


def test_tracer_partial_sampling_reduces_volume():
    """部分采样时采样数少于总数。"""
    tracer = Tracer(sample_ratio=0.3)
    sampled = sum(1 for _ in range(100) if tracer.should_sample())
    assert 0 < sampled < 100


def test_tracer_reset():
    """reset 清空 span。"""
    tracer = Tracer()
    tracer.record_span("op", VALID_TRACE, VALID_SPAN, None, 0.0, 0.1)
    tracer.reset()
    assert tracer.span_count() == 0


def test_tracer_records_parent_span():
    """父 span 被保留，实现链路串联。"""
    tracer = Tracer()
    tracer.record_span("child", VALID_TRACE, new_span_id(), VALID_SPAN, 0.0, 0.1)
    assert tracer.recent_spans()[0].parent_span_id == VALID_SPAN


def test_tracer_error_status():
    """可记录错误状态。"""
    tracer = Tracer()
    tracer.record_span("op", VALID_TRACE, VALID_SPAN, None, 0.0, 0.1, status="ERROR")
    assert tracer.recent_spans()[0].status == "ERROR"


def test_attach_otel_degrades_gracefully():
    """OTel 未安装时降级为内置实现且不抛异常。"""
    tracer = Tracer()
    attached = tracer.attach_otel()
    assert attached == tracer.otel_attached
    assert isinstance(attached, bool)


def test_capability_probes_return_bool():
    """可选依赖探测返回布尔值，不抛异常。"""
    assert isinstance(otel_available(), bool)
    assert isinstance(prometheus_client_available(), bool)


def test_default_tracer_is_singleton():
    """进程级追踪器为单例。"""
    assert get_tracer() is get_tracer()
