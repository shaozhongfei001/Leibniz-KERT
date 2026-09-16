"""数据出口运维面（M7 · ①）**真实例**用例：三态（不可达 / 可达未授权 / 可达已授权）各自断言。

纪律（照 ``tests/integration/test_lightrag_publication.py`` 顶部口径）：

1. **不 skip**：server 未启动 ⇒ 断言**具名** ``LightRagUnavailable``；server 在听但无/错凭据
   ⇒ 断言**具名** 401/403；可达且已授权 ⇒ 跑**真**流程（发布 → ``current`` → 改本地 ⇒ ``stale``
   → 默认发布**不写** → ``refresh`` **被归属校验拒绝** → 显式 ``force`` 撤回 → 稳定消失）；
2. **测试自持唯一出处标识**（``EGRESS-PROBE-<uuid8>.md`` + 测试自有 service_id）：
   实测教训（2026-09-16）——用真实产物名会**撞名**，收尾撤回会**误删真实文档**；
3. **收尾回测试前状态**：撤回自家探针并**连续 2 次读为空**才放行（删除异步且分阶段）。

⚠ CI 无常驻实例 ⇒ 本文件在 CI 上走"**具名不可达**"分支；**"CI 绿"不等于"E2E 已验"**。
带凭据 opt-in：
``KERT_LIGHTRAG_URL=… KERT_LIGHTRAG_API_KEY=… python -m pytest tests/integration/test_egress_ops_live.py -q``
"""

from __future__ import annotations

import hashlib
import time
import uuid

import pytest

from kert.application.services import (
    EGRESS_CURRENT,
    EGRESS_STALE,
    EGRESS_STATE_PUBLISHED,
    KnowledgeService,
    sha_marker,
)
from kert.infrastructure.lightrag_client import (
    LightRagClient,
    LightRagHTTPError,
    LightRagRetractRefused,
    LightRagUnavailable,
    artifact_file_source,
)

#: 测试自有的 service_id ⇒ 出处唯一 ⇒ 撤回只触及本测试的探针（不碰真实产物）
SERVICE_ID = "egress_live_probe"
ARTIFACT_DIR = f"04_serve/{SERVICE_ID}/version=2026.09.17.1"


def _probe_rel() -> str:
    return f"{ARTIFACT_DIR}/EGRESS-PROBE-{uuid.uuid4().hex[:8]}.md"


def _write(ws, rel: str, body: str) -> str:
    p = ws / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
    return rel


def _snapshot(ws) -> dict:
    return {p.relative_to(ws).as_posix(): p.read_bytes()
            for p in ws.rglob("*") if p.is_file()}


def _pre_clean(client: LightRagClient, source: str) -> None:
    """清掉上次异常退出可能残留的同标识条目（否则本次发布只会得到 ``already_published``）。"""
    stale = client.find_documents(source)
    if stale:
        ids = [d.doc_id for d in stale]
        client.delete_documents(ids)
        client.wait_until_absent(ids, timeout=120.0)


def _wait_processed(client: LightRagClient, source: str, timeout: float = 420.0) -> None:
    """等到该文档索引结束（``processed``/``failed``）；超时 ⇒ 红（不放过未落地的发布）。"""
    deadline = time.monotonic() + timeout
    while True:
        docs = client.find_documents(source)
        status = docs[0].status if docs else ""
        if status in ("processed", "failed"):
            assert status == "processed", f"索引失败：{docs[0]}"
            return
        assert time.monotonic() < deadline, (
            f"索引未在 {timeout:.0f}s 内完成（status={status!r}）")
        time.sleep(5.0)


def _assert_absent_stable(client: LightRagClient, source: str, *,
                          timeout: float = 60.0, interval: float = 2.0,
                          consecutive: int = 2) -> None:
    """删除是**异步且分阶段**的 ⇒ 要求**连续** ``consecutive`` 次读都为空才放行。"""
    deadline = time.monotonic() + timeout
    streak = 0
    while True:
        streak = streak + 1 if not client.find_documents(source) else 0
        if streak >= consecutive:
            return
        assert time.monotonic() < deadline, f"{timeout:.0f}s 内该条目未稳定消失（{source}）"
        time.sleep(interval)


