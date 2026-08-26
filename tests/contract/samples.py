"""每类合同的合法最小样例生成器（供合同测试与集成测试复用）。"""

from __future__ import annotations

import yaml

from dkws.domain.contracts import specs

ZERO_SHA = "0" * 64
FAKE_SHA = "a" * 64


def _render(fm: dict, body: str) -> str:
    fm_text = yaml.safe_dump(fm, sort_keys=False, allow_unicode=True).strip()
    return f"---\n{fm_text}\n---\n\n{body}"


def manifest(files=None, **overrides) -> str:
    fm = {
        "schema": "raw_manifest/v1",
        "batch_id": "BATCH-20260819-001",
        "domain": "product",
        "status": "CLOSED",
        "source_system": "product_management",
        "idempotency_key": "product-20260819-001",
        "received_at": "2026-08-19T10:00:00Z",
        "received_by": "svc_ingestor",
        "files": files or [
            {"path": "product.parquet",
             "media_type": "application/vnd.apache.parquet",
             "size_bytes": 10240, "sha256": ZERO_SHA, "role": "DATA"},
        ],
        "closed_at": "2026-08-19T10:00:02Z",
        "version": "1.0",
    }
    fm.update(overrides)
    return _render(fm, "# 原始批次清单\n\n## 来源说明\n\n产品管理系统日快照。\n\n## 接入备注\n\n无。\n")


def document(**overrides) -> str:
    fm = {
        "schema": "document/v1",
        "document_id": "DOC-001",
        "title": "产品说明手册",
        "document_type": "MANUAL",
        "language": "zh-CN",
        "source_batch_id": "BATCH-20260819-001",
        "source_path": "01_raw/product/batch=BATCH-20260819-001/product_manual.pdf",
        "source_sha256": FAKE_SHA,
        "source_media_type": "application/pdf",
        "confidentiality": "INTERNAL",
        "parse_status": "PARSED",
        "parser_id": "text_parser",
        "parser_version": "1.0.0",
        "page_count": 3,
        "validation_status": "CANDIDATE",
        "status": "ACTIVE",
        "version": "1.0",
    }
    fm.update(overrides)
    return _render(fm, "# 产品说明手册\n\n## 文档摘要\n\n产品说明。\n\n## 来源与效力说明\n\n无。\n\n## 解析说明\n\n文本解析。\n")


def normalized(**overrides) -> str:
    fm = {
        "schema": "normalized_document/v1",
        "document_id": "DOC-001",
        "source_sha256": FAKE_SHA,
        "parser_id": "text_parser",
        "parser_version": "1.0.0",
        "parse_run_id": "RUN-PARSE-20260819-001",
        "normalization_policy_version": "norm/v1",
        "status": "ACTIVE",
        "version": "1.0",
    }
    fm.update(overrides)
    return _render(fm, "# 产品说明手册\n\n<!-- page:1 -->\n\n产品正文。\n")


def segment(**overrides) -> str:
    fm = {
        "schema": "document_segment/v1",
        "segment_id": "SEG-DOC-001-0001",
        "document_id": "DOC-001",
        "segment_type": "PARAGRAPH",
        "heading_path": ["产品说明手册"],
        "page_from": 1, "page_to": 1,
        "sequence": 1,
        "char_start": 0, "char_end": 10,
        "content_sha256": FAKE_SHA,
        "chunk_policy_version": "chunk/v1",
        "status": "ACTIVE",
        "version": "1.0",
    }
    fm.update(overrides)
    return _render(fm, "# 片段\n\n## 原文\n\n产品正文。\n")


def entity(**overrides) -> str:
    fm = {
        "schema": "entity/v1",
        "entity_id": "PROD-001",
        "entity_type": "PRODUCT",
        "name": "标准产品A",
        "aliases": ["产品A"],
        "domain": "product",
        "source_ids": ["BATCH-20260819-001"],
        "validation_status": "CANDIDATE",
        "status": "ACTIVE",
        "version": "1.0",
    }
    fm.update(overrides)
    return _render(fm, "# 标准产品A\n\n## 定义\n\n标准产品。\n\n## 业务说明\n\n无。\n\n## 来源证据\n\n批次。\n\n## 审核说明\n\n无。\n")


