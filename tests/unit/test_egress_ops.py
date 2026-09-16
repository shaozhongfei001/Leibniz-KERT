"""数据出口**运维面**（M7 · ①）：`egress_state` / `egress_publish` 的**确定性**用例（零网络）。

短接方式 = **注入内存假实例**（走服务层既有 ``client=`` 注入缝），而不是"打桩断言"：
假实例只实现服务层真正用到的那几处客户端面（``documents`` / ``find_documents`` /
``publish_text`` / ``delete_documents`` / ``wait_until_*``），且 ``publish_text``
**忠实复刻"先查后写"**（同出处已存在 ⇒ 不写、回 ``already_published``）——
这样"未发写请求"的断言才有意义。

要证明的东西（对应用户可见行为）：

1. **内容变更检测**：实例上该出处的正文摘要 vs 本地**当前**摘要 ⇒ ``missing``/``current``/``stale``；
2. **两种状态不能混**：产物内容变了 ⇒ ``stale``（旧行为是回 ``already_published``，即
   "知识库永远停在旧内容"而调用方看不出来）；
3. **默认安全**：``stale`` 时 ``publish`` **不写不删**；``--refresh`` 的撤回**仍受归属校验**
   （D-34）⇒ 摘要不符时**具名拒绝、一份都不删**。← 本文件的**反例**都挂在这两条上。

约定（与仓内同族一致）：反例在各类 docstring 里显式标注「反例」，并在
``test_state_and_guard_agree`` 中把"判据与守卫**同口径**"钉成一条不变式。
"""

from __future__ import annotations

import hashlib

import pytest

from kert.application.services import (
    EGRESS_CURRENT,
    EGRESS_MISSING,
    EGRESS_STALE,
    EGRESS_STATE_PUBLISHED,
    EGRESS_STATE_REFRESHED,
    KnowledgeService,
    sha_marker,
)
from kert.domain.errors import AssetNotFoundError
from kert.infrastructure.lightrag_client import (
    ALREADY_PUBLISHED,
    PUBLISHED,
    LightRagArtifactRefused,
    LightRagDocument,
    LightRagPipelineTimeout,
    LightRagRetractRefused,
    PublishOutcome,
    artifact_file_source,
)

#: 数据出口白名单内的产物（测试专用 service/version ⇒ 出处唯一）
ARTIFACT_DIR = "04_serve/egress_probe/version=2026.09.17.1"
ARTIFACT = f"{ARTIFACT_DIR}/ONTOLOGY.md"
BODY = "# 本体物化产物\n实体 CUST-CORP-0001（华东精工装备集团有限公司）。\n"
#: 假实例的"正文头部窗口"宽度（真实例返回 content_summary，出处头必须落在窗口内）
WINDOW = 400


class _FakeInstance:
    """**内存假实例**：零网络、确定性；行为复刻 `LightRagClient` 的**先查后写**。"""

    def __init__(self, docs=()):
        self.docs = list(docs)
        self.published: list[tuple[str, str]] = []   # 真正发出去的写请求
        self.deleted: list[str] = []                 # 真正发生的删除

    # -- 读 --
    def documents(self, *, page_size: int = 200):
        return tuple(self.docs)

    def find_documents(self, file_source: str):
        return tuple(d for d in self.docs if d.file_path == file_source)

    def wait_until_present(self, file_source: str, *, timeout: float = 30.0,
                           interval: float = 1.0):
        found = self.find_documents(file_source)
        if not found:
            raise LightRagPipelineTimeout("fake：入库为异步，窗口内未可见")
        return found

    # -- 写 --
    def publish_text(self, text: str, *, file_source: str, visibility_timeout: float = 30.0):
        existing = self.find_documents(file_source)
        if existing:                       # 复刻真客户端的"先查后写"：同出处 ⇒ 不重复写入
            return PublishOutcome(file_source=file_source, status=ALREADY_PUBLISHED,
                                  track_id=existing[0].doc_id)
        self.published.append((file_source, text))
        self.docs.append(LightRagDocument(
            doc_id=f"doc-{len(self.docs) + 1}", file_path=file_source, status="processed",
            chunks_count=1, content_summary=text[:WINDOW]))
        return PublishOutcome(file_source=file_source, status=PUBLISHED, track_id="track-1")

    def delete_documents(self, doc_ids):
        ids = [str(i) for i in doc_ids if str(i)]
        self.deleted.extend(ids)
        self.docs = [d for d in self.docs if d.doc_id not in set(ids)]
        return {"status": "ok"}

    def wait_until_absent(self, doc_ids, *, timeout: float = 180.0, interval: float = 3.0):
        want = {str(i) for i in doc_ids if str(i)}
        if {d.doc_id for d in self.docs} & want:
            raise LightRagPipelineTimeout("fake：删除未落地")


