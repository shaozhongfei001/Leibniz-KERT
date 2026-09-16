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
    from kert.domain import workspace as ws_mod

    ws_mod.init_workspace(tmp_path)
    return tmp_path


#: 受控控制面元数据源（知识地图 / 路由策略 / 本体引用）。
CONTROL_PLANE_SOURCE = Path(__file__).resolve().parent.parent / "examples" / "bank-front-knowledge-maps"


@pytest.fixture
def ws_provisioned(ws):
    """已在 ``ws`` 上供给控制面的工作区。

    M7.3 ⑤b-full 起，customer-engagement 三个技能**按计划**读取资产；M7 ② 起
    **另加 4 个技能**（``bank-front-supply-chain-graph`` / ``SP-15`` / ``SP-20`` / ``SP-21``）
    同口径纳入计划门禁 ⇒ **共 7 个技能**都是「计划被拒即拒绝执行」（fail-closed）
    ⇒ 任何执行这 7 个技能的测试都必须用**已供给**的工作区；
    未供给/无工作区得到的是**具名拒绝**，那本身是有意义的用例，见
    ``tests/integration/test_skill_routing_trace.py`` 与 ``tests/integration/test_skill_route_gate.py``。
    """
    from kert.application.provision import provision_control_plane

    provision_control_plane(ws, CONTROL_PLANE_SOURCE)
    return ws


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
