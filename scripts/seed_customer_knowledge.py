#!/usr/bin/env python3
"""DKWS v1.3 造数脚本：客户知识落库（本体 FS + 图谱 + 检索投影）+ CRM 主档投影。

客户：
- CUST-CORP-0001 华东精工装备集团有限公司（主联调户，战略层级）
- CUST-CORP-0002 华东新能源汽车有限公司（0001 的关键下游客户，演示上下游链）

规则（v1.3）：
- 客户 ID 同一字符串贯穿 DKWS 实体 / 图节点 / Skill 请求 / GITS customer.customer_id；
- 每个客户：7 条 KI 片段（document_id = customerId）+ 客户实体 + 供应链对手方/关系；
- 产出 CRM 主档夹具 gits-crm-customer-master.json（交付物 A，枚举/日期/金额内建校验）；
- 可选 upsert 到 GITS（交付物 B）：--gits-base → PUT {GITS_BASE}/api/v1/engagement/customer/{id}；
- 幂等：每次运行新 run_id，可重复执行。

用法：.venv/bin/python scripts/seed_customer_knowledge.py -w <demo_workspace> [--gits-base URL] [--api-key KEY]
"""
from __future__ import annotations

import argparse
import json
import re as _re
from pathlib import Path

from dkws.application.publish import Publisher
from dkws.application.projection import ProjectionBuilder
from dkws.application.review import ReviewService
from dkws.domain import hashing, timeutil
from dkws.infrastructure import markdown
from dkws.infrastructure.fs import WorkspaceWriter

DOMAIN = "customer"
SERVICE_ID = "customer_knowledge"
SOURCE = "SEED-CUST-20260822"

# ---------------------------------------------------------------- 客户定义

