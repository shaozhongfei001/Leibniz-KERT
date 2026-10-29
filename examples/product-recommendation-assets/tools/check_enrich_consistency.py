#!/usr/bin/env python3
"""「回填内容 vs 源声明」一致性门禁（防止再次漂移）

## 为什么需要

`tools/enrich_cards_from_sources.py` 会把权威源条款**回填**进产品卡 §1/§2/§4/§5/§7/§8。
历史上出现过四类漂移，本门禁逐类设卡：

| 编号 | 漂移类型 | 实例 |
|---|---|---|
| D1 | 源映射错配（按编号盲配，不按内容） | `SRC-CM-002`（法人账户透支规程）曾被灌进「资金归集」卡 |
| D2 | 引用不逐字（改写/拼接/编造） | 回填正文与源条款原文不一致 |
| D3 | **主张类型越界**（回填内容 vs `allowed_claim_types` 声明） | 源只声明 `ELIGIBILITY/PROCESS`，却被引用于 §8 定价 |
| D4 | 门槛无出处 / 双口径 | 卡片写「信用评级 A 及以上」，源材料只写「按准入线」 |

## 校验项

1. `SRC_MAP` 覆盖全部卡片、源文件存在（D1）
2. 卡内 enrich 块来源 == `SRC_MAP`，块内每条 `（依据 <SRC> 第N条）` 的源与条号必须成立（D1/D2）
3. 块内正文必须是该条款**逐字片段**（去空白后包含关系）（D2）
4. 块所在小节 → 主张类型必须 ∈ 源 `allowed_claim_types`（D3）
   - §1 `制度依据` ⇒ `ELIGIBILITY`/`REGULATORY`
   - §2 `适用范围依据`、§4 `准入依据`、§5 `排除依据` ⇒ `ELIGIBILITY`
   - §7 ⇒ `PROCESS`
   - §8 `定价政策` ⇒ `PRICE`
5. 标签与小节必须对应（`准入依据` 不得出现在 §8 等）（D1）
6. 评级门槛：卡片 front matter `minRating` 与**卡片自有**（非回填块）§4 行的门槛，必须能在该源条款中找到；
   且卡片自有门槛与 `minRating` 唯一一致（D4）
7. **回填块内门槛唯一**：同一卡片的 enrich 块中，门槛句式（`不低于 X 级` / `准入线为 X 级` / `X 级及以上`）
   只能出现 `minRating` 一个等级 —— 防止「第六条说 AA、第二十条说 BB」这类同卡双口径（D4）
   - 注：`AA 级（含）以上适用…品种` 属**授权档位**而非准入门槛，不计入本项
7. 结构卫生：无空块、无重复「办理渠道」行、无历史合成行残留

## 用法

    python3 tools/check_enrich_consistency.py
退出码 0 表示全部通过。
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
ENRICH = Path(__file__).resolve().parent / "enrich_cards_from_sources.py"

# 小节 → 允许的标签
LABEL_BY_SECTION = {
    "1": "制度依据",
    "2": "适用范围依据",
    "4": "准入依据",
    "5": "排除依据",
    "8": "定价政策",
}
# 小节 → 必需的主张类型（D3）
CLAIM_BY_SECTION = {
    "1": {"ELIGIBILITY", "REGULATORY"},
    "2": {"ELIGIBILITY"},
    "4": {"ELIGIBILITY"},
    "5": {"ELIGIBILITY"},
    "7": {"PROCESS"},
    "8": {"PRICE"},
}
# 评级门槛表达（只认"最低门槛"句式；区间/档位描述不算）
# `不低于 X 级` / `X 级及以上` / `准入线为（内部评级）X 级` 三种都必须能识别
THRESHOLD_RE = re.compile(
    r"(?:不低于|准入线为(?:内部评级)?)\s*(AA|A|BBB|BB|B)\s*级"
    r"|(AA|A|BBB|BB|B)\s*级\s*及以上"
)
LEVEL_RE = re.compile(r"(?<![A-Za-z])(AA|A|BBB|BB|B)(?![A-Za-z])")
BLOCK_RE = re.compile(r"<!-- enrich:(SRC-[A-Z0-9-]+) begin -->(.*?)<!-- enrich:\1 end -->", re.S)
BULLET_RE = re.compile(r"^- (.+?)（依据 (SRC-[A-Z0-9-]+) (第[^）]+条)）：(.+)$")
CITE_RE = re.compile(r"^(?:- (?:流程|办理渠道)：)?(.+?)（依据 (SRC-[A-Z0-9-]+) (第[^）]+条)）\s*$")

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    results.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'} | {name}" + (f" | {detail}" if detail and not ok else ""))
    return ok


def norm(s: str) -> str:
    """去空白 + 去 Markdown 强调符，用于逐字比对。"""
    return re.sub(r"\s+", "", s.replace("**", "").replace("`", ""))


def load_enrich():
    spec = importlib.util.spec_from_file_location("_enrich", ENRICH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def front_matter(text: str) -> str:
    if not text.startswith("---"):
        return ""
    parts = text.split("\n---", 1)
    return parts[0] if len(parts) == 2 else ""


def claim_types(src_text: str) -> set[str]:
    m = re.search(r"^allowed_claim_types:\s*\[(.*?)\]", front_matter(src_text), re.M)
    return {x.strip() for x in m.group(1).split(",") if x.strip()} if m else set()


def min_rating(card_text: str) -> str | None:
    m = re.search(r"^\s*minRating:\s*(\S+)", front_matter(card_text), re.M)
    if not m or m.group(1).lower() in ("null", "none", "~"):
        return None
    return m.group(1).strip().strip('"\'')


def thresholds(line: str) -> set[str]:
    out = set()
    for m in THRESHOLD_RE.finditer(line):
        out.add(m.group(1) or m.group(2))
    return out


def main() -> int:
    if not ENRICH.exists():
        check("enrich 脚本存在", False, str(ENRICH))
        return 1
    mod = load_enrich()
    cards = sorted(mod.CORE.rglob("product-cards/PROD-*.md"))
    check(f"扫描到产品卡 {len(cards)} 张", len(cards) > 0, f"实际 {len(cards)}")

    missing_map = [c.stem for c in cards if c.stem not in mod.SRC_MAP]
    check("SRC_MAP 覆盖全部卡片（防编号盲配）", not missing_map, f"未登记: {missing_map}")

    for card in cards:
        pid = card.stem
        src_id = mod.SRC_MAP.get(pid)
        if not src_id:
            continue
        src_path = mod.SRC_DIR / f"{src_id}.DEMO.md"
        if not check(f"{pid} 源文件存在（{src_id}）", src_path.is_file(), str(src_path)):
            continue
        src_text = src_path.read_text(encoding="utf-8")
        claims = claim_types(src_text)
        clauses = {cid: body for cid, body in mod.clauses_of(src_text)}
        card_text = card.read_text(encoding="utf-8")

        # ---- D1/D2/D3/D5：回填块 ----
        for sec_no, sec_text in mod.split_sections(card_text):
            blocks = list(BLOCK_RE.finditer(sec_text))
            if not blocks:
                continue
            if not check(f"{pid} §{sec_no} 允许回填块", sec_no in CLAIM_BY_SECTION,
                         "该小节不应出现 enrich 块"):
                continue
            for bm in blocks:
                block_src, block_body = bm.group(1), bm.group(2)
                check(f"{pid} §{sec_no} 块来源 == SRC_MAP", block_src == src_id,
                      f"块写 {block_src} vs 登记 {src_id}")
                ok_claim = claims & CLAIM_BY_SECTION[sec_no]
                check(f"{pid} §{sec_no} 主张类型 ∈ 源声明", bool(ok_claim),
                      f"源 {src_id} 声明 {sorted(claims)}，§{sec_no} 需要 "
                      f"{sorted(CLAIM_BY_SECTION[sec_no])}")
                bullets = [ln for ln in block_body.strip().split("\n") if ln.strip()]
                check(f"{pid} §{sec_no} 块非空", bool(bullets), "块内无条目")
                for ln in bullets:
                    m = BULLET_RE.match(ln.strip())
                    if not check(f"{pid} §{sec_no} 条目格式", m is not None, ln[:60]):
                        continue
                    label, line_src, cid, body = m.groups()
                    check(f"{pid} §{sec_no} 标签=={LABEL_BY_SECTION[sec_no]}",
                          label == LABEL_BY_SECTION[sec_no], f"实际「{label}」")
                    check(f"{pid} §{sec_no} 条目源 == {src_id}", line_src == src_id, line_src)
                    clause = clauses.get(cid)
                    if not check(f"{pid} §{sec_no} 条号 {cid} 存在于源", clause is not None):
                        continue
                    check(f"{pid} §{sec_no} {cid} 正文逐字来自源", norm(body) in norm(clause),
                          "回填正文不是该条款的逐字片段（疑似改写/编造）")

        # ---- D2/D4：行内引用（§7 流程/办理渠道 等）----
        for line in card_text.split("\n"):
            m = CITE_RE.match(line.strip())
            if not m:
                continue
            content, line_src, cid = m.groups()
            if not check(f"{pid} 行内引用源 == {src_id}", line_src == src_id, line_src):
                continue
            clause = clauses.get(cid)
            if not check(f"{pid} 行内引用 {cid} 存在于源", clause is not None):
                continue
            if "→" in content:  # 流程箭头串：逐步名必须在条款内（允许用「→」重组）
                steps = [s.strip() for s in content.split("→") if s.strip()]
                miss = [s for s in steps if norm(s) not in norm(clause)]
                check(f"{pid} §7 流程步骤可回译到 {cid}", not miss, f"缺失 {miss}")
            else:
                check(f"{pid} 行内引用 {cid} 正文逐字来自源", norm(content) in norm(clause),
                      "引用正文不是该条款的逐字片段")

        # ---- D4：评级门槛唯一且有出处 ----
        mr = min_rating(card_text)
        sec4 = dict(mod.split_sections(card_text)).get("4", "")
        card_own = BLOCK_RE.sub("", sec4)
        card_thresholds = set()
        for line in card_own.split("\n"):
            card_thresholds |= thresholds(line)
        if mr:
            check(f"{pid} minRating={mr} 在源中有出处", mr in set(LEVEL_RE.findall(src_text)),
                  f"源 {src_id} 未出现评级等级 {mr}")
            bad = card_thresholds - {mr}
            check(f"{pid} §4 自有门槛与 minRating 一致", not bad,
                  f"minRating={mr} 但卡片自有门槛 {sorted(bad)}")
            miss = card_thresholds - set(LEVEL_RE.findall(src_text))
            check(f"{pid} §4 自有门槛在源中有出处", not miss, f"无出处 {sorted(miss)}")
        else:
            check(f"{pid} 无 minRating ⇒ §4 不得出现评级门槛", not card_thresholds,
                  f"存在未登记门槛 {sorted(card_thresholds)}")

        # ---- D4'：回填块内门槛唯一（防同卡双口径） ----
        block_thresholds: set[str] = set()
        for _sec_no, _sec_text in mod.split_sections(card_text):
            for _bm in BLOCK_RE.finditer(_sec_text):
                for _ln in _bm.group(2).split("\n"):
                    block_thresholds |= thresholds(_ln)
        if mr:
            extra = block_thresholds - {mr}
            check(f"{pid} 回填块内门槛唯一（== minRating）", not extra,
                  f"minRating={mr} 但回填块另含门槛 {sorted(extra)}（同卡双口径）")
        else:
            check(f"{pid} 无 minRating ⇒ 回填块不得出现门槛", not block_thresholds,
                  f"存在未登记门槛 {sorted(block_thresholds)}")

        # ---- 结构卫生 ----
        chan = re.findall(r"^- 办理渠道：.*$", card_text, re.M)
        check(f"{pid} 无重复「办理渠道」行", len(chan) == len(set(chan)),
              f"{len(chan)} 行，去重后 {len(set(chan))}")
        check(f"{pid} 无历史合成行残留",
              "费率金额：待核定（源材料未给出具体数值" not in card_text)

    failed = [r for r in results if not r[1]]
    print(f"\n{'=' * 64}")
    print(f"回填—声明一致性：{len(results) - len(failed)}/{len(results)} PASS")
    if failed:
        print("失败项：")
        for n, _ok, d in failed[:40]:
            print(f"  - {n} {d}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
