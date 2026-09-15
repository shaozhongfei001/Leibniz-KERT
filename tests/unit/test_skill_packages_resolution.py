"""外部 Skill 包根目录解析的 fail-closed 语义（D-E2E-01 / 缺口 F-E2E-02）。

背景：该路径原先由 ``Path(__file__).resolve().parents[3]`` 相对定位，并在路径无效时
**静默**回落为 ``None`` —— 于是「技能消失」只在运行时以 ``UNKNOWN_SKILL`` 显现，
且没有任何日志线索。真实 CI（run 34845070952）的 10 条失败即由此产生：
e2e job 用非 editable 安装，``parents[3]`` 落在 site-packages 之外，
7 个 ``bank-front-*`` 技能全部未注册。

本测试锁定修复后的语义：
1. **显式配置**（入参或 ``KERT_SKILL_PACKAGES``）无效 → 必须抛错，绝不静默降级；
2. 入参优先级高于环境变量；
3. 空白的 ``KERT_SKILL_PACKAGES`` 视为未设置（不得因此抛错）。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kert.api.server import (
    DEFAULT_SKILL_PACKAGES,
    SKILL_PACKAGES_ENV,
    resolve_skill_packages,
)


def _make_packages(root: Path) -> Path:
    """构造一个合法的 Skill 包根目录（含 ``<skill>/SKILL.md``）。"""
    skill = root / "demo-skill"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nname: demo-skill\nversion: 1.0.0\n---\n演示技能\n", encoding="utf-8")
    return root


def test_explicit_valid_path_is_used(tmp_path: Path) -> None:
    pkgs = _make_packages(tmp_path / "pkgs")
    assert resolve_skill_packages(pkgs) == pkgs


def test_explicit_dir_without_any_skill_md_is_rejected(tmp_path: Path) -> None:
    """目录存在但没有 <skill>/SKILL.md —— 与「不存在」同样必须失败。"""
    empty = tmp_path / "pkgs"
    empty.mkdir()
    with pytest.raises(ValueError):
        resolve_skill_packages(empty)


def test_explicit_nonexistent_path_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        resolve_skill_packages(tmp_path / "does-not-exist")


def test_env_var_invalid_is_rejected(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(SKILL_PACKAGES_ENV, str(tmp_path / "nope"))
    with pytest.raises(ValueError):
        resolve_skill_packages()


def test_env_var_valid_is_used(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pkgs = _make_packages(tmp_path / "envpkgs")
    monkeypatch.setenv(SKILL_PACKAGES_ENV, str(pkgs))
    assert resolve_skill_packages() == pkgs


def test_param_takes_precedence_over_env(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    param = _make_packages(tmp_path / "param")
    monkeypatch.setenv(SKILL_PACKAGES_ENV, str(tmp_path / "nope"))
    assert resolve_skill_packages(param) == param


def test_blank_env_var_is_treated_as_unset(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """空白视为未设置：不得因「显式配置」而抛错。"""
    monkeypatch.setenv(SKILL_PACKAGES_ENV, "   ")
    assert resolve_skill_packages() in (None, DEFAULT_SKILL_PACKAGES)