CUSTOMERS: list[dict] = [
    {
        "customerId": "CUST-CORP-0001",
        "crm": {
            "customerId": "CUST-CORP-0001",
            "customerName": "华东精工装备集团有限公司",
            "customerShortName": "华东精工集团",
            "unifiedSocialCreditCode": "91330000MA27DEMO",
            "establishedDate": "2005-03-15",
            "registeredCapitalCny": 500000000,
            "industry": "MANUFACTURING",
            "region": "浙江省杭州市",
            "enterpriseScale": "LARGE",
            "customerTier": "STRATEGIC",
            "relationshipSince": "2018-06-01",
            "rmId": "RM-ZW-001",
            "rmName": "张伟",
            "managingBranch": "杭州城西支行",
            "groupFlag": True,
            "listedStatus": "UNLISTED",
            "riskLevel": "MEDIUM",
            "mainProducts": ["精密加工", "智能装备", "自动化产线"],
            "coreTags": ["制造业", "出口导向", "技改需求"],
            "relationshipSummary": "战略客户，集团本部及子公司在我行开户（摘要与 KI-009 身份段一致，不含 KYC 缺口正文）。",
        },
        "segments": [
            {
                "ki": "KI-009", "title": "企业客户基本信息",
                "content": (
                    "华东精工装备集团有限公司（统一社会信用代码 91330000MA27DEMO，成立于 2005-03-15，"
                    "注册资本 5 亿元）为浙江省杭州市大型高端装备制造集团，战略客户层级，2018-06-01 起与我行建立合作，"
                    "管户客户经理 张伟（RM-ZW-001），管辖行杭州城西支行。集团本部及子公司在我行开立结算账户并办理综合授信，"
                    "主营精密加工、智能装备与自动化产线，出口导向，近期有技术改造与产线升级需求，风险等级中等。"
                    "实控人股权结构清晰，集团统一授信、统借统还。"),
            },
            {
                "ki": "KI-FRONT-001", "title": "公司供应链图谱",
                "content": (
                    "上游供应商（按年采购额）：①华鑫轴承材料集团，年采购 8,500 万元、占比 34%、趋势上升、月结 60 天；"
                    "②长三角精钢有限公司，年采购 6,200 万元、占比 25%、趋势持平、货到付款；"
                    "③杭州精密铸件厂，年采购 4,800 万元、占比 19%、趋势下降、月结 30 天。"
                    "下游客户（按年销售额）：①华东新能源汽车有限公司，年销售 1.6 亿元、占比 38%、趋势上升、账期 45 天；"
                    "②中远传动系统股份有限公司，年销售 9,800 万元、占比 23%、趋势持平、账期 30 天；"
                    "③恒力工程机械集团有限公司，年销售 7,600 万元、占比 18%、趋势上升、账期 60 天。"
                    "客户处于中游核心制造环节，上游原材料集中度 78%，下游大客户集中度 79%。"),
            },
            {
                "ki": "KI-FRONT-002", "title": "产业链八维研判",
                "content": (
                    "①产业链位置：中游精密加工与智能装备制造，承上启下；②需求景气：新能源与自动化产线需求上行，"
                    "在手订单覆盖 6 个月；③供给格局：上游钢材/轴承供给充裕，价格小幅上行；④竞争格局：细分赛道头部集中，"
                    "公司市占率约 12%；⑤政策环境：高端装备制造获专项扶持，技改补贴到位；⑥技术演进：数控化/柔性产线升级中；"
                    "⑦替代威胁：低端产品替代风险低，高端定制粘性高；⑧经营趋势：营收与毛利双升，现金流改善。"),
            },
            {
                "ki": "KI-FRONT-003", "title": "行内变动行为",
                "content": (
                    "近 12 个月行内变动：①结算流水月均 1.2 亿元，同比 +18%，主要来自华东新能源汽车回款；"
                    "②现有流贷 8,000 万元已提用 75%，出现提款节奏加快迹象；③6 月发生一笔 3,000 万元大额他行转入，"
                    "用途待核实；④集团关联子公司新开 2 个结算账户；⑤授信项下无逾期、无欠息记录。"),
            },
            {
                "ki": "KI-FRONT-004", "title": "事实承诺事项 / 沟通话术",
                "content": (
                    "近期沟通记录与承诺：①8 月拜访中财务总监口头承诺技改项目优先使用我行贷款；"
                    "②已递交供应链融资意向书，倾向以华东新能源汽车应收账款办理保理；"
                    "③行长会谈提出跨境结算与套期保值需求；④尚未签署任何正式承诺文件，以上均为意向层面。"),
            },
            {
                "ki": "KI-FRONT-005", "title": "KYC 信息缺口",
                "content": (
                    "KYC 缺口：①实控人境外架构与海外子公司股权未完全穿透；②集团关联方清单（尤其新设 2 家子公司）"
                    "尚未在我行系统完整登记；③3,000 万元大额他行转入的资金用途与贸易背景待核实；"
                    "④未提供最新一期经审计财报（仅提供内部报表）。"),
            },
            {
                "ki": "KI-FRONT-006", "title": "产品候选组合",
                "content": (
                    "产品候选组合：①供应链金融（应收账款保理 / e信，以华东新能源汽车为链主）；②技术改造贷款"
                    "（匹配技改补贴与设备更新周期，授信 5,000 万-1 亿）；③票据池与票据置换；④跨境结算与套期保值"
                    "（远期结售汇）；⑤流动资金贷款增额续贷（匹配 3,000 万他行转入的归集）。匹配理由：集团战略层级、"
                    "订单充足、结算归行率提升空间大。"),
            },
        ],
        "suppliers": [  # (eid, name, annual_amount, share, trend, settlement)
            ("SUP-HD001", "华鑫轴承材料集团", 85000000, 0.34, "up", "月结 60 天"),
            ("SUP-HD002", "长三角精钢有限公司", 62000000, 0.25, "flat", "货到付款"),
            ("SUP-HD003", "杭州精密铸件厂", 48000000, 0.19, "down", "月结 30 天"),
        ],
        "customers": [  # 下游（CUST-CORP-0002 为独立客户，其余为纯对手方）
            ("CUST-CORP-0002", "华东新能源汽车有限公司", 160000000, 0.38, "up", "账期 45 天"),
            ("CUS-HD002", "中远传动系统股份有限公司", 98000000, 0.23, "flat", "账期 30 天"),
            ("CUS-HD003", "恒力工程机械集团有限公司", 76000000, 0.18, "up", "账期 60 天"),
        ],
    },
    {
        "customerId": "CUST-CORP-0002",
        "crm": {
            "customerId": "CUST-CORP-0002",
            "customerName": "华东新能源汽车有限公司",
            "customerShortName": "华东新能源",
            "unifiedSocialCreditCode": "91330100MA28NEV01",
            "establishedDate": "2010-06-18",
            "registeredCapitalCny": 200000000,
            "industry": "MANUFACTURING",
            "region": "浙江省嘉兴市",
            "enterpriseScale": "LARGE",
            "customerTier": "KEY",
            "relationshipSince": "2019-03-12",
            "rmId": "RM-ZW-002",
            "rmName": "李娜",
            "managingBranch": "嘉兴高新支行",
            "groupFlag": False,
            "listedStatus": "UNLISTED",
            "riskLevel": "MEDIUM",
            "mainProducts": ["新能源汽车整车", "动力总成"],
            "coreTags": ["新能源", "整车制造", "出口"],
            "relationshipSummary": "重点客户，华东精工集团下游核心客户（摘要与 KI-009 身份段一致，不含 KYC 缺口正文）。",
        },
        "segments": [
            {
                "ki": "KI-009", "title": "企业客户基本信息",
                "content": (
                    "华东新能源汽车有限公司（统一社会信用代码 91330100MA28NEV01，成立于 2010-06-18，"
                    "注册资本 2 亿元）为浙江省嘉兴市新能源整车制造企业，重点客户层级，2019-03-12 起与我行建立合作，"
                    "管户客户经理 李娜（RM-ZW-002），管辖行嘉兴高新支行。主营新能源汽车整车与动力总成，出口为主，"
                    "为华东精工装备集团有限公司（CUST-CORP-0001）关键下游客户，风险等级中等。"),
            },
            {
                "ki": "KI-FRONT-001", "title": "公司供应链图谱",
                "content": (
                    "上游供应商（按年采购额）：①华东精工装备集团有限公司，年采购 1.6 亿元、占比 38%、趋势上升、账期 45 天；"
                    "②赣江动力电池有限公司，年采购 1.1 亿元、占比 26%、趋势上升、货到付款；"
                    "③湘湖电机控制器有限公司，年采购 9,000 万元、占比 21%、趋势持平、月结 30 天。"
                    "下游客户（按年销售额）：①华南新能源整车厂A，年销售 2.2 亿元、占比 45%、趋势上升、账期 30 天；"
                    "②华北新能源整车厂B，年销售 1.3 亿元、占比 27%、趋势持平、账期 30 天；"
                    "③西部新能源整车厂C，年销售 8,000 万元、占比 16%、趋势上升、账期 60 天。"
                    "客户处于下游整车制造环节，上游供应商集中度 85%，下游大客户集中度 88%。"),
            },
            {
                "ki": "KI-FRONT-002", "title": "产业链八维研判",
                "content": (
                    "①产业链位置：下游整车制造与动力总成集成；②需求景气：新能源乘用车渗透率持续上行，出口订单旺盛；"
                    "③供给格局：电池/电驱供给充裕，价格竞争加剧；④竞争格局：二三线品牌加速出清，公司聚焦出口细分市场；"
                    "⑤政策环境：购置税减免延续、出口退税支持；⑥技术演进：800V 平台与智能座舱升级中；"
                    "⑦替代威胁：传统燃油车替代风险低，但竞品价格战构成压力；⑧经营趋势：销量与毛利改善，研发投入加大。"),
            },
            {
                "ki": "KI-FRONT-003", "title": "行内变动行为",
                "content": (
                    "近 12 个月行内变动：①结算流水月均 1.8 亿元，同比 +35%，主要来自出口收汇；"
                    "②新增流贷 5,000 万元，已提用 60%；③Q2 大额购汇 4,000 万元用于进口电芯，频率上升；"
                    "④与华东精工（CUST-CORP-0001）的应收账期由 60 天缩短至 45 天；⑤无逾期、无欠息。"),
            },
            {
                "ki": "KI-FRONT-004", "title": "事实承诺事项 / 沟通话术",
                "content": (
                    "近期沟通记录与承诺：①8 月会谈承诺出口收汇优先归集我行；②申请票据池额度 3,000 万元用于支付电芯采购；"
                    "③意向办理跨境套保（远期结汇）；④未签署正式承诺文件，均为意向层面。"),
            },
            {
                "ki": "KI-FRONT-005", "title": "KYC 信息缺口",
                "content": (
                    "KYC 缺口：①境外销售主体股权结构未穿透；②电芯进口贸易背景材料待补（大额购汇 4,000 万元）；"
                    "③实际控制人个人征信查询授权未签署；④未提供最新经审计年报。"),
            },
            {
                "ki": "KI-FRONT-006", "title": "产品候选组合",
                "content": (
                    "产品候选组合：①供应链金融（以华东精工为核心企业的反向保理）；②票据池与票据置换（电芯采购付款）；"
                    "③跨境结算与套期保值（远期结汇，匹配出口收汇）；④流动资金贷款增额；⑤并购贷（若推进上游电芯自研）。"
                    "匹配理由：出口为主、结算归行率提升空间大、供应链闭环（上游华东精工）。"),
            },
        ],
        "suppliers": [  # 上游（CUST-CORP-0001 为独立客户，其余为纯对手方）
            ("CUST-CORP-0001", "华东精工装备集团有限公司", 160000000, 0.38, "up", "账期 45 天"),
            ("SUP-NE001", "赣江动力电池有限公司", 110000000, 0.26, "up", "货到付款"),
            ("SUP-NE002", "湘湖电机控制器有限公司", 90000000, 0.21, "flat", "月结 30 天"),
        ],
        "customers": [
            ("CUS-NE001", "华南新能源整车厂A", 220000000, 0.45, "up", "账期 30 天"),
            ("CUS-NE002", "华北新能源整车厂B", 130000000, 0.27, "flat", "账期 30 天"),
            ("CUS-NE003", "西部新能源整车厂C", 80000000, 0.16, "up", "账期 60 天"),
        ],
    },
]

