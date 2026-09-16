"""D-28 层 2：技能健康域**单源化**（源 ↔ 生产者 ↔ 域边界）的机械核对。

三处分工（**不重复钉同一条**）：

- **源** = ``kert.domain.health.SKILL_HEALTH_STATES``（``ok`` / ``degraded``）—— 本文件 ①；
- **生产者** = ``api/server.py`` 的 ``skill_health()``（``GET /api/skill/health``）—— 本文件 ②；
- **合同** = ``SkillHealthResponse.status.enum`` —— 由
  ``tests/unit/test_contract_enum_single_source.py`` 的 ``MAPPINGS`` 核对（本文件不重复）；
- **域边界** —— 本文件 ③：轨迹条目状态域（``assembly-trace.schema.json``）**不是**同一域，禁止合并。

⚠ 同批**不**包含``/v1/health`` 的 ``data.status``（大写 ``OK``/``DEGRADED``、形状亦与合同
``HealthResponse`` 不同）—— 那是**另一处发现**（登记待裁），见 ``kert/domain/health.py`` 的边界说明。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (str(REPO_ROOT / "src"), str(REPO_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from kert.domain.health import (  # noqa: E402
    HEALTH_DEGRADED,
    HEALTH_OK,
    SKILL_HEALTH_STATES,
)

SERVER_SRC = REPO_ROOT / "src" / "kert" / "api" / "server.py"
TRACE_SCHEMA = REPO_ROOT / "docs" / "contracts" / "schemas" / "assembly-trace.schema.json"


# --------------------------------------------------------------------------- #
# ① 源自身
# --------------------------------------------------------------------------- #

def test_source_is_closed_ordered_and_lowercase():
    """值域闭集、顺序=恶化方向、且是**小写**健康词汇（与轨迹域的大写/混合词汇不同）。"""
    assert SKILL_HEALTH_STATES == ("ok", "degraded")
    assert (HEALTH_OK, HEALTH_DEGRADED) == SKILL_HEALTH_STATES
    assert len(set(SKILL_HEALTH_STATES)) == len(SKILL_HEALTH_STATES), "值域必须互异"
    assert all(s == s.lower() and s.strip() for s in SKILL_HEALTH_STATES), SKILL_HEALTH_STATES


# --------------------------------------------------------------------------- #
# ② 生产者（真实端点）
# --------------------------------------------------------------------------- #

def test_producer_emits_only_single_source_values(ws):
    """`GET /api/skill/health` 的 `status` 必须落在单一源内（走真实应用）。"""
    from kert.api.server import create_app

    client = TestClient(create_app(ws, service_id="product_knowledge"))
    body = client.get("/api/skill/health").json()
    assert body["status"] in SKILL_HEALTH_STATES, body
    # 「立源」是**零行为变化**：把当前**实际字节值**钉住 ⇒ 任何"顺手改值"都会在此显形。
    assert body["status"] == "ok", body
    assert isinstance(body["skills"], list) and body["skills"], body
    assert set(body) == {"status", "service", "skills"}, "响应形状与合同闭集声明一致"


def test_producer_body_has_no_status_literals():
    """**防复发**：`skill_health()` 函数体内不得再出现健康状态字面量（只许用具名常量）。

    与 `test_gate_state_single_source.py::test_producer_method_has_no_stray_state_literals`
    同口径：把"改了源却漏改生产者"从"靠人记得"变成机械红灯。
    """
    src = SERVER_SRC.read_text(encoding="utf-8")
    assert "def skill_health" in src, "未找到生产者（实现可能改名：请同步本用例）"
    body = src.split("def skill_health", 1)[1].split("@app.", 1)[0]
    strays = [st for st in SKILL_HEALTH_STATES if f'"{st}"' in body]
    assert strays == [], f"生产者函数体仍有状态字面量（须改用单一源常量）: {strays}"


# --------------------------------------------------------------------------- #
# ③ 域边界（防止"看上去一致"被合并）
# --------------------------------------------------------------------------- #

def test_trace_status_vocabulary_is_a_different_domain():
    """轨迹条目状态域（`assembly-trace.schema.json`）**不等**于健康域 ⇒ 禁止合并取值域。"""
    trace = json.loads(TRACE_SCHEMA.read_text(encoding="utf-8"))
    trace_statuses = set(trace["properties"]["status"]["enum"])
    assert trace_statuses != set(SKILL_HEALTH_STATES), "两域取值集合相同 ⇒ 请重新裁定归属"
    assert not (set(SKILL_HEALTH_STATES) & {"failed", "blocked", "skipped"}), (
        "健康域不得吞并轨迹域取值（把健康状态写成 failed/blocked 会污染两处判据）")
