"""全部契约化 Markdown 合同的 SchemaSpec 定义（规格 §9、§14.3、§17.4）。

每类合同 = schema 名 + 字段表 + 正文固定标题 + 交叉校验。
权威字段表以规格文档为准；本文为机器实现镜像。
"""

from __future__ import annotations

from .base import FieldSpec, SchemaSpec
from .helpers import (
    check_confidence,
    check_effective_range,
    check_list_at_least,
    check_list_nonempty,
    check_nonneg_int,
    check_positive_int,
    check_sha256_field,
)

# =====================================================================
# 9.1 原始批次清单 MANIFEST.md —— raw_manifest/v1
# =====================================================================

MANIFEST_FILES = {
    "path": FieldSpec("path", required=True),
    "media_type": FieldSpec("media_type", required=True),
    "size_bytes": FieldSpec("size_bytes", type="integer", required=True,
                            validator=check_nonneg_int),
    "sha256": FieldSpec("sha256", required=True, validator=check_sha256_field),
    "role": FieldSpec("role", type="enum", required=True,
                      enum=["DATA", "DOCUMENT", "IMAGE", "RULE", "REFERENCE", "OTHER"]),
}


def _manifest_extra(fm: dict, body: str) -> list[str]:
    errors: list[str] = []
    files = fm.get("files")
    if not isinstance(files, list) or not files:
        errors.append("files 必须至少包含一个文件")
    if fm.get("status") == "CLOSED" and not fm.get("closed_at"):
        errors.append("CLOSED 批次必须填写 closed_at")
    if fm.get("status") == "QUARANTINED" and not fm.get("closed_at"):
        errors.append("QUARANTINED 批次必须填写 closed_at")
    for f in files if isinstance(files, list) else []:
        p = f.get("path", "")
        if p.startswith(("/", "..")) or ".." in p.split("/"):
            errors.append(f"清单内路径越界: {p!r}")
    return errors


MANIFEST_SPEC = SchemaSpec(
    schema_name="raw_manifest/v1",
    primary_id="batch_id",
    fields=[
        FieldSpec("batch_id", required=True),
        FieldSpec("domain", required=True),
        FieldSpec("status", type="enum", required=True,
                  enum=["OPEN", "CLOSED", "QUARANTINED"]),
        FieldSpec("source_system", required=True),
        FieldSpec("source_uri", nullable=True),
        FieldSpec("idempotency_key", required=True),
        FieldSpec("received_at", type="timestamp", required=True),
        FieldSpec("received_by", required=True),
        FieldSpec("files", type="list", element_type="map",
                  element_fields=MANIFEST_FILES, required=True),
        FieldSpec("closed_at", type="timestamp", nullable=True),
        FieldSpec("version", required=True),
    ],
    required_headings=["原始批次清单", "来源说明", "接入备注"],
    extra_validator=_manifest_extra,
)

# =====================================================================
# 9.2 文档登记 DOCUMENT.md —— document/v1
# =====================================================================


def _document_extra(fm: dict, body: str) -> list[str]:
    errors: list[str] = []
    errors += check_effective_range(fm)
    if fm.get("parse_status") in ("PARSED", "PARTIAL"):
        if not fm.get("parser_id") or not fm.get("parser_version"):
            errors.append("已解析文档必须填写 parser_id 与 parser_version")
    if not fm.get("title"):
        errors.append("title 不能为空")
    return errors


DOCUMENT_SPEC = SchemaSpec(
    schema_name="document/v1",
    primary_id="document_id",
    fields=[
        FieldSpec("document_id", required=True),
        FieldSpec("title", required=True),
        FieldSpec("document_type", type="enum", required=True,
                  enum=["POLICY", "MANUAL", "CONTRACT", "REPORT", "WEBPAGE", "FORM", "OTHER"]),
        FieldSpec("language", required=True),
        FieldSpec("source_batch_id", required=True),
        FieldSpec("source_path", required=True),
        FieldSpec("source_sha256", required=True, validator=check_sha256_field),
        FieldSpec("source_media_type", required=True),
        FieldSpec("business_owner", nullable=True),
        FieldSpec("published_at", type="timestamp", nullable=True),
        FieldSpec("effective_from", type="date", nullable=True),
        FieldSpec("effective_to", type="date", nullable=True),
        FieldSpec("confidentiality", type="enum", required=True,
                  enum=["PUBLIC", "INTERNAL", "CONFIDENTIAL", "RESTRICTED"]),
        FieldSpec("parse_status", type="enum", required=True,
                  enum=["PENDING", "PARSED", "PARTIAL", "FAILED"]),
        FieldSpec("parser_id", nullable=True),
        FieldSpec("parser_version", nullable=True),
        FieldSpec("page_count", type="integer", nullable=True, validator=check_positive_int),
        FieldSpec("validation_status", type="enum", required=True,
                  enum=["CANDIDATE", "APPROVED", "REJECTED"]),
        FieldSpec("status", type="enum", required=True,
                  enum=["ACTIVE", "INACTIVE", "SUPERSEDED"]),
        FieldSpec("version", required=True),
    ],
    required_headings=["文档摘要", "来源与效力说明", "解析说明"],
    extra_validator=_document_extra,
)

# =====================================================================
# 9.3 规范化全文 NORMALIZED.md —— normalized_document/v1
# =====================================================================

NORMALIZED_SPEC = SchemaSpec(
    schema_name="normalized_document/v1",
    primary_id="document_id",
    fields=[
        FieldSpec("document_id", required=True),
        FieldSpec("source_sha256", required=True, validator=check_sha256_field),
        FieldSpec("parser_id", required=True),
        FieldSpec("parser_version", required=True),
        FieldSpec("parse_run_id", required=True),
        FieldSpec("normalization_policy_version", required=True),
        FieldSpec("status", type="enum", required=True,
                  enum=["ACTIVE", "INACTIVE", "SUPERSEDED"]),
        FieldSpec("version", required=True),
    ],
)