CUSTOMER_IDS = [c["customerId"] for c in CUSTOMERS]

# CRM 主档契约约束（交付物 A 字段枚举/格式；写中文会导致 GITS 反序列化失败）
CRM_ENUMS = {
    "industry": {"MANUFACTURING", "FINANCE", "TECHNOLOGY", "REAL_ESTATE", "ENERGY",
                 "HEALTHCARE", "AGRICULTURE", "LOGISTICS", "RETAIL", "OTHER"},
    "enterpriseScale": {"LARGE", "MEDIUM", "SMALL", "MICRO"},
    "customerTier": {"STRATEGIC", "KEY", "GROWTH", "GENERAL"},
    "listedStatus": {"LISTED", "UNLISTED", "DELISTED"},
    "riskLevel": {"HIGH", "MEDIUM", "LOW"},
}


def _validate_crm_master(c: dict) -> None:
    """交付物 A 字段约束（枚举/日期/金额/数组），违规即失败，防止坏夹具进 GITS。"""
    for k, allowed in CRM_ENUMS.items():
        if c.get(k) not in allowed:
            raise ValueError(f"CRM 字段 {k}={c.get(k)!r} 不在枚举 {sorted(allowed)} 内")
    for k in ("establishedDate", "relationshipSince"):
        if not _re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(c.get(k) or "")):
            raise ValueError(f"CRM 日期字段 {k} 必须为 YYYY-MM-DD，实际 {c.get(k)!r}")
    if not isinstance(c.get("registeredCapitalCny"), int):
        raise ValueError(f"CRM registeredCapitalCny 必须为人民币元整数，实际 {c.get('registeredCapitalCny')!r}")
    for k in ("mainProducts", "coreTags"):
        v = c.get(k)
        if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
            raise ValueError(f"CRM 字段 {k} 必须为字符串数组")


