"""M7.1-B1 守卫：声明驱动读取的**机械边界**（白名单精确 + fail-closed）。

授权：``evidence/m7-3/TL_DECISION_M7-1-FIRST-SLICE.md``（条件性实施授权）
设计：``evidence/m7-3/CANDIDATE-M7-1-B1-EQUIVALENT-SWAP.md`` §4.1（Q4 守卫）/ §1.1.3 / §1.5

本文件只做四件事，全部是**机械可判**的（不靠"看起来对"）：

1. **Q4 调用点守卫（fail-closed）**：``_load_ki`` 前缀枚举集合必须恰为
   ``{_load_ki, _load_ki_from_declaration}``；新方法的调用点必须恰为
   ``{_run_outreach, _run_meeting, _run_previsit}``；``_run_supply_chain`` **不得**被接线
   —— 源码不可读 / 解析不到 / 夹具缺失一律 **FAIL**（不是 skip）。
   打击点：变异 **V8**（改 ``_load_ki`` 本体）、**V12**（出现第 4 个调用点）。
2. **签名等式守卫**：``inspect.signature`` 逐字相等 ⇒ 日后为传计划参数而改签名立即 FAIL。
   打击点：变异 **V14**（签名漂移）。
3. **trace 字段纪律 T1–T6**：新增条目不得带 ``kiId``/``mapId``/``errorCode``、
   ``message`` 不得含 ``KI-``、``phase``/``status`` 必须在 canonical 枚举内、
   且**只追加**（剔除后与接线前逐字全等，顺序含）。
   打击点：变异 **V6**（字段污染）、**V13**（插在既有序列中间）。
4. **canonical schema 必须**真的声明这两个新字段（不得只靠 ``additionalProperties``）。
"""

from __future__ import annotations

import ast
import inspect
import json
import sys
from pathlib import Path

