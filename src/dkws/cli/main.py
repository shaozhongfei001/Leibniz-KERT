"""DKWS CLI（规格 §12）。P0：init / inspect / validate / recover。"""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

import typer

from .. import __version__
from ..domain import timeutil, workspace as ws_mod
from ..domain.errors import (
    DKWSException,
    EXIT_CONFLICT,
    EXIT_INTERNAL,
    EXIT_OK,
    EXIT_QUALITY_GATE,
    EXIT_USAGE,
)
from ..infrastructure import locks as locks_mod

app = typer.Typer(
    no_args_is_help=True,
    add_completion=False,
    help="DKWS 文件目录型数据知识服务模拟平台（DKWS-SPEC-001 V1.0）",
)

_COMMON = "text|json"


def _emit(output: str, data: dict, *, status: str = "OK",
          errors: list | None = None, human: str | None = None) -> None:
    """统一输出：--output json 走 §10.8 标准响应 JSON；否则人类可读摘要。"""
    if output == "json":
        payload = {
            "request_id": f"REQ-CLI-{uuid.uuid4().hex[:8].upper()}",
            "status": status,
            "data": data,
            "errors": errors or [],
            "meta": {
                "service_version": __version__,
                "generated_at": timeutil.ts_utc(),
            },
        }
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        typer.echo(human or json.dumps(data, ensure_ascii=False, indent=2, default=str))


def _exit_code_for(exc: DKWSException) -> int:
    if exc.error_code == "WORKSPACE_LOCKED":
        return EXIT_CONFLICT
    if exc.error_code == "QUALITY_GATE_FAILED":
        return EXIT_QUALITY_GATE
    return exc.exit_code


def main() -> None:
    try:
        app()
    except DKWSException as exc:
        msg = f"ERROR[{exc.error_code}] {exc.message}"
        typer.echo(msg, err=True)
        raise typer.Exit(_exit_code_for(exc))
    except typer.Exit:
        raise
    except Exception as exc:  # 内部错误
        typer.echo(f"ERROR[INTERNAL_ERROR] {exc}", err=True)
        raise typer.Exit(EXIT_INTERNAL)


@app.command("init")
def init_cmd(
    workspace_path: Path = typer.Option(..., "--workspace", "-w",
                                       help="目标工作区目录"),
    force: bool = typer.Option(False, "--force",
                               help="允许在非空目录初始化（默认禁止）"),
    owner: str = typer.Option("svc_dkws", "--owner", help="初始化主体"),
    output: str = typer.Option("text", "--output", help=_COMMON),
    dry_run: bool = typer.Option(False, "--dry-run",
                                 help="仅展示将创建的目录与文件"),
):
    """初始化符合合同的工作区（FR-WS-001）。"""
    ws = Path(workspace_path)
    if dry_run:
        dirs = list(ws_mod.TOP_LEVEL_DIRS) + [f"90_control/{d}" for d in ws_mod.CONTROL_SUBDIRS]
        files = [ws_mod.MARKER_FILE, "90_control/README.md"]
        _emit(output, {"dry_run": True, "dirs": dirs, "files": files},
              human="将创建目录:\n  " + "\n  ".join(dirs) + "\n将创建文件:\n  " + "\n  ".join(files))
        return
    result = ws_mod.init_workspace(ws, force=force, owner=owner)
    if result.already_initialized:
        _emit(output, {"status": "ALREADY_INITIALIZED", "workspace": str(ws)},
              human=f"工作区已初始化: {ws}")
        return
    _emit(output, {"status": "CREATED", "dirs": result.created_dirs,
                   "files": result.created_files, "workspace": str(ws)},
          human=f"已初始化工作区: {ws}\n  目录: {len(result.created_dirs)} 个\n  文件: {len(result.created_files)} 个")


