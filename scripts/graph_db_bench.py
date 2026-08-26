#!/usr/bin/env python3
"""轻量图数据库选型实测：10 万节点级对比（kuzu / igraph / networkx / sqlite）。

- 合成图：100000 节点，链式边(99999) + 随机边(200000) ≈ 30 万有向边；
- 指标：加载耗时、一跳邻居、深度3可达、出度聚合、存储体积、依赖体积。
- 说明：仅选型参考；不修改 DKWS 工程代码。
"""

from __future__ import annotations

import json
import os
import random
import shutil
import subprocess
import sys
import time
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", "/tmp/mpl")

N_NODES = 100_000
N_EXTRA_EDGES = 200_000
WORK = Path("/tmp/graphbench") if os.path.exists("/tmp") else Path("examples/graphbench")
shutil.rmtree(WORK, ignore_errors=True)
WORK.mkdir(parents=True, exist_ok=True)

random.seed(42)
edges = [(f"n{i}", f"n{i+1}", i % 7) for i in range(N_NODES - 1)]
for i in range(N_EXTRA_EDGES):
    edges.append((f"n{random.randrange(N_NODES)}", f"n{random.randrange(N_NODES)}", i % 7))
print(f"图规模: {N_NODES} 节点, {len(edges)} 有向边")


def report(name, secs, extra=""):
    print(f"  [{name:10s}] {secs:7.2f}s  {extra}")


# ============ 1) SQLite（自建图 schema，基线） ============
def bench_sqlite():
    t0 = time.monotonic()
    con = sqlite3.connect(WORK / "graph.db")
    con.execute("PRAGMA journal_mode=OFF")
    con.execute("CREATE TABLE nodes(eid TEXT PRIMARY KEY)")
    con.execute("CREATE TABLE edges(src TEXT, rel INTEGER, tgt TEXT)")
    con.executemany("INSERT INTO nodes VALUES (?)", [(f"n{i}",) for i in range(N_NODES)])
    con.executemany("INSERT INTO edges VALUES (?,?,?)", edges)
    con.execute("CREATE INDEX idx_e_src ON edges(src)")
    con.execute("CREATE INDEX idx_e_tgt ON edges(tgt)")
    con.commit()
    load = time.monotonic() - t0
    t0 = time.monotonic()
    n1 = con.execute("SELECT COUNT(*) FROM edges WHERE src='n50000'").fetchone()[0]
    t1 = time.monotonic() - t0
    t0 = time.monotonic()
    rows = con.execute("""
        WITH RECURSIVE r(src,tgt,d) AS (
          SELECT src,tgt,1 FROM edges WHERE src='n50000'
          UNION SELECT e.src,e.tgt,r.d+1 FROM edges e JOIN r ON e.src=r.tgt WHERE r.d<3
        ) SELECT COUNT(DISTINCT tgt) FROM r""").fetchone()[0]
    t3 = time.monotonic() - t0
    con.close()
    size = (WORK / "graph.db").stat().st_size / 1024 / 1024
    report("sqlite", load, f"neighbor={n1} reach3={rows} file={size:.1f}MB")
    return {"load": load, "n1": n1, "reach3": rows, "size_mb": size}


