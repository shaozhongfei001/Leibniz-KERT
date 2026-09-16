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

from kert.application import services
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

        # ②' 本体**输入面**：顶层 `ontology` 子块（5 键，逐字取自既有 helper），且校验放行
        from kert.domain.activation_plan import ActivationPlanBuilder
        from kert.domain.ontology_reference import (
            LINEAGE_ONTOLOGY_FIELDS,
            check_lineage_ontology,
        )

        block = lineage["ontology"]
        assert tuple(sorted(block)) == tuple(sorted(LINEAGE_ONTOLOGY_FIELDS))
        assert all(isinstance(v, str) and v.strip() for v in block.values())
        assert block["version"] == lineage["versions"]["ontology"]  # 与计划版本同值
        resolution = ActivationPlanBuilder.load(ws).ontology_resolution()
        chk = check_lineage_ontology(resolution, lineage)
        assert chk.allowed, chk.reason

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

    def test_tampered_ontology_input_is_refused_and_nothing_materialized(
            self, ws_plan_ready, monkeypatch):
        """反例：**写入口径偏差**（本体面被篡改）⇒ `MISMATCH` ⇒ **不产出投影**（fail-closed）。

        篡改点只作用于**写入侧**（`kert.application.services.lineage_ontology_fields`）；
        校验侧 `check_lineage_ontology` 仍取**真实**期望值 ⇒ 二者不一致必须被拒。
        """
        from kert.domain.errors import UsageError

        real = services.lineage_ontology_fields

        def _tampered(resolution):
            fields = real(resolution)
            if fields is None:
                return None
            fields = dict(fields)
            fields["contentSha256"] = "0" * 64
            return fields

        monkeypatch.setattr(services, "lineage_ontology_fields", _tampered)
        ws = ws_plan_ready
        svc = KnowledgeService(ws, service_id=SERVICE_ID)

        with pytest.raises(UsageError) as ei:
            svc.materialize_from_plan("OUTREACH_PREPARATION", domain="product")
        assert "不一致" in str(ei.value)
        assert not (ws / "04_serve" / SERVICE_ID).exists()

    def test_tampered_written_artifact_is_refused(self, ws_plan_ready):
        """反例（TL 硬要求③）：**篡改已写产物**后校验 ⇒ `MISMATCH`。

        该反例同时证明「**产物形状 == 校验器期望的形状**」：若形状不对（例如本体块仍在
        ``versions.ontology`` 字符串里、或缺顶层对象块），校验会恒判 `ABSENT`，
        接线"成功"也无意义。故先断言**未篡改即放行**，再篡改 `contentSha256` 断言 `MISMATCH`。
        ⚠ 不拿 `authorityRepo`/`authoritySource` 当拒绝理由（依既有 D-3：来源路径环境相关、
        必记但不据以拒绝）—— 该口径由 m71 侧用例覆盖，本文件不重复。
        """
        from kert.domain.activation_plan import ActivationPlanBuilder
        from kert.domain.ontology_reference import (
            CODE_LINEAGE_MISMATCH,
            LINEAGE_ONTOLOGY_KEY,
            check_lineage_ontology,
        )

        ws = ws_plan_ready
        out = KnowledgeService(ws, service_id=SERVICE_ID).materialize_from_plan(
            "OUTREACH_PREPARATION", domain="product")
        p = ws / out["lineage_path"]
        resolution = ActivationPlanBuilder.load(ws).ontology_resolution()

        # 未篡改 ⇒ 放行（形状与校验器期望对齐）
        assert check_lineage_ontology(resolution, json.loads(p.read_text(
            encoding="utf-8"))).allowed

        # 篡改**已写产物**并回写 ⇒ 必判 MISMATCH
        fm = json.loads(p.read_text(encoding="utf-8"))
        good = fm[LINEAGE_ONTOLOGY_KEY]["contentSha256"]
        fm[LINEAGE_ONTOLOGY_KEY]["contentSha256"] = (
            "0" if good[0] != "0" else "1") + good[1:]
        p.write_text(json.dumps(fm, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        chk = check_lineage_ontology(resolution, json.loads(p.read_text(encoding="utf-8")))
        assert not chk.allowed
        assert chk.code == CODE_LINEAGE_MISMATCH
        assert "contentSha256" in chk.reason
