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
GET  /v1/knowledge-maps            （v1.5：知识地图注册查询）
GET  /v1/knowledge-maps/{map_id}   （v1.5：单张地图详情）
POST /v1/routing/plan              （v1.5：路由裁决 + 激活计划，fail-closed）
GET  /v1/analytics/dimensions      （CCRM-BA：分析维度与成员）
GET  /v1/analytics/orgs            （CCRM-BA：机构树）
GET  /v1/analytics/periods         （CCRM-BA：可用期间）
GET  /v1/analytics/screens         （CCRM-BA：10 个分析屏注册表）
GET  /v1/analytics/params          （CCRM-BA：生效口径参数）
GET  /v1/analytics/metrics         （CCRM-BA：按屏/维度/机构/期间聚合指标）
GET  /v1/analytics/trend           （CCRM-BA：单一成员 12 个月趋势）
POST /v1/analytics/combo-query     （CCRM-BA：客户级多条件圈选）

发布/审核/回滚不暴露为远程 API（§13.1）。
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi import Response as FastApiResponse
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, ConfigDict, Field

from ..application import report as report_mod
from ..application.jobs import read_job_status
from ..application.services import KnowledgeService
from ..application.skills import SkillExecutionService
from ..domain import timeutil
from ..domain.activation_plan import ActivationPlanBuilder, PlanDenial
from ..domain.errors import KERTException, ServiceNotReadyError
from ..domain.health import HEALTH_OK
from ..domain.knowledge_map import KnowledgeMapRegistry
from ..domain.query_modes import (
    DIRECTION_OUT,
    GRAPH_MODE_NEIGHBOR,
    SEARCH_MODE_FULLTEXT,
)
from ..domain.route_policy import load_route_policy
from ..domain.skill_status import SKILL_ERROR
from ..infrastructure.observability import (
    configure_structured_logging,
    get_metrics_registry,
    get_tracer,
    log_event,
    new_request_id,
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
    STATE_REQUEST_ID,
    ApiKeyAuthMiddleware,
    ConcurrencyLimitMiddleware,
    ObservabilityMiddleware,
    RateLimitMiddleware,
    ResponseRedactionMiddleware,
    SizeLimitMiddleware,
)

SERVICE_VERSION = "1.0.0"

_log = logging.getLogger(__name__)

# 外部 Skill 包默认目录（kert/examples/bank-front-skills/）。
#
# ⚠ 该默认值依赖「源码检出」布局：只有本模块位于 <repo>/src/kert/api/ 时 parents[3]
# 才是仓库根。在 site-packages（非 editable 安装）或容器镜像里它会落到仓外，从而命中
# 不到任何技能包 —— 而原实现以 pkgs=None **静默降级**，表现为运行时 UNKNOWN_SKILL 且
# 无任何日志线索（CI run 34845070952 的 10 条失败即此，
# 见 evidence/kert-e2e-ci/TASK_PACKAGE_D-E2E-01.md）。故：
#   - 生产/CI 必须用 KERT_SKILL_PACKAGES 显式指定；
#   - 显式配置无效 → 启动即失败（fail-closed），不得静默降级。
DEFAULT_SKILL_PACKAGES = Path(__file__).resolve().parents[3] / "examples" / "bank-front-skills"

#: 显式指定外部 Skill 包根目录的环境变量（优先级高于内置默认）。
SKILL_PACKAGES_ENV = "KERT_SKILL_PACKAGES"

#: CCRM-BA 落地（2026-09-22）：对公经营分析 DuckDB 路径。
#: 显式设置且库文件缺失 ⇒ 启动即失败（fail-closed，与 SKILL_PACKAGES 同纪律）；
#: 未设置 ⇒ 分析能力不接入（不影响既有技能注册表与测试）。
ANALYTICS_DUCKDB_ENV = "KERT_ANALYTICS_DUCKDB"

#: 4 个数据分析 Skill 包目录（bank-front-operating-metrics 等，确定性执行器）。
ANALYTICS_SKILL_PACKAGES = (Path(__file__).resolve().parents[3] / "examples"
                            / "bank-front-analytics" / "skills")

#: D-3：内部错误对外的**通用**文案（**唯一来源**，所有 5xx 兜底路径共用）。
#: 与 `str(exc)` 无关 —— 响应体不得随异常内容变化（安全口径），异常细节只进服务端日志。
INTERNAL_ERROR_MESSAGE = "内部错误"