def _write(ws, rel: str = ARTIFACT, body: str = BODY) -> str:
    p = ws / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
    return rel


def _digest(ws, rel: str = ARTIFACT) -> str:
    return hashlib.sha256((ws / rel).read_bytes()).hexdigest()


def _snapshot(ws) -> dict:
    return {p.relative_to(ws).as_posix(): p.read_bytes()
            for p in ws.rglob("*") if p.is_file()}


def _foreign_summary(rel: str) -> str:
    """**他人的合法文档**：出处头同形（同产物路径 + 同发布标识），**摘要不同**。"""
    return ("# KERT 产物出处（数据出口；登记见 ADR-017）\n"
            f"- sha256: {'0' * 64}\n"
            f"- 产物路径: {rel}\n"
            f"- 发布标识: {artifact_file_source(rel)}\n\n他人的正文…")


def _publish_own(ws, rel: str = ARTIFACT, body: str = BODY):
    """经**生产发布路径**灌入假实例 ⇒ content_summary 与生产同形（不手搓出处头）。"""
    inst = _FakeInstance()
    svc = KnowledgeService(ws)
    _write(ws, rel, body)
    out = svc.publish_artifact(rel, client=inst)
    assert out["status"] == PUBLISHED, out
    inst.published.clear()          # 只留"被断言的那次"写请求（seed 不算）
    return svc, inst


# --------------------------------------------------------------------------- #
# 内容变更检测（状态分类）
# --------------------------------------------------------------------------- #

