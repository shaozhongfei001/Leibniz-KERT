"""
DKWS Python Client — GITS Adapter 参考实现

与 GITS DshHttpSkillExecutionAdapter 功能对齐：
- 同步/异步 Skill 执行
- 健康检查
- Job 轮询
- 闸门查询/审计
- API Key 认证
- fail-closed 错误处理 + 指数退避重试

仅使用标准库（urllib），无第三方依赖。
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional
from urllib.parse import urljoin

logger = logging.getLogger("dkws_client")


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

class SkillStatus(str, Enum):
    OK = "ok"
    SKILL_ERROR = "skill_error"
    EXIT_POLICY = "exit_policy_no_new_evidence"


class JobStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class GateDecision(str, Enum):
    PASSED = "PASSED"
    BLOCKED = "BLOCKED"
    WAIVED = "WAIVED"


@dataclass
class SkillInfo:
    skill_id: str
    name: str
    version: str = ""
    description: str = ""
    async_capable: bool = False


@dataclass
class SkillExecutionResult:
    request_id: str
    status: str
    skill_id: str = ""
    report_url: str = ""
    result: dict[str, Any] = field(default_factory=dict)
    rule_violations: list[dict[str, Any]] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)
    assembly_trace: dict[str, Any] = field(default_factory=dict)
    model_calls: list[dict[str, Any]] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class AsyncJob:
    job_id: str
    status: JobStatus = JobStatus.PENDING


@dataclass
class JobResult:
    job_id: str
    status: JobStatus
    created_at: str = ""
    started_at: str = ""
    completed_at: str = ""
    skill_result: Optional[SkillExecutionResult] = None
    error: Optional[dict[str, Any]] = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class GateItem:
    gate: str
    name: str
    state: str
    must: list[str] = field(default_factory=list)
    forbidden: list[str] = field(default_factory=list)


@dataclass
class GateAuditResult:
    recorded: bool
    timestamp: str = ""
    audit_path: str = ""


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class DkwsError(Exception):
    """DKWS 调用基础异常"""

    def __init__(self, message: str, status_code: int = 0, error_code: str = "", detail: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code
        self.detail = detail


class DkwsConnectionError(DkwsError):
    """网络连接失败"""


class DkwsTimeoutError(DkwsError):
    """请求超时"""


class DkwsSkillError(DkwsError):
    """Skill 执行错误（DKWS 返回非 ok 状态）"""


class DkwsJobFailedError(DkwsError):
    """异步 Job 执行失败"""


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class DkwsClient:
    """
    DKWS API 客户端。

    与 GITS DshHttpSkillExecutionAdapter 功能对齐：
    - 同步 Skill 执行（R1/图谱/外联/会面/SP-21）
    - 异步 Skill 执行 + Job 轮询（SP-20）
    - 健康检查
    - 闸门查询/审计
    - fail-closed + 指数退避重试

    用法::

        client = DkwsClient(base_url="http://127.0.0.1:8106", api_key="xxx")
        result = client.execute_skill_sync("R1", "req-001", customer_id="CUST-001")
        job = client.execute_skill_async("SP-20", "req-002", context={...})
        final = client.poll_job(job.job_id)
    """

    DEFAULT_CONNECT_TIMEOUT = 5.0       # 秒，对齐 GITS connect-timeout-ms=5000
    DEFAULT_READ_TIMEOUT = 120.0        # 秒，对齐 GITS read-timeout-ms=120000
    DEFAULT_POLL_INTERVAL = 3.0         # 秒，对齐 GITS async-poll-interval-ms=3000
    DEFAULT_POLL_TIMEOUT = 180.0        # 秒，对齐 GITS async-poll-timeout-ms=180000
    DEFAULT_MAX_RETRIES = 3
    DEFAULT_RETRY_BACKOFF = 1.0         # 秒，初始退避
    DEFAULT_RETRY_BACKOFF_MAX = 30.0    # 秒，最大退避

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8106",
        api_key: str = "",
        connect_timeout: float = DEFAULT_CONNECT_TIMEOUT,
        read_timeout: float = DEFAULT_READ_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
        retry_backoff: float = DEFAULT_RETRY_BACKOFF,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.connect_timeout = connect_timeout
        self.read_timeout = read_timeout
        self.max_retries = max_retries
        self.retry_backoff = retry_backoff

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def health_check(self) -> dict[str, Any]:
        """GET /v1/health — 服务整体健康检查"""
        return self._request("GET", "/v1/health")

    def skill_health(self) -> dict[str, Any]:
        """GET /api/skill/health — Skill 子系统健康检查（GITS 适配器使用）"""
        return self._request("GET", "/api/skill/health")

    def list_skills(self) -> list[SkillInfo]:
        """GET /v1/skills — 列出可用 Skill"""
        data = self._request("GET", "/v1/skills")
        return [
            SkillInfo(
                skill_id=s.get("skillId", ""),
                name=s.get("name", ""),
                version=s.get("version", ""),
                description=s.get("description", ""),
                async_capable=s.get("async", False),
            )
            for s in data.get("skills", [])
        ]

    def execute_skill_sync(
        self,
        skill_id: str,
        request_id: str,
        *,
        customer_id: str = "",
        context: Optional[dict[str, Any]] = None,
    ) -> SkillExecutionResult:
        """
        POST /api/skill/execute — 同步执行 Skill。

        Args:
            skill_id: Skill ID（如 R1, SP-21）
            request_id: 请求唯一标识（幂等键）
            customer_id: 客户 ID（单客户技能）
            context: ContextPackage（SP-20/SP-21 组合技能）

        Returns:
            SkillExecutionResult

        Raises:
            DkwsSkillError: Skill 执行失败
            DkwsError: 其他错误
        """
        body = self._build_execute_body(skill_id, request_id, async_mode=False,
                                         customer_id=customer_id, context=context)
        resp = self._request("POST", "/api/skill/execute", json_body=body)
        return self._parse_execute_response(resp)

    def execute_skill_async(
        self,
        skill_id: str,
        request_id: str,
        *,
        customer_id: str = "",
        context: Optional[dict[str, Any]] = None,
    ) -> AsyncJob:
        """
        POST /api/skill/execute (async=true) — 异步提交 Skill 执行。

        Returns:
            AsyncJob with job_id and PENDING status

        Raises:
            DkwsSkillError: 提交失败
        """
        body = self._build_execute_body(skill_id, request_id, async_mode=True,
                                         customer_id=customer_id, context=context)
        resp = self._request("POST", "/api/skill/execute", json_body=body)
        return AsyncJob(
            job_id=resp.get("jobId", ""),
            status=JobStatus(resp.get("status", "PENDING")),
        )

    def poll_job(
        self,
        job_id: str,
        *,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
        poll_timeout: float = DEFAULT_POLL_TIMEOUT,
    ) -> JobResult:
        """
        GET /v1/jobs/{jobId} — 轮询异步 Job 直到 COMPLETED/FAILED 或超时。

        Args:
            job_id: 异步作业 ID
            poll_interval: 轮询间隔（秒）
            poll_timeout: 轮询超时（秒）

        Returns:
            JobResult（COMPLETED 时含 skill_result）

        Raises:
            DkwsJobFailedError: Job 执行失败
            DkwsTimeoutError: 轮询超时
        """
        deadline = time.monotonic() + poll_timeout
        while True:
            result = self.get_job(job_id)
            if result.status in (JobStatus.COMPLETED, JobStatus.FAILED):
                if result.status == JobStatus.FAILED:
                    err = result.error or {}
                    raise DkwsJobFailedError(
                        message=err.get("message", f"Job {job_id} failed"),
                        error_code=err.get("code", "JOB_FAILED"),
                        detail=result.raw,
                    )
                return result
            if time.monotonic() >= deadline:
                raise DkwsTimeoutError(
                    f"Polling job {job_id} timed out after {poll_timeout}s",
                    error_code="POLL_TIMEOUT",
                )
            time.sleep(poll_interval)

    def get_job(self, job_id: str) -> JobResult:
        """GET /v1/jobs/{jobId} — 查询 Job 状态（单次）"""
        resp = self._request("GET", f"/v1/jobs/{job_id}")
        return self._parse_job_response(resp)

    def get_gates(self, customer_id: str) -> list[GateItem]:
        """GET /api/skill/gates/{customerId} — 获取客户闸门清单"""
        resp = self._request("GET", f"/api/skill/gates/{customer_id}")
        gates = []
        for g in resp.get("gates", []):
            cl = g.get("checklist", {})
            gates.append(GateItem(
                gate=g.get("gate", ""),
                name=g.get("name", ""),
                state=g.get("state", ""),
                must=cl.get("must", []),
                forbidden=cl.get("forbidden", []),
            ))
        return gates

    def audit_gate(
        self,
        customer_id: str,
        gate: str,
        decision: str,
        decided_by: str,
        reason: str = "",
    ) -> GateAuditResult:
        """POST /api/skill/gates/audit — 闸门决策镜像"""
        body = {
            "customerId": customer_id,
            "gate": gate,
            "decision": decision,
            "decidedBy": decided_by,
            "reason": reason,
        }
        resp = self._request("POST", "/api/skill/gates/audit", json_body=body)
        return GateAuditResult(
            recorded=resp.get("recorded", False),
            timestamp=resp.get("timestamp", ""),
            audit_path=resp.get("auditPath", ""),
        )

    def livez(self) -> dict[str, Any]:
        """GET /livez — 存活探针"""
        return self._request("GET", "/livez")

    def readyz(self) -> dict[str, Any]:
        """GET /readyz — 就绪探针"""
        return self._request("GET", "/readyz")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_execute_body(
        self,
        skill_id: str,
        request_id: str,
        *,
        async_mode: bool = False,
        customer_id: str = "",
        context: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "skillId": skill_id,
            "requestId": request_id,
            "request": {},
        }
        if async_mode:
            body["async"] = True

        if context:
            body["request"]["context"] = context
        elif customer_id:
            body["request"]["customerId"] = customer_id

        return body

    def _parse_execute_response(self, resp: dict[str, Any]) -> SkillExecutionResult:
        data = resp.get("data", {})
        status = resp.get("status", "")
        errors = resp.get("errors", [])

        result = SkillExecutionResult(
            request_id=resp.get("requestId", ""),
            status=status,
            skill_id=data.get("skillId", ""),
            report_url=data.get("reportUrl", ""),
            result=data.get("result", {}),
            rule_violations=data.get("ruleViolations", []),
            errors=errors,
            assembly_trace=resp.get("assemblyTrace", {}),
            model_calls=resp.get("modelCalls", []),
            raw=resp,
        )

        # fail-closed: 非 ok 状态抛异常
        if status != SkillStatus.OK.value:
            err_msg = "; ".join(e.get("message", "") for e in errors) if errors else f"Skill error: status={status}"
            raise DkwsSkillError(
                message=err_msg,
                error_code=errors[0].get("code", "SKILL_ERROR") if errors else "SKILL_ERROR",
                detail=resp,
            )

        return result

    def _parse_job_response(self, resp: dict[str, Any]) -> JobResult:
        status = JobStatus(resp.get("status", "PENDING"))
        skill_result = None
        job_data = resp.get("data", {})
        if status == JobStatus.COMPLETED and job_data:
            sr = job_data.get("skill_result", {})
            if sr:
                skill_result = self._parse_execute_response(sr)

        return JobResult(
            job_id=resp.get("jobId", ""),
            status=status,
            created_at=resp.get("createdAt", ""),
            started_at=resp.get("startedAt", ""),
            completed_at=resp.get("completedAt", ""),
            skill_result=skill_result,
            error=resp.get("error"),
            raw=resp,
        )

    def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """带重试的 HTTP 请求（指数退避）。"""
        url = f"{self.base_url}{path}"
        data = json.dumps(json_body).encode("utf-8") if json_body else None

        last_exc: Optional[Exception] = None
        for attempt in range(self.max_retries + 1):
            try:
                req = urllib.request.Request(url, data=data, method=method)
                req.add_header("Content-Type", "application/json")
                req.add_header("Accept", "application/json")
                if self.api_key:
                    req.add_header("X-API-Key", self.api_key)

                with urllib.request.urlopen(req, timeout=self.read_timeout) as resp:
                    body = resp.read().decode("utf-8")
                    return json.loads(body)

            except urllib.error.HTTPError as e:
                # 4xx 不重试（客户端错误），5xx 可重试
                if 400 <= e.code < 500:
                    try:
                        err_body = json.loads(e.read().decode("utf-8"))
                    except Exception:
                        err_body = {}
                    errors = err_body.get("errors", [])
                    err_msg = "; ".join(er.get("message", "") for er in errors) if errors else e.reason
                    err_code = errors[0].get("code", "HTTP_" + str(e.code)) if errors else "HTTP_" + str(e.code)
                    raise DkwsSkillError(
                        message=err_msg,
                        status_code=e.code,
                        error_code=err_code,
                        detail=err_body,
                    )
                # 5xx — 可重试
                last_exc = DkwsError(
                    f"Server error {e.code}: {e.reason}",
                    status_code=e.code,
                    error_code="HTTP_" + str(e.code),
                )

            except urllib.error.URLError as e:
                last_exc = DkwsConnectionError(
                    f"Connection failed: {e.reason}",
                    error_code="CONNECTION_ERROR",
                )

            except TimeoutError as e:
                last_exc = DkwsTimeoutError(
                    f"Request timed out after {self.read_timeout}s",
                    error_code="TIMEOUT",
                )

            # 指数退避
            if attempt < self.max_retries:
                backoff = min(self.retry_backoff * (2 ** attempt), self.DEFAULT_RETRY_BACKOFF_MAX)
                logger.warning("Retry %d/%d after %.1fs: %s", attempt + 1, self.max_retries, backoff, last_exc)
                time.sleep(backoff)

        # 重试耗尽
        if last_exc:
            raise last_exc
        raise DkwsError("Unknown error after retries", error_code="RETRY_EXHAUSTED")


# ---------------------------------------------------------------------------
# Convenience: execute with auto-async for long-running skills
# ---------------------------------------------------------------------------

LONG_RUNNING_SKILLS = {"SP-20"}  # 这些 Skill 建议异步执行


def execute_skill(
    client: DkwsClient,
    skill_id: str,
    request_id: str,
    *,
    customer_id: str = "",
    context: Optional[dict[str, Any]] = None,
    force_async: bool = False,
) -> SkillExecutionResult:
    """
    自动选择同步/异步模式的 Skill 执行入口。

    - SP-20 等长任务自动走异步 + 轮询
    - 其他 Skill 走同步
    - force_async=True 强制异步
    """
    use_async = force_async or skill_id in LONG_RUNNING_SKILLS

    if use_async:
        job = client.execute_skill_async(
            skill_id, request_id,
            customer_id=customer_id, context=context,
        )
        result = client.poll_job(job.job_id)
        return result.skill_result  # type: ignore[return-value]
    else:
        return client.execute_skill_sync(
            skill_id, request_id,
            customer_id=customer_id, context=context,
        )


# ---------------------------------------------------------------------------
# CLI demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import os

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    base_url = os.environ.get("DKWS_BASE_URL", "http://127.0.0.1:8106")
    api_key = os.environ.get("DKWS_API_KEY", "")

    client = DkwsClient(base_url=base_url, api_key=api_key)

    # 1. 健康检查
    print("=== Health Check ===")
    try:
        health = client.skill_health()
        print(json.dumps(health, indent=2, ensure_ascii=False))
    except DkwsError as e:
        print(f"Health check failed: {e}")

    # 2. 同步执行 R1
    print("\n=== Execute R1 (sync) ===")
    try:
        result = client.execute_skill_sync("R1", "demo-req-001", customer_id="CUST-DEMO")
        print(f"Status: {result.status}, SkillId: {result.skill_id}")
        print(f"ReportUrl: {result.report_url}")
    except DkwsError as e:
        print(f"Execute failed: {e}")

    # 3. 异步执行 SP-20 + 轮询
    print("\n=== Execute SP-20 (async) ===")
    try:
        job = client.execute_skill_async("SP-20", "demo-req-002", context={
            "schemaVersion": "1.0.0",
            "customerId": "CUST-DEMO",
        })
        print(f"Job submitted: {job.job_id}, status: {job.status}")
        final = client.poll_job(job.job_id)
        if final.skill_result:
            print(f"Job completed: {final.skill_result.status}")
    except DkwsError as e:
        print(f"Async execute failed: {e}")