# =====================================================================
# 9.4 文档片段 <segment_id>.md —— document_segment/v1
# =====================================================================


def _segment_extra(fm: dict, body: str) -> list[str]:
    errors: list[str] = []
    pf, pt = fm.get("page_from"), fm.get("page_to")
    if pf is not None and pt is not None and int(pf) > int(pt):
        errors.append(f"page_to({pt}) < page_from({pf})")
    cs, ce = fm.get("char_start"), fm.get("char_end")
    if cs is not None and ce is not None and int(cs) > int(ce):
        errors.append(f"char_end({ce}) < char_start({cs})")
    if "原文" not in body:
        errors.append("片段正文缺少 '## 原文' 证据区")
    return errors


SEGMENT_SPEC = SchemaSpec(
    schema_name="document_segment/v1",
    primary_id="segment_id",
    fields=[
        FieldSpec("segment_id", required=True),
        FieldSpec("document_id", required=True),
        FieldSpec("segment_type", type="enum", required=True,
                  enum=["TITLE", "PARAGRAPH", "CLAUSE", "TABLE", "FIGURE",
                        "CAPTION", "LIST", "OTHER"]),
        FieldSpec("heading_path", type="list", element_type="string", required=True),
        FieldSpec("page_from", type="integer", nullable=True, validator=check_positive_int),
        FieldSpec("page_to", type="integer", nullable=True, validator=check_positive_int),
        FieldSpec("sequence", type="integer", required=True, validator=check_positive_int),
        FieldSpec("char_start", type="integer", nullable=True, validator=check_nonneg_int),
        FieldSpec("char_end", type="integer", nullable=True, validator=check_nonneg_int),
        FieldSpec("content_sha256", required=True, validator=check_sha256_field),
        FieldSpec("chunk_policy_version", required=True),
        FieldSpec("parent_segment_id", nullable=True),
        FieldSpec("previous_segment_id", nullable=True),
        FieldSpec("next_segment_id", nullable=True),
        FieldSpec("status", type="enum", required=True, enum=["ACTIVE", "SUPERSEDED"]),
        FieldSpec("version", required=True),
    ],
    required_headings=["原文"],
    extra_validator=_segment_extra,
)

# =====================================================================
# 9.5 实体 <entity_id>.md —— entity/v1
# =====================================================================


def _entity_extra(fm: dict, body: str) -> list[str]:
    errors: list[str] = []
    errors += check_effective_range(fm)
    errors += check_list_nonempty(fm.get("source_ids"), fm)
    if fm.get("status") == "MERGED" and not fm.get("merged_into"):
        errors.append("MERGED 实体必须填写 merged_into")
    conf = fm.get("confidence")
    if conf is not None:
        errors += check_confidence(conf, fm)
    ext = fm.get("extraction")
    if ext is not None:
        for key in ("extractor", "model_id", "model_version", "prompt_template_version"):
            if not ext.get(key):
                errors.append(f"extraction 缺少生成上下文字段: {key}")
    return errors


ENTITY_SPEC = SchemaSpec(
    schema_name="entity/v1",
    primary_id="entity_id",
    fields=[
        FieldSpec("entity_id", required=True),
        FieldSpec("entity_type", required=True),
        FieldSpec("name", required=True),
        FieldSpec("aliases", type="list", element_type="string", required=True),
        FieldSpec("description", nullable=True),
        FieldSpec("domain", required=True),
        FieldSpec("source_ids", type="list", element_type="string", required=True),
        FieldSpec("confidence", type="number", nullable=True),
        FieldSpec("extraction", type="map", nullable=True),
        FieldSpec("validation_status", type="enum", required=True,
                  enum=["CANDIDATE", "IN_REVIEW", "APPROVED", "REJECTED"]),
        FieldSpec("status", type="enum", required=True,
                  enum=["ACTIVE", "INACTIVE", "MERGED", "SUPERSEDED"]),
        FieldSpec("merged_into", nullable=True),
        FieldSpec("effective_from", type="date", nullable=True),
        FieldSpec("effective_to", type="date", nullable=True),
        FieldSpec("version", required=True),
    ],
    required_headings=["定义", "业务说明", "来源证据", "审核说明"],
    extra_validator=_entity_extra,
)

# =====================================================================
# 9.6 关系 <relation_id>.md —— relation/v1
# =====================================================================


def _relation_extra(fm: dict, body: str) -> list[str]:
    errors: list[str] = []
    errors += check_effective_range(fm)
    errors += check_list_nonempty(fm.get("source_ids"), fm)
    if fm.get("source_id") and fm.get("target_id") and fm["source_id"] == fm["target_id"]:
        errors.append(f"默认禁止自环关系（除非类型目录声明 allow_self_loop）: {fm['source_id']}")
    conf = fm.get("confidence")
    if conf is not None:
        errors += check_confidence(conf, fm)
    return errors


RELATION_SPEC = SchemaSpec(
    schema_name="relation/v1",
    primary_id="relation_id",
    fields=[
        FieldSpec("relation_id", required=True),
        FieldSpec("source_id", required=True),
        FieldSpec("relation_type", required=True),
        FieldSpec("target_id", required=True),
        FieldSpec("direction", type="enum", required=True, enum=["DIRECTED"]),
        FieldSpec("statement_id", nullable=True),
        FieldSpec("source_ids", type="list", element_type="string", required=True),
        FieldSpec("confidence", type="number", nullable=True),
        FieldSpec("validation_status", type="enum", required=True,
                  enum=["CANDIDATE", "IN_REVIEW", "APPROVED", "REJECTED"]),
        FieldSpec("status", type="enum", required=True,
                  enum=["ACTIVE", "INACTIVE", "SUPERSEDED"]),
        FieldSpec("effective_from", type="date", nullable=True),
        FieldSpec("effective_to", type="date", nullable=True),
        FieldSpec("version", required=True),
    ],
    required_headings=["语义", "来源证据", "审核说明"],
    extra_validator=_relation_extra,
)