@app.command("inspect")
def inspect_cmd(
    workspace_path: Path = typer.Option(..., "--workspace", "-w"),
    output: str = typer.Option("text", "--output", help=_COMMON),
):
    """检查目录与概要状态（FR-WS-001/005）。"""
    data = ws_mod.inspect_workspace(Path(workspace_path))
    if output == "json":
        _emit(output, data)
        return
    lines = [f"工作区: {data['workspace']}"]
    for d in ws_mod.TOP_LEVEL_DIRS:
        e = data.get(d, {})
        if not e.get("present"):
            lines.append(f"  {d}: 缺失")
            continue
        domains = ", ".join(e.get("domains", [])) or "-"
        lines.append(f"  {d}: 域=[{domains}] 子目录={e.get('subdirs', [])}")
    lines.append(f"  CURRENT 指针: {len(data.get('current_pointers', []))} 个")
    lines.append(f"  过期锁: {data.get('stale_locks', 0)} 个")
    _emit(output, data, human="\n".join(lines))


@app.command("validate")
def validate_cmd(
    workspace_path: Path = typer.Option(..., "--workspace", "-w"),
    mode: str = typer.Option("fast", "--mode", help="fast|full"),
    output: str = typer.Option("text", "--output", help=_COMMON),
):
    """工作区一致性检查（FR-WS-005）。发现 BLOCKER/MAJOR 时退出码 3。"""
    ws = Path(workspace_path)
    findings = ws_mod.check_workspace(ws, mode=mode)
    blockers = [f for f in findings if f.level in ("BLOCKER", "MAJOR")]
    data = {
        "mode": mode,
        "result": "PASS" if not blockers else "FAIL",
        "findings": [
            {"level": f.level, "code": f.code, "message": f.message, "path": f.path}
            for f in findings
        ],
    }
    if output == "json":
        _emit(output, data)
    else:
        for f in findings:
            typer.echo(f"[{f.level}] {f.code} {f.message} ({f.path})")
        typer.echo(f"结果: {data['result']}（共 {len(findings)} 项发现）")
    if blockers:
        raise typer.Exit(EXIT_QUALITY_GATE)


@app.command("ingest")
def ingest_cmd(
    workspace_path: Path = typer.Option(..., "--workspace", "-w"),
    domain: str = typer.Option(..., "--domain", "-d", help="业务域（^[a-z][a-z0-9_]{1,63}$）"),
    source: list[str] = typer.Option(..., "--source", "-s",
                                     help="源文件（可重复指定）"),
    idempotency_key: str = typer.Option(..., "--idempotency-key",
                                        help="幂等键（重试稳定）"),
    source_system: str = typer.Option("MANUAL_UPLOAD", "--source-system"),
    owner: str = typer.Option("svc_ingestor", "--owner"),
    output: str = typer.Option("text", "--output", help=_COMMON),
    dry_run: bool = typer.Option(False, "--dry-run"),
):
    """接入结构化/文档文件并生成不可变批次（FR-ING-001~006）。"""
    from ..application.ingest import Ingestor

    ing = Ingestor(Path(workspace_path), owner=owner, dry_run=dry_run)
    result = ing.ingest(domain, [Path(s) for s in source], idempotency_key,
                        source_system=source_system)
    if dry_run:
        _emit(output, {"dry_run": True, "plan": result.plan},
              human="将创建:\n  " + "\n  ".join(result.plan))
        return
    data = {
        "batch_id": result.batch_id,
        "job_id": result.job_id,
        "noop": result.noop,
        "manifest": result.manifest_rel,
        "files": result.files,
    }
    if result.noop:
        _emit(output, data, human=f"NO_OP：幂等命中，原批次 {result.batch_id}（job {result.job_id}）")
    else:
        _emit(output, data,
              human=f"接入完成: 批次 {result.batch_id}（job {result.job_id}）\n"
                    f"  清单: {result.manifest_rel}\n"
                    f"  文件: {len(result.files)} 个")


