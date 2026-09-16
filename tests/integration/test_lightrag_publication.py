"""P-1 数据出口：把 KERT 产物发布到外部 LightRAG，并断言**可检索 / 出处回指 / 幂等 / 可撤回**。

纪律（TL P-1 硬要求）：**禁 skip**。server 不在或未授权时，走**具名错误**分支并断言
（`LightRagUnavailable` / `LightRagHTTPError`），不会静默变绿。
"""

from __future__ import annotations

import time
import uuid

import pytest

from kert.application.services import KnowledgeService
from kert.domain.errors import AssetNotFoundError
from kert.infrastructure.lightrag_client import (
    ALREADY_PUBLISHED,
    LightRagArtifactRefused,
    LightRagClient,
    LightRagHTTPError,
    LightRagUnavailable,
    artifact_file_source,
    parse_artifact_file_source,
)

#: 确定性的"不可用"地址：保留端口 9（discard），本机无监听服务。
DEAD_URL = "http://127.0.0.1:9"
#: 数据出口白名单内的**目录**；测试专用产物名建在此处（见 `_probe_rel`）
ARTIFACT_DIR = "04_serve/product_knowledge/version=2026.09.16.1"
#: 纯函数（出处标识往返）用例用的路径 —— **不参与任何 HTTP**
ARTIFACT = f"{ARTIFACT_DIR}/ONTOLOGY.md"
SOURCE = "04_serve__product_knowledge__version=2026.09.16.1__ONTOLOGY.md"


def _probe_rel() -> str:
    """**测试专用**产物名（带唯一后缀）—— **绝不占用真实产物标识**。

    **实测教训（2026-09-16 清空-重建轮）**：曾直接用真实名 `…/ONTOLOGY.md` ⇒ 与重建语料中的
    真实文档**撞名** ⇒ ① "先查后写"**正确地**返回 `already_published`（原断言写死 `published` ⇒ 红）；
    ② `finally` 里的撤回**删掉了真实文档**（实例由 78/86 掉到 61/62）。
    ⇒ 测试必须自持**唯一**标识，撤回也只能触及自己的探针。
    """
    return f"{ARTIFACT_DIR}/P1-PROBE-{uuid.uuid4().hex[:8]}.md"


def _pre_clean(client: LightRagClient, file_source: str) -> None:
    """清掉**上次异常退出**可能残留的同标识条目（否则本次发布只会得到 `already_published`）。"""
    stale = client.find_documents(file_source)
    if stale:
        ids = [d.doc_id for d in stale]
        client.delete_documents(ids)
        client.wait_until_absent(ids, timeout=120.0)


def _assert_absent_stable(client: LightRagClient, file_source: str, *,
                          timeout: float = 60.0, interval: float = 2.0,
                          consecutive: int = 2) -> None:
    """断言该出处标识**持续**消失（不赌"某一次读恰好为空"）。

    删除是**异步且分阶段**的（先状态、后 chunks/向量/图），且不同读时机会看到不同状态
    ⇒ TL 2026-09-16 实测：在测试**运行/收尾附近**读库会看到 `P1-PROBE-*.md`（当时 6 条）。
    故本断言要求**连续 `consecutive` 次**读都为空才放行；超时 ⇒ **红**（不让"短暂残留"混过）。
    """
    deadline = time.monotonic() + timeout
    streak = 0
    while True:
        streak = streak + 1 if not client.find_documents(file_source) else 0
        if streak >= consecutive:
            return
        assert time.monotonic() < deadline, (
            f"{timeout:.0f}s 内该条目未稳定消失（{file_source}）")
        time.sleep(interval)


def _write_artifact(ws, rel: str, body: str = "") -> str:
    path = ws / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body or "# 本体物化产物\n实体 CUST-CORP-0001。\n", encoding="utf-8")
    return rel


def _snapshot(ws) -> dict:
    return {p.relative_to(ws).as_posix(): p.read_bytes()
            for p in ws.rglob("*") if p.is_file()}