import jsonschema
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC = REPO_ROOT / "src"
for _p in (str(SRC), str(REPO_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from kert.application.customer_knowledge import KI_ITEMS  # noqa: E402
from kert.application.skills import SkillExecutionService  # noqa: E402
from kert.domain.knowledge_source import (  # noqa: E402
    CODE_DECLARATION_ABSENT,
    CODE_DECLARATION_INVALID,
    CODE_UNAVAILABLE,
    FILENAME,
    declaration_path,
)

#: 客户知识库的 7 条知识条目（顺序即契约顺序）
KI_IDS = [k for k, _ in KI_ITEMS]

SKILLS_PY = REPO_ROOT / "src" / "kert" / "application" / "skills.py"
TRACE_SCHEMA = REPO_ROOT / "docs" / "contracts" / "schemas" / "assembly-trace.schema.json"
REAL_DECL = (REPO_ROOT / "examples" / "bank-front-knowledge-maps"
             / "90_control" / "schema" / FILENAME)

CUSTOMER_ID = "CUST-CORP-0001"
WIRED_SKILLS = ("skill-customer-outreach-script", "skill-customer-meeting-script",
                "skill-customer-previsit-report")

#: 与既有集成测试同形（``tests/integration/test_skills.py:24-26``）：
#: previsit 必须带 ``evidenceTimestamp``，否则会被 **R1 无新证据策略**在取数**之前**
#: 拦截（``exit_policy_no_new_evidence``）⇒ 根本走不到读取层（首版实测踩到）。
REQS: dict[str, dict] = {
    "skill-customer-outreach-script": {"customerId": CUSTOMER_ID},
    "skill-customer-meeting-script": {"customerId": CUSTOMER_ID},
    "skill-customer-previsit-report": {"customerId": CUSTOMER_ID,
                                       "evidenceTimestamp": "2026-08-22T10:00:00Z"},
}
READER = "_load_ki_from_declaration"
LEGACY_READER = "_load_ki"

#: 被技能执行器**接线**的三个方法（新方法的调用点必须恰为这三个）
WIRED_CALLERS = {"_run_outreach", "_run_meeting", "_run_previsit"}
#: **明确不接线**的（D 组：bank-front-supply-chain-graph 仍走字面量）
UNWIRED_CALLER = "_run_supply_chain"


# --------------------------------------------------------------------------- #
# 新条目的机械判据（**不**依赖字段自述之外的任何猜测）
# --------------------------------------------------------------------------- #

def _is_source_entry(entry: dict) -> bool:
    """是否为"知识源能力留痕条目"。

    判据刻意用**两个**独立的机械特征：``capabilityId`` 存在（解析出能力时）
    或 ``sourceCode`` 是 ``KNOWLEDGE_SOURCE_*`` 码（声明缺失/非法时没有能力可指，
    实现**不**伪造占位能力 ID）。其它任何既有条目（路由条目带 ``mapId``、
    逐知识条目条目带 ``kiId``）都不满足该判据。
    """
    if not isinstance(entry, dict):
        return False
    if entry.get("capabilityId") is not None:
        return True
    return str(entry.get("sourceCode", "")).startswith("KNOWLEDGE_SOURCE_")


def _strip_source(trace: list[dict]) -> list[dict]:
    """剔除知识源留痕条目后的 trace（顺序含）⇒ 必须与接线前**逐字全等**。"""
    return [e for e in trace if not _is_source_entry(e)]


def _source_entries(trace: list[dict]) -> list[dict]:
    return [e for e in trace if _is_source_entry(e)]


def _codes(trace: list[dict]) -> list[str]:
    return [e.get("sourceCode") for e in _source_entries(trace)]


def _route_entry(trace: list[dict]) -> dict:
    """trace 中的路由步骤（**忠实复刻** ``tests/integration/test_skill_routing_trace.py:33-39``）。

    刻意复制而非 import：既有测试文件一字不改，且守卫须能在"路由条目被新条目挤掉"
    时独立 FAIL —— 若新条目误带 ``mapId``/``ROUTE_*`` 码，这里会选到错的条目。
    """
    for t in trace:
        if "mapId" in t or str(t.get("errorCode", "")).startswith(
                ("ROUTE_", "KNOWLEDGE_MAP_", "ONTOLOGY_REFERENCE_")):
            return t
    raise AssertionError(f"trace 中未找到路由步骤：{trace}")


# --------------------------------------------------------------------------- #
# 1. Q4 调用点守卫（AST；fail-closed）
# --------------------------------------------------------------------------- #

def _class_methods() -> dict[str, ast.AST]:
    """解析 ``SkillExecutionService`` 的方法表；**解析不到即 FAIL**（不 skip）。"""
    assert SKILLS_PY.is_file(), f"守卫自身失效：源码不可读 {SKILLS_PY}（fail-closed）"
    tree = ast.parse(SKILLS_PY.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "SkillExecutionService":
            methods = {n.name: n for n in node.body
                       if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
            assert methods, f"守卫自身失效：{SKILLS_PY} 未解析到任何方法（fail-closed）"
            return methods
    raise AssertionError(f"守卫自身失效：未找到 SkillExecutionService（{SKILLS_PY}）")


def _callers_of(method_name: str) -> set[str]:
    """返回调用 ``self.<method_name>(...)`` 的**方法名**集合（AST，非文本匹配）。"""
    out: set[str] = set()
    for name, fn in _class_methods().items():
        for node in ast.walk(fn):
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == method_name
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "self"):
                out.add(name)
    return out


def test_prefix_scan_finds_exactly_two_load_ki_methods():
    """``_load_ki`` 前缀枚举集合必须恰为 ``{_load_ki, _load_ki_from_declaration}``。

    命名前缀是刻意的：使"所有 KI 读取点"可由**一个前缀**枚举。多出任何
    ``_load_ki*`` 方法 ⇒ FAIL（否则可新增读取点绕过本守卫）—— 变异 **V12**。
    """
    found = {n for n in _class_methods() if n.startswith(LEGACY_READER)}
    assert found == {LEGACY_READER, READER}, (
        f"KI 读取点集合被改动（多出/缺少读取点即视为绕过守卫）：{sorted(found)}")


def test_new_reader_call_sites_are_exactly_the_three_wired_skills():
    """新方法的调用点必须恰为三个已接线技能；出现第 4 个调用点 ⇒ FAIL（V12）。"""
    callers = _callers_of(READER)
    assert callers == WIRED_CALLERS, (
        f"新读取方法的调用点集合不符：实际 {sorted(callers)}，期望 {sorted(WIRED_CALLERS)}")


def _provisioned(ws: Path) -> Path:
    """已供给控制面的新工作区（**独立目录**，避免夹具互相污染）——夹具缺失即 FAIL。"""
    from kert.application.provision import provision_control_plane
    from kert.domain import workspace as ws_mod

    ws_mod.init_workspace(ws)
    provision_control_plane(ws, REPO_ROOT / "examples" / "bank-front-knowledge-maps")
    return ws


@pytest.fixture
def ws_ki_seeded(tmp_path):
    """已供给 + 已种客户知识的工作区（**独立目录**；自带夹具，不改既有测试文件）。"""
    from scripts.seed_customer_knowledge import seed_customer_knowledge

    ws = _provisioned(tmp_path / "seeded_ws")
    seed_customer_knowledge(ws, quiet=True)
    return ws


def test_legacy_reader_contract_is_unchanged(tmp_path, ws_ki_seeded):
    """**既有**读取路径 ``_load_ki`` 的对外契约（返回 + 文案 + 条目数）必须一字不改 —— V8。

    为什么必须**直调本体**：实测（2026-09-16）D 组 3 条既有断言只依赖
    ``CustomerKnowledgeProvider`` 的 ``supply_chain``/``interpretation``，
    **不依赖** ``_load_ki`` 的返回值 ⇒ 仅靠 D 组**抓不到**"改本体"（先按设计写的
    "改 ``_load_ki`` 本体"变异体在 D 组下**未 FAIL**，证据在交付报告）。
    故此处直接钉住三条分支的**逐字输出**：无投影 / 有投影 / 取数抛异常（fail-open）。
    """
    # 分支 1：无投影（未接入）⇒ {} + 恰一条 kert/skipped（文案逐字）
    # 注意：必须用**独立目录**（`ws_ki_seeded` 会往同一 tmp_path 里种库，
    # 若共用目录，分支 1 会看到"有投影"⇒ 本用例自相矛盾）。
    svc = SkillExecutionService(_provisioned(tmp_path / "plain_ws"))
    trace: list[dict] = []
    assert svc._load_ki(CUSTOMER_ID, trace) == {}
    assert trace == [{"phase": "kert", "status": "skipped",
                      "message": "KERT 客户知识库未接入（skipped）"}], trace

    # 分支 2：有投影 ⇒ 7 条 + 恰一条 kert/ok（文案逐字，条目不多不少）
    svc_seeded = SkillExecutionService(ws_ki_seeded)
    trace2: list[dict] = []
    ki = svc_seeded._load_ki(CUSTOMER_ID, trace2)
    assert set(ki) == set(KI_IDS), sorted(ki)
    assert all(set(v) == {"title", "content"} for v in ki.values()), ki
    assert trace2 == [{"phase": "kert", "status": "ok",
                       "message": f"KERT 客户知识库检索完成（{CUSTOMER_ID} 命中 {len(ki)} 条 KI）"}], trace2

    # 分支 3：取数抛异常 ⇒ fail-open（空结果 + 具名文案），不得变成拒绝
    boom = SkillExecutionService(ws_ki_seeded)

    def _raise(customer_id):  # noqa: ANN001
        raise RuntimeError("库不可用（测试桩）")

    boom._ckp.ki_map = _raise
    trace3: list[dict] = []
    assert boom._load_ki(CUSTOMER_ID, trace3) == {}
    assert trace3 == [{"phase": "kert", "status": "skipped",
                       "message": "KERT 客户知识库不可用（fail-open）：库不可用（测试桩）"}], trace3


def test_supply_chain_stays_on_literal_reader():
    """``_run_supply_chain`` 必须**仍**走字面量读取（D 组：不接线）—— 变异 **V8**。

    同时证明"改 ``_load_ki`` 本体"这条路仍然会波及未接线技能 ⇒ 本片不敢改它。
    """
    assert UNWIRED_CALLER not in _callers_of(READER), (
        f"{UNWIRED_CALLER} 被接线到声明驱动读取 —— 违反 O-6 范围（D 组不接线）")
    assert UNWIRED_CALLER in _callers_of(LEGACY_READER), (
        f"{UNWIRED_CALLER} 不再调用 {LEGACY_READER}（字面量读取路径被改动？）")


# --------------------------------------------------------------------------- #
# 2. 签名等式守卫（直接保护"不接计划参数"的决策）
# --------------------------------------------------------------------------- #

def _ast_signature_text(method_name: str) -> str:
    """方法的**源码级**签名文本（形参 + 返回注解）—— AST 口径。"""
    fn = _class_methods()[method_name]
    ret = f" -> {ast.unparse(fn.returns)}" if fn.returns is not None else ""
    return f"({ast.unparse(fn.args)}){ret}"


def _ast_param_names(method_name: str) -> list[str]:
    """方法的源码级形参名序列（AST 口径）。"""
    fn = _class_methods()[method_name]
    args = fn.args
    return ([a.arg for a in args.posonlyargs + args.args]
            + [a.arg for a in args.kwonlyargs])


def test_signature_equality_guard():
    """两个读取点的签名必须**逐字相同**，且新方法**不得被包装** —— 变异 **V14**。

    ⚠ 实证（2026-09-16，两次复现）：本用例**不能**只用 ``inspect.signature`` 互比 ——
    ``/tmp/m71b_impact_probe.py``（影响面探针，TL 认可的量具）在**同一进程内**把
    ``SkillExecutionService._load_ki`` **永久替换**为计数包装器（探针源码
    ``_install_instrumentation`` 的 ``skills_mod.SkillExecutionService._load_ki = load_ki_wrapper``），
    于是纯 introspect 互比会把**量具**误判成"签名漂移"⇒ **假红**。
    故拆成两条同样机械的断言：

    1. **源码级（AST）**：两个方法的形参+返回注解文本逐字相等 —— 不受任何运行期包装影响，
       V14（给新方法加 ``plan`` 参数）**仍然必 FAIL**；
    2. **运行期**：新方法必须是**未包装的裸函数**，且其实参名与源码一致 —— 防有人用
       decorator/wrapper 在运行期改签名（这类改动源码扫描抓不到，本条能抓）。
    """
    src_new = _ast_signature_text(READER)
    src_old = _ast_signature_text(LEGACY_READER)
    assert src_new == src_old, (
        f"源码级签名漂移：{READER}{src_new} vs {LEGACY_READER}{src_old}"
        "（传计划参数会破坏『本方法不读计划』的等价性论证，须整体退回评审）")

    fn = SkillExecutionService._load_ki_from_declaration
    assert inspect.isfunction(fn), f"{READER} 必须是裸函数，实际 {fn!r}"
    assert not hasattr(fn, "__wrapped__"), f"{READER} 被包装（签名可能已变）：{fn!r}"
    assert list(inspect.signature(fn).parameters) == _ast_param_names(READER), (
        f"运行期形参名与源码不一致：{list(inspect.signature(fn).parameters)}"
        f" vs {_ast_param_names(READER)}")


# --------------------------------------------------------------------------- #
# 3. trace 字段纪律（T1–T6）+ 剔除还原（"0 变化"的可判形式）
# --------------------------------------------------------------------------- #

def _reference_run(ws, skill_id: str, request_id: str, req: dict):
    """参照实现：**临时**把接线点别名替换回 ``_load_ki``（= 接线前行为）。

    刻意用局部 ``MonkeyPatch.context()`` 而不是 fixture：若整条用例都处于替换状态，
    "被测运行"本身也就走了旧路径 ⇒ 新条目恒为 0，用例会**假绿**或假红（首版实测踩到）。
    """
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(SkillExecutionService, READER, SkillExecutionService._load_ki)
        return SkillExecutionService(ws).execute(skill_id, request_id, req)


@pytest.mark.parametrize("skill_id", WIRED_SKILLS)
def test_trace_field_discipline_and_append_only(ws_provisioned, skill_id):
    """三个已接线技能：新条目字段纪律 T1–T6 + 剔除后与接线前**逐字全等**。

    夹具 ``ws_provisioned``：声明存在、**无**客户知识投影 ⇒ 走回落分支
    （``KNOWLEDGE_SOURCE_UNAVAILABLE``），正是 (β) 子命题的形态。
    """
    req = REQS[skill_id]
    # 两次运行**必须同 requestId**（trace 首条含 requestId），但**必须不同服务实例**
    # （幂等缓存是实例级）—— 否则比较的是两个不同的请求标识。
    rid = f"guard-trace-{skill_id}"
    svc = SkillExecutionService(ws_provisioned)
    r = svc.execute(skill_id, rid, req)
    r_ref = _reference_run(ws_provisioned, skill_id, rid, req)

    assert r.status == r_ref.status == "ok"
    assert r.errors == r_ref.errors == []

    news = _source_entries(r.assembly_trace)
    assert len(news) == 1, f"回落必须留**恰好一条**具名留痕；完整 trace：{r.assembly_trace}"
    entry = news[0]

    # T1 / T2：不得带 kiId、mapId、errorCode（否则既有断言/路由条目选择会走偏）
    assert "kiId" not in entry, f"T1 违反：新条目带 kiId {entry}"
    assert "mapId" not in entry, f"T2 违反：新条目带 mapId {entry}"
    assert "errorCode" not in entry, f"T2 违反：新条目带 errorCode {entry}"
    # T3：message 不得含 KI-（能力 ID 与资产引用 id 一律放独立字段）
    assert "KI-" not in entry["message"], f"T3 违反：message 含 KI- {entry['message']!r}"
    # 能力 ID 本身含 ``KI-``（``KS-CUSTOMER-KI-PARQUET``）—— 这不是问题，
    # 问题是它**出现在了 message 里**；因此这里断言的是"字段值存在且未被转写进 message"。
    assert entry.get("capabilityId"), "解析出能力时必须给出 capabilityId（不得省略）"
    assert entry["capabilityId"].startswith("KS-"), entry["capabilityId"]
    assert entry["capabilityId"] not in entry["message"]

    # 路由条目仍须是路由条目（新条目不得把它挤掉）
    route = _route_entry(r.assembly_trace)
    assert route.get("mapId") == "KM-CORP-RM-OUTREACH" or route.get("mapId", "").startswith("KM-")
    assert "capabilityId" not in route

    # T6 / 剔除还原：新条目是**纯追加**，剔除后与参照**逐字全等（顺序含）**
    assert _strip_source(r.assembly_trace) == r_ref.assembly_trace, (
        "剔除新条目后 trace 与接线前不等价（顺序/内容被改动）")
    # 追加位置：紧接既有 kert 条目之后，且是**连续**的一个块
    idx = [i for i, e in enumerate(r.assembly_trace) if _is_source_entry(e)]
    assert idx == list(range(idx[0], idx[0] + len(idx))), f"新条目不是连续块：{idx}"
    assert r.assembly_trace[idx[0] - 1].get("phase") == "kert", (
        "新条目必须追加在既有取数段之后（不得插到 kert 条目前面）")

    # data 与参照逐字相等（读取内容未被改写/裁剪）
    assert r.data == r_ref.data, "data 与接线前不等价（读取内容被裁改）"


def test_ki_messages_still_satisfy_existing_assertion(ws_provisioned):
    """复刻既有断言 ``test_skills.py:130``：含 ``KI-`` 的 message 必须都含 ``skipped``。

    若新条目把能力 ID / 资产引用 id 写进 ``message``，这条断言会**在既有测试里**变红
    —— 本用例是"提前失败"，把红点留在本片自己的文件里。
    """
    svc = SkillExecutionService(ws_provisioned)
    r = svc.execute("skill-customer-previsit-report", "guard-msg-1",
                    REQS["skill-customer-previsit-report"])
    msgs = [t.get("message", "") for t in r.assembly_trace]
    assert all("skipped" in m for m in msgs if "KI-" in m), msgs


def test_assembly_trace_validates_against_canonical_schema(ws_provisioned):
    """每条 trace 条目都必须通过 canonical schema 校验（T4），且 schema 必须**声明**新字段（T5）。

    T5 的理由：靠 ``additionalProperties: true`` 兜底 = "实现有字段、合同未声明"的失实模式
    （DECISION_SHEET C-3）。故本用例同时断言 schema 的 ``properties`` 里真的有两个字段。
    """
    schema = json.loads(TRACE_SCHEMA.read_text(encoding="utf-8"))
    props = schema.get("properties", {})
    for field in ("capabilityId", "sourceCode"):
        assert field in props, f"T5 违反：canonical schema 未声明 {field}（不得靠 additionalProperties 兜底）"

    svc = SkillExecutionService(ws_provisioned)
    for skill_id in WIRED_SKILLS:
        r = svc.execute(skill_id, f"guard-schema-{skill_id}", REQS[skill_id])
        for entry in r.assembly_trace:
            jsonschema.validate(entry, schema)


# --------------------------------------------------------------------------- #
# 4. 声明缺失/非法：**不得**拒绝（硬规则 E0）—— 变异 V11/V2
# --------------------------------------------------------------------------- #

def _provisioned_no_decl(ws: Path) -> Path:
    """已供给控制面、但**删除**声明文件的工作区（(γ) 形态；夹具缺失即 FAIL）。"""
    from kert.application.provision import provision_control_plane
    from kert.domain import workspace as ws_mod

    ws_mod.init_workspace(ws)
    provision_control_plane(ws, REPO_ROOT / "examples" / "bank-front-knowledge-maps")
    decl = declaration_path(ws)
    assert decl.is_file(), f"前置夹具失效：供给后应有 {decl}（fail-closed 而非 skip）"
    decl.unlink()
    return ws


def test_declaration_absent_is_refused(tmp_path):
    """**② B-2**（Owner 已批 2026-09-16）：声明缺失 ⇒ **拒绝执行**（fail-closed）。

    B-1 时本用例断言"回落 + 零拒绝"（硬规则 E0）；② 生效后**按裁定翻转**为拒绝。
    属**我方自建用例**的翻转（既有测试文件一字未改）。
    """
    from kert.application.skills import SkillExecutionService as Svc

    ws = _provisioned_no_decl(tmp_path / "no_decl")
    r = Svc(ws).execute("skill-customer-outreach-script", "guard-absent-1",
                        {"customerId": CUSTOMER_ID})
    # ② 拒绝：fail-closed（无半成品 + 既有拒绝码 + detail.sourceCode）
    assert r.status == "skill_error", (r.status, r.errors)
    assert r.data == {}, "fail-closed：不得返回残缺数据"
    assert r.errors and r.errors[0]["code"] == "KERT_PERMISSION_DENIED", r.errors
    entries = _source_entries(r.assembly_trace)
    assert _codes(r.assembly_trace) == [CODE_DECLARATION_ABSENT], r.assembly_trace
    assert entries[0]["status"] == "blocked", entries[0]      # ②：拒绝，不再是 degraded 回落
    assert "capabilityId" not in entries[0], "声明缺失 ⇒ 无能力可指（不伪造占位 ID）"
    assert "KI-" not in entries[0]["message"], entries[0]["message"]
    # **回落已不再发生**的机械证据：字面量路径若被走到，必留 `kert` 条目
    assert not any(t.get("phase") == "kert" for t in r.assembly_trace), (
        "② 生效后不得再走回落路径（`kert` 条目 = 回落发生的标志）")


def test_declaration_invalid_is_refused(tmp_path):
    """**② B-2**：声明非法（含未声明字段）⇒ 与缺失**不同码**、同样**拒绝**。"""
    from kert.application.skills import SkillExecutionService as Svc

    ws = _provisioned(tmp_path / "invalid_ws")
    doc = json.loads(REAL_DECL.read_text(encoding="utf-8"))
    doc["capabilities"][0]["未声明字段"] = 1
    declaration_path(ws).write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")

    r = Svc(ws).execute("skill-customer-meeting-script", "guard-invalid-1",
                        {"customerId": CUSTOMER_ID})
    assert r.status == "skill_error" and r.data == {}, (r.status, r.errors)
    assert r.errors and r.errors[0]["code"] == "KERT_PERMISSION_DENIED", r.errors
    assert _codes(r.assembly_trace) == [CODE_DECLARATION_INVALID], r.assembly_trace
    assert _source_entries(r.assembly_trace)[0]["status"] == "blocked"
    assert not any(t.get("phase") == "kert" for t in r.assembly_trace)


def test_unavailable_still_falls_back_while_absent_refuses(tmp_path, ws_provisioned):
    """**①/② 分野**：``UNAVAILABLE``（源不可用）**仍按 B-1 回落**；``ABSENT``/``INVALID`` **拒绝**。

    三码仍须**互不相同**（V7）。本条是"② 的实现**不得**顺手改掉 ①"的机械载体（TL 边界 2）。
    """
    from kert.application.skills import SkillExecutionService as Svc

    # ①：声明存在、投影缺失 ⇒ 回落 + degraded（与 B-1 逐字相同）
    r_unavail = Svc(ws_provisioned).execute("skill-customer-previsit-report",
                                            "guard-tri-1", REQS["skill-customer-previsit-report"])
    assert r_unavail.status == "ok" and r_unavail.errors == []
    assert _codes(r_unavail.assembly_trace) == [CODE_UNAVAILABLE], r_unavail.assembly_trace
    assert _source_entries(r_unavail.assembly_trace)[0]["status"] == "degraded"
    assert any(t.get("phase") == "kert" for t in r_unavail.assembly_trace), (
        "① 必须仍走回落路径（`kert` 条目在场）")

    # ②：删声明（同一供给面）⇒ 拒绝
    ws_absent = _provisioned_no_decl(tmp_path / "absent_ws")
    r_absent = Svc(ws_absent).execute("skill-customer-previsit-report",
                                      "guard-tri-2", REQS["skill-customer-previsit-report"])
    assert r_absent.status == "skill_error" and r_absent.data == {}
    assert _codes(r_absent.assembly_trace) == [CODE_DECLARATION_ABSENT], r_absent.assembly_trace
    assert _source_entries(r_absent.assembly_trace)[0]["status"] == "blocked"
    assert not any(t.get("phase") == "kert" for t in r_absent.assembly_trace)

    assert len({CODE_UNAVAILABLE, CODE_DECLARATION_ABSENT, CODE_DECLARATION_INVALID}) == 3, (
        "三个码必须互不相同（混码会让归因错位）")