# ============ 2) Kuzu（嵌入式 Cypher） ============
def bench_kuzu():
    import kuzu
    t0 = time.monotonic()
    with open(WORK / "nodes.csv", "w") as f:
        for i in range(N_NODES):
            f.write(f"n{i}\n")
    with open(WORK / "edges.csv", "w") as f:
        for a, b, r in edges:
            f.write(f"{a},{b},{r}\n")  # kuzu REL 默认列序: src,tgt,rel
    db = kuzu.Database(str(WORK / "kuzu_db"))
    con = kuzu.Connection(db)
    con.execute("CREATE NODE TABLE Node(eid STRING, PRIMARY KEY(eid))")
    con.execute("CREATE REL TABLE Knows(FROM Node TO Node, rel INT)")
    con.execute(f"COPY Node FROM '{WORK / 'nodes.csv'}'")
    con.execute(f"COPY Knows FROM '{WORK / 'edges.csv'}'")
    load = time.monotonic() - t0
    t0 = time.monotonic()
    r1 = con.execute("MATCH (a:Node)-[:Knows]->(b) WHERE a.eid='n50000' RETURN count(b)")
    n1 = r1.get_next()[0]
    t1 = time.monotonic() - t0
    t0 = time.monotonic()
    r3 = con.execute("MATCH (a:Node)-[:Knows*1..3]->(b) WHERE a.eid='n50000' RETURN count(DISTINCT b)")
    reach3 = r3.get_next()[0]
    t3 = time.monotonic() - t0
    t0 = time.monotonic()
    agg = con.execute("MATCH (a)-[k:Knows]->() RETURN a.eid, count(k) ORDER BY count(k) DESC LIMIT 1")
    top = agg.get_next()
    t4 = time.monotonic() - t0
    db.close()
    size = sum(f.stat().st_size for f in (WORK / "kuzu_db").rglob("*")) / 1024 / 1024
    report("kuzu", load, f"neighbor={n1} reach3={reach3} agg_top={top[0]}:{top[1]} file={size:.1f}MB")
    return {"load": load, "n1": n1, "reach3": reach3, "size_mb": size}


# ============ 3) igraph（C 内核内存图） ============
def bench_igraph():
    import igraph as ig
    t0 = time.monotonic()
    g = ig.Graph(directed=True)
    g.add_vertices(N_NODES)
    g.add_edges([(int(e[0][1:]), int(e[1][1:])) for e in edges])
    g.es["rel"] = [e[2] for e in edges]
    load = time.monotonic() - t0
    t0 = time.monotonic()
    n1 = len(g.neighbors(50000, mode="out"))
    t1 = time.monotonic() - t0
    t0 = time.monotonic()
    reach3 = len(g.neighborhood(50000, order=3, mode="out"))
    t3 = time.monotonic() - t0
    t0 = time.monotonic()
    top = sorted(g.outdegree(), reverse=True)[0]
    t4 = time.monotonic() - t0
    del g
    report("igraph", load, f"neighbor={n1} reach3={reach3} max_outdegree={top}")
    return {"load": load, "n1": n1, "reach3": reach3}


# ============ 4) networkx（纯 Python 内存图，基线） ============
def bench_networkx():
    import networkx as nx
    t0 = time.monotonic()
    g = nx.DiGraph()
    g.add_nodes_from(f"n{i}" for i in range(N_NODES))
    g.add_edges_from((a, b) for a, b, _ in edges)
    load = time.monotonic() - t0
    t0 = time.monotonic()
    n1 = len(list(g.successors("n50000")))
    t1 = time.monotonic() - t0
    t0 = time.monotonic()
    reach3 = len(nx.descendants_at_distance(g, "n50000", 3))
    t3 = time.monotonic() - t0
    report("networkx", load, f"neighbor={n1} reach3={reach3}")
    return {"load": load, "n1": n1, "reach3": reach3}


if __name__ == "__main__":
    import sqlite3
    results = {}
    print("\n== SQLite =="); results["sqlite"] = bench_sqlite()
    print("== Kuzu =="); results["kuzu"] = bench_kuzu()
    print("== igraph =="); results["igraph"] = bench_igraph()
    print("== networkx =="); results["networkx"] = bench_networkx()
    print("\n结果汇总:", json.dumps(results, ensure_ascii=False, indent=2))
    # 依赖体积（pip 已装 wheel 大小）
    try:
        dep = subprocess.run([sys.executable, "-m", "pip", "show", "kuzu", "igraph"],
                             capture_output=True, text=True).stdout
        print("\n[pip 元数据见上]")
    except Exception:
        pass
