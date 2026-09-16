#!/usr/bin/env python3
"""产品知识图谱 Kuzu 初始化脚本。

创建节点表（ProductFamily / Product / Customer / Industry / Need）和关系表，
导入演示数据，供 SP-15 产品推荐准入与匹配查询使用。

用法:
    python scripts/graph/init_product_knowledge_graph.py
"""
from __future__ import annotations

import kuzu
import os
import sys

DB_PATH = os.environ.get("KUZU_DB_PATH", "data/product_knowledge_graph.kuzu")

# ──────────────────────────────────────────────
# DDL：节点表
# ──────────────────────────────────────────────
NODE_DDL = [
    # 产品域
    """
    CREATE NODE TABLE IF NOT EXISTS ProductFamily (
        family_id      STRING,
        name           STRING,
        name_en        STRING,
        family_desc    STRING,
        PRIMARY KEY (family_id)
    )
    """,
    # 产品
    """
    CREATE NODE TABLE IF NOT EXISTS Product (
        product_id     STRING,
        name           STRING,
        family_id      STRING,
        status         STRING,
        min_scale      STRING,
        min_rating     STRING,
        version        STRING,
        PRIMARY KEY (product_id)
    )
    """,
    # 客户
    """
    CREATE NODE TABLE IF NOT EXISTS Customer (
        customer_id    STRING,
        name           STRING,
        industry       STRING,
        scale          STRING,
        rating         STRING,
        tier           STRING,
        region         STRING,
        PRIMARY KEY (customer_id)
    )
    """,
    # 行业
    """
    CREATE NODE TABLE IF NOT EXISTS Industry (
        industry_id    STRING,
        name           STRING,
        name_en        STRING,
        PRIMARY KEY (industry_id)
    )
    """,
    # 需求
    """
    CREATE NODE TABLE IF NOT EXISTS Need (
        need_id        STRING,
        customer_id    STRING,
        need_type      STRING,
        need_status    STRING,
        scenario       STRING,
        PRIMARY KEY (need_id)
    )
    """,
]

# ──────────────────────────────────────────────
# DDL：关系表
# ──────────────────────────────────────────────
REL_DDL = [
    # 产品 → 产品域
    """
    CREATE REL TABLE IF NOT EXISTS BelongsToFamily (
        FROM Product TO ProductFamily
    )
    """,
    # 产品 → 行业（适用）
    """
    CREATE REL TABLE IF NOT EXISTS ApplicableToIndustry (
        FROM Product TO Industry
    )
    """,
    # 行业 → 行业（禁止）
    """
    CREATE REL TABLE IF NOT EXISTS ProhibitedForIndustry (
        FROM Product TO Industry
    )
    """,
    # 客户 → 行业
    """
    CREATE REL TABLE IF NOT EXISTS CustomerInIndustry (
        FROM Customer TO Industry
    )
    """,
    # 客户 → 需求
    """
    CREATE REL TABLE IF NOT EXISTS CustomerHasNeed (
        FROM Customer TO Need
    )
    """,
    # 需求 → 产品（匹配）
    """
    CREATE REL TABLE IF NOT EXISTS NeedMatchesProduct (
        FROM Need TO Product,
        match_score DOUBLE,
        match_reason STRING
    )
    """,
    # 产品 → 产品（前置）
    """
    CREATE REL TABLE IF NOT EXISTS PrerequisiteOf (
        FROM Product TO Product
    )
    """,
    # 产品 → 产品（互斥）
    """
    CREATE REL TABLE IF NOT EXISTS MutexWith (
        FROM Product TO Product
    )
    """,
    # 产品 → 产品（配套）
    """
    CREATE REL TABLE IF NOT EXISTS ComplementaryWith (
        FROM Product TO Product
    )
    """,
]

# ──────────────────────────────────────────────
# 种子数据
# ──────────────────────────────────────────────

PRODUCT_FAMILIES = [
    ("FINANCING", "融资服务", "Financing", "流动资金贷款、应收账款质押融资、订单融资等融资类产品"),
    ("SETTLEMENT", "结算服务", "Settlement", "单位结算账户、国内保理等结算类产品"),
    ("CASH_MANAGEMENT", "现金管理", "Cash Management", "现金池、资金归集、法人账户透支等现金管理类产品"),
    ("TRADE_FINANCE", "贸易融资", "Trade Finance", "银行承兑汇票、国内信用证等贸易融资类产品"),
    ("CROSS_BORDER", "跨境金融", "Cross Border", "跨境人民币结算、内保外贷等跨境金融类产品"),
    ("INVESTMENT_BANKING", "投资银行", "Investment Banking", "并购贷款等投行类产品"),
]

