"""结构化数据加工：清洗、类型化、拒绝隔离、对账与血缘（FR-DATA-001~005、§11.4 数据部分）。

- 输入：Raw 批次中的 CSV/JSON/JSONL/Parquet（role=DATA）；
- 输出：02_work/<domain>/run=<run_id>/normalized/<dataset>.parquet 与 rejected/<dataset>_rejected.parquet；
- 错误记录进入 rejected/ 并保留原因；输入数 = 通过数 + 拒绝数（对账）；
- 每条记录保留 source_batch_id / source_record_id / processing_run_id / recorded_at（血缘）。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import pyarrow as pa

from ..domain import hashing, ids, timeutil
from ..domain.contracts import specs
from ..domain.contracts.base import validate_contract
from ..domain.errors import UsageError
from ..infrastructure import locks as locks_mod, markdown, parquet as pqio
from ..infrastructure.fs import WorkspaceWriter
from .jobs import JobController

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@dataclass
class ProcessDataResult:
    run_id: str
    job_id: str
    input_count: int = 0
    passed_count: int = 0
    rejected_count: int = 0
    normalized_rel: str | None = None
    rejected_rel: str | None = None
    plan: list[str] = field(default_factory=list)


class DataProcessor:
    def __init__(self, workspace: Path, *, owner: str = "svc_processor",
                 dry_run: bool = False):
        self.ws = Path(workspace)
        self.owner = owner
        self.dry_run = dry_run

    def process(self, domain: str, batch_id: str, dataset_id: str, *,
                mapping_id: str | None = None, key_field: str | None = None,
                mapping_json: str | None = None) -> ProcessDataResult:
        ids.validate_domain(domain)
        ids.validate_id(batch_id, "batch_id")
        writer = WorkspaceWriter(self.ws, dry_run=self.dry_run)
        batch_rel = f"01_raw/{domain}/batch={batch_id}"

        if self.dry_run:
            run_id = ids.new_run_id("DATA")
            base = f"02_work/{domain}/run={run_id}"
            return ProcessDataResult(
                run_id=run_id, job_id="", plan=[
                    f"{base}/normalized/{dataset_id}.parquet",
                    f"{base}/rejected/{dataset_id}_rejected.parquet",
                ])

        with locks_mod.WorkspaceLock(self.ws, f"domain:{domain}",
                                     job_id=f"JOB-DATA-{timeutil.ts_utc()[:19]}",
                                     owner=self.owner):
            job = JobController(self.ws, writer, job_type="PROCESS_DATA",
                                requested_by=self.owner,
                                idempotency_key=f"{batch_id}:{dataset_id}",
                                component="data_processor")
            if job.noop:
                return ProcessDataResult(run_id="", job_id=job.job_id)
            job.start()
            job.logger.info("DATA_START", "数据加工开始",
                            domain=domain, batch_id=batch_id, dataset_id=dataset_id)
            try:
                # G0 复查：清单合同、批次关闭、文件哈希
                manifest = self._load_manifest(batch_rel, job)
                data_files = [f for f in manifest["files"] if f.get("role") == "DATA"]
                if not data_files:
                    raise UsageError(f"批次 {batch_id} 中没有 role=DATA 的文件")
                job.update(progress=20, log_code="DATA_MANIFEST", log_message="清单校验通过")

                mapping = self._resolve_mapping(mapping_id, mapping_json)
                key = key_field or (mapping.get("key_policy") if mapping else None)

                run_id = self._allocate_run_id(domain)
                base = f"02_work/{domain}/run={run_id}"
                all_passed: list[dict] = []
                all_rejected: list[dict] = []
                input_count = 0
                for df in data_files:
                    src_rel = f"{batch_rel}/{df['path']}"
                    # 哈希一致性（FR-ING-002 / NFR-004）
                    actual = hashing.sha256_file(writer.resolve(src_rel))
                    if actual != df["sha256"]:
                        raise UsageError(f"文件哈希不一致: {df['path']}（G0 门禁失败）")
                    table = pqio.read_table(writer.resolve(src_rel))
                    passed, rejected, cnt = self._process_table(
                        table, mapping, key, dataset_id, batch_id, run_id, df["path"])
                    input_count += cnt
                    all_passed.extend(passed)
                    all_rejected.extend(rejected)
                job.update(progress=60, log_code="DATA_CLEAN",
                           log_message=f"清洗完成 passed={len(all_passed)} rejected={len(all_rejected)}")

                normalized_rel = f"{base}/normalized/{dataset_id}.parquet"
                rejected_rel = f"{base}/rejected/{dataset_id}_rejected.parquet"
                if all_passed:
                    writer.write_bytes(
                        normalized_rel,
                        _table_bytes(pa.Table.from_pylist(all_passed)))
                if all_rejected:
                    writer.write_bytes(
                        rejected_rel,
                        _table_bytes(pa.Table.from_pylist(all_rejected)))

                # 对账（FR-DATA-003）
                if input_count != len(all_passed) + len(all_rejected):
                    raise UsageError(
                        f"对账失败: input={input_count} != passed={len(all_passed)} + rejected={len(all_rejected)}")
                job.update(progress=85, log_code="DATA_RECONCILE",
                           log_message=f"对账平衡 input={input_count} passed={len(all_passed)} rejected={len(all_rejected)}")

                self._write_quality_results(batch_id, dataset_id, job, input_count,
                                            len(all_passed), len(all_rejected), writer)
                self._write_lineage(domain, batch_id, dataset_id, run_id, job, writer,
                                    input_count, len(all_passed), len(all_rejected))
                out_refs = []
                for rel in (normalized_rel, rejected_rel):
                    if writer.exists(rel):
                        out_refs.append({"path": rel, "version": "1.0",
                                         "content_hash": hashing.sha256_file(writer.resolve(rel))})
                job.finish(output_refs=out_refs, input_count=input_count,
                           output_count=len(out_refs), rejected_count=len(all_rejected),
                           quality_summary={"reconciled": True})
                return ProcessDataResult(
                    run_id=run_id, job_id=job.job_id, input_count=input_count,
                    passed_count=len(all_passed), rejected_count=len(all_rejected),
                    normalized_rel=normalized_rel if all_passed else None,
                    rejected_rel=rejected_rel if all_rejected else None)
            except Exception as exc:
                job.fail("DATA_PROCESS_FAILED", str(exc))
                raise

    # ---------------- 内部 ----------------

    def _allocate_run_id(self, domain: str) -> str:
        now = timeutil.now_utc()
        seq = 1
        while True:
            rid = ids.new_run_id("DATA", now=now, seq=seq)
            if not (self.ws / f"02_work/{domain}/run={rid}").exists():
                return rid
            seq += 1

    def _load_manifest(self, batch_rel: str, job) -> dict:
        rel = f"{batch_rel}/MANIFEST.md"
        text = self.ws.joinpath(*rel.split("/")).read_text(encoding="utf-8")
        result = validate_contract(text, specs.MANIFEST_SPEC, path=rel)
        result.raise_if_invalid(rel)
        if result.front_matter["status"] != "CLOSED":
            raise UsageError(f"批次未关闭（status={result.front_matter['status']}），不可加工")
        return result.front_matter

    def _resolve_mapping(self, mapping_id: str | None, mapping_json: str | None) -> dict:
        if mapping_json:
            data = json.loads(mapping_json)
            return {"field_mappings": data.get("field_mappings", []),
                    "key_policy": data.get("key_policy")}
        if mapping_id:
            rel = f"90_control/schema/mappings/{mapping_id}.md"
            text = self.ws.joinpath(*rel.split("/")).read_text(encoding="utf-8")
            result = validate_contract(text, specs.DATA_MAPPING_SPEC, path=rel)
            result.raise_if_invalid(rel)
            return result.front_matter
        return {"field_mappings": [], "key_policy": None}

    def _process_table(self, table, mapping, key, dataset_id, batch_id,
                       run_id, source_name) -> tuple[list, list, int]:
        fields = {fm["target_field"]: fm for fm in mapping.get("field_mappings", [])}
        rows = table.to_pylist()
        input_count = len(rows)
        passed: list[dict] = []
        rejected: list[dict] = []
        seen: set = set()
        recorded_at = timeutil.ts_utc()
        for i, row in enumerate(rows):
            out: dict = {}
            reasons: list[str] = []
            if fields:
                for target, fm in fields.items():
                    src = fm.get("source_field", target)
                    if src not in row:
                        reasons.append(f"missing_column:{src}")
                        out[target] = None
                        continue
                    val = row[src]
                    # CSV 空字段可能解析为 '' 或 None；业务上统一视为缺失（§8.6 空值语义）
                    if val is None or (isinstance(val, str) and not val.strip()):
                        if fm.get("missing_policy") in ("REJECT", "REJECT_REQUIRED"):
                            reasons.append(f"missing:{src}")
                        out[target] = None
                        continue
                    conv = _convert(val, fm.get("target_type", "string"))
                    if conv is _CONV_FAILED:
                        reasons.append(f"type:{src}->{fm.get('target_type')}")
                        out[target] = None
                        continue
                    out[target] = conv
            else:
                out = {c: row.get(c) for c in table.column_names}
            if reasons:
                out["reject_reason"] = ";".join(reasons)
                out["_source_row"] = i
                rejected.append(out)
                continue
            if key:
                key_val = tuple(str(out.get(k)) for k in ([key] if isinstance(key, str) else key))
                if key_val in seen:
                    out["reject_reason"] = f"duplicate_key:{key}"
                    out["_source_row"] = i
                    rejected.append(out)
                    continue
                seen.add(key_val)
            out["source_batch_id"] = batch_id
            out["source_record_id"] = str(i)
            out["source_file"] = source_name
            out["processing_run_id"] = run_id
            out["recorded_at"] = recorded_at
            passed.append(out)
        return passed, rejected, input_count

    def _write_quality_results(self, batch_id, dataset_id, job, input_count,
                               passed_count, rejected_count, writer) -> None:
        now = timeutil.now_utc()
        results = [
            {
                "quality_rule_id": "QR-DATA-RECONCILE",
                "evaluated_count": input_count,
                "failed_count": 1 if input_count != passed_count + rejected_count else 0,
                "result": "PASS" if input_count == passed_count + rejected_count else "FAIL",
                "name": "数据对账",
            },
            {
                "quality_rule_id": "QR-DATA-SCHEMA",
                "evaluated_count": input_count,
                "failed_count": rejected_count,
                "result": "PASS" if rejected_count == 0 else "WARN",
                "name": "数据合同（类型/必填/主键）",
            },
        ]
        for idx, qr in enumerate(results):
            self._ensure_quality_rule(qr["quality_rule_id"], qr["name"], writer)
            qr_id = ids.new_id("QR", now=now, seq=idx + 1)
            fm = {
                "schema": "quality_result/v1",
                "quality_result_id": qr_id,
                "quality_rule_id": qr["quality_rule_id"],
                "quality_rule_version": "1.0",
                "job_id": job.job_id,
                "target_asset": f"DS-{dataset_id.upper()}",
                "target_version": batch_id,
                "evaluated_count": qr["evaluated_count"],
                "failed_count": qr["failed_count"],
                "sample_failures": [],
                "result": qr["result"],
                "executed_at": timeutil.ts_utc(),
                "status": "ACTIVE",
                "version": "1.0",
            }
            writer.write_text(
                f"90_control/quality/results/{qr_id}.md",
                markdown.render_contract_md(fm, f"# 质量结果\n\n{qr['name']}：{qr['result']}\n"))

    def _ensure_quality_rule(self, rule_id, name, writer) -> None:
        rel = f"90_control/quality/rules/{rule_id}.md"
        if writer.exists(rel):
            return
        fm = {
            "schema": "quality_rule/v1",
            "quality_rule_id": rule_id,
            "name": name,
            "target_schema": "datasets/*/v1",
            "target_asset": "*",
            "dimension": "CONSISTENCY",
            "severity": "BLOCKER",
            "expression": "reconcile(input, passed, rejected)",
            "threshold": "0",
            "on_failure": "BLOCK",
            "status": "ACTIVE",
            "version": "1.0",
        }
        writer.write_text(rel, markdown.render_contract_md(fm, f"# {name}\n"))

    def _write_lineage(self, domain, batch_id, dataset_id, run_id, job, writer,
                       input_count, passed_count, rejected_count) -> None:
        lineage_id = ids.new_id("LG")
        fm = {
            "schema": "lineage/v1",
            "lineage_id": lineage_id,
            "process_id": "process_data",
            "job_id": job.job_id,
            "inputs": [{"asset_id": batch_id, "version": "1.0",
                        "path": f"01_raw/{domain}/batch={batch_id}",
                        "content_hash": hashing.sha256_hex(batch_id)}],
            "outputs": [
                {"asset_id": f"DS-{dataset_id.upper()}", "version": run_id,
                 "path": f"02_work/{domain}/run={run_id}/normalized/{dataset_id}.parquet",
                 "content_hash": hashing.sha256_hex(run_id)},
            ],
            "transformation_id": "data_clean",
            "transformation_version": "1.0.0",
            "code_version": "0.1.0",
            "started_at": timeutil.ts_utc(),
            "finished_at": timeutil.ts_utc(),
            "status": "COMPLETED",
            "version": "1.0",
        }
        writer.write_text(
            f"90_control/lineage/ingest/{lineage_id}.md",
            markdown.render_contract_md(
                fm, "# 血缘记录\n\n## 转换说明\n\n数据清洗与类型化。\n\n"
                    "## 输入\n\n见上。\n\n## 输出\n\n见上。\n\n## 已知限制\n\n无。\n"))


class _ConvFailed:
    pass


_CONV_FAILED = _ConvFailed()


def _convert(val, target_type: str):
    """确定性类型转换；失败返回 _CONV_FAILED。"""
    try:
        if target_type in ("string", "str"):
            if isinstance(val, str):
                return val
            if isinstance(val, bool):
                return "true" if val else "false"
            return str(val)
        if target_type in ("integer", "int"):
            if isinstance(val, bool):
                return _CONV_FAILED
            if isinstance(val, int):
                return val
            if isinstance(val, float) and val.is_integer():
                return int(val)
            if isinstance(val, str) and val.strip().lstrip("-").isdigit():
                return int(val)
            return _CONV_FAILED
        if target_type in ("decimal", "number", "float"):
            if isinstance(val, bool):
                return _CONV_FAILED
            if isinstance(val, (int, float)):
                return float(val)
            if isinstance(val, str):
                try:
                    return float(val)
                except ValueError:
                    return _CONV_FAILED
            return _CONV_FAILED
        if target_type in ("boolean", "bool"):
            if isinstance(val, bool):
                return val
            if isinstance(val, str) and val.strip().lower() in ("true", "1", "yes", "是"):
                return True
            if isinstance(val, str) and val.strip().lower() in ("false", "0", "no", "否"):
                return False
            if val in (1, 0):
                return bool(val)
            return _CONV_FAILED
        if target_type in ("date",):
            if isinstance(val, str) and _DATE_RE.match(val):
                return val
            if hasattr(val, "isoformat"):
                return val.isoformat()[:10]
            return _CONV_FAILED
        return val
    except (ValueError, TypeError):
        return _CONV_FAILED


def _table_bytes(table) -> bytes:
    import io

    import pyarrow.parquet as pq

    buf = io.BytesIO()
    pq.write_table(table, buf, compression="zstd")
    return buf.getvalue()
