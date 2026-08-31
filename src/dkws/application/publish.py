"""权威发布、Release 与 Current 指针（FR-PUB-001~005、规格 §11.3/11.8、§9.16/9.17）。

发布流程（§11.8）：
1. 解析待发布资产闭包（APPROVED 候选或显式对象）；
2. 运行 G3 门禁（审核决定、证据/引用闭包、冲突、Schema 复查）；
3. 写入临时 Core 版本目录（03_core/<domain>/.tmp-<version>/）；
4. 生成 RELEASE.md（资产清单含路径/Schema/ID/版本/SHA-256）；
5. 重读并全量验证临时版本；
6. 原子提交 Core 版本目录；
7. 原子更新 Core CURRENT.md（失败保留旧指针）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from ..domain import hashing, ids, timeutil
from ..domain.contracts import specs
from ..domain.contracts.base import validate_contract
from ..domain.errors import QualityGateError, UsageError
from ..infrastructure import locks as locks_mod, markdown
from ..infrastructure.fs import WorkspaceWriter
from . import validation as val_mod
from .jobs import JobController

_KIND_DIRS = {
    "entity/v1": "entities",
    "relation/v1": "relations",
    "statement/v1": "statements",
    "rule/v1": "rules",
    "document_segment/v1": "segments",
    "document/v1": "documents",
}
_CANDIDATE_DIRS = {
    "entity/v1": "entities",
    "relation/v1": "relations",
    "statement/v1": "statements",
    "rule/v1": "rules",
}


@dataclass
class PublishResult:
    release_id: str
    release_version: str
    job_id: str
    asset_count: int
    core_dir: str
    plan: list[str] = field(default_factory=list)


class Publisher:
    def __init__(self, workspace: Path, *, owner: str = "svc_publisher",
                 dry_run: bool = False):
        self.ws = Path(workspace)
        self.owner = owner
        self.dry_run = dry_run

    def publish(self, domain: str, *, run_id: str | None = None,
                release_version: str | None = None,
                objects: list[str] | None = None) -> PublishResult:
        ids.validate_domain(domain)
        writer = WorkspaceWriter(self.ws, dry_run=self.dry_run)
        version = release_version or self._next_version(domain)
        ids.validate_release_version(version)
        tmp_rel = f"03_core/{domain}/.tmp-{version}"
        final_rel = f"03_core/{domain}/version={version}"

        if self.dry_run:
            return PublishResult(release_id="", release_version=version, job_id="",
                                 asset_count=0, core_dir=final_rel,
                                 plan=[f"{final_rel}/RELEASE.md",
                                       f"03_core/{domain}/CURRENT.md"])

        with locks_mod.WorkspaceLock(self.ws, f"domain:{domain}",
                                     job_id=f"JOB-PUB-{timeutil.ts_utc()[:19]}",
                                     owner=self.owner):
            job = JobController(self.ws, writer, job_type="PUBLISH",
                                requested_by=self.owner,
                                idempotency_key=f"{domain}:{version}:publish:{run_id or 'auto'}",
                                component="publisher")
            if job.noop:
                return PublishResult(release_id="", release_version=version,
                                     job_id=job.job_id, asset_count=0,
                                     core_dir=final_rel)
            job.start()
            job.logger.info("PUBLISH_START", "发布开始", domain=domain,
                            version=version)
            try:
                # 1. 收集 APPROVED 资产
                assets = self._collect_approved(domain, run_id, objects)
                if not assets:
                    raise QualityGateError(
                        f"没有 APPROVED 资产可发布（run={run_id or 'auto'}）",
                        error_code="UNAPPROVED_ASSET")
                job.update(progress=20, log_code="PUBLISH_COLLECT",
                           log_message=f"收集 APPROVED 资产 {len(assets)} 个")

                # 2. G3 门禁
                gate = self._run_g3_gate(assets, writer)
                if not gate["pass"]:
                    raise QualityGateError(
                        "G3 门禁失败: " + "; ".join(gate["errors"][:8]))
                job.update(progress=40, log_code="PUBLISH_G3",
                           log_message="G3 门禁通过")

                # 3-4. 临时版本目录 + RELEASE.md
                manifest = self._stage_core(assets, tmp_rel, writer)
                release_text = self._render_release(
                    domain, version, manifest, gate["decision_ids"], writer)
                validate_contract(release_text, specs.RELEASE_SPEC,
                                  path=f"{tmp_rel}/RELEASE.md").raise_if_invalid()
                writer.write_text(f"{tmp_rel}/RELEASE.md", release_text)
                job.update(progress=70, log_code="PUBLISH_STAGE",
                           log_message=f"暂存 {len(manifest)} 项资产")

                # 5. 重读全量验证临时版本
                verify_errors = self._verify_staged(tmp_rel, writer)
                if verify_errors:
                    raise QualityGateError("发布验证失败: " + "; ".join(verify_errors[:8]))

                # 6. 原子提交
                writer.atomic_replace_dir(tmp_rel, final_rel)
                # 7. CURRENT.md（先新版本后指针）
                self._write_current(domain, version, writer, job)
                out_refs = [{"path": f"{final_rel}/RELEASE.md", "version": version,
                             "content_hash": hashing.sha256_file(
                                 writer.resolve(f"{final_rel}/RELEASE.md"))}]
                job.finish(output_refs=out_refs, input_count=len(assets),
                           output_count=len(assets) + 1,
                           quality_summary={"gates_passed": ["G3"]})
                return PublishResult(
                    release_id=manifest[0]["asset_id"], release_version=version,
                    job_id=job.job_id, asset_count=len(assets),
                    core_dir=final_rel)
            except Exception as exc:
                job.fail("PUBLISH_FAILED", str(exc))
                raise

    # ---------------- 收集与门禁 ----------------

    def _collect_approved(self, domain, run_id, objects) -> list[dict]:
        """从候选目录收集 APPROVED 资产（或显式对象）。"""
        assets: list[dict] = []
        if objects:
            for obj in objects:
                rel = self._resolve_asset_rel(domain, run_id, obj)
                if not rel:
                    raise UsageError(f"找不到候选对象: {obj}")
                assets.append(self._read_asset(rel))
        else:
            run_id = run_id or self._latest_run(domain)
            if not run_id:
                return []
            cand_base = self.ws / "02_work" / domain / f"run={run_id}" / "candidates"
            if not cand_base.is_dir():
                return []
            for subdir in ("entities", "relations", "statements", "rules"):
                for f in sorted((cand_base / subdir).glob("*.md")):
                    rel = f"02_work/{domain}/run={run_id}/candidates/{subdir}/{f.name}"
                    assets.append(self._read_asset(rel))
        approved = [a for a in assets if a["fm"].get("validation_status") == "APPROVED"]
        # 引用闭包：知识候选引用的片段与文档（§11.8）
        approved = self._collect_evidence_closure(domain, run_id, approved)
        return approved

    def _collect_evidence_closure(self, domain, run_id, approved) -> list[dict]:
        """收集被引用的 segment/document 证据资产（来源验证，无需审核决定）。"""
        if not approved:
            return approved
        run_id = run_id or self._latest_run(domain)
        if not run_id:
            return approved
        referenced: set[str] = set()
        for a in approved:
            fm = a["fm"]
            for sid in fm.get("source_ids", []) or []:
                if str(sid).startswith("SEG-"):
                    referenced.add(str(sid))
            if fm.get("source_segment_id"):
                referenced.add(str(fm["source_segment_id"]))
        existing = {a["fm"].get("segment_id") for a in approved
                    if a["schema"] == "document_segment/v1"}
        seg_base = self.ws / "02_work" / domain / f"run={run_id}" / "segments"
        doc_ids: set[str] = set()
        for sid in referenced:
            if sid in existing:
                continue
            hit = list(seg_base.rglob(f"{sid}.md")) if seg_base.is_dir() else []
            if hit:
                rel = hit[0].relative_to(self.ws).as_posix()
                approved.append(self._read_asset(rel))
                existing.add(sid)
                fm = approved[-1]["fm"]
                doc_ids.add(fm.get("document_id", ""))
        # 文档登记（DOCUMENT.md）
        for doc_id in doc_ids:
            if not doc_id:
                continue
            doc_rel = (f"02_work/{domain}/run={run_id}/documents/{doc_id}/DOCUMENT.md")
            if (self.ws / doc_rel).is_file():
                approved.append(self._read_asset(doc_rel))
        return approved

    def _read_asset(self, rel: str) -> dict:
        text = (self.ws / rel).read_text(encoding="utf-8")
        parsed = markdown.parse_contract_md(text, path=rel)
        if not parsed.ok:
            raise QualityGateError(f"资产合同失败: {rel}: {parsed.errors[:3]}")
        schema = parsed.front_matter.get("schema")
        spec = specs.get_spec(schema)
        result = validate_contract(text, spec, path=rel)
        if not result.ok:
            raise QualityGateError(f"资产合同失败: {rel}: {result.errors[:3]}")
        return {"rel": rel, "fm": result.front_matter, "body": result.body,
                "schema": schema, "source_text": text}

    def _run_g3_gate(self, assets, writer) -> dict:
        errors: list[str] = []
        ents: dict = {}
        rels: list[dict] = []
        stmts: list[dict] = []
        knowledge_schemas = {"entity/v1", "relation/v1", "statement/v1", "rule/v1"}

        # 审核决定证据（§9.16）：仅对知识类资产强制；证据类（片段/文档）验证来源
        decisions = self._load_decisions()
        approved_refs = {d for d in decisions}
        knowledge_assets = [a for a in assets if a["schema"] in knowledge_schemas]
        for a in knowledge_assets:
            asset_id = a["fm"].get(ids_for(a["schema"]))
            if asset_id and asset_id not in approved_refs:
                errors.append(f"资产缺少 APPROVE 审核决定: {asset_id}")
        if knowledge_assets and not decisions:
            errors.append("没有可引用的审核决定")

        for a in assets:
            schema, fm = a["schema"], a["fm"]
            if schema == "entity/v1":
                ents[fm["entity_id"]] = fm
            elif schema == "relation/v1":
                rels.append(fm)
            elif schema == "statement/v1":
                stmts.append(fm)
        # 引用/悬空/冲突检查
        for f in val_mod.check_dangling_references(ents, rels, stmts):
            errors.append(f.message)
        for f in val_mod.check_duplicate_entities(ents):
            errors.append(f.message)
        for f in val_mod.check_statement_conflicts(stmts):
            errors.append(f.message)
        return {"pass": not errors, "errors": errors,
                "decision_ids": sorted(approved_refs)[:20]}

    def _load_decisions(self) -> set[str]:
        dec_dir = self.ws / "90_control" / "decisions"
        refs: set[str] = set()
        if not dec_dir.is_dir():
            return refs
        for f in dec_dir.glob("*.md"):
            text = f.read_text(encoding="utf-8")
            rv = validate_contract(text, specs.REVIEW_DECISION_SPEC, path=f.name)
            if rv.ok and rv.front_matter.get("decision") == "APPROVE":
                for obj in rv.front_matter.get("object_refs", []):
                    refs.add(obj.split("/")[-1].removesuffix(".md"))
        return refs

    # ---------------- 暂存与验证 ----------------

    def _stage_core(self, assets, tmp_rel, writer) -> list[dict]:
        manifest: list[dict] = []
        for a in assets:
            kind_dir = _KIND_DIRS.get(a["schema"])
            if not kind_dir:
                continue
            asset_id = a["fm"].get(ids_for(a["schema"]))
            rel = f"{tmp_rel}/{kind_dir}/{asset_id}.md"
            writer.write_text(rel, a["source_text"])
            manifest.append({
                "path": f"{kind_dir}/{asset_id}.md",
                "schema": a["schema"],
                "asset_id": asset_id,
                "asset_version": a["fm"].get("version", "1.0"),
                "sha256": hashing.md_semantic_sha256(a["source_text"]),
            })
        return manifest

    def _render_release(self, domain, version, manifest, decision_ids, writer) -> str:
        now = timeutil.now_utc()
        previous = self._previous_version(domain)
        fm = {
            "schema": "release/v1",
            "release_id": f"REL-{now.strftime('%Y%m%d')}-{version.split('.')[-1]}",
            "domain": domain,
            "release_version": version,
            "previous_version": previous,
            "asset_manifest": manifest,
            "quality_gate_results": [{"gate": "G3", "result": "PASS"}],
            "approval_decision_ids": decision_ids,
            "released_by": self.owner,
            "released_at": timeutil.ts_utc(now),
            "status": "PUBLISHED",
            "version": "1.0",
        }
        body = "# 发布记录\n\n"
        return markdown.render_contract_md(fm, body)

    def _verify_staged(self, tmp_rel, writer) -> list[str]:
        errors: list[str] = []
        for f in sorted((self.ws / tmp_rel).rglob("*.md")):
            if f.name == "RELEASE.md":
                continue
            rel = f"{tmp_rel}/{f.relative_to(self.ws / tmp_rel).as_posix()}"
            text = f.read_text(encoding="utf-8")
            rv = validate_contract(text, specs.get_spec(
                markdown.parse_contract_md(text).front_matter.get("schema", "")),
                path=rel)
            if not rv.ok:
                errors.append(f"{f.name}: {rv.errors[:2]}")
        return errors

    def _write_current(self, domain, version, writer, job) -> None:
        release_id = f"REL-{version}"
        # 清单哈希：读取刚发布的 RELEASE.md
        release_rel = f"03_core/{domain}/version={version}/RELEASE.md"
        manifest_sha = hashing.sha256_file(writer.resolve(release_rel))
        fm = {
            "schema": "current_pointer/v1",
            "scope_type": "CORE_DOMAIN",
            "scope_id": domain,
            "target_version": version,
            "target_release_id": release_id,
            "target_manifest_sha256": manifest_sha,
            "switched_by": self.owner,
            "switched_at": timeutil.ts_utc(),
            "reason": f"发布 {version}（job {job.job_id}）",
            "status": "ACTIVE",
            "version": "1.0",
        }
        body = ("# 当前活动版本\n\n"
                f"## 切换说明\n\n当前指向版本 {version}。\n\n"
                "## 回滚说明\n\n回滚仅切换指针，不删除任何版本。\n")
        text = markdown.render_contract_md(fm, body)
        validate_contract(text, specs.CURRENT_SPEC,
                          path=f"03_core/{domain}/CURRENT.md").raise_if_invalid()
        writer.write_text(f"03_core/{domain}/CURRENT.md", text)

    # ---------------- 辅助 ----------------

    def _next_version(self, domain: str) -> str:
        base = self.ws / "03_core" / domain
        versions: list[str] = []
        if base.is_dir():
            for p in base.glob("version=*"):
                versions.append(p.name.removeprefix("version="))
        if not versions:
            return timeutil.now_utc().strftime("%Y.%m.%d") + ".1"
        latest = max(versions)
        return ids.next_release_version(latest)

    def _previous_version(self, domain: str) -> str | None:
        cur = self.ws / "03_core" / domain / "CURRENT.md"
        if not cur.is_file():
            return None
        m = re.search(r"^target_version:\s*\"?([^\n\" ]+)", cur.read_text(encoding="utf-8"), re.M)
        return m.group(1) if m else None

    def _latest_run(self, domain: str) -> str | None:
        base = self.ws / "02_work" / domain
        if not base.is_dir():
            return None
        runs = sorted((p.name for p in base.glob("run=*")), reverse=True)
        return runs[0].removeprefix("run=") if runs else None

    def _resolve_asset_rel(self, domain, run_id, obj) -> str | None:
        run_id = run_id or self._latest_run(domain)
        if not run_id:
            return None
        name = obj.split("/")[-1].removesuffix(".md")
        for subdir in ("entities", "relations", "statements", "rules"):
            rel = f"02_work/{domain}/run={run_id}/candidates/{subdir}/{name}.md"
            if (self.ws / rel).is_file():
                return rel
        return None


def ids_for(schema: str) -> str:
    return {
        "entity/v1": "entity_id",
        "relation/v1": "relation_id",
        "statement/v1": "statement_id",
        "rule/v1": "rule_id",
        "document_segment/v1": "segment_id",
        "document/v1": "document_id",
    }.get(schema, "id")