PRODUCTS = [
    # FINANCING
    ("PROD-FIN-001", "流动资金贷款", "FINANCING", "ACTIVE", "MICRO", None, "1.0.0"),
    ("PROD-FIN-002", "应收账款质押融资", "FINANCING", "ACTIVE", "SMALL", "BBB", "1.0.0"),
    ("PROD-FIN-003", "订单融资", "FINANCING", "ACTIVE", "SMALL", "BBB", "1.0.0"),
    # SETTLEMENT
    ("PROD-SET-001", "单位结算账户", "SETTLEMENT", "ACTIVE", "MICRO", None, "1.0.0"),
    ("PROD-SET-002", "国内保理", "SETTLEMENT", "ACTIVE", "SMALL", "BBB", "1.0.0"),
    # CASH_MANAGEMENT
    ("PROD-CM-001", "现金池", "CASH_MANAGEMENT", "ACTIVE", "MEDIUM", "A", "1.0.0"),
    ("PROD-CM-002", "资金归集", "CASH_MANAGEMENT", "ACTIVE", "SMALL", "BBB", "1.0.0"),
    ("PROD-CM-003", "法人账户透支", "CASH_MANAGEMENT", "ACTIVE", "MEDIUM", "A", "1.0.0"),
    # TRADE_FINANCE
    ("PROD-TF-001", "银行承兑汇票", "TRADE_FINANCE", "ACTIVE", "SMALL", "BBB", "1.0.0"),
    ("PROD-TF-002", "国内信用证", "TRADE_FINANCE", "ACTIVE", "SMALL", "BBB", "1.0.0"),
    # CROSS_BORDER
    ("PROD-CB-001", "跨境人民币结算", "CROSS_BORDER", "ACTIVE", "SMALL", "BBB", "1.0.0"),
    ("PROD-CB-002", "内保外贷", "CROSS_BORDER", "ACTIVE", "LARGE", "A", "1.0.0"),
    # INVESTMENT_BANKING
    ("PROD-IB-001", "并购贷款", "INVESTMENT_BANKING", "ACTIVE", "LARGE", "AA", "1.0.0"),
]

CUSTOMERS = [
    ("CUST-CORP-0001", "华东精工装备集团", "MANUFACTURING", "LARGE", "AA", "STRATEGIC", "CN-330100"),
    ("CUST-CORP-0002", "汇通供应链管理公司", "WHOLESALE_RETAIL", "MEDIUM", "A", "KEY", "CN-440300"),
    ("CUST-CORP-0003", "鼎信国际贸易集团", "WHOLESALE_RETAIL", "LARGE", "AA", "STRATEGIC", "CN-310100"),
]

INDUSTRIES = [
    ("MANUFACTURING", "制造业", "Manufacturing"),
    ("WHOLESALE_RETAIL", "批发和零售业", "Wholesale & Retail"),
    ("REAL_ESTATE", "房地产业", "Real Estate"),
    ("CONSTRUCTION", "建筑业", "Construction"),
    ("TRANSPORTATION", "交通运输业", "Transportation"),
    ("INFORMATION_TECHNOLOGY", "信息技术业", "Information Technology"),
]

NEEDS = [
    ("NEED-WORKING-CAPITAL", "CUST-CORP-0001", "FINANCING", "VERIFIED_FACT", "WORKING_CAPITAL_TURNOVER"),
    ("NEED-RECEIVABLE-FINANCING", "CUST-CORP-0001", "FINANCING", "INFERRED_NEED", "RECEIVABLE_HIGH_RATIO"),
    ("NEED-SUPPLY-CHAIN-SETTLEMENT", "CUST-CORP-0002", "SETTLEMENT", "VERIFIED_FACT", "SUPPLY_CHAIN_PAYMENT"),
    ("NEED-CASH-MANAGEMENT", "CUST-CORP-0002", "CASH_MANAGEMENT", "INFERRED_NEED", "GROUP_FUND_CENTRALIZATION"),
    ("NEED-CROSS-BORDER-SETTLEMENT", "CUST-CORP-0003", "CROSS_BORDER", "VERIFIED_FACT", "IMPORT_EXPORT_SETTLEMENT"),
    ("NEED-TRADE-FINANCE", "CUST-CORP-0003", "TRADE_FINANCE", "INFERRED_NEED", "TRADE_PAYMENT_GUARANTEE"),
]