# =====================================================================
# 9.7 知识声明 <statement_id>.md —— statement/v1
# =====================================================================


def _statement_extra(fm: dict, body: str) -> list[str]:
    errors: list[str] = []
    errors += check_effective_range(fm)
    oid, oval = fm.get("object_id"), fm.get("object_value")
    if (oid is None) == (oval is None):
        errors.append("object_id 与 object_value 必须且只能有一个非空")
    if fm.get("value_type") == "OBJECT_REF" and not oid:
        errors.append("value_type=OBJECT_REF 时必须填写 object_id")
    if fm.get("value_type") != "OBJECT_REF" and oid:
        errors.append("value_type 非 OBJECT_REF 时不得填写 object_id")
    if fm.get("source_type") == "DOCUMENT" and not fm.get("source_segment_id"):
        errors.append("文档来源声明必须填写 source_segment_id")
    if fm.get("source_type") == "DERIVED" and not fm.get("derivation_rule_id"):
        errors.append("DERIVED 声明必须填写 derivation_rule_id")
    conf = fm.get("confidence")
    if conf is not None:
        errors += check_confidence(conf, fm)
    return errors


STATEMENT_SPEC = SchemaSpec(
    schema_name="statement/v1",
    primary_id="statement_id",
    fields=[
        FieldSpec("statement_id", required=True),
        FieldSpec("subject_id", required=True),
        FieldSpec("predicate", required=True),
        FieldSpec("object_id", nullable=True),
        FieldSpec("object_value", type="any", nullable=True),
        FieldSpec("value_type", type="enum", required=True,
                  enum=["OBJECT_REF", "STRING", "INTEGER", "DECIMAL", "BOOLEAN",
                        "DATE", "DATETIME", "DURATION", "CODE"]),
        FieldSpec("unit", nullable=True),
        FieldSpec("source_type", type="enum", required=True,
                  enum=["STRUCTURED_DATA", "DOCUMENT", "MANUAL", "DERIVED"]),
        FieldSpec("source_asset_id", required=True),
        FieldSpec("source_record_id", nullable=True),
        FieldSpec("source_segment_id", nullable=True),
        FieldSpec("derivation_rule_id", nullable=True),
        FieldSpec("confidence", type="number", nullable=True),
        FieldSpec("polarity", type="enum", required=True,
                  enum=["AFFIRMED", "NEGATED", "UNCERTAIN"]),
        FieldSpec("validation_status", type="enum", required=True,
                  enum=["CANDIDATE", "IN_REVIEW", "APPROVED", "REJECTED"]),
        FieldSpec("conflict_status", type="enum", required=True,
                  enum=["NONE", "POTENTIAL", "CONFIRMED", "RESOLVED"]),
        FieldSpec("effective_from", type="date", nullable=True),
        FieldSpec("effective_to", type="date", nullable=True),
        FieldSpec("recorded_at", type="timestamp", required=True),
        FieldSpec("status", type="enum", required=True,
                  enum=["ACTIVE", "INACTIVE", "SUPERSEDED"]),
        FieldSpec("version", required=True),
    ],
    required_headings=["规范表达", "来源证据", "冲突与限定", "审核说明"],
    extra_validator=_statement_extra,
)

# =====================================================================
# 9.8 规则 <rule_id>.md —— rule/v1
# =====================================================================


def _rule_extra(fm: dict, body: str) -> list[str]:
    errors: list[str] = []
    errors += check_effective_range(fm)
    pri = fm.get("priority")
    if pri is not None and (isinstance(pri, bool) or not isinstance(pri, int)
                            or not 0 <= pri <= 1000):
        errors.append("priority 必须为 0..1000 的整数")
    errors += check_list_at_least(fm.get("test_case_ids"), fm, 2)
    for key in ("when", "then"):
        if fm.get(key) is not None and not isinstance(fm.get(key), dict):
            errors.append(f"{key} 必须为受控表达式映射")
    if fm.get("execution_mode") == "AUTOMATIC":
        errors.append("AUTOMATIC 规则默认不允许（OD-006：默认全部 ADVISORY/HUMAN_CONFIRM_REQUIRED）")
    return errors


RULE_SPEC = SchemaSpec(
    schema_name="rule/v1",
    primary_id="rule_id",
    fields=[
        FieldSpec("rule_id", required=True),
        FieldSpec("name", required=True),
        FieldSpec("rule_type", type="enum", required=True,
                  enum=["VALIDATION", "ELIGIBILITY", "CALCULATION", "RECOMMENDATION",
                        "ROUTING", "ALERT"]),
        FieldSpec("priority", type="integer", required=True),
        FieldSpec("execution_mode", type="enum", required=True,
                  enum=["AUTOMATIC", "ADVISORY", "HUMAN_CONFIRM_REQUIRED"]),
        FieldSpec("when", type="map", required=True),
        FieldSpec("then", type="map", required=True),
        FieldSpec("else", type="map", nullable=True),
        FieldSpec("required_inputs", type="list", element_type="map", required=True),
        FieldSpec("source_document_id", nullable=True),
        FieldSpec("source_segment_id", nullable=True),
        FieldSpec("test_case_ids", type="list", element_type="string", required=True),
        FieldSpec("validation_status", type="enum", required=True,
                  enum=["CANDIDATE", "IN_REVIEW", "APPROVED", "REJECTED"]),
        FieldSpec("status", type="enum", required=True,
                  enum=["ACTIVE", "INACTIVE", "SUPERSEDED"]),
        FieldSpec("effective_from", type="date", nullable=True),
        FieldSpec("effective_to", type="date", nullable=True),
        FieldSpec("version", required=True),
    ],
    required_headings=["业务解释", "输入与输出", "证据", "人工责任边界", "测试说明"],
    extra_validator=_rule_extra,
)

