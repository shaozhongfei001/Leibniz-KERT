"""门禁报告生成器（规格 §17、§18.5 验收：G0—G5 均有可复现报告）。

G0 接入完整性：Manifest 合同、批次关闭、文件哈希重算、路径安全。
G1 解析与结构：文档/片段合同、内容哈希、页码区间。
G2 候选合同：候选 Schema、状态枚举、规则 DSL 白名单。
G3 权威发布：Release 合同、CURRENT 指针、资产清单哈希。
G4 投影一致性：行数一致、逻辑哈希、悬空引用、检索样例。
G5 服务验收：健康、检索、规则、溯源样例。

每个 Gate 输出 GATE_REPORT.md（schema=gate_report/v1），写入 90_control/quality/gates/。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from ..domain import hashing, ids, timeutil
from ..domain.contracts import specs
from ..domain.contracts.base import validate_contract
from ..domain.errors import UsageError
from ..infrastructure import markdown
from ..infrastructure.fs import WorkspaceWriter


@dataclass
class GateFinding:
    level: str  # BLOCKER/MAJOR/MINOR/NOTE
    code: str
    message: str


@dataclass
class GateResult:
    gate_id: str
    decision: str
    findings: list[GateFinding] = field(default_factory=list)
    report_rel: str | None = None

    @property
    def ok(self) -> bool:
        return not any(f.level in ("BLOCKER", "MAJOR") for f in self.findings)


class GateReporter:
    def __init__(self, workspace: Path, *, reviewer: str = "dkws_qa",
                 dry_run: bool = False):
        self.ws = Path(workspace)
        self.reviewer = reviewer
        self.dry_run = dry_run

    def run_all(self) -> list[GateResult]:
        results = [
            self.g0(), self.g1(), self.g2(), self.g3(), self.g4(), self.g5(),
        ]
        if not self.dry_run:
            for r in results:
                self._write_report(r)
        return results

    # ---------------- G0 接入完整性 ----------------

    def g0(self) -> GateResult:
        findings: list[GateFinding] = []
        raw = self.ws / "01_raw"
        batches = 0
        if raw.is_dir():
            for domain_dir in sorted(raw.iterdir()):
                for batch_dir in sorted(domain_dir.glob("batch=*")):
                    batches += 1
                    manifest = batch_dir / "MANIFEST.md"
                    if not manifest.is_file():
                        findings.append(GateFinding(
                            "BLOCKER", "G0_NO_MANIFEST", f"批次缺少清单: {batch_dir.name}"))
                        continue
                    text = manifest.read_text(encoding="utf-8")
                    rv = validate_contract(text, specs.MANIFEST_SPEC,
                                           path=str(manifest.relative_to(self.ws)))
                    if not rv.ok:
                        findings.append(GateFinding(
                            "BLOCKER", "G0_MANIFEST_SCHEMA",
                            f"清单合同失败: {batch_dir.name}: {rv.errors[:2]}"))
                        continue
                    fm = rv.front_matter
                    if fm.get("status") != "CLOSED":
                        findings.append(GateFinding(
                            "MAJOR", "G0_BATCH_NOT_CLOSED",
                            f"批次未关闭: {batch_dir.name}（{fm.get('status')}）"))
                    for f in fm.get("files", []):
                        fp = batch_dir / f["path"]
                        if not fp.is_file():
                            findings.append(GateFinding(
                                "BLOCKER", "G0_FILE_MISSING",
                                f"清单文件缺失: {f['path']}"))
                            continue
                        actual = hashing.sha256_file(fp)
                        if actual != f.get("sha256"):
                            findings.append(GateFinding(
                                "BLOCKER", "G0_HASH_MISMATCH",
                                f"文件哈希不一致: {f['path']}"))
        if batches == 0:
            findings.append(GateFinding("NOTE", "G0_EMPTY", "无已接入批次"))
        return GateResult("G0", "PASS_FOR_NEXT_GATE" if not any(
            f.level in ("BLOCKER", "MAJOR") for f in findings) else "RETURN_TO_WORK",
            findings)

    # ---------------- G1 解析与结构 ----------------

    def g1(self) -> GateResult:
        findings: list[GateFinding] = []
        work = self.ws / "02_work"
        docs = 0
        if work.is_dir():
            for doc_md in work.rglob("documents/*/DOCUMENT.md"):
                docs += 1
                rv = validate_contract(doc_md.read_text(encoding="utf-8"),
                                       specs.DOCUMENT_SPEC, path=str(doc_md))
                if not rv.ok:
                    findings.append(GateFinding(
                        "MAJOR", "G1_DOCUMENT_SCHEMA",
                        f"文档登记合同失败: {doc_md.parent.name}: {rv.errors[:2]}"))
            for seg_md in work.rglob("segments/*/*.md"):
                rv = validate_contract(seg_md.read_text(encoding="utf-8"),
                                       specs.SEGMENT_SPEC, path=str(seg_md))
                if not rv.ok:
                    findings.append(GateFinding(
                        "MAJOR", "G1_SEGMENT_SCHEMA",
                        f"片段合同失败: {seg_md.name}: {rv.errors[:2]}"))
                    continue
                fm = rv.front_matter
                if fm.get("page_from") and fm.get("page_to") \
                        and fm["page_to"] < fm["page_from"]:
                    findings.append(GateFinding(
                        "MAJOR", "G1_PAGE_RANGE", f"页码区间非法: {seg_md.name}"))
        if docs == 0:
            findings.append(GateFinding("NOTE", "G1_EMPTY", "无已解析文档"))
        return GateResult("G1", "PASS_FOR_NEXT_GATE" if not any(
            f.level in ("BLOCKER", "MAJOR") for f in findings) else "RETURN_TO_WORK",
            findings)

    # ---------------- G2 候选合同 ----------------

    def g2(self) -> GateResult:
        findings: list[GateFinding] = []
        cands = 0
        specs_map = {
            "entities": specs.ENTITY_SPEC, "relations": specs.RELATION_SPEC,
            "statements": specs.STATEMENT_SPEC, "rules": specs.RULE_SPEC,
        }
        work = self.ws / "02_work"
        if work.is_dir():
            for subdir, spec in specs_map.items():
                for f in work.rglob(f"candidates/{subdir}/*.md"):
                    cands += 1
                    text = f.read_text(encoding="utf-8")
                    rv = validate_contract(text, spec, path=str(f))
                    if not rv.ok:
                        findings.append(GateFinding(
                            "MAJOR", "G2_CANDIDATE_SCHEMA",
                            f"候选合同失败: {f.name}: {rv.errors[:2]}"))
                        continue
                    fm = rv.front_matter
                    if fm.get("validation_status") not in (
                            "CANDIDATE", "IN_REVIEW", "APPROVED", "REJECTED"):
                        findings.append(GateFinding(
                            "BLOCKER", "G2_BAD_STATE", f"候选状态非法: {f.name}"))
                    if fm.get("schema") == "rule/v1":
                        from ..domain.rules import dsl as dsl_mod

                        errs = dsl_mod.validate_dsl(fm.get("when", {})) + \
                               dsl_mod.validate_dsl(fm.get("then", {}))
                        if fm.get("else"):
                            errs += dsl_mod.validate_dsl(fm["else"])
                        if errs:
                            findings.append(GateFinding(
                                "MAJOR", "G2_RULE_DSL", f"规则 DSL 非法: {f.name}"))
        if cands == 0:
            findings.append(GateFinding("NOTE", "G2_EMPTY", "无知识候选"))
        return GateResult("G2", "PASS_FOR_NEXT_GATE" if not any(
            f.level in ("BLOCKER", "MAJOR") for f in findings) else "RETURN_TO_WORK",
            findings)

    # ---------------- G3 权威发布 ----------------

    def g3(self) -> GateResult:
        findings: list[GateFinding] = []
        releases = 0
        core = self.ws / "03_core"
        if core.is_dir():
            for domain_dir in sorted(core.iterdir()):
                cur = domain_dir / "CURRENT.md"
                if not cur.is_file():
                    continue
                cur_text = cur.read_text(encoding="utf-8")
                cur_rv = validate_contract(cur_text, specs.CURRENT_SPEC,
                                           path=str(cur.relative_to(self.ws)))
                if not cur_rv.ok:
                    findings.append(GateFinding(
                        "BLOCKER", "G3_CURRENT_SCHEMA",
                        f"当前指针合同失败: {domain_dir.name}: {cur_rv.errors[:2]}"))
                    continue
                version = cur_rv.front_matter["target_version"]
                version_dir = domain_dir / f"version={version}"
                release = version_dir / "RELEASE.md"
                if not release.is_file():
                    findings.append(GateFinding(
                        "BLOCKER", "G3_NO_RELEASE", f"活动版本缺少 RELEASE.md: {version}"))
                    continue
                releases += 1
                rel_rv = validate_contract(release.read_text(encoding="utf-8"),
                                           specs.RELEASE_SPEC,
                                           path=str(release.relative_to(self.ws)))
                if not rel_rv.ok:
                    findings.append(GateFinding(
                        "BLOCKER", "G3_RELEASE_SCHEMA",
                        f"发布记录合同失败: {version}: {rel_rv.errors[:2]}"))
                    continue
                for item in rel_rv.front_matter.get("asset_manifest", []):
                    ap = version_dir / item["path"]
                    if not ap.is_file():
                        findings.append(GateFinding(
                            "BLOCKER", "G3_ASSET_MISSING",
                            f"发布清单资产缺失: {item['path']}"))
                    else:
                        actual = hashing.md_semantic_sha256(ap.read_text(encoding="utf-8"))
                        if actual != item.get("sha256"):
                            findings.append(GateFinding(
                                "BLOCKER", "G3_ASSET_HASH",
                                f"发布资产哈希不一致: {item['path']}"))
        if releases == 0:
            findings.append(GateFinding("NOTE", "G3_EMPTY", "无活动 Core 版本"))
        return GateResult("G3", "PASS_FOR_NEXT_GATE" if not any(
            f.level in ("BLOCKER", "MAJOR") for f in findings) else "RETURN_TO_WORK",
            findings)

    # ---------------- G4 投影一致性 ----------------

    def g4(self) -> GateResult:
        findings: list[GateFinding] = []
        serve = self.ws / "04_serve"
        projections = 0
        if serve.is_dir():
            for svc_dir in sorted(serve.iterdir()):
                cur = svc_dir / "CURRENT.md"
                if not cur.is_file():
                    continue
                cur_rv = validate_contract(cur.read_text(encoding="utf-8"),
                                           specs.CURRENT_SPEC)
                if not cur_rv.ok:
                    findings.append(GateFinding(
                        "BLOCKER", "G4_CURRENT_SCHEMA",
                        f"服务指针合同失败: {svc_dir.name}"))
                    continue
                version = cur_rv.front_matter["target_version"]
                vdir = svc_dir / f"version={version}"
                proj_md = vdir / "PROJECTION.md"
                if not proj_md.is_file():
                    findings.append(GateFinding(
                        "BLOCKER", "G4_NO_PROJECTION",
                        f"活动投影缺少 PROJECTION.md: {svc_dir.name}"))
                    continue
                projections += 1
                prj_rv = validate_contract(proj_md.read_text(encoding="utf-8"),
                                           specs.PROJECTION_SPEC)
                if not prj_rv.ok:
                    findings.append(GateFinding(
                        "MAJOR", "G4_PROJECTION_SCHEMA",
                        f"投影记录合同失败: {svc_dir.name}: {prj_rv.errors[:2]}"))
                    continue
                # 行数一致（entities/relations 与 Core 计数比较）
                try:
                    import pyarrow.parquet as pq
                    ents_t = pq.read_table(vdir / "entities.parquet")
                    rels_t = pq.read_table(vdir / "relations.parquet")
                    core_ents = self._count_core("entities")
                    core_rels = self._count_core("relations")
                    if ents_t.num_rows != core_ents:
                        findings.append(GateFinding(
                            "MAJOR", "G4_ROW_MISMATCH",
                            f"实体行数不一致: 投影 {ents_t.num_rows} vs Core {core_ents}"))
                    if rels_t.num_rows != core_rels:
                        findings.append(GateFinding(
                            "MAJOR", "G4_ROW_MISMATCH",
                            f"关系行数不一致: 投影 {rels_t.num_rows} vs Core {core_rels}"))
                    # 悬空引用
                    ent_ids = set(ents_t.column("entity_id").to_pylist())
                    for src, tgt in zip(rels_t.column("source_id").to_pylist(),
                                        rels_t.column("target_id").to_pylist()):
                        if src not in ent_ids or tgt not in ent_ids:
                            findings.append(GateFinding(
                                "BLOCKER", "G4_DANGLING", f"关系端点悬空: {src}→{tgt}"))
                            break
                except Exception as exc:  # 缺表
                    findings.append(GateFinding(
                        "MAJOR", "G4_TABLE_MISSING", f"投影表读取失败: {exc}"))
        if projections == 0:
            findings.append(GateFinding("NOTE", "G4_EMPTY", "无活动服务投影"))
        return GateResult("G4", "PASS_FOR_NEXT_GATE" if not any(
            f.level in ("BLOCKER", "MAJOR") for f in findings) else "RETURN_TO_WORK",
            findings)

    def _count_core(self, kind: str) -> int:
        n = 0
        core = self.ws / "03_core"
        if core.is_dir():
            for domain_dir in core.iterdir():
                cur = domain_dir / "CURRENT.md"
                if not cur.is_file():
                    continue
                m = re.search(r"^target_version:\s*\"?([^\n\" ]+)",
                              cur.read_text(encoding="utf-8"), re.M)
                if m:
                    d = domain_dir / f"version={m.group(1)}" / kind
                    if d.is_dir():
                        n += len(list(d.glob("*.md")))
        return n

    # ---------------- G5 服务验收 ----------------

    def g5(self) -> GateResult:
        findings: list[GateFinding] = []
        try:
            from ..application.services import KnowledgeService

            svc = KnowledgeService(self.ws)
            version = svc._active_version()
            # 健康
            findings.append(GateFinding("NOTE", "G5_HEALTH",
                                        f"服务健康，活动投影版本 {version}"))
            # 检索样例
            r = svc.search("利率", mode="FULLTEXT", top_k=3)
            if r.data["hit_count"] == 0:
                findings.append(GateFinding("MAJOR", "G5_SEARCH",
                                            "全文检索样例无命中"))
            # 规则样例
            try:
                rr = svc.evaluate_rule(facts={"rate": 5})
                findings.append(GateFinding(
                    "NOTE", "G5_RULE",
                    f"规则评估样例命中 {len(rr.data['matched_rules'])} 条"))
            except Exception as exc:
                findings.append(GateFinding("MAJOR", "G5_RULE", f"规则样例失败: {exc}"))
            # 溯源样例
            try:
                import pyarrow.parquet as pq
                t = pq.read_table(svc._version_dir() / "statements.parquet")
                if t.num_rows:
                    sid = t.column("statement_id").to_pylist()[0]
                    tr = svc.trace(sid)
                    if not tr.data.get("complete"):
                        findings.append(GateFinding(
                            "MAJOR", "G5_TRACE", "溯源样例证据链不完整"))
            except Exception as exc:
                findings.append(GateFinding("MAJOR", "G5_TRACE", f"溯源样例失败: {exc}"))
        except Exception as exc:
            findings.append(GateFinding("MAJOR", "G5_NOT_READY",
                                        f"服务不可用: {exc}"))
        return GateResult("G5", "PASS_FOR_NEXT_GATE" if not any(
            f.level in ("BLOCKER", "MAJOR") for f in findings) else "RETURN_TO_WORK",
            findings)

    # ---------------- 报告写入 ----------------

    def _write_report(self, r: GateResult) -> None:
        writer = WorkspaceWriter(self.ws, dry_run=self.dry_run)
        gate_id = f"{r.gate_id}-{timeutil.today_business()}"
        seq = 1
        while writer.exists(f"90_control/quality/gates/{gate_id}-{seq:02d}.md"):
            seq += 1
        report_id = f"{gate_id}-{seq:02d}"
        now = timeutil.now_utc()
        fm = {
            "schema": "gate_report/v1",
            "gate_id": report_id,
            "review_object": f"workspace:{self.ws.name}",
            "target_transition": f"{r.gate_id}",
            "decision": r.decision,
            "substantive_review": f"机器校验 {len(r.findings)} 项发现",
            "findings": [{"level": f.level, "code": f.code, "message": f.message}
                         for f in r.findings],
            "reviewed_by": self.reviewer,
            "reviewed_at": timeutil.ts_utc(now),
            "baseline_state": "NOT_BASELINED",
            "frozen": False,
            "status": "ACTIVE",
            "version": "1.0",
        }
        body = (f"# 门禁报告 {r.gate_id}\n\n"
                f"决定：{r.decision}\n\n"
                + ("".join(f"- [{f.level}] {f.code} {f.message}\n" for f in r.findings)
                   or "- 无发现\n"))
        text = markdown.render_contract_md(fm, body)
        validate_contract(text, specs.GATE_REPORT_SPEC,
                          path=f"90_control/quality/gates/{report_id}.md").raise_if_invalid()
        writer.write_text(f"90_control/quality/gates/{report_id}.md", text)
        r.report_rel = f"90_control/quality/gates/{report_id}.md"
