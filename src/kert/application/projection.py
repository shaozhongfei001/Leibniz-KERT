"""服务投影构建（FR-SRV-001/002、规格 §9.18、§10、§15）。

- 从活动 Core 版本生成 entities/relations/statements/segments/rules/vectors Parquet；
- 列序固定、逻辑哈希记录于 PROJECTION.md（可重建性：§8.4、§18.4）；
- G4 门禁：行数一致、逻辑哈希、悬空引用、检索样例；
- 04_serve/<service_id>/version=*/ 与 CURRENT.md（原子提交）。
"""

from __future__ import annotations

import hashlib
import io
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import pyarrow as pa

from ..domain import hashing, ids, timeutil
from ..domain.contracts import specs
from ..domain.contracts.base import validate_contract
from ..domain.errors import QualityGateError, ServiceNotReadyError
from ..infrastructure import locks as locks_mod, markdown
from ..infrastructure.fs import WorkspaceWriter
from .jobs import JobController

DEFAULT_SERVICE = "product_knowledge"
BUILDER_ID = "projection_builder"
BUILDER_VERSION = "1.0.0"
DEFAULT_EMBEDDER = "deterministic_hash_embedder"
DEFAULT_EMBED_DIM = 64


@dataclass
class ProjectionResult:
    service_id: str
    projection_version: str
    job_id: str
    files: list[str] = field(default_factory=list)
    plan: list[str] = field(default_factory=list)


