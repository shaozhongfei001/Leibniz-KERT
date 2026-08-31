"""跨服务健康检查 E2E 测试。

验证 KERT、GITS Backend、GITS Frontend 三端服务均可达且返回健康状态。
"""

from __future__ import annotations

import httpx


class TestCrossServiceHealth:
    """三端服务健康可达性验证。"""

    def test_kert_health(self, kert_client: httpx.Client) -> None:
        """KERT /api/skill/health 返回 200。"""
        resp = kert_client.get("/api/skill/health")
        assert resp.status_code == 200, (
            f"KERT health 端点返回 {resp.status_code}: {resp.text[:200]}"
        )

    def test_gits_backend_health(self, gits_client: httpx.Client) -> None:
        """GITS Backend /actuator/health 返回 200。"""
        resp = gits_client.get("/actuator/health")
        assert resp.status_code == 200, (
            f"GITS Backend health 端点返回 {resp.status_code}: {resp.text[:200]}"
        )
        body = resp.json()
        # Spring Boot Actuator health 默认返回 {"status":"UP",...}
        assert body.get("status") == "UP", (
            f"GITS Backend health status 非 UP: {body}"
        )

    def test_gits_frontend_reachable(self, gits_frontend_ready: str) -> None:
        """GITS Frontend 首页返回 200。"""
        resp = httpx.get(gits_frontend_ready, timeout=10)
        assert resp.status_code == 200, (
            f"GITS Frontend 返回 {resp.status_code}: {resp.text[:200]}"
        )

    def test_all_services_simultaneously(self, all_services_ready: dict[str, str]) -> None:
        """三端服务全部可达（依赖 session 级 fixture 的就绪检查）。"""
        assert "kert" in all_services_ready
        assert "gits" in all_services_ready
        assert "gits_frontend" in all_services_ready