# =====================================================================
# 9.9 资产目录 90_control/catalog/<asset_id>.md —— asset_catalog/v1
# =====================================================================

ASSET_CATALOG_SPEC = SchemaSpec(
    schema_name="asset_catalog/v1",
    primary_id="asset_id",
    fields=[
        FieldSpec("asset_id", required=True),
        FieldSpec("asset_type", type="enum", required=True,
                  enum=["DATASET", "DOCUMENT_COLLECTION", "ENTITY_SET", "RELATION_SET",
                        "STATEMENT_SET", "RULE_SET", "KNOWLEDGE_PACK", "SERVICE", "PROJECTION"]),
        FieldSpec("name", required=True),
        FieldSpec("domain", required=True),
        FieldSpec("owner", required=True),
        FieldSpec("classification", required=True),
        FieldSpec("authoritative_layer", type="enum", required=True,
                  enum=["01_raw", "02_work", "03_core", "04_serve", "90_control"]),
        FieldSpec("current_version", required=True),
        FieldSpec("location", required=True),
        FieldSpec("upstream_ids", type="list", element_type="string", required=True),
        FieldSpec("downstream_ids", type="list", element_type="string", required=True),
        FieldSpec("status", type="enum", required=True,
                  enum=["ACTIVE", "INACTIVE", "SUPERSEDED"]),
        FieldSpec("version", required=True),
    ],
    required_headings=["业务定义", "内容范围", "上下游", "使用限制", "变更记录"],
)

# =====================================================================
# 9.10 Schema 合同 90_control/schema/<name>/v<major>/SCHEMA.md —— schema_contract/v1
# =====================================================================

SCHEMA_CONTRACT_SPEC = SchemaSpec(
    schema_name="schema_contract/v1",
    primary_id="schema_id",
    fields=[
        FieldSpec("schema_id", required=True),
        FieldSpec("target_schema", required=True),
        FieldSpec("major_version", type="integer", required=True, validator=check_positive_int),
        FieldSpec("compatibility", required=True),
        FieldSpec("primary_id_field", required=True),
        FieldSpec("required_fields", type="list", element_type="string", required=True),
        FieldSpec("allowed_fields", type="list", element_type="string", required=True),
        FieldSpec("enums", type="map", required=True),
        FieldSpec("reference_fields", type="list", element_type="string", required=True),
        FieldSpec("status", required=True),
        FieldSpec("version", required=True),
    ],
    required_headings=["目的", "字段定义", "交叉字段约束", "兼容策略", "合法示例", "非法示例"],
)

# =====================================================================
# 9.11 血缘 90_control/lineage/<domain>/<lineage_id>.md —— lineage/v1
# =====================================================================

LINEAGE_IO = {
    "asset_id": FieldSpec("asset_id", required=True),
    "version": FieldSpec("version", required=True),
    "path": FieldSpec("path", required=True),
    "content_hash": FieldSpec("content_hash", required=True, validator=check_sha256_field),
}


def _lineage_extra(fm: dict, body: str) -> list[str]:
    errors: list[str] = []
    for key in ("inputs", "outputs"):
        errors += check_list_nonempty(fm.get(key), fm)
    s, f = fm.get("started_at"), fm.get("finished_at")
    if s and f and str(s) > str(f):
        errors.append(f"started_at({s}) > finished_at({f})")
    return errors


LINEAGE_SPEC = SchemaSpec(
    schema_name="lineage/v1",
    primary_id="lineage_id",
    fields=[
        FieldSpec("lineage_id", required=True),
        FieldSpec("process_id", required=True),
        FieldSpec("job_id", required=True),
        FieldSpec("inputs", type="list", element_type="map", element_fields=LINEAGE_IO, required=True),
        FieldSpec("outputs", type="list", element_type="map", element_fields=LINEAGE_IO, required=True),
        FieldSpec("transformation_id", required=True),
        FieldSpec("transformation_version", required=True),
        FieldSpec("code_version", required=True),
        FieldSpec("started_at", type="timestamp", required=True),
        FieldSpec("finished_at", type="timestamp", required=True),
        FieldSpec("status", type="enum", required=True,
                  enum=["COMPLETED", "FAILED", "PARTIAL"]),
        FieldSpec("version", required=True),
    ],
    required_headings=["转换说明", "输入", "输出", "已知限制"],
    extra_validator=_lineage_extra,
)

# =====================================================================
# 9.12 质量规则 90_control/quality/rules/<quality_rule_id>.md —— quality_rule/v1
# =====================================================================

QUALITY_RULE_SPEC = SchemaSpec(
    schema_name="quality_rule/v1",
    primary_id="quality_rule_id",
    fields=[
        FieldSpec("quality_rule_id", required=True),
        FieldSpec("name", required=True),
        FieldSpec("target_schema", required=True),
        FieldSpec("target_asset", required=True),
        FieldSpec("dimension", type="enum", required=True,
                  enum=["COMPLETENESS", "UNIQUENESS", "VALIDITY", "CONSISTENCY",
                        "REFERENTIAL_INTEGRITY", "TRACEABILITY", "FRESHNESS", "SECURITY"]),
        FieldSpec("severity", type="enum", required=True,
                  enum=["BLOCKER", "MAJOR", "MINOR", "NOTE"]),
        FieldSpec("expression", required=True),
        FieldSpec("threshold", required=True),
        FieldSpec("on_failure", type="enum", required=True,
                  enum=["BLOCK", "QUARANTINE", "WARN"]),
        FieldSpec("status", type="enum", required=True,
                  enum=["ACTIVE", "INACTIVE", "SUPERSEDED"]),
        FieldSpec("version", required=True),
    ],
)