@app.command("process-data")
def process_data_cmd(
    workspace_path: Path = typer.Option(..., "--workspace", "-w"),
    batch: str = typer.Option(..., "--batch", help="Raw 批次 ID"),
    domain: str = typer.Option(..., "--domain", "-d", help="业务域"),
    schema: str = typer.Option(..., "--schema", help="目标数据集 ID"),
    mapping: str | None = typer.Option(None, "--mapping", help="mapping_id（控制目录）"),
    mapping_json: str | None = typer.Option(None, "--mapping-json", help="内联映射 JSON"),
    key: str | None = typer.Option(None, "--key", help="主键字段"),
    owner: str = typer.Option("svc_processor", "--owner"),
    output: str = typer.Option("text", "--output", help=_COMMON),
    dry_run: bool = typer.Option(False, "--dry-run"),
):
    """清洗结构化数据并生成 Parquet（FR-DATA-001~005）。"""
    from ..application.process_data import DataProcessor

    proc = DataProcessor(Path(workspace_path), owner=owner, dry_run=dry_run)
    r = proc.process(domain, batch, schema, mapping_id=mapping,
                     key_field=key, mapping_json=mapping_json)
    if dry_run:
        _emit(output, {"dry_run": True, "plan": r.plan},
              human="将创建:\n  " + "\n  ".join(r.plan))
        return
    data = {
        "run_id": r.run_id, "job_id": r.job_id,
        "input_count": r.input_count, "passed_count": r.passed_count,
        "rejected_count": r.rejected_count,
        "normalized": r.normalized_rel, "rejected": r.rejected_rel,
    }
    _emit(output, data,
          human=f"加工完成: run={r.run_id}（job {r.job_id}）\n"
                f"  输入 {r.input_count} → 通过 {r.passed_count} / 拒绝 {r.rejected_count}\n"
                f"  标准化: {r.normalized_rel}\n"
                f"  拒绝: {r.rejected_rel or '（无）'}")


@app.command("parse-doc")
def parse_doc_cmd(
    workspace_path: Path = typer.Option(..., "--workspace", "-w"),
    batch: str = typer.Option(..., "--batch", help="Raw 批次 ID"),
    domain: str = typer.Option(..., "--domain", "-d"),
    chunk_policy: str = typer.Option("chunk/v1", "--chunk-policy"),
    owner: str = typer.Option("svc_parser", "--owner"),
    output: str = typer.Option("text", "--output", help=_COMMON),
    dry_run: bool = typer.Option(False, "--dry-run"),
):
    """解析文档并生成稳定切片（FR-DOC-001~005）。"""
    from ..application.parse_doc import DocumentParserService

    svc = DocumentParserService(Path(workspace_path), owner=owner, dry_run=dry_run)
    r = svc.parse(domain, batch, chunk_policy=chunk_policy)
    if dry_run:
        _emit(output, {"dry_run": True, "plan": r.plan},
              human="将创建:\n  " + "\n  ".join(r.plan))
        return
    data = {"run_id": r.run_id, "job_id": r.job_id,
            "documents": r.document_ids, "segment_count": r.segment_count,
            "warnings": r.warnings}
    _emit(output, data,
          human=f"解析完成: run={r.run_id}（job {r.job_id}）\n"
                f"  文档 {len(r.document_ids)} 个，片段 {r.segment_count} 个\n"
                + ("".join(f"  [WARN] {w}\n" for w in r.warnings[:5])))