# 产品 → 行业适用映射
APPLICABLE_INDUSTRIES = [
    # FINANCING 适用于大部分行业
    ("PROD-FIN-001", "MANUFACTURING"), ("PROD-FIN-001", "WHOLESALE_RETAIL"), ("PROD-FIN-001", "CONSTRUCTION"),
    ("PROD-FIN-002", "MANUFACTURING"), ("PROD-FIN-002", "WHOLESALE_RETAIL"),
    ("PROD-FIN-003", "MANUFACTURING"), ("PROD-FIN-003", "CONSTRUCTION"),
    # SETTLEMENT 适用于所有行业
    ("PROD-SET-001", "MANUFACTURING"), ("PROD-SET-001", "WHOLESALE_RETAIL"), ("PROD-SET-001", "CONSTRUCTION"),
    ("PROD-SET-001", "TRANSPORTATION"), ("PROD-SET-001", "INFORMATION_TECHNOLOGY"),
    ("PROD-SET-002", "MANUFACTURING"), ("PROD-SET-002", "WHOLESALE_RETAIL"),
    # CASH_MANAGEMENT 适用于大中型企业
    ("PROD-CM-001", "MANUFACTURING"), ("PROD-CM-001", "WHOLESALE_RETAIL"),
    ("PROD-CM-002", "MANUFACTURING"), ("PROD-CM-002", "WHOLESALE_RETAIL"),
    ("PROD-CM-003", "MANUFACTURING"), ("PROD-CM-003", "WHOLESALE_RETAIL"),
    # TRADE_FINANCE
    ("PROD-TF-001", "MANUFACTURING"), ("PROD-TF-001", "WHOLESALE_RETAIL"), ("PROD-TF-001", "CONSTRUCTION"),
    ("PROD-TF-002", "MANUFACTURING"), ("PROD-TF-002", "WHOLESALE_RETAIL"),
    # CROSS_BORDER
    ("PROD-CB-001", "WHOLESALE_RETAIL"), ("PROD-CB-001", "MANUFACTURING"),
    ("PROD-CB-002", "WHOLESALE_RETAIL"), ("PROD-CB-002", "MANUFACTURING"),
    # INVESTMENT_BANKING
    ("PROD-IB-001", "MANUFACTURING"), ("PROD-IB-001", "WHOLESALE_RETAIL"),
]

# 产品 → 行业禁止映射
PROHIBITED_INDUSTRIES = [
    ("PROD-SET-002", "REAL_ESTATE"),
    ("PROD-CM-003", "REAL_ESTATE"),
    ("PROD-TF-001", "REAL_ESTATE"),
    ("PROD-TF-002", "REAL_ESTATE"),
    ("PROD-CB-002", "REAL_ESTATE"),
    ("PROD-IB-001", "REAL_ESTATE"),
]

# 需求 → 产品匹配
NEED_PRODUCT_MATCHES = [
    ("NEED-WORKING-CAPITAL", "PROD-FIN-001", 0.95, "流动资金周转直接匹配"),
    ("NEED-WORKING-CAPITAL", "PROD-CM-003", 0.70, "透支可缓解短期流动性"),
    ("NEED-RECEIVABLE-FINANCING", "PROD-FIN-002", 0.90, "应收账款质押融资直接匹配"),
    ("NEED-RECEIVABLE-FINANCING", "PROD-SET-002", 0.75, "保理可转化应收账款"),
    ("NEED-SUPPLY-CHAIN-SETTLEMENT", "PROD-SET-001", 0.85, "结算账户基础服务"),
    ("NEED-SUPPLY-CHAIN-SETTLEMENT", "PROD-TF-001", 0.80, "银承支持供应链结算"),
    ("NEED-CASH-MANAGEMENT", "PROD-CM-001", 0.90, "现金池直接匹配集团资金归集"),
    ("NEED-CASH-MANAGEMENT", "PROD-CM-002", 0.80, "资金归集辅助"),
    ("NEED-CROSS-BORDER-SETTLEMENT", "PROD-CB-001", 0.95, "跨境人民币结算直接匹配"),
    ("NEED-CROSS-BORDER-SETTLEMENT", "PROD-TF-002", 0.60, "信用证支持跨境贸易"),
    ("NEED-TRADE-FINANCE", "PROD-TF-001", 0.85, "银承支持贸易融资"),
    ("NEED-TRADE-FINANCE", "PROD-TF-002", 0.80, "信用证支持贸易融资"),
    ("NEED-TRADE-FINANCE", "PROD-CB-001", 0.65, "跨境结算辅助"),
]