def _crm_fixture() -> dict:
    for c in CUSTOMERS:
        _validate_crm_master(c["crm"])
    return {"customers": [c["crm"] for c in CUSTOMERS]}


# ------------------------------------------------------------------ 契约 md

def _seg_md(customer_id: str, ki: str, title: str, content: str, seq: int) -> str:
    sid = f"SEG-{customer_id}-{ki.replace('-', '')}"
    fm = {
        "schema": "document_segment/v1",
        "segment_id": sid,
        "document_id": customer_id,
        "segment_type": "PARAGRAPH",
        "heading_path": [f"{ki} {title}"],
        "sequence": seq,
        "content_sha256": hashing.md_semantic_sha256(content),
        "chunk_policy_version": "ki-v1",
        "status": "ACTIVE",
        "version": "1.0",
    }
    body = f"# {ki} {title}\n\n## 原文\n\n{content}\n"
    return markdown.render_contract_md(fm, body)


def _entity_md(eid: str, name: str, etype: str, layer: str,
               extra: dict | None = None, source_segs: list[str] | None = None) -> str:
    fm = {
        "schema": "entity/v1",
        "entity_id": eid,
        "entity_type": etype,
        "name": name,
        "aliases": [],
        "description": f"客户知识库实体（{layer}）",
        "domain": DOMAIN,
        "source_ids": source_segs or [],
        "confidence": 0.9,
        "extraction": {"extractor": "seed_customer_knowledge", "model_id": "deterministic",
                       "model_version": "1.0.0", "prompt_template_version": "none"},
        "validation_status": "CANDIDATE",
        "status": "ACTIVE",
        "version": "1.0",
    }
    if extra:
        fm.update(extra)
    body = (f"# {name}\n\n## 定义\n\n客户知识库种子实体（{layer}），源 {SOURCE}。\n\n"
            f"## 业务说明\n\n{layer}。\n\n## 来源证据\n\n{SOURCE}。\n\n## 审核说明\n\n待审核。\n")
    return markdown.render_contract_md(fm, body)


