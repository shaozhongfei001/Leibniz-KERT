#!/usr/bin/env python3
"""袁阳 assemblyMaterials.zip → DKWS 五层工作区迁移（bank_front 域）。

规划映射（与 migrate_bank_front_data.py 同构，五层）：
- 01_raw   ：BATCH=<id> 不可变批次（MANIFEST.md + SHA-256，domain=bank_front，
             7 个原始 TASK-FRONT 任务 JSON 以 role=REFERENCE 保留原文，
             1 个派生记录文件 assembly_materials_records.json 以 role=DATA 供加工）
- 02_work  ：JSON → Parquet 规范化（dataset=assembly_materials，主键 customerId，对账+血缘+质量）
- 04_serve ：bank_front_data/version=* 新版本投影（既有 7 数据集 + assembly_materials）
             + PROJECTION.md + CURRENT.md（原子替换）
- 90_control：接入/加工任务状态、血缘、质量结果（由平台服务自动落盘）

用法：
  python migrate_assembly_materials.py --workspace ../demo_workspace \
      --zip "/media/.../袁阳/assemblyMaterials.zip"
"""

from __future__ import annotations

import argparse
import json
import tempfile
import zipfile
from pathlib import Path

from dkws.application.ingest import Ingestor
from dkws.application.process_data import DataProcessor
from dkws.domain import hashing, timeutil
from dkws.domain.contracts import specs
from dkws.domain.contracts.base import validate_contract
from dkws.infrastructure import markdown
from dkws.infrastructure.fs import WorkspaceWriter

DOMAIN = "bank_front"
SERVICE_ID = "bank_front_data"
IDEM_KEY = "bank-front-assembly-materials-v2"
DATASET = "assembly_materials"
EXISTING_DATASETS = [
    "bank-front-commitment-script", "bank-front-eight-dimension",
    "bank-front-fact-reconciliation", "bank-front-kyc-gap-check",
    "bank-front-product-recommendation", "bank-front-report-assembler",
    "bank-front-supply-chain-graph",
]


def safe_extract(zip_path: Path, target: Path) -> list[Path]:
    """安全解压：防路径穿越（.. / 绝对路径），仅允许常规文件。"""
    with zipfile.ZipFile(zip_path) as zf:
        for member in zf.infolist():
            name = member.filename
            if name.startswith("/") or ".." in Path(name).parts:
                raise ValueError(f"非法压缩条目: {name!r}")
        zf.extractall(target)
    return sorted(p for p in target.rglob("*") if p.is_file())