@app.command("extract")
def extract_cmd(
    workspace_path: Path = typer.Option(..., "--workspace", "-w"),
    domain: str = typer.Option(..., "--domain", "-d"),
    batch: str = typer.Option(..., "--batch", help="Raw 批次 ID"),
    run_id: str | None = typer.Option(None, "--run-id", help="解析 run（默认最近一次）"),
    extractor: str = typer.Option("deterministic_extractor", "--extractor"),
    owner: str = typer.Option("svc_extractor", "--owner"),
    output: str = typer.Option("text", "--output", help=_COMMON),
    dry_run: bool = typer.Option(False, "--dry-run"),
):
    """从片段生成知识候选（实体/关系/声明/规则）（FR-KNW-001~003）。"""
    from ..application.extract import KnowledgeExtractor

    ext = KnowledgeExtractor(Path(workspace_path), owner=owner, dry_run=dry_run,
                             extractor_id=extractor)
    r = ext.extract(domain, batch, run_id=run_id)
    if dry_run:
        _emit(output, {"dry_run": True, "plan": r.plan},
              human="将创建:\n  " + "\n  ".join(r.plan))
        return
    data = {"run_id": r.run_id, "job_id": r.job_id, "candidates": r.candidates}
    _emit(output, data,
          human=f"抽取完成: run={r.run_id}（job {r.job_id}）\n"
                f"  候选 {len(r.candidates)} 个，全部 CANDIDATE、NOT_PUBLISHED")


@app.command("review")
def review_cmd(
    workspace_path: Path = typer.Option(..., "--workspace", "-w"),
    domain: str = typer.Option(..., "--domain", "-d"),
    objects: list[str] = typer.Option(..., "--objects", "-o",
                                      help="候选对象引用（可重复）"),
    decision: str = typer.Option(..., "--decision",
                                 help="APPROVE/REJECT/REQUEST_CHANGES/WAIVE"),
    reason: str = typer.Option(..., "--reason", help="审核理由（驳回必填）"),
    run_id: str | None = typer.Option(None, "--run-id"),
    decided_by: str = typer.Option("reviewer", "--decided-by"),
    owner: str = typer.Option("svc_review", "--owner"),
    output: str = typer.Option("text", "--output", help=_COMMON),
    dry_run: bool = typer.Option(False, "--dry-run"),
):
    """记录审核决定（FR-KNW-005/006）。"""
    from ..application.review import ReviewService

    svc = ReviewService(Path(workspace_path), owner=owner, dry_run=dry_run)
    r = svc.review(domain, run_id=run_id, object_refs=objects,
                   decision=decision, reason=reason, decided_by=decided_by)
    data = {"job_id": r.job_id, "decisions": r.decisions}
    _emit(output, data,
          human=f"审核完成（job {r.job_id}）: {decision}\n"
                + "\n".join(f"  - {d['object_ref']} → {d['validation_status']} ({d['decision_id']})"
                            for d in r.decisions))


@app.command("publish")
def publish_cmd(
    workspace_path: Path = typer.Option(..., "--workspace", "-w"),
    domain: str = typer.Option(..., "--domain", "-d"),
    run_id: str | None = typer.Option(None, "--run-id", help="候选 run"),
    release_version: str | None = typer.Option(None, "--release-version",
                                               help="发布版本（默认递增）"),
    owner: str = typer.Option("svc_publisher", "--owner"),
    output: str = typer.Option("text", "--output", help=_COMMON),
    dry_run: bool = typer.Option(False, "--dry-run"),
):
    """发布 APPROVED 资产到 03_core 并更新 CURRENT（FR-PUB-001~004）。"""
    from ..application.publish import Publisher

    pub = Publisher(Path(workspace_path), owner=owner, dry_run=dry_run)
    r = pub.publish(domain, run_id=run_id, release_version=release_version)
    if dry_run:
        _emit(output, {"dry_run": True, "plan": r.plan},
              human="将创建:\n  " + "\n  ".join(r.plan))
        return
    _emit(output, {"release_version": r.release_version, "job_id": r.job_id,
                   "asset_count": r.asset_count, "core_dir": r.core_dir},
          human=f"发布完成: version={r.release_version}（job {r.job_id}）\n"
                f"  资产 {r.asset_count} 个 → {r.core_dir}\n"
                f"  CURRENT.md 已切换")