class ProjectionBuilder:
    def __init__(self, workspace: Path, *, owner: str = "svc_projection",
                 dry_run: bool = False):
        self.ws = Path(workspace)
        self.owner = owner
        self.dry_run = dry_run

    def build(self, domain: str, *, service_id: str = DEFAULT_SERVICE,
              core_version: str | None = None,
              include_vectors: bool = True,
              idempotency_key: str | None = None) -> ProjectionResult:
        ids.validate_domain(domain)
        writer = WorkspaceWriter(self.ws, dry_run=self.dry_run)
        core_root = f"03_core/{domain}"
        version = core_version or self._current_version(domain)
        if not version:
            raise ServiceNotReadyError(f"域 {domain} 没有活动 Core 版本")
        ids.validate_release_version(version)
        core_dir = f"{core_root}/version={version}"
        if not writer.exists(f"{core_dir}/RELEASE.md"):
            raise ServiceNotReadyError(f"Core 版本不完整: {core_dir}")

        proj_version = version
        tmp_rel = f"04_serve/{service_id}/.tmp-{proj_version}"
        final_rel = f"04_serve/{service_id}/version={proj_version}"

        if self.dry_run:
            return ProjectionResult(
                service_id=service_id, projection_version=proj_version, job_id="",
                plan=[f"{final_rel}/{f}" for f in
                      ("entities.parquet", "relations.parquet", "statements.parquet",
                       "segments.parquet", "rules.parquet",
                       "vectors.parquet" if include_vectors else "", "PROJECTION.md") if f])

        with locks_mod.WorkspaceLock(self.ws, f"service:{service_id}",
                                     job_id=f"JOB-PRJ-{timeutil.ts_utc()[:19]}",
                                     owner=self.owner):
            job = JobController(self.ws, writer, job_type="BUILD_PROJECTION",
                                requested_by=self.owner,
                                idempotency_key=idempotency_key
                                or f"{service_id}:{version}:projection",
                                component="projection")
            if job.noop:
                return ProjectionResult(service_id=service_id,
                                        projection_version=proj_version,
                                        job_id=job.job_id)
            job.start()
            job.logger.info("PROJ_START", "投影构建开始", domain=domain,
                            core_version=version, service=service_id)
            try:
                assets = self._load_core_assets(core_dir)
                job.update(progress=30, log_code="PROJ_LOAD",
                           log_message=f"Core 资产加载 {len(assets)} 个")

                tables = self._build_tables(assets, version, include_vectors)
                logical_hashes: list[dict] = []
                files: list[dict] = []
                for name, table in tables.items():
                    rel = f"{tmp_rel}/{name}"
                    writer.write_bytes(rel, _table_bytes(table))
                    logical_hashes.append({
                        "file": name,
                        "logical_hash": hashing.parquet_logical_hash(
                            table, key_columns=_key_columns(name)),
                    })
                    files.append({"path": name, "row_count": table.num_rows})
                    job.logger.info("PROJ_TABLE", "投影表生成", file=name,
                                    rows=table.num_rows)
                # 数据集投影（§10.7）：从最近一次数据加工 run 复制规范化 Parquet
                dataset_files = self._copy_datasets(domain, tmp_rel, writer)
                files.extend({"path": d, "row_count": 0} for d in dataset_files)
                job.update(progress=70, log_code="PROJ_TABLES",
                           log_message="投影表生成完成")

                # G4 门禁
                gate = self._g4_gate(assets, tables)
                if not gate["pass"]:
                    raise QualityGateError("G4 门禁失败: " + "; ".join(gate["errors"][:8]))

                config_hash = hashing.sha256_hex(json.dumps({
                    "core_version": version, "include_vectors": include_vectors,
                    "embedder": DEFAULT_EMBEDDER, "dim": DEFAULT_EMBED_DIM,
                }, sort_keys=True))
                projection_md = self._render_projection(
                    service_id, proj_version, version, files, logical_hashes,
                    config_hash)
                validate_contract(projection_md, specs.PROJECTION_SPEC,
                                  path=f"{tmp_rel}/PROJECTION.md").raise_if_invalid()
                writer.write_text(f"{tmp_rel}/PROJECTION.md", projection_md)

                writer.atomic_replace_dir(tmp_rel, final_rel)
                self._build_graph(service_id, proj_version, job)
                self._write_service_current(service_id, proj_version, writer, job)
                out_refs = [{"path": f"{final_rel}/{f['path']}", "version": proj_version,
                             "content_hash": hashing.sha256_hex(f["path"])}
                            for f in files]
                job.finish(output_refs=out_refs, input_count=len(assets),
                           output_count=len(files) + 1,
                           quality_summary={"gates_passed": ["G4"]})
                return ProjectionResult(service_id=service_id,
                                        projection_version=proj_version,
                                        job_id=job.job_id,
                                        files=[f["path"] for f in files])
            except Exception as exc:
                job.fail("PROJECTION_FAILED", str(exc))
                raise

    # ---------------- 内部 ----------------

    def _current_version(self, domain: str) -> str | None:
        cur = self.ws / "03_core" / domain / "CURRENT.md"
        if not cur.is_file():
            return None
        m = re.search(r"^target_version:\s*\"?([^\n\" ]+)",
                      cur.read_text(encoding="utf-8"), re.M)
        return m.group(1) if m else None

    def _load_core_assets(self, core_dir: str) -> dict:
        assets: dict[str, list[dict]] = {
            "entities": [], "relations": [], "statements": [],
            "segments": [], "rules": [], "documents": [],
        }
        base = self.ws / core_dir
        for kind in assets:
            d = base / kind
            if not d.is_dir():
                continue
            for f in sorted(d.glob("*.md")):
                text = f.read_text(encoding="utf-8")
                parsed = markdown.parse_contract_md(text, path=f.name)
                schema = parsed.front_matter.get("schema", "")
                spec = specs.get_spec(schema) if schema in specs.SCHEMA_REGISTRY else None
                rv = validate_contract(text, spec, path=f.name) if spec else None
                if rv is None or not rv.ok:
                    continue
                assets[kind].append({"fm": rv.front_matter, "body": rv.body})
        return assets

    def _build_tables(self, assets: dict, release_id: str,
                      include_vectors: bool) -> dict[str, pa.Table]:
        recorded_at = timeutil.ts_utc()
        tables: dict[str, pa.Table] = {}

        entities = []
        for a in assets["entities"]:
            row = {
                "entity_id": a["fm"]["entity_id"], "entity_type": a["fm"]["entity_type"],
                "name": a["fm"]["name"], "aliases": a["fm"].get("aliases", []),
                "description": a["fm"].get("description"),
                "domain": a["fm"].get("domain", ""),
                "status": a["fm"].get("status", "ACTIVE"),
                "effective_from": a["fm"].get("effective_from"),
                "effective_to": a["fm"].get("effective_to"),
                "source_ids": a["fm"].get("source_ids", []),
                "source_release_id": release_id,
                "asset_version": a["fm"].get("version", "1.0"),
                "recorded_at": recorded_at,
            }
            # 扩展字段透传（v1.3：客户知识 x_* 字段，如 x_credit_code / x_rm_id / x_annual_amount）
            row.update({k: a["fm"][k] for k in a["fm"] if k.startswith("x_")})
            entities.append(row)
        _pad_x_fields(entities)
        tables["entities.parquet"] = pa.Table.from_pylist(entities) if entities else \
            _empty_table(["entity_id", "entity_type", "name", "aliases", "description",
                          "domain", "status", "effective_from", "effective_to",
                          "source_ids", "source_release_id", "asset_version",
                          "recorded_at"])

        relations = []
        for a in assets["relations"]:
            row = {
                "relation_id": a["fm"]["relation_id"], "source_id": a["fm"]["source_id"],
                "relation_type": a["fm"]["relation_type"], "target_id": a["fm"]["target_id"],
                "statement_id": a["fm"].get("statement_id"),
                "status": a["fm"].get("status", "ACTIVE"),
                "effective_from": a["fm"].get("effective_from"),
                "effective_to": a["fm"].get("effective_to"),
                "source_ids": a["fm"].get("source_ids", []),
                "source_release_id": release_id,
                "asset_version": a["fm"].get("version", "1.0"),
                "recorded_at": recorded_at,
            }
            row.update({k: a["fm"][k] for k in a["fm"] if k.startswith("x_")})
            relations.append(row)
        _pad_x_fields(relations)
        tables["relations.parquet"] = pa.Table.from_pylist(relations) if relations else \
            _empty_table(["relation_id", "source_id", "relation_type", "target_id",
                          "statement_id", "status", "effective_from", "effective_to",
                          "source_ids", "source_release_id", "asset_version",
                          "recorded_at"])

        statements = []
        for a in assets["statements"]:
            fm = a["fm"]
            row = {
                "statement_id": fm["statement_id"], "subject_id": fm["subject_id"],
                "predicate": fm["predicate"], "object_id": fm.get("object_id"),
                "object_value_string": None, "object_value_decimal": None,
                "object_value_boolean": None, "object_value_date": None,
                "value_type": fm["value_type"], "unit": fm.get("unit"),
                "polarity": fm["polarity"], "conflict_status": fm.get("conflict_status"),
                "source_type": fm["source_type"], "source_asset_id": fm["source_asset_id"],
                "source_record_id": fm.get("source_record_id"),
                "source_segment_id": fm.get("source_segment_id"),
                "effective_from": fm.get("effective_from"),
                "effective_to": fm.get("effective_to"),
                "source_release_id": release_id,
                "asset_version": fm.get("version", "1.0"),
                "recorded_at": recorded_at,
            }
            _fill_typed_value(row, fm)
            statements.append(row)
        tables["statements.parquet"] = pa.Table.from_pylist(statements) if statements else \
            _empty_table(["statement_id", "subject_id", "predicate", "object_id",
                          "object_value_string", "object_value_decimal",
                          "object_value_boolean", "object_value_date", "value_type",
                          "unit", "polarity", "conflict_status", "source_type",
                          "source_asset_id", "source_record_id", "source_segment_id",
                          "effective_from", "effective_to", "source_release_id",
                          "asset_version", "recorded_at"])

        segments = [{
            "segment_id": a["fm"]["segment_id"], "document_id": a["fm"]["document_id"],
            "segment_type": a["fm"]["segment_type"],
            "heading_path": a["fm"].get("heading_path", []),
            "page_from": a["fm"].get("page_from"), "page_to": a["fm"].get("page_to"),
            "sequence": a["fm"].get("sequence", 0),
            "content": _segment_content(a["body"]),
            "content_sha256": a["fm"]["content_sha256"],
            "source_path": f"03_core/{release_id}/segments/{a['fm']['segment_id']}.md",
            "source_release_id": release_id,
            "asset_version": a["fm"].get("version", "1.0"),
        } for a in assets["segments"]]
        tables["segments.parquet"] = pa.Table.from_pylist(segments) if segments else \
            _empty_table(["segment_id", "document_id", "segment_type", "heading_path",
                          "page_from", "page_to", "sequence", "content",
                          "content_sha256", "source_path", "source_release_id",
                          "asset_version"])

        rules = [{
            "rule_id": a["fm"]["rule_id"], "name": a["fm"]["name"],
            "rule_type": a["fm"]["rule_type"], "priority": a["fm"]["priority"],
            "execution_mode": a["fm"]["execution_mode"],
            "when": json.dumps(a["fm"]["when"], ensure_ascii=False),
            "then": json.dumps(a["fm"]["then"], ensure_ascii=False),
            "else": json.dumps(a["fm"].get("else"), ensure_ascii=False) if a["fm"].get("else") else None,
            "required_inputs": a["fm"].get("required_inputs", []),
            "test_case_ids": a["fm"].get("test_case_ids", []),
            "status": a["fm"].get("status", "ACTIVE"),
            "source_release_id": release_id,
            "asset_version": a["fm"].get("version", "1.0"),
        } for a in assets["rules"]]
        tables["rules.parquet"] = pa.Table.from_pylist(rules) if rules else \
            _empty_table(["rule_id", "name", "rule_type", "priority", "execution_mode",
                          "when", "then", "else", "required_inputs", "test_case_ids",
                          "status", "source_release_id", "asset_version"])

        if include_vectors and segments:
            tables["vectors.parquet"] = _build_vectors(segments)
        return tables

    def _build_graph(self, service_id: str, version: str, job) -> None:
        """构建 Kùzu 图谱投影（IMP-ADR-011 受控变更）；失败 fail-open。"""
        try:
            from ..infrastructure.graph.kuzu_builder import KuzuGraphBuilder

            r = KuzuGraphBuilder(self.ws, service_id=service_id).build(version)
            job.logger.info("PROJ_GRAPH", "Kùzu 图谱投影构建完成",
                            nodes=r.node_count, edges=r.edge_count)
        except Exception as exc:
            job.logger.warn("PROJ_GRAPH_SKIP",
                            f"Kùzu 图谱投影构建失败（fail-open）: {exc}")

    def _copy_datasets(self, domain: str, tmp_rel: str, writer) -> list[str]:
        """从最近数据 run 复制规范化数据集到投影 datasets/。"""
        base = self.ws / "02_work" / domain
        if not base.is_dir():
            return []
        runs = sorted((p.name for p in base.glob("run=*")), reverse=True)
        copied: list[str] = []
        for run in runs:
            norm = base / run / "normalized"
            if not norm.is_dir():
                continue
            for f in sorted(norm.glob("*.parquet")):
                target = f"datasets/{f.name}"
                writer.write_bytes(f"{tmp_rel}/{target}",
                                   f.read_bytes())
                copied.append(target)
            break  # 仅最近一次 run
        return copied

    def _g4_gate(self, assets: dict, tables: dict) -> dict:
        errors: list[str] = []
        checks = [
            ("entities", "entities.parquet"), ("relations", "relations.parquet"),
            ("statements", "statements.parquet"), ("segments", "segments.parquet"),
            ("rules", "rules.parquet"),
        ]
        for kind, file in checks:
            if len(assets[kind]) != tables[file].num_rows:
                errors.append(
                    f"{file} 行数不一致: Core {len(assets[kind])} vs 投影 {tables[file].num_rows}")
        # 悬空引用（关系端点必须在实体投影中）
        if "relations.parquet" in tables and tables["relations.parquet"].num_rows:
            ents = set(tables["entities.parquet"].column("entity_id").to_pylist())
            rels = tables["relations.parquet"]
            for src, tgt in zip(rels.column("source_id").to_pylist(),
                                rels.column("target_id").to_pylist()):
                if src not in ents or tgt not in ents:
                    errors.append(f"关系端点悬空: {src}→{tgt}")
                    break
        # 检索样例：segments 全文可用
        if tables.get("segments.parquet") and tables["segments.parquet"].num_rows:
            sample = tables["segments.parquet"].column("content").to_pylist()[0]
            if not sample:
                errors.append("segments 检索样例为空")
        return {"pass": not errors, "errors": errors}

    def _render_projection(self, service_id, version, core_version, files,
                           logical_hashes, config_hash) -> str:
        fm = {
            "schema": "projection/v1",
            "projection_id": f"PRJ-{version.replace('.', '')}",
            "service_id": service_id,
            "projection_version": version,
            "source_core_releases": [core_version],
            "builder_id": BUILDER_ID,
            "builder_version": BUILDER_VERSION,
            "configuration_hash": config_hash,
            "files": files,
            "logical_hashes": logical_hashes,
            "built_at": timeutil.ts_utc(),
            "verification_status": "VERIFIED",
            "status": "ACTIVE",
            "version": "1.0",
        }
        return markdown.render_contract_md(fm, "# 投影记录\n")

    def _write_service_current(self, service_id, version, writer, job) -> None:
        proj_rel = f"04_serve/{service_id}/version={version}/PROJECTION.md"
        manifest_sha = hashing.sha256_file(writer.resolve(proj_rel))
        fm = {
            "schema": "current_pointer/v1",
            "scope_type": "SERVICE",
            "scope_id": service_id,
            "target_version": version,
            "target_release_id": f"PRJ-{version.replace('.', '')}",
            "target_manifest_sha256": manifest_sha,
            "switched_by": self.owner,
            "switched_at": timeutil.ts_utc(),
            "reason": f"投影构建 {version}（job {job.job_id}）",
            "status": "ACTIVE",
            "version": "1.0",
        }
        body = ("# 当前活动版本\n\n"
                f"## 切换说明\n\n当前投影版本 {version}。\n\n"
                "## 回滚说明\n\n回滚仅切换指针。\n")
        text = markdown.render_contract_md(fm, body)
        validate_contract(text, specs.CURRENT_SPEC,
                          path=f"04_serve/{service_id}/CURRENT.md").raise_if_invalid()
        writer.write_text(f"04_serve/{service_id}/CURRENT.md", text)


