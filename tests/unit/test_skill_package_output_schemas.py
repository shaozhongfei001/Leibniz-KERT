"""技能包 `references/output-schema.md` 的**示例块**与加载器抽取的一致性（D-49）。

存在理由（实测缺陷，2026-09-17）：三个技能包的示例块是**伪 JSON**（把评分区间写成 `1-5`、
把布尔示例写成 `true | false`）⇒ `json.loads` 失败；而加载器当时**退回"按缩进猜键"**，
把 4 空格缩进的**嵌套**键（如 `dimensions.policy`）当成**顶层必含键** ⇒
**正确的嵌套输出被 fail-closed 拒绝**，且报错只说"输出结构不符" ——
**上游缺件被下游 fail-closed 掩盖**（本地实测：`bank-front-eight-dimension` 的 `schema_keys` 从
真值 10 个被污染成 18 个，两个技能因此失败）。

本文件钉两件事：
① 每个包的示例块**必须能解析**（这就能挡住当初那三个坏文件）；
② 加载器抽出的键**必须等于**该块的真实**顶层**键（不得混入嵌套键）；
③ 兜底路径**有牙**：喂一个伪 JSON 块 ⇒ 只取顶层键 + 记具名警告（不是静默、也不是猜）。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from kert.application.skills import SkillExecutionService, _top_level_keys

REPO_ROOT = Path(__file__).resolve().parents[2]
ROOTS = (REPO_ROOT / "examples" / "bank-front-skills", REPO_ROOT / "skills" / "customer-engagement")
FENCE = re.compile(r"```json\n([\s\S]*?)\n```")


def _packages() -> list[Path]:
    out: list[Path] = []
    for root in ROOTS:
        if root.is_dir():
            out.extend(sorted(p for p in root.iterdir() if (p / "SKILL.md").is_file()))
    assert out, "未找到任何技能包（检查 ROOTS）"
    return out


def _block(pkg: Path) -> str:
    f = pkg / "references" / "output-schema.md"
    assert f.is_file(), f"缺少 output-schema.md: {pkg.name}"
    m = FENCE.search(f.read_text(encoding="utf-8"))
    assert m, f"未找到 ```json 块: {pkg.name}"
    return m.group(1)


# ── ① 示例块必须可解析（挡住"伪 JSON"）──


def test_every_package_schema_block_is_valid_json() -> None:
    broken: list[str] = []
    for pkg in _packages():
        try:
            obj = json.loads(_block(pkg))
        except Exception as exc:  # noqa: BLE001
            broken.append(f"{pkg.name}: {exc}")
            continue
        assert isinstance(obj, dict), f"{pkg.name}: 顶层必须是对象"
    assert not broken, (
        "以下技能包的 output-schema.md 示例块**不是合法 JSON**（会让加载器退回兜底路径）：\n  "
        + "\n  ".join(broken)
    )


# ── ② 加载器抽出的键 == 真实顶层键（不得混入嵌套键）──


@pytest.mark.parametrize("root_kind", ("bank-front", "customer-engagement"))
def test_loader_extracts_true_top_level_keys(tmp_path: Path, root_kind: str) -> None:
    root = ROOTS[0] if root_kind == "bank-front" else ROOTS[1]
    if not root.is_dir():
        pytest.skip(f"{root} 不存在")
    svc = SkillExecutionService(workspace=tmp_path, profile="dev", skill_packages=root)
    checked = 0
    for pkg in sorted(p for p in root.iterdir() if (p / "SKILL.md").is_file()):
        block = _block(pkg)
        expected = list(json.loads(block).keys())      # 真值：块的真实顶层键
        # 加载器用 SKILL.md front matter 的 name 作键（缺省退回目录名）⇒ 这里按同一口径取键
        fm = (pkg / "SKILL.md").read_text(encoding="utf-8")
        m = re.search(r"^name:\s*(.+)$", fm, re.M)
        loaded_name = (m.group(1).strip() if m else pkg.name)
        assert loaded_name in svc._packages, f"未加载到包 {pkg.name}（期望键 {loaded_name}）"
        got = list(svc._packages[loaded_name].get("schema_keys") or [])
        assert got == expected, (
            f"{pkg.name}: 抽取键与真实顶层键不一致\n  抽取={got}\n  真值={expected}"
        )
        checked += 1
    assert checked > 0


# ── ③ 兜底路径有牙（伪 JSON ⇒ 只取顶层键 + 具名警告）──


PSEUDO_BLOCK = """{
  "schemaVersion": "1.0",
  "dimensions": {
    "policy": { "score": 1-5 },
    "market": { "score": 1-5 }
  },
  "warnings": []
}"""


def test_fallback_never_mixes_nested_keys() -> None:
    keys = _top_level_keys(PSEUDO_BLOCK)
    assert keys == ["schemaVersion", "dimensions", "warnings"], keys
    for nested in ("policy", "market"):
        assert nested not in keys, f"嵌套键 {nested} 不得被当成顶层键"


def test_loader_flags_unparsable_schema_block(tmp_path: Path) -> None:
    root = tmp_path / "packages"
    pkg = root / "probe-pkg"
    (pkg / "references").mkdir(parents=True)
    (pkg / "SKILL.md").write_text("---\nname: probe-pkg\nversion: 1.0.0\n---\n指令\n", encoding="utf-8")
    (pkg / "references" / "output-schema.md").write_text(
        "示例：\n\n```json\n" + PSEUDO_BLOCK + "\n```\n", encoding="utf-8"
    )
    svc = SkillExecutionService(workspace=tmp_path / "ws", profile="dev", skill_packages=root)
    meta = svc._packages["probe-pkg"]
    # 兜底：只取顶层键（不猜缩进）
    assert list(meta["schema_keys"]) == ["schemaVersion", "dimensions", "warnings"]
    # 且**不是静默**：必须留下具名警告
    assert meta.get("schema_warning"), "伪 JSON 必须留下具名警告（不得静默降级）"
    assert "非合法 JSON" in meta["schema_warning"]


def test_warning_is_visible_in_trace(tmp_path: Path) -> None:
    """警告要能被人在 trace 里看到（status=degraded），否则等于没登记。"""
    root = tmp_path / "packages"
    pkg = root / "probe-pkg2"
    (pkg / "references").mkdir(parents=True)
    (pkg / "SKILL.md").write_text("---\nname: probe-pkg2\nversion: 1.0.0\n---\n指令\n", encoding="utf-8")
    (pkg / "references" / "output-schema.md").write_text(
        "示例：\n\n```json\n" + PSEUDO_BLOCK + "\n```\n", encoding="utf-8"
    )
    svc = SkillExecutionService(workspace=tmp_path / "ws2", profile="dev", skill_packages=root)
    res = svc.execute("probe-pkg2", "req-probe", {"context": {}})
    phases = [(t.get("phase"), t.get("status")) for t in res.assembly_trace]
    assert ("schema", "degraded") in phases, phases
