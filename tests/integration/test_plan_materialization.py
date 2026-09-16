"""T1 端到端：**计划驱动**的服务投影物化（计划 → 产物 → 血缘含本体引用 → 可查询）。

Owner 2026-09-16 直接指令：把「知识地图 → skill 路由 → 本体模型 → 业务语义 → lightRAG →
本体物化」这条链真正连通。本用例只验证**物化这一跳**：

1. 输入是**激活计划**（路由策略 + 知识地图 + 本体引用声明，均由控制面供给）——计划被拒即不物化；
2. 产物与既有投影**同形**（`04_serve/<svc>/version=*/` 的 Parquet 族 + `PROJECTION.md`）；
3. 产物元数据含**计划身份 + 本体引用**（逐键取自计划本身，无新造字段）；
4. 产物**可查询**（Kùzu 图已建 + 经服务 API 的图谱查询命中）。
"""

from __future__ import annotations

import json
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from kert.application.extract import KnowledgeExtractor
from kert.application.ingest import Ingestor
from kert.application.parse_doc import DocumentParserService
from kert.application.projection import ProjectionBuilder
from kert.application.provision import provision_control_plane
from kert.application.publish import Publisher
from kert.application.review import ReviewService
from kert.application.services import KnowledgeService

REPO = Path(__file__).resolve().parents[2]
CONTROL_PLANE_SRC = REPO / "examples" / "bank-front-knowledge-maps"
SERVICE_ID = "product_knowledge"


@pytest.fixture
def ws_plan_ready(ws, tmp_path):
    """工作区 = 控制面（路由策略 + 地图 + 本体引用声明）**＋** 一个已发布 Core 版本。"""
    provision_control_plane(ws, CONTROL_PLANE_SRC)
    md = tmp_path / "p.md"
    md.write_text(
        "# 政策\n\n## 产品\n\n产品A利率为3.5%。\n\n产品B利率为4.2%。\n\n"
        "产品A需要材料M1。\n\n规则：利率不超过10。\n",
        encoding="utf-8",
    )
    r = Ingestor(ws).ingest("product", [md], "batch-plan-mat-1")
    pr = DocumentParserService(ws).parse("product", r.batch_id)
    ex = KnowledgeExtractor(ws).extract("product", r.batch_id, run_id=pr.run_id)
    ReviewService(ws).review("product", run_id=pr.run_id,
                             object_refs=[c["path"] for c in ex.candidates],
                             decision="APPROVE", reason="ok", decided_by="r")
    Publisher(ws).publish("product", run_id=pr.run_id)
    return ws


class TestPlanDrivenMaterialization:
    def test_materialize_lineage_and_query(self, ws_plan_ready):
        ws = ws_plan_ready
        svc = KnowledgeService(ws, service_id=SERVICE_ID)

        out = svc.materialize_from_plan("OUTREACH_PREPARATION", domain="product",
                                        subject_id="CUST-CORP-0001")

        # ① 产物出现，且与既有投影**同形**
        vdir = ws / "04_serve" / SERVICE_ID / f"version={out['projection_version']}"
        for name in ("entities.parquet", "relations.parquet", "statements.parquet",
                     "segments.parquet", "rules.parquet", "PROJECTION.md"):
            assert (vdir / name).is_file(), f"缺少 {name}"

        # ② 血缘 = 计划本身（键名取自既有计划；含计划身份 + 本体引用）
        lineage = json.loads((vdir / "PLAN_LINEAGE.json").read_text(encoding="utf-8"))
        assert lineage["planId"].startswith("AP-KERT-OUTREACH_PREPARATION-")
        assert lineage["planHash"] == out["plan"]["planHash"]
        assert lineage["taskType"] == "OUTREACH_PREPARATION"
        ontology = lineage["versions"]["ontology"]
        assert ontology and "@sha256:" in ontology, ontology
        # 本体引用**来自控制面声明**（不是测试内置的期望值）
        declared = json.loads(
            (ws / "90_control" / "schema" / "ontology_reference.json").read_text(
                encoding="utf-8"))
        assert declared  # 声明存在（值域由供给源决定，此处只断言非空）

        # ③ 可查询：Kùzu 图已建，且图查询命中节点
        from kert.infrastructure.graph.kuzu_builder import KuzuGraphBuilder

        kb = KuzuGraphBuilder(ws, service_id=SERVICE_ID)
        assert kb.graph_available() is True
        import kuzu

        con = kuzu.Connection(kuzu.Database(str(kb.graph_path())))
        assert con.execute("MATCH (c:Company) RETURN count(c)").get_next()[0] >= 3

        ents = pq.read_table(vdir / "entities.parquet")
        start = ents.column("entity_id")[0].as_py()
        g = svc.graph(start_entity_ids=[start], direction="BOTH", mode="neighbor")
        assert g.data["node_count"] >= 1

        # ④ 「同形/同族」判据：**直接**调用既有 builder 得到的产物落在**同一路径族**
        #    （⚠ 该调用会重写同名 version 目录 ⇒ 故放在**最后**，避免清掉 ② 的血缘文件）
        direct = ProjectionBuilder(ws).build("product", service_id=SERVICE_ID)
        assert direct.projection_version == out["projection_version"]
        assert (ws / "04_serve" / SERVICE_ID / f"version={direct.projection_version}"
                / "entities.parquet").is_file()

    def test_plan_denied_materializes_nothing(self, ws, tmp_path):
        """未供给控制面 ⇒ 计划被拒 ⇒ **不产出任何投影**（fail-closed）。"""
        svc = KnowledgeService(ws, service_id=SERVICE_ID)
        from kert.domain.errors import UsageError

        with pytest.raises(UsageError) as ei:
            svc.materialize_from_plan("OUTREACH_PREPARATION", domain="product")
        assert "不物化" in str(ei.value)
        assert not (ws / "04_serve" / SERVICE_ID).exists()
