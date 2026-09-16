"""T2/T3：把「语义载体是谁」与「哪些 API 是**预留**」写成**可执行断言**（防漂移）。

- **T2①**：业务语义的载体 = **KI 标题 + 正文**（在**真实投影数据**上验证）
  + **能力读取绑定**（声明驱动，且与既有隐式约定逐字等价）；
- **T2②**：``ActivationContract.semantic_queries`` / ``rule_checks`` **已解析**、但**无运行时消费者**
  ⇒ 判定 **预留**（不为接线而接线）；
- **T3** ：``knowledge_map.resolve_for_task`` / ``route_policy.resolve_via_registry_only`` **未接线**
  ⇒ 判定 **预留**（跳过策略放行 = 绕过治理面）。

判定依据：``evidence/m7-3/EVIDENCE-SEMANTICS-MAP-RESERVATION-AND-LINEAGE-INPUT.md``。
**若日后真正接线，本文件会变红** —— 那是要求同步更新"判定 + 证据"，不是缺陷。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (str(REPO_ROOT / "src"), str(REPO_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from kert.application.customer_knowledge import (  # noqa: E402
    _KI_RE,
    KI_ITEMS,
    CustomerKnowledgeProvider,
)
from kert.domain.knowledge_source import resolve_declaration  # noqa: E402

SRC = REPO_ROOT / "src" / "kert"
ACTIVATIONS = (REPO_ROOT / "examples" / "bank-front-knowledge-maps"
               / "90_control" / "schema" / "activations")
CUSTOMER_ID = "CUST-CORP-0001"


def _scan(pattern: str, *, allow: set[str]) -> dict[str, list[int]]:
    """扫 ``src/kert/**/*.py``；返回 ``{相对路径: 行号}``（排除 ``allow`` 中的文件名）。"""
    rx = re.compile(pattern)
    hits: dict[str, list[int]] = {}
    for p in sorted(SRC.rglob("*.py")):
        if p.name in allow:
            continue
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if rx.search(line):
                hits.setdefault(str(p.relative_to(REPO_ROOT)), []).append(i)
    return hits


@pytest.fixture
def ws_seeded(ws_provisioned):
    """已供给控制面 + 已种客户知识的工作区（与既有集成测试同法）。"""
    from scripts.seed_customer_knowledge import seed_customer_knowledge

    seed_customer_knowledge(ws_provisioned, quiet=True)
    return ws_provisioned


# --------------------------------------------------------------------------- #
# T2① 语义载体 = KI 标题 + 正文（真实数据）
# --------------------------------------------------------------------------- #

def test_semantics_are_carried_by_ki_title_and_body(ws_seeded):
    """载体是 KI **标题（语义键）+ 正文（语义载荷）**：在真实投影上验证，不靠常量自述。"""
    ki = CustomerKnowledgeProvider(ws_seeded).ki_map(CUSTOMER_ID)

    assert set(ki) == {k for k, _ in KI_ITEMS}, "计划资产引用应恰好是这 7 条 KI"
    for kid, title in KI_ITEMS:
        assert ki[kid]["title"] == title, f"{kid} 的语义键（标题）被改动"
        assert ki[kid]["content"].strip(), f"{kid} 正文为空 ⇒ 语义载荷缺失"


def test_read_binding_drives_title_parsing_and_matches_implicit_convention(ws_provisioned):
    """读取绑定来自**声明**，且去掉命名分组后与既有隐式约定**逐字等价**（防两套语义口径）。"""
    load = resolve_declaration(ws_provisioned)
    assert load.allowed, load.reason
    caps = load.declaration.capabilities
    assert len(caps) == 1, [c.capability_id for c in caps]

    match = caps[0].read_contract.asset_match
    assert match.field == "heading_path[0]"
    assert re.sub(r"\(\?P<\w+>", "(", match.pattern) == _KI_RE.pattern, (
        f"声明 pattern 与隐式约定不等价: {match.pattern!r} vs {_KI_RE.pattern!r}")


# --------------------------------------------------------------------------- #
# T2② semanticQueries / ruleChecks：**预留**（已解析、无消费者）
# --------------------------------------------------------------------------- #

def test_semantic_queries_and_rule_checks_have_no_runtime_consumer():
    """预留判定（无消费者侧）：若出现消费者 ⇒ 本断言变红，须复核判定与证据。"""
    hits = _scan(r"\.(semantic_queries|rule_checks)\b", allow={"activation_contract.py"})
    assert hits == {}, f"semanticQueries/ruleChecks 出现运行时消费者 ⇒ 预留判定须复核: {hits}"


def test_semantic_queries_and_rule_checks_are_parsed_from_real_contracts():
    """预留判定（已解析侧）：真实合同里二者**非空** ⇒ 确有数据、只是没有用途。"""
    from kert.domain.activation_contract import load_activation_contract_file

    files = sorted(ACTIVATIONS.glob("AC-*.json"))
    assert files, f"前置夹具失效：{ACTIVATIONS} 下无 AC-*.json"
    parsed = [load_activation_contract_file(p) for p in files]
    assert all(c.semantic_queries and c.rule_checks for c in parsed), \
        [(c.contract_id, len(c.semantic_queries), len(c.rule_checks)) for c in parsed]


# --------------------------------------------------------------------------- #
# T3 地图按任务遍历：**预留**（无生产调用点）
# --------------------------------------------------------------------------- #

def test_map_task_traversal_has_no_production_call_site():
    """预留判定：``resolve_via_registry_only`` / 地图 ``resolve_for_task`` 均**无生产调用点**。

    白名单以外的任何出现 ⇒ 视为"已接线"，本断言变红（要求同步更新判定与证据）。
    """
    # ① 包装器本身：除其定义文件外，src 侧零出现
    a = _scan(r"\bresolve_via_registry_only\s*\(", allow={"route_policy.py"})
    assert a == {}, f"出现生产调用点 ⇒ 已接线，须更新判定与证据: {a}"

    # ② 地图遍历：src 侧只有三处**已知且无害**的出现
    #    · knowledge_map.py   —— 定义
    #    · activation_contract.py —— **另一套** API（合同注册表）的同名方法
    #    · route_policy.py    —— 预留包装器的**内部转发**（下方逐字钉住）
    b = _scan(r"\bresolve_for_task\s*\(",
              allow={"knowledge_map.py", "activation_contract.py", "route_policy.py"})
    assert b == {}, f"地图 resolve_for_task 出现生产调用点 ⇒ 已接线: {b}"

    rp = (REPO_ROOT / "src/kert/domain/route_policy.py").read_text(encoding="utf-8")
    body = rp.split("def resolve_via_registry_only", 1)[1].split("\n    def ", 1)[0]
    assert "self._registry.resolve_for_task(" in body, (
        "route_policy.py 内的那处调用必须**只在**预留包装器体内（不得挪作放行路径）")


def test_reserved_apis_carry_the_reservation_marker_in_source():
    """预留判定必须**落在源码**（可执行钉住注释，防"悄悄接线"）。"""
    for rel in ("src/kert/domain/route_policy.py", "src/kert/domain/knowledge_map.py"):
        text = (REPO_ROOT / rel).read_text(encoding="utf-8")
        assert "判定：预留（未接线）" in text, f"{rel} 缺少预留声明（D-17a / T3）"
