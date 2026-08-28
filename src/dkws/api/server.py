"""HTTP API（规格 §13，可选实现；仅做协议适配，不复制业务逻辑）。

端点：
GET  /v1/health
POST /v1/extractions             （写 Work，202 Accepted）
GET  /v1/jobs/{job_id}
GET  /v1/extractions/{job_id}/result
GET  /v1/entities/{entity_id}
POST /v1/data/query
POST /v1/search
POST /v1/graph/query
POST /v1/rules/evaluate
GET  /v1/evidence/{object_id}
GET  /v1/catalog

发布/审核/回滚不暴露为远程 API（§13.1）。
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi import Response as FastApiResponse
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from ..application import report as report_mod
from ..application.jobs import read_job_status
from ..application.services import KnowledgeService
from ..application.skills import SkillExecutionService
from ..domain import timeutil
from ..domain.errors import DKWSException, ServiceNotReadyError
from ..infrastructure.observability import (
    configure_structured_logging,
    get_metrics_registry,
    get_tracer,
    log_event,
    otel_available,
    prometheus_client_available,
)
from ..infrastructure.runtime_config import (
    SCOPE_ADMIN,
    RuntimeConfig,
    load_runtime_config,
)
from ..infrastructure.runtime_store import RuntimeStore
from .middleware import (
    ApiKeyAuthMiddleware,
    ConcurrencyLimitMiddleware,
    ObservabilityMiddleware,
    RateLimitMiddleware,
    ResponseRedactionMiddleware,
    SizeLimitMiddleware,
)

SERVICE_VERSION = "1.0.0"

# 外部 Skill 包默认目录（dkws/examples/bank-front-skills/）
DEFAULT_SKILL_PACKAGES = Path(__file__).resolve().parents[3] / "examples" / "bank-front-skills"


class SkillExecuteRequest(BaseModel):
    skillId: str
    requestId: str | None = None
    request: dict = Field(default_factory=dict)
    # v1.4：ContextPackage（顶层或 request.context 二选一）+ 异步模式
    context: dict | None = None
    async_run: bool | None = Field(default=None, alias="async")


class GateAuditRequest(BaseModel):
    customerId: str
    gate: str
    decision: str
    decidedBy: str
    reason: str = ""


class ExtractionRequest(BaseModel):
    request_id: str
    idempotency_key: str
    domain: str
    input: dict
    extraction_types: list[str] = ["ENTITY", "RELATION", "STATEMENT", "RULE"]
    schema_versions: list[str] | None = None
    options: dict = Field(default_factory=dict)


class DataQueryRequest(BaseModel):
    request_id: str
    dataset: str
    select: list[str] | None = None
    where: dict | None = None
    limit: int = 100


class SearchRequest(BaseModel):
    request_id: str
    query: str
    mode: str = "FULLTEXT"
    top_k: int = 10
    filters: dict | None = None


class GraphRequest(BaseModel):
    request_id: str
    start_entity_ids: list[str]
    relation_types: list[str] | None = None
    direction: str = "OUT"
    max_depth: int = 1
    max_nodes: int = 100
    mode: str = "neighbor"  # neighbor | closure | paths（Kùzu 后端）
    service: str = "product_knowledge"  # 服务 ID（如 supply_chain_graph）
    as_of: str | None = None


class RuleRequest(BaseModel):
    request_id: str
    rule_set: str | None = None
    facts: dict


def _response(request_id: str, data: dict, meta: dict | None = None) -> dict:
    return {
        "request_id": request_id,
        "status": "OK",
        "data": data,
        "errors": [],
        "meta": meta or {"service_version": SERVICE_VERSION,
                         "data_version": "active",
                         "generated_at": timeutil.ts_utc()},
    }


def _install_hardening(app: FastAPI, cfg: RuntimeConfig) -> None:
    """按外→内顺序注册 M2.1/M2.2 加固与 M2.5 可观测性中间件。

    Starlette 的 ``add_middleware`` 为栈式注册（后加先执行），因此这里
    的调用顺序与实际执行顺序相反。实际执行顺序为：

    可观测性 → 响应脱敏 → 大小限制 → 并发限制 → 限流 → 认证 → 路由

    - 可观测性置于**最外层**，因此被限流/认证拦截的请求同样产生指标与日志，
      使可观测性不留盲区（4xx 拒绝也可观测）。
    - 响应脱敏（M2.9）紧随其后：需在响应体最终成型后处理，
      且脱敏动作本身应被可观测（其日志由外层中间件的上下文覆盖）。
    - 限流置于认证之前，使未认证的洪水请求同样受限；限流中间件自行识别
      API Key 以保持按 Key 分桶（见 :class:`RateLimitMiddleware`）。

    Args:
        app: FastAPI 应用。
        cfg: 运行时配置。
    """
    app.add_middleware(ApiKeyAuthMiddleware, config=cfg.auth)
    app.add_middleware(RateLimitMiddleware, config=cfg.rate_limit, auth_config=cfg.auth)
    app.add_middleware(ConcurrencyLimitMiddleware, config=cfg.concurrency)
    app.add_middleware(SizeLimitMiddleware, config=cfg.size_limit)
    app.add_middleware(ResponseRedactionMiddleware, config=cfg.redaction)
    app.add_middleware(ObservabilityMiddleware, config=cfg.observability)


def create_app(workspace: Path, service_id: str = "product_knowledge",
               skill_packages: Path | None = None,
               runtime_config: RuntimeConfig | None = None) -> FastAPI:
    """创建 DKWS HTTP 应用。

    Args:
        workspace: DKWS 工作区根目录。
        service_id: 默认服务 ID。
        skill_packages: 外部 Skill 包目录；``None`` 时使用内置示例目录。
        runtime_config: 运行时配置；``None`` 时从环境变量/配置文件装载
            （生产 profile 缺少安全控制会 fail-fast）。

    Returns:
        已注册路由与加固中间件的 FastAPI 应用。
    """
    cfg = runtime_config or load_runtime_config()
    # M2.5：结构化日志需在任何日志产生前配置
    if cfg.observability.structured_logs:
        configure_structured_logging(level=cfg.observability.log_level,
                                     service=cfg.observability.service_name)
    registry = get_metrics_registry()
    tracer = get_tracer()
    if cfg.observability.otel_enabled:
        tracer.attach_otel()

    app = FastAPI(title="DKWS Knowledge Service API",
                  description="文件目录型数据知识服务模拟平台（DKWS-SPEC-001 V1.0）",
                  version=SERVICE_VERSION)
    ws = Path(workspace)
    svc = KnowledgeService(ws, service_id=service_id)
    pkgs = Path(skill_packages) if skill_packages else (
        DEFAULT_SKILL_PACKAGES if DEFAULT_SKILL_PACKAGES.is_dir() else None)
    store: RuntimeStore | None = None
    if cfg.runtime_store.enabled:
        store = RuntimeStore(
            cfg.runtime_store.resolve_path(ws),
            wal=cfg.runtime_store.wal,
            busy_timeout_ms=cfg.runtime_store.busy_timeout_ms,
            idempotency_ttl_seconds=cfg.runtime_store.idempotency_ttl_seconds)
        # M2.4：改用 lease 感知的回收，仅处理 lease 已过期者。
        # 原 recover_stale_jobs 会无条件复位所有 RUNNING，在 Worker 与 API
        # 并存时会误抢正在被 Worker 正常处理的 Job（已标记 deprecated）。
        store.reclaim_expired_leases()
    skill_svc = SkillExecutionService(ws, knowledge=svc, skill_packages=pkgs,
                                     runtime_store=store, profile=cfg.profile,
                                     llm_redaction=cfg.redaction.llm_enabled)
    app.state.runtime_config = cfg
    app.state.runtime_store = store
    # 暴露 Service 便于运维自检与测试断言（M2-P2 Owner 决策 3 的校验链路）
    app.state.skill_service = skill_svc
    app.state.metrics_registry = registry
    app.state.tracer = tracer
    app.state.observability_capabilities = {
        "otel_available": otel_available(),
        "otel_attached": tracer.otel_attached,
        "prometheus_client_available": prometheus_client_available(),
    }
    _install_hardening(app, cfg)

    def _handle(exc: Exception) -> HTTPException:
        if isinstance(exc, DKWSException):
            return HTTPException(status_code=exc.http_status(),
                                 detail={"error": {"code": exc.error_code,
                                                   "message": exc.message,
                                                   "retryable": exc.retryable()}})
        return HTTPException(status_code=500,
                             detail={"error": {"code": "INTERNAL_ERROR",
                                               "message": str(exc)}})

    @app.get("/livez")
    def livez():
        """存活探针：进程是否活着。

        **不检查任何外部依赖**——存活探针一旦失败通常触发重启，
        若把依赖故障计入存活，会导致依赖抖动时无谓地重启本服务。
        依赖健康归 ``/readyz`` 负责。

        故意不使用 :func:`_response` 信封：探针需裸响应与真实 HTTP 状态码，
        便于 Kubernetes / systemd / 负载均衡器直接判定。
        """
        return {"status": "alive", "service": cfg.observability.service_name,
                "service_version": SERVICE_VERSION,
                "uptime_seconds": round(registry.uptime_seconds(), 3)}

    @app.get("/readyz")
    def readyz(response: FastApiResponse):
        """就绪探针：能否正常承接业务流量。

        检查项及其严重级别：

        | 检查项 | 未通过后果 |
        |---|---|
        | 工作区存在且可写 | **not ready**（无法写审计与产物） |
        | Runtime Store 可连接 | 取决于 ``readiness_require_store`` |
        | 知识投影可读 | 仅 degraded，**不阻断** |
        | 队列积压（过期 lease） | 仅 degraded，不阻断 |

        知识投影**不作硬性条件**：全新部署尚未发布投影时若判为未就绪，
        实例将永远无法进入服务状态；且部分只读能力（健康、目录）此时仍可用。
        投影缺失通过 ``degraded`` 标记与 ``/v1/health`` 的 ``DEGRADED`` 暴露。

        未就绪返回 **503**，使负载均衡器摘除本实例而不重启进程。
        """
        checks: dict[str, dict] = {}
        ready = True
        degraded: list[str] = []

        try:
            writable = ws.is_dir() and os.access(ws, os.W_OK)
            checks["workspace"] = {"ok": bool(writable), "path": str(ws)}
            ready = ready and bool(writable)
        except OSError as exc:
            checks["workspace"] = {"ok": False, "error": str(exc)}
            ready = False

        try:
            checks["knowledge_projection"] = {"ok": True, "version": svc._active_version()}
        except ServiceNotReadyError as exc:
            # 投影缺失不阻断就绪（见上表说明），仅标记 degraded
            checks["knowledge_projection"] = {"ok": False, "error": str(exc),
                                              "blocking": False}
            degraded.append("knowledge_projection")

        if store is not None:
            try:
                checks["runtime_store"] = {"ok": True,
                                           "schema_version": store.schema_version(),
                                           "journal_mode": store.journal_mode()}
            except Exception as exc:  # noqa: BLE001 - 探针需兜住任何 DB 异常
                checks["runtime_store"] = {"ok": False, "error": str(exc)}
                if cfg.observability.readiness_require_store:
                    ready = False
                else:
                    degraded.append("runtime_store")
            try:
                stats = store.queue_stats()
                checks["job_queue"] = {"ok": True, "claimable": stats["claimable"],
                                       "dead_letter": stats["dead_letter"],
                                       "expired_leases": stats["expired_leases"]}
                if stats["expired_leases"] > 0:
                    degraded.append("job_queue_expired_leases")
            except Exception as exc:  # noqa: BLE001 - 队列统计失败不阻断就绪
                checks["job_queue"] = {"ok": False, "error": str(exc)}
                degraded.append("job_queue")
        else:
            checks["runtime_store"] = {"ok": True, "enabled": False,
                                       "note": "未启用运行态持久化（dev 可接受）"}

        registry.gauge("readiness", 1.0 if ready else 0.0,
                       "服务是否就绪（1=就绪，0=未就绪）")
        response.status_code = 200 if ready else 503
        return {"status": "ready" if ready else "not_ready",
                "degraded": degraded, "checks": checks}

    @app.get("/metrics")
    def metrics(request: Request, response: FastApiResponse):
        """Prometheus 文本格式指标端点。

        安全考量：指标含队列深度、DB schema 版本等内部信息。
        ``metrics_require_admin=true`` 时要求 admin 作用域；否则依赖网络层
        限制采集来源（生产建议二者至少其一，见部署文档）。

        故意不使用 :func:`_response` 信封：Prometheus 需要
        ``text/plain`` 曝光格式。
        """
        if not cfg.observability.metrics_enabled:
            response.status_code = 404
            return PlainTextResponse("指标端点未启用\n", status_code=404)
        if cfg.observability.metrics_require_admin:
            # BaseHTTPMiddleware 每层各有独立 Request，故身份经 ASGI scope 传递
            scopes = (request.scope.get("api_key_scopes")
                      or request.state.__dict__.get("api_key_scopes") or ())
            if SCOPE_ADMIN not in tuple(scopes):
                return PlainTextResponse(
                    "指标端点要求 admin 作用域\n", status_code=403)

        # 采集时刷新运行态派生指标，避免额外后台线程
        if store is not None:
            try:
                stats = store.queue_stats()
                registry.gauge("job_queue_claimable", stats["claimable"],
                               "可领取的 Job 数")
                registry.gauge("job_queue_dead_letter", stats["dead_letter"],
                               "进入 dead-letter 的 Job 数")
                registry.gauge("job_queue_expired_leases", stats["expired_leases"],
                               "lease 已过期待回收的 Job 数")
                for status_name, count in (stats.get("by_status") or {}).items():
                    registry.gauge("job_status_count", count,
                                   "各状态 Job 数", labels={"status": status_name})
            except Exception:  # noqa: BLE001 - 指标采集失败不应影响端点可用
                registry.counter("metrics_collection_errors_total",
                                 "指标采集失败次数")
        registry.gauge("process_uptime_seconds", registry.uptime_seconds(),
                       "进程运行时长（秒）")
        registry.gauge("build_info", 1.0, "构建信息",
                       labels={"version": SERVICE_VERSION, "profile": cfg.profile})
        return PlainTextResponse(registry.render(),
                                 media_type="text/plain; version=0.0.4; charset=utf-8")

    @app.get("/v1/health")
    def health():
        try:
            version = svc._active_version()
            status = "OK"
        except ServiceNotReadyError:
            version = None
            status = "DEGRADED"
        return _response(f"REQ-H-{timeutil.ts_utc()[:19]}",
                         {"status": status, "service_version": SERVICE_VERSION,
                          "data_version": version,
                          "runtime": {
                              "profile": cfg.profile,
                              "auth_enabled": cfg.auth.enabled,
                              "rate_limit_enabled": cfg.rate_limit.enabled,
                              "size_limit_enabled": cfg.size_limit.enabled,
                              "concurrency_enabled": cfg.concurrency.enabled,
                              "runtime_store_enabled": store is not None,
                              "schema_version": (store.schema_version()
                                                 if store is not None else None),
                              "warnings": list(cfg.warnings),
                          }})

    @app.post("/v1/extractions", status_code=202)
    def extract(req: ExtractionRequest):
        import re as _re

        from ..application.extract import KnowledgeExtractor

        try:
            extractor = KnowledgeExtractor(ws)
            path = req.input.get("path", "")
            if not path:
                raise DKWSException("input.path 必填")
            m = _re.search(r"batch=([A-Z][A-Z0-9_-]+)", path)
            if not m:
                raise DKWSException("无法从 path 解析 batch_id")
            batch_id = m.group(1)
            run = extractor._latest_parse_run(req.domain)
            result = extractor.extract(req.domain, batch_id, run_id=run)
            return {
                "request_id": req.request_id,
                "status": "ACCEPTED",
                "data": {"job_id": result.job_id,
                         "result_status": "CANDIDATE",
                         "publish_status": "NOT_PUBLISHED"},
                "errors": [],
                "meta": {"service_version": SERVICE_VERSION,
                         "data_version": "work",
                         "generated_at": timeutil.ts_utc()},
            }
        except DKWSException as exc:
            raise _handle(exc)

    @app.get("/v1/jobs/{job_id}")
    def job(job_id: str):
        try:
            fm = read_job_status(ws, job_id)
            return _response(f"REQ-JOB-{job_id}", fm)
        except DKWSException as exc:
            raise _handle(exc)

    @app.get("/v1/extractions/{job_id}/result")
    def extraction_result(job_id: str):
        try:
            fm = read_job_status(ws, job_id)
            return _response(f"REQ-EXT-R-{job_id}", {
                "job_id": job_id, "status": fm.get("status"),
                "publish_status": fm.get("publish_status"),
                "output_refs": fm.get("output_refs", []),
            })
        except DKWSException as exc:
            raise _handle(exc)

    @app.get("/v1/entities/{entity_id}")
    def entity(entity_id: str, as_of: str | None = None):
        try:
            r = svc.get_entity(entity_id, as_of=as_of)
            return _response(f"REQ-E-{entity_id}", r.data, r.meta)
        except DKWSException as exc:
            raise _handle(exc)

    @app.post("/v1/data/query")
    def data_query(req: DataQueryRequest):
        try:
            r = svc.data_query(req.dataset, select=req.select, where=req.where,
                               limit=req.limit)
            return _response(req.request_id, r.data, r.meta)
        except DKWSException as exc:
            raise _handle(exc)

    @app.post("/v1/search")
    def search(req: SearchRequest):
        try:
            r = svc.search(req.query, mode=req.mode, top_k=req.top_k,
                           filters=req.filters)
            return _response(req.request_id, r.data, r.meta)
        except DKWSException as exc:
            raise _handle(exc)

    @app.post("/v1/graph/query")
    def graph(req: GraphRequest):
        try:
            from ..application.services import KnowledgeService

            target = KnowledgeService(ws, service_id=req.service)
            r = target.graph(req.start_entity_ids, relation_types=req.relation_types,
                             direction=req.direction, max_depth=req.max_depth,
                             max_nodes=req.max_nodes, mode=req.mode)
            return _response(req.request_id, r.data, r.meta)
        except DKWSException as exc:
            raise _handle(exc)

    @app.post("/v1/rules/evaluate")
    def rules(req: RuleRequest):
        try:
            r = svc.evaluate_rule(req.rule_set, facts=req.facts)
            return _response(req.request_id, r.data, r.meta)
        except DKWSException as exc:
            raise _handle(exc)

    @app.get("/v1/evidence/{object_id}")
    def evidence(object_id: str):
        try:
            r = svc.trace(object_id)
            if store is not None:
                try:
                    refs = r.data.get("evidence_refs") or r.data.get("evidenceRefs") or []
                    first = refs[0] if refs else {}
                    ref_id = (first.get("evidence_id") or first.get("evidenceId")
                              if isinstance(first, dict) else str(first)) or object_id
                    store.record_evidence(object_id, str(ref_id),
                                          source_ref="GET /v1/evidence",
                                          detail={"ref_count": len(refs)})
                except Exception as exc:  # noqa: BLE001 - 审计镜像失败不阻断主流程
                    # M2.5：原为静默 pass，现补日志与指标使失败可观测
                    registry.counter("evidence_audit_errors_total",
                                     "evidence 审计镜像写入失败次数")
                    log_event(logging.getLogger("dkws.api"), "WARNING",
                              "EVIDENCE_AUDIT_FAILED",
                              "evidence 审计镜像写入失败（不影响查询结果）",
                              object_id=object_id, error=str(exc))
            return _response(f"REQ-EV-{object_id}", r.data, r.meta)
        except DKWSException as exc:
            raise _handle(exc)

    @app.get("/v1/catalog")
    def catalog():
        try:
            version = svc._active_version()
            vdir = svc._version_dir()
            files = sorted(f.relative_to(vdir).as_posix()
                           for f in vdir.rglob("*.parquet"))
            return _response(f"REQ-CAT-{timeutil.ts_utc()[:19]}", {
                "service_id": service_id, "version": version, "projections": files,
            })
        except DKWSException as exc:
            raise _handle(exc)

    # ================= 客户经理持续经营 Skill 平台（/api/skill/*）=================

    @app.get("/api/skill/health")
    def skill_health():
        """D1：列出已注册 skill 及版本。"""
        return {
            "status": "ok",
            "service": "customer-engagement",
            "skills": [{"skillId": s.skill_id, "name": s.name, "version": s.version}
                       for s in skill_svc.registry()],
        }

    @app.post("/api/skill/execute")
    def skill_execute(req: SkillExecuteRequest):
        """D2-D6 + v1.4：执行一个 skill（幂等 / fail-closed / 无新证据策略 / 异步 / ContextPackage）。"""
        import json as _json

        from fastapi import Response

        if req.context is not None:
            req.request.setdefault("context", req.context)
        if req.async_run:
            # v1.4 异步：SP-20 长任务 → 202 {jobId}，轮询 GET /v1/jobs/{jobId}
            job_id = skill_svc.execute_async(req.skillId, req.requestId, req.request)
            return Response(content=_json.dumps({"jobId": job_id, "status": "PENDING"},
                                                ensure_ascii=False),
                            status_code=202, media_type="application/json")
        result = skill_svc.execute(req.skillId, req.requestId, req.request)
        payload = result.as_dict()
        if isinstance(payload.get("data"), dict):
            payload["data"].setdefault(
                "reportUrl", f"/api/skill/report/{payload.get('requestId', '')}")
        unknown = result.status == "skill_error" and any(
            e.get("code") == "UNKNOWN_SKILL" for e in result.errors)
        return Response(content=_json.dumps(payload, ensure_ascii=False),
                        status_code=404 if unknown else 200,
                        media_type="application/json")

    @app.get("/api/skill/report/{request_id}")
    def skill_report(request_id: str):
        """执行结果的可视化报告页（供应链图谱 Skill 用定制模板，其余用 JSON 兜底）。

        结果取自执行幂等缓存（TTL 约 10 分钟），过期返回 404。
        """
        from fastapi.responses import HTMLResponse

        hit = skill_svc.get_result(request_id)
        if hit is None:
            raise HTTPException(
                status_code=404,
                detail="报告不存在或已过期（执行结果仅缓存 10 分钟，请重新执行）")
        return HTMLResponse(content=report_mod.render_report(hit))

    @app.get("/api/skill/gates/{customer_id}")
    def skill_gates(customer_id: str):
        """Phase 2：GATE-BIZ-* 闸门清单资产（权威清单，推进权威在 GITS）。"""
        return {"customerId": customer_id, "gates": skill_svc.sp20_gate_checklist(customer_id)}

    @app.post("/api/skill/gates/audit")
    def skill_gates_audit(req: GateAuditRequest):
        """Phase 2：业务闸门决策镜像（非权威；权威在 GITS，DKWS 仅追加审计日志）。"""
        try:
            rec = skill_svc.record_gate_audit(req.customerId, req.gate, req.decision,
                                              req.decidedBy, req.reason)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return rec

    # ── DSH Web 界面 ──
    from ..dsh.app import mount_dsh
    app.state.workspace = ws
    app.state.knowledge_service = svc
    mount_dsh(app)

    return app