# 产品 → 产品前置
PREREQUISITES = [
    ("PROD-SET-002", "PROD-SET-001"),  # 国内保理前置：结算账户
    ("PROD-CM-001", "PROD-SET-001"),  # 现金池前置：结算账户
    ("PROD-CM-002", "PROD-SET-001"),  # 资金归集前置：结算账户
    ("PROD-CM-003", "PROD-SET-001"),  # 法人账户透支前置：结算账户
    ("PROD-TF-001", "PROD-SET-001"),  # 银承前置：结算账户
    ("PROD-TF-002", "PROD-SET-001"),  # 信用证前置：结算账户
    ("PROD-CB-001", "PROD-SET-001"),  # 跨境结算前置：结算账户
    ("PROD-CB-002", "PROD-SET-001"),  # 内保外贷前置：结算账户
    ("PROD-IB-001", "PROD-SET-001"),  # 并购贷款前置：结算账户
    ("PROD-FIN-002", "PROD-SET-001"),  # 应收账款质押融资前置：结算账户
    ("PROD-FIN-003", "PROD-SET-001"),  # 订单融资前置：结算账户
]

# 产品 → 产品配套
COMPLEMENTARY = [
    ("PROD-FIN-001", "PROD-SET-001"),
    ("PROD-FIN-002", "PROD-SET-002"),
    ("PROD-CM-001", "PROD-CM-002"),
    ("PROD-TF-001", "PROD-TF-002"),
    ("PROD-CB-001", "PROD-TF-002"),
    ("PROD-IB-001", "PROD-CB-002"),
]


