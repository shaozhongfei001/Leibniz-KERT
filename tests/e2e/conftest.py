"""GITS+KERT 联合 E2E 测试共享夹具。"""

from __future__ import annotations

import os
import time

import httpx
import pytest

# ---------------------------------------------------------------------------
# 服务基址（可通过环境变量覆盖）
# ---------------------------------------------------------------------------
KERT_BASE_URL = os.getenv("KERT_BASE_URL", "http://127.0.0.1:8106")
GITS_BASE_URL = os.getenv("GITS_BASE_URL", "http://127.0.0.1:8082")
GITS_FRONTEND_URL = os.getenv("GITS_FRONTEND_URL", "http://127.0.0.1:5173")

# 等待就绪参数
HEALTH_TIMEOUT = float(os.getenv("E2E_HEALTH_TIMEOUT", "30"))  # 秒
HEALTH_INTERVAL = float(os.getenv("E2E_HEALTH_INTERVAL", "1"))  # 秒


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------
def _wait_for(url: str, timeout: float = HEALTH_TIMEOUT, interval: float = HEALTH_INTERVAL) -> bool:
    """轮询 GET url 直到返回 2xx 或超时。"""
    deadline = time.monotonic() + timeout
    last_exc: Exception | None = None
    while time.monotonic() < deadline:
        try:
            resp = httpx.get(url, timeout=5)
            if 200 <= resp.status_code < 300:
                return True
            last_exc = RuntimeError(f"{url} 返回 {resp.status_code}")
        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            last_exc = exc
        time.sleep(interval)
    raise AssertionError(f"服务未就绪: {url} ({last_exc})")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def kert_ready() -> str:
    """等待 KERT 服务就绪，返回基址。"""
    _wait_for(f"{KERT_BASE_URL}/api/skill/health")
    return KERT_BASE_URL


@pytest.fixture(scope="session")
def gits_ready() -> str:
    """等待 GITS Backend 服务就绪，返回基址。"""
    _wait_for(f"{GITS_BASE_URL}/actuator/health")
    return GITS_BASE_URL


@pytest.fixture(scope="session")
def gits_frontend_ready() -> str:
    """等待 GITS Frontend 服务就绪，返回基址。"""
    _wait_for(GITS_FRONTEND_URL)
    return GITS_FRONTEND_URL


@pytest.fixture(scope="session")
def all_services_ready(kert_ready: str, gits_ready: str, gits_frontend_ready: str) -> dict[str, str]:
    """等待三端服务全部就绪，返回 {service: base_url} 映射。"""
    return {
        "kert": kert_ready,
        "gits": gits_ready,
        "gits_frontend": gits_frontend_ready,
    }


@pytest.fixture(scope="session")
def kert_client(kert_ready: str) -> httpx.Client:
    """KERT HTTP 客户端（session 级复用）。"""
    with httpx.Client(base_url=kert_ready, timeout=120) as client:
        yield client


@pytest.fixture(scope="session")
def gits_client(gits_ready: str) -> httpx.Client:
    """GITS Backend HTTP 客户端（session 级复用）。"""
    with httpx.Client(base_url=gits_ready, timeout=120) as client:
        yield client
