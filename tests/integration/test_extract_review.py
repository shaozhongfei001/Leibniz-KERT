"""P5 集成测试：知识候选抽取、审核、冲突检测（FR-KNW-*）。"""

from __future__ import annotations


import pytest

from dkws.application.extract import KnowledgeExtractor
from dkws.application.ingest import Ingestor
from dkws.application.parse_doc import DocumentParserService
from dkws.application.review import ReviewService
from dkws.application import validation
from dkws.domain.contracts import specs
from dkws.domain.contracts.base import validate_contract
from dkws.domain.rules import dsl


@pytest.fixture
def knowledge_batch(ws, tmp_path):
    """含产品/材料/利率/规则文本的文档批次。"""
    md = tmp_path / "loan_policy.md"
    md.write_text(
        "# 贷款政策\n\n"
        "## 产品与材料\n\n"
        "产品A利率为3.5%。\n\n"
        "产品B利率为4.2%。\n\n"
        "产品A需要材料M1。\n\n"
        "规则：利率不超过10。\n\n"
        "产品C不可申请。\n",
        encoding="utf-8",
    )
    r = Ingestor(ws).ingest("product", [md], "batch-knw-1")
    pr = DocumentParserService(ws).parse("product", r.batch_id)
    return {"ws": ws, "batch_id": r.batch_id, "parse_run": pr.run_id}


class TestExtract:
    def test_candidates_all_candidate(self, knowledge_batch):
        ws = knowledge_batch["ws"]
        r = KnowledgeExtractor(ws).extract(
            "product", knowledge_batch["batch_id"],
            run_id=knowledge_batch["parse_run"])
        kinds = {"ENTITY", "RELATION", "STATEMENT", "RULE"}
        found = {c["kind"] for c in r.candidates}
        assert kinds.issubset(found), found
        assert len(r.candidates) >= 8
        # 每个候选合同合法且 CANDIDATE
        for c in r.candidates:
            text = (ws / c["path"]).read_text(encoding="utf-8")
            spec = {
                "ENTITY": specs.ENTITY_SPEC, "RELATION": specs.RELATION_SPEC,
                "STATEMENT": specs.STATEMENT_SPEC, "RULE": specs.RULE_SPEC,
            }[c["kind"]]
            rv = validate_contract(text, spec, path=c["path"])
            assert rv.ok, (c["kind"], rv.errors)
            assert rv.front_matter["validation_status"] == "CANDIDATE"

    def test_extraction_metadata_recorded(self, knowledge_batch):
        ws = knowledge_batch["ws"]
        r = KnowledgeExtractor(ws).extract(
            "product", knowledge_batch["batch_id"],
            run_id=knowledge_batch["parse_run"])
        ent = [c for c in r.candidates if c["kind"] == "ENTITY"][0]
        fm = validate_contract((ws / ent["path"]).read_text(encoding="utf-8"),
                               specs.ENTITY_SPEC).front_matter
        assert fm["confidence"] == 0.9
        assert fm["extraction"]["extractor"] == "deterministic_extractor"
        assert fm["source_ids"]  # 来源片段

    def test_rule_dsl_valid(self, knowledge_batch):
        ws = knowledge_batch["ws"]
        r = KnowledgeExtractor(ws).extract(
            "product", knowledge_batch["batch_id"],
            run_id=knowledge_batch["parse_run"])
        rules = [c for c in r.candidates if c["kind"] == "RULE"]
        assert rules
        fm = validate_contract((ws / rules[0]["path"]).read_text(encoding="utf-8"),
                               specs.RULE_SPEC).front_matter
        assert dsl.validate_dsl(fm["when"]) == []
        assert dsl.validate_dsl(fm["then"]) == []

    def test_negated_statement(self, knowledge_batch):
        ws = knowledge_batch["ws"]
        r = KnowledgeExtractor(ws).extract(
            "product", knowledge_batch["batch_id"],
            run_id=knowledge_batch["parse_run"])
        stmts = [c for c in r.candidates if c["kind"] == "STATEMENT"]
        assert len(stmts) >= 3  # A 利率、B 利率、C 不可申请
        neg = [c for c in stmts if "不可" in (ws / c["path"]).read_text(encoding="utf-8")]
        assert neg


