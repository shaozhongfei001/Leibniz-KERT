#!/usr/bin/env python3
"""产品卡「数据层」补强：把 01_raw 权威源中的条款回填到产品卡 §1/§4/§7/§8。

## 背景（为什么需要这一步）

产品中心 8 章由 `03_core/**/product-cards/PROD-*.md` **确定性派生**（见 l40 生成器）。
实测 13 张卡存在同类缺陷：

- §7 流程被压缩（现金池源材料 7 步，卡片只剩 5 步）；
- §8 只有一句「按行内收费标准执行（待核定）」⇒ 投影 `pricingItems: []`（Owner 裁定 O-2
  时无内容可出），前端「价格与协议」整章空白；
- §1/§4 未登记制度条款，导致「产品目的 / 适用主体」只能依赖检索派生。

## 纪律（**不编造**）

1. 只做**逐字摘录 + 重组**：每一条写入卡片的内容都来自 `01_raw/_authoritative/SRC-*.md`
   的条款原文，并附 `（依据 <source_id> 第N条）`；
2. 不新增任何事实、不改写数字、不引入外部知识；源里没有的（如具体费率）保持「待核定」；
3. 幂等：写入块用 `<!-- enrich:<SRC> begin/end -->` 包裹，重跑先删旧块再写入；
4. 条款按关键词归类（定价/流程/准入/目的），归类失败即跳过并打印告警，不猜。

用法：
    python3 tools/enrich_cards_from_sources.py --dry-run   # 只看将写入的内容
    python3 tools/enrich_cards_from_sources.py            # 实际写入
    python3 tools/check_enrich_consistency.py             # **必跑**：回填—声明一致性门禁

## 门禁

回填后必须通过 `tools/check_enrich_consistency.py`（D1 源映射错配 / D2 非逐字引用 /
D3 主张类型越界 / D4 评级门槛无出处）。它会检出「源声明 `allowed_claim_types` 与回填小节不符」
与「卡片门槛在源材料中找不到」——两类历史漂移。新增源或改映射时同步更新 `SRC_MAP`。
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
CORE = BASE / "03_core"
SRC_DIR = BASE / "01_raw" / "_authoritative"

# 产品 → 权威源（**显式登记，不按编号盲配**）
# ⚠ 编号并不对齐：SRC-CM-002 是「法人账户透支业务操作规程」（对应 PROD-CM-003），
#   SRC-CM-003 是「集团客户资金集中管理风险政策」（对应资金归集 PROD-CM-002）。
SRC_MAP = {
    "PROD-CM-001": "SRC-CM-001",    # 现金池 ← 现金管理业务管理办法
    "PROD-CM-002": "SRC-CM-003",    # 资金归集 ← 集团客户资金集中管理风险政策
    "PROD-CM-003": "SRC-CM-002",    # 法人账户透支 ← 法人账户透支业务操作规程
    "PROD-CB-001": "SRC-CB-001",    # 跨境人民币结算
    "PROD-CB-002": "SRC-CB-002",    # 内保外贷
    "PROD-FIN-001": "SRC-FIN-001",  # 流动资金贷款
    "PROD-FIN-002": "SRC-FIN-003",  # 应收账款质押融资 ← 供应链金融（第二条 应收账款类）
    "PROD-FIN-003": "SRC-FIN-003",  # 订单融资 ← 供应链金融（第二条 订单类）
    "PROD-IB-001": "SRC-IB-001",    # 并购贷款
    "PROD-SET-001": "SRC-SET-001",  # 单位结算账户
    "PROD-SET-002": "SRC-SET-002",  # 国内保理
    "PROD-TF-001": "SRC-TF-001",    # 银行承兑汇票
    "PROD-TF-002": "SRC-TF-002",    # 国内信用证
}

# 一源多卡时，用产品关键词限定条款范围（供应链金融源同时覆盖应收账款类与订单类）
SRC_FOCUS = {
    "PROD-FIN-002": "应收账款",
    "PROD-FIN-003": "订单",
}

# 适用范围正/负向判据：`本产品适用于…`（正向）与 `本产品不适用于…`（负向）不可混判
POS_FIT_RE = re.compile(r"(?<!不)本产品适用于")
NEG_FIT_RE = re.compile(r"本产品不适用于|客户不适用本产品|应适用结算类产品")
CLAUSE_RE = re.compile(r"\*\*第([一二三四五六七八九十百〇零0-9]+)条\*\*\s*(.+?)(?=\n\*\*第|\n##|\Z)", re.S)
SECTION_RE = re.compile(r"^## (\d+)\. (.+)$", re.M)


def clauses_of(src_text: str) -> list[tuple[str, str]]:
    out = []
    for m in CLAUSE_RE.finditer(src_text):
        body = re.sub(r"\s*\n\s*", "", m.group(2)).strip()
        out.append((f"第{m.group(1)}条", body))
    return out


def classify(body: str) -> set[str]:
    """按**条款语义**归类。刻意收紧：总则/原则类条款不得混入准入或定价。"""
    tags = set()
    # 总则/附则条款（立法目的、解释权）不得进入任何业务小节
    if any(k in body for k in ("制定本办法", "本办法由", "本办法自", "为规范")):
        return tags
    # 定价：必须出现具体计费/利率概念；仅含"定价"二字的原则性表述不算
    # 台账登记/登记要素类条款常把「保证金比例」列为登记项，属流程文书要求，不是定价条款
    if any(k in body for k in ("台账登记", "登记要素")):
        pass
    elif any(k in body for k in ("服务费", "收费", "费率", "利率", "保证金比例")):
        tags.add("price")
    elif "定价" in body and "原则" not in body:
        tags.add("price")
    # 流程：流程/渠道/受理审查环节
    if any(k in body for k in ("流程为", "办理流程", "渠道", "受理环节", "审查环节")):
        tags.add("process")
    # 准入：仅取真正的准入/受理条件表述
    if any(k in body for k in ("应当同时满足", "应同时满足", "不得受理", "准入",
                               "评级不低于", "双签", "不得办理", "受理前提",
                               "成员单位不少于")):
        tags.add("access")
    # 排除：条款明示不适用/应改用其它产品
    if NEG_FIT_RE.search(body):
        tags.add("exclude")
    # 适用范围：**正向**适用主体/分层（`本产品不适用于…` 不得命中；混写条款两个标签并存，逐字不改写）
    if POS_FIT_RE.search(body):
        tags.add("fit")
    # 目的/定义
    if any(k in body for k in ("本办法所称", "业务范围包括", "是指卖方", "是指本行")):
        tags.add("purpose")
    return tags


def split_mixed(cid: str, body: str) -> list[tuple[str, str]]:
    """「正向适用 + 不适用」混写的条款按句切分（**逐字**，不跨句改写），
    使 §2 只收正向适用、§5 只收排除，避免同一条款原样出现在两处。"""
    if POS_FIT_RE.search(body) and NEG_FIT_RE.search(body):
        parts = [x.strip() for x in re.split(r"(?<=。)", body) if x.strip()]
        return [(cid, x) for x in parts]
    return [(cid, body)]


def split_sections(text: str) -> list[tuple[str, str]]:
    """返回 [(section_key, section_text)]，section_key 形如 '1'。"""
    marks = [(m.start(), m.group(1), m.group(2)) for m in SECTION_RE.finditer(text)]
    out = []
    for i, (pos, num, _title) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else len(text)
        out.append((num, text[pos:end]))
    return out


def strip_blocks(text: str) -> str:
    text = re.sub(r"\n?<!-- enrich:.*?begin -->.*?<!-- enrich:.*?end -->\n?", "", text, flags=re.S)
    # 删除块后若残留连续空行，收敛为一个空行（卡片小节间统一空一行）
    return re.sub(r"\n{3,}", "\n\n", text)


def ensure_trailing_newline(block: str) -> str:
    return block if block.endswith("\n") else block + "\n"


def build_block(src_id: str, picked: list[tuple[str, str]], label: str) -> str:
    """一条款一**顶层**项目符号：下游 l40 只解析顶层 `- `，嵌套会被当成散文丢弃。"""
    lines = [f"<!-- enrich:{src_id} begin -->"]
    for cid, body in picked:
        lines.append(f"- {label}（依据 {src_id} {cid}）：{body}")
    lines.append(f"<!-- enrich:{src_id} end -->")
    return "\n".join(lines) + "\n"


def process_card(card_path: Path, dry: bool) -> list[str]:
    pid = card_path.stem
    src_id = SRC_MAP.get(pid)
    if not src_id:
        return [f"[SKIP] {pid}: 未在 SRC_MAP 登记权威源"]
    src_path = SRC_DIR / f"{src_id}.DEMO.md"
    if not src_path.is_file():
        return [f"[SKIP] {pid}: 缺少源 {src_path.name}"]
    cs = clauses_of(src_path.read_text(encoding="utf-8"))
    if not cs:
        return [f"[SKIP] {pid}: 源文件未解析到条款"]

    focus = SRC_FOCUS.get(pid)
    if focus:
        cs = [(c, b) for c, b in cs if focus in b]
        if not cs:
            return [f"[SKIP] {pid}: 源 {src_id} 无「{focus}」相关条款"]
    units = [u for cid, body in cs for u in split_mixed(cid, body)]
    purpose = [(c, b) for c, b in units if "purpose" in classify(b)][:2]
    fit = [(c, b) for c, b in units if "fit" in classify(b)][:2]
    exclude = [(c, b) for c, b in units if "exclude" in classify(b)][:3]
    # 上限 5：FIN-001 有 5 条真准入条款（第四条主体/第五条条件/第六条档位/第七条不得受理/第二十条准入线），
    # 上限 4 会把「准入线」条款截掉，导致卡片门槛失去出处（check_enrich_consistency D4 会报）。
    access = [(c, b) for c, b in units if "access" in classify(b)][:5]
    price = [(c, b) for c, b in units if "price" in classify(b)][:3]
    flow_cl = next(((c, b) for c, b in cs if "流程为" in b), None)
    chan_cl = next(((c, b) for c, b in cs if "渠道" in b and "流程" not in b), None)

    original_text = card_path.read_text(encoding="utf-8")
    text = strip_blocks(original_text)
    sections = split_sections(text)
    by_num = {n: t for n, t in sections}
    msgs = []

    # §1 产品目的依据
    if purpose and "1" in by_num:
        blk = build_block(src_id, purpose, "制度依据")
        sec = by_num["1"].rstrip("\n") + "\n\n" + blk + "\n"
        text = text.replace(by_num["1"], sec, 1)
        msgs.append(f"{pid} §1 追加 {len(purpose)} 条")

    # §2 适用范围依据（正向适用主体/分层）
    if fit and "2" in by_num:
        blk = build_block(src_id, fit, "适用范围依据")
        sec = by_num["2"].rstrip("\n") + "\n\n" + blk + "\n"
        text = text.replace(by_num["2"], sec, 1)
        msgs.append(f"{pid} §2 追加 {len(fit)} 条")

    # §5 排除依据（源条款明示不适用/应改用其它产品）
    if exclude and "5" in by_num:
        blk = build_block(src_id, exclude, "排除依据")
        sec = by_num["5"].rstrip("\n") + "\n\n" + blk + "\n"
        text = text.replace(by_num["5"], sec, 1)
        msgs.append(f"{pid} §5 追加 {len(exclude)} 条")

    # §4 准入依据
    if access and "4" in by_num:
        blk = build_block(src_id, access, "准入依据")
        sec = by_num["4"].rstrip("\n") + "\n\n" + blk + "\n"
        text = text.replace(by_num["4"], sec, 1)
        msgs.append(f"{pid} §4 追加 {len(access)} 条")

    # §7 流程：用源条款替换卡片压缩后的流程步骤，保留材料行
    if "7" in by_num:
        sec = by_num["7"]
        new_sec = sec
        if flow_cl:
            cid, body = flow_cl
            m = re.search(r"流程为[：:]\s*(.+?)。?$", body)
            if m:
                steps = re.sub(r"、", " → ", m.group(1).strip().rstrip("。"))
                new_sec = re.sub(r"^- 流程：.*$", f"- 流程：{steps}（依据 {src_id} {cid}）", new_sec, count=1, flags=re.M)
        if chan_cl:
            cid, body = chan_cl
            # 幂等：渠道行不在 enrich 块内，先清掉历史写入的同类行，避免重跑累积
            new_sec = re.sub(
                rf"^- 办理渠道：.*（依据 {re.escape(src_id)} 第.+?条）\n?",
                "",
                new_sec,
                flags=re.M,
            )
            new_sec = new_sec.rstrip("\n") + f"\n- 办理渠道：{body}（依据 {src_id} {cid}）\n\n"
        if new_sec != sec:
            text = text.replace(sec, new_sec, 1)
            msgs.append(f"{pid} §7 流程按源条款重建")

    # §8 定价政策（解除 O-2：呈现政策条款，不编费率）
    # 卡片原有价格行**逐字保留**（如「承兑手续费按票面金额的 0.5‰（待核定）」是卡片自有事实，
    # 不得因回填而丢弃），源条款作为「定价政策」块附在其后；不额外生成任何费率数字。
    if "8" in by_num and price:
        blk = build_block(src_id, price, "定价政策")
        sec = by_num["8"]
        head, _, rest = sec.partition("\n")
        keep = [ln.rstrip() for ln in rest.split("\n")
                if ln.strip() and not ln.lstrip().startswith("<!--")]
        new_sec = head + "\n\n" + "".join(f"{ln}\n" for ln in keep) + ("\n" if keep else "") + blk + "\n"
        text = text.replace(sec, new_sec, 1)
        msgs.append(f"{pid} §8 追加定价政策 {len(price)} 条")

    if text == original_text:
        return [f"[NOOP] {pid}: 已是最新"]
    if dry:
        return msgs
    card_path.write_text(text, encoding="utf-8")
    return msgs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--only", default="", help="只处理指定产品，逗号分隔")
    args = ap.parse_args()
    only = {x.strip() for x in args.only.split(",") if x.strip()}
    changed = 0
    for card in sorted(CORE.rglob("product-cards/PROD-*.md")):
        if only and card.stem not in only:
            continue
        for m in process_card(card, args.dry_run):
            print(("DRY " if args.dry_run else "") + m)
            if not m.startswith("[SKIP]") and not m.startswith("[NOOP]"):
                changed += 1
    print(f"\n{'将修改' if args.dry_run else '已修改'} {changed} 处")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