@app.command("rollback")
def rollback_cmd(
    workspace_path: Path = typer.Option(..., "--workspace", "-w"),
    scope: str = typer.Option(..., "--scope", help="scope_id（域或服务ID）"),
    scope_type: str = typer.Option("CORE_DOMAIN", "--scope-type",
                                   help="CORE_DOMAIN|SERVICE"),
    to_version: str = typer.Option(..., "--to-version"),
    reason: str = typer.Option(..., "--reason", help="回滚原因"),
    owner: str = typer.Option("svc_operator", "--owner"),
    output: str = typer.Option("text", "--output", help=_COMMON),
    dry_run: bool = typer.Option(False, "--dry-run"),
):
    """回滚服务指针（FR-PUB-005）。"""
    from ..application.rollback import RollbackService

    svc = RollbackService(Path(workspace_path), owner=owner, dry_run=dry_run)
    r = svc.rollback(scope_type, scope, to_version, reason=reason)
    _emit(output, {"job_id": r.job_id, "scope": r.scope,
                   "from_version": r.from_version, "to_version": r.to_version},
          human=f"回滚完成（job {r.job_id}）: {r.scope} {r.from_version} → {r.to_version}")


@app.command("build-projection")
def build_projection_cmd(
    workspace_path: Path = typer.Option(..., "--workspace", "-w"),
    domain: str = typer.Option(..., "--domain", "-d"),
    service: str = typer.Option("product_knowledge", "--service",
                                help="service_id"),
    core_version: str | None = typer.Option(None, "--core-version"),
    no_vectors: bool = typer.Option(False, "--no-vectors"),
    owner: str = typer.Option("svc_projection", "--owner"),
    output: str = typer.Option("text", "--output", help=_COMMON),
    dry_run: bool = typer.Option(False, "--dry-run"),
):
    """从活动 Core 版本重建服务投影（FR-SRV-001/002、G4）。"""
    from ..application.projection import ProjectionBuilder

    b = ProjectionBuilder(Path(workspace_path), owner=owner, dry_run=dry_run)
    r = b.build(domain, service_id=service, core_version=core_version,
                include_vectors=not no_vectors)
    if dry_run:
        _emit(output, {"dry_run": True, "plan": r.plan},
              human="将创建:\n  " + "\n  ".join(r.plan))
        return
    _emit(output, {"service_id": r.service_id, "version": r.projection_version,
                   "job_id": r.job_id, "files": r.files},
          human=f"投影构建完成: {r.service_id} version={r.projection_version}（job {r.job_id}）\n"
                f"  文件: {', '.join(r.files)}")


def _service(workspace_path: Path, service: str):
    from ..application.services import KnowledgeService

    return KnowledgeService(Path(workspace_path), service_id=service)


@app.command("query-data")
def query_data_cmd(
    workspace_path: Path = typer.Option(..., "--workspace", "-w"),
    dataset: str = typer.Option(..., "--dataset"),
    select: str | None = typer.Option(None, "--select", help="逗号分隔列"),
    where: str | None = typer.Option(None, "--where", help="JSON 过滤条件"),
    limit: int = typer.Option(100, "--limit"),
    service: str = typer.Option("product_knowledge", "--service"),
    output: str = typer.Option("text", "--output", help=_COMMON),
):
    """查询 Parquet 数据集（FR-SRV-003）。"""
    r = _service(workspace_path, service).data_query(
        dataset, select=select.split(",") if select else None,
        where=json.loads(where) if where else None, limit=limit)
    _emit(output, r.data, human=f"数据集 {r.data['dataset']}: {r.data['count']} 条记录")


@app.command("get-entity")
def get_entity_cmd(
    workspace_path: Path = typer.Option(..., "--workspace", "-w"),
    entity_id: str = typer.Option(..., "--entity-id"),
    as_of: str | None = typer.Option(None, "--as-of"),
    service: str = typer.Option("product_knowledge", "--service"),
    output: str = typer.Option("text", "--output", help=_COMMON),
):
    """查询实体及声明（FR-SRV-004）。"""
    r = _service(workspace_path, service).get_entity(entity_id, as_of=as_of)
    _emit(output, r.data,
          human=f"实体 {r.data['entity']['name']}（{entity_id}），"
                f"声明 {r.data['statement_count']} 条")