def _relation_md(rid: str, src: str, tgt: str, source_segs: list[str] | None = None) -> str:
    fm = {
        "schema": "relation/v1",
        "relation_id": rid,
        "source_id": src,
        "relation_type": "SUPPLIES",
        "target_id": tgt,
        "direction": "DIRECTED",
        "source_ids": source_segs or [],
        "confidence": 0.9,
        "validation_status": "CANDIDATE",
        "status": "ACTIVE",
        "version": "1.0",
    }
    body = (f"# {src} 供应 {tgt}\n\n## 语义\n\n供应链供应关系（种子数据）。\n\n"
            f"## 来源证据\n\n{SOURCE}。\n\n## 审核说明\n\n待审核。\n")
    return markdown.render_contract_md(fm, body)


def _upsert_to_gits(customers: list[dict], gits_base: str, api_key: str | None) -> list[dict]:
    """交付物 B：PUT {GITS_BASE}/api/v1/engagement/customer/{customerId} upsert。

    幂等（PUT upsert）；任一失败仅告警不阻断造数（GITS 未发布/不可达时造数仍完成）。
    """
    import urllib.request
    import urllib.error

    results = []
    for c in customers:
        cid = c.get("customerId", "")
        url = f"{gits_base.rstrip('/')}/api/v1/engagement/customer/{cid}"
        req = urllib.request.Request(
            url, data=json.dumps(c, ensure_ascii=False).encode("utf-8"),
            method="PUT",
            headers={"Content-Type": "application/json",
                     **({"X-API-KEY": api_key} if api_key else {})})
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                results.append({"customerId": cid, "status": resp.status, "ok": True})
                print(f"  [upsert] PUT {url} → {resp.status}")
        except urllib.error.HTTPError as e:
            results.append({"customerId": cid, "status": e.code, "ok": False,
                            "detail": str(e.read(200)[:200])})
            print(f"  [upsert] PUT {url} → {e.code}（告警，不阻断造数）")
        except Exception as e:
            results.append({"customerId": cid, "status": None, "ok": False, "detail": str(e)[:200]})
            print(f"  [upsert] PUT {url} 不可达（告警，不阻断造数）：{e}")
    return results


