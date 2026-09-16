"""状态机（规格 §11）：任务状态、知识资产状态、发布状态。

状态转换必须校验前态，禁止跳转；终态不可直接退出。
"""

from __future__ import annotations

from .errors import UsageError

# ---- 任务状态机（§11.1）----
JOB_STATES = [
    "PENDING", "RUNNING", "VALIDATING", "COMPLETED",
    "FAILED", "CANCEL_REQUESTED", "CANCELLED", "RETRYING", "BLOCKED",
]
JOB_TERMINAL = {"COMPLETED", "FAILED", "CANCELLED", "BLOCKED"}
JOB_TRANSITIONS: dict[str, set[str]] = {
    "PENDING": {"RUNNING", "BLOCKED", "FAILED"},
    "RUNNING": {"VALIDATING", "FAILED", "CANCEL_REQUESTED"},
    "VALIDATING": {"COMPLETED", "FAILED"},
    "CANCEL_REQUESTED": {"CANCELLED"},
    "FAILED": {"RETRYING"},
    "RETRYING": {"RUNNING", "FAILED"},
    "COMPLETED": set(),
    "CANCELLED": set(),
    "BLOCKED": set(),
}


def transition_job(current: str, target: str) -> str:
    _check_state(current, JOB_STATES, "任务")
    _check_state(target, JOB_STATES, "任务")
    if target not in JOB_TRANSITIONS.get(current, set()):
        raise UsageError(f"非法任务状态转换: {current} → {target}")
    return target


def is_job_terminal(state: str) -> bool:
    return state in JOB_TERMINAL


# ---- 知识资产状态机（§11.2）----
# validation_status 管理审核，status 管理业务活动性
KNOWLEDGE_VALIDATION_STATES = ["CANDIDATE", "IN_REVIEW", "APPROVED", "REJECTED"]
KNOWLEDGE_VALIDATION_TRANSITIONS: dict[str, set[str]] = {
    "CANDIDATE": {"IN_REVIEW"},
    "IN_REVIEW": {"APPROVED", "REJECTED", "CANDIDATE"},  # REQUEST_CHANGES → CANDIDATE
    "APPROVED": set(),
    "REJECTED": set(),
}
KNOWLEDGE_STATUS_STATES = ["ACTIVE", "INACTIVE", "MERGED", "SUPERSEDED"]
KNOWLEDGE_STATUS_TRANSITIONS: dict[str, set[str]] = {
    "ACTIVE": {"INACTIVE", "SUPERSEDED", "MERGED"},
    "INACTIVE": set(),
    "MERGED": set(),
    "SUPERSEDED": set(),
}
# PUBLISHED 由 Release 记录驱动，不属于 MD 内枚举（APPROVED 且进入 Core 版本才视为已发布）


def transition_knowledge_validation(current: str, target: str) -> str:
    _check_state(current, KNOWLEDGE_VALIDATION_STATES, "知识审核状态")
    _check_state(target, KNOWLEDGE_VALIDATION_STATES, "知识审核状态")
    if target not in KNOWLEDGE_VALIDATION_TRANSITIONS.get(current, set()):
        raise UsageError(f"非法知识审核状态转换: {current} → {target}")
    return target


def transition_knowledge_status(current: str, target: str) -> str:
    _check_state(current, KNOWLEDGE_STATUS_STATES, "知识业务状态")
    _check_state(target, KNOWLEDGE_STATUS_STATES, "知识业务状态")
    if target not in KNOWLEDGE_STATUS_TRANSITIONS.get(current, set()):
        raise UsageError(f"非法知识业务状态转换: {current} → {target}")
    return target


# ---- 发布状态机（§11.3）----
RELEASE_STATES = [
    "DRAFT_RELEASE", "VALIDATING", "READY_TO_PUBLISH", "PUBLISHING",
    "PUBLISHED", "VALIDATION_FAILED", "PUBLISH_FAILED",
]
RELEASE_TRANSITIONS: dict[str, set[str]] = {
    "DRAFT_RELEASE": {"VALIDATING"},
    "VALIDATING": {"READY_TO_PUBLISH", "VALIDATION_FAILED"},
    "READY_TO_PUBLISH": {"PUBLISHING"},
    "PUBLISHING": {"PUBLISHED", "PUBLISH_FAILED"},
    "PUBLISHED": set(),
    "VALIDATION_FAILED": {"VALIDATING"},
    "PUBLISH_FAILED": {"PUBLISHING"},
}
RELEASE_TERMINAL = {"PUBLISHED"}


def transition_release(current: str, target: str) -> str:
    _check_state(current, RELEASE_STATES, "发布")
    _check_state(target, RELEASE_STATES, "发布")
    if target not in RELEASE_TRANSITIONS.get(current, set()):
        raise UsageError(f"非法发布状态转换: {current} → {target}")
    return target


def _check_state(state: str, allowed: list[str], label: str) -> None:
    if state not in allowed:
        raise UsageError(f"非法{label}状态: {state!r}（允许 {allowed}）")
