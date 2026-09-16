"""B① LightRAG 检索接入：**真检索** 与 **具名失败** 两个方向都断言（禁 skip 成假绿）。

- 用例 1（环境无关、确定性）：指向**未监听端口** ⇒ 必须抛**具名** `LightRagUnavailable`；
- 用例 2（对**配置的** server）：可达 ⇒ 真检索（断言结构与**出处非空**）；不可达 ⇒ 断言具名错误。
  两个分支都是**断言**，没有任何 `skip`。
"""

from __future__ import annotations

import pytest

from kert.application.services import KnowledgeService
from kert.infrastructure.lightrag_client import (
    LightRagClient,
    LightRagError,
    LightRagHTTPError,
    LightRagUnavailable,
)

#: 确定性的"不可用"地址：保留端口 9（discard），本机无监听服务。
DEAD_URL = "http://127.0.0.1:9"


class TestUnavailableIsNamedAndFailClosed:
    def test_dead_endpoint_raises_named_unavailable(self):
        """确定性反例：不可达 ⇒ 具名 `LightRagUnavailable`（**不是**空结果、**不是** skip）。"""
        client = LightRagClient(base_url=DEAD_URL, api_key="x", timeout=1.0)
        assert client.available() is False
        with pytest.raises(LightRagUnavailable) as ei:
            client.query_data("客户最近的融资需求", mode="hybrid")
        assert ei.value.code == "LIGHTRAG_UNAVAILABLE"
        assert DEAD_URL in str(ei.value)

    def test_illegal_mode_is_named_error(self):
        """口径：非法 mode ⇒ 具名错误（不自造模式）。"""
        client = LightRagClient(base_url=DEAD_URL, api_key="x", timeout=1.0)
        with pytest.raises(LightRagError) as ei:
            client.query_data("x", mode="not-a-mode")
        assert ei.value.code == "LIGHTRAG_ERROR"

    def test_service_method_propagates_named_error(self, ws):
        """服务方法**不吞错**：不可达经 `retrieve_via_lightrag` 仍抛具名错误。"""
        client = LightRagClient(base_url=DEAD_URL, api_key="x", timeout=1.0)
        svc = KnowledgeService(ws, service_id="product_knowledge")
        with pytest.raises(LightRagUnavailable):
            svc.retrieve_via_lightrag("客户最近的融资需求", client=client)


class TestConfiguredServer:
    def test_real_retrieval_or_named_error(self, ws):
        """对**配置的** server：可达 ⇒ 真检索（结构 + 出处非空）；不可达 ⇒ 具名错误。

        两分支都断言 ⇒ 不会出现"环境不在就静默变绿"。
        """
        client = LightRagClient.from_env()
        svc = KnowledgeService(ws, service_id="product_knowledge")

        if not client.available():
            with pytest.raises(LightRagUnavailable):
                svc.retrieve_via_lightrag("客户最近的融资需求", client=client)
            return

        try:
            out = svc.retrieve_via_lightrag("客户最近的融资需求", mode="hybrid", client=client)
        except LightRagHTTPError as exc:
            # 可达但**凭据未配置/被拒** ⇒ 仍是**具名**错误（不是空结果、不是 skip）；
            # 但**端点/口径变化（404/405）不得被吞** —— 那种情况必须让用例红。
            assert exc.code == "LIGHTRAG_HTTP_ERROR"
            assert any(s in str(exc) for s in ("401", "403")), (
                f"LightRAG 可达却非鉴权失败 ⇒ 接入口径可能变了，必须暴露: {exc}")
            return
        # 结构
        assert out["mode"] == "hybrid"
        assert out["endpoint"] == "/query/data"
        for key in ("query", "entities", "relations", "citations"):
            assert key in out
        assert isinstance(out["entities"], list)
        assert isinstance(out["relations"], list)
        # 真检索：至少要有**证据**（出处）或实体/关系之一非空
        assert out["citations"] or out["entities"] or out["relations"], (
            f"LightRAG 可达但返回全空（{client.base_url}）——需核对其库内容/模式: {out}")
        # 出处结构
        for c in out["citations"]:
            assert "referenceId" in c and "filePath" in c

    def test_retrieval_never_writes_workspace(self, ws):
        """ADR-017 判据①（「不是事实源」的机械证据）：**无论可达与否**，检索零写入工作区。

        两分支都断言（无 skip）：可达 ⇒ 真检索后工作区不变；不可达/未授权 ⇒ 具名错误后工作区同样不变。
        （非 `LightRagError` 的异常会直接让用例红，不被吞。）
        """

        def _snapshot():
            return {p.relative_to(ws).as_posix(): p.read_bytes()
                    for p in ws.rglob("*") if p.is_file()}

        before = _snapshot()
        svc = KnowledgeService(ws, service_id="product_knowledge")
        try:
            svc.retrieve_via_lightrag("客户最近的融资需求",
                                      client=LightRagClient.from_env())
        except LightRagError:
            pass  # 具名性由上方用例断言；本用例只断言"零写入"
        assert _snapshot() == before
