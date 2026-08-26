#!/usr/bin/env python3
"""把 DKWS 访前报告 Markdown 转成带样式的独立 HTML。

用法：python md_to_html.py --input 访前报告_HZB0000001234.md [--output out.html]
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import markdown as md_lib

CSS = """
:root { --primary:#1a4d8f; --accent:#2f6fc0; --bg:#f5f7fa; --card:#ffffff; --text:#1f2d3d; --muted:#6b7a8d; }
* { box-sizing: border-box; }
body { margin:0; background:var(--bg); color:var(--text); font-family:"Microsoft YaHei","PingFang SC",-apple-system,"Segoe UI",sans-serif; line-height:1.7; }
.page { max-width:880px; margin:32px auto; background:var(--card); border-radius:14px; box-shadow:0 10px 40px rgba(31,45,61,.12); overflow:hidden; }
.hero { background:linear-gradient(135deg,var(--primary),var(--accent)); color:#fff; padding:34px 44px; }
.hero h1 { margin:0 0 10px; font-size:26px; letter-spacing:.5px; }
.hero .meta { font-size:13px; opacity:.92; line-height:1.9; }
.hero .tag { display:inline-block; background:rgba(255,255,255,.18); border-radius:999px; padding:2px 12px; margin-right:8px; font-size:12px; }
.content { padding:32px 44px 20px; }
.content h2 { color:var(--primary); font-size:19px; border-left:4px solid var(--accent); padding-left:12px; margin:28px 0 12px; }
.content h3 { color:var(--accent); font-size:16px; margin:18px 0 8px; }
.content p { margin:8px 0; }
.content ul, .content ol { margin:8px 0 8px 22px; }
.content blockquote { margin:10px 0; padding:10px 16px; background:#eef4fb; border-left:4px solid var(--accent); border-radius:0 8px 8px 0; color:var(--text); }
.content code { background:#eef2f7; border-radius:4px; padding:1px 6px; font-size:.9em; font-family:"SF Mono","Consolas",monospace; }
.summary { background:#eef4fb; border-radius:10px; padding:14px 18px; margin:12px 0; }
.footer { padding:18px 44px 26px; color:var(--muted); font-size:12px; border-top:1px solid #e6ebf2; }
.footer .badge { display:inline-block; background:#fde8e8; color:#b3261e; border-radius:999px; padding:1px 10px; font-size:11px; margin-right:8px; }
"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", default=None)
    ap.add_argument("--title", default="客户经理访前报告")
    args = ap.parse_args()

    src = Path(args.input)
    text = src.read_text(encoding="utf-8")
    out = Path(args.output) if args.output else src.with_suffix(".html")

    lines = text.splitlines()
    hero_lines: list[str] = []
    body_lines: list[str] = []
    in_hero = False
    for i, line in enumerate(lines):
        if line.startswith("# ") and i < 3:
            in_hero = True
            hero_lines.append(line[2:].strip())
            continue
        if in_hero:
            if line.startswith(">"):
                hero_lines.append(line.lstrip(">").strip())
            elif line.strip():
                hero_lines.append(line.strip())
            else:
                in_hero = False
            continue
        body_lines.append(line)

    hero_html = "".join(f"<div class='meta'>{_escape(h)}</div>" for h in hero_lines[1:] if h)
    body_md = "\n".join(body_lines)
    body_html = md_lib.markdown(body_md, extensions=["extra", "sane_lists"])

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_escape(args.title)}</title>
<style>{CSS}</style>
</head>
<body>
<div class="page">
  <div class="hero">
    <h1>{_escape(hero_lines[0] if hero_lines else args.title)}</h1>
    {hero_html}
  </div>
  <div class="content">
{body_html}
  </div>
  <div class="footer">
    <span class="badge">humanGate · 非审批结论</span>
    由 DKWS 客户经理持续经营 Skill 平台生成。
    本报告基于输入事实与证据生成，仅供访前准备参考，不构成业务审批、合规批准或监管结论。
  </div>
</div>
</body>
</html>
"""
    out.write_text(html, encoding="utf-8")
    print(f"HTML 报告已生成: {out}（{out.stat().st_size} 字节）")


def _escape(s: str) -> str:
    return re.sub(r"[&<>]", lambda m: {"&": "&amp;", "<": "&lt;", ">": "&gt;"}[m.group(0)], s)


if __name__ == "__main__":
    main()
