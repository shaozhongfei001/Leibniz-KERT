"""DSH FastAPI 子应用 — 知识服务平台 Web 界面。

API 端点前缀 /dsh/api/，静态文件 /dsh/。
从主应用 app.state 获取 KnowledgeService / SkillExecutionService 等实例。
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

_log = logging.getLogger(__name__)

_STATIC_DIR = Path(__file__).resolve().parent / "static"

router = APIRouter(prefix="/dsh")


# ──────────────────────── 仪表盘 ────────────────────────

@router.get("/api/dashboard")
async def dashboard(request: Request):
    """工作区仪表盘：状态、资产统计。"""
    svc = _get_knowledge_service(request)
    skill_svc = _get_skill_service(request)
    ws: Path = request.app.state.workspace

    stats = {
        "workspace": str(ws),
        "workspace_exists": ws.is_dir(),
        "service_id": svc.service_id if svc else None,
    }

    # 资产计数
    if svc is not None:
        try:
            version = svc._active_version()
            vdir = svc._version_dir()
            stats["data_version"] = version
            stats["projections_ready"] = True
            for name, key in [
                ("entities.parquet", "entity_count"),
                ("relations.parquet", "relation_count"),
                ("statements.parquet", "statement_count"),
                ("rules.parquet", "rule_count"),
            ]:
                p = vdir / name
                if p.is_file():
                    try:
                        import pyarrow.parquet as pq
                        stats[key] = pq.read_metadata(p).num_rows
                    except Exception:
                        stats[key] = -1
                else:
                    stats[key] = 0
        except Exception:
            stats["projections_ready"] = False
            stats["entity_count"] = 0
            stats["relation_count"] = 0
            stats["statement_count"] = 0
            stats["rule_count"] = 0
    else:
        stats["projections_ready"] = False
        stats["entity_count"] = 0
        stats["relation_count"] = 0
        stats["statement_count"] = 0
        stats["rule_count"] = 0

    # 技能统计
    if skill_svc is not None:
        try:
            reg = skill_svc.registry()
            stats["skill_count"] = len(reg)
            stats["skills"] = [
                {"skillId": s.skill_id, "name": s.name, "version": s.version}
                for s in reg
            ]
        except Exception:
            stats["skill_count"] = 0
            stats["skills"] = []
    else:
        stats["skill_count"] = 0
        stats["skills"] = []

    # 任务统计
    jobs_dir = ws / "90_control" / "jobs"
    if jobs_dir.is_dir():
        running = completed = failed = 0
        for jd in jobs_dir.iterdir():
            sf = jd / "STATUS.md"
            if sf.is_file():
                text = sf.read_text(encoding="utf-8")
                m = re.search(r'^status:\s*"?([A-Z_]+)', text, re.M)
                st = m.group(1) if m else "UNKNOWN"
                if st == "RUNNING":
                    running += 1
                elif st == "COMPLETED":
                    completed += 1
                elif st in ("FAILED", "CANCELLED", "BLOCKED"):
                    failed += 1
        stats["jobs_running"] = running
        stats["jobs_completed"] = completed
        stats["jobs_failed"] = failed
    else:
        stats["jobs_running"] = 0
        stats["jobs_completed"] = 0
        stats["jobs_failed"] = 0

    return JSONResponse(content=stats)


# ──────────────────────── 技能管理 ────────────────────────

@router.get("/api/skills")
async def list_skills(request: Request):
    """列出已注册技能。"""
    skill_svc = _get_skill_service(request)
    if skill_svc is None:
        return JSONResponse(content={"skills": []})
    reg = skill_svc.registry()
    return JSONResponse(content={
        "skills": [{"skillId": s.skill_id, "name": s.name, "version": s.version}
                   for s in reg]
    })


@router.post("/api/skills/execute")
async def execute_skill(request: Request):
    """执行技能。"""
    skill_svc = _get_skill_service(request)
    if skill_svc is None:
        raise HTTPException(status_code=503, detail="技能服务不可用")
    body = await request.json()
    skill_id = body.get("skillId", "")
    request_id = body.get("requestId")
    req_data = body.get("request", {})
    result = skill_svc.execute(skill_id, request_id, req_data)
    return JSONResponse(content=result.as_dict())


# ──────────────────────── 知识浏览 ────────────────────────

@router.get("/api/knowledge/entities")
async def list_entities(request: Request, limit: int = 50, offset: int = 0):
    """实体列表。"""
    svc = _get_knowledge_service(request)
    if svc is None:
        return JSONResponse(content={"records": [], "count": 0})
    try:
        r = svc.data_query("entities", limit=limit + offset)
        records = r.data.get("records", [])[offset:offset + limit]
        return JSONResponse(content={"records": records, "count": len(records)})
    except Exception as exc:
        return JSONResponse(content={"records": [], "count": 0, "error": str(exc)})


@router.get("/api/knowledge/relations")
async def list_relations(request: Request, limit: int = 50, offset: int = 0):
    """关系列表。"""
    svc = _get_knowledge_service(request)
    if svc is None:
        return JSONResponse(content={"records": [], "count": 0})
    try:
        r = svc.data_query("relations", limit=limit + offset)
        records = r.data.get("records", [])[offset:offset + limit]
        return JSONResponse(content={"records": records, "count": len(records)})
    except Exception as exc:
        return JSONResponse(content={"records": [], "count": 0, "error": str(exc)})


@router.get("/api/knowledge/statements")
async def list_statements(request: Request, limit: int = 50, offset: int = 0):
    """声明列表。"""
    svc = _get_knowledge_service(request)
    if svc is None:
        return JSONResponse(content={"records": [], "count": 0})
    try:
        r = svc.data_query("statements", limit=limit + offset)
        records = r.data.get("records", [])[offset:offset + limit]
        return JSONResponse(content={"records": records, "count": len(records)})
    except Exception as exc:
        return JSONResponse(content={"records": [], "count": 0, "error": str(exc)})


@router.get("/api/knowledge/rules")
async def list_rules(request: Request, limit: int = 50, offset: int = 0):
    """规则列表。"""
    svc = _get_knowledge_service(request)
    if svc is None:
        return JSONResponse(content={"records": [], "count": 0})
    try:
        r = svc.data_query("rules", limit=limit + offset)
        records = r.data.get("records", [])[offset:offset + limit]
        return JSONResponse(content={"records": records, "count": len(records)})
    except Exception as exc:
        return JSONResponse(content={"records": [], "count": 0, "error": str(exc)})


# ──────────────────────── 任务监控 ────────────────────────

@router.get("/api/jobs")
async def list_jobs(request: Request, status: str | None = None):
    """任务列表。"""
    ws: Path = request.app.state.workspace
    jobs_dir = ws / "90_control" / "jobs"
    if not jobs_dir.is_dir():
        return JSONResponse(content={"jobs": []})
    jobs = []
    for jd in sorted(jobs_dir.iterdir()):
        sf = jd / "STATUS.md"
        if not sf.is_file():
            continue
        try:
            text = sf.read_text(encoding="utf-8")
            m = re.search(r'^status:\s*"?([A-Z_]+)', text, re.M)
            st = m.group(1) if m else "UNKNOWN"
            if status and st != status:
                continue
            jobs.append({"job_id": jd.name, "status": st})
        except Exception:
            continue
    return JSONResponse(content={"jobs": jobs})


@router.get("/api/jobs/{job_id}")
async def get_job(request: Request, job_id: str):
    """任务详情。"""
    from ..application.jobs import read_job_status
    ws: Path = request.app.state.workspace
    try:
        fm = read_job_status(ws, job_id)
        return JSONResponse(content=fm)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc))


# ──────────────────────── SPA 入口（必须放最后） ────────────────────────

@router.get("/", response_class=HTMLResponse, include_in_schema=False)
async def spa_root(request: Request):
    """DSH 首页。"""
    return _serve_spa()


@router.get("/{path:path}", response_class=HTMLResponse, include_in_schema=False)
async def spa_path(request: Request, path: str = ""):
    """所有 /dsh/* 非 API/非 static 路径均返回 SPA 入口 HTML。"""
    if path.startswith("api/") or path.startswith("static/"):
        raise HTTPException(status_code=404, detail="未找到")
    return _serve_spa()


def _serve_spa() -> HTMLResponse:
    index = _STATIC_DIR / "index.html"
    if not index.is_file():
        return HTMLResponse("<h1>DSH 界面未安装</h1><p>static/index.html 不存在</p>", status_code=503)
    return HTMLResponse(content=index.read_text(encoding="utf-8"))


# ──────────────────────── 辅助 ────────────────────────

def _get_knowledge_service(request: Request):
    """从 app.state 获取 KnowledgeService。"""
    return getattr(request.app.state, "knowledge_service", None)


def _get_skill_service(request: Request):
    """从 app.state 获取 SkillExecutionService。"""
    return getattr(request.app.state, "skill_service", None)


def mount_dsh(app) -> None:
    """将 DSH 子应用挂载到主 FastAPI 应用。

    - 注册 DSH API 路由
    - 挂载静态文件目录
    - 在 app.state 上暴露 workspace / knowledge_service
    """
    app.include_router(router)
    # 暴露 workspace 供 DSH API 使用
    if not hasattr(app.state, "workspace"):
        svc = getattr(app.state, "skill_service", None)
        if svc and hasattr(svc, "workspace") and svc.workspace:
            app.state.workspace = svc.workspace
        else:
            app.state.workspace = Path(".")
    # 暴露 KnowledgeService
    if not hasattr(app.state, "knowledge_service"):
        try:
            from ..application.services import KnowledgeService
            svc = KnowledgeService(app.state.workspace)
            app.state.knowledge_service = svc
        except Exception:
            app.state.knowledge_service = None
    # 挂载静态文件
    if _STATIC_DIR.is_dir():
        app.mount("/dsh/static", StaticFiles(directory=str(_STATIC_DIR)), name="dsh-static")
    _log.info("DSH Web 界面已挂载到 /dsh/")