# =====================================================================
# 9.13 质量结果 90_control/quality/results/<quality_result_id>.md —— quality_result/v1
# =====================================================================


def _quality_result_extra(fm: dict, body: str) -> list[str]:
    errors: list[str] = []
    ev, fc = fm.get("evaluated_count"), fm.get("failed_count")
    if ev is not None and fc is not None and int(fc) > int(ev):
        errors.append(f"failed_count({fc}) > evaluated_count({ev})")
    result = fm.get("result")
    if result == "PASS" and fc:
        errors.append("result=PASS 时 failed_count 必须为 0")
    if result == "FAIL" and not fc:
        errors.append("result=FAIL 时 failed_count 必须大于 0")
    return errors


QUALITY_RESULT_SPEC = SchemaSpec(
    schema_name="quality_result/v1",
    primary_id="quality_result_id",
    fields=[
        FieldSpec("quality_result_id", required=True),
        FieldSpec("quality_rule_id", required=True),
        FieldSpec("quality_rule_version", required=True),
        FieldSpec("job_id", required=True),
        FieldSpec("target_asset", required=True),
        FieldSpec("target_version", required=True),
        FieldSpec("evaluated_count", type="integer", required=True, validator=check_nonneg_int),
        FieldSpec("failed_count", type="integer", required=True, validator=check_nonneg_int),
        FieldSpec("sample_failures", type="list", element_type="map", required=True),
        FieldSpec("result", type="enum", required=True, enum=["PASS", "WARN", "FAIL"]),
        FieldSpec("executed_at", type="timestamp", required=True),
        FieldSpec("status", required=True),
        FieldSpec("version", required=True),
    ],
    extra_validator=_quality_result_extra,
)

# =====================================================================
# 9.14 任务状态 90_control/jobs/<job_id>/STATUS.md —— job_status/v1
# =====================================================================

from ..states import JOB_STATES  # noqa: E402


def _job_status_extra(fm: dict, body: str) -> list[str]:
    errors: list[str] = []
    from ..states import is_job_terminal

    prog = fm.get("progress")
    if prog is not None and (isinstance(prog, bool) or not isinstance(prog, int)
                             or not 0 <= prog <= 100):
        errors.append("progress 必须为 0..100 的整数")
    if is_job_terminal(fm.get("status", "")) and not fm.get("finished_at"):
        errors.append("终态任务必须填写 finished_at")
    if fm.get("status") == "FAILED" and not fm.get("error_code"):
        errors.append("FAILED 任务必须填写 error_code")
    if fm.get("retry_of"):
        import re as _re
        if not _re.match(r"^JOB-[A-Z0-9_-]+-\d+$", str(fm["retry_of"])):
            errors.append(f"retry_of 非法任务ID: {fm['retry_of']}")
    return errors


JOB_STATUS_SPEC = SchemaSpec(
    schema_name="job_status/v1",
    primary_id="job_id",
    fields=[
        FieldSpec("job_id", required=True),
        FieldSpec("job_type", required=True),
        FieldSpec("status", type="enum", required=True, enum=list(JOB_STATES)),
        FieldSpec("requested_by", required=True),
        FieldSpec("idempotency_key", required=True),
        FieldSpec("input_refs", type="list", element_type="map", required=True),
        FieldSpec("output_refs", type="list", element_type="map", required=True),
        FieldSpec("started_at", type="timestamp", required=True),
        FieldSpec("updated_at", type="timestamp", required=True),
        FieldSpec("finished_at", type="timestamp", nullable=True),
        FieldSpec("progress", type="integer", required=True),
        FieldSpec("error_code", nullable=True),
        FieldSpec("error_message", nullable=True),
        FieldSpec("retry_of", nullable=True),
        FieldSpec("publish_status", type="enum", required=True,
                  enum=["NOT_APPLICABLE", "NOT_PUBLISHED", "PUBLISHED"]),
        FieldSpec("version", required=True),
    ],
    required_headings=["当前摘要", "输入输出", "错误与恢复建议"],
    extra_validator=_job_status_extra,
)

# =====================================================================
# 9.15 运行报告 RUN_REPORT.md —— run_report/v1
# =====================================================================


def _run_report_extra(fm: dict, body: str) -> list[str]:
    errors: list[str] = []
    for key in ("input_count", "output_count", "rejected_count",
                "warning_count", "error_count"):
        v = fm.get(key)
        if v is not None and (isinstance(v, bool) or not isinstance(v, int) or v < 0):
            errors.append(f"{key} 必须为 >=0 的整数")
    s, f = fm.get("started_at"), fm.get("finished_at")
    if s and f and str(s) > str(f):
        errors.append(f"started_at({s}) > finished_at({f})")
    return errors


RUN_REPORT_SPEC = SchemaSpec(
    schema_name="run_report/v1",
    primary_id="job_id",
    fields=[
        FieldSpec("job_id", required=True),
        FieldSpec("final_status", type="enum", required=True,
                  enum=["COMPLETED", "FAILED", "CANCELLED", "BLOCKED"]),
        FieldSpec("started_at", type="timestamp", required=True),
        FieldSpec("finished_at", type="timestamp", required=True),
        FieldSpec("duration_ms", type="integer", required=True, validator=check_nonneg_int),
        FieldSpec("input_count", type="integer", required=True),
        FieldSpec("output_count", type="integer", required=True),
        FieldSpec("rejected_count", type="integer", required=True),
        FieldSpec("warning_count", type="integer", required=True),
        FieldSpec("error_count", type="integer", required=True),
        FieldSpec("quality_summary", type="map", required=True),
        FieldSpec("log_sha256", required=True, validator=check_sha256_field),
        FieldSpec("status", required=True),
        FieldSpec("version", required=True),
    ],
    required_headings=["执行摘要", "输入与输出", "质量结果", "警告与错误",
                       "可复现信息", "非声明事项"],
    extra_validator=_run_report_extra,
)

