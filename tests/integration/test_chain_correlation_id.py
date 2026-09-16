"""⑧ **全链关联 ID**：一次业务动作（计划 → 物化 → 发布 → 检索）能被**同一个 id** 串起来查。

要证明的东西（机械断言，不靠"看着像"）：

1. **四处同名同值**：同一对既有字段名 ``planId``/``planHash`` 在
   ① 计划（`ActivationPlan.to_dict`）② 物化返回与 `PLAN_LINEAGE.json` ③ 发布结果与**实例侧出处头**
   ④ 检索引用的出处条目 —— **逐处相等**（不是"各自一套 id 恰好相似"）；
2. **经既有端点取回该链**：`GET /v1/evidence/{object_id}`（**未新增路径/未改规格**）在
   ``object_id`` 命中计划身份时返回该链（计划层 + 物化层 + 数据出口锚点），
   且两个身份（``planId`` 与 ``planHash``）都能取到**同一条链**；
3. **反例（防空转）**：
   - 未知 id ⇒ **不**返回链（`complete=False` + `blocker`）⇒ 证明匹配不是恒真；
   - 无计划血缘的产物（`03_core` 资产）⇒ 发布结果与出处头**都不出现**链 ID（**不伪造占位**）；
   - 血缘坏掉（缺 `planId`）⇒ 具名 `UsageError`（**ID 不得静默消失**）；
   - 引用 `filePath` 不可回译（如被实例名规范化吃掉目录）⇒ 引用**不出现**链 ID（**不瞎猜**）。

边界（**不外推**）：发布/检索的**状态**不在本地留痕（数据出口只读工作区，ADR-017 ⑥）⇒
本文件断言的是与发布结果、检索引用**同名同值**的**锚点**（`file_source`），不是"已发布/已检索到"。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from kert.application.extract import KnowledgeExtractor
from kert.application.ingest import Ingestor
from kert.application.parse_doc import DocumentParserService
from kert.application.provision import provision_control_plane
from kert.application.publish import Publisher
from kert.application.review import ReviewService
from kert.application.services import (
    PLAN_HASH_KEY,
    PLAN_ID_KEY,
    KnowledgeService,
    plan_identity_for_artifact,
    sha_marker,
)
from kert.domain.activation_plan import ActivationPlanBuilder
from kert.domain.errors import UsageError
from kert.infrastructure.lightrag_client import (
    ALREADY_PUBLISHED,
    PUBLISHED,
    LightRagCitation,
    LightRagDocument,
    LightRagResult,
    PublishOutcome,
    artifact_file_source,
)
from kert.api.server import create_app

REPO = Path(__file__).resolve().parents[2]
CONTROL_PLANE_SRC = REPO / "examples" / "bank-front-knowledge-maps"
#: 测试自有 service_id（避免与真实投影/真实发布标识撞名）
SERVICE_ID = "chain_id_probe"
TASK_TYPE = "OUTREACH_PREPARATION"
DOMAIN = "product"
SUBJECT_ID = "CUST-CORP-0001"


@pytest.fixture
def ws_chain(ws, tmp_path):
    """链的起点：控制面（路由策略 + 地图 + 本体引用声明）＋ 一个已发布 Core 版本。"""
    provision_control_plane(ws, CONTROL_PLANE_SRC)
    md = tmp_path / "p.md"
    md.write_text(
        "# 政策\n\n## 产品\n\n产品A利率为3.5%。\n\n产品B利率为4.2%。\n\n"
        "产品A需要材料M1。\n\n规则：利率不超过10。\n",
        encoding="utf-8",
    )
    r = Ingestor(ws).ingest("product", [md], "batch-chain-id-1")
    pr = DocumentParserService(ws).parse("product", r.batch_id)
    ex = KnowledgeExtractor(ws).extract("product", r.batch_id, run_id=pr.run_id)
    ReviewService(ws).review("product", run_id=pr.run_id,
                             object_refs=[c["path"] for c in ex.candidates],
                             decision="APPROVE", reason="ok", decided_by="r")
    Publisher(ws).publish("product", run_id=pr.run_id)
    return ws


class _CaptureInstance:
    """只够 `publish_artifact` 用的**内存假实例**（零网络；记录正文供断言出处头）。"""

    def __init__(self):
        self.docs: list[LightRagDocument] = []
        self.texts: list[tuple[str, str]] = []

    def find_documents(self, file_source: str):
        return tuple(d for d in self.docs if d.file_path == file_source)

    def publish_text(self, text: str, *, file_source: str, visibility_timeout: float = 30.0):
        exist = self.find_documents(file_source)
        if exist:
            return PublishOutcome(file_source=file_source, status=ALREADY_PUBLISHED,
                                  track_id=exist[0].doc_id)
        self.texts.append((file_source, text))
        self.docs.append(LightRagDocument(
            doc_id=f"doc-{len(self.docs) + 1}", file_path=file_source, status="processed",
            chunks_count=1, content_summary=text[:400]))
        return PublishOutcome(file_source=file_source, status=PUBLISHED, track_id="track-1")


class _CitationStub:
    """检索 stub：按给定 `filePath` 造引用（**不触网**；用于断言引用侧的链 ID）。"""

    def __init__(self, file_paths):
        self.file_paths = list(file_paths)

    def query_data(self, query: str, *, mode: str = "hybrid") -> LightRagResult:
        return LightRagResult(
            query=query, mode=mode, endpoint="/query/data", entities=(), relations=(),
            citations=tuple(
                LightRagCitation(reference_id=f"ref-{i}", file_path=p, content="出处正文…")
                for i, p in enumerate(self.file_paths)))


def _plan_and_materialize(ws):
    builder = ActivationPlanBuilder.load(ws)
    plan = builder.build(TASK_TYPE, subject_id=SUBJECT_ID)
    assert plan.allowed, f"计划未放行（{plan.code}）：{plan.reason}"
    svc = KnowledgeService(ws, service_id=SERVICE_ID)
    out = svc.materialize_from_plan(TASK_TYPE, domain=DOMAIN, subject_id=SUBJECT_ID)
    return svc, plan.to_dict(), out


class TestSameChainIdAcrossFourPoints:
    def test_plan_lineage_publish_and_citation_share_one_id(self, ws_chain):
        ws = ws_chain
        svc, plan_doc, out = _plan_and_materialize(ws)
        plan_id, plan_hash = plan_doc[PLAN_ID_KEY], plan_doc[PLAN_HASH_KEY]

        # ① 计划 ↔ ② 物化返回
        assert out[PLAN_ID_KEY] == plan_id and out[PLAN_HASH_KEY] == plan_hash, out
        # ② 物化血缘（= plan.to_dict() 照抄）与取 ID 入口（发布/检索两侧都走它）
        lineage = json.loads((ws / out["lineage_path"]).read_text(encoding="utf-8"))
        assert lineage[PLAN_ID_KEY] == plan_id and lineage[PLAN_HASH_KEY] == plan_hash
        rel = f"04_serve/{SERVICE_ID}/version={out['projection_version']}/PROJECTION.md"
        assert (ws / rel).is_file()
        assert plan_identity_for_artifact(ws, rel)[PLAN_ID_KEY] == plan_id

        # ③ 发布结果（假实例；零网络）+ 实例侧出处头
        inst = _CaptureInstance()
        pub = svc.publish_artifact(rel, client=inst)
        assert pub[PLAN_ID_KEY] == plan_id and pub[PLAN_HASH_KEY] == plan_hash, pub
        text = inst.texts[0][1]
        assert f"- 计划标识: {plan_id}" in text and f"- 计划哈希: {plan_hash}" in text
        # D-34 判据不被挤走：摘要行**仍是第 2 行**
        assert text.splitlines()[1] == sha_marker(pub["sha256"])

        # ④ 检索引用的出处条目（stub client；filePath = 发布标识）
        ret = svc.retrieve_via_lightrag(
            "本体物化产物 客户画像", client=_CitationStub([pub["file_source"]]))
        cit = ret["citations"][0]
        assert cit["artifact"] == rel
        assert cit[PLAN_ID_KEY] == plan_id and cit[PLAN_HASH_KEY] == plan_hash, cit

        # ⑤ 经**既有端点**取回该链（未新增路径/未改规格）
        api = TestClient(create_app(ws, service_id=SERVICE_ID))
        for identity in (plan_id, plan_hash):
            body = api.get(f"/v1/evidence/{identity}")
            assert body.status_code == 200, body.text
            data = body.json()["data"]
            assert data["object_id"] == identity and data["complete"] is True, data
            assert data["chain"][0]["layer"] == "plan"
            assert data["chain"][0][PLAN_ID_KEY] == plan_id
            assert data["chain"][0][PLAN_HASH_KEY] == plan_hash
            assert any(e["layer"] == "04_serve/egress" for e in data["chain"])
            anchor = next(e for e in data["chain"]
                          if e.get("file_source") == pub["file_source"])
            assert anchor["artifact"] == rel and anchor["sha256"] == pub["sha256"]


class TestChainIdCounterexamples:
    def test_unknown_identity_returns_no_chain(self, ws_chain):
        """反例（防空转）：**链确实存在时**，未知 id ⇒ **不**返回链 ⇒ 证明匹配不是恒真。"""
        _plan_and_materialize(ws_chain)          # 先造出真实链（否则"取不到"可能只是空工作区）
        api = TestClient(create_app(ws_chain, service_id=SERVICE_ID))
        body = api.get("/v1/evidence/AP-KERT-OUTREACH_PREPARATION-DEADBEEF")
        assert body.status_code == 200, body.text
        data = body.json()["data"]
        assert data["complete"] is False and data.get("blocker"), data
        assert not any(e.get("layer") == "plan" for e in data["chain"]), data["chain"]

    def test_artifact_without_lineage_carries_no_id(self, ws_chain):
        """反例（**不伪造占位**）：`03_core` 资产无计划血缘 ⇒ 发布结果与出处头都不出现链 ID。"""
        ws = ws_chain
        rel = "03_core/product/version=2026.09.17.1/entities/E-CORE-1.md"
        (ws / rel).parent.mkdir(parents=True, exist_ok=True)
        (ws / rel).write_text("# 实体 E-CORE-1\n", encoding="utf-8")
        assert plan_identity_for_artifact(ws, rel) is None

        inst = _CaptureInstance()
        pub = KnowledgeService(ws, service_id=SERVICE_ID).publish_artifact(rel, client=inst)
        assert PLAN_ID_KEY not in pub and PLAN_HASH_KEY not in pub, pub
        assert "计划标识" not in inst.texts[0][1]

    def test_broken_lineage_is_named_not_silent(self, ws_chain):
        """反例（fail-closed）：血缘缺 `planId` ⇒ **具名** `UsageError`（ID 不得静默消失）。"""
        ws = ws_chain
        _svc, _plan, out = _plan_and_materialize(ws)
        p = ws / out["lineage_path"]
        doc = json.loads(p.read_text(encoding="utf-8"))
        doc.pop(PLAN_ID_KEY)
        p.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        rel = f"04_serve/{SERVICE_ID}/version={out['projection_version']}/PROJECTION.md"
        with pytest.raises(UsageError) as ei:
            plan_identity_for_artifact(ws, rel)
        assert PLAN_ID_KEY in str(ei.value), ei.value

    def test_unresolvable_citation_path_carries_no_id(self, ws_chain):
        """反例（**不瞎猜**）：引用 `filePath` 不可回译（被规范化成 basename）⇒ 引用不带链 ID。"""
        ws = ws_chain
        svc, plan_doc, out = _plan_and_materialize(ws)
        ret = svc.retrieve_via_lightrag("x", client=_CitationStub(["ONTOLOGY.md"]))
        cit = ret["citations"][0]
        assert cit["filePath"] == "ONTOLOGY.md"
        assert "artifact" not in cit and PLAN_ID_KEY not in cit, cit
        # 反空转：同一次检索里可回译的引用**确实**带上了链 ID
        rel = f"04_serve/{SERVICE_ID}/version={out['projection_version']}/PROJECTION.md"
        ret2 = svc.retrieve_via_lightrag("x", client=_CitationStub([artifact_file_source(rel)]))
        assert ret2["citations"][0][PLAN_ID_KEY] == plan_doc[PLAN_ID_KEY]
        assert PLAN_HASH_KEY in ret2["citations"][0]
