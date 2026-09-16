"""GITS+KERT 联合 E2E 测试共享夹具。

本模块承担两件事，二者共同保证「未验证不得表现为通过」：

1. **按需探活 + 策略化降级**
   - 只声明某服务夹具的用例，不会因其它服务缺失而被牵连（按需探活）；
   - 缺失服务默认 ``skip``，reason 含**服务名 + 探活地址**；
   - 被显式 require 的服务缺失时 ``fail/error``，**禁止**降级为 skip。
2. **防假绿下限断言 + 覆盖账本**
   - 下限/上限由**本次收集结果**推导（非魔数），用例增删后自动重算；
   - 违反即把 pytest 退出码置为失败，使「KERT 未起来」表现为 job 失败；
   - 每轮打印覆盖账本，含未覆盖用例逐条清单（按文件分组）。

环境变量：

| 变量 | 默认 | 含义 |
|---|---|---|
| ``KERT_BASE_URL`` | ``http://127.0.0.1:8106`` | KERT 基址 |
| ``GITS_BASE_URL`` | ``http://127.0.0.1:8082`` | GITS Backend 基址 |
| ``GITS_FRONTEND_URL`` | ``http://127.0.0.1:5173`` | GITS 前端基址 |
| ``E2E_HEALTH_TIMEOUT`` | ``30`` | **被 require** 的服务的就绪等待窗口（秒） |
| ``E2E_PROBE_TIMEOUT`` | ``3`` | 服务缺失判定窗口（秒）：缺失时快速失败，不复用 30s |
| ``E2E_HEALTH_INTERVAL`` | ``1`` | 轮询间隔（秒） |
| ``E2E_REQUIRE_KERT`` | 未设 | 服务维度 require：KERT 不可达 → fail |
| ``E2E_REQUIRE_GITS`` | 未设 | 服务维度 require：GITS Backend 不可达 → fail |
| ``E2E_REQUIRE_GITS_FRONTEND`` | 未设 | 服务维度 require：GITS 前端不可达 → fail |
| ``E2E_REQUIRE_SERVICES`` | 未设 | 全局 require（向后兼容）：等价于三者全开 |
| ``E2E_LEDGER_PATH`` | 未设 | 覆盖账本 JSON 落盘路径（供 CI 独立断言步骤核验） |
| ``KERT_API_KEY`` | 未设 | KERT API Key 的**密钥本身（secret）**，非空时注入 ``X-API-Key`` 请求头 |

关于 ``KERT_API_KEY``：由本仓编排（``deploy/docker-compose.yml``，``KERT_PROFILE=prod``）
拉起的 KERT **强制鉴权**，不注入该头则除公开探针（``/livez``、``/readyz``、
``/api/skill/health``）外一律 401；CI 因 ``KERT_PROFILE=dev`` 而无需它。
值取 ``deploy/.env`` 中 ``KERT_API_KEYS`` 首个 key 的 **secret 段**，
**不是** ``key_id:secret``（见 ``deploy/README.md`` §4）。未设置时行为与既有完全一致。

require 语义取**并集**：任一开关要求即要求。全局开关 ``E2E_REQUIRE_SERVICES=1``
的既有语义不变（三端全要求）。被 require 的服务的不可达判定发生在**夹具解析之前**
（``pytest_runtest_setup``），且只针对该用例所需的服务——既保证「required 缺失
必然 fail 而非 skip」，又不牵连其它用例可独立验证的部分。
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx
import pytest

if TYPE_CHECKING:  # pragma: no cover - 仅类型标注用
    from _pytest.config import Config
    from _pytest.main import Session
    from _pytest.reports import TestReport
    from _pytest.terminal import TerminalReporter

# ---------------------------------------------------------------------------
# 服务基址（可通过环境变量覆盖）
# ---------------------------------------------------------------------------
KERT_BASE_URL = os.getenv("KERT_BASE_URL", "http://127.0.0.1:8106")
GITS_BASE_URL = os.getenv("GITS_BASE_URL", "http://127.0.0.1:8082")
GITS_FRONTEND_URL = os.getenv("GITS_FRONTEND_URL", "http://127.0.0.1:5173")

# KERT API Key 的**密钥本身（secret）**（非 `key_id:secret`，见 deploy/README.md §4）。
# 空 ⇒ 不注入请求头（与 dev profile / 既有行为一致）；prod profile 下必须设置，
# 否则 KERT 侧除公开探针外一律 401。
KERT_API_KEY = os.getenv("KERT_API_KEY", "").strip()

# ---------------------------------------------------------------------------
# 探活参数
# ---------------------------------------------------------------------------
# 被 require 的服务：给足就绪等待窗口（服务可能刚启动）
HEALTH_TIMEOUT = float(os.getenv("E2E_HEALTH_TIMEOUT", "30"))  # 秒
# 未被 require 的服务：短窗口，缺失时快速失败（3 个夹具各等 30s 会拖长 job）
PROBE_TIMEOUT = float(os.getenv("E2E_PROBE_TIMEOUT", "3"))  # 秒
HEALTH_INTERVAL = float(os.getenv("E2E_HEALTH_INTERVAL", "1"))  # 秒

# 覆盖账本落盘路径（留空 = 不落盘）
LEDGER_PATH_ENV = "E2E_LEDGER_PATH"

_TRUTHY = frozenset({"1", "true", "yes", "on"})
_GLOBAL_REQUIRE_ENV = "E2E_REQUIRE_SERVICES"


@dataclass(frozen=True)
class _Service:
    """一个需要探活的外部服务。"""

    key: str
    label: str
    base: str
    path: str
    require_env: str

    @property
    def probe_url(self) -> str:
        """探活地址（reason 中逐字引用，便于运维定位）。"""
        return f"{self.base}{self.path}"


class ServiceNotReadyError(RuntimeError):
    """被显式 require 的服务不可用——必须以失败暴露，禁止降级为 skip。"""


SERVICES: dict[str, _Service] = {
    "kert": _Service(
        key="kert",
        label="KERT Skill Service",
        base=KERT_BASE_URL,
        path="/api/skill/health",
        require_env="E2E_REQUIRE_KERT",
    ),
    "gits": _Service(
        key="gits",
        label="GITS Backend",
        base=GITS_BASE_URL,
        path="/actuator/health",
        require_env="E2E_REQUIRE_GITS",
    ),
    "gits_frontend": _Service(
        key="gits_frontend",
        label="GITS Frontend",
        base=GITS_FRONTEND_URL,
        path="",
        require_env="E2E_REQUIRE_GITS_FRONTEND",
    ),
}

# 夹具名 → 该夹具隐含要求的服务集合。
# 用途有二：把 session 夹具的传递依赖摊平到「用例的直接 fixturenames」上，
# 从而由收集结果推导覆盖账本下限；以及识别跨服务用例。
_FIXTURE_TO_SERVICES: dict[str, frozenset[str]] = {
    "kert_ready": frozenset({"kert"}),
    "kert_client": frozenset({"kert"}),
    "gits_ready": frozenset({"gits"}),
    "gits_client": frozenset({"gits"}),
    "gits_frontend_ready": frozenset({"gits_frontend"}),
    "all_services_ready": frozenset({"kert", "gits", "gits_frontend"}),
}

# 探活结果缓存：同一 URL 在 session 内只判定一次，避免重复等待
_PROBE_CACHE: dict[str, bool] = {}


# ---------------------------------------------------------------------------
# require 策略（服务维度 + 全局向后兼容，取并集）
# ---------------------------------------------------------------------------
def _env_enabled(name: str) -> bool:
    """环境变量是否为真值（``1``/``true``/``yes``/``on``）。"""
    return os.getenv(name, "").strip().lower() in _TRUTHY


def _service_required(key: str) -> bool:
    """该服务是否被显式要求可用（服务维度开关 ∪ 全局开关）。"""
    if _env_enabled(SERVICES[key].require_env):
        return True
    return _env_enabled(_GLOBAL_REQUIRE_ENV)


def _required_message(service: _Service) -> str:
    return (
        f"{service.label} 不可达 ({service.probe_url})，但已被显式要求可用"
        f"（{service.require_env}=1 或 {_GLOBAL_REQUIRE_ENV}=1）——禁止降级为 skip"
    )


def _services_for(item: Any) -> set[str]:
    """用例**直接**声明的夹具所隐含要求的服务集合。"""
    needed: set[str] = set()
    for fixture_name in item.fixturenames:
        needed |= _FIXTURE_TO_SERVICES.get(fixture_name, frozenset())
    return needed


def _guard_required_for(item: Any) -> None:
    """在夹具解析**之前**判定：本用例所需的服务中，被 require 却不可达的服务。

    必须早于夹具解析：否则「同时需要缺失的 GITS 与被 require 且缺失的 KERT」的用例
    会先因 GITS 而 skip，把「被要求的服务没起来」伪装成合法跳过。
    只针对**本用例所需**的服务，因此不会牵连其它用例可独立验证的部分。
    """
    needed = _services_for(item)
    for key, service in SERVICES.items():
        if key in needed and _service_required(key) and not _ready(service):
            raise ServiceNotReadyError(_required_message(service))


# ---------------------------------------------------------------------------
# 探活
# ---------------------------------------------------------------------------
def _probe(url: str, timeout: float, interval: float = HEALTH_INTERVAL) -> bool:
    """轮询 GET url 直到返回 2xx 或超时。

    只回答「是否就绪」，**不抛异常、不 skip**——skip / fail 由 ``_resolve`` 按策略决定。
    """
    deadline = time.monotonic() + max(timeout, 0.0)
    per_request = min(5.0, max(1.0, timeout))
    while True:
        try:
            resp = httpx.get(url, timeout=per_request)
            if 200 <= resp.status_code < 300:
                return True
        except httpx.HTTPError:
            # 连接被拒 / 超时 / 协议错误：一律视为"尚未就绪"，继续轮询
            pass
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        time.sleep(min(interval, remaining))


def _ready(service: _Service) -> bool:
    """探活该服务（session 级缓存）。"""
    cached = _PROBE_CACHE.get(service.probe_url)
    if cached is None:
        timeout = HEALTH_TIMEOUT if _service_required(service.key) else PROBE_TIMEOUT
        cached = _probe(service.probe_url, timeout)
        _PROBE_CACHE[service.probe_url] = cached
    return cached


def _resolve(service: _Service) -> str:
    """按 require 策略解析服务基址：就绪返回基址；缺失则 fail 或 skip。"""
    if _ready(service):
        return service.base
    reason = f"{service.label} 不可达 ({service.probe_url})"
    if _service_required(service.key):
        raise ServiceNotReadyError(_required_message(service))
    pytest.skip(reason)
    raise AssertionError("unreachable")  # pragma: no cover - pytest.skip 永不返回


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def kert_ready() -> str:
    """等待 KERT 服务就绪，返回基址；缺失时按 require 策略 skip 或 fail。"""
    return _resolve(SERVICES["kert"])


@pytest.fixture(scope="session")
def gits_ready() -> str:
    """等待 GITS Backend 服务就绪，返回基址；缺失时按 require 策略 skip 或 fail。"""
    return _resolve(SERVICES["gits"])


@pytest.fixture(scope="session")
def gits_frontend_ready() -> str:
    """等待 GITS Frontend 服务就绪，返回基址；缺失时按 require 策略 skip 或 fail。"""
    return _resolve(SERVICES["gits_frontend"])


@pytest.fixture(scope="session")
def all_services_ready(kert_ready: str, gits_ready: str, gits_frontend_ready: str) -> dict[str, str]:
    """等待三端服务全部就绪，返回 {service: base_url} 映射（语义继承三个夹具）。"""
    return {
        "kert": kert_ready,
        "gits": gits_ready,
        "gits_frontend": gits_frontend_ready,
    }


@pytest.fixture(scope="session")
def kert_client(kert_ready: str) -> httpx.Client:
    """KERT HTTP 客户端（session 级复用）。

    ``KERT_API_KEY`` 非空时注入 ``X-API-Key``——由本仓编排拉起的服务是 ``prod``
    profile，强制鉴权；为让「用本仓编排真跑 e2e」成为可能，必须能带上凭据。
    """
    headers = {"X-API-Key": KERT_API_KEY} if KERT_API_KEY else {}
    with httpx.Client(base_url=kert_ready, timeout=120, headers=headers) as client:
        yield client


@pytest.fixture(scope="session")
def gits_client(gits_ready: str) -> httpx.Client:
    """GITS Backend HTTP 客户端（session 级复用）。"""
    with httpx.Client(base_url=gits_ready, timeout=120) as client:
        yield client


# ---------------------------------------------------------------------------
# 覆盖账本 + 防假绿下限断言
# ---------------------------------------------------------------------------
_HERE = Path(__file__).resolve().parent
_COUNTERS = ("passed", "failed", "skipped", "error")

# 本次属于本目录的用例 nodeid（由收集阶段填充）
_OWN_NODEIDS: set[str] = set()
# 本次分组（由收集结果推导）
_GROUPS: dict[str, list[str]] = {}
# 每个用例的最终结论与 skip reason（由报告钩子填充）
_OUTCOMES: dict[str, str] = {}
_SKIP_REASONS: dict[str, str] = {}
# 账本（sessionfinish 构建一次，terminal_summary 打印）
_LEDGER: dict[str, Any] | None = None


def _classify(items: list[Any]) -> dict[str, list[str]]:
    """按用例**直接**声明的夹具，把用例分为四组。

    - ``no_service``：不依赖任何外部服务
    - ``kert_only``：只依赖 KERT
    - ``gits_only``：只依赖 GITS Backend
    - ``multi_end``：依赖多端或含 GITS 前端（与 ``gits_only`` 合称跨服务用例）
    """
    groups: dict[str, list[str]] = {
        "no_service": [],
        "kert_only": [],
        "gits_only": [],
        "multi_end": [],
        "cross_service": [],
    }
    for item in items:
        needed = _services_for(item)
        nodeid = item.nodeid
        if not needed:
            groups["no_service"].append(nodeid)
        elif needed == {"kert"}:
            groups["kert_only"].append(nodeid)
        elif needed == {"gits"}:
            groups["gits_only"].append(nodeid)
            groups["cross_service"].append(nodeid)
        else:
            groups["multi_end"].append(nodeid)
            groups["cross_service"].append(nodeid)
    return groups


def _skip_reason(report: TestReport) -> str:
    """从 skip 报告中取出 reason（pytest 以 (path, lineno, reason) 三元组承载）。"""
    longrepr = report.longrepr
    if isinstance(longrepr, tuple) and len(longrepr) == 3:
        return str(longrepr[2])
    return str(longrepr)


def pytest_collection_modifyitems(session: Session, config: Config, items: list[Any]) -> None:
    """记录本目录用例清单并推导覆盖账本下限/上限。

    下限**不是魔数**：由本次收集结果推导，用例增删后自动重算
    （``min_passed = 无服务用例 + 仅 KERT 用例``，``max_skipped = 跨服务用例``）。
    """
    global _GROUPS
    ours = [item for item in items if _HERE in Path(str(item.path)).resolve().parents]
    _OWN_NODEIDS.clear()
    _OWN_NODEIDS.update(item.nodeid for item in ours)
    _GROUPS = _classify(ours)


def pytest_runtest_setup(item: Any) -> None:
    """require 优先于 skip：夹具解析前先判定本用例所需服务是否被 require 且缺失。"""
    if item.nodeid not in _OWN_NODEIDS:
        return
    _guard_required_for(item)


def pytest_runtest_logreport(report: TestReport) -> None:
    """逐用例记录最终结论（setup 的 skip/error 与 call 的 passed/failed）。"""
    nodeid = report.nodeid
    if nodeid not in _OWN_NODEIDS:
        return
    if report.when == "setup":
        if report.skipped:
            _OUTCOMES[nodeid] = "skipped"
            _SKIP_REASONS[nodeid] = _skip_reason(report)
        elif report.failed:
            _OUTCOMES[nodeid] = "error"
    elif report.when == "call":
        if report.skipped:
            _OUTCOMES[nodeid] = "skipped"
            _SKIP_REASONS[nodeid] = _skip_reason(report)
        elif report.passed:
            _OUTCOMES[nodeid] = "passed"
        else:
            _OUTCOMES[nodeid] = "failed"
    elif report.failed and nodeid not in _OUTCOMES:
        _OUTCOMES[nodeid] = "error"


def _build_ledger(exitstatus: int) -> dict[str, Any] | None:
    """构建覆盖账本；无本目录用例时不启用（避免影响其它测试目录的运行）。"""
    if not _OWN_NODEIDS:
        return None
    collected = len(_OWN_NODEIDS)
    counts = {name: sum(1 for outcome in _OUTCOMES.values() if outcome == name) for name in _COUNTERS}
    unrun = collected - len(_OUTCOMES)

    no_service = _GROUPS.get("no_service", [])
    kert_only = _GROUPS.get("kert_only", [])
    gits_only = _GROUPS.get("gits_only", [])
    multi_end = _GROUPS.get("multi_end", [])
    cross_service = _GROUPS.get("cross_service", [])

    min_passed = len(no_service) + len(kert_only)
    max_skipped = len(cross_service)

    uncovered = sorted(
        (nodeid for nodeid, outcome in _OUTCOMES.items() if outcome == "skipped"),
    )
    uncovered_by_file: dict[str, list[str]] = {}
    for nodeid in uncovered:
        uncovered_by_file.setdefault(nodeid.split("::", 1)[0], []).append(nodeid.split("::", 1)[1])

    violations: list[str] = []
    if counts["error"] > 0:
        violations.append(f"errors={counts['error']}（必须 0）")
    if counts["failed"] > 0:
        violations.append(f"failed={counts['failed']}（必须 0）")
    if counts["passed"] < min_passed:
        violations.append(
            f"passed={counts['passed']} < 下限 {min_passed}"
            f"（无服务 {len(no_service)} + 仅 KERT {len(kert_only)}）"
            "——被 require 的服务可能未起来，禁止以 skip 掩盖"
        )
    if counts["skipped"] > max_skipped:
        violations.append(
            f"skipped={counts['skipped']} > 上限 {max_skipped}（跨服务用例数）"
            "——存在计划外跳过"
        )
    if unrun > 0:
        violations.append(f"未产生结果的用例 {unrun} 个（收集 {collected}，报告 {len(_OUTCOMES)}）")

    return {
        "collected": collected,
        "passed": counts["passed"],
        "skipped": counts["skipped"],
        "failed": counts["failed"],
        "errors": counts["error"],
        "min_passed": min_passed,
        "max_skipped": max_skipped,
        "min_passed_derivation": f"无服务 {len(no_service)} + 仅 KERT {len(kert_only)}",
        "max_skipped_derivation": f"跨服务 {len(cross_service)}（仅 GITS {len(gits_only)} + 多端/含前端 {len(multi_end)}）",
        "coverage": f"{counts['passed']}/{collected} 真跑，{counts['skipped']}/{collected} 未覆盖",
        "groups": {
            "no_service": no_service,
            "kert_only": kert_only,
            "gits_only": gits_only,
            "multi_end": multi_end,
        },
        "uncovered": uncovered,
        "uncovered_reasons": {nodeid: _SKIP_REASONS.get(nodeid, "") for nodeid in uncovered},
        "uncovered_by_file": uncovered_by_file,
        "require_switches": {
            service.require_env: _env_enabled(service.require_env) for service in SERVICES.values()
        }
        | {_GLOBAL_REQUIRE_ENV: _env_enabled(_GLOBAL_REQUIRE_ENV)},
        "violations": violations,
        "pytest_exitstatus": int(exitstatus),
    }


def pytest_sessionfinish(session: Session, exitstatus: int) -> None:
    """落盘账本，并在下限被击穿时把退出码置为失败（防假绿）。"""
    global _LEDGER
    if getattr(session.config.option, "collectonly", False):
        return
    _LEDGER = _build_ledger(exitstatus)
    if _LEDGER is None:
        return
    path = os.getenv(LEDGER_PATH_ENV, "").strip()
    if path:
        Path(path).write_text(
            json.dumps(_LEDGER, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    if _LEDGER["violations"] and session.exitstatus == pytest.ExitCode.OK:
        session.exitstatus = pytest.ExitCode.TESTS_FAILED


def _ledger_lines(ledger: dict[str, Any]) -> list[str]:
    lines = [
        "",
        "E2E 覆盖账本（下限由本次收集结果推导，见 TECH_LEAD_DECISION.md D-8）：",
        f"  collected = {ledger['collected']}",
        f"  passed  = {ledger['passed']}   (下限 {ledger['min_passed']} = {ledger['min_passed_derivation']})",
        f"  skipped = {ledger['skipped']}   (上限 {ledger['max_skipped']} = {ledger['max_skipped_derivation']})",
        f"  failed  = {ledger['failed']}   (必须 0)",
        f"  errors  = {ledger['errors']}   (必须 0)",
        f"  覆盖口径：{ledger['coverage']}",
        "  未覆盖用例清单（按文件分组）：",
    ]
    uncovered_by_file: dict[str, list[str]] = ledger["uncovered_by_file"]
    if not uncovered_by_file:
        lines.append("    （无）")
    for path, items in uncovered_by_file.items():
        lines.append(f"    {path}  ({len(items)} 条)")
        for short in items:
            reason = ledger["uncovered_reasons"].get(f"{path}::{short}", "")
            lines.append(f"      - {short}  [{reason}]")
    active = [name for name, on in ledger["require_switches"].items() if on]
    lines.append(f"  require 开关：{', '.join(active) if active else '（未设置 → 缺失服务一律 skip）'}")
    if ledger["violations"]:
        lines.append("  ✗ 下限断言失败：")
        for violation in ledger["violations"]:
            lines.append(f"    - {violation}")
        lines.append("::error::E2E 覆盖账本下限断言失败，job 必须失败（禁止以 skip 掩盖未验证）")
    else:
        lines.append("  ✓ 下限断言通过（errors=0, failed=0, passed>=下限, skipped<=上限）")
    lines.append(
        "  说明：本账本是「未覆盖」的显式登记，不等于「通过」；"
        "CI 绿不代表跨服务链路已验证。"
    )
    return lines


def pytest_terminal_summary(
    terminalreporter: TerminalReporter, exitstatus: int, config: Config
) -> None:
    """每轮打印覆盖账本（无论成败都打印）。"""
    if _LEDGER is None:
        return
    for line in _ledger_lines(_LEDGER):
        terminalreporter.write_line(line)