#: D-3：就绪探针检查项失败时对外的固定值（`/readyz` 属 `DEFAULT_EXEMPT_PATHS` ⇒ **公开**）。
#: 具体异常（可能含路径等内部信息）只进日志，**不回显**。
READINESS_ERROR = "unavailable"


def _internal_error_http_exception(exc: Exception) -> HTTPException:
    """非领域异常 ⇒ **通用** 500（``INTERNAL_ERROR`` + ``INTERNAL_ERROR_MESSAGE``）。

    D-3（异常口径对齐）：本函数与 app 级 :func:`_unhandled_exception` 同口径 ——
    非 KERT 异常**不回显** ``str(exc)``/异常类名；异常**类型与消息**写入服务端日志
    （``exc_info`` 带栈），保证"响应不泄露"不等于"排障靠猜"。

    状态码（500）与响应体形状（``{"error": {"code", "message"}}``）与 D-3 之前**一致**，
    只把 ``message`` 由 ``str(exc)`` 换成通用文案。
    """
    _log.error("非 KERT 异常已转为 500（不回显异常内容）：type=%s message=%s",
               type(exc).__name__, exc, exc_info=(type(exc), exc, exc.__traceback__))
    return HTTPException(status_code=500,
                         detail={"error": {"code": "INTERNAL_ERROR",
                                           "message": INTERNAL_ERROR_MESSAGE}})


def _readiness_check_error(check: str, exc: Exception) -> str:
    """就绪检查失败 ⇒ 返回**固定**错误值，并把异常类型/消息写入日志（D-3）。

    ``/readyz`` 是公开探测端点（在 ``DEFAULT_EXEMPT_PATHS`` 内），此前把 ``str(exc)``
    （数据库/文件系统异常常含**内部路径**）直接放进响应体 ⇒ 公开端点泄露内部信息。
    响应体形状不变（仍是字符串值），只换成固定值 :data:`READINESS_ERROR`。
    """
    _log.warning("就绪检查失败（细节仅进日志）：check=%s type=%s message=%s",
                 check, type(exc).__name__, exc, exc_info=(type(exc), exc, exc.__traceback__))
    return READINESS_ERROR


def _has_skill_packages(path: Path) -> bool:
    """``path`` 是目录，且至少含一个 ``<skill>/SKILL.md``。"""
    try:
        if not path.is_dir():
            return False
        return any((child / "SKILL.md").is_file()
                   for child in path.iterdir() if child.is_dir())
    except OSError:
        return False


def resolve_skill_packages(explicit: Path | str | None = None) -> Path | None:
    """解析外部 Skill 包根目录（fail-closed）。

    优先级：``explicit`` > ``KERT_SKILL_PACKAGES`` > 内置默认（源码布局）。

    Returns:
        有效目录；未显式配置且默认不可用时返回 ``None``。

    Raises:
        ValueError: **显式配置**（入参或环境变量）但目标无效（不存在，或其中没有任何
            ``<skill>/SKILL.md``）。此处刻意 fail-closed —— 静默降级会让技能在运行时以
            ``UNKNOWN_SKILL`` 的形式消失且无日志线索（CI run 34845070952 的 10 条失败即此）。
    """
    explicit_source = "入参 skill_packages"
    candidate: Path | str | None = explicit
    if candidate is None:
        raw = (os.environ.get(SKILL_PACKAGES_ENV) or "").strip()
        if raw:
            explicit_source = f"环境变量 {SKILL_PACKAGES_ENV}"
            candidate = raw
    if candidate is not None:
        path = Path(candidate)
        if not _has_skill_packages(path):
            raise ValueError(
                f"{explicit_source} 指向的 Skill 包目录无效：{path}"
                f"（不存在，或其中没有任何 <skill>/SKILL.md）—— 拒绝静默降级；"
                f"技能缺失会在运行时表现为 UNKNOWN_SKILL")
        return path
    if _has_skill_packages(DEFAULT_SKILL_PACKAGES):
        return DEFAULT_SKILL_PACKAGES
    _log.warning(
        "未解析到外部 Skill 包：%s 未设置，且内置默认目录不可用（%s）—— "
        "bank-front 等外部技能将不可用；生产/CI 请显式设置 %s",
        SKILL_PACKAGES_ENV, DEFAULT_SKILL_PACKAGES, SKILL_PACKAGES_ENV)
    return None


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
    mode: str = SEARCH_MODE_FULLTEXT          # 值域见 domain/query_modes.SEARCH_MODES
    top_k: int = 10
    filters: dict | None = None


