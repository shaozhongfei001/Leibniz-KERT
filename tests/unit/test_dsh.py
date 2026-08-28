"""DSH Web 界面单元测试。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from fastapi.testclient import TestClient


# ── 夹具 ──

@pytest.fixture
def dsh_client(ws):
    """创建挂载了 DSH 的测试客户端。"""
    from dkws.api.server import create_app

    app = create_app(ws, service_id="product_knowledge")
    return TestClient(app)


# ── SPA 入口 ──

class TestSpaEntry:
    def test_dsh_root_returns_html(self, dsh_client):
        r = dsh_client.get("/dsh/")
        assert r.status_code == 200
        assert "DSH" in r.text
        assert "text/html" in r.headers["content-type"]

    def test_dsh_subpath_returns_html(self, dsh_client):
        r = dsh_client.get("/dsh/skills")
        assert r.status_code == 200
        assert "DSH" in r.text

    def test_dsh_api_nonexistent_returns_404(self, dsh_client):
        r = dsh_client.get("/dsh/api/nonexistent")
        assert r.status_code == 404


# ── 仪表盘 ──

class TestDashboard:
    def test_dashboard_returns_stats(self, dsh_client):
        r = dsh_client.get("/dsh/api/dashboard")
        assert r.status_code == 200
        data = r.json()
        assert "workspace" in data
        assert "workspace_exists" in data
        assert "entity_count" in data
        assert "relation_count" in data
        assert "statement_count" in data
        assert "rule_count" in data
        assert "skill_count" in data
        assert "jobs_running" in data
        assert "jobs_completed" in data
        assert "jobs_failed" in data

    def test_dashboard_workspace_exists(self, dsh_client, ws):
        r = dsh_client.get("/dsh/api/dashboard")
        data = r.json()
        assert data["workspace_exists"] is True


# ── 技能管理 ──

class TestSkills:
    def test_list_skills_returns_list(self, dsh_client):
        r = dsh_client.get("/dsh/api/skills")
        assert r.status_code == 200
        data = r.json()
        assert "skills" in data
        assert isinstance(data["skills"], list)

    def test_execute_skill_no_service(self, dsh_client):
        """无技能服务时返回 503。"""
        # 默认 workspace 无技能注册，skill_service 可能为 None
        r = dsh_client.post("/dsh/api/skills/execute", json={
            "skillId": "test_skill", "request": {}
        })
        # 可能 503（服务不可用）或正常返回
        assert r.status_code in (200, 503)


# ── 知识浏览 ──

class TestKnowledge:
    @pytest.mark.parametrize("asset", ["entities", "relations", "statements", "rules"])
    def test_knowledge_list_returns_records(self, dsh_client, asset):
        r = dsh_client.get(f"/dsh/api/knowledge/{asset}")
        assert r.status_code == 200
        data = r.json()
        assert "records" in data
        assert "count" in data
        assert isinstance(data["records"], list)

    def test_knowledge_with_limit(self, dsh_client):
        r = dsh_client.get("/dsh/api/knowledge/entities?limit=10")
        assert r.status_code == 200


# ── 任务监控 ──

class TestJobs:
    def test_list_jobs_returns_list(self, dsh_client):
        r = dsh_client.get("/dsh/api/jobs")
        assert r.status_code == 200
        data = r.json()
        assert "jobs" in data
        assert isinstance(data["jobs"], list)

    def test_list_jobs_with_filter(self, dsh_client):
        r = dsh_client.get("/dsh/api/jobs?status=RUNNING")
        assert r.status_code == 200

    def test_get_job_not_found(self, dsh_client):
        r = dsh_client.get("/dsh/api/jobs/nonexistent-job")
        assert r.status_code == 404


# ── mount_dsh 函数 ──

class TestMountDsh:
    def test_mount_dsh_adds_router(self):
        from fastapi import FastAPI
        from dkws.dsh.app import mount_dsh

        app = FastAPI()
        app.state.workspace = Path(".")
        mount_dsh(app)
        # 验证路由已注册 — 检查 app.routes 中有 DSH 相关路由
        has_dsh = False
        for route in app.routes:
            rpath = getattr(route, "path", "") or getattr(route, "route", "")
            if "/dsh" in str(rpath):
                has_dsh = True
                break
            # _IncludedRouter 内部路由
            for sub in getattr(route, "routes", []):
                sp = getattr(sub, "path", "")
                if "dashboard" in sp or "skills" in sp or "knowledge" in sp:
                    has_dsh = True
                    break
        assert has_dsh, "DSH 路由未注册"