class TestReview:
    def test_approve_flow(self, knowledge_batch):
        ws = knowledge_batch["ws"]
        ext = KnowledgeExtractor(ws).extract(
            "product", knowledge_batch["batch_id"],
            run_id=knowledge_batch["parse_run"])
        ent = [c for c in ext.candidates if c["kind"] == "ENTITY"][0]
        svc = ReviewService(ws)
        # 审核动作：CANDIDATE → (IN_REVIEW) → APPROVED（§11.2）
        r = svc.review("product", run_id=knowledge_batch["parse_run"],
                       object_refs=[ent["path"]], decision="APPROVE",
                       reason="来源一致", decided_by="reviewer")
        assert r.decisions[0]["validation_status"] == "APPROVED"
        rel = ent["path"]
        fm = validate_contract((ws / rel).read_text(encoding="utf-8"),
                               specs.ENTITY_SPEC).front_matter
        assert fm["validation_status"] == "APPROVED"
        # 决策记录
        dec = list((ws / "90_control" / "decisions").glob("*.md"))
        assert dec
        dv = validate_contract(dec[0].read_text(encoding="utf-8"),
                               specs.REVIEW_DECISION_SPEC)
        assert dv.ok and dv.front_matter["decision"] == "APPROVE"

    def test_reject_keeps_candidate_and_decision(self, knowledge_batch):
        ws = knowledge_batch["ws"]
        ext = KnowledgeExtractor(ws).extract(
            "product", knowledge_batch["batch_id"],
            run_id=knowledge_batch["parse_run"])
        st = [c for c in ext.candidates if c["kind"] == "STATEMENT"][0]
        svc = ReviewService(ws)
        # REJECT 允许从 CANDIDATE 直接进行（保留候选与原因）
        r = svc.review("product", run_id=knowledge_batch["parse_run"],
                       object_refs=[st["path"]], decision="REJECT",
                       reason="利率与事实不符", decided_by="reviewer")
        assert r.decisions[0]["validation_status"] == "REJECTED"
        # 候选文件仍存在（不物理删除）
        assert (ws / st["path"]).is_file()
        fm = validate_contract((ws / st["path"]).read_text(encoding="utf-8"),
                               specs.STATEMENT_SPEC).front_matter
        assert fm["validation_status"] == "REJECTED"
        # 决策记录保留驳回原因
        dec = list((ws / "90_control" / "decisions").glob("*.md"))
        assert dec
        dv = validate_contract(dec[0].read_text(encoding="utf-8"),
                               specs.REVIEW_DECISION_SPEC)
        assert dv.ok and dv.front_matter["decision"] == "REJECT"
        assert "不符" in dv.front_matter["reason"]


class TestDsl:
    def test_whitelist_enforced(self):
        errs = dsl.validate_dsl({"eval": ["1+1"]})
        assert errs and "eval" in errs[0]
        errs = dsl.validate_dsl({"all": [{"exec": []}]})
        assert errs

    def test_valid_dsl_ok(self):
        assert dsl.validate_dsl({"all": [{"gte": ["$facts.rate", 0]},
                                         {"lte": ["$facts.rate", 10]}]}) == []

    def test_depth_limit(self):
        deep: dict = True
        for _ in range(30):  # 深度 30 > MAX_DEPTH 20
            deep = {"not": deep}
        errs = dsl.validate_dsl(deep)
        assert errs

    def test_evaluate_basic(self):
        r = dsl.evaluate({"gte": ["$facts.rate", 5]}, {"rate": 8})
        assert r.value is True
        r = dsl.evaluate({"lte": ["$facts.rate", 5]}, {"rate": 8})
        assert r.value is False

    def test_unknown_missing_field(self):
        r = dsl.evaluate({"eq": ["$facts.missing", 1]}, {})
        assert isinstance(r.value, dsl.UnknownValue)
        # UNKNOWN 不自动等于 FALSE
        r2 = dsl.evaluate({"all": [{"eq": ["$facts.missing", 1]}]}, {})
        assert isinstance(r2.value, dsl.UnknownValue)

    def test_rule_body_dangerous_text(self):
        assert dsl.validate_rule_body_text("请执行 eval('x')") != []
        assert dsl.validate_rule_body_text("利率不超过10") == []


class TestValidation:
    def test_dangling_relation_detected(self):
        findings = validation.check_dangling_references(
            {"ENT-1": {"name": "a"}},
            [{"relation_id": "REL-1", "source_id": "ENT-1", "target_id": "ENT-X"}],
            [])
        assert any(f.code == "DANGLING_RELATION" for f in findings)

    def test_duplicate_entity_name(self):
        findings = validation.check_duplicate_entities({
            "ENT-1": {"name": "产品A", "aliases": []},
            "ENT-2": {"name": "产品A", "aliases": []},
        })
        assert any(f.code == "DUPLICATE_ENTITY_NAME" for f in findings)

    def test_statement_conflict(self):
        findings = validation.check_statement_conflicts([
            {"statement_id": "ST-1", "subject_id": "ENT-1", "predicate": "rate",
             "polarity": "AFFIRMED", "value_type": "DECIMAL",
             "object_value": 3.5, "effective_from": "2026-01-01", "effective_to": None},
            {"statement_id": "ST-2", "subject_id": "ENT-1", "predicate": "rate",
             "polarity": "AFFIRMED", "value_type": "DECIMAL",
             "object_value": 9.9, "effective_from": "2026-01-01", "effective_to": None},
        ])
        assert any(f.code == "CONFLICTING_STATEMENT" for f in findings)