class RetrievalQueryRequest(BaseModel):
    """LightRAG **派生检索**请求（PC8 · CR-5，纯新增）。

    - 与既有 ``/v1/search``（库内检索）**语义不同**：本端点走外部 LightRAG 实例的**派生检索层**；
    - ``mode`` 取 lightRAG 既有模式（``local``/``global``/``hybrid``/``naive``/``mix``）；
    - ``service`` 缺省用 ``create_app`` 的 ``service_id``（保持既有默认行为）。
    """

    request_id: str
    query: str
    mode: str = "hybrid"
    service: str | None = None


class GraphRequest(BaseModel):
    request_id: str
    start_entity_ids: list[str]
    relation_types: list[str] | None = None
    direction: str = DIRECTION_OUT            # 值域见 domain/query_modes.GRAPH_DIRECTIONS
    max_depth: int = 1
    max_nodes: int = 100
    mode: str = GRAPH_MODE_NEIGHBOR           # 值域见 domain/query_modes.GRAPH_MODES（Kùzu 后端）
    service: str = "product_knowledge"  # 服务 ID（如 supply_chain_graph）
    as_of: str | None = None


class RuleRequest(BaseModel):
    request_id: str
    rule_set: str | None = None
    facts: dict


class RoutingPlanRequest(BaseModel):
    """v1.5 路由裁决请求（合同 `RoutingPlanRequest`）。

    字段命名沿用 Skill/Gate 面的 camelCase 约定；``extra="forbid"`` 兑现合同中的
    ``additionalProperties: false`` —— 未知字段一律 422，不静默忽略。
    """

    model_config = ConfigDict(extra="forbid")

    taskType: str
    subjectId: str | None = None


class AnalyticsComboQueryRequest(BaseModel):
    """CCRM-BA 组合查询请求（客户级多条件圈选）。

    ``filters`` 的结构与白名单见
    ``kert.application.operational_analytics.COMBO_METRIC_COLUMNS``
    （``amountRules`` 的 metric/op 均为白名单校验，防注入）。
    """

    model_config = ConfigDict(extra="forbid")

    filters: dict = Field(default_factory=dict)
    pageNumber: int = 0
    pageSize: int = 20


_PROVENANCE_VALUES = ("VERIFIED", "DEMO")
"""`provenanceState` 契约取值域（见 `specs/product-knowledge/product-knowledge-release.schema.json`）。"""

_DEFAULT_PROVENANCE = "DEMO"
"""证据不足时的 fail-closed 取值：**未证实一律按演示处理**（不得冒充真实制度）。"""


def derive_provenance_state(citations, workspace) -> str:
    """派生响应级 ``provenanceState`` —— **不取自检索返回值**（CR-5 边界第 5 条）。

    唯一证据：**出处回译到的 KERT 产物**顶层 ``provenanceState``
    （回译用 :func:`~kert.infrastructure.lightrag_client.parse_artifact_file_source`，
    与发布侧同一把尺）。取值域与契约一致：``VERIFIED`` / ``DEMO``。

    规则（保守方向，与 ``INV-RLS-09``「DEMO 不得冒充真实」同向）：
      · 任一产物为 ``DEMO`` ⇒ ``DEMO``（真实来源不得"洗白"混入的演示内容）；
      · 全部产物为 ``VERIFIED`` ⇒ ``VERIFIED``；
      · **证据不足**（无 citations / 不可回译 / 产物缺失 / 值不在取值域）⇒ ``DEMO``。
    """
    from ..infrastructure.lightrag_client import (
        LightRagArtifactRefused,
        parse_artifact_file_source,
    )

    states: list[str] = []
    for c in citations or ():
        if not isinstance(c, dict):
            continue
        source = c.get("docId") or c.get("filePath")
        if not source:
            continue
        try:
            rel = parse_artifact_file_source(str(source))
        except LightRagArtifactRefused:
            continue
        path = Path(workspace) / rel
        if not path.is_file():
            continue
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(doc, dict):
            continue
        value = doc.get("provenanceState")
        if not isinstance(value, str):
            continue
        normalized = value.strip().upper()
        if normalized not in _PROVENANCE_VALUES:
            continue
        states.append(normalized)
    if not states:
        return _DEFAULT_PROVENANCE
    return "DEMO" if "DEMO" in states else "VERIFIED"