def _wait_processed(client: LightRagClient, file_source: str, timeout: float = 420.0) -> None:
    """等到该文档索引结束（`processed` / `failed`）；超时 ⇒ **红**（不放过未落地的发布）。"""
    deadline = time.monotonic() + timeout
    while True:
        docs = client.find_documents(file_source)
        status = docs[0].status if docs else ""
        if status in ("processed", "failed"):
            assert status == "processed", f"索引失败：{docs[0]}"
            return
        assert time.monotonic() < deadline, (
            f"索引未在 {timeout:.0f}s 内完成（status={status!r}）")
        time.sleep(5.0)


def _citation_paths(client: LightRagClient, query: str) -> set:
    """用多种**既有**模式检索，取引用出处集合（任一模式命中即算可检索）。"""
    paths: set[str] = set()
    for mode in ("mix", "naive", "hybrid"):
        for c in client.query_data(query, mode=mode).citations:
            paths.add(c.file_path)
    return paths


class TestEgressBoundary:
    def test_outside_egress_roots_refused(self, ws):
        """白名单外（`02_work/**`、`90_control/**`、绝对路径、`..`）⇒ **具名拒绝**。"""
        svc = KnowledgeService(ws)
        for bad in ("02_work/draft.md", "90_control/schema/x.json",
                    "01_raw/source.txt", "/etc/hosts", "../out.md"):
            with pytest.raises(LightRagArtifactRefused) as ei:
                svc.publish_artifact(bad)
            assert ei.value.code == "LIGHTRAG_ARTIFACT_REFUSED"
            with pytest.raises(LightRagArtifactRefused):
                svc.retract_artifact(bad)

    def test_missing_artifact_is_named(self, ws):
        """白名单内但文件不存在 ⇒ 具名 `AssetNotFoundError`（不是静默成功）。"""
        svc = KnowledgeService(ws)
        with pytest.raises(AssetNotFoundError):
            svc.publish_artifact("03_core/customer/version=2026.09.16.1/none.md")

    def test_source_roundtrip_and_guard(self):
        """出处标识必须**可回译**（检索命中的 filePath 才能回指产物路径 + 版本）。"""
        assert artifact_file_source(ARTIFACT) == SOURCE
        assert parse_artifact_file_source(SOURCE) == ARTIFACT
        # 纯函数只判"可回译"：段内含分隔符 / 绝对路径 / `..` / 空 ⇒ 拒绝；
        # 单段相对名（`x.md`）本身可回译，**根白名单**是服务层 `_egress_rel` 的职责（上方已断言）。
        assert artifact_file_source("x.md") == "x.md"
        for bad in ("04_serve/a__b/ONTOLOGY.md", "/abs/x.md", "04_serve/../x.md", ""):
            with pytest.raises(LightRagArtifactRefused):
                artifact_file_source(bad)