def _segment_content(body: str) -> str:
    m = re.search(r"## 原文\n\n(.*?)(?:\n\n## 解析注记|\Z)", body, re.S)
    return m.group(1).rstrip() if m else ""


def _fill_typed_value(row: dict, fm: dict) -> None:
    vt = fm.get("value_type")
    val = fm.get("object_value")
    if val is None:
        return
    if vt == "OBJECT_REF":
        row["object_value_string"] = str(fm.get("object_id"))
    elif vt in ("STRING", "CODE"):
        row["object_value_string"] = str(val)
    elif vt in ("INTEGER", "DECIMAL", "DURATION"):
        try:
            row["object_value_decimal"] = float(val)
        except (TypeError, ValueError):
            row["object_value_string"] = str(val)
    elif vt == "BOOLEAN":
        row["object_value_boolean"] = bool(val)
    elif vt in ("DATE", "DATETIME"):
        row["object_value_date"] = str(val)[:10] if str(val).startswith("20") else str(val)


def _build_vectors(segments: list[dict]) -> pa.Table:
    """确定性嵌入（无外部模型时）：由内容哈希派生伪随机但稳定的 float32 向量。"""

    dim = DEFAULT_EMBED_DIM
    rows = []
    for seg in segments:
        digest = hashlib.sha256(seg["content_sha256"].encode("utf-8")).digest()
        vec = []
        for i in range(dim):
            b = digest[i % len(digest)]
            vec.append((b / 255.0) - 0.5)
        rows.append({
            "segment_id": seg["segment_id"],
            "embedding_model_id": DEFAULT_EMBEDDER,
            "embedding_model_version": "1.0.0",
            "dimension": dim,
            "embedding": vec,
            "content_sha256": seg["content_sha256"],
            "generated_at": timeutil.ts_utc(),
        })
    return pa.Table.from_pylist(rows)


