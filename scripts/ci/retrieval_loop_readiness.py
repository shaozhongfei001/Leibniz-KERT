#!/usr/bin/env python3
"""检索环**就绪 + 真往返**闸门（CI job 步骤，跑在 pytest **之前**）。

**为什么必须有这一步（防假绿）**：`tests/integration/test_lightrag_publication.py`、
`test_lightrag_retrieval.py`、`test_six_ring_chain_end_to_end.py` 按 ADR-017 ⑦-a 的口径设计成
"**实例不可达 ⇒ 断言具名错误**"⇒ 实例挂掉/起不来时这些用例**照样会绿**。
⇒ 必须有**一道不可绕过**的闸门证明实例真的在、真的能写、真的能被检索到出处、真的能撤回。

判据（全部机械；任一步失败 ⇒ 打印 ``::error::`` 并 **exit 1**，绝不静默）：

1. 实例可达（``available()`` ⇒ ``/health``）；不可达 ⇒ ``LIGHTRAG_UNAVAILABLE``；
2. 文档面可读（``documents()`` 不抛）⇒ 未授权/鉴权错由 ``LIGHTRAG_HTTP_ERROR`` 具名暴露；
3. 发布本工作区一件**本次唯一**的探针产物 ⇒ ``status == published``（先查后写若命中残留会暴露）；
4. 该出处**可见**（入库异步）且索引态 `processed`（超时 ⇒ 具名）；
5. **检索能命中本次发布的出处**（引用 ``filePath`` 回指 ``file_source``）⇒ 打印实际命中集；
6. **撤回**（`force=False`，即**带归属校验**）⇒ ``removed`` 非空，且该出处持续不可见。

末行输出机读标记：``RETRIEVAL_LOOP_READY publish=1 retrieve=1 retract=1``（供 job 断言引用）。

用法：``python scripts/ci/retrieval_loop_readiness.py --workspace <dir>``（连接参数走 env：
``KERT_LIGHTRAG_URL`` / ``KERT_LIGHTRAG_API_KEY``）。
"""

from __future__ import annotations

import argparse
import sys
import time
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from kert.application.services import KnowledgeService           # noqa: E402
from kert.domain.errors import KERTException                     # noqa: E402
from kert.domain.workspace import init_workspace                  # noqa: E402
from kert.infrastructure.lightrag_client import (                 # noqa: E402
    LightRagClient,
    LightRagError,
)

SERVICE_ID = "ci_retrieval_probe"
#: 检索模式（都走 lightrag 既有取值域；任一命中即算"可检索"）
MODES = ("hybrid", "mix", "naive")


def _log(msg: str) -> None:
    print(msg, flush=True)


def _wait_processed(client: LightRagClient, source: str, timeout: float = 300.0) -> str:
    """等索引结束（`processed`/`failed`）；超时 ⇒ 具名失败。"""
    deadline = time.monotonic() + timeout
    while True:
        docs = client.find_documents(source)
        status = docs[0].status if docs else ""
        if status in ("processed", "failed"):
            return status
        if time.monotonic() >= deadline:
            raise TimeoutError(f"索引未在 {timeout:.0f}s 内完成（status={status!r}，source={source}）")
        time.sleep(2.0)


def _citation_sources(client, query: str) -> set:
    """多模式检索，取引用出处集合（引用 `filePath` 即发布标识）。"""
    out: set = set()
    for mode in MODES:
        result = client.query_data(query, mode=mode)
        for c in result.citations:
            out.add(c.file_path)
    return out


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="检索环就绪 + 真往返闸门（fail-closed）")
    ap.add_argument("--workspace", required=True, help="KERT 工作区（不存在则就地初始化）")
    args = ap.parse_args(argv[1:])

    ws = Path(args.workspace)
    if not (ws / ".kert_workspace").is_file():
        ws.mkdir(parents=True, exist_ok=True)
        init_workspace(ws)
        _log(f"[readiness] 已初始化工作区：{ws}")

    client = LightRagClient.from_env()
    _log(f"[readiness] 实例地址 = {client.base_url}（凭据：{'有' if client.api_key else '无'}）")
    if not client.available():
        _log("::error::[LIGHTRAG_UNAVAILABLE] 实例不可达 ⇒ 检索环**未**被验证（拒绝静默通过）")
        return 1
    docs = client.documents()                      # 401/403 ⇒ 具名异常
    _log(f"[readiness] 实例当前文档数 = {len(docs)}（文档面可读 ⇒ 凭据有效）")

    marker = f"CIMARK{uuid.uuid4().hex[:8].upper()}"
    rel = f"04_serve/{SERVICE_ID}/version=ci.{time.strftime('%Y%m%d')}/CI-PROBE-{uuid.uuid4().hex[:8]}.md"
    path = ws / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"# 检索环 CI 探针\n\n对公客户最近的融资需求：客户 CUST-CORP-0001 流动资金贷款。\n"
        f"检索标记 {marker}。\n", encoding="utf-8")

    svc = KnowledgeService(ws, service_id=SERVICE_ID)
    published = svc.publish_artifact(rel, client=client)
    source = published["file_source"]
    _log(f"[readiness] ① 发布：status={published['status']} file_source={source} "
         f"sha256={published['sha256'][:16]}…")
    if published["status"] != "published":
        _log("::error::[READINESS_PUBLISH_NOT_EFFECTIVE] 本次发布未真正写入"
             f"（status={published['status']}）⇒ 实例上可能存在同出处残留")
        return 1

    try:
        status = _wait_processed(client, source)
        _log(f"[readiness] ② 索引：status={status}")
        if status != "processed":
            _log(f"::error::[READINESS_INDEX_FAILED] 索引未完成：status={status}")
            return 1

        hits = _citation_sources(client, f"融资需求 {marker} CUST-CORP-0001")
        _log(f"[readiness] ③ 检索：命中出处集合 = {sorted(hits)}")
        if source not in hits:
            _log("::error::[READINESS_NOT_RETRIEVABLE] 检索未命中本次发布出处"
                 "（出处回指失效）⇒ 检索环**未**被验证")
            return 1
    finally:
        removed = svc.retract_artifact(rel, client=client)
        ids = list(removed.get("removed") or [])
        _log(f"[readiness] ④ 撤回（带归属校验）：verified={removed['verified']} "
             f"removed={len(ids)} 条")
        if not ids:
            _log("::error::[READINESS_RETRACT_EMPTY] 撤回未见任何条目（发布或撤回失效）")
            return 1
        client.wait_until_absent(ids, timeout=180.0)
        left = client.find_documents(source)
        _log(f"[readiness] ⑤ 撤回后残留 = {len(left)} 条")
        if left:
            _log("::error::[READINESS_RETRACT_RESIDUAL] 撤回后仍有残留")
            return 1

    _log("RETRIEVAL_LOOP_READY publish=1 retrieve=1 retract=1")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv))
    except KERTException as exc:                   # 领域错误：具名
        print(f"::error::[{exc.error_code}] {exc.message}", flush=True)
        raise SystemExit(1) from exc
    except (LightRagError, TimeoutError) as exc:   # 接入口径/超时：具名
        print(f"::error::[{getattr(exc, 'code', 'READINESS_TIMEOUT')}] {exc}", flush=True)
        raise SystemExit(1) from exc
