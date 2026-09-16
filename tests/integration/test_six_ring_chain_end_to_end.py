"""T-CHAIN：**六环贯通**端到端（同一条链、同一次物化）。

链路（按顺序断言，全部落在**同一条链**上）：

1. **知识地图/路由 → 计划放行**：控制面供给 `route_policy` / 知识地图 / 本体引用声明 ⇒
   `ActivationPlanBuilder` 产出**已放行**的激活计划（未放行 ⇒ 后续全部 fail-closed）；
2. **`materialize_from_plan` → 产物出现且图库可查**：`04_serve/<svc>/version=<v>/` 的 Parquet 族
   + `PROJECTION.md`，Kùzu 图已建并经服务 API 命中节点；
3. **血缘的 5 键 `ontology` 子块**：键集 == `LINEAGE_ONTOLOGY_FIELDS`，值取自
   `ActivationPlanBuilder.load(ws).ontology_resolution()`，且 `check_lineage_ontology` 判**放行**；
4. **本体侧真解析结果进入该次物化**：`ontology_parse` 真解析 OWL+SHACL 的类/属性/形状结果经
   `ontology_materialize.materialize_ontology` 落到**同一 version 目录**，且其血缘的
   `contentSha256` 与环 3 的血缘**同值**（证明"同一条链"，不是另起一套）；
5. **lightRAG：发布本次 KERT 产物 → 检索到含出处（citation）的结果 → 索引可由 KERT 产物重建**
   （撤回 ⇒ 条目消失 ⇒ 重发同一产物 ⇒ **同一出处集合**恢复）；
6. **反向断言**：**篡改血缘里的哈希 ⇒ 拒绝**（`LINEAGE_ONTOLOGY_REF_MISMATCH`，不是告警）。

纪律（ADR-017 ⑦-a）：

- **不加 marker、不 skip**：环 5 的三种环境**各自断言对应分支**（不可达 ⇒ 具名 `LightRagUnavailable`；
  可达未授权 ⇒ 具名 401/403；可达已授权 ⇒ 真发布/检索/重建）；
- ⚠ **CI 无常驻 LightRAG 实例** ⇒ 环 5 在 CI 上走"**具名不可达**"分支 ⇒ **真正的 E2E（发布/检索/重建）
  不在 CI 被执行，故"CI 绿 ≠ E2E 已验"**；带凭据 opt-in：
  `KERT_LIGHTRAG_URL=… KERT_LIGHTRAG_API_KEY=… python -m pytest tests/integration/test_six_ring_chain_end_to_end.py -q`；
- **不新增依赖**（仅用仓内既有模块 + pytest/pyarrow/kuzu/httpx 经由既有路径）。

⚠ **与 ADR ⑧ 的边界（本测试不越界）**：环 5 的"重建"在**文档级**证明（撤回 ⇒ 重发 ⇒ 出处集合一致），
**不执行全库清空-重建** —— 后者是**操作员程序**（含 `cp -a` 备份与 `diff -r` 保真核对，见 ADR ⑧），
不应由测试对共享实例自动执行。全库重建的实测（`662/784 → 734/861 → 662/784`）已在 ADR ⑧ 登记。
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from kert.application.extract import KnowledgeExtractor
from kert.application.ingest import Ingestor
from kert.application.ontology_materialize import materialize_ontology
from kert.application.parse_doc import DocumentParserService
from kert.application.provision import provision_control_plane
from kert.application.publish import Publisher
from kert.application.review import ReviewService
from kert.application.services import KnowledgeService

REPO = Path(__file__).resolve().parents[2]
CONTROL_PLANE_SRC = REPO / "examples" / "bank-front-knowledge-maps"
ONTOLOGY_SRC = CONTROL_PLANE_SRC / "90_control" / "ontology"
#: ⚠ **测试自带的 service_id**（不是 `product_knowledge`）：发布标识由产物路径派生，若用真实
#: service_id，`04_serve/<svc>/version=<v>/ONTOLOGY.md` 会与实例里既有的真实产物**撞名**
#: ⇒ "先查后写"会命中真实文档，而测试收尾的 `retract_artifact` 会**误删它**（实测教训：2026-09-16，
#: 本轮首次运行把实例上真实的 `04_serve__product_knowledge__…__ONTOLOGY.md` 删掉、图 78/86→61/62）。
#: 用测试自有 id ⇒ 出处唯一 ⇒ 撤回只触及本测试的探针。
SERVICE_ID = "chain_probe"
TASK_TYPE = "OUTREACH_PREPARATION"
DOMAIN = "product"
SUBJECT_ID = "CUST-CORP-0001"


@pytest.fixture
def ws_chain(ws, tmp_path):
    """六环链的起点：控制面（路由策略 + 地图 + 本体引用声明）＋ 一个已发布 Core 版本。"""
    provision_control_plane(ws, CONTROL_PLANE_SRC)
    md = tmp_path / "p.md"
    md.write_text(
        "# 政策\n\n## 产品\n\n产品A利率为3.5%。\n\n产品B利率为4.2%。\n\n"
        "产品A需要材料M1。\n\n规则：利率不超过10。\n",
        encoding="utf-8",
    )
    r = Ingestor(ws).ingest("product", [md], "batch-chain-1")
    pr = DocumentParserService(ws).parse("product", r.batch_id)
    ex = KnowledgeExtractor(ws).extract("product", r.batch_id, run_id=pr.run_id)
    ReviewService(ws).review("product", run_id=pr.run_id,
                             object_refs=[c["path"] for c in ex.candidates],
                             decision="APPROVE", reason="ok", decided_by="r")
    Publisher(ws).publish("product", run_id=pr.run_id)
    return ws


def _version_dir(ws, version: str) -> Path:
    return ws / "04_serve" / SERVICE_ID / f"version={version}"


def _wait_processed(client, file_source: str, timeout: float = 420.0) -> str:
    """等到该文档索引结束（`processed`/`failed`）；超时 ⇒ 红（不放过未落地的发布）。"""
    deadline = time.monotonic() + timeout
    while True:
        docs = client.find_documents(file_source)
        status = docs[0].status if docs else ""
        if status in ("processed", "failed"):
            assert status == "processed", f"索引失败：{docs[0]}"
            return status
        assert time.monotonic() < deadline, (
            f"索引未在 {timeout:.0f}s 内完成（status={status!r}）")
        time.sleep(3.0)


def _citation_paths(client, query: str) -> set:
    """用多种**既有**模式检索，取引用出处集合（任一模式命中即算可检索）。"""
    paths: set = set()
    for mode in ("mix", "naive", "hybrid"):
        for c in client.query_data(query, mode=mode).citations:
            paths.add(c.file_path)
    return paths


class TestSixRingChain:
    def test_rings_1_to_5_same_chain_then_counterexample(self, ws_chain):
        """环 1→5 顺序断言（同一条链），环 6 反向断言见下一条用例（篡改会使产物失效，故分列）。"""
        ws = ws_chain
        svc = KnowledgeService(ws, service_id=SERVICE_ID)

        # ── 环 1：计划放行（路由策略 / 计划门禁）────────────────────────────
        from kert.domain.activation_plan import ActivationPlanBuilder

        builder = ActivationPlanBuilder.load(ws)
        plan = builder.build(TASK_TYPE, subject_id=SUBJECT_ID)
        assert plan.allowed, f"计划未放行（{plan.code}）：{plan.reason}"
        assert plan.to_dict()["planId"].startswith(f"AP-KERT-{TASK_TYPE}-")
        print("[环1] 计划放行：", plan.to_dict()["planId"])

        # ── 环 2：计划驱动物化 → 产物 + 图库可查 ───────────────────────────
        out = svc.materialize_from_plan(TASK_TYPE, domain=DOMAIN, subject_id=SUBJECT_ID)
        vdir = _version_dir(ws, out["projection_version"])
        for name in ("entities.parquet", "relations.parquet", "statements.parquet",
                     "segments.parquet", "rules.parquet", "PROJECTION.md"):
            assert (vdir / name).is_file(), f"环2 缺少产物：{name}"
        from kert.infrastructure.graph.kuzu_builder import KuzuGraphBuilder

        kb = KuzuGraphBuilder(ws, service_id=SERVICE_ID)
        assert kb.graph_available() is True, "环2：Kùzu 图未建"
        import kuzu

        con = kuzu.Connection(kuzu.Database(str(kb.graph_path())))
        assert con.execute("MATCH (c:Company) RETURN count(c)").get_next()[0] >= 1
        start = pq.read_table(vdir / "entities.parquet").column("entity_id")[0].as_py()
        g = svc.graph(start_entity_ids=[start], direction="BOTH", mode="neighbor")
        assert g.data["node_count"] >= 1, "环2：图查询未命中"
        print("[环2] 物化版本 =", out["projection_version"], "| 产物数 =", len(out["files"]))

        # ── 环 3：血缘 5 键 ontology 子块 + 校验放行 ────────────────────────
        from kert.domain.ontology_reference import (
            LINEAGE_ONTOLOGY_FIELDS,
            check_lineage_ontology,
        )

        lineage = json.loads((ws / out["lineage_path"]).read_text(encoding="utf-8"))
        block = lineage["ontology"]
        assert tuple(sorted(block)) == tuple(sorted(LINEAGE_ONTOLOGY_FIELDS))
        assert all(isinstance(v, str) and v.strip() for v in block.values())
        resolution = builder.ontology_resolution()
        assert block["version"] == resolution.reference.version
        chk = check_lineage_ontology(resolution, lineage)
        assert chk.allowed, f"环3：血缘本体块未放行（{chk.code}）：{chk.reason}"
        print("[环3] 血缘本体块 5 键放行 | contentSha256 =", block["contentSha256"][:16])

        # ── 环 4：本体真解析结果进入**该次**物化（同一 version 目录）────────
        mat = materialize_ontology(ws, version=out["projection_version"],
                                   service_id=SERVICE_ID,
                                   assets_source=ONTOLOGY_SRC)
        onto_lineage = json.loads((vdir / "ONTOLOGY_LINEAGE.json").read_text(encoding="utf-8"))
        for name in ("ontology_classes.parquet", "ontology_properties.parquet",
                     "ontology_shapes.parquet", "ONTOLOGY.md", "ONTOLOGY_LINEAGE.json"):
            assert (vdir / name).is_file(), f"环4 缺少本体产物：{name}"
        assert mat["version"] == out["projection_version"], "环4：本体物化未落在同一 version"
        # 反空转：真解析必须解析出东西（类/形状/三元组均不得为 0）
        counts = onto_lineage["counts"]
        assert counts["classes"] >= 1 and counts["shapes"] >= 1 and counts["triples"] >= 1, counts
        assert mat["graph"]["node_count"] >= 1 and mat["graph"]["edge_count"] >= 1, mat["graph"]
        # **同一条链**的机械证据：本体物化的输入摘要 == 环 3 血缘的声明摘要
        assert any(a["contentSha256"] == block["contentSha256"]
                   for a in onto_lineage["assets"]), onto_lineage["assets"]
        print("[环4] 本体真解析：classes =", counts["classes"], "| shapes =", counts["shapes"],
              "| triples =", counts["triples"], "| fp =", mat["graph"]["fingerprint"][:16])

        # ── 环 5：lightRAG 发布 → 检索（含出处）→ 重建（文档级） ───────────
        from kert.infrastructure.lightrag_client import (
            LightRagClient,
            LightRagHTTPError,
            LightRagUnavailable,
        )

        client = LightRagClient.from_env()
        rels = [f"04_serve/{SERVICE_ID}/version={out['projection_version']}/{n}"
                for n in ("PROJECTION.md", "ONTOLOGY.md")]
        sources = []
        if not client.available():
            with pytest.raises(LightRagUnavailable):
                svc.publish_artifact(rels[0], client=client)
            print("[环5] 分支=**不可达**（具名错误已断言）⇒ 真正的 E2E 未执行；"
                  "CI 绿 ≠ E2E 已验（ADR ⑦-a）")
        else:
            try:
                for rel in rels:
                    sources.append(svc.publish_artifact(rel, client=client)["file_source"])
            except LightRagHTTPError as exc:
                assert any(s in str(exc) for s in ("401", "403")), (
                    f"环5：可达却非鉴权失败 ⇒ 接入口径可能变了：{exc}")
                print("[环5] 分支=**可达但未授权**（具名 401/403 已断言）⇒ 真正的 E2E 未执行")
            else:
                try:
                    for source in sources:
                        _wait_processed(client, source)
                    query = "本体物化产物 客户画像 产品 利率"
                    hits = _citation_paths(client, query)
                    assert hits & set(sources), (
                        f"环5：检索未命中本次发布产物（需要出处回指）∶hits={sorted(hits)}")
                    # 重建（文档级）：撤回 ⇒ 消失 ⇒ 重发 ⇒ **同一出处集合**恢复
                    for rel in rels:
                        svc.retract_artifact(rel, client=client)
                    for source in sources:
                        assert client.find_documents(source) == (), "环5：撤回后仍有残留"
                    for rel in rels:
                        svc.publish_artifact(rel, client=client)
                    for source in sources:
                        _wait_processed(client, source)
                    assert _citation_paths(client, query) & set(sources), (
                        "环5：重发后未恢复同一出处集合 ⇒ 索引不能由 KERT 产物重建")
                    print("[环5] 分支=**已授权**：发布 → 检索(出处回指) → 撤回 → 重发 ⇒ 出处集合一致 ✓")
                finally:
                    for rel in rels:  # 收尾：回到测试前状态（不留残留条目）
                        svc.retract_artifact(rel, client=client)

        # ── 环 6 的反向断言在 `test_ring_6_tampered_lineage_is_refused`（同一条链、另起 fixture）
        assert (vdir / "PLAN_LINEAGE.json").is_file()

    def test_ring_6_tampered_lineage_is_refused(self, ws_chain):
        """环 6：**篡改血缘里的哈希 ⇒ 拒绝**（`MISMATCH`，不是告警），且**下游物化也拒绝**。"""
        from kert.domain.activation_plan import ActivationPlanBuilder
        from kert.domain.ontology_reference import (
            CODE_LINEAGE_MISMATCH,
            LINEAGE_ONTOLOGY_KEY,
            check_lineage_ontology,
        )

        ws = ws_chain
        svc = KnowledgeService(ws, service_id=SERVICE_ID)
        out = svc.materialize_from_plan(TASK_TYPE, domain=DOMAIN, subject_id=SUBJECT_ID)
        p = ws / out["lineage_path"]
        resolution = ActivationPlanBuilder.load(ws).ontology_resolution()
        assert check_lineage_ontology(resolution, json.loads(p.read_text(
            encoding="utf-8"))).allowed, "未篡改时应放行（否则该反例无意义）"

        fm = json.loads(p.read_text(encoding="utf-8"))
        good = fm[LINEAGE_ONTOLOGY_KEY]["contentSha256"]
        fm[LINEAGE_ONTOLOGY_KEY]["contentSha256"] = (
            ("0" if good[0] != "0" else "1") + good[1:])
        p.write_text(json.dumps(fm, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        chk = check_lineage_ontology(resolution, json.loads(p.read_text(encoding="utf-8")))
        assert not chk.allowed, "篡改哈希后竟然放行 —— 拒绝语义失效"
        assert chk.code == CODE_LINEAGE_MISMATCH, chk.code
        assert "contentSha256" in chk.reason, chk.reason

        # 下游（本体物化）也必须**拒绝**，而不是告警后继续产出
        from kert.domain.ontology_assets import OntologyAssetError

        with pytest.raises(OntologyAssetError) as ei:
            materialize_ontology(ws, version=out["projection_version"],
                                 service_id=SERVICE_ID, assets_source=ONTOLOGY_SRC)
        assert ei.value.code == CODE_LINEAGE_MISMATCH, ei.value.code
        print("[环6] 篡改 contentSha256 ⇒ 校验拒绝 + 下游物化拒绝 ✓")
