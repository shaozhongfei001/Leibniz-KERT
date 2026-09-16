"""合同 `enum` 与**单一源**一致性（机械核对；D-27 + A1 层 1）。

纪律（与 `test_gate_state_single_source.py` 同族，不用行号定位 —— schema **按名查找**，行位移不致失效）：

- **等值** = `list(源)`；**严格子集**必须**显式登记到** :data:`SUBSET_DECLARATIONS` **并写明非空理由**，
  否则红 —— 禁止"合同悄悄写窄"（D-27 的成因正是**合同 4 值 / 源 9 值**长期无人发现）。
- **防空转**：核对项数有下限，且每条的两侧都不得为空。
"""

from __future__ import annotations

from pathlib import Path

import yaml

from kert.application.interaction_memory import DECAY_RULES, MEMORY_CATEGORIES
from kert.domain.states import JOB_STATES

SPEC = Path(__file__).resolve().parents[2] / "specs" / "kert-openapi-v1.yaml"

#: 合同 `enum` 允许为**严格子集**的显式登记：键＝`Schema.field`，值＝**非空理由**（空串视为违规）。
#: 目前 **1 条**（其余均为"等值"档）；若日后确需再写窄，必须在此逐条写明理由，否则红。
SUBSET_DECLARATIONS: dict[str, str] = {
    "AsyncAcceptedResponse.status": (
        "202 受理体的 `status` **恒为** `PENDING`（实现为 `server.py` 的**手写信封**，不走 `_response()`）"
        "⇒ 声明为 `JOB_STATES` 的**单值子集**：这是**语义**，不是漏登记；"
        "若要改宽或改值，必须**显式改本登记**（不得无声改动）。"),
}

#: （schema, field, 单一源）—— 源与合同 `enum` **必须等值**（除非在上表显式登记）
MAPPINGS: tuple[tuple[str, str, list], ...] = (
    ("JobStatusData", "status", list(JOB_STATES)),                 # D-27（1.6.1 值域更正）
    ("CandidateMemory", "category", list(MEMORY_CATEGORIES)),      # A1 层 1
    ("CandidateMemory", "suggestedDecayRule", list(DECAY_RULES)),  # A1 层 1
    ("AsyncAcceptedResponse", "status", list(JOB_STATES)),         # 202 受理体：子集，见上表
)


def _enum(spec: dict, schema: str, field: str) -> list:
    """按 **schema 名 / 字段名**取合同 `enum`（不依赖行号）。"""
    schemas = spec["components"]["schemas"]
    assert schema in schemas, f"合同缺少 schema：{schema}"
    prop = schemas[schema]["properties"][field]
    enum = prop.get("enum")
    assert isinstance(enum, list) and enum, f"{schema}.{field} 未声明 enum：{prop!r}"
    return enum


def test_contract_enum_matches_single_source():
    """三处合同 `enum` 必须等于其命名源（子集须显式登记理由，否则红）。"""
    spec = yaml.safe_load(SPEC.read_text(encoding="utf-8"))
    checked = 0
    for schema, field, source in MAPPINGS:
        key = f"{schema}.{field}"
        assert source, f"{key} 的**单一源为空**（防空转：空源会让断言无意义）"
        enum = _enum(spec, schema, field)
        if enum == source:
            checked += 1
            continue
        if set(enum) < set(source):  # 严格子集
            reason = SUBSET_DECLARATIONS.get(key, "")
            assert reason.strip(), (
                f"{key} 的合同 enum 是命名源的**真子集**（缺 {sorted(set(source) - set(enum))}）"
                f"⇒ 必须显式登记到 SUBSET_DECLARATIONS 并写明理由，"
                f"否则视为「合同悄悄写窄」（D-27 的成因）")
            checked += 1
            continue
        raise AssertionError(
            f"{key} 合同 enum 与命名源不一致：合同={enum}，源={source}"
            f"（合同多出={sorted(set(enum) - set(source))}，合同缺少={sorted(set(source) - set(enum))}）")
    # 防空转：本用例不得在"核对项为空/骤减"时静默通过（下限随登记项数同步抬高）
    assert checked >= 4, f"防空转：实际核对项数 {checked} 少于下限 4"
    assert len(MAPPINGS) >= 4, "防空转：映射表异常收缩"
