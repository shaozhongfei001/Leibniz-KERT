"""P-1 数据出口：把 KERT 产物发布到外部 LightRAG，并断言**可检索 / 出处回指 / 幂等 / 可撤回**。

纪律（TL P-1 硬要求）：**禁 skip**；环境的**三种分支都要被断言**（缺一格就会漏掉一类真实故障）：

1. **不可达**（server 未启动）⇒ 具名 `LightRagUnavailable`（确定性由 `DEAD_URL`＝端口 9 覆盖）；
2. **可达但未授权**（server 在听、无/错 `KERT_LIGHTRAG_API_KEY`）⇒ 具名 `LightRagHTTPError`
   （**断言 401/403**）。⚠ **这一格曾漏**：预清调用被放在受保护 `try` **之外** ⇒ 无凭据环境下
   它以**未捕获 401** 把用例红掉（m71 实测报障，2026-09-16；抛点 `lightrag_client.py:201`）；
3. **可达且已授权** ⇒ 真发布 → 等索引 → 检索命中（**出处回指产物路径**）→ 幂等 → 撤回 → **连续两次读为空**。
"""

from __future__ import annotations

import hashlib
import time
import uuid

import pytest

from kert.application.services import KnowledgeService
from kert.domain.errors import AssetNotFoundError
from kert.infrastructure.lightrag_client import (
    ALREADY_PUBLISHED,
    LightRagArtifactRefused,
    LightRagClient,
    LightRagDocument,
    LightRagHTTPError,
    LightRagRetractRefused,
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
        try:
            # 预清 + 发布**都**可能因「可达但**未授权**」(401/403) 抛具名 `LightRagHTTPError`
            # ⇒ 二者必须在**同一处**被断言。曾把 `_pre_clean` 放在 try **之外** ⇒
            # 无凭据环境下它以**未捕获异常**把用例红掉（m71 实测报障，2026-09-16；抛点
            # `lightrag_client.py:201` 的 `/documents/paginated`）⇒ 这才是"未授权"分支的漏网。
            _pre_clean(client, artifact_file_source(rel))   # 清掉上次异常退出可能残留的同标识条目
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


# --------------------------------------------------------------------------- #
# D-34：撤回前的**归属校验**（默认开启；`force=True` 才可跳过）
#
# 事故背景（2026-09-16 实测）：`file_source` 由**确定性规则**派生，与"谁发布的"无关
# ⇒ 撞名时按出处撤回会删掉**他人的合法文档**（实例 docs 5→4、图 78/86→61/62）。
# 下列前三格**不触网**（短接客户端三处调用）⇒ 在任何环境都确定性可跑；末格为真实例分支。
# --------------------------------------------------------------------------- #

def _own_summary(rel: str, digest: str) -> str:
    """模拟我们发布时写入的**出处头**（`sha256` 在首行之后，故落在摘要窗口内）。"""
    return ("# KERT 产物出处（数据出口；登记见 ADR-017）\n"
            f"- sha256: {digest}\n"
            f"- 产物路径: {rel}\n"
            f"- 发布标识: {artifact_file_source(rel)}\n\n正文…")


def _foreign_summary(rel: str) -> str:
    return _own_summary(rel, "0" * 64)


def _stub_client(monkeypatch, rows, deleted: list) -> None:
    """短接客户端网络调用；`deleted` 记录被删的 doc id ⇒ 用于断言 fail-closed。"""
    monkeypatch.setattr(LightRagClient, "find_documents", lambda self, s: tuple(rows))
    monkeypatch.setattr(LightRagClient, "delete_documents",
                        lambda self, ids: (deleted.extend(ids), {"status": "ok"})[1])
    monkeypatch.setattr(LightRagClient, "wait_until_absent",
                        lambda self, ids, timeout=0.0: None)


class TestRetractOwnershipGuard:
    def test_refuses_when_instance_content_is_not_ours(self, monkeypatch, ws):
        """实例上那份的出处头摘要 ≠ 本工作区当前摘要 ⇒ **拒绝**，且**一个 doc 都不删**。"""
        rel = _write_artifact(ws, _probe_rel())
        deleted: list = []
        _stub_client(monkeypatch, [LightRagDocument(
            doc_id="doc-foreign", file_path=artifact_file_source(rel), status="processed",
            content_summary=_foreign_summary(rel))], deleted)

        with pytest.raises(LightRagRetractRefused) as ei:
            KnowledgeService(ws).retract_artifact(
                rel, client=LightRagClient(base_url=DEAD_URL, api_key="x", timeout=1.0))
        assert ei.value.code == "LIGHTRAG_RETRACT_REFUSED"
        assert "doc-foreign" in str(ei.value), ei.value
        assert deleted == [], "归属校验失败时**不得**调用删除（fail-closed）"

    def test_refuses_when_local_artifact_missing(self, monkeypatch, ws):
        """本地产物不存在 ⇒ 无从比对 ⇒ **拒绝**（要清理必须显式 `force=True`）。"""
        rel = _probe_rel()                       # 刻意不落盘
        deleted: list = []
        _stub_client(monkeypatch, [], deleted)
        with pytest.raises(LightRagRetractRefused) as ei:
            KnowledgeService(ws).retract_artifact(
                rel, client=LightRagClient(base_url=DEAD_URL, api_key="x", timeout=1.0))
        assert "本地产物不存在" in str(ei.value)
        assert deleted == []

    def test_allows_and_stamps_verified_when_content_matches(self, monkeypatch, ws):
        """摘要与本地当前内容一致 ⇒ 放行，且返回值标注 `verified=True` + 摘要。"""
        rel = _write_artifact(ws, _probe_rel())
        digest = hashlib.sha256((ws / rel).read_bytes()).hexdigest()
        deleted: list = []
        _stub_client(monkeypatch, [LightRagDocument(
            doc_id="doc-ok", file_path=artifact_file_source(rel), status="processed",
            content_summary=_own_summary(rel, digest))], deleted)

        res = KnowledgeService(ws).retract_artifact(
            rel, client=LightRagClient(base_url=DEAD_URL, api_key="x", timeout=1.0))
        assert res["verified"] is True and res["sha256"] == digest
        assert res["removed"] == ["doc-ok"] and deleted == ["doc-ok"]

    def test_force_skips_verification_and_leaves_trace(self, monkeypatch, ws):
        """`force=True` ⇒ 跳过校验但**留痕**（`verified=False`），绝不静默。"""
        rel = _write_artifact(ws, _probe_rel())
        deleted: list = []
        _stub_client(monkeypatch, [LightRagDocument(
            doc_id="doc-foreign", file_path=artifact_file_source(rel), status="processed",
            content_summary=_foreign_summary(rel))], deleted)

        res = KnowledgeService(ws).retract_artifact(
            rel, client=LightRagClient(base_url=DEAD_URL, api_key="x", timeout=1.0), force=True)
        assert res["verified"] is False and res["removed"] == ["doc-foreign"]
        assert res["sha256"] == "" and deleted == ["doc-foreign"]


class TestRetractGuardOnLiveInstance:
    def test_changed_local_content_refuses_then_force_retracts(self, ws):
        """真实例：发布后**改动本地产物** ⇒ 撤回被拒且**一份不删**；`force=True` 才放行并清干净。

        环境三态各自断言（**不 skip**）：不可达 / 可达未授权 / 可达已授权（同本文件顶部纪律）。
        """
        marker = f"GUARD{uuid.uuid4().hex[:8].upper()}"
        rel = _write_artifact(ws, _probe_rel(), body=f"# 归属校验探针 {marker}\n")
        svc = KnowledgeService(ws)
        client = LightRagClient.from_env()
        source = artifact_file_source(rel)

        if not client.available():
            with pytest.raises(LightRagUnavailable):
                svc.retract_artifact(rel, client=client)
            return
        try:
            _pre_clean(client, source)
            svc.publish_artifact(rel, client=client)
        except LightRagHTTPError as exc:
            assert exc.code == "LIGHTRAG_HTTP_ERROR"
            assert any(s in str(exc) for s in ("401", "403")), (
                f"LightRAG 可达却非鉴权失败 ⇒ 接入口径可能变了: {exc}")
            return

        try:
            _wait_processed(client, source)
            # 关键动作：**发布之后**改动本地产物 ⇒ 实例上那份的摘要不再等于当前摘要
            (ws / rel).write_text(f"# 归属校验探针 {marker}\n\n**本地已改动**\n", encoding="utf-8")
            with pytest.raises(LightRagRetractRefused) as ei:
                svc.retract_artifact(rel, client=client, visibility_timeout=5.0)
            assert ei.value.code == "LIGHTRAG_RETRACT_REFUSED"
            assert client.find_documents(source), "拒绝时**不得**删除任何文档（fail-closed）"
            forced = svc.retract_artifact(rel, client=client, force=True)
            assert forced["verified"] is False and forced["removed"], forced
            _assert_absent_stable(client, source)
        finally:
            _pre_clean(client, source)   # 本测试**自有**探针的收尾（唯一后缀 ⇒ 不触及他人文档）