def relation(**overrides) -> str:
    fm = {
        "schema": "relation/v1",
        "relation_id": "REL-001",
        "source_id": "PROD-001",
        "relation_type": "REQUIRES",
        "target_id": "MAT-001",
        "direction": "DIRECTED",
        "source_ids": ["BATCH-20260819-001"],
        "validation_status": "CANDIDATE",
        "status": "ACTIVE",
        "version": "1.0",
    }
    fm.update(overrides)
    return _render(fm, "# 产品A 需要 材料B\n\n## 语义\n\n产品需要材料。\n\n## 来源证据\n\n批次。\n\n## 审核说明\n\n无。\n")


def statement(**overrides) -> str:
    fm = {
        "schema": "statement/v1",
        "statement_id": "ST-001",
        "subject_id": "PROD-001",
        "predicate": "interest_rate",
        "object_value": 3.5,
        "value_type": "DECIMAL",
        "source_type": "STRUCTURED_DATA",
        "source_asset_id": "DS-PRODUCT-001",
        "source_record_id": "rec-1",
        "polarity": "AFFIRMED",
        "validation_status": "CANDIDATE",
        "conflict_status": "NONE",
        "recorded_at": "2026-08-19T10:00:00Z",
        "status": "ACTIVE",
        "version": "1.0",
    }
    fm.update(overrides)
    return _render(fm, "# 产品A利率为3.5\n\n## 规范表达\n\nPROD-001 interest_rate 3.5\n\n## 来源证据\n\n数据集。\n\n## 冲突与限定\n\n无。\n\n## 审核说明\n\n无。\n")


def rule(**overrides) -> str:
    fm = {
        "schema": "rule/v1",
        "rule_id": "RULE-001",
        "name": "利率上限规则",
        "rule_type": "VALIDATION",
        "priority": 100,
        "execution_mode": "ADVISORY",
        "when": {"all": [{"gt": ["$input.rate", 0]}, {"lte": ["$input.rate", 10]}]},
        "then": {"set": {"result": "OK"}},
        "required_inputs": [{"name": "rate", "type": "DECIMAL"}],
        "test_case_ids": ["TC-001", "TC-002"],
        "validation_status": "CANDIDATE",
        "status": "ACTIVE",
        "version": "1.0",
    }
    fm.update(overrides)
    return _render(fm, "# 利率上限规则\n\n## 业务解释\n\n利率须在0到10之间。\n\n## 输入与输出\n\nrate。\n\n## 证据\n\n无。\n\n## 人工责任边界\n\n建议。\n\n## 测试说明\n\n正向反向。\n")


def release(**overrides) -> str:
    fm = {
        "schema": "release/v1",
        "release_id": "REL-20260819-001",
        "domain": "product",
        "release_version": "2026.08.19.1",
        "asset_manifest": [
            {"path": "entities/PROD-001.md", "schema": "entity/v1",
             "asset_id": "PROD-001", "asset_version": "1.0", "sha256": FAKE_SHA},
        ],
        "quality_gate_results": [{"gate": "G3", "result": "PASS"}],
        "approval_decision_ids": ["DEC-001"],
        "released_by": "operator",
        "released_at": "2026-08-19T10:00:00Z",
        "status": "PUBLISHED",
        "version": "1.0",
    }
    fm.update(overrides)
    return _render(fm, "# 发布记录\n")


def current(scope_type="CORE_DOMAIN", **overrides) -> str:
    fm = {
        "schema": "current_pointer/v1",
        "scope_type": scope_type,
        "scope_id": "product",
        "target_version": "2026.08.19.1",
        "target_release_id": "REL-20260819-001",
        "target_manifest_sha256": FAKE_SHA,
        "switched_by": "operator",
        "switched_at": "2026-08-19T10:00:00Z",
        "reason": "发布",
        "status": "ACTIVE",
        "version": "1.0",
    }
    fm.update(overrides)
    return _render(fm, "# 当前活动版本\n\n## 切换说明\n\n发布。\n\n## 回滚说明\n\n回滚指针。\n")


def projection(**overrides) -> str:
    fm = {
        "schema": "projection/v1",
        "projection_id": "PRJ-20260819-001",
        "service_id": "product_knowledge",
        "projection_version": "2026.08.19.1",
        "source_core_releases": ["2026.08.19.1"],
        "builder_id": "projection_builder",
        "builder_version": "1.0.0",
        "configuration_hash": FAKE_SHA,
        "files": [{"path": "entities.parquet", "sha256": FAKE_SHA}],
        "logical_hashes": [{"file": "entities.parquet", "logical_hash": FAKE_SHA}],
        "built_at": "2026-08-19T10:00:00Z",
        "verification_status": "VERIFIED",
        "status": "ACTIVE",
        "version": "1.0",
    }
    fm.update(overrides)
    return _render(fm, "# 投影记录\n")