def build_records(task_files: list[Path]) -> list[dict]:
    """7 个任务 JSON → 扁平记录（注入 customerId，主键供规范化）。"""
    tasks = []
    for f in task_files:
        d = json.loads(f.read_text(encoding="utf-8"))
        if not isinstance(d, dict) or "taskId" not in d:
            raise ValueError(f"非任务结构: {f.name}")
        tasks.append(d)
    tasks.sort(key=lambda t: t.get("executionOrder", 99))
    # customerId 取自 TASK-FRONT-001 输出（客户编号），作为全批主键
    first = tasks[0]
    customer_id = ((first.get("output") or {}).get("客户编号")
                   or first.get("customerId"))
    if not customer_id:
        raise ValueError("无法从 TASK-FRONT-001 解析 customerId")
    records = []
    for t in tasks:
        records.append({
            "customerId": customer_id,
            "taskId": t.get("taskId", ""),
            "taskName": t.get("taskName", ""),
            "executionOrder": t.get("executionOrder", 0),
            "outputKey": t.get("outputKey", ""),
            "dependsOn": t.get("dependsOn", []),
            "skillName": (t.get("skillLoad") or {}).get("skillName", ""),
            "payload": t,
        })
    return records


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace", "-w", required=True)
    ap.add_argument("--zip", required=True, help="袁阳 assemblyMaterials.zip 路径")
    args = ap.parse_args()

    ws = Path(args.workspace).resolve()
    zip_path = Path(args.zip).resolve()
    if not zip_path.is_file():
        raise SystemExit(f"zip 不存在: {zip_path}")

    print(f"== 迁移开始：{zip_path.name} → {ws}（domain={DOMAIN}）==")
    ing = Ingestor(ws)
    proc = DataProcessor(ws)
    writer = WorkspaceWriter(ws)

    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        files = safe_extract(zip_path, td_path / "x")
        task_files = [f for f in files if f.suffix == ".json" and "TASK-FRONT" in f.name]
        task_files.sort()
        if len(task_files) != 7:
            print(f"  警告：识别到 {len(task_files)} 个任务文件（预期 7）")
        print(f"  [EXTRACT] {len(files)} 个文件解压（{len(task_files)} 个 TASK-FRONT JSON）")

        # 派生记录文件（role=DATA，供规范化）
        records = build_records(task_files)
        rec_path = td_path / "assembly_materials_records.json"
        rec_path.write_text(json.dumps(records, ensure_ascii=False, indent=1),
                            encoding="utf-8")

        # 原始任务 JSON 按 ID 命名规范重命名（TASK-FRONT-00X.json），
        # 任务名/中文原名保留在内容与记录文件中（MANIFEST.source_uri 指向 zip 可溯源）
        norm_tasks: list[Path] = []
        for f in task_files:
            m = __import__("re").search(r"(TASK-FRONT-\d+)", f.name)
            norm = td_path / f"{m.group(1) if m else f.stem}.json"
            norm.write_bytes(f.read_bytes())
            norm_tasks.append(norm)

        # 1) Raw 接入：原始任务 JSON 保留原文（REFERENCE）+ 记录文件（DATA）
        roles = {f.name: "REFERENCE" for f in norm_tasks}
        roles[rec_path.name] = "DATA"
        r = ing.ingest(DOMAIN, norm_tasks + [rec_path], IDEM_KEY,
                       source_system="skill_package",
                       source_uri=str(zip_path), roles=roles)
        print(f"  [RAW] batch={r.batch_id}（{len(r.files)} 文件，7 REFERENCE + 1 DATA）")

        # 2) Work 规范化（JSON → Parquet，主键 taskId——每任务一条记录，customerId 为属性列）
        pr = proc.process(DOMAIN, r.batch_id, DATASET, key_field="taskId")
        if pr.normalized_rel:
            print(f"  [WORK] {DATASET} → {pr.normalized_rel}（输入 {pr.input_count} / "
                  f"通过 {pr.passed_count} / 拒绝 {pr.rejected_count}）")
        else:
            print(f"  [WORK] 无通过记录（input={pr.input_count} "
                  f"rejected={pr.rejected_count}），中止投影")
            return

    # 3) Serve 数据投影（既有 7 数据集 + 新数据集；原子替换 + CURRENT 指针）
    print("\n== 构建 Serve 数据投影 ==")
    version = _next_service_version(ws, SERVICE_ID)
    tmp = f"04_serve/{SERVICE_ID}/.tmp-{version}"
    final = f"04_serve/{SERVICE_ID}/version={version}"
    files_meta: list[dict] = []
    runs = sorted((ws / "02_work" / DOMAIN).glob("run=*"), reverse=True)
    for ds in EXISTING_DATASETS + [DATASET]:
        src = None
        for run in runs:
            cand = run / "normalized" / f"{ds}.parquet"
            if cand.is_file():
                src = cand
                break
        if not src:
            print(f"  跳过缺失数据集: {ds}")
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
    _write_service_current(SERVICE_ID, version, writer, ws)
    print(f"  [SERVE] {SERVICE_ID} version={version}：{len(files_meta)} 个数据集")

    # 4) 工作区一致性检查
    print("\n== 工作区一致性 ==")
    from dkws.domain import workspace as ws_mod

    findings = ws_mod.check_workspace(ws, mode="full")
    blockers = [f for f in findings if f.level in ("BLOCKER", "MAJOR")]
    print(f"  校验: {'PASS' if not blockers else 'FAIL'}（发现 {len(findings)} 项）")
    for f in findings:
        print(f"    [{f.level}] {f.code} {f.message}")
    print(f"\n== 迁移完成：batch={r.batch_id}、run={pr.run_id}、"
          f"投影 version={version}（{len(files_meta)} 数据集）==")


# ---------------- 投影辅助（与 migrate_bank_front_data.py 同构） ----------------

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
        "builder_id": "assembly_materials_migrator",
        "builder_version": "1.0.0",
        "configuration_hash": hashing.sha256_hex(json.dumps(files_meta, sort_keys=True)),
        "files": files_meta,
        "logical_hashes": [],
        "built_at": timeutil.ts_utc(now),
        "verification_status": "VERIFIED",
        "status": "ACTIVE",
        "version": "1.0",
    }
    return markdown.render_contract_md(
        fm, "# 投影记录\n\nbank-front 装配材料（袁阳 assemblyMaterials.zip）示例数据投影。\n")


def _write_service_current(service_id: str, version: str, writer, ws: Path) -> None:
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
        "reason": "装配材料示例数据迁移投影",
        "status": "ACTIVE",
        "version": "1.0",
    }
    body = ("# 当前活动版本\n\n## 切换说明\n\n当前数据投影版本 " + version
            + "（含 assembly_materials 装配材料）。\n\n## 回滚说明\n\n回滚仅切换指针。\n")
    text = markdown.render_contract_md(fm, body)
    validate_contract(text, specs.CURRENT_SPEC,
                      path=f"04_serve/{service_id}/CURRENT.md").raise_if_invalid()
    writer.write_text(f"04_serve/{service_id}/CURRENT.md", text)


if __name__ == "__main__":
    main()
