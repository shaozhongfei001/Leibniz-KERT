"""合同 `enum` 与**单一源**一致性（机械核对；D-27 + A1 层 1 + **D-28 层 2**）。

纪律（与 `test_gate_state_single_source.py` 同族，不用行号定位 —— schema **按名查找**，行位移不致失效）：

- **等值** = `list(源)`；**严格子集**必须**显式登记到** :data:`SUBSET_DECLARATIONS` **并写明非空理由**，
  否则红 —— 禁止"合同悄悄写窄"（D-27 的成因正是**合同 4 值 / 源 9 值**长期无人发现）。
- **防空转**：核对项数有下限，且每条的两侧都不得为空。
- **两向敏感**：① 只改**命名源** ⇒ 红（:func:`test_source_mutation_is_detected`）；
  ② 只改**合同 enum** ⇒ 红（:func:`test_contract_enum_mutation_is_detected`，在**内存副本**上变异，
  不写 `specs/**`）。
"""

from __future__ import annotations

import copy
from pathlib import Path

import pytest
import yaml

from kert.application.interaction_memory import DECAY_RULES, MEMORY_CATEGORIES
from kert.application.service_proposal import GATE_STATES, OVERALL_READINESS_STATES
from kert.domain.activation_plan import SCHEMA as ACTIVATION_PLAN_SCHEMA
from kert.domain.contracts.specs import JOB_STATUS_SCHEMA
from kert.domain.health import SKILL_HEALTH_STATES
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
    # D-28 层 2：gate 语义域（清单 §2 #12/#13 点名的"同域字面量地图"）——
    # 源在 `service_proposal`（生产者同模块），展示侧派生、生产者无字面量由
    # `test_gate_state_single_source.py` 另钉；此处钉**合同 enum == 命名源**。
    ("GateChecklistItem", "state", list(GATE_STATES)),
    # D-28 层 2：同一对象的另一字段 `overallReadiness`（{READY, BLOCKED}）——
    # 此前**只有具名常量、无合同核对**（本批补的就是这一格）。
    ("GateRecommendations", "overallReadiness", list(OVERALL_READINESS_STATES)),
    # D-28 层 2：技能健康域（清单 §2 #2）——源 `kert.domain.health`，生产者为
    # `api/server.py:skill_health()`（其函数体内不得再有字面量，见
    # `test_health_status_single_source.py`）。
    ("SkillHealthResponse", "status", list(SKILL_HEALTH_STATES)),
    # D-28 层 2 第三片：**文件合同 schema 标签域**（清单 #15 `JobStatusData.schema`）——
    # 源 `domain/contracts/specs.JOB_STATUS_SCHEMA`：声明方（SchemaSpec）与写入方
    # （`application/jobs.py:_write_status`）共用；生产者侧由
    # `test_contract_tags_single_source.py` 走真实写入路径钉住。
    ("JobStatusData", "schema", [JOB_STATUS_SCHEMA]),
    # D-28 层 2 第三片（清单 #21 `ActivationPlan.schema`）——源**已存在**
    # （`domain/activation_plan.SCHEMA`），本批只补"合同 enum == 命名源"这格。
    ("ActivationPlan", "schema", [ACTIVATION_PLAN_SCHEMA]),
)


def _enum(spec: dict, schema: str, field: str) -> list:
    """按 **schema 名 / 字段名**取合同 `enum`（不依赖行号）。"""
    schemas = spec["components"]["schemas"]
    assert schema in schemas, f"合同缺少 schema：{schema}"
    prop = schemas[schema]["properties"][field]
    enum = prop.get("enum")
    assert isinstance(enum, list) and enum, f"{schema}.{field} 未声明 enum：{prop!r}"
    return enum


def _assert_matches(spec: dict, mappings=MAPPINGS) -> int:
    """核对 ``spec`` 里的每一条映射；返回**实际核对项数**（供防空转下限判定）。

    不等值且非"已登记的真子集" ⇒ :class:`AssertionError`（把判定逻辑抽出来是为了让
    :func:`test_contract_enum_mutation_is_detected` 能在**内存副本**上做变异自证，
    而不必改 ``specs/**``）。

    ``mappings`` 可注入（默认 :data:`MAPPINGS`）⇒ **两向**变异都能在同一判据上做：
    注入"被改过的源"（:func:`test_source_mutation_is_detected`）或"被改过的合同"。
    """
    checked = 0
    for schema, field, source in mappings:
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
    return checked


def test_contract_enum_matches_single_source():
    """登记表里的每处合同 `enum` 必须等于其命名源（子集须显式登记理由，否则红）。"""
    spec = yaml.safe_load(SPEC.read_text(encoding="utf-8"))
    checked = _assert_matches(spec)
    # 防空转：本用例不得在"核对项为空/骤减"时静默通过（下限随登记项数同步抬高）
    assert checked >= 9, f"防空转：实际核对项数 {checked} 少于下限 9"
    assert len(MAPPINGS) >= 9, "防空转：映射表异常收缩"


@pytest.mark.parametrize("mode", ["changed_value", "narrowed"])
def test_contract_enum_mutation_is_detected(mode):
    """**方向 B 自证（自动化）**：合同 enum 被换值 / 被写窄 ⇒ 判据**必须**红。

    在**内存副本**上变异（不写 ``specs/**``）：若有人把判据改成"读常量自比"或短路，
    本用例会失去可红性 ⇒ 自动暴露（把一次性的手工自证固化成机械保护）。
    """
    spec = yaml.safe_load(SPEC.read_text(encoding="utf-8"))
    assert _assert_matches(spec) >= 9, "基线合同必须先通过（否则变异证明无意义）"

    checked = 0
    for schema, field, _source in MAPPINGS:
        key = f"{schema}.{field}"
        if key in SUBSET_DECLARATIONS:      # 子集档的"写窄"是已登记语义，另论
            continue
        mutated = copy.deepcopy(spec)
        enum = mutated["components"]["schemas"][schema]["properties"][field]["enum"]
        if mode == "changed_value":
            enum[0] = f"MUTANT_{enum[0]}"
        else:
            enum.pop()                      # 未登记的真子集 ⇒ 必须红
        with pytest.raises(AssertionError):
            _assert_matches(mutated)
        checked += 1
    assert checked >= 8, f"防空转：实际变异项数 {checked} 少于下限 8"


@pytest.mark.parametrize("mode", ["changed_value", "extended"])
def test_source_mutation_is_detected(mode):
    """**方向 A 自证**：只改**命名源**（合同文本一字不动）⇒ 判据**必须**红。

    为何必须钉这一向：只钉"合同被改"的话，判据可能退化成"读合同自比"（**永不红**）。
    本用例在**内存**里把源改坏（合同仍取真实文本）⇒ 判据恒真即失去可红性，自动暴露。
    子集档（:data:`SUBSET_DECLARATIONS`）不参与：源加宽后合同仍是**已登记**子集，属正常。
    """
    spec = yaml.safe_load(SPEC.read_text(encoding="utf-8"))
    checked = 0
    for schema, field, source in MAPPINGS:
        if f"{schema}.{field}" in SUBSET_DECLARATIONS:
            continue
        mutated = ([f"MUTANT_{v}" for v in source] if mode == "changed_value"
                   else list(source) + ["MUTANT_EXTRA"])
        with pytest.raises(AssertionError):
            _assert_matches(spec, [(schema, field, mutated)])
        checked += 1
    assert checked >= 8, f"防空转：实际变异项数 {checked} 少于下限 8"
