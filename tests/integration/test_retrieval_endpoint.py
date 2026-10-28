"""PC8 · CR-5：LightRAG **派生检索出口** ``POST /v1/retrieval/query``。

两条分支各自**独立可机械证明**（口径与 ADR-017 ⑦-a 一致）：

1. **实例不可达** ⇒ **具名** ``LIGHTRAG_UNAVAILABLE``（HTTP 503）—— 本仓红线：
   **禁止**用「空结果 + 200」冒充成功（调用方必须能区分「检索不到」与「检索不可达」）；
2. **实例可达** ⇒ 200，响应含 ``evidenceClass`` / ``simulationOnly``，且出处**可回译**
   （``chunkId`` 取自 lightRAG ``referenceId``；``docId``/``artifact`` 可回译到 KERT 产物路径）。

⚠ **防假绿（显式声明）**：分支 2 在实例不可达时 **skip 并打印原因** —— 真实往返
（发布 → 索引 → 检索命中出处 → 撤回）由 CI ``retrieval-loop-e2e`` job 的
``scripts/ci/retrieval_loop_readiness.py`` **不可绕过地**证明；本用例**不假装**验过实例。
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from kert.api.server import create_app
from kert.infrastructure.lightrag_client import (
    API_KEY_ENV,
    URL_ENV,
    LightRagArtifactRefused,
    parse_artifact_file_source,
)

REPO = Path(__file__).resolve().parents[2]
#: 保留端口（IANA discard）：连接必然失败 ⇒ 稳定的「不可达」反例。
DEAD_URL = "http://127.0.0.1:9"
ENDPOINT = "/v1/retrieval/query"
PAYLOAD = {"request_id": "it-retrieval-1", "query": "流动资金贷款 融资需求", "mode": "hybrid"}


def _client(ws, monkeypatch, url: str, api_key: str = "it-key") -> TestClient:
    monkeypatch.setenv(URL_ENV, url)
    monkeypatch.setenv(API_KEY_ENV, api_key)
    return TestClient(create_app(ws, skill_packages=REPO / "examples" / "bank-front-skills"))


def _reachable(url: str) -> bool:
    try:
        urllib.request.urlopen(f"{url.rstrip('/')}/health", timeout=2).read()
        return True
    except (urllib.error.URLError, OSError):
        return False


def test_unavailable_instance_is_named_not_empty(ws, monkeypatch):
    """分支 1：实例不可达 ⇒ 具名 ``LIGHTRAG_UNAVAILABLE``，**且不得**是 200 空结果。"""
    client = _client(ws, monkeypatch, DEAD_URL)
    resp = client.post(ENDPOINT, json=PAYLOAD)

    assert resp.status_code == 503, resp.text
    err = resp.json()["detail"]["error"]
    assert err["code"] == "LIGHTRAG_UNAVAILABLE", err
    assert err["retryable"] is True
    # 红线：不可达绝不伪装成成功
    assert resp.status_code != 200


def test_available_instance_returns_derived_citations(ws, monkeypatch):
    """分支 2：实例可达 ⇒ 200 + 派生层标识 + 可回译出处（回译不出血缘时**省略**键，不伪造）。"""
    import os

    url = os.environ.get(URL_ENV)
    if not url or not _reachable(url):
        pytest.skip(f"LightRAG 实例不可达（{url or URL_ENV + ' 未设置'}）⇒ 分支 2 未验；"
                    "真实往返由 CI retrieval-loop-e2e job 兜底证明")

    client = _client(ws, monkeypatch, url, api_key=os.environ.get(API_KEY_ENV, "it-key"))
    resp = client.post(ENDPOINT, json=PAYLOAD)
    assert resp.status_code == 200, resp.text

    data = resp.json()["data"]
    assert data["evidenceClass"] == "DERIVED_RETRIEVAL"
    # provenanceState / simulationOnly **同源派生**（CR-5 边界 5：不得取自检索、不得字面量）⇒
    # 由出处回译到的产物 `provenanceState` **独立复算**（不由被测函数提供，避免同义反复）。
    states = []
    for c in data["citations"]:
        try:
            rel = parse_artifact_file_source(c["docId"])
        except LightRagArtifactRefused:
            continue
        art = ws / rel
        if art.is_file():
            state = json.loads(art.read_text(encoding="utf-8")).get("provenanceState")
            if isinstance(state, str) and state.strip().upper() in ("VERIFIED", "DEMO"):
                states.append(state.strip().upper())
    expected_state = "DEMO" if (not states or "DEMO" in states) else "VERIFIED"
    assert data["provenanceState"] == expected_state, data["citations"]
    assert data["simulationOnly"] is (expected_state == "DEMO")
    assert set(data) >= {"query", "mode", "endpoint", "entities", "relations", "citations"}
    for c in data["citations"]:
        assert c["chunkId"], "出处必须带 chunkId（lightRAG referenceId）"
        assert c["docId"], "出处必须带 docId（可回译的产物标识）"


def test_existing_endpoints_untouched(ws, monkeypatch):
    """CR-5 边界：**纯新增** —— 既有端点路由仍在（不改语义、不改路径）。"""
    client = _client(ws, monkeypatch, DEAD_URL)
    paths = {r.path for r in client.app.routes if hasattr(r, "path")}
    for p in ("/v1/search", "/v1/data/query", "/v1/entities/{entity_id}",
              "/v1/evidence/{object_id}", "/v1/graph/query"):
        assert p in paths, f"既有端点缺失：{p}"
    assert ENDPOINT in paths
