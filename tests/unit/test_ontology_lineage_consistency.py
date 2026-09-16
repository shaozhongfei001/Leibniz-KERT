"""T1：物化血缘的「本体输入面」—— 字段口径（**不新造键名**）+ 与计划的**一致性校验**。

判定：**拒绝**（fail-closed），理由见 ``kert.domain.ontology_reference.check_lineage_ontology``。

覆盖：正例（逐字一致 ⇒ 放行）×1；反例（强制比对项被改 / 缺必记字段）×2；
口径反例（``authoritySource`` 变化 ⇒ **仍放行**，依据既有 D-3：来源路径环境相关、不入判定项）。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (str(REPO_ROOT / "src"), str(REPO_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from kert.domain.activation_plan import ActivationPlanBuilder  # noqa: E402
from kert.domain.ontology_reference import (  # noqa: E402
    CODE_LINEAGE_ABSENT,
    CODE_LINEAGE_MISMATCH,
    CODE_LINEAGE_OK,
    LINEAGE_ONTOLOGY_ENFORCED,
    LINEAGE_ONTOLOGY_FIELDS,
    LINEAGE_ONTOLOGY_KEY,
    check_lineage_ontology,
    lineage_ontology_fields,
)

TASK = "MEETING_PREPARATION"


def _plan_ontology(ws):
    """计划的**本体引用解析结果**（可执行基准，非硬编码）。"""
    return ActivationPlanBuilder.load(ws).ontology_resolution()


def _lineage(ws) -> dict:
    """按口径产出一条"应记"的血缘 Front Matter（写入侧由 c20 负责，此处模拟其形状）。"""
    fields = lineage_ontology_fields(_plan_ontology(ws))
    assert fields is not None, "前置夹具失效：供给后本体引用应放行"
    return {LINEAGE_ONTOLOGY_KEY: dict(fields)}


def test_positive_lineage_records_exactly_the_declared_fields(ws_provisioned):
    """正例：键名 = 既有字段（不新造）+ 与计划逐字一致 ⇒ 放行。"""
    res = _plan_ontology(ws_provisioned)
    assert res.allowed, res.reason

    fields = lineage_ontology_fields(res)
    assert tuple(fields) == LINEAGE_ONTOLOGY_FIELDS, "血缘字段口径必须固定且不新造键名"
    assert fields["version"].startswith(f"{fields['contractId']}@sha256:"), fields["version"]

    chk = check_lineage_ontology(res, _lineage(ws_provisioned))
    assert chk.allowed, chk.reason
    assert chk.code == CODE_LINEAGE_OK


@pytest.mark.parametrize("key", LINEAGE_ONTOLOGY_ENFORCED)
def test_negative_mismatch_is_refused(ws_provisioned, key):
    """反例 1：强制比对项被改 ⇒ **拒绝**，并在 reason 中点名字段（可归因）。"""
    res = _plan_ontology(ws_provisioned)
    lin = _lineage(ws_provisioned)
    good = lin[LINEAGE_ONTOLOGY_KEY][key]
    lin[LINEAGE_ONTOLOGY_KEY][key] = ("0" if good[-1] != "0" else "1") + good[1:]

    chk = check_lineage_ontology(res, lin)
    assert not chk.allowed
    assert chk.code == CODE_LINEAGE_MISMATCH
    assert key in chk.reason, chk.reason


def test_negative_missing_field_is_refused(ws_provisioned):
    """反例 2：缺必记字段 / 缺整个本体块 ⇒ **拒绝**（``ABSENT``）。"""
    res = _plan_ontology(ws_provisioned)
    lin = _lineage(ws_provisioned)
    del lin[LINEAGE_ONTOLOGY_KEY]["version"]

    chk = check_lineage_ontology(res, lin)
    assert chk.code == CODE_LINEAGE_ABSENT
    assert "version" in chk.reason

    assert check_lineage_ontology(res, {}).code == CODE_LINEAGE_ABSENT
    assert check_lineage_ontology(res, {LINEAGE_ONTOLOGY_KEY: "not-an-object"}).code \
        == CODE_LINEAGE_ABSENT


def test_authority_source_is_recorded_but_not_enforced(ws_provisioned):
    """口径反例：来源路径变化 ⇒ **仍放行**（D-3：环境相关，计划本身即不入 hash）。"""
    res = _plan_ontology(ws_provisioned)
    lin = _lineage(ws_provisioned)
    lin[LINEAGE_ONTOLOGY_KEY]["authoritySource"] = "vendor/ontology/other-copy.yaml"

    assert "authorityRepo" not in LINEAGE_ONTOLOGY_ENFORCED
    assert "authoritySource" not in LINEAGE_ONTOLOGY_ENFORCED
    assert check_lineage_ontology(res, lin).allowed, "来源路径属记录项，不得据此拒绝"
