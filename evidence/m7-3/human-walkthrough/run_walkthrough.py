"""人类走查（Playwright）：把"六环链路"用浏览器**像人一样**走一遍，逐步留**原图**。

**一键复跑**（推荐；自动起 KERT、收尾清理、按需带知识库侧）：

    scripts/run_human_walkthrough.sh                 # KERT 侧（含六环工作台）
    scripts/run_human_walkthrough.sh --with-lightrag # 再加知识库侧（需 9621 在跑）

手动用法（需先起好服务）：

    # 1) KERT（供给态，自带技能包）—— 走查用**独立端口**，不碰任何他人实例
    python -c "import sys; sys.argv=['kert','provision','-w','/tmp/human-ws',\
'-s','examples/bank-front-knowledge-maps','--init']; from kert.cli.main import app; app()"
    KERT_PROFILE=dev KERT_SKILL_PACKAGES=$PWD/examples/bank-front-skills \
      python scripts/serve_skill_service.py --port 8123 --workspace /tmp/human-ws

    # 2) LightRAG（外部实例，WebUI 9621，账号见其 .env 的 AUTH_ACCOUNTS）—— 只在走 b 时需要
    .venv/bin/python evidence/m7-3/human-walkthrough/run_walkthrough.py                 # kert + workbench
    .venv/bin/python evidence/m7-3/human-walkthrough/run_walkthrough.py --only all      # 再加 lightrag
    .venv/bin/python evidence/m7-3/human-walkthrough/run_walkthrough.py --only b        # 只走知识库侧

产出：本目录下的 PNG（原图，未裁剪未美化）+ 控制台文字（每步"人看到了什么"）。

⚠ 纪律：全程只调用**只读或幂等**的端点 + 一个自带技能执行；LightRAG 侧只做**检索**（不发布/不撤回），
因此不会改动任何共享语料。
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time

from playwright.sync_api import sync_playwright

KERT = "http://127.0.0.1:8123"
LIGHTRAG_WEBUI = "http://127.0.0.1:9621/webui"
LIGHTRAG_ACCOUNT = ("admin", "lightrag123")
OUT = pathlib.Path(__file__).resolve().parent
VIEWPORT = {"width": 1500, "height": 950}
#: `--only` 取值（`a`/`b` 为**历史别名**，保持向后兼容）
PARTS = {"kert", "workbench", "lightrag", "all", "a", "b"}

PLAN_BODY = json.dumps({"taskType": "OUTREACH_PREPARATION",
                        "subjectId": "CUST-CORP-0001"}, ensure_ascii=False)
SKILL_OK_BODY = json.dumps({
    "skillId": "skill-customer-previsit-report",
    "request": {"customerId": "CUST-CORP-0001",
                "evidenceTimestamp": "2026-09-16T10:00:00Z"}}, ensure_ascii=False)
SKILL_BLOCKED_BODY = json.dumps({
    "skillId": "skill-customer-previsit-report",
    "request": {"customerId": "CUST-CORP-0001"}}, ensure_ascii=False)
SKILL_ASYNC_BODY = json.dumps({
    "skillId": "skill-customer-outreach-script",
    "async": True,
    "request": {"customerId": "CUST-CORP-0001",
                "evidenceTimestamp": "2026-09-16T10:00:00Z"}}, ensure_ascii=False)
#: 人类会提的那种问题（围绕已发布进知识库的 KERT 产物：客户画像 / 产品 / 利率）
QUERY = "客户 CUST-CORP-0001 的客户画像 与 产品利率 是什么？"


def shot(page, name: str, *, element=None, full: bool = True) -> None:
    path = OUT / name
    if element is not None:
        element.scroll_into_view_if_needed()
        element.screenshot(path=str(path))          # 元素截图：请求+响应同框，便于人眼核
    else:
        page.screenshot(path=str(path), full_page=full)
    print(f"  [原图] {name}  ({(path.stat().st_size / 1024):.0f} KB)")


def opblock(page, path_text: str, method: str = "post"):
    """按路径文案定位 Swagger 里的某个操作块（人类也是这么找的）。"""
    loc = page.locator(f".opblock-{method}").filter(
        has=page.locator(".opblock-summary-path", has_text=path_text))
    loc.first.wait_for(state="visible", timeout=20000)
    return loc.first


def try_it(block, body: str | None = None, *, path_param: str | None = None,
           execute: bool = True):
    """人对 Swagger 的动作序列：展开 → Try it out → 填入参 → Execute（**幂等**，可反复用同一块）。

    Swagger 的 "Try it out" 按钮在同一操作上点第二次会变成 "Cancel" ⇒ 这里按**按钮文案**判断，
    不重复点（人类也是这么做的）。
    """
    if not block.locator(".opblock-body").is_visible():
        block.locator(".opblock-summary").click()
        time.sleep(0.4)
    # 进入 try-out 模式后 Swagger 会同时渲染 "Cancel" 与 "Reset" 两个同 class 按钮
    # ⇒ 必须取 .first，否则 strict 模式报歧义（实测）。
    btn = block.locator("button.try-out__btn").first
    btn.wait_for(state="visible", timeout=15000)
    if (btn.inner_text() or "").strip().lower().startswith("try"):
        btn.click()
        time.sleep(0.3)
    if path_param is not None:
        inp = block.locator("input[type=text]").first
        inp.wait_for(state="visible", timeout=10000)
        inp.fill(path_param)
    if body is not None:
        ta = block.locator("textarea.body-param__text")
        ta.wait_for(state="visible", timeout=10000)
        ta.fill(body)
    if execute:
        ex = block.locator("button.execute").first
        ex.wait_for(state="visible", timeout=15000)
        ex.click()
        block.locator(".responses-table").first.wait_for(timeout=30000)
        time.sleep(1.2)
    return block


def kert_walkthrough(page) -> None:
    print("[Part A] KERT：人类在 API 控制台上走 环1→环3")
    page.goto(f"{KERT}/docs", wait_until="domcontentloaded")
    page.locator(".opblock").first.wait_for(timeout=30000)
    time.sleep(1.0)
    shot(page, "S01_kert_swagger_overview.png")

    # 环 1：知识地图
    b = try_it(opblock(page, "/v1/knowledge-maps", "get"))
    shot(page, "S02_ring1_knowledge_maps.png", element=b)

    # 环 2：技能路由 / 计划放行（含本体版本）
    b = try_it(opblock(page, "/v1/routing/plan"), PLAN_BODY)
    shot(page, "S03_ring2_routing_plan.png", element=b)

    # 环 3：本体语义 → 业务报告（真出结果）
    sk = opblock(page, "/api/skill/execute")
    b = try_it(sk, SKILL_OK_BODY)
    shot(page, "S04_ring3_skill_report.png", element=b)

    # 环 3 对照：无新证据 ⇒ 受控退出（不是"随便就能出结果"）
    b = try_it(sk, SKILL_BLOCKED_BODY)
    shot(page, "S05_policy_controlled_exit.png", element=b)

    # 异步作业：受理 202 + 作业状态（业务状态机）
    b = try_it(sk, SKILL_ASYNC_BODY)
    shot(page, "S06a_job_accepted_202.png", element=b)
    b = try_it(opblock(page, "/v1/jobs/{job_id}", "get"),
               path_param="JOB-SKILL-20260916-001")
    shot(page, "S06b_job_status.png", element=b)


def lightrag_walkthrough(page) -> None:
    print("[Part B] LightRAG：人类在知识库 WebUI 里看文档 / 检索（环5/环6 的可见面）")
    page.goto(LIGHTRAG_WEBUI, wait_until="domcontentloaded")
    time.sleep(3.0)
    shot(page, "S07_lightrag_login.png")

    page.fill("#username-input", LIGHTRAG_ACCOUNT[0])
    page.fill("#password-input", LIGHTRAG_ACCOUNT[1])
    page.locator("button:has-text('登录')").first.click()
    time.sleep(6.0)
    shot(page, "S08_lightrag_documents.png")

    # 检索：输入自然语言问题 ⇒ 看答案与**出处**
    page.locator("button:has-text('检索')").first.click()
    time.sleep(3.0)
    box = page.locator("input[placeholder*='输入查询内容'], textarea[placeholder*='输入查询内容']").first
    box.wait_for(state="visible", timeout=15000)
    box.fill(QUERY)
    page.locator("button:has-text('发送')").first.click()
    body = ""
    for _ in range(48):                      # 流式回答：最多等 ~48s
        time.sleep(1.0)
        body = page.inner_text("body")
        if "引用" in body or "参考" in body or "References" in body:
            break
    time.sleep(2.0)
    shot(page, "S09_lightrag_answer_with_citations.png")

    # 知识图谱（对人类可见的图规模）
    page.locator("button:has-text('知识图谱')").first.click()
    time.sleep(7.0)
    shot(page, "S10_lightrag_graph.png")


def workbench_part(page) -> None:
    """[Part C] **六环工作台**（`/dsh/rings`）：人点一次「一键走一遍」，逐环看结论与原始响应。

    与 Part A 的区别：A 是"在 Swagger 里逐个 Try it out"，C 是"我们自己的工作台"——
    同一批端点、但按**环**组织，且环 5/6 直接用环 2 拿到的 `planId` 把整条链取回来（全链关联 ID）。
    """
    print("[Part C] 六环工作台：人点一次「一键走一遍」，逐环看结论（含全链关联 ID）")
    page.goto(f"{KERT}/dsh/rings", wait_until="networkidle")
    page.wait_for_selector("#run-all", timeout=30000)
    time.sleep(1.0)
    shot(page, "S11_workbench_overview.png")
    page.click("#run-all")
    page.wait_for_function(
        "() => document.getElementById('run-summary').textContent.includes('走完')",
        timeout=60000)
    time.sleep(1.0)
    print(f"  连接状态：{page.inner_text('#conn-pill')}；"
          f"小结：{page.inner_text('#run-summary').splitlines()[0][:140]}")
    for key in ("ring1", "ring2", "ring4", "ring56"):
        first = page.inner_text("#sum-" + key).splitlines()[0][:120]
        print(f"  [{key}] {first}")
    shot(page, "S12_workbench_after_run.png")


def _launch(pw):
    """优先用**系统 Chrome**（`channel="chrome"`）：本机缓存里的 chromium 构建号与 pip 版
    playwright 不匹配（期望 1243，缓存只有 1223/1234），用系统 Chrome 可免下载且更接近
    "人类日常浏览器"。失败则回退到 Playwright 自带构建（需 `playwright install chromium`）。"""
    try:
        return pw.chromium.launch(channel="chrome", headless=True)
    except Exception as exc:  # pragma: no cover - 视本机安装而定
        print("  (系统 Chrome 启动失败，回退自带 chromium:", exc, ")")
        return pw.chromium.launch(headless=True)


def main() -> int:
    global KERT, LIGHTRAG_WEBUI, OUT

    ap = argparse.ArgumentParser(description="六环链路人类走查（Playwright；原图 + 故事）")
    ap.add_argument("only", nargs="?", default=None, choices=sorted(PARTS),
                    help="kert（KERT 侧 + 工作台，**默认**）/ workbench / lightrag / all；"
                         "a、b 为历史别名（a→kert，b→lightrag）")
    ap.add_argument("--kert-url", default=KERT, help="KERT 基址（默认 http://127.0.0.1:8123）")
    ap.add_argument("--lightrag-url", default=LIGHTRAG_WEBUI,
                    help="知识库 WebUI 基址（默认 http://127.0.0.1:9621/webui）")
    ap.add_argument("--out", default=str(OUT), help="PNG 输出目录（默认：本脚本所在目录）")
    ap.add_argument("--with-lightrag", action="store_true",
                    help="等价 --only all（同时走知识库侧；需该实例在跑）")
    args = ap.parse_args()

    KERT = args.kert_url.rstrip("/")
    LIGHTRAG_WEBUI = args.lightrag_url.rstrip("/")
    OUT = pathlib.Path(args.out)

    only = args.only or "kert"
    if args.with_lightrag:
        only = "all"
    elif only == "a":
        only = "kert"
    elif only == "b":
        only = "lightrag"
    if args.only is None and not args.with_lightrag:
        print("（未指定 --only ⇒ 默认只走 KERT 侧 + 六环工作台；知识库侧请用 "
              "--only all 或 --with-lightrag）")

    want_kert = only in ("all", "kert", "workbench")
    want_workbench = only in ("all", "kert", "workbench")
    want_lightrag = only in ("all", "lightrag")

    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        browser = _launch(pw)
        ctx = browser.new_context(viewport=VIEWPORT, locale="zh-CN")
        page = ctx.new_page()
        page.set_default_timeout(30000)
        try:
            if want_kert:
                kert_walkthrough(page)
            if want_workbench:
                workbench_part(page)
            if want_lightrag:
                lightrag_walkthrough(page)
        finally:
            ctx.close()
            browser.close()
    print("完成。原图目录：", OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