def job_status(**overrides) -> str:
    fm = {
        "schema": "job_status/v1",
        "job_id": "JOB-INGEST-20260819-001",
        "job_type": "INGEST",
        "status": "COMPLETED",
        "requested_by": "operator",
        "idempotency_key": "ingest-001",
        "input_refs": [{"path": "input.csv", "version": "1.0", "content_hash": FAKE_SHA}],
        "output_refs": [{"path": "01_raw/.../MANIFEST.md", "version": "1.0", "content_hash": FAKE_SHA}],
        "started_at": "2026-08-19T10:00:00Z",
        "updated_at": "2026-08-19T10:00:05Z",
        "finished_at": "2026-08-19T10:00:05Z",
        "progress": 100,
        "publish_status": "NOT_PUBLISHED",
        "version": "1.0",
    }
    fm.update(overrides)
    return _render(fm, "# 任务状态\n\n## 当前摘要\n\n完成。\n\n## 输入输出\n\n见上。\n\n## 错误与恢复建议\n\n无。\n")


def run_report(**overrides) -> str:
    fm = {
        "schema": "run_report/v1",
        "job_id": "JOB-INGEST-20260819-001",
        "final_status": "COMPLETED",
        "started_at": "2026-08-19T10:00:00Z",
        "finished_at": "2026-08-19T10:00:05Z",
        "duration_ms": 5000,
        "input_count": 1, "output_count": 1, "rejected_count": 0,
        "warning_count": 0, "error_count": 0,
        "quality_summary": {"gates_passed": ["G0"]},
        "log_sha256": FAKE_SHA,
        "status": "COMPLETED",
        "version": "1.0",
    }
    fm.update(overrides)
    return _render(fm, "# 运行报告\n\n## 执行摘要\n\n完成。\n\n## 输入与输出\n\n1/1。\n\n## 质量结果\n\n通过。\n\n## 警告与错误\n\n无。\n\n## 可复现信息\n\n无。\n\n## 非声明事项\n\n无。\n")


def decision(**overrides) -> str:
    fm = {
        "schema": "review_decision/v1",
        "decision_id": "DEC-001",
        "object_refs": ["entities/PROD-001.md"],
        "decision": "APPROVE",
        "decided_by": "reviewer-a",
        "role": "Reviewer",
        "decided_at": "2026-08-19T10:00:00Z",
        "reason": "核对来源一致",
        "conditions": [],
        "evidence_refs": ["segments/SEG-DOC-001-0001.md"],
        "status": "ACTIVE",
        "version": "1.0",
    }
    fm.update(overrides)
    return _render(fm, "# 审核决定\n")


def lineage(**overrides) -> str:
    fm = {
        "schema": "lineage/v1",
        "lineage_id": "LG-001",
        "process_id": "ingest",
        "job_id": "JOB-INGEST-20260819-001",
        "inputs": [{"asset_id": "INPUT-FILE", "version": "1.0",
                    "path": "input.csv", "content_hash": FAKE_SHA}],
        "outputs": [{"asset_id": "BATCH-20260819-001", "version": "1.0",
                     "path": "01_raw/product/batch=BATCH-20260819-001/MANIFEST.md",
                     "content_hash": FAKE_SHA}],
        "transformation_id": "ingest_copy",
        "transformation_version": "1.0.0",
        "code_version": "0.1.0",
        "started_at": "2026-08-19T10:00:00Z",
        "finished_at": "2026-08-19T10:00:05Z",
        "status": "COMPLETED",
        "version": "1.0",
    }
    fm.update(overrides)
    return _render(fm, "# 血缘记录\n\n## 转换说明\n\n复制。\n\n## 输入\n\n见上。\n\n## 输出\n\n见上。\n\n## 已知限制\n\n无。\n")


def vocabulary(**overrides) -> str:
    fm = {
        "schema": "vocabulary_term/v1",
        "term_id": "VT-PRODUCT",
        "term_kind": "ENTITY_TYPE",
        "name": "产品",
        "definition": "可销售的产品",
        "domain": "product",
        "aliases": [],
        "allowed_source_types": ["STRUCTURED_DATA", "DOCUMENT"],
        "status": "ACTIVE",
        "version": "1.0",
    }
    fm.update(overrides)
    return _render(fm, "# 产品\n\n## 定义\n\n可销售的产品。\n\n## 使用约束\n\n无。\n\n## 示例\n\n标准产品A。\n\n## 变更记录\n\n无。\n")