def _run_seed(ws: Path) -> None:
    """执行落库主流程（候选 → 审核 → 发布 → 投影）。"""
    run_id = f"RUN-SEED-CUST-{timeutil.ts_utc()[:19].replace('-', '').replace('T', '').replace(':', '')}"
    writer = WorkspaceWriter(ws)
    seg_base = f"02_work/{DOMAIN}/run={run_id}/segments"
    cand_base = f"02_work/{DOMAIN}/run={run_id}/candidates"

    # 客户实体 ID 集合（独立客户同时也是他人对手方时，实体只写一次、字段合并）
    seeded_ids = {c["customerId"] for c in CUSTOMERS}
    # eid -> 作为他客户对手方时的金额字段（合并进客户实体）
    counterparty_x: dict[str, dict] = {}
    for cust in CUSTOMERS:
        for eid, _name, amt, share, trend, settlement in cust["suppliers"] + cust["customers"]:
            counterparty_x.setdefault(eid, {
                "x_annual_amount": amt, "x_share": share, "x_trend": trend,
                "x_settlement": settlement, "x_data_source": "T-CORE-001",
            })

    refs: list[str] = []
    entity_rels: dict[str, str] = {}
    relation_seen: set[tuple[str, str]] = set()  # (src, tgt) 去重（双方各自建模可能重复）

    def _add_relation(src: str, tgt: str, rid_prefix: str, idx: int, ki1: str) -> None:
        nonlocal refs
        key = (src, tgt)
        if key in relation_seen:
            return
        relation_seen.add(key)
        rid = f"REL-{rid_prefix}-{idx:02d}"
        rel = f"{cand_base}/relations/{rid}.md"
        writer.write_text(rel, _relation_md(rid, src, tgt, source_segs=[ki1]))
        refs.append(rel)

    for cust in CUSTOMERS:
        cid = cust["customerId"]
        cname = cust["crm"]["customerName"]
        seg_ids = [f"SEG-{cid}-{s['ki'].replace('-', '')}" for s in cust["segments"]]
        print(f"== 客户 {cid} {cname} ==")

        # 1) KI 片段（经实体 source_ids 引用，随发布闭包进入核心层）
        for i, s in enumerate(cust["segments"], start=1):
            rel = f"{seg_base}/{cid}/SEG-{cid}-{s['ki'].replace('-', '')}.md"
            writer.write_text(rel, _seg_md(cid, s["ki"], s["title"], s["content"], i))
        print(f"  KI 片段 {len(cust['segments'])} 条")

        # 2) 客户实体（CRM 身份字段 + 作为对手方的金额字段，合并为 x_*；只写一次）
        cm = cust["crm"]
        cust_fm = {
            "x_credit_code": cm["unifiedSocialCreditCode"],
            "x_established_date": cm["establishedDate"],
            "x_registered_capital_cny": cm["registeredCapitalCny"],
            "x_industry": cm["industry"],
            "x_region": cm["region"],
            "x_enterprise_scale": cm["enterpriseScale"],
            "x_customer_tier": cm["customerTier"],
            "x_relationship_since": cm["relationshipSince"],
            "x_rm_id": cm["rmId"],
            "x_rm_name": cm["rmName"],
            "x_managing_branch": cm["managingBranch"],
            "x_group_flag": cm["groupFlag"],
            "x_listed_status": cm["listedStatus"],
            "x_risk_level": cm["riskLevel"],
            "x_main_products": cm["mainProducts"],
            "x_core_tags": cm["coreTags"],
            "x_relationship_summary": cm["relationshipSummary"],
        }
        cust_fm.update(counterparty_x.get(cid, {}))
        rel = f"{cand_base}/entities/{cid}.md"
        if cid not in entity_rels:
            writer.write_text(rel, _entity_md(cid, cname, "CUSTOMER", "enterprise",
                                              extra=cust_fm, source_segs=seg_ids))
            entity_rels[cid] = rel
            refs.append(rel)
        else:
            # 已作为对手方写过占位实体 → 覆写为完整客户实体（refs 已含该路径，不重复）
            writer.write_text(rel, _entity_md(cid, cname, "CUSTOMER", "enterprise",
                                              extra=cust_fm, source_segs=seg_ids))

        # 3) 供应链对手方实体 + 关系（上游：对手方→客户；下游：客户→对手方）
        ki1 = seg_ids[1]
        rid = 0
        for eid, name, amt, share, trend, settlement in cust["suppliers"]:
            if eid not in entity_rels and eid not in seeded_ids:
                rel = f"{cand_base}/entities/{eid}.md"
                writer.write_text(rel, _entity_md(
                    eid, name, "SUPPLIER", "supplier",
                    extra={"x_annual_amount": amt, "x_share": share, "x_trend": trend,
                           "x_settlement": settlement, "x_data_source": "T-CORE-001"},
                    source_segs=[ki1]))
                entity_rels[eid] = rel
                refs.append(rel)
            rid += 1
            _add_relation(eid, cid, f"{cid}-SUP", rid, ki1)
        for eid, name, amt, share, trend, settlement in cust["customers"]:
            if eid not in entity_rels and eid not in seeded_ids:
                rel = f"{cand_base}/entities/{eid}.md"
                writer.write_text(rel, _entity_md(
                    eid, name, "CUSTOMER", "customer",
                    extra={"x_annual_amount": amt, "x_share": share, "x_trend": trend,
                           "x_settlement": settlement, "x_data_source": "T-CORE-001"},
                    source_segs=[ki1]))
                entity_rels[eid] = rel
                refs.append(rel)
            rid += 1
            _add_relation(cid, eid, f"{cid}-DIST", rid - len(cust['suppliers']), ki1)
        print(f"  对手方 {len(cust['suppliers']) + len(cust['customers'])} 个，关系同数")

    ReviewService(ws).review(DOMAIN, run_id=run_id, object_refs=refs,
                             decision="APPROVE", reason="客户知识种子数据审核", decided_by="svc_seed")
    print("  审核 APPROVE 完成")
    pub = Publisher(ws).publish(DOMAIN, run_id=run_id)
    print(f"  发布 version={pub.release_version}（资产 {pub.asset_count}）")
    prj = ProjectionBuilder(ws).build(DOMAIN, service_id=SERVICE_ID)
    print(f"  投影 {SERVICE_ID} version={prj.projection_version}")