# =====================================================================
# 9.16 发布记录 03_core/<domain>/version=*/RELEASE.md —— release/v1
# =====================================================================

RELEASE_ASSET = {
    "path": FieldSpec("path", required=True),
    "schema": FieldSpec("schema", required=True),
    "asset_id": FieldSpec("asset_id", required=True),
    "asset_version": FieldSpec("asset_version", required=True),
    "sha256": FieldSpec("sha256", required=True, validator=check_sha256_field),
}


def _release_extra(fm: dict, body: str) -> list[str]:
    errors: list[str] = []
    errors += check_list_nonempty(fm.get("asset_manifest"), fm)
    errors += check_list_nonempty(fm.get("quality_gate_results"), fm)
    if fm.get("status") == "PUBLISHED" and not fm.get("approval_decision_ids"):
        errors.append("需要人工批准的资产发布必须引用 approval_decision_ids")
    prev = fm.get("previous_version")
    if prev and str(prev) == str(fm.get("release_version")):
        errors.append("previous_version 不能等于 release_version")
    return errors


RELEASE_SPEC = SchemaSpec(
    schema_name="release/v1",
    primary_id="release_id",
    fields=[
        FieldSpec("release_id", required=True),
        FieldSpec("domain", required=True),
        FieldSpec("release_version", required=True),
        FieldSpec("previous_version", nullable=True),
        FieldSpec("asset_manifest", type="list", element_type="map",
                  element_fields=RELEASE_ASSET, required=True),
        FieldSpec("quality_gate_results", type="list", element_type="map", required=True),
        FieldSpec("approval_decision_ids", type="list", element_type="string", required=True),
        FieldSpec("released_by", required=True),
        FieldSpec("released_at", type="timestamp", required=True),
        FieldSpec("status", type="enum", required=True, enum=["PUBLISHED", "REVOKED"]),
        FieldSpec("version", required=True),
    ],
    extra_validator=_release_extra,
)

# =====================================================================
# 9.17 当前指针 CURRENT.md —— current_pointer/v1
# =====================================================================


def _current_extra(fm: dict, body: str) -> list[str]:
    import re as _re

    errors: list[str] = []
    scope_type, scope_id = fm.get("scope_type"), fm.get("scope_id")
    if scope_type == "CORE_DOMAIN" and not _re.match(r"^[a-z][a-z0-9_]{1,63}$", str(scope_id or "")):
        errors.append(f"CORE_DOMAIN 的 scope_id 必须为合法业务域: {scope_id!r}")
    if scope_type == "SERVICE" and not (
            _re.match(r"^[a-z][a-z0-9_]{1,63}$", str(scope_id or ""))
            or _re.match(r"^[A-Z][A-Z0-9_-]{2,127}$", str(scope_id or ""))):
        errors.append(f"SERVICE 的 scope_id 必须为合法服务目录名或服务ID: {scope_id!r}")
    return errors


CURRENT_SPEC = SchemaSpec(
    schema_name="current_pointer/v1",
    fields=[
        FieldSpec("scope_type", type="enum", required=True,
                  enum=["CORE_DOMAIN", "SERVICE"]),
        FieldSpec("scope_id", required=True),
        FieldSpec("target_version", required=True),
        FieldSpec("target_release_id", required=True),
        FieldSpec("target_manifest_sha256", required=True, validator=check_sha256_field),
        FieldSpec("switched_by", required=True),
        FieldSpec("switched_at", type="timestamp", required=True),
        FieldSpec("reason", required=True),
        FieldSpec("status", type="enum", required=True, enum=["ACTIVE"]),
        FieldSpec("version", required=True),
    ],
    required_headings=["当前活动版本", "切换说明", "回滚说明"],
    extra_validator=_current_extra,
)

# =====================================================================
# 9.18 投影记录 04_serve/<service_id>/version=*/PROJECTION.md —— projection/v1
# =====================================================================

PROJECTION_SPEC = SchemaSpec(
    schema_name="projection/v1",
    primary_id="projection_id",
    fields=[
        FieldSpec("projection_id", required=True),
        FieldSpec("service_id", required=True),
        FieldSpec("projection_version", required=True),
        FieldSpec("source_core_releases", type="list", element_type="string", required=True),
        FieldSpec("builder_id", required=True),
        FieldSpec("builder_version", required=True),
        FieldSpec("configuration_hash", required=True),
        FieldSpec("files", type="list", element_type="map", required=True),
        FieldSpec("logical_hashes", type="list", element_type="map", required=True),
        FieldSpec("built_at", type="timestamp", required=True),
        FieldSpec("verification_status", type="enum", required=True,
                  enum=["VERIFIED", "FAILED", "PENDING"]),
        FieldSpec("status", type="enum", required=True,
                  enum=["ACTIVE", "INACTIVE", "SUPERSEDED"]),
        FieldSpec("version", required=True),
    ],
)

# =====================================================================
# 9.19 审核决定 90_control/decisions/<decision_id>.md —— review_decision/v1
# =====================================================================

REVIEW_DECISION_SPEC = SchemaSpec(
    schema_name="review_decision/v1",
    primary_id="decision_id",
    fields=[
        FieldSpec("decision_id", required=True),
        FieldSpec("object_refs", type="list", element_type="string", required=True),
        FieldSpec("decision", type="enum", required=True,
                  enum=["APPROVE", "REJECT", "REQUEST_CHANGES", "WAIVE"]),
        FieldSpec("decided_by", required=True),
        FieldSpec("role", required=True),
        FieldSpec("decided_at", type="timestamp", required=True),
        FieldSpec("reason", required=True),
        FieldSpec("conditions", type="list", element_type="string", required=True),
        FieldSpec("evidence_refs", type="list", element_type="string", required=True),
        FieldSpec("status", required=True),
        FieldSpec("version", required=True),
    ],
)