class TestEgressState:
    def test_missing_when_instance_has_none(self, ws):
        """实例上没有该出处 ⇒ ``missing``；摘要/字节数取自**本地产物**（人能看到判据）。"""
        rel = _write(ws)
        info = KnowledgeService(ws).egress_state(rel, documents=())
        assert info["state"] == EGRESS_MISSING
        assert info["sha256"] == _digest(ws) and info["bytes"] == len(BODY.encode("utf-8"))
        assert info["file_source"] == artifact_file_source(rel)
        assert info["documents"] == []

    def test_current_after_own_publication(self, ws):
        """经生产路径发布 ⇒ ``current``，且**摘要行确实落在实例返回的摘要窗口内**。"""
        svc, inst = _publish_own(ws)
        info = svc.egress_state(ARTIFACT, documents=inst.documents())
        assert info["state"] == EGRESS_CURRENT
        assert len(info["documents"]) == 1 and info["documents"][0]["marker_hit"] is True
        assert sha_marker(info["sha256"]) in inst.docs[0].content_summary

    def test_stale_after_local_content_changes(self, ws):
        """**功能缺口的核心反例**：本地内容变了 ⇒ ``stale``（不是"已发布、没事"）。

        「反例」：把判据改回"只看同出处**存在与否**"⇒ 本条必红（会得到 ``current``）。
        """
        svc, inst = _publish_own(ws)
        _write(ws, ARTIFACT, BODY + "\n**本地已更新**\n")
        info = svc.egress_state(ARTIFACT, documents=inst.documents())
        assert info["state"] == EGRESS_STALE
        assert info["sha256"] == _digest(ws) != ""
        assert info["documents"][0]["marker_hit"] is False

    def test_stale_when_any_duplicate_entry_is_foreign(self, ws):
        """同出处下有**多条**（含 `dup-*` / 他人残留）⇒ **全部**摘要一致才算 ``current``。

        「反例」：把 ``all(...)`` 改成 ``any(...)`` ⇒ 本条必红（一条命中就误判 current，
        而带校验的撤回会拒绝 ⇒ "能撤回却不 current"的第二态，正是要避免的）。
        """
        svc, inst = _publish_own(ws)
        inst.docs.append(LightRagDocument(
            doc_id="doc-foreign", file_path=artifact_file_source(ARTIFACT),
            status="processed", chunks_count=1, content_summary=_foreign_summary(ARTIFACT)))
        info = svc.egress_state(ARTIFACT, documents=inst.documents())
        assert info["state"] == EGRESS_STALE
        assert [d["marker_hit"] for d in info["documents"]] == [True, False]

    def test_local_artifact_missing_is_named(self, ws):
        """本地产物不存在 ⇒ 具名 :class:`AssetNotFoundError`（**无从比对**，不静默回状态）。"""
        with pytest.raises(AssetNotFoundError):
            KnowledgeService(ws).egress_state(ARTIFACT, documents=())

    def test_outside_egress_root_refused(self, ws):
        """白名单外（`02_work`/`90_control`/绝对路径/`..`）⇒ 具名拒绝（同发布面，不分叉）。"""
        for bad in ("02_work/draft.md", "90_control/schema/x.json", "/etc/hosts", "../out.md"):
            with pytest.raises(LightRagArtifactRefused) as ei:
                KnowledgeService(ws).egress_state(bad, documents=())
            assert ei.value.code == "LIGHTRAG_ARTIFACT_REFUSED"

    def test_state_and_guard_agree(self, ws):
        """**不变式**：``current`` ⟺ 带校验的撤回可放行；``stale`` ⟺ 撤回必被拒。

        这条把"判据"与"守卫"钉成**同一条**：不存在"status 说 current、撤回却被拒"的第三态
        （D-34 的机械表达）。
        """
        svc, inst = _publish_own(ws)
        assert svc.egress_state(ARTIFACT, documents=inst.documents())["state"] == EGRESS_CURRENT
        assert svc.retract_artifact(ARTIFACT, client=inst)["removed"] == ["doc-1"]

        svc2, inst2 = _publish_own(ws)                     # 重新发布一份
        _write(ws, ARTIFACT, BODY + "\n**已改动**\n")      # 本地内容变了 ⇒ stale
        assert svc2.egress_state(ARTIFACT, documents=inst2.documents())["state"] == EGRESS_STALE
        with pytest.raises(LightRagRetractRefused):
            svc2.retract_artifact(ARTIFACT, client=inst2)
        assert inst2.deleted == []


# --------------------------------------------------------------------------- #
# 发布（默认安全）与 --refresh（守卫不放宽）
# --------------------------------------------------------------------------- #