class TestEgressOpsOnLiveInstance:
    def test_publish_status_stale_refresh_guard_then_force_retract(self, ws):
        """真实例全流程：发布 → current → stale（默认不写）→ refresh 拒绝 → force 撤回。

        环境三态**各自断言**（**不 skip**，口径同 ``test_lightrag_publication.py``）。
        """
        marker = f"EGRESSMARK{uuid.uuid4().hex[:8].upper()}"
        rel = _write(ws, _probe_rel(), body=(
            f"# 数据出口运维面探针\n实体 CUST-CORP-0001 的检索标记 {marker}。\n"))
        svc = KnowledgeService(ws, service_id=SERVICE_ID)
        client = LightRagClient.from_env()
        source = artifact_file_source(rel)

        if not client.available():
            # ① 不可达：**具名**错误（不返回"空状态"来假装成功）
            with pytest.raises(LightRagUnavailable) as ei:
                svc.egress_state(rel, client=client)
            assert ei.value.code == "LIGHTRAG_UNAVAILABLE"
            return
        try:
            # ② 可达但未授权：预清与发布**都**可能 401/403 ⇒ 在同一处断言
            _pre_clean(client, source)
            out = svc.egress_publish(rel, client=client)
        except LightRagHTTPError as exc:
            assert exc.code == "LIGHTRAG_HTTP_ERROR"
            assert any(s in str(exc) for s in ("401", "403")), (
                f"LightRAG 可达却非鉴权失败 ⇒ 接入口径可能变了，必须暴露: {exc}")
            return

        try:
            # ③ 可达已授权：真流程
            assert out["state"] == EGRESS_STATE_PUBLISHED, out
            _wait_processed(client, source)
            info = svc.egress_state(rel, client=client)
            assert info["state"] == EGRESS_CURRENT, info
            assert info["documents"][0]["marker_hit"] is True, info["documents"]

            # 本地内容变了 ⇒ **stale**（旧行为在这里回 already_published，看不到缺口）
            _write(ws, rel, (f"# 数据出口运维面探针\n实体 CUST-CORP-0001 的检索标记 {marker}。\n"
                             "**本地已更新**\n"))
            after_change = _snapshot(ws)
            stale = svc.egress_state(rel, client=client)
            assert stale["state"] == EGRESS_STALE, stale
            assert stale["sha256"] == hashlib.sha256((ws / rel).read_bytes()).hexdigest()

            # 默认发布：**不写不删**（具名 stale）
            doc_id_before = client.find_documents(source)[0].doc_id
            out2 = svc.egress_publish(rel, client=client)
            assert out2["state"] == EGRESS_STALE and out2["published"] is False, out2
            assert [d.doc_id for d in client.find_documents(source)] == [doc_id_before], (
                "stale 时**不得**改动实例")

            # `--refresh` 的撤回**仍受归属校验**（D-34）⇒ 具名拒绝、**一份都不删**
            with pytest.raises(LightRagRetractRefused) as ei:
                svc.egress_publish(rel, refresh=True, client=client)
            assert ei.value.code == "LIGHTRAG_RETRACT_REFUSED"
            assert [d.doc_id for d in client.find_documents(source)] == [doc_id_before], (
                "归属校验失败时**不得**删除任何文档（fail-closed）")

            # 显式 force 才是操作员的清理动作：撤回后**稳定消失**
            forced = svc.retract_artifact(rel, client=client, force=True)
            assert forced["verified"] is False and forced["removed"], forced
            _assert_absent_stable(client, source)
            assert _snapshot(ws) == after_change, "运维面命令**不得**改动工作区"
        finally:
            _pre_clean(client, source)   # 只清**自家探针**（唯一后缀）

    def test_marker_is_readable_in_instance_summary(self, ws):
        """判据可用性：发布后实例返回的 ``content_summary`` **确实**含我们自写的摘要行。

        这条是"判据唯一可用"的**实测**前提（ADR-017：无读正文端点、不支持自定义 metadata）：
        若实例改了摘要窗口/字段名，本用例会红 —— 那正是要暴露的接入口径变化。
        """
        rel = _write(ws, _probe_rel(), body="# 摘要窗口探针\n实体 CUST-CORP-0001。\n")
        svc = KnowledgeService(ws, service_id=SERVICE_ID)
        client = LightRagClient.from_env()
        source = artifact_file_source(rel)

        if not client.available():
            with pytest.raises(LightRagUnavailable):
                client.documents()
            return
        try:
            _pre_clean(client, source)
            out = svc.publish_artifact(rel, client=client)
        except LightRagHTTPError as exc:
            assert any(s in str(exc) for s in ("401", "403")), str(exc)
            return
        try:
            _wait_processed(client, source)
            docs = client.find_documents(source)
            assert len(docs) == 1, docs
            assert sha_marker(out["sha256"]) in (docs[0].content_summary or ""), (
                f"实例摘要窗口读不到摘要行 ⇒ 内容变更检测/归属校验失效：{docs[0].content_summary[:200]!r}")
        finally:
            svc.retract_artifact(rel, client=client, force=True)
            _assert_absent_stable(client, source)
