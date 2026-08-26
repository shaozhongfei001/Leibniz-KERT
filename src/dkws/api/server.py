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

from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from ..application.jobs import read_job_status
from ..application.services import KnowledgeService
from ..application.skills import SkillExecutionService
from ..application import report as report_mod
from ..domain import timeutil
from ..domain.errors import DKWSException, ServiceNotReadyError

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


def create_app(workspace: Path, service_id: str = "product_knowledge",
               skill_packages: Path | None = None) -> FastAPI:
    app = FastAPI(title="DKWS Knowledge Service API",
                  description="文件目录型数据知识服务模拟平台（DKWS-SPEC-001 V1.0）",
                  version=SERVICE_VERSION)
    ws = Path(workspace)
    svc = KnowledgeService(ws, service_id=service_id)
    pkgs = Path(skill_packages) if skill_packages else (
        DEFAULT_SKILL_PACKAGES if DEFAULT_SKILL_PACKAGES.is_dir() else None)
    skill_svc = SkillExecutionService(ws, knowledge=svc, skill_packages=pkgs)

    def _handle(exc: Exception) -> HTTPException:
        if isinstance(exc, DKWSException):
            return HTTPException(status_code=exc.http_status(),
                                 detail={"error": {"code": exc.error_code,
                                                   "message": exc.message,
                                                   "retryable": exc.retryable()}})
        return HTTPException(status_code=500,
                             detail={"error": {"code": "INTERNAL_ERROR",
                                               "message": str(exc)}})

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
                          "data_version": version})

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

    return app