@app.command("graph")
def graph_cmd(
    workspace_path: Path = typer.Option(..., "--workspace", "-w"),
    start: str = typer.Option(..., "--start", help="起始实体 ID（逗号分隔）"),
    relation: str | None = typer.Option(None, "--relation", help="关系类型（逗号分隔）"),
    direction: str = typer.Option("OUT", "--direction"),
    depth: int = typer.Option(1, "--depth"),
    max_nodes: int = typer.Option(100, "--max-nodes"),
    mode: str = typer.Option("neighbor", "--mode",
                             help="neighbor|closure|paths"),
    service: str = typer.Option("product_knowledge", "--service"),
    output: str = typer.Option("text", "--output", help=_COMMON),
):
    """图谱邻居/闭包/路径查询（FR-SRV-004、IMP-ADR-011 Kùzu 后端）。"""
    r = _service(workspace_path, service).graph(
        [s.strip() for s in start.split(",") if s.strip()],
        relation_types=relation.split(",") if relation else None,
        direction=direction, max_depth=depth, max_nodes=max_nodes, mode=mode)
    _emit(output, r.data,
          human=f"图谱: {r.data['node_count']} 节点, {r.data['edge_count']} 边")


@app.command("search")
def search_cmd(
    workspace_path: Path = typer.Option(..., "--workspace", "-w"),
    query: str = typer.Option(..., "--query", "-q"),
    mode: str = typer.Option("FULLTEXT", "--mode",
                             help="FULLTEXT|VECTOR|HYBRID"),
    top_k: int = typer.Option(10, "--top-k"),
    service: str = typer.Option("product_knowledge", "--service"),
    output: str = typer.Option("text", "--output", help=_COMMON),
):
    """全文/向量/混合检索（FR-SRV-002）。"""
    r = _service(workspace_path, service).search(query, mode=mode, top_k=top_k)
    if output == "json":
        _emit(output, r.data)
    else:
        typer.echo(f"检索 [{mode}] {r.data['hit_count']} 个命中"
                   + ("（向量降级）" if r.data.get("degraded") else ""))
        for h in r.data["hits"]:
            typer.echo(f"  {h['segment_id']} score={h['score']} "
                       f"doc={h['document_id']} p{h['page_from']}-{h['page_to']}")
            typer.echo(f"    {h['content_excerpt']}")


@app.command("evaluate-rule")
def evaluate_rule_cmd(
    workspace_path: Path = typer.Option(..., "--workspace", "-w"),
    rule_set: str | None = typer.Option(None, "--rule-set"),
    facts: str = typer.Option(..., "--facts", help="JSON 事实映射"),
    service: str = typer.Option("product_knowledge", "--service"),
    output: str = typer.Option("text", "--output", help=_COMMON),
):
    """执行规则评估（FR-SRV-005）。"""
    r = _service(workspace_path, service).evaluate_rule(
        rule_set, facts=json.loads(facts))
    _emit(output, r.data,
          human=f"规则评估: 命中 {len(r.data['matched_rules'])} 条，"
                f"缺失输入 {r.data['missing_inputs']}，"
                f"需人工确认 {r.data['human_confirmation_required']}")


@app.command("trace")
def trace_cmd(
    workspace_path: Path = typer.Option(..., "--workspace", "-w"),
    object_id: str = typer.Option(..., "--object-id"),
    service: str = typer.Option("product_knowledge", "--service"),
    output: str = typer.Option("text", "--output", help=_COMMON),
):
    """证据与血缘溯源（FR-SRV-007）。"""
    r = _service(workspace_path, service).trace(object_id)
    if output == "json":
        _emit(output, r.data)
    else:
        typer.echo(f"溯源 {object_id}: 完整={r.data['complete']}")
        for c in r.data["chain"]:
            typer.echo(f"  [{c['layer']}] {c['object']} @ {c.get('version', '')} {c.get('path', '')}")


