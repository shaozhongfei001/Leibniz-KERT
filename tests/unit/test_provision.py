"""控制面供给测试（M7.3 第五步）。

覆盖顺序纪律：**先全量校验 → 后逐份原子写入**（fail-closed）、幂等、dry-run、
不删既有文件、以及"供给后运行时路由真的可用"的端到端链。
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from kert.application.provision import (
    ACTION_CREATED,
    ACTION_UNCHANGED,
    ACTION_UPDATED,
    provision_control_plane,
)
from kert.domain.errors import SchemaValidationError, UsageError
from kert.domain.knowledge_source import (
    CODE_DECLARATION_ABSENT,
    FILENAME as KNOWLEDGE_SOURCES_FILENAME,
    resolve_declaration,
)
from kert.domain.workspace import init_workspace

REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE = REPO_ROOT / "examples" / "bank-front-knowledge-maps"
CATALOG = "90_control/catalog"
SCHEMA_DIR = "90_control/schema"
ONTOLOGY_DIR = "90_control/ontology"

#: 内置本体资产（M7-⑤ 起由 `kert provision` 供给）：4 件资产 + provenance（信任锚）
ONTOLOGY_FILES = ("gits-core.owl.ttl", "gits-core.shacl.ttl", "products.ttl",
                  "customer-source-mapping.r2rml.ttl", "PROVENANCE.json")

#: 供给清单文件数（3 张地图 + route_policy + ontology_reference + knowledge_sources
#: + 内置本体 ONTOLOGY_FILES）
PROVISION_ITEM_COUNT = 6 + len(ONTOLOGY_FILES)


@pytest.fixture
def target(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    init_workspace(ws)
    return ws


@pytest.fixture
def source_copy(tmp_path: Path) -> Path:
    """可篡改的源副本（避免污染受控 example）。"""
    dst = tmp_path / "src"
    shutil.copytree(SOURCE, dst)
    return dst


# --------------------------------------------------------------------------- #
# 正常供给
# --------------------------------------------------------------------------- #

def test_creates_all_control_plane_files(target):
    r = provision_control_plane(target, SOURCE)

    assert r.map_count == 3
    assert r.policy_id == "RP-KERT-BANKFRONT-001"
    assert r.policy_version == "1.0.0"
    assert r.counts() == {ACTION_CREATED: PROVISION_ITEM_COUNT, ACTION_UPDATED: 0,
                          ACTION_UNCHANGED: 0}
    assert r.changed() is True
    assert r.manifest_rel == f"{CATALOG}/provision_manifest.json"

    assert sorted(p.name for p in (target / CATALOG).glob("KM-*.json")) == [
        "KM-CORP-RM-MEETING.json", "KM-CORP-RM-OUTREACH.json", "KM-CORP-RM-PREVISIT.json"]
    assert (target / SCHEMA_DIR / "route_policy.json").is_file()
    assert (target / SCHEMA_DIR / "ontology_reference.json").is_file()
    # M7.1-A 第 4 类：知识源能力声明（若从 _plan_items 移除本项，本断言必红）
    assert (target / SCHEMA_DIR / KNOWLEDGE_SOURCES_FILENAME).is_file()

    manifest = json.loads((target / r.manifest_rel).read_text(encoding="utf-8"))
    assert manifest["schema"] == "control_plane_provision/v1"
    assert len(manifest["items"]) == PROVISION_ITEM_COUNT
    assert all(len(i["sha256"]) == 64 for i in manifest["items"])
    assert sorted(i["relPath"] for i in manifest["items"]) == sorted([
        f"{CATALOG}/KM-CORP-RM-MEETING.json",
        f"{CATALOG}/KM-CORP-RM-OUTREACH.json",
        f"{CATALOG}/KM-CORP-RM-PREVISIT.json",
        f"{SCHEMA_DIR}/route_policy.json",
        f"{SCHEMA_DIR}/ontology_reference.json",
        f"{SCHEMA_DIR}/{KNOWLEDGE_SOURCES_FILENAME}",
        # M7-⑤：内置本体资产（含 provenance）—— 若从供给面移除任一份，本断言必红
        *[f"{ONTOLOGY_DIR}/{n}" for n in ONTOLOGY_FILES],
    ])


def test_idempotent_second_run_rewrites_nothing(target):
    first = provision_control_plane(target, SOURCE)
    assert first.changed() is True

    mtimes = {p.name: p.stat().st_mtime_ns for p in (target / CATALOG).glob("KM-*.json")}

    second = provision_control_plane(target, SOURCE)
    assert second.counts() == {ACTION_CREATED: 0, ACTION_UPDATED: 0,
                               ACTION_UNCHANGED: PROVISION_ITEM_COUNT}
    assert second.changed() is False
    assert {p.name: p.stat().st_mtime_ns for p in (target / CATALOG).glob("KM-*.json")} == mtimes


def test_source_change_yields_updated_only_for_that_file(target, source_copy):
    provision_control_plane(target, source_copy)

    p = source_copy / CATALOG / "KM-CORP-RM-MEETING.json"
    doc = json.loads(p.read_text(encoding="utf-8"))
    doc["title"] = "会面准备知识地图（改）"
    p.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")

    r = provision_control_plane(target, source_copy)
    assert r.counts() == {ACTION_CREATED: 0, ACTION_UPDATED: 1,
                          ACTION_UNCHANGED: PROVISION_ITEM_COUNT - 1}
    updated = [i for i in r.items if i.action == ACTION_UPDATED]
    assert updated[0].rel_path == f"{CATALOG}/KM-CORP-RM-MEETING.json"
    assert "（改）" in (target / CATALOG / "KM-CORP-RM-MEETING.json").read_text(encoding="utf-8")


def test_dry_run_writes_nothing(target):
    r = provision_control_plane(target, SOURCE, dry_run=True)
    assert r.dry_run is True
    assert r.changed() is True  # 会新建，但未落盘
    assert list((target / CATALOG).glob("KM-*.json")) == []
    assert not (target / SCHEMA_DIR / "route_policy.json").exists()
    assert not (target / CATALOG / "provision_manifest.json").exists()


# --------------------------------------------------------------------------- #
# fail-closed：源非法 ⇒ 一份都不写
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("bad_name", [
    "KM-CORP-RM-MEETING.json",
    "KM-CORP-RM-OUTREACH.json",
    "KM-CORP-RM-PREVISIT.json",
])
def test_invalid_map_writes_nothing(target, source_copy, bad_name):
    """**逐份**破坏源内每一张地图：任一份非法 ⇒ 一份都不写。

    必须逐份参数化（不能只坏第一份）：只坏第一份时，"实现只校验第一份就开写"
    这类错误仍会通过——而那恰恰是"半供给"最可能的形态。
    """
    bad = source_copy / CATALOG / bad_name
    doc = json.loads(bad.read_text(encoding="utf-8"))
    del doc["mapId"]          # 破坏必需字段
    bad.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(SchemaValidationError):
        provision_control_plane(target, source_copy)

    # 关键：**一份都没写**（半供给会把"部分可用"误读为"已配置"）
    assert list((target / CATALOG).glob("KM-*.json")) == []
    assert list((target / SCHEMA_DIR).glob("*.json")) == []
    assert not (target / CATALOG / "provision_manifest.json").exists()


def test_invalid_policy_writes_nothing(target, source_copy):
    """策略非法同样一份不写（地图全部合法时也不能先写地图）。"""
    p = source_copy / SCHEMA_DIR / "route_policy.json"
    doc = json.loads(p.read_text(encoding="utf-8"))
    del doc["policyId"]
    p.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(SchemaValidationError):
        provision_control_plane(target, source_copy)

    assert list((target / CATALOG).glob("KM-*.json")) == []
    assert list((target / SCHEMA_DIR).glob("*.json")) == []


def test_invalid_knowledge_sources_writes_nothing(target, source_copy):
    """第 4 类（知识源能力声明）非法同样**一份都不写**。

    M7.1-A 纪律 7 与 :func:`validate_source` 的第 5 步：声明**可选但必须校验** ——
    把该校验从 ``validate_source`` 去掉 ⇒ 本用例必红（"先全量校验后写入"被破坏）。
    """
    p = source_copy / SCHEMA_DIR / KNOWLEDGE_SOURCES_FILENAME
    doc = json.loads(p.read_text(encoding="utf-8"))
    doc["未声明字段"] = 1
    p.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(SchemaValidationError):
        provision_control_plane(target, source_copy)

    assert list((target / CATALOG).glob("KM-*.json")) == []
    assert list((target / SCHEMA_DIR).glob("*.json")) == []
    assert not (target / CATALOG / "provision_manifest.json").exists()


def test_broken_knowledge_sources_json_writes_nothing(target, source_copy):
    """声明的 JSON 层损坏（连解析都过不去）同样中止全量供给，不得只拷不管。"""
    p = source_copy / SCHEMA_DIR / KNOWLEDGE_SOURCES_FILENAME
    p.write_text("{ 不是合法 JSON", encoding="utf-8")

    with pytest.raises(SchemaValidationError):
        provision_control_plane(target, source_copy)

    assert list((target / CATALOG).glob("KM-*.json")) == []
    assert list((target / SCHEMA_DIR).glob("*.json")) == []


def test_source_without_knowledge_sources_is_tolerated(target, source_copy):
    """声明**缺失** ⇒ 不供给、不报错（与本体引用同口径，见 provision docstring 纪律 7）。

    这是**有意**的取舍：该声明当前无运行时消费方（M7.1-A 只读、未接线），
    缺它不应让整个部署起不来；"非法"才必须中止。
    """
    (source_copy / SCHEMA_DIR / KNOWLEDGE_SOURCES_FILENAME).unlink()

    r = provision_control_plane(target, source_copy)
    assert r.counts() == {ACTION_CREATED: PROVISION_ITEM_COUNT - 1, ACTION_UPDATED: 0,
                          ACTION_UNCHANGED: 0}
    assert not (target / SCHEMA_DIR / KNOWLEDGE_SOURCES_FILENAME).exists()
    assert resolve_declaration(target).code == CODE_DECLARATION_ABSENT


def test_source_without_policy_is_rejected(target, source_copy):
    (source_copy / SCHEMA_DIR / "route_policy.json").unlink()
    with pytest.raises(UsageError, match="缺少路由策略"):
        provision_control_plane(target, source_copy)
    assert list((target / CATALOG).glob("KM-*.json")) == []


def test_source_without_maps_is_rejected(target, source_copy):
    for f in (source_copy / CATALOG).glob("KM-*.json"):
        f.unlink()
    with pytest.raises(UsageError, match="未注册任何知识地图"):
        provision_control_plane(target, source_copy)


# --------------------------------------------------------------------------- #
# 用法错误
# --------------------------------------------------------------------------- #

def test_target_must_be_initialized_workspace(tmp_path):
    with pytest.raises(UsageError, match="目标工作区未初始化"):
        provision_control_plane(tmp_path / "not-initialized", SOURCE)


def test_source_must_be_workspace(target, source_copy):
    (source_copy / ".kert_workspace").unlink()
    with pytest.raises(UsageError, match="不是合法工作区"):
        provision_control_plane(target, source_copy)


def test_same_source_and_target_is_rejected(target):
    with pytest.raises(UsageError, match="相同"):
        provision_control_plane(target, target)


# --------------------------------------------------------------------------- #
# 不触碰清单外内容
# --------------------------------------------------------------------------- #

def test_does_not_delete_or_touch_other_files(target):
    provision_control_plane(target, SOURCE)

    keep_catalog = target / CATALOG / "operator_note.json"
    keep_catalog.write_text('{"note": "运维手工放置"}', encoding="utf-8")
    keep_core = target / "03_core" / "product" / "CURRENT.md"
    keep_core.parent.mkdir(parents=True, exist_ok=True)
    keep_core.write_text("权威资产\n", encoding="utf-8")

    provision_control_plane(target, SOURCE)

    assert keep_catalog.read_text(encoding="utf-8") == '{"note": "运维手工放置"}'
    assert keep_core.read_text(encoding="utf-8") == "权威资产\n"


# --------------------------------------------------------------------------- #
# 端到端：供给后运行时路由真的可用（这正是第五步的目的）
# --------------------------------------------------------------------------- #

def test_provisioned_workspace_serves_routing(target):
    from fastapi.testclient import TestClient

    from kert.api.server import create_app

    provision_control_plane(target, SOURCE)

    c = TestClient(create_app(target))
    listed = c.get("/v1/knowledge-maps").json()["data"]
    assert listed["count"] == 3
    assert listed["policy"]["policyId"] == "RP-KERT-BANKFRONT-001"

    plan = c.post("/v1/routing/plan",
                  json={"taskType": "PRE_VISIT_PREPARATION"}).json()["data"]
    assert plan["allowed"] is True

    # 与"直接消费受控 example"得到**同一**计划哈希：供给没有改变语义
    ref = TestClient(create_app(SOURCE)).post(
        "/v1/routing/plan", json={"taskType": "PRE_VISIT_PREPARATION"}).json()["data"]
    assert plan["plan"]["planHash"] == ref["plan"]["planHash"]
    assert plan["plan"]["versions"]["ontology"] == ref["plan"]["versions"]["ontology"]


def test_provisioned_workspace_can_load_knowledge_sources(target):
    """供给后工作区能加载知识源声明（第 4 类的端到端证明）。

    同时守住裁定 O-A：供给该声明**不改变** ``planHash`` 与其 ``versions``
    （绑定指纹只留痕，不进计划）。
    """
    provision_control_plane(target, SOURCE)

    load = resolve_declaration(target)
    assert load.allowed, load.reason
    assert load.declaration is not None
    bound = {b.asset_ref_id for b in load.declaration.bindings}
    assert bound >= {"KI-009", "KI-FRONT-001", "KI-FRONT-006"}

    from kert.domain.activation_plan import ActivationPlanBuilder
    from kert.domain.knowledge_map import KnowledgeMapRegistry

    ws_plan = ActivationPlanBuilder.load(target).build("PRE_VISIT_PREPARATION")
    src_plan = ActivationPlanBuilder.load(SOURCE).build("PRE_VISIT_PREPARATION")
    assert ws_plan.to_dict()["planHash"] == src_plan.to_dict()["planHash"]
    assert "knowledgeSources" not in ws_plan.to_dict()["versions"]
    # 反空转：工作区确实被供给过（否则上面的相等可能是"两边都拒绝"的假相等）
    assert len(KnowledgeMapRegistry.load(target).maps) == 3