def quality_rule(**overrides) -> str:
    fm = {
        "schema": "quality_rule/v1",
        "quality_rule_id": "QR-001",
        "name": "主键唯一",
        "target_schema": "datasets/product/v1",
        "target_asset": "DS-PRODUCT-001",
        "dimension": "UNIQUENESS",
        "severity": "BLOCKER",
        "expression": "count_duplicates(product_id)==0",
        "threshold": "0",
        "on_failure": "BLOCK",
        "status": "ACTIVE",
        "version": "1.0",
    }
    fm.update(overrides)
    return _render(fm, "# 质量规则\n")


def quality_result(**overrides) -> str:
    fm = {
        "schema": "quality_result/v1",
        "quality_result_id": "QR-20260819-001",
        "quality_rule_id": "QR-001",
        "quality_rule_version": "1.0",
        "job_id": "JOB-INGEST-20260819-001",
        "target_asset": "DS-PRODUCT-001",
        "target_version": "1.0",
        "evaluated_count": 100,
        "failed_count": 0,
        "sample_failures": [],
        "result": "PASS",
        "executed_at": "2026-08-19T10:00:00Z",
        "status": "ACTIVE",
        "version": "1.0",
    }
    fm.update(overrides)
    return _render(fm, "# 质量结果\n")


def gate_report(**overrides) -> str:
    fm = {
        "schema": "gate_report/v1",
        "gate_id": "G0-001",
        "review_object": "batch=BATCH-20260819-001",
        "target_transition": "OPEN->CLOSED",
        "decision": "PASS_FOR_NEXT_GATE",
        "substantive_review": "人工复核通过",
        "findings": [],
        "reviewed_by": "qa-a",
        "reviewed_at": "2026-08-19T10:00:00Z",
        "baseline_state": "NOT_BASELINED",
        "frozen": False,
        "status": "ACTIVE",
        "version": "1.0",
    }
    fm.update(overrides)
    return _render(fm, "# 门禁报告\n")


BUILDERS = {
    "raw_manifest/v1": manifest,
    "document/v1": document,
    "normalized_document/v1": normalized,
    "document_segment/v1": segment,
    "entity/v1": entity,
    "relation/v1": relation,
    "statement/v1": statement,
    "rule/v1": rule,
    "release/v1": release,
    "current_pointer/v1": current,
    "projection/v1": projection,
    "job_status/v1": job_status,
    "run_report/v1": run_report,
    "review_decision/v1": decision,
    "lineage/v1": lineage,
    "vocabulary_term/v1": vocabulary,
    "quality_rule/v1": quality_rule,
    "quality_result/v1": quality_result,
    "gate_report/v1": gate_report,
}


def valid_sample(schema_name: str) -> str:
    builder = BUILDERS.get(schema_name)
    if builder is None:
        raise KeyError(f"缺少 {schema_name} 的样例 builder")
    return builder()


def asset_catalog(**overrides) -> str:
    fm = {
        "schema": "asset_catalog/v1",
        "asset_id": "DS-PRODUCT-001",
        "asset_type": "DATASET",
        "name": "产品数据集",
        "domain": "product",
        "owner": "data-team",
        "classification": "INTERNAL",
        "authoritative_layer": "03_core",
        "current_version": "1.0",
        "location": "03_core/product/version=2026.08.19.1/datasets/product.parquet",
        "upstream_ids": ["BATCH-20260819-001"],
        "downstream_ids": [],
        "status": "ACTIVE",
        "version": "1.0",
    }
    fm.update(overrides)
    return _render(fm, "# 产品数据集\n\n## 业务定义\n\n产品主数据。\n\n## 内容范围\n\n产品列表。\n\n## 上下游\n\n见上。\n\n## 使用限制\n\n内部。\n\n## 变更记录\n\n无。\n")


def data_mapping(**overrides) -> str:
    fm = {
        "schema": "data_mapping/v1",
        "mapping_id": "MAP-001",
        "source_schema": "product_raw/v1",
        "target_schema": "datasets/product/v1",
        "field_mappings": [
            {"source_field": "prod_id", "target_field": "product_id",
             "target_type": "string", "missing_policy": "REJECT"},
        ],
        "key_policy": "product_id",
        "null_policy": "REJECT_REQUIRED",
        "reject_policy": "ISOLATE",
        "status": "ACTIVE",
        "version": "1.0",
    }
    fm.update(overrides)
    return _render(fm, "# 数据映射\n")