def derive_simulation_only(citations, workspace) -> bool:
    """``simulationOnly`` 与 ``provenanceState`` **同源**：``DEMO`` ⇒ ``True``。

    两字段由同一派生源产生 ⇒ 天然自洽，不会出现"一个说模拟、另一个说真实"的组合。
    """
    return derive_provenance_state(citations, workspace) == _DEFAULT_PROVENANCE


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


def _maybe_analytics_service():
    """按 ``KERT_ANALYTICS_DUCKDB`` 构造经营分析服务（可选能力）。

    - 未设置 ⇒ ``None``（不接入；注册表与端点行为不变，既有测试不受扰动）；
    - 已设置但库文件缺失 ⇒ 启动即失败（fail-closed，与 KERT_SKILL_PACKAGES 同纪律）。
    """
    raw = os.environ.get(ANALYTICS_DUCKDB_ENV, "").strip()
    if not raw:
        return None
    from ..application.operational_analytics import OperationalAnalyticsService
    from ..infrastructure.analytics_store import AnalyticsDuckDb

    path = Path(raw)
    if not path.is_file():
        raise ServiceNotReadyError(
            f"{ANALYTICS_DUCKDB_ENV} 指定的分析库不存在: {raw}")
    return OperationalAnalyticsService(AnalyticsDuckDb(path, read_only=True))


