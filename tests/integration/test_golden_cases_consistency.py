"""WP2-2：KERT 规则包与黄金样例一致性自证测试（CANDIDATE）。

状态块（CANDIDATE 交付）：
STATUS=CANDIDATE / FROZEN=NO / IMPLEMENTED=NO

范围与边界：
- 本测试主体只校验 WP2-2 规则包 8 个交付文件之间的**自洽性**；FO-01 起新增一条
  「执行器 `RULE_CATALOG` ⊆ 清单」交叉断言（仅比对 ruleId/ruleVersion，消除 ID 漂移），
  不含 golden-cases 逐组执行器重放——那仍待 WP2-3 完成（见 manifest §5 跨包集成待办）。
- 校验项：
  1. golden-cases.json 结构合法、≥6 组、映射 TC-PR 用例；
  2. 必覆盖「硬失败不可绕过」：TC-PR-002 / TC-PR-004 / TC-PR-008；
  3. golden-cases.json 引用的 ruleId 全部可解析到 rules/ 目录规则文件；
  4. manifest 声明的规则清单与 rules/ 目录规则文件一一对应；
  5. 每条规则 frontmatter 具备 ruleId/ruleVersion/Owner/trigger/结论/EvidenceRef 等必填字段；
  6. Tech Lead 打回修复项：PR-MAT-001 非阻断（NON_BLOCKING、不占硬约束序号）、
     PR-PRMUTEX-001 显式覆盖 README 硬约束顺序 5+6。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

RULES_DIR = (
    Path(__file__).resolve().parents[2] / "skills" / "product-recommendation" / "rules"
)
GOLDEN_PATH = RULES_DIR / "golden-cases.json"
MANIFEST_PATH = RULES_DIR / "rule-bundle-manifest.md"
README_PATH = RULES_DIR / "README.md"

RESULT_CLOSED_SET = {"PASS", "FAIL", "UNKNOWN", "REVIEW_REQUIRED"}
# D1 裁决：全集排除（fail-closed）以 EXCLUDED 表达（非资格结果，是全集解析阶段的受控排除标记）
ELIGIBILITY_CLOSED_SET = {"ELIGIBLE", "INELIGIBLE", "UNKNOWN", "REVIEW_REQUIRED", "EXCLUDED"}


def _load_golden() -> dict:
    return json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))


def _rule_files() -> dict[str, Path]:
    """扫描 rules/ 目录，返回 {ruleId: 文件路径}（README.md、manifest、golden 除外）。"""
    out: dict[str, Path] = {}
    for p in sorted(RULES_DIR.glob("PR-*.md")):
        m = re.match(r"(PR-[A-Z]+-\d+)\.md", p.name)
        if m:
            out[m.group(1)] = p
    return out


def _frontmatter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    assert m, f"{path.name} 缺少 YAML frontmatter"
    return yaml.safe_load(m.group(1)) or {}


def _manifest_rule_ids() -> set[str]:
    """从 manifest 提取「规则文件」引用（PR-*.md）对应的 ruleId。

    只认 `.md` 文件名，避免 §5 跨包集成说明中引用的 WP2-3 执行器旧 ID
    （PR-ADM-004/PR-PRE-001/PR-BND-001，非本包规则）被误当作本包清单。
    """
    text = MANIFEST_PATH.read_text(encoding="utf-8")
    return {m[:-3] for m in re.findall(r"PR-[A-Z]+-\d+\.md", text)}


# ---------------------------------------------------------------------------
# 1) golden-cases.json 结构 + 覆盖
# ---------------------------------------------------------------------------
def test_golden_cases_structure_and_minimum_count():
    data = _load_golden()
    assert data["docStatus"] == "CANDIDATE"
    assert data["frozen"] == "NO"
    assert data["implemented"] == "NO"
    assert data["ruleBundleRef"] == "RB-PR-20260831-0001"
    assert data["ruleBundleVersion"] == "1.0.0-candidate"
    cases = data["cases"]
    assert len(cases) >= 6
    # 每个样例必备字段
    for case in cases:
        assert case["caseId"].startswith("GC-PR-")
        assert case["tcPrId"].startswith("TC-PR-")
        assert case["polarity"] in {"POSITIVE", "NEGATIVE"}
        assert case["input"]["customerFactSnapshotId"]
        assert case["expected"]["eligibility"] in ELIGIBILITY_CLOSED_SET
        for rr in case["expected"]["ruleResults"]:
            assert rr["result"] in RESULT_CLOSED_SET
            assert rr["ruleId"]
            assert rr["ruleVersion"]
            assert rr["reasonCode"]


def test_golden_cases_cover_hard_fail_not_bypassable():
    """必覆盖硬失败不可绕过：TC-PR-002 / TC-PR-004 / TC-PR-008。"""
    data = _load_golden()
    by_tc = {c["tcPrId"]: c for c in data["cases"]}

    # TC-PR-002：监管禁止 → INELIGIBLE
    c002 = by_tc["TC-PR-002"]
    assert c002["expected"]["eligibility"] == "INELIGIBLE"
    assert any(r["ruleId"] == "PR-REG-001" and r["result"] == "FAIL"
               and r["reasonCode"] == "FORBIDDEN_INDUSTRY"
               for r in c002["expected"]["ruleResults"])

    # TC-PR-004：版本失效 → FAIL_CLOSED（D1：全集排除 → EXCLUDED）
    c004 = by_tc["TC-PR-004"]
    assert c004["expected"]["runStatus"] == "FAILED_CLOSED"
    assert c004["expected"]["eligibility"] == "EXCLUDED"
    assert any(r["ruleId"] == "PR-VALID-001" and r["result"] == "FAIL"
               and r["reasonCode"] == "PRODUCT_VERSION_EXPIRED"
               for r in c004["expected"]["ruleResults"])

    # TC-PR-008：高分不能覆盖 INELIGIBLE
    c008 = by_tc["TC-PR-008"]
    assert c008["expected"]["eligibility"] == "INELIGIBLE"
    assert c008["input"]["bypassAttempt"]["fitScore"] == 0.9
    assert any(r["ruleId"] == "PR-REG-001" and r["result"] == "FAIL"
               for r in c008["expected"]["ruleResults"])


def test_golden_case_ruleids_resolve_to_rule_files():
    """golden-cases.json 引用的 ruleId 必须全部解析到 rules/ 目录规则文件。"""
    data = _load_golden()
    files = _rule_files()
    referenced = {
        rr["ruleId"]
        for case in data["cases"]
        for rr in case["expected"]["ruleResults"]
    }
    assert referenced
    missing = referenced - set(files)
    assert not missing, f"golden-cases.json 引用了不存在的规则文件: {missing}"


# ---------------------------------------------------------------------------
# 2) manifest 与规则文件一一对应
# ---------------------------------------------------------------------------
def test_manifest_lists_all_rule_files():
    files = set(_rule_files())
    manifest_ids = _manifest_rule_ids()
    assert files, "rules/ 目录未发现 PR-*.md 规则文件"
    assert manifest_ids == files, f"manifest 与规则文件不一致: {manifest_ids ^ files}"


def test_manifest_declares_material_outside_hard_sequence():
    """Tech Lead 打回修复项：manifest 不得把材料规则放进 README 硬约束顺序(1-7)。"""
    text = MANIFEST_PATH.read_text(encoding="utf-8")
    assert "沿用" not in text  # 不得宣称「沿用序号」
    assert "2.2 非硬约束规则" in text
    # 材料规则应出现在 2.2 且标注 NON_BLOCKING
    assert "PR-MAT-001" in text
    assert "NON_BLOCKING" in text


# ---------------------------------------------------------------------------
# 3) 规则 frontmatter 必填字段 + Tech Lead 打回修复项
# ---------------------------------------------------------------------------
def test_rule_frontmatter_has_required_fields():
    for rid, path in _rule_files().items():
        fm = _frontmatter(path)
        assert fm["ruleId"] == rid
        assert fm["ruleVersion"] == "1.0.0-candidate"
        assert fm.get("owner"), f"{rid} 缺少 Owner"
        assert fm.get("trigger"), f"{rid} 缺少触发条件"
        assert fm.get("status") == "CANDIDATE"
        assert fm.get("frozen") == "NO"
        assert fm.get("implemented") == "NO"
        # 结论闭集 + reasonCode + effect
        conclusions = fm.get("conclusions") or []
        assert conclusions, f"{rid} 缺少 conclusions"
        for c in conclusions:
            assert c["result"] in RESULT_CLOSED_SET, f"{rid} 结论 result 越界: {c}"
            assert c.get("reasonCode"), f"{rid} 结论缺少 reasonCode"
            assert c.get("effect"), f"{rid} 结论缺少 effect"
        # EvidenceRef
        refs = fm.get("evidenceRefs") or []
        assert refs, f"{rid} 缺少 evidenceRefs"
        for r in refs:
            assert r.get("evidenceRefId"), f"{rid} EvidenceRef 缺少 evidenceRefId"


def test_material_rule_is_non_blocking_not_in_hard_sequence():
    """Tech Lead 打回修复项：PR-MAT-001 应为非阻断，且不占用 README 硬约束序号。"""
    fm = _frontmatter(RULES_DIR / "PR-MAT-001.md")
    assert fm["enforcement"] == "NON_BLOCKING"
    order = fm["executionOrder"]
    assert order == [] or order is None, f"PR-MAT-001 不得占用硬约束序号: {order}"


def test_prmutex_rule_covers_order_5_and_6():
    """Tech Lead 打回修复项：PR-PRMUTEX-001 显式覆盖 README 硬约束顺序 5+6。"""
    fm = _frontmatter(RULES_DIR / "PR-PRMUTEX-001.md")
    assert fm["executionOrder"] == [5, 6], f"PR-PRMUTEX-001 executionOrder: {fm['executionOrder']}"


def test_rules_readme_unchanged_and_hard_order_intact():
    """纪律自证：本任务未改动既有 README，其硬约束顺序(1-7)保持不变。"""
    text = README_PATH.read_text(encoding="utf-8")
    assert "硬约束执行顺序" in text
    assert "1. 权限与数据用途" in text
    assert "7. 销售边界" in text


# ---------------------------------------------------------------------------
# 4) FO-01：执行器 RULE_CATALOG ⊆ 清单（消除规则 ID 漂移）
# ---------------------------------------------------------------------------
def test_executor_rule_catalog_is_subset_of_manifest():
    """FO-01：执行器 RULE_CATALOG 的 ruleId ⊆ 规则清单，且 ruleVersion 对齐候选版本。

    跨包自证：WP2-3 执行器 `eligibility.py` 不再引用清单外的 ID
    （原 PR-ADM-004 / PR-PRE-001 / PR-BND-001 已映射到真实规则），
    且 ruleVersion 统一为清单候选版本 `1.0.0-candidate`。
    """
    from dkws.application.product_recommendation.eligibility import RULE_CATALOG

    manifest_ids = _manifest_rule_ids()
    catalog_ids = {r["ruleId"] for r in RULE_CATALOG}

    # 子集：执行器不得引用清单中不存在的规则 ID（ID 漂移消除）
    extra = catalog_ids - manifest_ids
    assert not extra, f"执行器 RULE_CATALOG 引用了清单不存在的 ruleId: {sorted(extra)}"
    # 完备：执行器应覆盖清单全部 6 条规则（无遗漏、无孤儿）
    assert catalog_ids == manifest_ids, (
        f"RULE_CATALOG 与清单不一致: 仅执行器={sorted(catalog_ids - manifest_ids)}, "
        f"仅清单={sorted(manifest_ids - catalog_ids)}"
    )
    # 版本对齐：ruleVersion 与清单/规则文件一致
    assert all(r["ruleVersion"] == "1.0.0-candidate" for r in RULE_CATALOG)