def processing_policy(**overrides) -> str:
    fm = {
        "schema": "processing_policy/v1",
        "policy_id": "POL-001",
        "policy_kind": "CHUNK",
        "implementation_id": "chunker_v1",
        "implementation_version": "1.0.0",
        "parameters": {"max_chars": 500, "calls_model": False},
        "input_schemas": ["normalized_document/v1"],
        "output_schemas": ["document_segment/v1"],
        "deterministic": True,
        "status": "ACTIVE",
        "version": "1.0",
    }
    fm.update(overrides)
    return _render(fm, "# 处理策略\n")


def knowledge_pack(**overrides) -> str:
    fm = {
        "schema": "knowledge_pack/v1",
        "knowledge_pack_id": "KP-001",
        "name": "产品知识包",
        "domain": "product",
        "intended_consumers": ["sales"],
        "entity_ids": ["PROD-001"],
        "relation_ids": ["REL-001"],
        "statement_ids": ["ST-001"],
        "rule_ids": ["RULE-001"],
        "document_ids": ["DOC-001"],
        "scope_filters": [{"field": "domain", "value": "product"}],
        "source_release_ids": ["2026.08.19.1"],
        "status": "ACTIVE",
        "version": "1.0",
    }
    fm.update(overrides)
    return _render(fm, "# 产品知识包\n")


def rule_test_case(**overrides) -> str:
    fm = {
        "schema": "rule_test_case/v1",
        "test_case_id": "TC-001",
        "rule_id": "RULE-001",
        "rule_version": "1.0",
        "input_facts": {"rate": 5},
        "expected_match": True,
        "expected_outcome": {"result": "OK"},
        "expected_missing_inputs": [],
        "status": "ACTIVE",
        "version": "1.0",
    }
    fm.update(overrides)
    return _render(fm, "# 规则测试用例\n")


def schema_contract(**overrides) -> str:
    fm = {
        "schema": "schema_contract/v1",
        "schema_id": "SC-001",
        "target_schema": "entity/v1",
        "major_version": 1,
        "compatibility": "BACKWARD",
        "primary_id_field": "entity_id",
        "required_fields": ["entity_id", "entity_type", "name"],
        "allowed_fields": ["entity_id", "entity_type", "name", "aliases", "x_extra"],
        "enums": {"validation_status": ["CANDIDATE", "IN_REVIEW", "APPROVED", "REJECTED"]},
        "reference_fields": ["source_ids"],
        "status": "ACTIVE",
        "version": "1.0",
    }
    fm.update(overrides)
    return _render(fm, "# 实体Schema\n\n## 目的\n\n实体合同。\n\n## 字段定义\n\n见上。\n\n## 交叉字段约束\n\n无。\n\n## 兼容策略\n\n向后。\n\n## 合法示例\n\n见样例。\n\n## 非法示例\n\n见样例。\n")


def service_catalog(**overrides) -> str:
    fm = {
        "schema": "service_catalog/v1",
        "service_id": "SVC-PRODUCT-QUERY",
        "name": "产品查询服务",
        "service_type": "DATA_QUERY",
        "input_contract": {"dataset": "product", "filters": []},
        "output_contract": {"records": [], "meta": {}},
        "source_projection_id": "PRJ-20260819-001",
        "authorization_policy": "READ_ONLY",
        "limits": {"max_rows": 1000},
        "sla_class": "BEST_EFFORT",
        "current_version": "1.0",
        "status": "ACTIVE",
        "version": "1.0",
    }
    fm.update(overrides)
    return _render(fm, "# 产品查询服务\n\n## 服务目的\n\n查询产品。\n\n## 输入输出\n\n见上。\n\n## 数据与知识范围\n\n产品。\n\n## 限制和责任边界\n\n只读。\n\n## 示例\n\n见样例。\n")


BUILDERS.update({
    "asset_catalog/v1": asset_catalog,
    "data_mapping/v1": data_mapping,
    "processing_policy/v1": processing_policy,
    "knowledge_pack/v1": knowledge_pack,
    "rule_test_case/v1": rule_test_case,
    "schema_contract/v1": schema_contract,
    "service_catalog/v1": service_catalog,
})
