#!/usr/bin/env python3
"""**UI 冒烟**（真人浏览器）：页面能开、**样式与脚本真的加载**、页面里的 JS 能调通本地 API。

存在理由（实测缺陷，2026-09-17）：`mount_dsh` 曾把静态挂载放在 SPA 兜底**之后** ⇒
`/dsh/static/*` 全部 **404** —— 页面 200 可开，但**无样式、无脚本、界面等于不可用**。
纯 HTTP 断言（"GET /dsh/ 返回 200"）**发现不了**这类故障 ⇒ 必须用浏览器验"资源真的加载了、JS 真的跑了"。

本脚本验什么 / 不验什么（**防误读**）：

- **验**（可达性三件）：① 两个页面 200 且有 HTML；② 同源 css/js **无 4xx/5xx**（防"样式/脚本 404"复发）；
  ③ 页面里的 JS **无未捕获异常**，且「六环工作台」的**一键走一遍**能跑完（说明页面能从前端调通本地 API）。
- **不验**：六环链路本身（知识地图→计划→技能→出口→检索的**正确性**由
  `tests/integration/**` 与 CI 的 `retrieval-loop-e2e` 负责）；**本脚本通过 ≠ 链路已验证**。
- **不做**：不发布/不撤回/不改工作区（只读浏览 + 一次自带技能/计划的**幂等只读**调用）。

用法：``python scripts/ci/ui_smoke.py --base-url http://127.0.0.1:8123 --out <截图目录>``
退出码：0 = 三项全过；1 = 任一失败（打印 ``::error::`` 与浏览器控制台/网络错误明细）。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

NON_CLAIM = ("本步只验『页面能开 + 样式/脚本加载 + 前端能调通本地 API』；"
             "**不等于**六环链路已验证（链路由 tests/integration/** 与 retrieval-loop-e2e 负责）。")


def _fail(msg: str) -> None:
    print(f"::error::[UI_SMOKE] {msg}", flush=True)


def _shoot(page, out: Path, name: str) -> None:
    """尽力截图（失败不掩盖主问题：诊断需要图，但图不是判据）。"""
    try:
        page.screenshot(path=str(out / name), full_page=True)
    except Exception as exc:                       # noqa: BLE001 - 截图失败不改变判定
        print(f"  (截图 {name} 失败：{exc})", flush=True)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="UI 冒烟（真人浏览器，只验可达性）")
    ap.add_argument("--base-url", default="http://127.0.0.1:8123")
    ap.add_argument("--out", default="/tmp/ui-smoke")
    ap.add_argument("--timeout-ms", type=int, default=30000)
    args = ap.parse_args(argv[1:])

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    base = args.base_url.rstrip("/")

    from playwright.sync_api import sync_playwright

    bad_resources: list[str] = []
    page_errors: list[str] = []
    problems: list[str] = []

    # ── 判据 A（发布物层）：`kert.dsh.static` 是否**随安装带过来** ──────────────────
    # 为什么放在最前：这一格一旦缺失，服务会回 503（"DSH 界面未安装"），
    # 后面的页面断言只会报"未返回 200（503）"，**指不到根因**（包装缺陷）。
    # 缺陷 2（2026-09-17 实测）：`pyproject.toml` 未声明 `package-data` ⇒ 非 editable 安装**不含**
    # `kert/dsh/static/*` ⇒ 部署形态下界面恒 503。此处把它钉成**具名**判据。
    # 本脚本以 `--file` 直接运行 ⇒ `sys.path` 首项是 `scripts/ci`，故 `import kert` 取的是**已安装的发布物**
    #（正是本 job 要验的对象；editable 安装下则指向源树，同样成立）。
    try:
        from kert.dsh import app as _dsh_app

        static_dir = Path(_dsh_app._STATIC_DIR)          # noqa: SLF001 - 与该应用同源常量
        print(f"  [发布物] kert.dsh 位置 = {Path(_dsh_app.__file__).parent}"
              f"；static 目录 = {static_dir}（存在={static_dir.is_dir()}）", flush=True)
        wanted = ("index.html", "app.js", "style.css", "rings.html", "rings.js")
        missing = [n for n in wanted if not (static_dir / n).is_file()]
        if not static_dir.is_dir() or missing:
            problems.append(
                f"发布物缺 `kert/dsh/static/`：{static_dir} 下缺 {missing or '整个目录'}"
                " ⇒ 非 editable 安装未含界面静态件（检查 `pyproject.toml` 的 "
                "`[tool.setuptools.package-data]` → \"kert.dsh\" = [\"static/*\"]）")
    except Exception as exc:                      # noqa: BLE001 - 导入失败也要具名
        problems.append(f"无法核对发布物里的界面静态件（导入 kert.dsh.app 失败）：{exc}")

    try:
        with sync_playwright() as pw:
            try:
                browser = pw.chromium.launch(channel="chrome", headless=True)
                browser_kind = "system chrome"
            except Exception as exc:              # 本机无系统 Chrome ⇒ 用自带 chromium
                print(f"  (系统 Chrome 不可用，回退自带 chromium：{exc})", flush=True)
                browser = pw.chromium.launch(headless=True)
                browser_kind = "bundled chromium"
            ctx = browser.new_context(viewport={"width": 1500, "height": 950}, locale="zh-CN")
            page = ctx.new_page()
            page.set_default_timeout(args.timeout_ms)

            def on_response(resp) -> None:
                """同源 css/js 的 4xx/5xx 一律记账（这正是"静默 404"的探测器）。"""
                url = resp.url
                if not url.startswith(base):
                    return
                if resp.status >= 400 and any(url.endswith(s) for s in (".css", ".js")):
                    bad_resources.append(f"{resp.status} {url}")

            page.on("response", on_response)
            page.on("pageerror", lambda exc: page_errors.append(str(exc)))

            print(f"[ui-smoke] 浏览器 = {browser_kind}；目标 = {base}", flush=True)

            # ── 判据 B（服务层）：两个页面**引用的静态件**必须真能取到 ──
            # 缺陷 1（2026-09-17 实测）：`mount_dsh` 曾把静态挂载放在 SPA 兜底**之后** ⇒
            # 兜底先匹配并 404 ⇒ 页面 200 但**无样式、无脚本**。此处按 HTTP 至少钉住这一格。
            for asset in ("/dsh/static/style.css", "/dsh/static/app.js",
                          "/dsh/static/rings.html", "/dsh/static/rings.js"):
                asset_resp = page.request.get(f"{base}{asset}")
                if asset_resp.status != 200:
                    problems.append(
                        f"静态件 {asset} = {asset_resp.status}（应为 200）"
                        " ⇒ 服务未把静态件暴露出来（常见原因：SPA 兜底 `/{path:path}` 先于静态挂载"
                        " 匹配 ⇒ 需‘静态先挂载、再 include_router’）")
            if not any(p.startswith("静态件 ") for p in problems):
                print("  [静态件] style.css / app.js / rings.html / rings.js 均 200", flush=True)

            # ① DSH 首页：能开 + 样式/脚本加载 + 侧栏真的被样式化
            resp = page.goto(f"{base}/dsh/", wait_until="networkidle")
            if resp is None or resp.status != 200:
                problems.append(f"/dsh/ 未返回 200（{getattr(resp, 'status', None)}）")
            _shoot(page, out, "ui_smoke_01_dsh_dashboard.png")
            try:
                styled = page.evaluate(
                    "() => { const n = document.querySelector('.sidebar');"
                    " return n ? getComputedStyle(n).display : ''; }")
                sheets = page.evaluate("() => document.styleSheets.length")
            except Exception as exc:              # noqa: BLE001 - 页面不可交互 ⇒ 记为问题
                styled, sheets = "", 0
                problems.append(f"/dsh/ 无法执行页面脚本：{exc}".splitlines()[0])
            print(f"  /dsh/ 侧栏 display={styled!r}；样式表数={sheets}", flush=True)
            if sheets < 1:
                problems.append("/dsh/ 未加载任何样式表（css 未被引用/加载）")
            if not styled:
                problems.append("/dsh/ 侧栏元素缺失（页面结构未渲染）")

            # ② 六环工作台：能开 + JS 真的跑了（一键走一遍跑完）+ 前端能调通本地 API
            resp2 = page.goto(f"{base}/dsh/rings", wait_until="networkidle")
            if resp2 is None or resp2.status != 200:
                problems.append(f"/dsh/rings 未返回 200（{getattr(resp2, 'status', None)}）")
            conn = ""
            try:
                page.wait_for_selector("#run-all", timeout=args.timeout_ms)
                page.click("#run-all")
                page.wait_for_function(
                    "() => (document.getElementById('run-summary')||{}).textContent"
                    ".includes('走完')", timeout=args.timeout_ms)
                summary = page.inner_text("#run-summary")
                conn = page.inner_text("#conn-pill")
                print(f"  工作台连接状态={conn!r}；一键走一遍小结："
                      f"{summary.splitlines()[0][:120]}", flush=True)
            except Exception as exc:              # noqa: BLE001 - 交互失败 ⇒ 具名问题（不打堆栈）
                problems.append(
                    "工作台「一键走一遍」未能跑完（页面 JS 未生效）："
                    f"{str(exc).splitlines()[0]}"
                    " —— 常见原因：`/dsh/static/rings.js` 未加载（静态挂载被兜底吞掉？）"
                    "或页面 JS 抛异常")
            _shoot(page, out, "ui_smoke_02_rings_workbench.png")
            if conn and conn != "已连接":
                problems.append(f"工作台未能连上 API（连接标记={conn!r}）")

            ctx.close()
            browser.close()
    except Exception as exc:                      # noqa: BLE001 - 浏览器/进程级失败转具名，不打堆栈
        first = (str(exc).splitlines() or [type(exc).__name__])[0]
        problems.append(f"浏览器步骤失败：{type(exc).__name__}: {first}")

    if bad_resources:
        problems.append("同源 css/js 出现 4xx/5xx：" + "；".join(sorted(set(bad_resources))[:5]))
    if page_errors:
        problems.append("页面存在未捕获 JS 异常：" + "；".join(page_errors[:3]))

    if problems:
        for p in problems:
            _fail(p)
        print(f"::error::UI 冒烟失败（截图见 {out}）", flush=True)
        return 1

    print(f"✓ UI 冒烟通过：/dsh/ 与 /dsh/rings 均可开、样式与脚本无 4xx/5xx、"
          f"前端能调通本地 API（截图见 {out}）", flush=True)
    print(f"  非声明：{NON_CLAIM}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
