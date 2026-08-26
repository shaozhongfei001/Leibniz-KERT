"""pytest 共享夹具。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


@pytest.fixture
def ws(tmp_path):
    """已初始化的临时工作区。"""
    from dkws.domain import workspace as ws_mod

    ws_mod.init_workspace(tmp_path)
    return tmp_path


@pytest.fixture
def proj_version():
    """返回读取活动服务投影版本的函数（避免测试硬编码日期）。"""
    import re

    def _get(ws) -> str:
        cur = Path(ws) / "04_serve" / "product_knowledge" / "CURRENT.md"
        if not cur.is_file():
            return ""
        m = re.search(r"^target_version:\s*\"?([^\n\" ]+)",
                      cur.read_text(encoding="utf-8"), re.M)
        return m.group(1) if m else ""

    return _get
