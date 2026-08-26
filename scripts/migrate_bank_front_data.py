#!/usr/bin/env python3
"""bank-front 示例数据按 DKWS 数据规划迁移。

规划映射（五层）：
- 01_raw   ：每个 Skill 的 example-input.json + mock-input-data.json 作为原始资产
             （batch=<id>，MANIFEST.md + SHA-256，domain=bank_front）
- 02_work  ：JSON → Parquet 规范化（dataset=<skill>，主键 customerId，对账+拒绝）
- 04_serve ：数据投影 bank_front_data/version=*/datasets/<skill>.parquet + PROJECTION.md + CURRENT.md
- 90_control：接入/加工任务状态、运行报告、血缘

用法：python migrate_bank_front_data.py --workspace <工作区> [--source <bank-front-skills 目录>]
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from dkws.application.ingest import Ingestor
from dkws.application.process_data import DataProcessor
from dkws.domain import hashing, ids, timeutil
from dkws.domain.contracts import specs
from dkws.domain.contracts.base import validate_contract
from dkws.infrastructure import markdown
from dkws.infrastructure.fs import WorkspaceWriter

DOMAIN = "bank_front"
SERVICE_ID = "bank_front_data"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace", "-w", required=True)
    ap.add_argument("--source", default=None,
                    help="bank-front-skills 目录（默认 dkws/examples/bank-front-skills）")
    ap.add_argument("--domain", default=DOMAIN)
    args = ap.parse_args()

    ws = Path(args.workspace).resolve()
    source = Path(args.source) if args.source else \
        Path(__file__).resolve().parent.parent / "examples" / "bank-front-skills"
    domain = args.domain

    print(f"== 迁移开始：{source} → {ws}（domain={domain}）==")
    ing = Ingestor(ws)
    proc = DataProcessor(ws)
    writer = WorkspaceWriter(ws)

    batches: dict[str, str] = {}
    datasets: list[str] = []
    for skill_dir in sorted(source.iterdir()):
        skill_id = skill_dir.name
        # dataset 文件名遵循 snake_case（§8.2）：连字符 → 下划线
        dataset_id = skill_id.replace("-", "_")
        files = []
        for rel in ("assets/example-input.json", "references/mock-input-data.json"):
            f = skill_dir / rel
            if f.is_file():
                files.append(f)
        if not files:
            continue
        # 1) Raw 接入（不可变批次 + 清单 + 哈希；文件名规范化为 snake_case）
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            norm_files = []
            for f in files:
                norm_name = f.name.replace("-", "_")
                norm_path = Path(td) / norm_name
                norm_path.write_bytes(f.read_bytes())
                norm_files.append(norm_path)
            r = ing.ingest(domain, norm_files, f"bank-front-{skill_id}",
                           source_system="skill_package")
        batches[skill_id] = r.batch_id
        print(f"  [RAW] {skill_id} → batch={r.batch_id}（{len(r.files)} 文件）")
        # 2) Work 规范化（JSON → Parquet，主键 customerId）
        pr = proc.process(domain, r.batch_id, dataset_id, key_field="customerId")
        if pr.normalized_rel:
            datasets.append(dataset_id)
            print(f"  [WORK] {skill_id} → {pr.normalized_rel}（输入 {pr.input_count} / 通过 {pr.passed_count} / 拒绝 {pr.rejected_count}）")

    # 3) Serve 数据投影（datasets/*.parquet + PROJECTION.md + CURRENT.md，原子）
    print("\n== 构建 Serve 数据投影 ==")
    version = _next_service_version(ws, SERVICE_ID)
    tmp = f"04_serve/{SERVICE_ID}/.tmp-{version}"
    final = f"04_serve/{SERVICE_ID}/version={version}"
    files_meta: list[dict] = []
    for ds in datasets:
        runs = sorted((ws / "02_work" / domain).glob("run=*"), reverse=True)
        src = None
        for run in runs:
            cand = run / "normalized" / f"{ds}.parquet"
            if cand.is_file():
                src = cand
                break
        if not src:
            continue
        writer.write_bytes(f"{tmp}/datasets/{ds}.parquet", src.read_bytes())
        files_meta.append({"path": f"datasets/{ds}.parquet",
                           "row_count": 0,
                           "sha256": hashing.sha256_file(src)})
    if not files_meta:
        print("  无可用数据集，跳过投影")
        return
    proj_md = _render_projection(SERVICE_ID, version, files_meta)
    validate_contract(proj_md, specs.PROJECTION_SPEC,
                      path=f"{tmp}/PROJECTION.md").raise_if_invalid()
    writer.write_text(f"{tmp}/PROJECTION.md", proj_md)
    writer.atomic_replace_dir(tmp, final)
    _write_service_current(SERVICE_ID, version, writer)
    print(f"  [SERVE] {SERVICE_ID} version={version}：{len(files_meta)} 个数据集")

    # 4) 一致性检查
    print("\n== 工作区一致性 ==")
    from dkws.domain import workspace as ws_mod

    findings = ws_mod.check_workspace(ws, mode="full")
    blockers = [f for f in findings if f.level in ("BLOCKER", "MAJOR")]
    print(f"  校验: {'PASS' if not blockers else 'FAIL'}（发现 {len(findings)} 项）")
    for f in findings:
        print(f"    [{f.level}] {f.code} {f.message}")
    print(f"\n== 迁移完成：{len(batches)} 个 Skill 批次、{len(datasets)} 个数据集投影 ==")


def _next_service_version(ws: Path, service_id: str) -> str:
    root = ws / "04_serve" / service_id
    versions = []
    if root.is_dir():
        for p in root.glob("version=*"):
            versions.append(p.name.removeprefix("version="))
    if not versions:
        return timeutil.now_utc().strftime("%Y.%m.%d") + ".1"
    head, _, tail = max(versions).rpartition(".")
    return f"{head}.{int(tail) + 1}"


def _render_projection(service_id: str, version: str, files_meta: list[dict]) -> str:
    now = timeutil.now_utc()
    fm = {
        "schema": "projection/v1",
        "projection_id": f"PRJ-DATA-{version.replace('.', '')}",
        "service_id": service_id,
        "projection_version": version,
        "source_core_releases": [],
        "builder_id": "bank_front_data_migrator",
        "builder_version": "1.0.0",
        "configuration_hash": hashing.sha256_hex(json.dumps(files_meta, sort_keys=True)),
        "files": files_meta,
        "logical_hashes": [],
        "built_at": timeutil.ts_utc(now),
        "verification_status": "VERIFIED",
        "status": "ACTIVE",
        "version": "1.0",
    }
    return markdown.render_contract_md(fm, "# 投影记录\n\nbank-front 示例数据投影。\n")


def _write_service_current(service_id: str, version: str, writer) -> None:
    proj_rel = f"04_serve/{service_id}/version={version}/PROJECTION.md"
    fm = {
        "schema": "current_pointer/v1",
        "scope_type": "SERVICE",
        "scope_id": service_id,
        "target_version": version,
        "target_release_id": f"PRJ-DATA-{version.replace('.', '')}",
        "target_manifest_sha256": hashing.sha256_file(writer.resolve(proj_rel)),
        "switched_by": "svc_migrator",
        "switched_at": timeutil.ts_utc(),
        "reason": "bank-front 示例数据迁移投影",
        "status": "ACTIVE",
        "version": "1.0",
    }
    body = "# 当前活动版本\n\n## 切换说明\n\n当前数据投影版本 " + version + "。\n\n## 回滚说明\n\n回滚仅切换指针。\n"
    text = markdown.render_contract_md(fm, body)
    validate_contract(text, specs.CURRENT_SPEC,
                      path=f"04_serve/{service_id}/CURRENT.md").raise_if_invalid()
    writer.write_text(f"04_serve/{service_id}/CURRENT.md", text)


if __name__ == "__main__":
    main()
