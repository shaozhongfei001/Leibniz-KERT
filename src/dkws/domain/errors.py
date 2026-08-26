"""DKWS 领域错误与 CLI/HTTP 错误码映射（规格 §12.1、§13.6）。"""

from __future__ import annotations

from dataclasses import dataclass, field

# CLI 退出码（规格 §12.1）
EXIT_OK = 0
EXIT_USAGE = 2          # 参数/合同错误
EXIT_QUALITY_GATE = 3   # 质量门禁失败
EXIT_CONFLICT = 4       # 冲突/锁失败
EXIT_INTERNAL = 5       # 内部错误


@dataclass
class ErrorCode:
    """规格 §13.6 错误码表。"""

    code: str
    http: int
    retryable: bool


ERROR_CODES = {
    "INVALID_REQUEST": ErrorCode("INVALID_REQUEST", 400, False),
    "PATH_OUTSIDE_WORKSPACE": ErrorCode("PATH_OUTSIDE_WORKSPACE", 400, False),
    "ASSET_NOT_FOUND": ErrorCode("ASSET_NOT_FOUND", 404, False),
    "VERSION_NOT_FOUND": ErrorCode("VERSION_NOT_FOUND", 404, False),
    "IDEMPOTENCY_CONFLICT": ErrorCode("IDEMPOTENCY_CONFLICT", 409, False),
    "WORKSPACE_LOCKED": ErrorCode("WORKSPACE_LOCKED", 409, True),
    "SCHEMA_VALIDATION_FAILED": ErrorCode("SCHEMA_VALIDATION_FAILED", 422, False),
    "QUALITY_GATE_FAILED": ErrorCode("QUALITY_GATE_FAILED", 422, False),
    "UNAPPROVED_ASSET": ErrorCode("UNAPPROVED_ASSET", 422, False),
    "UNSUPPORTED_MEDIA_TYPE": ErrorCode("UNSUPPORTED_MEDIA_TYPE", 415, False),
    "PAYLOAD_TOO_LARGE": ErrorCode("PAYLOAD_TOO_LARGE", 413, False),
    "SERVICE_NOT_READY": ErrorCode("SERVICE_NOT_READY", 503, True),
    "INTERNAL_ERROR": ErrorCode("INTERNAL_ERROR", 500, True),
    "JOB_ORPHANED": ErrorCode("INTERNAL_ERROR", 500, False),
    "RULE_CONFLICT": ErrorCode("INVALID_REQUEST", 409, False),
}


class DKWSException(Exception):
    """基础领域异常。"""

    exit_code: int = EXIT_INTERNAL
    error_code: str = "INTERNAL_ERROR"

    def __init__(self, message: str, *, error_code: str | None = None,
                 exit_code: int | None = None, details: dict | None = None):
        super().__init__(message)
        self.message = message
        if error_code:
            self.error_code = error_code
        if exit_code is not None:
            self.exit_code = exit_code
        self.details = details or {}

    def http_status(self) -> int:
        ec = ERROR_CODES.get(self.error_code)
        return ec.http if ec else 500

    def retryable(self) -> bool:
        ec = ERROR_CODES.get(self.error_code)
        return ec.retryable if ec else False


class UsageError(DKWSException):
    """参数或合同错误（退出码 2）。"""

    exit_code = EXIT_USAGE
    error_code = "INVALID_REQUEST"


class SchemaValidationError(DKWSException):
    """文件合同校验失败（退出码 2/HTTP 422）。"""

    exit_code = EXIT_USAGE
    error_code = "SCHEMA_VALIDATION_FAILED"


class QualityGateError(DKWSException):
    """质量门禁失败（退出码 3/HTTP 422）。"""

    exit_code = EXIT_QUALITY_GATE
    error_code = "QUALITY_GATE_FAILED"


class ConflictError(DKWSException):
    """冲突或锁失败（退出码 4/HTTP 409）。"""

    exit_code = EXIT_CONFLICT
    error_code = "WORKSPACE_LOCKED"


class PathSafetyError(DKWSException):
    """路径越界/不安全（退出码 2/HTTP 400）。"""

    exit_code = EXIT_USAGE
    error_code = "PATH_OUTSIDE_WORKSPACE"


class AssetNotFoundError(DKWSException):
    """资产不存在（HTTP 404）。"""

    exit_code = EXIT_USAGE
    error_code = "ASSET_NOT_FOUND"


class VersionNotFoundError(DKWSException):
    """版本不存在（HTTP 404）。"""

    exit_code = EXIT_USAGE
    error_code = "VERSION_NOT_FOUND"


class IdempotencyConflictError(DKWSException):
    """同幂等键不同内容（HTTP 409）。"""

    exit_code = EXIT_CONFLICT
    error_code = "IDEMPOTENCY_CONFLICT"


class ServiceNotReadyError(DKWSException):
    """无有效投影（HTTP 503）。"""

    exit_code = EXIT_INTERNAL
    error_code = "SERVICE_NOT_READY"


class UnapprovedAssetError(DKWSException):
    """试图服务/发布未批准候选（HTTP 422）。"""

    exit_code = EXIT_QUALITY_GATE
    error_code = "UNAPPROVED_ASSET"


class RuleConflictError(DKWSException):
    """同优先级规则冲突动作（HTTP 409）。"""

    exit_code = EXIT_CONFLICT
    error_code = "RULE_CONFLICT"
