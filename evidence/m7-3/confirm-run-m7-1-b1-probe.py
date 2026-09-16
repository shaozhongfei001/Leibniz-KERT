#!/usr/bin/env python3
"""M7.1-B1 **最终确认跑**探针（R-G 合规版；临时脚本，位于 /tmp，不入库、不改仓内代码）。

与原探针（`/tmp/m71b_impact_probe.py`）的差异 —— 全部为满足 **R-G** 与"红集逐条报"：

1. **双计数在同一脚本、同一次跑内产出**（R-G 第 2 条）：
   同时包装 `_load_ki`（既有）与 `_load_ki_from_declaration`（B-1 新读取点），
   **不跑两次再拼接**（那会引入 R-A 的 nodeid 归属竞态）。
2. **主口径 = `_route_plan` 命中用例的显式 node id 集合**（R-G 第 1 条）：
   逐条打印，**不提供**"命中数一致"式的聚合结论；聚合数只作交叉参考并显式标注"不得单独作为证据"。
3. **红集在同一次跑内逐条采集**（`pytest_runtest_logreport`）⇒ 支持"红灯变少也要报"。
4. 双计数的**差集非空且归因不了 ⇒ 停下条件**（R-G 第 3 条）：本脚本只**报差集**，不替人做归因结论。
5. 输出机器可读 JSON（含各集合与红集），便于与基准逐条 diff。

用法（**收到 TL 信号后**才执行）：
    cd /home/szf/dev/Leibniz-KERT && .venv/bin/python /tmp/m71b_confirm_probe.py
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

import pytest

REPO = Path("/home/szf/dev/Leibniz-KERT")
sys.path.insert(0, str(REPO / "src"))

DECL_REL = Path("90_control") / "schema" / "knowledge_sources.json"

RECORDS: list[dict] = []
CURRENT = {"nodeid": ""}
REDS: list[str] = []


def _common(self) -> dict:  # noqa: ANN001
    ws = Path(self.workspace) if self.workspace is not None else None
    proj = (ws / "04_serve" / "customer_knowledge" / "CURRENT.md") if ws else None
    return {
        "nodeid": CURRENT["nodeid"],
        "workspace": str(ws) if ws else None,
        "declarationPresent": bool(ws and (ws / DECL_REL).is_file()),
        "ckpAvailable": bool(getattr(self, "_ckp", None) is not None
                             and getattr(self._ckp, "available", False)),
        "projectionPresent": bool(proj and proj.is_file()),
    }


def _install_instrumentation() -> None:
    """只读仪器：记录调用与结果，**不改行为**、不改任何仓内文件。"""
    from kert.application import skills as skills_mod

    svc = skills_mod.SkillExecutionService
    orig_route = svc._route_plan
    orig_supply = svc._run_supply_chain
    orig_load_ki = svc._load_ki
    orig_load_ki_new = svc._load_ki_from_declaration

    def route_wrapper(self, trace, expected_map_id, task):  # noqa: ANN001
        rec = _common(self)
        rec.update({"kind": "route_plan", "task": task,
                    "expectedMapId": expected_map_id, "outcome": ""})
        RECORDS.append(rec)
        try:
            res = orig_route(self, trace, expected_map_id, task)
        except Exception as exc:  # noqa: BLE001 - 只记录，不改行为
            rec["outcome"] = f"RAISED:{type(exc).__name__}:{getattr(exc, 'code', '')}"
            raise
        rec["outcome"] = "ALLOWED"
        return res

    def load_ki_wrapper(self, customer_id, trace):  # noqa: ANN001
        rec = _common(self)
        rec.update({"kind": "load_ki", "task": "", "expectedMapId": None, "outcome": ""})
        RECORDS.append(rec)
        out = orig_load_ki(self, customer_id, trace)
        rec["outcome"] = f"HITS={len(out)}"
        return out

    def load_ki_new_wrapper(self, customer_id, trace):  # noqa: ANN001
        """B-1 新读取点（**签名与 `_load_ki` 逐字一致** ⇒ 不干扰守卫用例）。"""
        rec = _common(self)
        rec.update({"kind": "load_ki_from_declaration", "task": "",
                    "expectedMapId": None, "outcome": ""})
        RECORDS.append(rec)
        out = orig_load_ki_new(self, customer_id, trace)
        rec["outcome"] = f"HITS={len(out)}"
        return out

    def supply_wrapper(self, request, trace):  # noqa: ANN001
        rec = _common(self)
        rec.update({"kind": "supply_chain_unwired",
                    "task": "bank-front-supply-chain-graph",
                    "expectedMapId": None, "outcome": "OK"})
        RECORDS.append(rec)
        return orig_supply(self, request, trace)

    svc._route_plan = route_wrapper
    svc._load_ki = load_ki_wrapper
    svc._load_ki_from_declaration = load_ki_new_wrapper
    svc._run_supply_chain = supply_wrapper


class Tracker:
    """nodeid 归属 + 红集采集（都在同一次跑内）。"""

    def pytest_runtest_setup(self, item):  # noqa: ANN001
        CURRENT["nodeid"] = item.nodeid

    def pytest_runtest_teardown(self, item, nextitem):  # noqa: ANN001
        CURRENT["nodeid"] = nextitem.nodeid if nextitem is not None else ""

    def pytest_runtest_logreport(self, report):  # noqa: ANN001
        if report.failed and report.when in ("setup", "call"):
            if report.nodeid not in REDS:
                REDS.append(report.nodeid)


def _set_of(kind: str) -> list[str]:
    return sorted({r["nodeid"] for r in RECORDS if r["kind"] == kind})


def main() -> int:
    _install_instrumentation()
    args = ["tests/unit", "tests/integration", "tests/contract", "tests/recovery",
            "-p", "no:warnings", "-p", "no:cacheprovider", "-o", "addopts=",
            "-q", "--tb=no"]
    rc = pytest.main(args, plugins=[Tracker()])

    print()
    print("=" * 78)
    print("M7.1-B1 最终确认跑（R-G 合规版）")
    print("=" * 78)
    print(f"[env] python={sys.version.split()[0]}  pytest={pytest.__version__}  "
          f"pytest_exit={int(rc)}")
    print("[cmd] cd /home/szf/dev/Leibniz-KERT && "
          ".venv/bin/python /tmp/m71b_confirm_probe.py")

    route_set = _set_of("route_plan")
    old_set = _set_of("load_ki")
    new_set = _set_of("load_ki_from_declaration")
    supply_set = _set_of("supply_chain_unwired")

    print(f"\n[d] **R-G 主口径**：`_route_plan` 命中用例的**显式 node id 集合**（逐条，共 {len(route_set)}）")
    for n in route_set:
        print(f"    {n}")

    print("\n[d2] **同脚本同一次跑的双计数**（R-G 第 2 条）")
    print(f"    `_load_ki`                命中用例集合（逐条，共 {len(old_set)}）:")
    for n in old_set:
        print(f"      {n}")
    print(f"    `_load_ki_from_declaration` 命中用例集合（逐条，共 {len(new_set)}）:")
    for n in new_set:
        print(f"      {n}")

    only_old = sorted(set(old_set) - set(new_set))
    only_new = sorted(set(new_set) - set(old_set))
    print(f"    [差集] 仅 `_load_ki` 命中（新读取点未命中）: {only_old}")
    print(f"    [差集] 仅 `_load_ki_from_declaration` 命中: {only_new}")
    print(f"    [差集判据] 两集差是否为空: {not only_old and not only_new}"
          "（非空且**归因不了 ⇒ 停下报 TL**，R-G 第 3 条）")

    print("\n[d3] 聚合数（**仅交叉参考；R-G 明令不得单独作为证据**）")
    print(f"    route_plan={len(route_set)}  load_ki={len(old_set)}  "
          f"load_ki_from_declaration={len(new_set)}  supply_chain_unwired={len(supply_set)}")

    print(f"\n[e] **红集**（同一次跑内采集，逐条，共 {len(REDS)}）")
    for n in sorted(REDS):
        print(f"    {n}")

    print(f"\n[b] `_run_supply_chain`（未接线，O-6 范围）命中用例数: {len(supply_set)}")
    for n in supply_set:
        print(f"    {n}")

    out = Path("/tmp/m71b_confirm_sets.json")
    out.write_text(json.dumps({
        "env": {"python": sys.version.split()[0], "pytest": pytest.__version__,
                "pytest_exit": int(rc)},
        "reds": sorted(REDS),
        "route_plan_set": route_set,
        "load_ki_set": old_set,
        "load_ki_from_declaration_set": new_set,
        "supply_chain_unwired_set": supply_set,
        "diff_only_load_ki": only_old,
        "diff_only_new": only_new,
        "records": RECORDS,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n机器可读集合（供与基准逐条 diff）: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
