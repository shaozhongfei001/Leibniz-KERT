"""⑤ 本体供给面（集成）：`kert provision` 把 `90_control/ontology/**` 供进工作区 + 就绪判据（缺一件即红）。

正例：全量供给 ⇒ 5 份本体资产逐份落盘、与源逐字一致、且出现在供给留痕 `items[]` 的 sha256 台账；
反例 1（fail-closed）：源**声明了**本体资产但文件缺失 ⇒ 供给中止（`SchemaValidationError`）且**一份都不写**；
反例 2（判据有牙）：全量供给后删掉工作区里的一份本体资产 ⇒ 镜像 `.github/workflows/ci.yml` 的判据**变红**
       （不再是 M7-⑤ 之前的 warning-only）。
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (str(REPO_ROOT / "src"), str(REPO_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from kert.application.provision import provision_control_plane  # noqa: E402
from kert.domain.errors import SchemaValidationError  # noqa: E402
from kert.domain.workspace import init_workspace  # noqa: E402

SRC = REPO_ROOT / "examples" / "bank-front-knowledge-maps"
ONTOLOGY_REL = "90_control/ontology"
NON_DECL = {"README.md", "PROVENANCE.md"}   # 与 ci.yml 的"说明件不进判据"口径一致
ONTOLOGY_MIN = 5                            # OWL / SHACL / INSTANCES / R2RML + PROVENANCE.json
CORE_DECLARED = 11                          # ci.yml 的防空转下限（入库核心）


def _decl(root: Path, *, not_provisioned: tuple = ()) -> dict:
    """镜像 `.github/workflows/ci.yml` 的 `decl()`：90_control 逐份 sha256（说明件除外）。"""
    out = {}
    for p in (root / "90_control").rglob("*"):
        rel = p.relative_to(root).as_posix()
        if not p.is_file() or p.name in NON_DECL:
            continue
        if any(rel == d or rel.startswith(d + "/") for d in not_provisioned):
            continue
        out[rel] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def _judge(src: Path, ws: Path) -> dict:
    """CI 就绪判据本体（去掉 sys.exit）：源侧声明的每一份都必须在工作区存在且 sha256 一致。"""
    want = _decl(src)
    got = _decl(ws)
    assert len(want) >= CORE_DECLARED, f"防空转：源声明 {len(want)} < {CORE_DECLARED}"
    ont = sorted(k for k in want if k.startswith(ONTOLOGY_REL + "/"))
    assert len(ont) >= ONTOLOGY_MIN, f"防空转：本体声明 {len(ont)} < {ONTOLOGY_MIN}：{ont}"
    return {"missing": sorted(set(want) - set(got)),
            "diff": sorted(k for k in set(want) & set(got) if want[k] != got[k]),
            "ontology": ont}


@pytest.fixture
def target(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    init_workspace(ws)
    return ws


def test_provision_supplies_builtin_ontology_with_sha256_ledger(target):
    """正例：本体逐份落盘 + 与源逐字一致 + 出现在留痕 `items[]`（sha256 台账）。"""
    provision_control_plane(target, SRC)

    ont_dir = target / ONTOLOGY_REL
    assert ont_dir.is_dir(), "本体目录未被供给（M7-⑤ 未接线）"
    src_files = {p.name: p for p in (SRC / ONTOLOGY_REL).iterdir() if p.is_file()}
    assert len(src_files) >= ONTOLOGY_MIN, f"夹具失效：受控源本体只有 {len(src_files)} 份"
    for name, sp in src_files.items():
        dp = ont_dir / name
        assert dp.is_file(), f"未供给 {name}"
        assert dp.read_bytes() == sp.read_bytes(), f"{name} 内容与源不一致"

    manifest = json.loads((target / "90_control/catalog/provision_manifest.json").read_text("utf-8"))
    ledger = {it["relPath"]: it["sha256"] for it in manifest["items"]}
    for name, sp in src_files.items():
        rel = f"{ONTOLOGY_REL}/{name}"
        assert rel in ledger, f"供给留痕缺 {rel}"
        assert ledger[rel] == hashlib.sha256(sp.read_bytes()).hexdigest(), rel

    j = _judge(SRC, target)
    assert j["missing"] == [] and j["diff"] == [], j
    assert len(j["ontology"]) >= ONTOLOGY_MIN


def test_negative_source_declaring_a_missing_asset_aborts_everything(tmp_path, target):
    """反例 1：源声明了本体资产但**文件缺失** ⇒ 供给中止（fail-closed），**一份都不写**。"""
    src = tmp_path / "src"
    shutil.copytree(SRC, src)
    (src / ONTOLOGY_REL / "products.ttl").unlink()

    with pytest.raises(SchemaValidationError) as ei:
        provision_control_plane(target, src)
    assert "ONTOLOGY_ASSETS_ABSENT" in str(ei.value) and "products.ttl" in str(ei.value)
    assert not (target / "90_control/catalog/provision_manifest.json").exists(), "中止时不得写留痕"
    assert list((target / "90_control/catalog").glob("KM-*.json")) == [], "中止时不得写任何一份"


def test_negative_one_asset_removed_from_workspace_is_red(target):
    """反例 2：**判据有牙** —— 工作区少一份本体资产 ⇒ 镜像 CI 判据必红（不是 warning-only）。"""
    provision_control_plane(target, SRC)
    assert _judge(SRC, target)["missing"] == [], "前置：全量供给后判据应为绿"

    (target / ONTOLOGY_REL / "gits-core.shacl.ttl").unlink()

    after = _judge(SRC, target)
    assert f"{ONTOLOGY_REL}/gits-core.shacl.ttl" in after["missing"], after