def create_app(workspace: Path, service_id: str = "product_knowledge",
               skill_packages: Path | None = None,
               runtime_config: RuntimeConfig | None = None) -> FastAPI:
    """创建 KERT HTTP 应用。

    Args:
        workspace: KERT 工作区根目录。
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

    app = FastAPI(title="KERT Knowledge Service API",
                  description="文件目录型数据知识服务模拟平台（KERT-SPEC-001 V1.0）",
                  version=SERVICE_VERSION)
    ws = Path(workspace)
    svc = KnowledgeService(ws, service_id=service_id)
    pkgs = resolve_skill_packages(skill_packages)
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
    # 技能注册结果必须显式可见：技能缺失曾以「运行时 UNKNOWN_SKILL + 无日志」的形式
    # 静默发生（CI run 34845070952，见 evidence/kert-e2e-ci/TASK_PACKAGE_D-E2E-01.md）。
    _registered = [s.skill_id for s in skill_svc.registry()]
    _log.info("外部 Skill 包：resolved=%s；已注册技能 %d 个：%s",
              pkgs, len(_registered), _registered)
    # CCRM-BA 落地：DuckDB 可用时接入经营分析（4 个数据分析 Skill + REST 端点）。
    # 未配置 KERT_ANALYTICS_DUCKDB ⇒ 不接入，注册表与既有行为完全不变。
    analytics_svc = _maybe_analytics_service()
    if analytics_svc is not None:
        skill_svc.attach_analytics(analytics_svc, ANALYTICS_SKILL_PACKAGES)
        _analytics_registered = [s.skill_id for s in skill_svc.registry()
                                 if s.skill_id.startswith("bank-front-")
                                 and s.skill_id.endswith(
                                     ("-metrics", "-segment", "-query", "-monitor"))]
        _log.info("经营分析已接入：数据分析 Skill=%s", _analytics_registered)
    app.state.runtime_config = cfg
    app.state.runtime_store = store
    # 暴露 Service 便于运维自检与测试断言（M2-P2 Owner 决策 3 的校验链路）
    app.state.skill_service = skill_svc
    app.state.analytics_service = analytics_svc
    app.state.metrics_registry = registry
    app.state.tracer = tracer
    app.state.observability_capabilities = {
        "otel_available": otel_available(),
        "otel_attached": tracer.otel_attached,
        "prometheus_client_available": prometheus_client_available(),
    }
    _install_hardening(app, cfg)

    def _handle(exc: Exception) -> HTTPException:
        """领域异常 ⇒ 其**具名码**（原样透传）；非领域异常 ⇒ 通用 500（见 D-3）。

        非 KERT 分支此前把 ``str(exc)`` 放进响应体，与下面 app 级处理器的 A-5 口径
        （只给通用文案、细节进日志）不一致 —— D-3 已统一，且该分支**仍保持** 500 与
        原响应体形状（只换 message 文案）。
        """
        if isinstance(exc, KERTException):
            return HTTPException(status_code=exc.http_status(),
                                 detail={"error": {"code": exc.error_code,
                                                   "message": exc.message,
                                                   "retryable": exc.retryable()}})
        return _internal_error_http_exception(exc)

    @app.exception_handler(Exception)
    async def _unhandled_exception(request: Request, exc: Exception) -> JSONResponse:
        """未捕获异常 ⇒ 合同声明的 `ErrorResponse` 信封（HTTP 500）。

        修正记录（2026-09-16，Contract Owner 授权；对应失实项 F4c）：
        此前未捕获异常落到 FastAPI 默认 500（**纯文本** `Internal Server Error`），
        与 `specs/kert-openapi-v1.yaml` 中 `/api/skill/execute` 的 `500` 声明
        （`ErrorResponse` 信封：`requestId`/`status`/`errors[]`）不符。
        本处理器使**实际响应**与合同一致（只影响 5xx 兜底路径，2xx 与中间件行为不变）。

        安全口径：响应体**只**给通用 `INTERNAL_ERROR` 消息，**不回显** `str(exc)`
        （异常细节仅进服务端日志）；回传 `requestId` 供排障关联。
        登记：`evidence/m7-3/CANDIDATE-CONTRACT-MERGE-V1-V2.md`；用例
        `tests/integration/test_contract_shape_conformance.py`。

        D-3（2026-09-17）：本处理器是**非 KERT 异常的唯一实际路径**（各路由只捕获
        ``KERTException``），其口径现与 ``_internal_error_http_exception`` 完全一致
        （共用 :data:`INTERNAL_ERROR_MESSAGE`）；日志显式带**异常类型与消息**（``type=``
        / ``message=``）并附 ``exc_info`` 栈，供"响应里没有、日志里有"的机械核对。
        """
        request_id = (getattr(request.state, STATE_REQUEST_ID, None)
                      or new_request_id())
        _log.error("未捕获异常已转为 ErrorResponse 信封：request_id=%s method=%s path=%s "
                   "type=%s message=%s",
                   request_id, request.method, request.url.path,
                   type(exc).__name__, exc,
                   exc_info=(type(exc), exc, exc.__traceback__))
        return JSONResponse(status_code=500, content={
            "requestId": request_id,
            "status": SKILL_ERROR,
            "errors": [{"code": "INTERNAL_ERROR", "message": INTERNAL_ERROR_MESSAGE}],
        })

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
            checks["workspace"] = {"ok": False, "error": _readiness_check_error("workspace", exc)}
            ready = False

        try:
            checks["knowledge_projection"] = {"ok": True, "version": svc._active_version()}
        except ServiceNotReadyError as exc:
            # 投影缺失不阻断就绪（见上表说明），仅标记 degraded
            checks["knowledge_projection"] = {
                "ok": False, "error": _readiness_check_error("knowledge_projection", exc),
                "blocking": False}
            degraded.append("knowledge_projection")

        if store is not None:
            try:
                checks["runtime_store"] = {"ok": True,
                                           "schema_version": store.schema_version(),
                                           "journal_mode": store.journal_mode()}
            except Exception as exc:  # noqa: BLE001 - 探针需兜住任何 DB 异常
                checks["runtime_store"] = {"ok": False,
                                           "error": _readiness_check_error("runtime_store", exc)}
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
                checks["job_queue"] = {"ok": False,
                                       "error": _readiness_check_error("job_queue", exc)}
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
                raise KERTException("input.path 必填")
            m = _re.search(r"batch=([A-Z][A-Z0-9_-]+)", path)
            if not m:
                raise KERTException("无法从 path 解析 batch_id")
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
        except KERTException as exc:
            raise _handle(exc)

    @app.get("/v1/jobs/{job_id}")
    def job(job_id: str):
        try:
            fm = read_job_status(ws, job_id)
            return _response(f"REQ-JOB-{job_id}", fm)
        except KERTException as exc:
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
        except KERTException as exc:
            raise _handle(exc)

    @app.get("/v1/entities/{entity_id}")
    def entity(entity_id: str, as_of: str | None = None):
        try:
            r = svc.get_entity(entity_id, as_of=as_of)
            return _response(f"REQ-E-{entity_id}", r.data, r.meta)
        except KERTException as exc:
            raise _handle(exc)

    @app.post("/v1/data/query")
    def data_query(req: DataQueryRequest):
        try:
            r = svc.data_query(req.dataset, select=req.select, where=req.where,
                               limit=req.limit)
            return _response(req.request_id, r.data, r.meta)
        except KERTException as exc:
            raise _handle(exc)

    @app.post("/v1/search")
    def search(req: SearchRequest):
        try:
            r = svc.search(req.query, mode=req.mode, top_k=req.top_k,
                           filters=req.filters)
            return _response(req.request_id, r.data, r.meta)
        except KERTException as exc:
            raise _handle(exc)

    # ---------------- PC8 · CR-5：LightRAG 派生检索出口（纯新增） ----------------
    # 边界（CR-5 冻结口径，越界即回问）：
    #   1. **纯新增**：不改 /v1/search、/v1/data/query、/v1/entities/*、/v1/evidence/* 的语义与响应；
    #   2. 响应带**可回译出处**（chunkId = lightRAG referenceId；docId/filePath 可回译到 KERT 产物路径）
    #      与 `evidenceClass` / `provenanceState` / `simulationOnly`（后两者**同源派生**自出处产物，见第 5 条）；
    #   3. **fail-closed**：实例不可达 / 鉴权失败 / 响应形状不符 ⇒ 返回**具名 `LIGHTRAG_*` 码**，
    #      **禁止**空结果冒充成功（本端点**不吞错**、**不返回空列表**）；
    #   4. 不扩 EGRESS_ROOTS（本端点只读检索，不写入）；01_raw 一律 IR 白名单外（由 egress 侧守卫）；
    #   5. LightRAG 保持**派生检索层**：**字段值不得取自检索**。
    _LIGHTRAG_HTTP = {
        "LIGHTRAG_UNAVAILABLE": 503,
        "LIGHTRAG_HTTP_ERROR": 502,
        "LIGHTRAG_RESPONSE_INVALID": 502,
        "LIGHTRAG_PIPELINE_TIMEOUT": 504,
        "LIGHTRAG_ARTIFACT_REFUSED": 422,
        "LIGHTRAG_RETRACT_REFUSED": 409,
        "LIGHTRAG_ERROR": 500,
    }
    _LIGHTRAG_RETRYABLE = {"LIGHTRAG_UNAVAILABLE", "LIGHTRAG_HTTP_ERROR",
                           "LIGHTRAG_PIPELINE_TIMEOUT"}

    @app.post("/v1/retrieval/query")
    def retrieval_query(req: RetrievalQueryRequest):
        from ..application.services import KnowledgeService
        from ..infrastructure.lightrag_client import LightRagError

        try:
            target = svc if not req.service else KnowledgeService(ws, service_id=req.service)
            r = target.retrieve_via_lightrag(req.query, mode=req.mode)
            citations = []
            for c in r.get("citations", []):
                item = {"chunkId": c.get("referenceId"), "docId": c.get("filePath")}
                # 其余键（content / artifact / planId / planHash）**原样透传**：不伪造、不裁剪
                for k, v in c.items():
                    if k not in ("referenceId", "filePath"):
                        item[k] = v
                citations.append(item)
            data = {
                "query": r["query"],
                "mode": r["mode"],
                "endpoint": r["endpoint"],
                "entities": r["entities"],
                "relations": r["relations"],
                "citations": citations,
                "evidenceClass": "DERIVED_RETRIEVAL",
                # 两字段**同源派生**（出处回译到的产物 `provenanceState`；**不取自检索**，见边界 5）；
                # 证据不足即按 `DEMO`（fail-closed）。**禁止**写成字面量。
                "provenanceState": derive_provenance_state(citations, ws),
                "simulationOnly": derive_simulation_only(citations, ws),
            }
            return _response(req.request_id, data)
        except LightRagError as exc:
            code = getattr(exc, "code", "LIGHTRAG_ERROR")
            raise HTTPException(
                status_code=_LIGHTRAG_HTTP.get(code, 500),
                detail={"error": {"code": code, "message": str(exc),
                                  "retryable": code in _LIGHTRAG_RETRYABLE}})
        except KERTException as exc:
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
        except KERTException as exc:
            raise _handle(exc)

    @app.post("/v1/rules/evaluate")
    def rules(req: RuleRequest):
        try:
            r = svc.evaluate_rule(req.rule_set, facts=req.facts)
            return _response(req.request_id, r.data, r.meta)
        except KERTException as exc:
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
                    log_event(logging.getLogger("kert.api"), "WARNING",
                              "EVIDENCE_AUDIT_FAILED",
                              "evidence 审计镜像写入失败（不影响查询结果）",
                              object_id=object_id, error=str(exc))
            return _response(f"REQ-EV-{object_id}", r.data, r.meta)
        except KERTException as exc:
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
        except KERTException as exc:
            raise _handle(exc)

    # ================= 客户经理持续经营 Skill 平台（/api/skill/*）=================

    @app.get("/api/skill/health")
    def skill_health():
        """D1：列出已注册 skill 及版本。

        ``status`` 取**单一命名源** :data:`kert.domain.health.HEALTH_OK`（D-28 层 2 立源：
        合同 ``SkillHealthResponse.status.enum`` == ``SKILL_HEALTH_STATES`` 由用例机械核对）——
        本函数体内**不得**再出现状态字面量。
        """
        return {
            "status": HEALTH_OK,
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
        unknown = result.status == SKILL_ERROR and any(
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
        """Phase 2：业务闸门决策镜像（非权威；权威在 GITS，KERT 仅追加审计日志）。"""
        try:
            rec = skill_svc.record_gate_audit(req.customerId, req.gate, req.decision,
                                              req.decidedBy, req.reason)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return rec

    # ── v1.5：知识路由与激活计划（控制面读）──
    # 合同：specs/kert-openapi-v1.yaml（Routing tag）；变更提案见
    # evidence/m7-3/CONTRACT_CHANGE_PROPOSAL_ROUTING_API.md

    def _map_summary(m) -> dict:
        """地图摘要（合同 `KnowledgeMapSummary`；不含资产逐条明细）。"""
        return {
            "mapId": m.map_id,
            "version": m.version,
            "title": m.title,
            "domain": m.domain,
            "tasks": list(m.tasks),
            "priority": m.priority,
            "assetCount": len(m.asset_refs),
            "skillCount": len(m.skill_refs),
            "routePolicyRef": m.route_policy_ref,
        }

    @app.get("/v1/knowledge-maps")
    def list_knowledge_maps():
        """列出本工作区注册的知识地图。

        控制面未注册任何地图时返回**空列表**（不报错）——但空列表**不等于"可用"**：
        此时 ``/v1/routing/plan`` 会按 fail-closed 默认拒绝。
        """
        try:
            registry = KnowledgeMapRegistry.load(ws)
            policy = load_route_policy(ws)
        except KERTException as exc:
            raise _handle(exc)
        return _response(f"REQ-KM-{timeutil.ts_utc()[:19]}", {
            "maps": [_map_summary(m) for m in registry.maps],
            "count": len(registry),
            "policy": None if policy is None else {
                "policyId": policy.policy_id,
                "version": policy.version,
                "defaultDecision": policy.default_decision,
            },
        })

    @app.get("/v1/knowledge-maps/{map_id}")
    def get_knowledge_map(map_id: str):
        """单张知识地图详情；未注册 ⇒ 404（协议级"资源不存在"）。"""
        try:
            registry = KnowledgeMapRegistry.load(ws)
        except KERTException as exc:
            raise _handle(exc)
        if map_id not in registry:
            raise HTTPException(status_code=404, detail={"error": {
                "code": "KNOWLEDGE_MAP_NOT_REGISTERED",
                "message": f"知识地图未注册: {map_id}",
                "retryable": False}})
        return _response(f"REQ-KM-{map_id}", _map_summary(registry.get(map_id)))

    @app.post("/v1/routing/plan")
    def routing_plan(req: RoutingPlanRequest):
        """解析任务并产出**可重放**激活计划（fail-closed）。

        拒绝是**预期业务结果**（策略缺失 / 任务未映射 / 同优先级歧义 / 地图未注册 /
        策略错配 / 本体引用缺失或非法）：返回 **200** 且 ``allowed=false`` + ``denial``。
        ``allowed`` 只可能是 ``true``（带 ``plan``）或 ``false``（带 ``denial``）——没有第三态。
        """
        try:
            decision = ActivationPlanBuilder.load(ws).build(
                req.taskType, subject_id=req.subjectId)
        except KERTException as exc:
            raise _handle(exc)
        if isinstance(decision, PlanDenial):
            data = {"allowed": False, "plan": None,
                    "denial": {"code": decision.code, "reason": decision.reason}}
        else:
            data = {"allowed": True, "plan": decision.to_dict(), "denial": None}
        return _response(f"REQ-RPLAN-{timeutil.ts_utc()[:19]}", data)

    # ── CCRM-BA 对公经营分析（DuckDB，可选接入）──────────────────────────

    def _require_analytics():
        if analytics_svc is None:
            raise HTTPException(status_code=503, detail={"error": {
                "code": "ANALYTICS_UNAVAILABLE",
                "message": "经营分析未接入（设置 KERT_ANALYTICS_DUCKDB 后重启）",
                "retryable": False}})
        return analytics_svc

    @app.get("/v1/analytics/dimensions")
    def analytics_dimensions():
        """CCRM-BA：分析维度与成员（原型「分布维度」下拉的数据源）。"""
        try:
            return _response(new_request_id(),
                             {"dimensions": _require_analytics().dimensions()})
        except KERTException as exc:
            raise _handle(exc)

    @app.get("/v1/analytics/orgs")
    def analytics_orgs():
        """CCRM-BA：机构树（org_path 支持上卷过滤）。"""
        try:
            return _response(new_request_id(), {"orgs": _require_analytics().orgs()})
        except KERTException as exc:
            raise _handle(exc)

    @app.get("/v1/analytics/periods")
    def analytics_periods():
        """CCRM-BA：可用分析期间（YYYYMM）。"""
        try:
            return _response(new_request_id(),
                             {"periods": _require_analytics().periods()})
        except KERTException as exc:
            raise _handle(exc)

    @app.get("/v1/analytics/screens")
    def analytics_screens():
        """CCRM-BA：10 个分析屏注册表（screen/bizType/dims/metrics）。"""
        try:
            return _response(new_request_id(),
                             {"screens": _require_analytics().screen_catalog()})
        except KERTException as exc:
            raise _handle(exc)

    @app.get("/v1/analytics/params")
    def analytics_params():
        """CCRM-BA：当前生效的分析口径参数（告警阈值/年化月数/杠杆系数/利润来源）。"""
        try:
            return _response(new_request_id(),
                             {"params": _require_analytics().params()})
        except KERTException as exc:
            raise _handle(exc)

    @app.get("/v1/analytics/metrics")
    def analytics_metrics(screen: str, dim: str, orgId: str, period: str,
                          bizType: str | None = None,
                          dimValues: str | None = None):
        """CCRM-BA：按屏聚合指标（行=机构或维度成员，含 mom/ytd/share）。"""
        try:
            values = [v for v in (dimValues or "").split(",") if v.strip()] or None
            data = _require_analytics().metrics(
                screen=screen, dim=dim, org_id=orgId, period=period,
                biz_type=bizType, dim_values=values)
            return _response(new_request_id(), data, data.pop("meta", None))
        except KERTException as exc:
            raise _handle(exc)

    @app.get("/v1/analytics/trend")
    def analytics_trend(screen: str, dim: str, dimValue: str, orgId: str,
                        metric: str, months: int = 12):
        """CCRM-BA：单一维度成员 12 个月趋势（监视器右图 / 走势图）。"""
        try:
            data = _require_analytics().trend(
                screen=screen, dim=dim, dim_value=dimValue, org_id=orgId,
                metric=metric, months=months)
            return _response(new_request_id(), data)
        except KERTException as exc:
            raise _handle(exc)

    @app.post("/v1/analytics/combo-query")
    def analytics_combo_query(req: AnalyticsComboQueryRequest):
        """CCRM-BA：客户级多条件圈选（组合查询工具，白名单 fail-closed）。"""
        try:
            data = _require_analytics().combo_query(
                filters=req.filters, page_number=req.pageNumber,
                page_size=req.pageSize)
            return _response(new_request_id(), data)
        except KERTException as exc:
            raise _handle(exc)

    # ── DSH Web 界面 ──
    from ..dsh.app import mount_dsh
    app.state.workspace = ws
    app.state.knowledge_service = svc
    mount_dsh(app)

    return app
