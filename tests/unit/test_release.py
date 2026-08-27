"""M2.6 发布清单与版本锚点单元测试。"""

from __future__ import annotations

import json
from pathlib import Path

from dkws.infrastructure.release import (
    ReleaseManifest,
    build_release_manifest,
    collect_version_map,
    compare_manifests,
    git_anchor,
    hash_directory,
    write_release_manifest,
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


class TestGitAnchor:
    """git 版本锚点采集（治理文档登记的缺失项）。"""

    def test_anchor_available_in_repo(self):
        """本仓库内可采集到 commit 锚点。"""
        anchor = git_anchor(REPO_ROOT)
        assert anchor["available"] is True
        assert len(anchor["commit"]) == 40
        assert anchor["short_commit"] == anchor["commit"][:12]

    def test_anchor_reports_branch_and_dirty(self):
        """回报分支与工作区脏状态。"""
        anchor = git_anchor(REPO_ROOT)
        assert isinstance(anchor["branch"], str)
        assert isinstance(anchor["dirty"], bool)
        assert isinstance(anchor["dirty_file_count"], int)

    def test_anchor_degrades_outside_repo(self, tmp_path):
        """非 git 目录降级为不可用，不抛异常。"""
        anchor = git_anchor(tmp_path)
        assert anchor["available"] is False
        assert "锚点缺失" in anchor["note"]


class TestVersionMap:
    """版本号汇总（不统一，只如实记录）。"""

    def test_collects_all_known_versions(self):
        """汇总代码中分散的各套版本。"""
        versions = collect_version_map()
        for key in ("package", "service_http", "runtime_db_schema",
                    "projection_builder", "python", "platform"):
            assert key in versions

    def test_runtime_schema_is_int(self):
        """Runtime DB schema 为整数版本。"""
        assert collect_version_map()["runtime_db_schema"] == 2

    def test_versions_may_differ(self):
        """各套版本可以不同——本模块只记录不统一。"""
        versions = collect_version_map()
        assert versions["package"] is not None
        assert versions["service_http"] is not None


class TestHashDirectory:
    """目录内容确定性哈希。"""

    def test_absent_dir(self, tmp_path):
        """目录不存在时明确标记。"""
        assert hash_directory(tmp_path / "nope")["present"] is False

    def test_deterministic(self, tmp_path):
        """同样内容得到同样哈希。"""
        (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
        (tmp_path / "b.py").write_text("y = 2\n", encoding="utf-8")
        first = hash_directory(tmp_path, patterns=("*.py",))
        second = hash_directory(tmp_path, patterns=("*.py",))
        assert first["content_sha256"] == second["content_sha256"]
        assert first["file_count"] == 2

    def test_content_change_alters_hash(self, tmp_path):
        """内容变化导致哈希变化。"""
        target = tmp_path / "a.py"
        target.write_text("x = 1\n", encoding="utf-8")
        before = hash_directory(tmp_path, patterns=("*.py",))["content_sha256"]
        target.write_text("x = 2\n", encoding="utf-8")
        after = hash_directory(tmp_path, patterns=("*.py",))["content_sha256"]
        assert before != after

    def test_excludes_pycache(self, tmp_path):
        """排除 __pycache__ 等非源码内容。"""
        (tmp_path / "__pycache__").mkdir()
        (tmp_path / "__pycache__" / "a.py").write_text("cached", encoding="utf-8")
        (tmp_path / "real.py").write_text("x = 1\n", encoding="utf-8")
        assert hash_directory(tmp_path, patterns=("*.py",))["file_count"] == 1


class TestReleaseManifest:
    """发布清单生成。"""

    def test_builds_with_all_components(self):
        """六个组件全部被采集。"""
        manifest = build_release_manifest(REPO_ROOT)
        expected = {"python_source", "public_contracts", "public_schemas",
                    "internal_contracts", "skill_packages", "scripts"}
        assert set(manifest.components) == expected
        assert all(info["present"] for info in manifest.components.values())

    def test_release_id_defaults_to_commit(self):
        """缺省 release_id 取 git short commit。"""
        manifest = build_release_manifest(REPO_ROOT)
        assert manifest.release_id == manifest.git["short_commit"]

    def test_explicit_release_id(self):
        """可指定 release_id。"""
        assert build_release_manifest(REPO_ROOT, release_id="v9").release_id == "v9"

    def test_fingerprint_stable(self):
        """同一状态下指纹稳定。"""
        first = build_release_manifest(REPO_ROOT).fingerprint()
        second = build_release_manifest(REPO_ROOT).fingerprint()
        assert first == second
        assert len(first) == 64

    def test_notes_include_non_claims(self):
        """含非声明与版本分散说明。"""
        joined = " ".join(build_release_manifest(REPO_ROOT).notes)
        assert "不代表已通过发布门禁" in joined
        assert "版本号在代码中分散" in joined

    def test_dirty_workspace_warned(self, monkeypatch):
        """工作区有未提交变更时明确警示不应用于生产。"""
        monkeypatch.setattr(
            "dkws.infrastructure.release.git_anchor",
            lambda repo: {"available": True, "commit": "a" * 40,
                          "short_commit": "a" * 12, "branch": "x", "tag": None,
                          "dirty": True, "dirty_file_count": 3,
                          "committed_at": None})
        joined = " ".join(build_release_manifest(REPO_ROOT).notes)
        assert "不应用于生产" in joined

    def test_missing_git_warned(self, monkeypatch):
        """git 不可用时警示可追溯性受限。"""
        monkeypatch.setattr("dkws.infrastructure.release.git_anchor",
                            lambda repo: {"available": False, "note": "n/a"})
        joined = " ".join(build_release_manifest(REPO_ROOT).notes)
        assert "可追溯性受限" in joined

    def test_as_dict_has_schema(self):
        """含 schema 标识便于版本演进。"""
        data = build_release_manifest(REPO_ROOT).as_dict()
        assert data["schema"] == "dkws_release_manifest/v1"

    def test_write_manifest(self, tmp_path):
        """清单可写出且含指纹。"""
        dest, manifest = write_release_manifest(REPO_ROOT, tmp_path / "r.json")
        data = json.loads(dest.read_text(encoding="utf-8"))
        assert data["fingerprint"] == manifest.fingerprint()
        assert data["release_id"] == manifest.release_id


class TestCompareManifests:
    """清单比对（升级/回滚前确认差异）。"""

    @staticmethod
    def _manifest(commit: str, src_hash: str, version: str) -> dict:
        """构造用于比对的最小清单。"""
        return {
            "git": {"commit": commit},
            "fingerprint": f"fp-{commit}-{src_hash}",
            "versions": {"package": version, "runtime_db_schema": 2},
            "components": {"python_source": {"content_sha256": src_hash}},
        }

    def test_identical_manifests(self):
        """相同清单无差异。"""
        left = self._manifest("a" * 40, "h1", "1.0.0")
        diff = compare_manifests(left, dict(left))
        assert diff["same_commit"] is True
        assert diff["same_fingerprint"] is True
        assert diff["version_diff"] == {}
        assert diff["component_diff"] == {}

    def test_detects_commit_change(self):
        """检测 commit 变化。"""
        diff = compare_manifests(self._manifest("a" * 40, "h1", "1.0.0"),
                                 self._manifest("b" * 40, "h1", "1.0.0"))
        assert diff["same_commit"] is False

    def test_detects_version_change(self):
        """检测版本变化并给出 from/to。"""
        diff = compare_manifests(self._manifest("a" * 40, "h1", "1.0.0"),
                                 self._manifest("a" * 40, "h1", "1.1.0"))
        assert diff["version_diff"]["package"] == {"from": "1.0.0", "to": "1.1.0"}

    def test_detects_component_change(self):
        """检测组件哈希变化。"""
        diff = compare_manifests(self._manifest("a" * 40, "h1", "1.0.0"),
                                 self._manifest("a" * 40, "h2", "1.0.0"))
        assert diff["component_diff"]["python_source"] == {"from": "h1", "to": "h2"}

    def test_handles_empty_manifests(self):
        """空清单不报错。"""
        diff = compare_manifests({}, {})
        assert diff["same_commit"] is True
        assert diff["version_diff"] == {}


class TestReleaseManifestDataclass:
    """ReleaseManifest 结构。"""

    def test_fingerprint_without_git(self):
        """无 git 时指纹仍可计算。"""
        manifest = ReleaseManifest(release_id="r", created_at="t")
        assert len(manifest.fingerprint()) == 64

    def test_fingerprint_reflects_components(self):
        """组件变化改变指纹。"""
        base = ReleaseManifest(release_id="r", created_at="t")
        base.components = {"src": {"content_sha256": "h1"}}
        other = ReleaseManifest(release_id="r", created_at="t")
        other.components = {"src": {"content_sha256": "h2"}}
        assert base.fingerprint() != other.fingerprint()