@app.command("gate-report")
def gate_report_cmd(
    workspace_path: Path = typer.Option(..., "--workspace", "-w"),
    reviewer: str = typer.Option("dkws_qa", "--reviewer"),
    output: str = typer.Option("text", "--output", help=_COMMON),
):
    """生成 G0—G5 门禁报告（§17.4、§18.5）。"""
    from ..application.gates import GateReporter

    results = GateReporter(Path(workspace_path), reviewer=reviewer).run_all()
    data = {
        "gates": [
            {"gate_id": r.gate_id, "decision": r.decision,
             "findings": len(r.findings), "report": r.report_rel,
             "ok": r.ok}
            for r in results
        ],
        "overall": "PASS" if all(r.ok for r in results) else "FAIL",
    }
    _emit(output, data,
          human="门禁报告（G0-G5）:\n"
                + "\n".join(f"  {r.gate_id}: {r.decision}（{len(r.findings)} 项发现）"
                            for r in results)
                + f"\n总评: {data['overall']}")


@app.command("job")
def job_cmd(
    workspace_path: Path = typer.Option(..., "--workspace", "-w"),
    job_id: str = typer.Option(..., "--job-id"),
    output: str = typer.Option("text", "--output", help=_COMMON),
):
    """查询任务状态（FR-CTL-001）。"""
    from ..application.jobs import read_job_status

    fm = read_job_status(Path(workspace_path), job_id)
    if output == "json":
        _emit(output, fm)
    else:
        typer.echo(
            f"任务 {fm['job_id']} [{fm['job_type']}] 状态={fm['status']} "
            f"进度={fm['progress']}% publish={fm['publish_status']}"
        )


@app.command("recover")
def recover_cmd(
    workspace_path: Path = typer.Option(..., "--workspace", "-w"),
    job_id: str | None = typer.Option(None, "--job", help="仅清理指定任务关联锁"),
    clear_expired: bool = typer.Option(False, "--clear-expired",
                                       help="验证关联任务已终止后清理过期锁"),
    output: str = typer.Option("text", "--output", help=_COMMON),
):
    """恢复：列出/清理过期写锁（§8.7）。"""
    ws = Path(workspace_path)
    stale = locks_mod.list_stale_locks(ws)
    if job_id:
        stale = [s for s in stale if s.get("job_id") == job_id]
    cleared: list[str] = []
    for s in stale:
        lock_file = s.get("lock_file", "")
        holder_job = s.get("job_id")
        terminated = _job_terminated(ws, holder_job)
        if clear_expired and terminated:
            if locks_mod.clear_stale_lock(ws, lock_file):
                cleared.append(lock_file)
    data = {
        "expired_locks": [
            {"lock_file": s.get("lock_file"), "job_id": s.get("job_id"),
             "holder_terminated": _job_terminated(ws, s.get("job_id"))}
            for s in stale
        ],
        "cleared": cleared,
    }
    _emit(output, data,
          human=f"过期锁 {len(stale)} 个；已清理 {len(cleared)} 个\n"
                + "\n".join(f"  - {s.get('lock_file')} job={s.get('job_id')}" for s in stale))


def _job_terminated(ws: Path, job_id: str | None) -> bool:
    """任务是否已终止（终态或状态文件缺失）。"""
    if not job_id:
        return True
    status_file = ws / "90_control" / "jobs" / job_id / "STATUS.md"
    if not status_file.is_file():
        return True
    text = status_file.read_text(encoding="utf-8")
    import re
    m = re.search(r"^status:\s*\"?([A-Z_]+)", text, re.M)
    return bool(m and m.group(1) in ("COMPLETED", "FAILED", "CANCELLED", "BLOCKED"))