# =====================================================================
# 9.21 类型与受控词汇 90_control/schema/vocabulary/<term_id>.md —— vocabulary_term/v1
# =====================================================================


def _vocabulary_extra(fm: dict, body: str) -> list[str]:
    errors: list[str] = []
    kind = fm.get("term_kind")
    if kind == "RELATION_TYPE":
        for key in ("source_entity_types", "target_entity_types", "symmetric",
                    "transitive", "allow_self_loop"):
            if fm.get(key) is None:
                errors.append(f"RELATION_TYPE 必须声明 {key}")
    if kind == "PREDICATE":
        for key in ("value_types", "cardinality"):
            if fm.get(key) is None:
                errors.append(f"PREDICATE 必须声明 {key}")
    return errors


VOCABULARY_SPEC = SchemaSpec(
    schema_name="vocabulary_term/v1",
    primary_id="term_id",
    fields=[
        FieldSpec("term_id", required=True),
        FieldSpec("term_kind", type="enum", required=True,
                  enum=["ENTITY_TYPE", "RELATION_TYPE", "PREDICATE", "CODE", "UNIT"]),
        FieldSpec("name", required=True),
        FieldSpec("definition", required=True),
        FieldSpec("domain", required=True),
        FieldSpec("parent_term_id", nullable=True),
        FieldSpec("aliases", type="list", element_type="string", required=True),
        FieldSpec("allowed_source_types", type="list", element_type="string", required=True),
        FieldSpec("source_entity_types", type="list", element_type="string", nullable=True),
        FieldSpec("target_entity_types", type="list", element_type="string", nullable=True),
        FieldSpec("symmetric", type="boolean", nullable=True),
        FieldSpec("transitive", type="boolean", nullable=True),
        FieldSpec("allow_self_loop", type="boolean", nullable=True),
        FieldSpec("value_types", type="list", element_type="string", nullable=True),
        FieldSpec("cardinality", nullable=True),
        FieldSpec("unit_terms", type="list", element_type="string", nullable=True),
        FieldSpec("status", type="enum", required=True,
                  enum=["ACTIVE", "INACTIVE", "SUPERSEDED"]),
        FieldSpec("version", required=True),
    ],
    required_headings=["定义", "使用约束", "示例", "变更记录"],
    extra_validator=_vocabulary_extra,
)

# =====================================================================
# 9.22 数据映射 90_control/schema/mappings/<mapping_id>.md —— data_mapping/v1
# =====================================================================

FIELD_MAPPING = {
    "source_field": FieldSpec("source_field", required=True),
    "target_field": FieldSpec("target_field", required=True),
    "target_type": FieldSpec("target_type", required=True),
    "missing_policy": FieldSpec("missing_policy", required=True),
    "transformation_id": FieldSpec("transformation_id", nullable=True),
}


def _mapping_extra(fm: dict, body: str) -> list[str]:
    return check_list_nonempty(fm.get("field_mappings"), fm)


DATA_MAPPING_SPEC = SchemaSpec(
    schema_name="data_mapping/v1",
    primary_id="mapping_id",
    fields=[
        FieldSpec("mapping_id", required=True),
        FieldSpec("source_schema", required=True),
        FieldSpec("target_schema", required=True),
        FieldSpec("field_mappings", type="list", element_type="map",
                  element_fields=FIELD_MAPPING, required=True),
        FieldSpec("key_policy", required=True),
        FieldSpec("null_policy", required=True),
        FieldSpec("reject_policy", required=True),
        FieldSpec("status", type="enum", required=True,
                  enum=["ACTIVE", "INACTIVE", "SUPERSEDED"]),
        FieldSpec("version", required=True),
    ],
    extra_validator=_mapping_extra,
)

# =====================================================================
# 9.23 解析、切片与抽取配置 90_control/schema/policies/<policy_id>.md —— processing_policy/v1
# =====================================================================


def _policy_extra(fm: dict, body: str) -> list[str]:
    errors: list[str] = []
    params = fm.get("parameters") or {}
    if params.get("calls_model"):
        for key in ("provider_adapter", "model_id", "model_version",
                    "prompt_template_id", "prompt_template_version",
                    "temperature", "seed", "response_schema"):
            if fm.get(key) is None:
                errors.append(f"调用模型时必须记录 {key}（§9.23）")
    return errors


PROCESSING_POLICY_SPEC = SchemaSpec(
    schema_name="processing_policy/v1",
    primary_id="policy_id",
    fields=[
        FieldSpec("policy_id", required=True),
        FieldSpec("policy_kind", type="enum", required=True,
                  enum=["PARSE", "NORMALIZE", "CHUNK", "EXTRACT", "EMBED", "RANK"]),
        FieldSpec("implementation_id", required=True),
        FieldSpec("implementation_version", required=True),
        FieldSpec("parameters", type="map", required=True),
        FieldSpec("input_schemas", type="list", element_type="string", required=True),
        FieldSpec("output_schemas", type="list", element_type="string", required=True),
        FieldSpec("deterministic", type="boolean", required=True),
        FieldSpec("provider_adapter", nullable=True),
        FieldSpec("model_id", nullable=True),
        FieldSpec("model_version", nullable=True),
        FieldSpec("prompt_template_id", nullable=True),
        FieldSpec("prompt_template_version", nullable=True),
        FieldSpec("temperature", type="number", nullable=True),
        FieldSpec("seed", type="integer", nullable=True),
        FieldSpec("response_schema", nullable=True),
        FieldSpec("status", type="enum", required=True,
                  enum=["ACTIVE", "INACTIVE", "SUPERSEDED"]),
        FieldSpec("version", required=True),
    ],
    extra_validator=_policy_extra,
)