class TestEgressPublish:
    def test_missing_publishes_with_marker_near_top(self, ws):
        """``missing`` ⇒ 发布；**摘要行必须靠前**（长路径会把摘要挤出窗口 ⇒ 守卫恒失效，D-34）。"""
        rel = _write(ws)
        inst = _FakeInstance()
        out = KnowledgeService(ws).egress_publish(rel, client=inst)
        assert out["state"] == EGRESS_STATE_PUBLISHED and out["published"] is True
        assert out["status"] == PUBLISHED and out["prior_state"] == EGRESS_MISSING
        assert len(inst.published) == 1
        head = inst.published[0][1].splitlines()[:2]
        assert head[1] == sha_marker(out["sha256"])

    def test_current_is_idempotent_and_sends_no_write(self, ws):
        """``current`` ⇒ ``already_published`` 且**一个写请求都不发**（幂等，不制造副本）。"""
        svc, inst = _publish_own(ws)
        out = svc.egress_publish(ARTIFACT, client=inst)
        assert out["state"] == EGRESS_CURRENT and out["status"] == ALREADY_PUBLISHED
        assert out["published"] is False and inst.published == []
        assert len(inst.docs) == 1

    def test_stale_is_named_and_writes_nothing(self, ws):
        """``stale`` ⇒ **具名** ``stale``、不写不删（旧行为在这里回 ``already_published``）。

        「反例」：把"比较摘要"改回"只看同出处存在与否"⇒ 本条必红（会回 already_published/published）。
        """
        svc, inst = _publish_own(ws)
        _write(ws, ARTIFACT, BODY + "\n**本地已更新**\n")
        before = _snapshot(ws)
        summary_before = inst.docs[0].content_summary

        out = svc.egress_publish(ARTIFACT, client=inst)
        assert out["state"] == EGRESS_STALE and out["status"] == EGRESS_STALE
        assert out["published"] is False and out["prior_state"] == EGRESS_STALE
        assert inst.published == [] and inst.deleted == [], "stale 默认必须**不写不删**"
        assert inst.docs[0].content_summary == summary_before
        assert _snapshot(ws) == before, "运维面命令**不得**改动工作区"

    def test_refresh_on_stale_refuses_and_deletes_nothing(self, ws):
        """**D-34 反例**：``--refresh`` **不是**绕过归属校验的开关 ⇒ 摘要不符时拒绝且一份都不删。

        「反例」：把 ``refresh`` 的撤回改成 ``force=True`` ⇒ 本条必红
        （会删掉"不是本工作区当前内容"的文档，正是本轮事故要防的事）。
        """
        svc, inst = _publish_own(ws)
        _write(ws, ARTIFACT, BODY + "\n**本地已更新**\n")
        with pytest.raises(LightRagRetractRefused) as ei:
            svc.egress_publish(ARTIFACT, refresh=True, client=inst)
        assert ei.value.code == "LIGHTRAG_RETRACT_REFUSED"
        assert inst.deleted == [], "归属校验失败 ⇒ **不得**调用删除（fail-closed）"
        assert inst.published == [], "拒绝后**不得**继续发布"
        assert len(inst.docs) == 1

    def test_refresh_on_current_retracts_then_republishes(self, ws):
        """``current`` + ``refresh`` ⇒ 撤回（校验**通过**）+ 重发（`state=refreshed`）。"""
        svc, inst = _publish_own(ws)
        out = svc.egress_publish(ARTIFACT, refresh=True, client=inst)
        assert out["state"] == EGRESS_STATE_REFRESHED and out["published"] is True
        assert out["removed"] == ["doc-1"] and inst.deleted == ["doc-1"]
        assert len(inst.published) == 1 and len(inst.docs) == 1

    def test_refresh_on_missing_is_plain_publish(self, ws):
        """``missing`` + ``refresh`` ⇒ 没有可撤回的东西，**不误报** refreshed。"""
        rel = _write(ws)
        inst = _FakeInstance()
        out = KnowledgeService(ws).egress_publish(rel, refresh=True, client=inst)
        assert out["state"] == EGRESS_STATE_PUBLISHED
        assert out["removed"] == [] and inst.deleted == []

    def test_publish_is_read_only_on_workspace(self, ws):
        """三条路径（missing / current / stale）都**逐字节**不动工作区（ADR-017 ⑥ 的机械断言）。"""
        rel = _write(ws)
        inst = _FakeInstance()
        svc = KnowledgeService(ws)
        before = _snapshot(ws)
        svc.egress_publish(rel, client=inst)
        assert _snapshot(ws) == before
        svc.egress_publish(rel, client=inst)                  # current
        assert _snapshot(ws) == before
        _write(ws, rel, BODY + "\n**本地已更新**\n")
        after_change = _snapshot(ws)
        svc.egress_publish(rel, client=inst)                  # stale
        assert _snapshot(ws) == after_change
