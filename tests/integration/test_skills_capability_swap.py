"""M7.1-B1 等价性证据：声明驱动读取 vs 接线前字面量读取（α / β / γ 三子命题）。

授权：``evidence/m7-3/TL_DECISION_M7-1-FIRST-SLICE.md``（条件性实施授权）
设计：``evidence/m7-3/CANDIDATE-M7-1-B1-EQUIVALENT-SWAP.md`` §1.2/§1.3/§2.2–§2.7

三条子命题（硬规则 E0：**声明缺失一律回落，绝不拒绝**）：

- **(α) 有声明 + 有投影**：新旧两条路径读出的知识条目**逐字节等价**，且剔除新增留痕后
  trace 与接线前**逐字全等**（含顺序）。
- **(β) 有声明 + 无投影**：技能 ``ok``、既有 ``kert``/逐条目轨迹原样、仅多一条具名留痕
  （``KNOWLEDGE_SOURCE_UNAVAILABLE``），**无任何拒绝**。
- **(γ) 声明缺失 + 任意投影**：**回落**字面量路径，技能照常完成，``KNOWLEDGE_SOURCE_DECLARATION_ABSENT``
  仅为**留痕**（不是拒绝码）。该组合在接线前**零覆盖**，属本片**补洞**。

本文件自带夹具（不依赖也不修改任何既有测试文件）：
``ws_provisioned`` 取自 ``tests/conftest.py``，种客户知识沿用
``scripts.seed_customer_knowledge.seed_customer_knowledge``（与 ``tests/integration/test_skills.py:41-49`` 同法）。

参照实现 = ``CustomerKnowledgeProvider.ki_map``（本片**不改**该模块）+ 临时把接线点别名
替换回 ``_load_ki`` 的运行 ⇒ "接线前行为"由**既有代码**给出，不需另写旧逻辑副本。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC = REPO_ROOT / "src"
for _p in (str(SRC), str(REPO_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from kert.application.customer_knowledge import (  # noqa: E402
    KI_ITEMS,
    KI_ORDER,
    CustomerKnowledgeProvider,
)
from kert.application.skills import SkillExecutionService  # noqa: E402
from kert.domain.activation_plan import ActivationPlanBuilder, PlanDenial  # noqa: E402
from kert.domain.knowledge_source import (  # noqa: E402
    CODE_DECLARATION_ABSENT,
    CODE_DECLARATION_INVALID,
    CODE_OK,
    CODE_UNAVAILABLE,
    FILENAME,
    KnowledgeSourceResolver,
    declaration_path,
)

CUSTOMER_ID = "CUST-CORP-0001"
KI_IDS = [k for k, _ in KI_ITEMS]
READER = "_load_ki_from_declaration"
WIRED_SKILLS = ("skill-customer-outreach-script", "skill-customer-meeting-script",
                "skill-customer-previsit-report")
#: 与既有集成测试同形（``test_skills.py:24-26``）；previsit 必须带时间戳，
#: 否则会被 R1 无新证据策略在**取数之前**拦截（走不到读取层）。
REQS: dict[str, dict] = {
    "skill-customer-outreach-script": {"customerId": CUSTOMER_ID},
    "skill-customer-meeting-script": {"customerId": CUSTOMER_ID},
    "skill-customer-previsit-report": {"customerId": CUSTOMER_ID,
                                       "evidenceTimestamp": "2026-08-22T10:00:00Z"},
}


# --------------------------------------------------------------------------- #
# 夹具与机械判据
# --------------------------------------------------------------------------- #

@pytest.fixture
def ws_ki_seeded(ws_provisioned):
    """已供给控制面 + 已种 ``CUST-CORP-0001`` 客户知识的工作区（(α) 形态）。"""
    from scripts.seed_customer_knowledge import seed_customer_knowledge

    seed_customer_knowledge(ws_provisioned, quiet=True)
    return ws_provisioned


def _is_source_entry(entry: dict) -> bool:
    """知识源留痕条目的机械判据（同 unit 守卫；不靠字段自述之外的猜测）。"""
    if not isinstance(entry, dict):
        return False
    return (entry.get("capabilityId") is not None
            or str(entry.get("sourceCode", "")).startswith("KNOWLEDGE_SOURCE_"))


def _strip_source(trace: list[dict]) -> list[dict]:
    """剔除留痕条目后的 trace ⇒ 必须与接线前**逐字全等（顺序含）**。"""
    return [e for e in trace if not _is_source_entry(e)]


def _codes(trace: list[dict]) -> list[str]:
    return [e.get("sourceCode") for e in trace if _is_source_entry(e)]


def _source_entry(trace: list[dict]) -> dict:
    entries = [e for e in trace if _is_source_entry(e)]
    assert len(entries) == 1, f"每次取数必须恰好一条留痕：{entries}"
    return entries[0]


def _hit_ids(trace: list[dict]) -> set[str]:
    return {t["kiId"] for t in trace if t.get("kiId") and t.get("status") == "ok"}


def _run(ws, skill_id: str, request_id: str, req: dict):
    """被测运行：**声明驱动**读取（生产路径）。"""
    return SkillExecutionService(ws).execute(skill_id, request_id, req)


def _reference_run(ws, skill_id: str, request_id: str, req: dict):
    """参照运行：临时把接线点别名替换回 ``_load_ki`` = 接线前行为。

    同 requestId（trace 首条含 requestId）+ **新实例**（幂等缓存是实例级）⇒ 两次可比。
    """
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(SkillExecutionService, READER, SkillExecutionService._load_ki)
        return SkillExecutionService(ws).execute(skill_id, request_id, req)


def _decl_doc() -> dict:
    """受控工作区声明的原样副本（负例一律从它派生，避免凭空造声明）。"""
    p = REPO_ROOT / "examples" / "bank-front-knowledge-maps" / "90_control" / "schema" / FILENAME
    return json.loads(p.read_text(encoding="utf-8"))


def _write_decl(ws, doc: dict) -> None:
    p = declaration_path(ws)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _no_refusal(result) -> None:
    """硬规则 E0 的机械断言：**不得出现任何拒绝**（技能层与 trace 层都查）。"""
    assert result.status == "ok", (result.status, result.errors)
    assert result.errors == []
    assert not [e for e in result.assembly_trace
                if _is_source_entry(e) and e.get("status") in {"failed", "blocked"}], (
        "知识源留痕不得是失败/阻塞态：B-1 一律回落，不是拒绝")


# --------------------------------------------------------------------------- #
# (α) 有声明 + 有投影：逐字节等价
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("skill_id", WIRED_SKILLS)
def test_alpha_data_and_trace_are_byte_equivalent(ws_ki_seeded, skill_id):
    """(α)：``data``/``status`` 与接线前**逐字相等**，剔除留痕后 trace 亦逐字相等。"""
    req = REQS[skill_id]
    rid = f"alpha-{skill_id}"
    r = _run(ws_ki_seeded, skill_id, rid, req)
    ref = _reference_run(ws_ki_seeded, skill_id, rid, req)

    assert r.status == ref.status == "ok"
    assert r.data == ref.data, "读取结果与接线前不等价（内容被裁改/改写）"
    assert _strip_source(r.assembly_trace) == ref.assembly_trace, (
        "剔除留痕后 trace 与接线前不等价（顺序或内容被改动）")
    entry = _source_entry(r.assembly_trace)
    assert entry["sourceCode"] == CODE_OK, entry
    assert entry["capabilityId"] == "KS-CUSTOMER-KI-PARQUET"
    assert entry["status"] == "ok"


def test_alpha_ki_text_equals_reference_provider(ws_ki_seeded):
    """(α)：每个命中的知识条目必须与``CustomerKnowledgeProvider.ki_map``**逐字节相等**。

    参照实现未改动（本片不改 ``customer_knowledge.py``）⇒ 可直接调用做对照。
    """
    ref_ki = CustomerKnowledgeProvider(ws_ki_seeded).ki_map(CUSTOMER_ID)
    assert set(ref_ki) == set(KI_IDS), f"夹具失真：库中命中集不是 7 条 {sorted(ref_ki)}"

    r = _run(ws_ki_seeded, "skill-customer-previsit-report", "alpha-bytes",
             REQS["skill-customer-previsit-report"])
    expected = [{"heading": f"{kid} {ref_ki[kid]['title']}", "content": ref_ki[kid]["content"]}
                for kid in KI_ORDER if kid in ref_ki]
    assert r.data["sections"] == expected, "章节文本与参照实现不等价"
    assert _hit_ids(r.assembly_trace) == set(KI_IDS)
    # 证据引用里必须含 KI-009（既有断言 test_skills.py:250 的口径；前置项由模型输出贡献）
    assert any(e.get("id") == "KI-009" for e in r.data["evidenceRefs"]), r.data["evidenceRefs"]


# --------------------------------------------------------------------------- #
# (β) 有声明 + 无投影：具名留痕 + 零拒绝
# --------------------------------------------------------------------------- #

def test_beta_unavailable_falls_back_with_named_trace(ws_provisioned):
    """(β)：无投影 ⇒ 与接线前逐项相同，仅多一条 ``UNAVAILABLE`` 留痕，零拒绝。"""
    r = _run(ws_provisioned, "skill-customer-outreach-script", "beta-1",
             REQS["skill-customer-outreach-script"])
    _no_refusal(r)
    assert _codes(r.assembly_trace) == [CODE_UNAVAILABLE]
    # 既有行为原样保留：kert skipped；逐条目全 skipped；无 ok 命中
    assert any(t.get("phase") == "kert" and t.get("status") == "skipped"
               for t in r.assembly_trace)
    assert not _hit_ids(r.assembly_trace)
    msgs = [t.get("message", "") for t in r.assembly_trace]
    assert all("skipped" in m for m in msgs if "KI-" in m), msgs
    assert r.data.get("sections") or r.data.get("agenda"), "技能仍须产出正常结构"


# --------------------------------------------------------------------------- #
# (γ→②) 声明缺失 + 任意投影：**B-2② 起 ⇒ 拒绝**（B-1 时为"回落"，已按裁定翻转）
# --------------------------------------------------------------------------- #

def test_gamma_declaration_absent_is_refused(ws_ki_seeded):
    """**② B-2**：删声明后**计划仍放行**，但读取层**拒绝**（不再回落字面量路径）。

    B-1 时本用例断言"回落、仍读到 7 条、与参照逐字等价"；② 生效后按裁定翻转为拒绝。
    **同时**保留"计划仍放行"这一前提断言：证明拒绝**来自读取层**，而非计划门禁漂移。
    """
    decl = declaration_path(ws_ki_seeded)
    original = decl.read_text(encoding="utf-8")
    decl.unlink()
    try:
        # 前提断言：声明不是计划门禁的输入（否则本夹具没进到读取层）
        plan = ActivationPlanBuilder.load(ws_ki_seeded).build("PRE_VISIT_PREPARATION")
        assert not isinstance(plan, PlanDenial), getattr(plan, "reason", plan)

        r = _run(ws_ki_seeded, "skill-customer-previsit-report", "gamma-absent",
                 REQS["skill-customer-previsit-report"])
        # ② 拒绝（fail-closed）
        assert r.status == "skill_error", (r.status, r.errors)
        assert r.data == {}, "fail-closed：不得返回残缺数据"
        assert r.errors and r.errors[0]["code"] == "KERT_PERMISSION_DENIED", r.errors
        assert _codes(r.assembly_trace) == [CODE_DECLARATION_ABSENT], r.assembly_trace
        assert _source_entry(r.assembly_trace)["status"] == "blocked"
        # **回落已不再发生**：库可用（本夹具已种 7 条），若仍回落则必然读满 7 条并留 `kert` 条目
        assert _hit_ids(r.assembly_trace) == set(), "② 生效后不得再读到任何条目"
        assert not any(t.get("phase") == "kert" for t in r.assembly_trace), (
            "`kert` 条目 = 回落发生的标志 ⇒ 声明缺失时不应出现")
    finally:
        decl.write_text(original, encoding="utf-8")


def test_gamma_prime_absent_is_refused_regardless_of_projection(ws_provisioned):
    """**② B-2**：声明缺失 **且** 源不可用 ⇒ 仍按 **②** 拒绝（声明缺失优先，不被 ① 覆盖）。"""
    from kert.application.provision import provision_control_plane

    ws = ws_provisioned
    provision_control_plane(ws, REPO_ROOT / "examples" / "bank-front-knowledge-maps")
    decl = declaration_path(ws)
    original = decl.read_text(encoding="utf-8")
    decl.unlink()
    try:
        r = _run(ws, "skill-customer-meeting-script", "gamma-prime-1",
                 REQS["skill-customer-meeting-script"])
        assert r.status == "skill_error" and r.data == {}, (r.status, r.errors)
        assert _codes(r.assembly_trace) == [CODE_DECLARATION_ABSENT], r.assembly_trace
        assert _source_entry(r.assembly_trace)["status"] == "blocked"
        assert not any(t.get("phase") == "kert" for t in r.assembly_trace)
        assert not any(t.get("kiId") for t in r.assembly_trace)
    finally:
        decl.write_text(original, encoding="utf-8")


# --------------------------------------------------------------------------- #
# 反"接线后仍读字面量"：声明必须**真的**是取数驱动（变异 V1）
# --------------------------------------------------------------------------- #

def test_declaration_pattern_is_the_read_driver(ws_ki_seeded):
    """双向证据：改声明的匹配规则 ⇒ 命中集随之改变；恢复 ⇒ 恢复。

    若实现仍走源码字面量正则（变异 V1），方向 A 的断言**必然 FAIL**（仍命中 7 条）。

    刻意用 **previsit**：其计划资产 = 全部 7 条 ⇒ "命中集"与"库内容"同口径，
    任何"仍读字面量"的实现在方向 A 下都会留下 7 条命中，无法蒙混。
    """
    ws = ws_ki_seeded
    decl = declaration_path(ws)
    original = decl.read_text(encoding="utf-8")
    rid = "driver"
    req = REQS["skill-customer-previsit-report"]
    try:
        baseline = _run(ws, "skill-customer-previsit-report", rid, req)
        assert _hit_ids(baseline.assembly_trace) == set(KI_IDS)

        doc = json.loads(original)
        doc["capabilities"][0]["readContract"]["assetMatch"]["pattern"] = \
            r"^(?P<assetRefId>KI-XXX)\s+(?P<title>.+)$"
        _write_decl(ws, doc)

        broken = _run(ws, "skill-customer-previsit-report", rid, req)
        _no_refusal(broken)
        assert _hit_ids(broken.assembly_trace) == set(), (
            "改声明后仍命中 ⇒ 读取未由声明驱动（变异 V1）")
        assert _source_entry(broken.assembly_trace)["sourceCode"] == CODE_OK
    finally:
        decl.write_text(original, encoding="utf-8")

    restored = _run(ws, "skill-customer-previsit-report", rid, req)
    assert _hit_ids(restored.assembly_trace) == set(KI_IDS), "恢复声明后必须恢复命中"


def test_binding_fingerprint_is_not_hardcoded(ws_provisioned):
    """留痕里的绑定指纹必须等于解析器现算值，且**改声明后必变**（变异 V10）。"""
    ws = ws_provisioned
    decl = declaration_path(ws)
    original = decl.read_text(encoding="utf-8")
    try:
        r = _run(ws, "skill-customer-meeting-script", "fp-1",
                 REQS["skill-customer-meeting-script"])
        first = _source_entry(r.assembly_trace)
        expected = KnowledgeSourceResolver.load(ws).binding_sha256
        assert expected, "声明应可加载"
        assert first.get("assetVersion") == expected, (
            f"留痕指纹与解析器现算值不符：{first.get('assetVersion')} vs {expected}")

        doc = json.loads(original)
        for b in doc["bindings"]:
            b["priority"] = int(b["priority"]) + 1      # 只改绑定 ⇒ 指纹必变
        _write_decl(ws, doc)

        r2 = _run(ws, "skill-customer-meeting-script", "fp-2",
                  REQS["skill-customer-meeting-script"])
        second = _source_entry(r2.assembly_trace)
        assert second.get("assetVersion") != first.get("assetVersion"), (
            "改声明后指纹未变 ⇒ 指纹被写死（变异 V10）")
        assert second.get("assetVersion") == KnowledgeSourceResolver.load(ws).binding_sha256
    finally:
        decl.write_text(original, encoding="utf-8")


# --------------------------------------------------------------------------- #
# 三态可区分 + required **不**升格（变异 V4 / V7）
# --------------------------------------------------------------------------- #

def test_three_declaration_forms_have_distinct_codes_with_2_refusing(tmp_path, ws_provisioned):
    """三态**可区分** + **①/② 分野**：``UNAVAILABLE`` 仍回落（①），``INVALID``/``ABSENT`` 拒绝（②）。

    B-1 时三者"都不拒绝"；② 生效后**只有声明缺失/非法**拒绝 —— 本用例同时钉住
    "② 不得顺手改掉 ①"（TL 边界 2）与"三码互不相同"（V7）。
    """
    from kert.domain import workspace as ws_mod
    from kert.application.provision import provision_control_plane

    # ① 不可用：声明合法、但无投影 ⇒ 回落（与 B-1 相同）
    r_unavail = _run(ws_provisioned, "skill-customer-outreach-script", "tri-u",
                     REQS["skill-customer-outreach-script"])

    # ② 非法：多写一个未声明字段 ⇒ 拒绝
    ws_invalid = tmp_path / "invalid_ws"
    ws_mod.init_workspace(ws_invalid)
    provision_control_plane(ws_invalid, REPO_ROOT / "examples" / "bank-front-knowledge-maps")
    doc = _decl_doc()
    doc["capabilities"][0]["未声明字段"] = 1
    _write_decl(ws_invalid, doc)
    r_invalid = _run(ws_invalid, "skill-customer-outreach-script", "tri-i",
                     REQS["skill-customer-outreach-script"])

    # ② 缺失：删声明 ⇒ 拒绝
    ws_absent = tmp_path / "absent_ws"
    ws_mod.init_workspace(ws_absent)
    provision_control_plane(ws_absent, REPO_ROOT / "examples" / "bank-front-knowledge-maps")
    declaration_path(ws_absent).unlink()
    r_absent = _run(ws_absent, "skill-customer-outreach-script", "tri-a",
                    REQS["skill-customer-outreach-script"])

    # 三码互不相同（V7）
    assert _codes(r_unavail.assembly_trace) == [CODE_UNAVAILABLE]
    assert _codes(r_invalid.assembly_trace) == [CODE_DECLARATION_INVALID]
    assert _codes(r_absent.assembly_trace) == [CODE_DECLARATION_ABSENT]
    assert len({CODE_UNAVAILABLE, CODE_DECLARATION_INVALID, CODE_DECLARATION_ABSENT}) == 3, (
        "三个码必须互不相同（混码会让归因错位）")

    # ①：回落（ok + degraded + 仍走 `kert` 路径）
    _no_refusal(r_unavail)
    assert _source_entry(r_unavail.assembly_trace)["status"] == "degraded"
    assert any(t.get("phase") == "kert" for t in r_unavail.assembly_trace)

    # ②：拒绝（skill_error + blocked + 未走回落）
    for r in (r_invalid, r_absent):
        assert r.status == "skill_error" and r.data == {}, (r.status, r.errors)
        assert r.errors and r.errors[0]["code"] == "KERT_PERMISSION_DENIED", r.errors
        assert _source_entry(r.assembly_trace)["status"] == "blocked"
        assert not any(t.get("phase") == "kert" for t in r.assembly_trace)


def test_required_flag_does_not_escalate(ws_provisioned):
    """``required`` 不得升格：只留 ``required: false`` 的绑定、或只留 ``true`` 的绑定，
    两侧结果**必须相同**（``ok`` + ``skipped``，零拒绝）—— 变异 V4。

    夹具锚定受控地图真实取值（``KM-CORP-RM-OUTREACH``：``KI-009``/``KI-FRONT-004`` 为
    ``required: true``，``KI-FRONT-006`` 为 ``false``）；取值变了即前置断言失败。
    """
    ws = ws_provisioned
    rid = "required-flag"
    req = REQS["skill-customer-outreach-script"]
    plan = ActivationPlanBuilder.load(ws).build("OUTREACH_PREPARATION")
    reqs = {a.asset_id: getattr(a, "required", None) for a in plan.assets}
    assert reqs == {"KI-009": True, "KI-FRONT-004": True, "KI-FRONT-006": False}, (
        f"前置夹具失真：受控地图 required 取值已变 {reqs}")

    decl = declaration_path(ws)
    original = decl.read_text(encoding="utf-8")
    try:
        base = _run(ws, "skill-customer-outreach-script", rid, req)
        _no_refusal(base)
        base_states = {t["kiId"]: t["status"] for t in base.assembly_trace if t.get("kiId")}
        assert base_states == {"KI-009": "skipped", "KI-FRONT-004": "skipped",
                               "KI-FRONT-006": "skipped"}, base_states

        # 只留 required: false 的绑定 ⇒ 仍须 ok、仍须 skipped、零拒绝
        doc = json.loads(original)
        doc["bindings"] = [b for b in doc["bindings"] if b["assetRefId"] == "KI-FRONT-006"]
        _write_decl(ws, doc)
        only_false = _run(ws, "skill-customer-outreach-script", rid, req)

        # 只留 required: true 的绑定 ⇒ 结果必须与上一步**相同**
        doc = json.loads(original)
        doc["bindings"] = [b for b in doc["bindings"] if b["assetRefId"] in ("KI-009", "KI-FRONT-004")]
        _write_decl(ws, doc)
        only_true = _run(ws, "skill-customer-outreach-script", rid, req)

        for r in (only_false, only_true):
            _no_refusal(r)
        assert only_false.data == only_true.data == base.data
        assert _strip_source(only_false.assembly_trace) == _strip_source(only_true.assembly_trace)
    finally:
        decl.write_text(original, encoding="utf-8")