class TestPublishFailuresAreNamed:
    def test_dead_endpoint_publish_and_retract(self, ws):
        """不可达 ⇒ 发布与撤回**都**抛具名 `LightRagUnavailable`（不返回空、不 skip）。"""
        client = LightRagClient(base_url=DEAD_URL, api_key="x", timeout=1.0)
        rel = _write_artifact(ws, _probe_rel())
        svc = KnowledgeService(ws)
        with pytest.raises(LightRagUnavailable) as ei:
            svc.publish_artifact(rel, client=client)
        assert ei.value.code == "LIGHTRAG_UNAVAILABLE"
        with pytest.raises(LightRagUnavailable):
            svc.retract_artifact(rel, client=client)

    def test_server_409_maps_to_already_published(self, monkeypatch):
        """服务端 409（同 file_source 已存在）⇒ **幂等** `already_published`，不是失败。"""
        client = LightRagClient(base_url="http://127.0.0.1:9621", api_key="x", timeout=1.0)
        monkeypatch.setattr(LightRagClient, "find_documents", lambda self, s: ())

        def _boom(*_a, **_k):
            raise LightRagHTTPError(
                "LightRAG 返回 409（http://x/documents/text）："
                "{\"detail\":\"Document storage already contains 'a.md' "
                "(Status: processed). Delete the existing record before re-inserting.\"}")

        monkeypatch.setattr(LightRagClient, "_request", _boom)
        out = client.publish_text("t", file_source="04_serve__a__b.md")
        assert out.status == ALREADY_PUBLISHED

    def test_same_source_is_not_rewritten(self, monkeypatch, ws):
        """**先查后写**：同 file_source 已有记录 ⇒ 返回 `already_published` 且**不发写请求**。"""
        client = LightRagClient(base_url=DEAD_URL, api_key="x", timeout=1.0)
        monkeypatch.setattr(
            LightRagClient, "find_documents",
            lambda self, s: (type("D", (), {"doc_id": "doc-x", "file_path": s,
                                            "status": "processed"}),))
        out = client.publish_text("t", file_source="04_serve__a__b.md")
        assert out.status == ALREADY_PUBLISHED          # 未触及网络（DEAD_URL 也照样返回）
        rel = _write_artifact(ws, _probe_rel())
        svc = KnowledgeService(ws)
        assert svc.publish_artifact(rel, client=client)["status"] == ALREADY_PUBLISHED


class TestPublishedIsRetrievableAndRetractable:
    def test_publish_retrieve_provenance_then_retract(self, ws):
        """端到端：发布 ⇒ **检索命中且出处回指产物路径** ⇒ 重复发布无副本 ⇒ 撤回后消失。

        server 不可达 / 可达但未授权 ⇒ 走**具名错误**分支并断言（**不 skip**）。
        """
        marker = f"P1MARK{uuid.uuid4().hex[:8].upper()}"
        rel = _write_artifact(ws, _probe_rel(), body=(
            f"# 本体物化产物（样例）\n"
            f"实体 CUST-CORP-0001（华东精工装备集团有限公司）的客户画像与供应链融资偏好。\n"
            f"本体物化检索标记 {marker}。\n"))
        svc = KnowledgeService(ws)
        client = LightRagClient.from_env()
        before = _snapshot(ws)

        if not client.available():
            with pytest.raises(LightRagUnavailable):
                svc.publish_artifact(rel, client=client)
            return
        _pre_clean(client, artifact_file_source(rel))   # 清掉上次异常退出可能残留的同标识条目
        try:
            out = svc.publish_artifact(rel, client=client)
        except LightRagHTTPError as exc:
            assert exc.code == "LIGHTRAG_HTTP_ERROR"
            assert any(s in str(exc) for s in ("401", "403")), (
                f"LightRAG 可达却非鉴权失败 ⇒ 接入口径可能变了，必须暴露: {exc}")
            return

        try:
            assert out["status"] == "published", out
            assert out["file_source"] == artifact_file_source(rel)
            assert out["endpoint"] == "/documents/text"
            assert _snapshot(ws) == before, "发布**不得**改动工作区（只读）"
            again = svc.publish_artifact(rel, client=client)
            assert again["status"] == ALREADY_PUBLISHED, again
            _wait_processed(client, out["file_source"])
            docs = client.find_documents(out["file_source"])
            assert len(docs) == 1, f"重复发布产生了副本：{docs}"
            hits = _citation_paths(client, f"本体物化产物 {marker} CUST-CORP-0001")
            assert hits, f"发布后检索不到标记 {marker}（发布/索引未生效）"
            assert out["file_source"] in hits, (
                f"检索命中但出处未回指 KERT 产物路径：{sorted(hits)}")
        finally:
            res = svc.retract_artifact(rel, client=client)
            assert isinstance(res["removed"], list) and res["removed"], res
            _assert_absent_stable(client, out["file_source"])
            assert _snapshot(ws) == before, "撤回**不得**改动工作区"