def init_graph(db_path: str = DB_PATH) -> None:
    """初始化产品知识图谱。"""
    # 删除旧数据库
    import shutil
    if os.path.exists(db_path):
        if os.path.isdir(db_path):
            shutil.rmtree(db_path)
        else:
            os.remove(db_path)
        print(f"[INFO] 已删除旧数据库: {db_path}")

    db = kuzu.Database(db_path)
    conn = kuzu.Connection(db)

    # 创建节点表
    for ddl in NODE_DDL:
        conn.execute(ddl)
    print("[INFO] 节点表创建完成")

    # 创建关系表
    for ddl in REL_DDL:
        conn.execute(ddl)
    print("[INFO] 关系表创建完成")

    # 导入产品域
    for row in PRODUCT_FAMILIES:
        conn.execute(
            "CREATE (pf:ProductFamily {family_id: $fid, name: $name, name_en: $name_en, family_desc: $d})",
            {"fid": row[0], "name": row[1], "name_en": row[2], "d": row[3]},
        )
    print(f"[INFO] 导入 {len(PRODUCT_FAMILIES)} 个产品域")

    # 导入产品
    for row in PRODUCTS:
        conn.execute(
            "CREATE (p:Product {product_id: $pid, name: $name, family_id: $fid, status: $status, min_scale: $ms, min_rating: $mr, version: $ver})",
            {"pid": row[0], "name": row[1], "fid": row[2], "status": row[3], "ms": row[4], "mr": row[5], "ver": row[6]},
        )
    print(f"[INFO] 导入 {len(PRODUCTS)} 个产品")

    # 导入客户
    for row in CUSTOMERS:
        conn.execute(
            "CREATE (c:Customer {customer_id: $cid, name: $name, industry: $ind, scale: $scale, rating: $rating, tier: $tier, region: $region})",
            {"cid": row[0], "name": row[1], "ind": row[2], "scale": row[3], "rating": row[4], "tier": row[5], "region": row[6]},
        )
    print(f"[INFO] 导入 {len(CUSTOMERS)} 个客户")

    # 导入行业
    for row in INDUSTRIES:
        conn.execute(
            "CREATE (i:Industry {industry_id: $iid, name: $name, name_en: $name_en})",
            {"iid": row[0], "name": row[1], "name_en": row[2]},
        )
    print(f"[INFO] 导入 {len(INDUSTRIES)} 个行业")

    # 导入需求
    for row in NEEDS:
        conn.execute(
            "CREATE (n:Need {need_id: $nid, customer_id: $cid, need_type: $ntype, need_status: $nstatus, scenario: $scenario})",
            {"nid": row[0], "cid": row[1], "ntype": row[2], "nstatus": row[3], "scenario": row[4]},
        )
    print(f"[INFO] 导入 {len(NEEDS)} 个需求")

    # 导入关系：产品 → 产品域
    for pid, fid, *_ in PRODUCTS:
        conn.execute(
            "MATCH (p:Product {product_id: $pid}), (pf:ProductFamily {family_id: $fid}) CREATE (p)-[:BelongsToFamily]->(pf)",
            {"pid": pid, "fid": fid},
        )
    print(f"[INFO] 导入 {len(PRODUCTS)} 条 BelongsToFamily 关系")

    # 导入关系：客户 → 行业
    for cid, _, ind, *_ in CUSTOMERS:
        conn.execute(
            "MATCH (c:Customer {customer_id: $cid}), (i:Industry {industry_id: $iid}) CREATE (c)-[:CustomerInIndustry]->(i)",
            {"cid": cid, "iid": ind},
        )
    print(f"[INFO] 导入 {len(CUSTOMERS)} 条 CustomerInIndustry 关系")

    # 导入关系：客户 → 需求
    for nid, cid, *_ in NEEDS:
        conn.execute(
            "MATCH (c:Customer {customer_id: $cid}), (n:Need {need_id: $nid}) CREATE (c)-[:CustomerHasNeed]->(n)",
            {"cid": cid, "nid": nid},
        )
    print(f"[INFO] 导入 {len(NEEDS)} 条 CustomerHasNeed 关系")

    # 导入关系：产品 → 行业适用
    for pid, iid in APPLICABLE_INDUSTRIES:
        conn.execute(
            "MATCH (p:Product {product_id: $pid}), (i:Industry {industry_id: $iid}) CREATE (p)-[:ApplicableToIndustry]->(i)",
            {"pid": pid, "iid": iid},
        )
    print(f"[INFO] 导入 {len(APPLICABLE_INDUSTRIES)} 条 ApplicableToIndustry 关系")

    # 导入关系：产品 → 行业禁止
    for pid, iid in PROHIBITED_INDUSTRIES:
        conn.execute(
            "MATCH (p:Product {product_id: $pid}), (i:Industry {industry_id: $iid}) CREATE (p)-[:ProhibitedForIndustry]->(i)",
            {"pid": pid, "iid": iid},
        )
    print(f"[INFO] 导入 {len(PROHIBITED_INDUSTRIES)} 条 ProhibitedForIndustry 关系")

    # 导入关系：需求 → 产品匹配
    for nid, pid, score, reason in NEED_PRODUCT_MATCHES:
        conn.execute(
            "MATCH (n:Need {need_id: $nid}), (p:Product {product_id: $pid}) CREATE (n)-[:NeedMatchesProduct {match_score: $score, match_reason: $reason}]->(p)",
            {"nid": nid, "pid": pid, "score": score, "reason": reason},
        )
    print(f"[INFO] 导入 {len(NEED_PRODUCT_MATCHES)} 条 NeedMatchesProduct 关系")

    # 导入关系：产品 → 产品前置
    for from_pid, to_pid in PREREQUISITES:
        conn.execute(
            "MATCH (p1:Product {product_id: $from_pid}), (p2:Product {product_id: $to_pid}) CREATE (p1)-[:PrerequisiteOf]->(p2)",
            {"from_pid": from_pid, "to_pid": to_pid},
        )
    print(f"[INFO] 导入 {len(PREREQUISITES)} 条 PrerequisiteOf 关系")

    # 导入关系：产品 → 产品配套
    for pid1, pid2 in COMPLEMENTARY:
        conn.execute(
            "MATCH (p1:Product {product_id: $pid1}), (p2:Product {product_id: $pid2}) CREATE (p1)-[:ComplementaryWith]->(p2)",
            {"pid1": pid1, "pid2": pid2},
        )
    print(f"[INFO] 导入 {len(COMPLEMENTARY)} 条 ComplementaryWith 关系")

    # 验证
    result = conn.execute("MATCH (p:Product) RETURN count(p) AS cnt")
    cnt = result.get_next()[0]
    print(f"\n[DONE] 产品知识图谱初始化完成: {cnt} 个产品节点, 数据库路径: {db_path}")

    # 演示查询
    print("\n--- 演示查询：CUST-CORP-0001 的需求匹配产品 ---")
    result = conn.execute("""
        MATCH (c:Customer {customer_id: 'CUST-CORP-0001'})-[:CustomerHasNeed]->(n:Need)-[m:NeedMatchesProduct]->(p:Product)-[:BelongsToFamily]->(pf:ProductFamily)
        RETURN c.name, n.need_id, n.scenario, p.product_id, p.name, pf.name, m.match_score, m.match_reason
        ORDER BY m.match_score DESC
    """)
    while result.has_next():
        row = result.get_next()
        print(f"  {row[0]} | {row[1]} | {row[2]} | → {row[3]} {row[4]} ({row[5]}) | score={row[6]:.2f} | {row[7]}")


if __name__ == "__main__":
    init_graph()