def seed_customer_knowledge(ws: Path, *, quiet: bool = False) -> dict:
    """可复用造数入口（脚本与测试共用）：全部客户知识落库 + CRM 夹具。

    返回 {crm_path, customers, customer_ids}。
    """
    import io
    import contextlib

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        _run_seed(ws)
    crm = _crm_fixture()
    out = Path(__file__).resolve().parents[1] / "examples" / "output" / "gits-crm-customer-master.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(crm, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "crm_path": str(out),
        "customers": crm["customers"],
        "customer_ids": [c["customerId"] for c in crm["customers"]],
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace", "-w", required=True)
    ap.add_argument("--gits-base", default=None,
                    help="GITS 基址（如 http://127.0.0.1:8080）。提供则执行交付物 B upsert："
                         "PUT {GITS_BASE}/api/v1/engagement/customer/{customerId}")
    ap.add_argument("--api-key", default=None, help="GITS X-API-KEY（环境变量 GITS_API_KEY 亦可）")
    args = ap.parse_args()
    ws = Path(args.workspace).resolve()
    info = seed_customer_knowledge(ws)
    print(f"  CRM 主档投影: {info['crm_path']}")
    gits_base = args.gits_base or __import__("os").environ.get("GITS_BASE")
    api_key = args.api_key or __import__("os").environ.get("GITS_API_KEY")
    if gits_base:
        results = _upsert_to_gits(info["customers"], gits_base, api_key)
        ok_count = sum(1 for r in results if r["ok"])
        print(f"  [upsert] 完成 {ok_count}/{len(results)}（幂等，可重复执行）")
    else:
        print("  [upsert] 未配置 --gits-base / GITS_BASE，仅提交交付物 A（夹具），未调用 GITS")
    print(f"  [customerId 变更清单] 本次新增/更新: {', '.join(info['customer_ids'])}")
    from dkws.infrastructure.graph.kuzu_builder import KuzuGraphBuilder
    b = KuzuGraphBuilder(ws, service_id=SERVICE_ID)
    fp = b.fingerprint_of(b._active_version())
    print(f"  Kùzu 图谱: {fp['nodes']} 节点 / {fp['edges']} 边（指纹 {fp['hash'][:12]}…）")


if __name__ == "__main__":
    main()
