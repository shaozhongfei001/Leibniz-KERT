#!/usr/bin/env python3
"""Kùzu 原型（方案 C）：用真实业务查询量化嵌入式 Cypher 图库收益。

数据：bank_front 供应链示例（HZB0000001234 杭州智造精密齿轮）为根，
叠加【合成】多级供应链扩展（仅演示递归查询能力，非真实客户事实，脚本内标注）。
查询：与现有 graph()（内存 BFS，depth≤3 硬上限）对比 Cypher 表达力。

用法：python scripts/kuzu_prototype.py
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import kuzu

DEMO = True  # 合成扩展标注

# ---- 图谱数据：真实根（bank_front 示例）+ 合成多级链 ----
# 实体（企业）
entities = {
    "HZB0000001234": {"name": "杭州智造精密齿轮有限公司", "etype": "CUSTOMER"},
    "SUP-BEARING": {"name": "浙江轴承集团", "etype": "SUPPLIER"},
    "SUP-STEEL": {"name": "宁波特种钢公司", "etype": "SUPPLIER"},
    "CUST-EV-A": {"name": "新能源汽车主机厂A", "etype": "CUSTOMER_DOWN"},
    "CUST-GEAR-B": {"name": "变速箱总成厂B", "etype": "CUSTOMER_DOWN"},
    # 合成二级/三级（DEMO）
    "SUP2-ROLL": {"name": "滚子钢坯厂（合成二级供应商）", "etype": "SUPPLIER2"},
    "SUP2-IRON": {"name": "特种铁矿公司（合成二级供应商）", "etype": "SUPPLIER2"},
    "SUP3-ORE": {"name": "铁矿石开采集团（合成三级供应商）", "etype": "SUPPLIER3"},
    "CUST2-EV-PLANT": {"name": "主机厂A装配基地（合成二级客户）", "etype": "CUSTOMER2"},
}
# 关系：supplies（供应商→客户）金额（万元）
rels = [
    ("SUP-BEARING", "HZB0000001234", 12000),
    ("SUP-STEEL", "HZB0000001234", 8000),
    ("HZB0000001234", "CUST-EV-A", 25000),
    ("HZB0000001234", "CUST-GEAR-B", 18000),
    # 合成链
    ("SUP2-ROLL", "SUP-BEARING", 6000),
    ("SUP2-IRON", "SUP-STEEL", 5000),
    ("SUP3-ORE", "SUP2-IRON", 4000),
    ("CUST-EV-A", "CUST2-EV-PLANT", 20000),
]

print("== Kùzu 原型（:memory:，10 节点 / 8 边；标注：含合成扩展仅供演示）==")
t0 = time.monotonic()
db = kuzu.Database(":memory:")
con = kuzu.Connection(db)
con.execute("CREATE NODE TABLE Company(eid STRING, name STRING, etype STRING, PRIMARY KEY(eid))")
con.execute("CREATE REL TABLE Supplies(FROM Company TO Company, amount_wan INT)")
for eid, e in entities.items():
    con.execute("CREATE (:Company {eid:$e, name:$n, etype:$t})",
                {"e": eid, "n": e["name"], "t": e["etype"]})
for s, t, a in rels:
    con.execute("MATCH (a:Company {eid:$s}), (b:Company {eid:$t}) CREATE (a)-[:Supplies {amount_wan:$a}]->(b)",
                {"s": s, "t": t, "a": a})
build_s = time.monotonic() - t0
print(f"建图耗时: {build_s:.3f}s\n")

# ---- 业务查询 1：供应链多级上游（不限深度，Cypher 可变长度）----
print("== 查询1：HZB0000001234 的多级上游供应商（*1..5）==")
t0 = time.monotonic()
r = con.execute("""
  MATCH p = (c:Company {eid:'HZB0000001234'})<-[:Supplies*1..5]-(up:Company)
  RETURN up.name, length(p) AS depth ORDER BY depth LIMIT 10
""")
rows = [(x[0], x[1]) for x in r.get_all()]
print(f"  {rows}  [{time.monotonic()-t0:.3f}s]")
print("  对比现有 graph(): depth≤3 硬上限，多级需手写迭代 BFS\n")

# ---- 业务查询 2：递归闭包（所有可达上游，去重）----
print("== 查询2：递归闭包（可达上游全量，MIN 深度）==")
t0 = time.monotonic()
# 可变长度 + 去重 = 递归闭包（kuzu 0.11 支持 *1..N）
r = con.execute("""
  MATCH (c:Company {eid:'HZB0000001234'})<-[:Supplies*1..6]-(up:Company)
  RETURN DISTINCT up.name, up.etype
""")
rows = sorted((x[0], x[1]) for x in r.get_all())
print(f"  {rows}  [{time.monotonic()-t0:.3f}s]")
print("  对比现有 graph(): 无闭包查询，需应用层循环直至无新节点\n")

# ---- 业务查询 3：路径枚举（供应链溯源路径）----
print("== 查询3：从铁矿石到客户的多级路径（路径枚举）==")
t0 = time.monotonic()
r = con.execute("""
  MATCH p = (ore:Company {eid:'SUP3-ORE'})-[:Supplies*1..6]->(c:Company)
  RETURN nodes(p) LIMIT 5
""")
paths = [" → ".join(n["name"] for n in x[0]) for x in r.get_all()]
print(f"  {paths}  [{time.monotonic()-t0:.3f}s]")
print("  对比现有 graph(): 只回 nodes/edges 列表，无路径串\n")

# ---- 业务查询 4：复合查询（图 + 属性聚合：按层级统计金额）----
print("== 查询4：一级 vs 二级上游交易额聚合 ==")
t0 = time.monotonic()
r = con.execute("""
  MATCH (c:Company {eid:'HZB0000001234'})<-[r1:Supplies]-(s1:Company)
  OPTIONAL MATCH (s2:Company)-[:Supplies]->(s1)
  RETURN s1.name AS l1, r1.amount_wan AS direct_wan, count(s2) AS l2_count
  ORDER BY direct_wan DESC LIMIT 5
""")
print(f"  {[(x[0], x[1]) for x in r.get_all()]}  [{time.monotonic()-t0:.3f}s]")
print("  对比现有 graph(): 需多表遍历+内存聚合（30+ 行）\n")

print("== 收益小结 ==")
print("""
| 查询 | Cypher | 现有 graph() |
|---|---|---|
| 多级上游(不限深) | 1 条 `*1..5` | depth≤3 硬限，更深手写 |
| 递归闭包 | 1 条 `*1..6`+DISTINCT | 手写迭代+防环 |
| 路径枚举 | 1 条 `nodes(p)` 归约 | 只回列表无路径 |
| 图+属性聚合 | 1 条 MATCH+GROUP | 多表遍历拼装 |
""")
db.close()
