#!/usr/bin/env python3
"""规模化供应链图谱性能验证（Kùzu 查询计时，对外 8106 等价）。

用法：python scripts/perf_supply_chain.py --workspace <demo_workspace>
"""

from __future__ import annotations

import argparse
import statistics
import time
from pathlib import Path

from dkws.application.services import KnowledgeService
from dkws.infrastructure.graph.kuzu_builder import KuzuGraphBuilder


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace", "-w", required=True)
    ap.add_argument("--service", default="supply_chain_graph")
    args = ap.parse_args()
    ws = Path(args.workspace).resolve()

    b = KuzuGraphBuilder(ws, service_id=args.service)
    fp = b.fingerprint_of(b._active_version())
    if not fp:
        print("无图谱投影"); return
    print(f"图谱规模: {fp['nodes']} 节点 / {fp['edges']} 边")

    svc = KnowledgeService(ws, service_id=args.service)
    start = "CORE-000"

    def bench(label, fn, runs=5):
        times = []
        for _ in range(runs):
            t0 = time.monotonic()
            r = fn()
            times.append((time.monotonic() - t0) * 1000)
        print(f"  {label:28s} 中位 {statistics.median(times):8.1f}ms  "
              f"min {min(times):7.1f}ms  max {max(times):7.1f}ms  "
              f"(runs={runs}, 结果节点 {r.data.get('node_count')}, 边 {r.data.get('edge_count')})")

    print("\n== Kùzu 查询性能（1000+ 节点图谱）==")
    bench("闭包：CORE-000 上游全量(≤5级,全量)",
          lambda: svc.graph([start], direction="IN", max_depth=5, max_nodes=1000, mode="closure"))
    bench("邻居：CORE-000 一级上下游",
          lambda: svc.graph([start], direction="BOTH", max_depth=1, mode="neighbor"))
    bench("路径：最深上游→核心(≤5级,全量)",
          lambda: svc.graph([start], direction="IN", max_depth=5, max_nodes=1000, mode="paths"))
    bench("聚合：全图按类型计数(≤3级)",
          lambda: svc.graph([start], direction="BOTH", max_depth=3, mode="neighbor"))


if __name__ == "__main__":
    main()