# =====================================================================
# 9.24 知识包 03_core/<domain>/version=*/packs/<knowledge_pack_id>.md —— knowledge_pack/v1
# =====================================================================

KNOWLEDGE_PACK_SPEC = SchemaSpec(
    schema_name="knowledge_pack/v1",
    primary_id="knowledge_pack_id",
    fields=[
        FieldSpec("knowledge_pack_id", required=True),
        FieldSpec("name", required=True),
        FieldSpec("domain", required=True),
        FieldSpec("intended_consumers", type="list", element_type="string", required=True),
        FieldSpec("entity_ids", type="list", element_type="string", required=True),
        FieldSpec("relation_ids", type="list", element_type="string", required=True),
        FieldSpec("statement_ids", type="list", element_type="string", required=True),
        FieldSpec("rule_ids", type="list", element_type="string", required=True),
        FieldSpec("document_ids", type="list", element_type="string", required=True),
        FieldSpec("scope_filters", type="list", element_type="map", required=True),
        FieldSpec("source_release_ids", type="list", element_type="string", required=True),
        FieldSpec("status", type="enum", required=True,
                  enum=["ACTIVE", "INACTIVE", "SUPERSEDED"]),
        FieldSpec("version", required=True),
    ],
)

# =====================================================================
# 9.25 服务目录 90_control/catalog/services/<service_id>.md —— service_catalog/v1
# =====================================================================

SERVICE_CATALOG_SPEC = SchemaSpec(
    schema_name="service_catalog/v1",
    primary_id="service_id",
    fields=[
        FieldSpec("service_id", required=True),
        FieldSpec("name", required=True),
        FieldSpec("service_type", type="enum", required=True,
                  enum=["DATA_QUERY", "EXTRACTION", "SEARCH", "GRAPH",
                        "RULE", "EVIDENCE", "CATALOG"]),
        FieldSpec("input_contract", type="map", required=True),
        FieldSpec("output_contract", type="map", required=True),
        FieldSpec("source_projection_id", required=True),
        FieldSpec("authorization_policy", required=True),
        FieldSpec("limits", type="map", required=True),
        FieldSpec("sla_class", required=True),
        FieldSpec("current_version", required=True),
        FieldSpec("status", type="enum", required=True,
                  enum=["ACTIVE", "INACTIVE", "SUPERSEDED"]),
        FieldSpec("version", required=True),
    ],
    required_headings=["服务目的", "输入输出", "数据与知识范围", "限制和责任边界", "示例"],
)

# =====================================================================
# 14.3 规则测试用例 90_control/quality/rule_tests/<test_case_id>.md —— rule_test_case/v1
# =====================================================================

RULE_TEST_CASE_SPEC = SchemaSpec(
    schema_name="rule_test_case/v1",
    primary_id="test_case_id",
    fields=[
        FieldSpec("test_case_id", required=True),
        FieldSpec("rule_id", required=True),
        FieldSpec("rule_version", required=True),
        FieldSpec("input_facts", type="map", required=True),
        FieldSpec("expected_match", type="boolean", required=True),
        FieldSpec("expected_outcome", type="map", required=True),
        FieldSpec("expected_missing_inputs", type="list", element_type="string", required=True),
        FieldSpec("status", required=True),
        FieldSpec("version", required=True),
    ],
)

# =====================================================================
# 17.4 门禁报告 GATE_REPORT.md —— gate_report/v1
# =====================================================================

GATE_REPORT_SPEC = SchemaSpec(
    schema_name="gate_report/v1",
    primary_id="gate_id",
    fields=[
        FieldSpec("gate_id", required=True),
        FieldSpec("review_object", required=True),
        FieldSpec("target_transition", required=True),
        FieldSpec("decision", type="enum", required=True,
                  enum=["PASS_FOR_NEXT_GATE", "PASS_WITH_REQUIRED_CHANGES",
                        "RETURN_TO_WORK", "BLOCKED", "INSUFFICIENT_EVIDENCE"]),
        FieldSpec("substantive_review", required=True),
        FieldSpec("findings", type="list", element_type="map", required=True),
        FieldSpec("reviewed_by", required=True),
        FieldSpec("reviewed_at", type="timestamp", required=True),
        FieldSpec("baseline_state", required=True),
        FieldSpec("frozen", type="boolean", required=True),
        FieldSpec("status", required=True),
        FieldSpec("version", required=True),
    ],
)

# =====================================================================
# 注册表
# =====================================================================

SCHEMA_REGISTRY: dict[str, SchemaSpec] = {
    spec.schema_name: spec
    for spec in [
        MANIFEST_SPEC, DOCUMENT_SPEC, NORMALIZED_SPEC, SEGMENT_SPEC,
        ENTITY_SPEC, RELATION_SPEC, STATEMENT_SPEC, RULE_SPEC,
        ASSET_CATALOG_SPEC, SCHEMA_CONTRACT_SPEC, LINEAGE_SPEC,
        QUALITY_RULE_SPEC, QUALITY_RESULT_SPEC, JOB_STATUS_SPEC, RUN_REPORT_SPEC,
        RELEASE_SPEC, CURRENT_SPEC, PROJECTION_SPEC, REVIEW_DECISION_SPEC,
        VOCABULARY_SPEC, DATA_MAPPING_SPEC, PROCESSING_POLICY_SPEC,
        KNOWLEDGE_PACK_SPEC, SERVICE_CATALOG_SPEC, RULE_TEST_CASE_SPEC,
        GATE_REPORT_SPEC,
    ]
}


def get_spec(schema_name: str) -> SchemaSpec:
    spec = SCHEMA_REGISTRY.get(schema_name)
    if spec is None:
        from ..errors import UsageError

        raise UsageError(f"未知合同 schema: {schema_name!r}")
    return spec