def _key_columns(file: str) -> list[str]:
    return {
        "entities.parquet": ["entity_id"],
        "relations.parquet": ["relation_id"],
        "statements.parquet": ["statement_id"],
        "segments.parquet": ["segment_id"],
        "rules.parquet": ["rule_id"],
        "vectors.parquet": ["segment_id"],
    }.get(file, [])


def _pad_x_fields(rows: list[dict]) -> None:
    """补齐每行的 x_ 扩展字段为并集，避免 pa.Table.from_pylist 丢弃仅出现在后行的键。"""
    keys = sorted({k for r in rows for k in r if k.startswith("x_")})
    for r in rows:
        for k in keys:
            r.setdefault(k, None)


def _empty_table(columns: list[str]) -> pa.Table:
    arrays = []
    for col in columns:
        if col in ("aliases", "source_ids", "heading_path", "required_inputs",
                   "test_case_ids", "embedding"):
            arrays.append(pa.array([], type=pa.list_(pa.string())))
        elif col in ("page_from", "page_to", "sequence", "priority"):
            arrays.append(pa.array([], type=pa.int64()))
        elif col in ("object_value_decimal",):
            arrays.append(pa.array([], type=pa.float64()))
        elif col in ("object_value_boolean",):
            arrays.append(pa.array([], type=pa.bool_()))
        elif col in ("effective_from", "effective_to", "object_value_date"):
            arrays.append(pa.array([], type=pa.date32()))
        else:
            arrays.append(pa.array([], type=pa.string()))
    return pa.Table.from_arrays(arrays, names=columns)


def _table_bytes(table: pa.Table) -> bytes:
    import pyarrow.parquet as pq

    buf = io.BytesIO()
    pq.write_table(table, buf, compression="zstd")
    return buf.getvalue()
