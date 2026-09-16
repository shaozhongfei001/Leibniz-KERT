"""内置本体资产的**供给面**（M7-⑤）：受控源 ``90_control/ontology/`` → 目标工作区，逐份留痕 sha256。

为什么单独成模块
----------------
- 资产语义（provenance / 漂移 / 角色）留在 :mod:`kert.domain.ontology_assets`；
  本模块只回答**"该供给哪些文件、供到哪里、源侧非法怎么办"**。
- 源目录与目标目录**都**取自 :func:`~kert.domain.ontology_assets.assets_dir`
  （写侧与读侧同源 ⇒ "装到哪里"与"从哪里读"不可能漂移，与 ``provision`` 纪律 3 同口径）。
- 在 M7-⑤ 之前，内置本体**不在** ``kert provision`` 的供给面内（由 ``ensure_assets()`` 显式引入），
  CI 的 e2e 供给就绪断言对它只发 warning；本模块是"把它纳入判据"的代码那一半。

口径（与 ``provision`` 既有纪律 7/8 完全对齐）
----------------------------------------------
1. **缺失 ⇒ 不供给**：受控源没有 ``PROVENANCE.json``（即没有内置本体资产）⇒ 清单为空、不报错
   （缺它不应让整个部署起不来）。
2. **在场即必须合法 ⇒ fail-closed**：``PROVENANCE.json`` 在场时，provenance 结构非法 /
   资产文件缺失 / 副本漂移（实际 sha256 与记录不符）⇒ **具名拒绝**
   （:class:`~kert.domain.errors.SchemaValidationError`，消息内带
   ``ONTOLOGY_ASSETS_PROVENANCE_INVALID`` / ``ONTOLOGY_ASSETS_ABSENT`` / ``ONTOLOGY_ASSET_DRIFT``）。
   理由同供给纪律 1：半供给、坏供给比不供给更危险。
3. **逐份 sha256 留痕**：清单里每一份都能由写侧 ``sha256_file`` 现算摘要
   （``provision_manifest.json`` 的 ``items[].sha256`` 与它同源）。

注：本模块**不联网**、不读 gits 仓；对源仓的比对仍只能由人类/QA 显式调用
``ontology_assets.drift_against_source``。
"""
from __future__ import annotations

from pathlib import Path

from .errors import SchemaValidationError
from .ontology_assets import (
    PROVENANCE_FILENAME,
    AssetsLoad,
    assets_dir,
    load_assets_from_dir,
)

DIRNAME_REL = "90_control/ontology"
"""供给面相对路径（与 ``assets_dir`` 同源，勿在别处再写一遍字面量）。"""


def source_has_assets(source: Path | str) -> bool:
    """受控源是否**声明**了内置本体资产（判据 = ``<src>/90_control/ontology/PROVENANCE.json`` 在场）。"""
    return (assets_dir(source) / PROVENANCE_FILENAME).is_file()


def source_assets(source: Path | str) -> AssetsLoad:
    """载入受控源的内置本体资产（按 provenance 校验；不覆盖、不联网）。"""
    return load_assets_from_dir(assets_dir(source))


def require_source_assets(source: Path | str) -> None:
    """源侧资产**在场即必须合法**（fail-closed）；不在场 ⇒ 直接返回（不供给，不报错）。

    :raises SchemaValidationError: provenance 非法 / 资产缺失 / 漂移（消息内带**具名**码）。
    """
    if not source_has_assets(source):
        return
    load = source_assets(source)
    if not load.allowed:
        raise SchemaValidationError(
            f"[{load.code}] 供给源的内置本体资产不合法（{assets_dir(source)}）: {load.reason}")


def provision_pairs(workspace: Path | str, source: Path | str) -> list[tuple[str, Path, Path]]:
    """产出 ``(rel_path, 源文件, 目标文件)`` 清单（顺序确定，便于比对留痕）。

    与 ``provision._plan_items`` 的既有形状一致，可直接 ``pairs.extend(...)``。

    - 源未声明资产（无 ``PROVENANCE.json``）⇒ ``[]``（不供给）；
    - 源声明了资产但非法/漂移 ⇒ :class:`~kert.domain.errors.SchemaValidationError`
      （**先于任何写入**，由调用方在清单构建阶段就 fail-closed）。
    """
    require_source_assets(source)
    src_dir = assets_dir(source)
    if not src_dir.is_dir():
        return []
    dst_dir = assets_dir(workspace)
    return [(f"{DIRNAME_REL}/{p.name}", p, dst_dir / p.name)
            for p in sorted(src_dir.iterdir()) if p.is_file()]
