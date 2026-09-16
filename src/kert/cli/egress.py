"""数据出口（外部 LightRAG）**运维面** CLI：``kert egress status|publish|retract``（M7 · ADR-017）。

为什么需要它（**功能缺口**，实测）：``KnowledgeService.publish_artifact`` 的幂等是"**先查后写**"
（同 `file_source` 已存在 ⇒ 回 ``already_published`` 且**不发写请求**）⇒ 产物内容变了，
知识库**永远停在旧内容**、且调用方**看不出来**。本模块把它变成**人能看到、脚本能判定**：

- ``status``  —— 本地产物摘要 vs 实例上该出处的正文摘要 ⇒ ``missing``/``current``/``stale``；
- ``publish`` —— **默认安全**：同出处内容不同 ⇒ **具名 ``stale``**（不写不删、退出码非 0）；
  ``--refresh`` 才走"撤回→重发"，且撤回**仍受归属校验**（D-34，**不因 refresh 而放宽**）；
- ``retract`` —— 复用既有归属校验；``--force`` 才**显式**跳过（留痕 ``verified=false``）。

边界（**不越界**）：本模块**不加** HTTP 路径、**不改**规格；判据与动作全部复用
:class:`~kert.application.services.KnowledgeService`（``egress_state`` / ``egress_publish`` /
``retract_artifact``），CLI 只做"展开目标 + 统一信封 + 退出码"。
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

import typer

from ..domain.errors import (
    EXIT_CONFLICT,
    EXIT_INTERNAL,
    EXIT_USAGE,
    AssetNotFoundError,
)

egress_app = typer.Typer(
    no_args_is_help=True,
    help="数据出口（外部 LightRAG）运维：status / publish / retract（ADR-017）",
)

_OUTPUT = "text|json"
#: 目录/glob 展开的触发字符
_GLOB_CHARS = ("*", "?", "[")

#: `stale` 的**可照抄**处置（两条命令**原样**列出：人不用猜命令名与先后顺序）。
#: 依据：该实例 API 无读正文端点、不支持自定义 metadata ⇒ 摘要窗口内"我们自己的旧版本"与
#: "他人的合法文档"**不可区分**（D-34 事故）⇒ 替换**必须**由操作员**显式** force 撤回，
#: `--refresh` **不是**绕过归属校验的开关。
STALE_ACTIONS_HINT = (
    "确认是本工作区旧版本时，按顺序执行：\n"
    "  kert egress retract <rel> --force\n"
    "  kert egress publish <rel>\n"
    "疑似他人文档时**不要** --force（归属校验正是为拦住这种情况）。")


def _emit(output: str, data: dict, *, status: str = "OK",
          errors: list | None = None, human: str | None = None) -> None:
    """统一输出信封（**复用** :func:`kert.cli.main._emit` ⇒ 输出格式**不分叉**）。

    惰性导入的原因：``main`` 在模块级导入本模块（注册子命令组）⇒ 顶层反向导入会成环。
    """
    from .main import _emit as _main_emit

    _main_emit(output, data, status=status, errors=errors, human=human)


def _service(workspace_path: Path):
    from ..application.services import KnowledgeService

    return KnowledgeService(Path(workspace_path))


def _client():
    from ..infrastructure.lightrag_client import LightRagClient

    return LightRagClient.from_env()


def _expand_targets(ws: Path, target: str) -> list[str]:
    """把 ``<rel_path> | 目录 | glob`` 展开成**白名单内**的相对产物路径清单。

    空匹配 ⇒ **具名** :class:`AssetNotFoundError`（不静默回空表：把"打错路径"与
    "确实没有产物"混起来，运维面就失去了意义）；白名单外的匹配 ⇒ 由 ``_egress_rel`` 具名拒绝。
    """
    from ..application.services import EGRESS_ROOTS, _egress_rel

    raw = str(target).strip()
    if any(c in raw for c in _GLOB_CHARS):
        found = sorted(p.relative_to(ws).as_posix() for p in ws.glob(raw) if p.is_file())
    else:
        p = ws / raw
        if p.is_dir():
            found = sorted(q.relative_to(ws).as_posix() for q in p.rglob("*") if q.is_file())
        elif p.is_file():
            found = [raw]
        else:
            found = []
    if not found:
        raise AssetNotFoundError(
            f"未匹配到任何产物：{target!r}（数据出口白名单 {'/'.join(EGRESS_ROOTS)}）")
    return [_egress_rel(rel) for rel in found]


def _exit_code_for_lightrag(exc: Exception) -> int:
    """具名 LightRAG 错误 ⇒ 退出码（**不**让它们退化成 INTERNAL_ERROR 堆栈）。

    - 越界/用法、含 401/403 的非 2xx ⇒ ``EXIT_USAGE``（与 §12.1 的 ``UNAUTHENTICATED`` 同档）；
    - 归属校验拒绝（``LIGHTRAG_RETRACT_REFUSED``）⇒ ``EXIT_CONFLICT``（fail-closed 的**状态冲突**，
      与 `IDEMPOTENCY_CONFLICT` 同类：同 `file_source`、不同内容）；
    - 响应形状不符 / 不可达 / 流水线超时 ⇒ ``EXIT_INTERNAL``（**非重试语义的部署问题**）。
    """
    from ..infrastructure import lightrag_client as lc

    if isinstance(exc, lc.LightRagArtifactRefused):
        return EXIT_USAGE
    if isinstance(exc, lc.LightRagRetractRefused):
        return EXIT_CONFLICT
    if isinstance(exc, lc.LightRagHTTPError):
        return EXIT_USAGE
    return EXIT_INTERNAL


def _report_error(output: str, code: str, message: str) -> None:
    """具名错误出口：json ⇒ 统一信封（status=ERROR + errors[]）；text ⇒ **stderr** 一行。"""
    if output == "json":
        _emit(output, {"error_code": code, "message": message},
              status="ERROR", errors=[{"code": code, "message": message}])
    else:
        typer.echo(f"ERROR[{code}] {message}", err=True)


@contextmanager
def _named_errors(output: str):
    """把**具名**错误转成"统一信封 + 具名退出码"（fail-closed：不吞、不退化成裸堆栈）。

    两类都要处理（**退出码是运维面契约的一部分**）：

    - :class:`~kert.domain.errors.KERTException`（如 ``AssetNotFoundError`` 空匹配、越界）
      ⇒ 退出码复用 :func:`kert.cli.main._exit_code_for`（**与其余命令同一张映射表**，不分叉）；
    - :class:`~kert.infrastructure.lightrag_client.LightRagError` ⇒ 见
      :func:`_exit_code_for_lightrag`。
    """
    from ..domain.errors import KERTException
    from ..infrastructure.lightrag_client import LightRagError
    from .main import _exit_code_for

    try:
        yield
    except KERTException as exc:
        _report_error(output, exc.error_code, exc.message)
        raise typer.Exit(_exit_code_for(exc))
    except LightRagError as exc:
        _report_error(output, getattr(exc, "code", "LIGHTRAG_ERROR"), str(exc))
        raise typer.Exit(_exit_code_for_lightrag(exc))


@egress_app.command("status")
def status_cmd(
    artifact: str = typer.Argument(
        ..., help="工作区相对产物路径 / 目录 / glob（限 03_core|04_serve）"),
    workspace_path: Path = typer.Option(..., "--workspace", "-w", help="KERT 工作区"),
    output: str = typer.Option("text", "--output", help=_OUTPUT),
    as_json: bool = typer.Option(False, "--json", help="等价 --output json（统一信封）"),
):
    """查看**本地产物摘要 vs 实例上该出处的正文摘要**（missing / current / stale）。

    退出码：``0`` 全部 missing|current；``4`` 存在 ``stale``（实例与本地**已不一致**，
    脚本据此即可判定而无需解析文本）。
    """
    output = "json" if as_json else output
    ws = Path(workspace_path)
    svc = _service(ws)
    with _named_errors(output):
        targets = _expand_targets(ws, artifact)
        documents = _client().documents()      # 一次全量：避免逐产物做全表扫
        rows = [svc.egress_state(t, documents=documents) for t in targets]
    states = sorted({r["state"] for r in rows})
    data = {"workspace": str(ws), "count": len(rows), "states": states, "artifacts": rows}
    lines = [f"{r['artifact']}  [{r['state']}]  sha256={r['sha256'][:16]}…  "
             f"bytes={r['bytes']}  实例条目={len(r['documents'])}  "
             f"file_source={r['file_source']}" for r in rows]
    if "stale" in states:
        data["hint"] = STALE_ACTIONS_HINT
    if output == "json":
        _emit(output, data, human="\n".join(lines))
    else:
        typer.echo("\n".join(lines))
        typer.echo(f"合计 {len(rows)} 件；状态 {states}")
        if "stale" in states:
            typer.echo("存在 stale：实例上已有同出处但**摘要不同**的正文 ⇒ 知识库不是本地当前内容。\n"
                       + STALE_ACTIONS_HINT, err=True)
    if "stale" in states:
        raise typer.Exit(EXIT_CONFLICT)


@egress_app.command("publish")
def publish_cmd(
    artifact: str = typer.Argument(
        ..., help="工作区相对产物路径 / 目录 / glob（限 03_core|04_serve）"),
    workspace_path: Path = typer.Option(..., "--workspace", "-w", help="KERT 工作区"),
    refresh: bool = typer.Option(
        False, "--refresh",
        help="撤回→重发（撤回**仍受归属校验**：正文摘要与本地当前内容不符 ⇒ 拒绝且一份都不删）"),
    output: str = typer.Option("text", "--output", help=_OUTPUT),
    as_json: bool = typer.Option(False, "--json", help="等价 --output json（统一信封）"),
):
    """把工作区产物发布到外部实例（**默认安全**：同出处内容不同 ⇒ 具名 ``stale``，不静默成功）。

    退出码：``0`` published|current|refreshed；``4`` 存在 ``stale``（**未发布**）；
    ``4`` 归属校验拒绝（``--refresh``）；``2`` 越界/鉴权；``5`` 不可达/响应形状不符。
    """
    output = "json" if as_json else output
    ws = Path(workspace_path)
    svc = _service(ws)
    with _named_errors(output):
        targets = _expand_targets(ws, artifact)
        client = _client()
        rows = [svc.egress_publish(t, refresh=refresh, client=client) for t in targets]
    stale = [r["artifact"] for r in rows if r["state"] == "stale"]
    data = {"workspace": str(ws), "refresh": refresh, "count": len(rows),
            "stale": stale, "artifacts": rows}
    if stale:
        data["hint"] = STALE_ACTIONS_HINT
    lines = [f"{r['artifact']}  [{r['state']}]  status={r['status']}"
             f"  本地 sha256={r['sha256'][:16]}…"
             + (f"  已撤回 {len(r['removed'])} 条" if r.get("removed") else "")
             + f"  file_source={r['file_source']}" for r in rows]
    if output == "json":
        _emit(output, data, human="\n".join(lines))
    else:
        typer.echo("\n".join(lines))
        if stale:
            typer.echo("存在 stale（实例上同出处的正文摘要 != 本地当前摘要）⇒ **未发布**。\n"
                       + STALE_ACTIONS_HINT, err=True)
    if stale:
        raise typer.Exit(EXIT_CONFLICT)


@egress_app.command("retract")
def retract_cmd(
    artifact: str = typer.Argument(
        ..., help="工作区相对产物路径 / 目录 / glob（限 03_core|04_serve）"),
    workspace_path: Path = typer.Option(..., "--workspace", "-w", help="KERT 工作区"),
    force: bool = typer.Option(
        False, "--force",
        help="**显式**跳过归属校验（留痕 verified=false；确认来源已变/要清理时才用）"),
    timeout: float = typer.Option(180.0, "--timeout", help="等待撤回落地（异步）秒数"),
    output: str = typer.Option("text", "--output", help=_OUTPUT),
    as_json: bool = typer.Option(False, "--json", help="等价 --output json（统一信封）"),
):
    """撤回该产物在外部实例上的发布（**默认受归属校验**：摘要不符 ⇒ 拒绝且**一份都不删**）。

    退出码：``0`` 撤回或本就无可撤回；``4`` 归属校验拒绝（fail-closed）；``2`` 越界/鉴权。
    """
    output = "json" if as_json else output
    ws = Path(workspace_path)
    svc = _service(ws)
    with _named_errors(output):
        targets = _expand_targets(ws, artifact)
        client = _client()
        rows = [svc.retract_artifact(t, client=client, force=force, timeout=timeout)
                for t in targets]
    data = {"workspace": str(ws), "force": force, "count": len(rows), "artifacts": rows}
    lines = [f"{r['artifact']}  removed={len(r['removed'])}  verified={r['verified']}"
             f"  status={r['status']}" for r in rows]
    _emit(output, data, human="\n".join(lines))
